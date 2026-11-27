# SPDX-License-Identifier: Apache-2.0
"""suite-gate action: the gate as a GitHub Actions step.

Reads its inputs from the environment (GATE_* set by action.yml, GITHUB_* set by Actions), runs
the gate, prints the text report, annotates each finding on its file and line, writes a job
summary, sets the outputs `verdict` and `result`, and exits with the gate's exit status.
"""
import json
import os
import subprocess
import sys
import tempfile

from . import gate, mcp

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _escape_data(text):
    """Escape a workflow command's message (GitHub's %, CR and LF rules)."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(text):
    """Escape a workflow command's property value (also : and ,)."""
    return _escape_data(text).replace(":", "%3A").replace(",", "%2C")


def annotations(result, rules):
    """One ::error or ::warning line per finding with a fail or warn severity."""
    fail = set(rules["verdict"]["fail"])
    warn = set(rules["verdict"]["warn"])
    lines = []
    for check in result["checks"]:
        for f in check.get("result", {}).get("findings", []):
            level = "error" if f["severity"] in fail else "warning" if f["severity"] in warn else None
            if level is None:
                continue
            props = ["title=%s" % _escape_property("%s (%s)" % (f["rule"], f["severity"]))]
            evidence = f["evidence"]
            if "path" in evidence and not evidence["path"].startswith(("~", "/")):
                props.insert(0, "file=%s" % _escape_property(evidence["path"]))
                if "line" in evidence:
                    props.insert(1, "line=%d" % evidence["line"])
            lines.append("::%s %s::%s" % (level, ",".join(props), _escape_data(f["message"])))
    for check in result["checks"]:
        if check["status"] == "error":
            lines.append("::error title=%s::%s" % (_escape_property(check["tool"] + " did not run"),
                                                     _escape_data(check["error"])))
    return lines


def _cell(text):
    """Text for one Markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def summary(result):
    """The job summary, in Markdown: verdict, checks, findings with evidence."""
    out = ["## suite-gate: %s" % result["verdict"].upper(), "",
           "`%s` (%s) into `%s` (%s), rules `%s` version %d." % (
               result["ref"]["name"], result["ref"]["commit"][:12], result["base"]["name"],
               result["base"]["commit"][:12], result["rules"]["name"], result["rules"]["version"]),
           "", "| Check | Status | Result |", "| --- | --- | --- |"]
    findings = []
    for check in result["checks"]:
        if check["status"] == "ran":
            found = [f for f in check["result"]["findings"] if f["severity"] != "info"]
            findings.extend(found)
            text = ", ".join("%d %s" % (sum(f["severity"] == s for f in found), s)
                             for s in ("high", "medium", "low")
                             if any(f["severity"] == s for f in found)) or "nothing found"
            if check["result"]["errors"]:
                text = "; ".join(e["message"] for e in check["result"]["errors"])
        elif check["status"] == "skipped":
            text = check["reason"]
        else:
            text = check["error"]
        status = check["status"] + ("" if check["status"] != "ran" else " (%s)" % check["reason"])
        out.append("| %s | %s | %s |" % (_cell(check["tool"]), _cell(status), _cell(text)))
    if findings:
        out += ["", "| Severity | Rule | Finding | Evidence |", "| --- | --- | --- | --- |"]
        for f in sorted(findings, key=lambda f: SEVERITY_ORDER[f["severity"]]):
            ev = f["evidence"]
            where = ev.get("path", "")
            if "line" in ev:
                where += ":%d" % ev["line"]
            if "commit" in ev:
                where += " @ %s" % ev["commit"][:12]
            if "url" in ev:
                where += " %s" % ev["url"]
            out.append("| %s | `%s` | %s | %s |" % (f["severity"], _cell(f["rule"]),
                                                     _cell(f["message"]), _cell(where.strip())))
    return "\n".join(out) + "\n"


def _shallow(repo):
    proc = subprocess.run(["git", "-C", repo, "rev-parse", "--is-shallow-repository"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    return proc.stdout.strip() == "true"


def _append(path, text):
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)


def main(env=None, out=sys.stdout):
    """Run the gate from environment variables; return the exit status."""
    env = os.environ if env is None else env
    repo = env.get("GITHUB_WORKSPACE") or "."
    base = env.get("GATE_BASE") or (
        "origin/" + env["GITHUB_BASE_REF"] if env.get("GITHUB_BASE_REF") else "")
    ref = env.get("GATE_REF") or "HEAD"
    rules = env.get("GATE_RULES") or "ci"
    exclude = ["origin/" + env["GITHUB_HEAD_REF"]] if env.get("GITHUB_HEAD_REF") else []

    def fail(message):
        out.write("::error title=suite-gate::%s\n" % _escape_data(message))
        return 2
    if not base:
        return fail("no base: set the base input, or run on a pull_request event")
    if _shallow(repo):
        return fail("the checkout is shallow; check out with fetch-depth: 0 so the merge base "
                    "and the other branches are there")
    try:
        loaded = gate.load_rules(rules)[0]
        result = gate.gate(repo, base, ref, rules, mcp.Runner(int(env.get("GATE_TIMEOUT") or 600)),
                           env.get("GATE_LOCKFILE_CACHE") or None, exclude)
    except (gate.GateError, mcp.ToolError, ValueError) as exc:
        return fail(str(exc))
    out.write(gate.render(result))
    for line in annotations(result, loaded):
        out.write(line + "\n")
    directory = env.get("RUNNER_TEMP") or tempfile.gettempdir()
    path = os.path.join(directory, "suite-gate-result.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    if env.get("GITHUB_STEP_SUMMARY"):
        _append(env["GITHUB_STEP_SUMMARY"], summary(result))
    if env.get("GITHUB_OUTPUT"):
        _append(env["GITHUB_OUTPUT"], "verdict=%s\nresult=%s\n" % (result["verdict"], path))
    out.flush()
    return result["exit"]
