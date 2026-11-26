# SPDX-License-Identifier: Apache-2.0
"""Check an audit result against format audit-result/1 (docs/format.md).

validate() applies every rule in schema/audit-result-1.schema.json and the rules
the schema cannot express: exit 2 exactly when there are errors, otherwise exit 1
exactly when a finding is not "info". It returns a list of problems; empty means valid.
"""
import re

FORMAT = "audit-result/1"
SEVERITIES = ("high", "medium", "low", "info")
TARGET_KINDS = ("repository", "artifact", "package", "host")
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_RULE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
_COMMIT = re.compile(r"^([0-9a-f]{40}|[0-9a-f]{64})$")


def _text(v):
    return isinstance(v, str) and v != ""


def _keys(obj, where, required, allowed, out):
    if not isinstance(obj, dict):
        out.append(f"{where}: not an object")
        return False
    out.extend(f"{where}: missing {k}" for k in required if k not in obj)
    out.extend(f"{where}: unknown key {k}" for k in sorted(obj) if k not in allowed)
    return True


def _evidence(ev, where, out):
    if not _keys(ev, where, (), ("path", "line", "commit", "ref", "url"), out):
        return
    if not ev:
        out.append(f"{where}: empty")
    for k in ("path", "ref"):
        if k in ev and not _text(ev[k]):
            out.append(f"{where}.{k}: not a non-empty string")
    if "line" in ev:
        line = ev["line"]
        if type(line) is not int or line < 1:
            out.append(f"{where}.line: not an integer >= 1")
        if "path" not in ev:
            out.append(f"{where}.line: needs path")
    if "commit" in ev and not (isinstance(ev["commit"], str) and _COMMIT.match(ev["commit"])):
        out.append(f"{where}.commit: not a full hex object id")
    if "url" in ev and not (isinstance(ev["url"], str) and ev["url"].startswith("https://")):
        out.append(f"{where}.url: not an https URL")


def _finding(f, where, out):
    if not _keys(f, where, ("rule", "severity", "message", "evidence", "record"),
                 ("rule", "severity", "message", "evidence", "record"), out):
        return
    if "rule" in f and not (isinstance(f["rule"], str) and _RULE.match(f["rule"])):
        out.append(f"{where}.rule: not a rule id")
    if "severity" in f and f["severity"] not in SEVERITIES:
        out.append(f"{where}.severity: not one of {', '.join(SEVERITIES)}")
    if "message" in f and not _text(f["message"]):
        out.append(f"{where}.message: not a non-empty string")
    if "evidence" in f:
        _evidence(f["evidence"], f"{where}.evidence", out)
    if "record" in f and not isinstance(f["record"], dict):
        out.append(f"{where}.record: not an object")


def _error(e, where, out):
    if not _keys(e, where, ("message",), ("message", "path"), out):
        return
    for k in ("message", "path"):
        if k in e and not _text(e[k]):
            out.append(f"{where}.{k}: not a non-empty string")


def validate(doc):
    """Return the problems in doc as a list of strings; [] when doc is a valid result."""
    out = []
    top = ("format", "tool", "target", "exit", "findings", "errors")
    if not _keys(doc, "result", top, top, out):
        return out
    if "format" in doc and doc["format"] != FORMAT:
        out.append(f"result.format: not {FORMAT}")
    tool = doc.get("tool")
    if "tool" in doc and _keys(tool, "tool", ("name", "version"), ("name", "version"), out):
        if "name" in tool and not (isinstance(tool["name"], str) and _NAME.match(tool["name"])):
            out.append("tool.name: not a tool name")
        if "version" in tool and not _text(tool["version"]):
            out.append("tool.version: not a non-empty string")
    target = doc.get("target")
    if "target" in doc and _keys(target, "target", ("kind", "name"),
                                 ("kind", "name", "ref", "base"), out):
        if "kind" in target and target["kind"] not in TARGET_KINDS:
            out.append(f"target.kind: not one of {', '.join(TARGET_KINDS)}")
        for k in ("name", "ref", "base"):
            if k in target and not _text(target[k]):
                out.append(f"target.{k}: not a non-empty string")
    lists_ok = True
    for key, check in (("findings", _finding), ("errors", _error)):
        if key not in doc:
            lists_ok = False
        elif not isinstance(doc[key], list):
            out.append(f"result.{key}: not an array")
            lists_ok = False
        else:
            for i, item in enumerate(doc[key]):
                check(item, f"{key}[{i}]", out)
    code = doc.get("exit")
    if "exit" in doc and (type(code) is not int or code not in (0, 1, 2)):
        out.append("result.exit: not 0, 1 or 2")
    elif "exit" in doc and lists_ok and not out:
        out.extend(_exit_rules(doc))
    return out


def _exit_rules(doc):
    errors = len(doc["errors"])
    found = sum(1 for f in doc["findings"] if f["severity"] != "info")
    want = 2 if errors else (1 if found else 0)
    if doc["exit"] == want:
        return []
    why = {2: f"{errors} error(s)", 1: f"{found} finding(s) above info",
           0: "no errors and no finding above info"}[want]
    return [f"result.exit: is {doc['exit']}, must be {want} with {why}"]
