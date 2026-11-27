# SPDX-License-Identifier: Apache-2.0
"""MCP server over the installed audit tools.

Over stdio (JSON-RPC 2.0, one message per line), each MCP tool runs one installed audit tool
with --audit-json and returns its audit-result/1 object unchanged, after checking it with
suite_gate.envelope.validate. Nothing is computed or inferred here: an exit status of 1 is a
result (findings), not a failure. A tool that is missing, too old to print the format, or
prints an object that does not validate is a tool error, never a guess.
"""
import json
import os
import shutil
import subprocess

from . import __version__
from .envelope import validate

PROTOCOL_VERSION = "2025-06-18"

# Each audit tool's PyPI or release name and the first version with --audit-json.
MINIMUM = {
    "git-surface": "0.4.0", "trust-path": "0.8.1", "release-drift": "0.7.0",
    "git-overlap": "0.7.0", "pr-merge-audit": "2.3.0", "glassbox": "0.6.0",
}
INSTALL = {name: "pip install '%s>=%s'" % (name, v) for name, v in MINIMUM.items()}
INSTALL["glassbox"] = "brew install jacob-adm/tap/glassbox (or a GitHub release of 0.6.0 or later)"


class ToolError(Exception):
    """A call that cannot be answered with a valid audit result."""


# --- arguments --------------------------------------------------------------------------------

def _text(args, key, required=True):
    """A string argument that cannot be read as an option or hold a line break."""
    value = args.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value:
        raise ToolError("argument %s: a non-empty string is required" % key)
    if value.startswith("-"):
        raise ToolError("argument %s: must not start with '-'" % key)
    if any(ch in value for ch in "\n\r\t\0"):
        raise ToolError("argument %s: must not contain a TAB, line break or NUL" % key)
    return value


def _dir(args, key, required=True):
    """A directory argument that exists."""
    path = _text(args, key, required)
    if path is not None and not os.path.isdir(path):
        raise ToolError("argument %s: %s is not a directory" % (key, path))
    return path


def _file(args, key):
    """A file argument that exists."""
    path = _text(args, key)
    if not os.path.isfile(path):
        raise ToolError("argument %s: %s is not a file" % (key, path))
    return path


def _refs(args, key="refs"):
    """A non-empty list of refs."""
    refs = args.get(key)
    if not isinstance(refs, list) or not refs:
        raise ToolError("argument %s: a non-empty list of refs is required" % key)
    return [_text({key: r}, key) for r in refs]


def _pairs(args):
    """A non-empty list of [refA, refB] pairs."""
    pairs = args.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise ToolError("argument pairs: a non-empty list of [refA, refB] is required")
    out = []
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ToolError("argument pairs: each pair is a list of two refs")
        out.append([_text({"pairs": r}, "pairs") for r in pair])
    return out


# --- running a tool ---------------------------------------------------------------------------

class Runner:
    """Runs installed audit tools; TIMEOUT is seconds per run."""

    def __init__(self, timeout=600):
        self.timeout = timeout

    def exe(self, tool, command):
        """The path of COMMAND (a console script of TOOL), or a ToolError saying how to install it."""
        path = shutil.which(command)
        if path is None:
            raise ToolError("%s is not installed: %s" % (tool, INSTALL[tool]))
        return path

    def run(self, argv, stdin=b"", cwd=None):
        """(exit status, stdout, stderr) of one run, or a ToolError on a timeout."""
        try:
            proc = subprocess.run(argv, input=stdin, cwd=cwd, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            raise ToolError("%s did not finish within %d seconds" % (os.path.basename(argv[0]),
                                                                       self.timeout))
        except OSError as exc:
            raise ToolError("cannot run %s: %s" % (argv[0], exc))
        return proc.returncode, proc.stdout, proc.stderr

    def audit(self, tool, argv, stdin=b"", cwd=None):
        """Run TOOL with --audit-json in ARGV and return its checked audit result object."""
        code, out, err = self.run(argv, stdin, cwd)
        try:
            doc = json.loads(out.decode("utf-8"))
        except ValueError:
            doc = None
        if not isinstance(doc, dict):
            detail = err.decode("utf-8", "replace").strip().splitlines()
            raise ToolError("%s did not print an audit result (exit %d)%s; --audit-json needs %s %s "
                            "or later" % (tool, code, ": " + detail[-1] if detail else "", tool,
                                          MINIMUM[tool]))
        problems = validate(doc)
        if problems:
            raise ToolError("%s printed an object that is not a valid audit-result/1: %s"
                            % (tool, "; ".join(problems[:5])))
        if doc["tool"]["name"] != tool or doc["exit"] != code:
            raise ToolError("%s printed tool %r and exit %r but exited %d" % (
                tool, doc["tool"]["name"], doc["exit"], code))
        return doc

    def version(self, tool, command):
        """The installed version of TOOL, or None if it is not installed."""
        path = shutil.which(command)
        if path is None:
            return None
        if tool == "pr-merge-audit":
            # No --version flag: its audit object names the version, also on an error.
            _, out, _ = self.run([path, "report", "--audit-json", "--results", os.devnull])
            try:
                return json.loads(out.decode("utf-8"))["tool"]["version"]
            except (ValueError, KeyError, TypeError):
                return "unknown (older than %s)" % MINIMUM[tool]
        _, out, _ = self.run([path, "--version"])
        words = out.decode("utf-8", "replace").split()
        return words[-1] if words else "unknown"


# --- the tools --------------------------------------------------------------------------------

def _git_surface(r, args):
    repo, base, refs = _dir(args, "repo"), _text(args, "base"), _refs(args)
    exe = r.exe("git-surface", "git-surface")
    return r.audit("git-surface", [exe, "--audit-json", "--", base],
                   ("\n".join(refs) + "\n").encode(), cwd=repo)


def _git_overlap(r, args):
    repo, base, refs = _dir(args, "repo"), _text(args, "base"), _refs(args)
    with_ref = _text(args, "with", required=False)
    footprint = r.exe("git-overlap", "git-footprint")
    code, out, err = r.run([footprint, "--", base], ("\n".join(refs) + "\n").encode(), cwd=repo)
    if code != 0:
        raise ToolError("git footprint failed (exit %d): %s" % (
            code, err.decode("utf-8", "replace").strip()))
    argv = [r.exe("git-overlap", "git-overlap"), "--audit-json"]
    if with_ref:
        argv += ["--with", with_ref]
    return r.audit("git-overlap", argv, out, cwd=repo)


def _git_pairmerge(r, args):
    repo, pairs = _dir(args, "repo"), _pairs(args)
    onto = _text(args, "onto", required=False)
    argv = [r.exe("git-overlap", "git-pairmerge"), "--audit-json"]
    if onto:
        argv += ["--onto", onto]
    data = "".join("%s\t%s\n" % (a, b) for a, b in pairs).encode()
    return r.audit("git-overlap", argv, data, cwd=repo)


def _trust_path(r, args):
    directory, ref = _dir(args, "dir"), _text(args, "ref", required=False)
    argv = [r.exe("trust-path", "trust-path"), "--audit-json"]
    if ref:
        argv += ["--ref", ref]
    return r.audit("trust-path", argv + ["--", directory])


def _release_drift(command):
    def call(r, args):
        # Arguments are checked before the tool is looked for, so a bad call says what is wrong.
        if command in ("diff", "lockfile"):
            rest = [_file(args, "old"), _file(args, "new")]
        elif command == "source":
            rest = [_file(args, "artifact"), "--repo", _dir(args, "repo"), "--ref", _text(args, "ref")]
        else:
            registry = args.get("registry")
            if registry not in ("pypi", "npm"):
                raise ToolError("argument registry: pypi or npm")
            rest = [registry] + [_text(args, k) for k in ("name", "old", "new")]
        argv = [r.exe("release-drift", "release-drift"), command, "--audit-json"]
        return r.audit("release-drift", argv + rest)
    return call


def _pr_merge_audit(r, args):
    results = _file(args, "results")
    return r.audit("pr-merge-audit", [r.exe("pr-merge-audit", "pr-merge-audit"), "report",
                                      "--audit-json", "--results", results])


def _glassbox_reach(r, args):
    home, since = _dir(args, "home", required=False), _text(args, "since", required=False)
    rest = ["--since", _file(args, "since")] if since else []
    rest += ["--home", home] if home else []
    return r.audit("glassbox", [r.exe("glassbox", "glassbox"), "reach", "--audit-json"] + rest)


def _glassbox_persist(r, args):
    rest = ["--since", _file(args, "since")]
    home = _dir(args, "home", required=False)
    rest += ["--home", home] if home else []
    repos = args.get("repos", [])
    if not isinstance(repos, list):
        raise ToolError("argument repos: a list of directories")
    for repo in repos:
        rest += ["--repo", _dir({"repos": repo}, "repos")]
    return r.audit("glassbox", [r.exe("glassbox", "glassbox"), "persist", "--audit-json"] + rest)


def _s(description):
    return {"type": "string", "description": description}


def _schema(props, required):
    return {"type": "object", "properties": props, "required": required,
            "additionalProperties": False}


REFS = {"type": "array", "items": {"type": "string"}, "minItems": 1,
        "description": "Branch, tag or commit names to check"}

# name -> (description, input schema, reaches the network, handler)
TOOLS = {
    "git_surface": (
        "git-surface: what each ref changes, since its merge base with base, that runs or is "
        "trusted (CI, hooks, agent files, install scripts, dependencies, hidden text).",
        _schema({"repo": _s("Repository directory"), "base": _s("Base branch, e.g. main"),
                 "refs": REFS}, ["repo", "base", "refs"]), False, _git_surface),
    "git_overlap": (
        "git-overlap: pairs of refs that change the same path since base (git footprint, then "
        "git overlap). Optional 'with' keeps only pairs that include that ref.",
        _schema({"repo": _s("Repository directory"), "base": _s("Base branch"), "refs": REFS,
                 "with": _s("Only pairs that include this ref")}, ["repo", "base", "refs"]),
        False, _git_overlap),
    "git_pairmerge": (
        "git-overlap: whether each pair of refs merges (git pairmerge, in memory). Optional "
        "'onto' merges each pair as both would land on that base.",
        _schema({"repo": _s("Repository directory"),
                 "pairs": {"type": "array", "minItems": 1, "items": {
                     "type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2}},
                 "onto": _s("Base both refs land on")}, ["repo", "pairs"]), False, _git_pairmerge),
    "trust_path": (
        "trust-path: paths by which untrusted input reaches a secret, write permission, OIDC "
        "token, environment or AI agent action in GitHub Actions workflows.",
        _schema({"dir": _s("Repository directory"),
                 "ref": _s("Read the workflows from git at this ref instead of the files")},
                ["dir"]), False, _trust_path),
    "release_drift_diff": (
        "release-drift: what a new release artifact adds over an old one (install scripts, "
        "start-up hooks, native code, new dependencies, URL hosts, encoded strings).",
        _schema({"old": _s("Old artifact file (.whl, sdist or npm .tgz)"),
                 "new": _s("New artifact file")}, ["old", "new"]), False,
        _release_drift("diff")),
    "release_drift_source": (
        "release-drift: files of a release artifact that are not, as they are, in git at ref.",
        _schema({"artifact": _s("Artifact file"), "repo": _s("Repository directory"),
                 "ref": _s("Tag or commit the release was built from")},
                ["artifact", "repo", "ref"]), False, _release_drift("source")),
    "release_drift_lockfile": (
        "release-drift: every package a lockfile change upgrades, downloaded from its registry "
        "and compared as release_drift_diff does.",
        _schema({"old": _s("Old lockfile"), "new": _s("New lockfile")}, ["old", "new"]), True,
        _release_drift("lockfile")),
    "release_drift_provenance": (
        "release-drift: whether a new version was published differently from the old one "
        "(provenance removed, workflow changed, another npm account).",
        _schema({"registry": {"type": "string", "enum": ["pypi", "npm"]}, "name": _s("Package"),
                 "old": _s("Old version"), "new": _s("New version")},
                ["registry", "name", "old", "new"]), True, _release_drift("provenance")),
    "pr_merge_audit_report": (
        "pr-merge-audit: the findings of a merge-test results file (which PRs merged, "
        "conflicted or failed their tests).",
        _schema({"results": _s("Results file written by pr-merge-audit build")}, ["results"]),
        False, _pr_merge_audit),
    "glassbox_reach": (
        "glassbox: which sensitive locations (credentials, private data) a process started here "
        "could read. Opens each location read-only; never reads contents.",
        _schema({"home": _s("Audit this directory instead of $HOME"),
                 "since": _s("An earlier `glassbox reach --json` report to compare with")}, []),
        False, _glassbox_reach),
    "glassbox_persist": (
        "glassbox: persistence points (launch agents, shell startup, git hooks, agent configs) "
        "added, changed or removed since a snapshot saved with `glassbox persist --save`.",
        _schema({"since": _s("Snapshot file"), "home": _s("Use this directory as $HOME"),
                 "repos": {"type": "array", "items": {"type": "string"},
                           "description": "Repositories whose hooks and configs to include"}},
                ["since"]), False, _glassbox_persist),
}

COMMANDS = [("git-surface", "git-surface"), ("trust-path", "trust-path"),
            ("release-drift", "release-drift"), ("git-overlap", "git-overlap"),
            ("pr-merge-audit", "pr-merge-audit"), ("glassbox", "glassbox")]


def _at_least(version, minimum):
    """True if dotted VERSION is MINIMUM or later; an unreadable version is not."""
    def parts(v):
        try:
            return [int(x) for x in v.split(".")]
        except ValueError:
            return None
    have, need = parts(version), parts(minimum)
    return have is not None and have >= need


def tools():
    """The tool list returned by tools/list."""
    out = [{"name": "list_audit_tools",
            "description": "The six audit tools, whether each is installed, its version and the "
                           "minimum version with --audit-json.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "openWorldHint": False}}]
    for name, (description, schema, network, _) in TOOLS.items():
        out.append({"name": name, "description": description, "inputSchema": schema,
                    "annotations": {"readOnlyHint": True, "openWorldHint": network}})
    return out


def call(runner, name, args):
    """Run one tool; raises ToolError for anything that is not a valid audit result."""
    if not isinstance(args, dict):
        raise ToolError("arguments must be an object")
    if name == "list_audit_tools":
        rows = []
        for tool, command in COMMANDS:
            installed = runner.version(tool, command)
            rows.append({"name": tool, "installed": installed, "minimum": MINIMUM[tool],
                         "ready": installed is not None and _at_least(installed, MINIMUM[tool])})
        return {"tools": rows}
    if name not in TOOLS:
        raise ToolError("unknown tool '%s'" % name)
    allowed = set(TOOLS[name][1]["properties"])
    extra = sorted(set(args) - allowed)
    if extra:
        raise ToolError("unknown argument: %s" % ", ".join(extra))
    return TOOLS[name][3](runner, args)


def dumps(value):
    """Compact JSON with sorted keys, so the same result is the same bytes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def handle(runner, msg):
    """The reply to one JSON-RPC message, or None for a notification (no id)."""
    if not isinstance(msg, dict) or "id" not in msg:
        return None
    mid, method = msg["id"], msg.get("method")
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "suite-gate", "version": __version__},
                  "instructions": "Each tool runs one installed audit tool with --audit-json and "
                                  "returns its audit-result/1 object. exit 1 means findings, not "
                                  "a failure. Cite rule, path, line and commit from evidence."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tools()}
    elif method == "tools/call":
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        name = params.get("name") if isinstance(params.get("name"), str) else ""
        try:
            value = call(runner, name, params.get("arguments", {}))
            result = {"content": [{"type": "text", "text": dumps(value)}],
                      "structuredContent": value, "isError": False}
        except ToolError as exc:
            result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": "method not found: %s" % method}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(runner, stdin, stdout):
    """Answer one JSON-RPC message per input line until end of input."""
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            reply = handle(runner, json.loads(line))
        except ValueError as exc:
            reply = {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32700, "message": "parse error: %s" % exc}}
        if reply is not None:
            stdout.write(dumps(reply) + "\n")
            stdout.flush()
