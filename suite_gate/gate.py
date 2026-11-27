# SPDX-License-Identifier: Apache-2.0
"""suite-gate gate: one verdict for a branch, from fixed rules over the audit tools.

The rules file says which audit tool runs when, and which severities fail or warn. The verdict
follows a fixed precedence (fail, then error, then warn, then pass); no model takes part. Each
tool's audit result is kept unchanged in the gate result, so every finding keeps its evidence.
"""
import hashlib
import json
import os
import re
import subprocess
import tempfile

from .mcp import Runner, ToolError, _text

FORMAT = "gate-result/1"
RULES_FORMAT = "gate-rules/1"
RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")
DEFAULT_RULES = os.path.join(RULES_DIR, "default.json")
# Built-in rules by name: default (local branches) and ci (a CI checkout, branches under origin/).
BUILTIN = {"default": DEFAULT_RULES, "ci": os.path.join(RULES_DIR, "ci.json")}
SEVERITIES = ("high", "medium", "low")
# The keys each check may have, besides "tool"; a key in brackets is required.
CHECK_KEYS = {"git-surface": {}, "trust-path": {"when_changed": False},
              "release-drift": {"for_each_changed": True}, "git-overlap": {"others": True}}
EXIT = {"pass": 0, "warn": 0, "fail": 1, "error": 2}


class GateError(Exception):
    """The gate cannot run at all: bad rules, or BASE or REF is not a commit."""


# --- rules ------------------------------------------------------------------------------------

def _patterns(value, where):
    if not isinstance(value, list) or not value or not all(isinstance(p, str) for p in value):
        raise GateError("%s: a non-empty list of regular expressions" % where)
    try:
        return [re.compile(p) for p in value]
    except re.error as exc:
        raise GateError("%s: %s" % (where, exc))


def load_rules(path=None):
    """Read and check a rules file; return (rules, its sha256, the path read)."""
    path = BUILTIN.get(path, path) if path else DEFAULT_RULES
    try:
        with open(path, "rb") as handle:
            data = handle.read()
        rules = json.loads(data.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError("cannot read rules %s: %s" % (path, exc))
    if not isinstance(rules, dict):
        raise GateError("rules: not an object")
    extra = sorted(set(rules) - {"format", "name", "version", "checks", "verdict"})
    if extra:
        raise GateError("rules: unknown key %s" % extra[0])
    if rules.get("format") != RULES_FORMAT:
        raise GateError("rules.format: not %s" % RULES_FORMAT)
    if not isinstance(rules.get("name"), str) or type(rules.get("version")) is not int:
        raise GateError("rules: name (a string) and version (an integer) are required")
    checks = rules.get("checks")
    if not isinstance(checks, list) or not checks:
        raise GateError("rules.checks: a non-empty list")
    for i, check in enumerate(checks):
        where = "rules.checks[%d]" % i
        if not isinstance(check, dict) or check.get("tool") not in CHECK_KEYS:
            raise GateError("%s.tool: one of %s" % (where, ", ".join(sorted(CHECK_KEYS))))
        allowed = CHECK_KEYS[check["tool"]]
        for key in sorted(set(check) - {"tool"} - set(allowed)):
            raise GateError("%s: unknown key %s for %s" % (where, key, check["tool"]))
        for key, required in allowed.items():
            if required and key not in check:
                raise GateError("%s: %s is required for %s" % (where, key, check["tool"]))
        for key in ("when_changed", "for_each_changed"):
            if key in check:
                _patterns(check[key], "%s.%s" % (where, key))
        if "others" in check and (not isinstance(check["others"], str)
                                  or not check["others"].startswith("refs/")):
            raise GateError("%s.others: a ref prefix such as refs/heads/" % where)
    verdict = rules.get("verdict")
    if not isinstance(verdict, dict) or set(verdict) != {"fail", "warn"}:
        raise GateError("rules.verdict: an object with fail and warn")
    for key in ("fail", "warn"):
        if not isinstance(verdict[key], list) or not set(verdict[key]) <= set(SEVERITIES):
            raise GateError("rules.verdict.%s: a list of %s" % (key, ", ".join(SEVERITIES)))
    if set(verdict["fail"]) & set(verdict["warn"]):
        raise GateError("rules.verdict: a severity cannot both fail and warn")
    return rules, hashlib.sha256(data).hexdigest(), path


# --- git --------------------------------------------------------------------------------------

def _git(repo, *args):
    proc = subprocess.run(["git", "-C", repo] + list(args), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise GateError("git %s: %s" % (args[0], proc.stderr.decode("utf-8", "replace").strip()))
    return proc.stdout


def _commit(repo, ref):
    proc = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "--quiet",
                           "--end-of-options", ref + "^{commit}"], stdout=subprocess.PIPE)
    if proc.returncode != 0:
        raise GateError("not a commit: %s" % ref)
    return proc.stdout.decode().strip()


def changed(repo, base_commit, ref_commit):
    """(merge base, paths REF changes since it), paths sorted."""
    mb = _git(repo, "merge-base", base_commit, ref_commit).decode().strip()
    out = _git(repo, "diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", mb, ref_commit)
    return mb, sorted(p for p in out.decode("utf-8", "surrogateescape").split("\0") if p)


def _blob(repo, commit, path):
    """The bytes of PATH at COMMIT, or None if it is not there."""
    proc = subprocess.run(["git", "-C", repo, "show", "%s:%s" % (commit, path)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.stdout if proc.returncode == 0 else None


# --- checks -----------------------------------------------------------------------------------

def _entry(tool, reason, result=None, error=None, path=None):
    entry = {"tool": tool, "status": "error" if error else ("ran" if result else "skipped"),
             "reason": reason}
    if path is not None:
        entry["path"] = path
    if result is not None:
        entry["result"] = result
    if error is not None:
        entry["error"] = error
    return entry


def _run(runner, tool, reason, call, path=None):
    """One check that runs a tool: its result, or its error."""
    try:
        return _entry(tool, reason, result=call(), path=path)
    except ToolError as exc:
        return _entry(tool, reason, error=str(exc), path=path)


def _surface(runner, ctx, check):
    exe = lambda: runner.exe("git-surface", "git-surface")
    return [_run(runner, "git-surface", "always runs", lambda: runner.audit(
        "git-surface", [exe(), "--audit-json", "--", ctx["base"]],
        (ctx["ref"] + "\n").encode(), cwd=ctx["repo"]))]


def _trust(runner, ctx, check):
    patterns = [re.compile(p) for p in check.get("when_changed", [])]
    hits = [p for p in ctx["paths"] if any(r.search(p) for r in patterns)]
    if patterns and not hits:
        return [_entry("trust-path", "no changed path matches %s" % ", ".join(
            check["when_changed"]))]
    reason = "changed: %s" % ", ".join(hits) if patterns else "always runs"
    return [_run(runner, "trust-path", reason, lambda: runner.audit(
        "trust-path", [runner.exe("trust-path", "trust-path"), "--audit-json", "--ref",
                       ctx["ref_commit"], "--", ctx["repo"]]))]


def _drift(runner, ctx, check):
    patterns = [re.compile(p) for p in check["for_each_changed"]]
    hits = [p for p in ctx["paths"] if any(r.search(p) for r in patterns)]
    if not hits:
        return [_entry("release-drift", "no changed lockfile")]
    out = []
    for path in hits:
        old, new = _blob(ctx["repo"], ctx["merge_base"], path), _blob(ctx["repo"], ctx["ref_commit"], path)
        if old is None or new is None:
            out.append(_entry("release-drift", "%s %s; nothing to compare" % (
                path, "added" if old is None else "deleted"), path=path))
            continue
        out.append(_run(runner, "release-drift", "changed: %s" % path, lambda o=old, n=new, p=path:
                        _lockfile(runner, ctx, p, o, n), path=path))
    return out


def _lockfile(runner, ctx, path, old, new):
    """release-drift lockfile on the two versions of PATH, written to temporary files."""
    name = os.path.basename(path)
    with tempfile.TemporaryDirectory(prefix="suite-gate-") as tmp:
        files = []
        for side, data in (("base", old), ("ref", new)):
            os.makedirs(os.path.join(tmp, side))
            files.append(os.path.join(tmp, side, name))
            with open(files[-1], "wb") as handle:
                handle.write(data)
        argv = [runner.exe("release-drift", "release-drift"), "lockfile", "--audit-json"] + files
        if ctx.get("lockfile_cache"):
            argv += ["--cache", ctx["lockfile_cache"], "--no-provenance"]
        return runner.audit("release-drift", argv)


def _overlap(runner, ctx, check):
    names = _git(ctx["repo"], "for-each-ref", "--format=%(refname:short)", check["others"])
    skip = {ctx["ref"], ctx["base"]} | set(ctx.get("exclude", ()))
    others = [n for n in names.decode("utf-8", "surrogateescape").splitlines()
              if n and n not in skip and not n.endswith("/HEAD") and n != "origin"]
    if not others:
        return [_entry("git-overlap", "no other branch under %s" % check["others"])]
    reason = "against %d other branch(es) under %s" % (len(others), check["others"])

    def call():
        footprint = runner.exe("git-overlap", "git-footprint")
        code, out, err = runner.run([footprint, "--", ctx["base"]],
                                    ("\n".join([ctx["ref"]] + others) + "\n").encode(),
                                    cwd=ctx["repo"])
        if code != 0:
            raise ToolError("git footprint failed (exit %d): %s"
                            % (code, err.decode("utf-8", "replace").strip()))
        return runner.audit("git-overlap", [runner.exe("git-overlap", "git-overlap"),
                                            "--audit-json", "--with", ctx["ref"]], out,
                            cwd=ctx["repo"])
    return [_run(runner, "git-overlap", reason, call)]


HANDLERS = {"git-surface": _surface, "trust-path": _trust, "release-drift": _drift,
            "git-overlap": _overlap}


# --- verdict ----------------------------------------------------------------------------------

def verdict(checks, rules):
    """fail if a finding has a fail severity; else error if a check or tool errored; else warn
    if a finding has a warn severity; else pass."""
    severities = [f["severity"] for c in checks if "result" in c for f in c["result"]["findings"]]
    errored = any(c["status"] == "error" or c.get("result", {}).get("exit") == 2 for c in checks)
    if any(s in rules["verdict"]["fail"] for s in severities):
        return "fail"
    if errored:
        return "error"
    if any(s in rules["verdict"]["warn"] for s in severities):
        return "warn"
    return "pass"


def gate(repo, base, ref, rules_path=None, runner=None, lockfile_cache=None, exclude=()):
    """Run the gate; return the gate result object. Raises GateError if it cannot start."""
    runner = runner or Runner()
    rules, sha256, path = load_rules(rules_path)
    _text({"base": base}, "base")
    _text({"ref": ref}, "ref")
    if not os.path.isdir(repo):
        raise GateError("not a directory: %s" % repo)
    base_commit, ref_commit = _commit(repo, base), _commit(repo, ref)
    merge_base, paths = changed(repo, base_commit, ref_commit)
    ctx = {"repo": repo, "base": base, "ref": ref, "ref_commit": ref_commit,
           "merge_base": merge_base, "paths": paths, "lockfile_cache": lockfile_cache,
           "exclude": exclude}
    checks = []
    for check in rules["checks"]:
        checks.extend(HANDLERS[check["tool"]](runner, ctx, check))
    result = {
        "format": FORMAT,
        "rules": {"name": rules["name"], "version": rules["version"], "sha256": sha256},
        "base": {"name": base, "commit": base_commit},
        "ref": {"name": ref, "commit": ref_commit},
        "merge_base": merge_base,
        "changed": paths,
        "checks": checks,
    }
    result["verdict"] = verdict(checks, rules)
    result["exit"] = EXIT[result["verdict"]]
    return result


def render(result):
    """The gate result as text: the verdict, one line per check, then each finding above info."""
    lines = ["%s: %s into %s (rules %s %d)" % (result["verdict"].upper(), result["ref"]["name"],
                                                result["base"]["name"], result["rules"]["name"],
                                                result["rules"]["version"])]
    findings = []
    for c in result["checks"]:
        what = c["tool"]
        if c["status"] == "ran":
            found = [f for f in c["result"]["findings"] if f["severity"] != "info"]
            counts = {}
            for f in found:
                counts[f["severity"]] = counts.get(f["severity"], 0) + 1
            summary = ", ".join("%d %s" % (counts[s], s) for s in SEVERITIES if s in counts)
            if c["result"]["errors"]:
                summary = "; ".join(e["message"] for e in c["result"]["errors"])
            lines.append("  %-14s ran      %s (%s)" % (what, summary or "nothing found", c["reason"]))
            findings.extend(found)
        elif c["status"] == "skipped":
            lines.append("  %-14s skipped  %s" % (what, c["reason"]))
        else:
            lines.append("  %-14s error    %s" % (what, c["error"]))
    order = {s: i for i, s in enumerate(SEVERITIES)}
    for f in sorted(findings, key=lambda f: order[f["severity"]]):
        where = f["evidence"].get("path", "")
        if "line" in f["evidence"]:
            where += ":%d" % f["evidence"]["line"]
        lines.append("%-6s %s  %s%s" % (f["severity"], f["rule"], f["message"],
                                        "  [%s]" % where if where else ""))
    return "\n".join(lines) + "\n"
