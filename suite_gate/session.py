# SPDX-License-Identifier: Apache-2.0
"""suite-gate session: what an agent session left behind that runs again later.

`save` takes a glassbox persist snapshot before the session, `check` compares with it after and
reports in the audit result format, and `run` does both around one command. glassbox does the
work; this module picks the snapshot file, checks the result object and words the report.
"""
import json
import os
import re
import subprocess
import sys

from .mcp import Runner, ToolError

STATE_NAME = "session.snapshot"
_SESSION_ID = re.compile(r"\A[A-Za-z0-9._-]{1,128}\Z")


def state_dir(env=None):
    """$XDG_STATE_HOME/suite-gate, or ~/.local/state/suite-gate."""
    env = os.environ if env is None else env
    base = env.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "suite-gate")


def hook_state(stdin_text, env=None):
    """The snapshot file for a Claude Code hook, from the session_id in its JSON input."""
    try:
        data = json.loads(stdin_text)
    except ValueError:
        raise ToolError("--hook: standard input is not the hook's JSON")
    session = data.get("session_id") if isinstance(data, dict) else None
    if not isinstance(session, str) or not _SESSION_ID.match(session):
        raise ToolError("--hook: the hook input has no usable session_id")
    return os.path.join(state_dir(env), "sessions", session + ".snapshot")


def _scope(home, repos):
    """glassbox options for the locations to watch."""
    out = ["--home", home] if home else []
    for repo in repos:
        out += ["--repo", repo]
    return out


def save(runner, state, home=None, repos=()):
    """Write a glassbox persist snapshot to STATE."""
    os.makedirs(os.path.dirname(os.path.abspath(state)), exist_ok=True)
    exe = runner.exe("glassbox", "glassbox")
    code, out, err = runner.run([exe, "persist", "--save", state] + _scope(home, repos))
    if code != 0:
        raise ToolError("glassbox persist --save failed (exit %d): %s"
                        % (code, err.decode("utf-8", "replace").strip()))
    return out.decode("utf-8", "replace").strip()


def check(runner, state, home=None, repos=()):
    """The audit result of comparing now with the snapshot in STATE."""
    if not os.path.isfile(state):
        raise ToolError("no snapshot at %s; run suite-gate session save first" % state)
    exe = runner.exe("glassbox", "glassbox")
    return runner.audit("glassbox", [exe, "persist", "--audit-json", "--since", state]
                        + _scope(home, repos))


def report(result, state):
    """A few lines a person can read: counts, then each added or changed point."""
    counts = {"added": 0, "changed": 0, "removed": 0}
    for f in result["findings"]:
        change = f["rule"].rsplit(".", 1)[-1]
        counts[change] = counts.get(change, 0) + 1
    if result["errors"]:
        return "suite-gate session: %s\n" % "; ".join(e["message"] for e in result["errors"])
    head = "suite-gate session: %d added, %d changed, %d removed since %s" % (
        counts["added"], counts["changed"], counts["removed"], state)
    lines = [head] + ["  %s" % f["message"] for f in result["findings"] if f["severity"] != "info"]
    return "\n".join(lines) + "\n"


def main(args, stdin=None, out=None, err=None, env=None):
    """Run `session save|check|run` with ARGS from argparse; return the exit status."""
    stdin = sys.stdin if stdin is None else stdin
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    runner = Runner(args.timeout)
    hook_input = stdin.read() if args.hook else None
    try:
        if args.hook:
            state = hook_state(hook_input, env)
        else:
            state = args.state or os.path.join(state_dir(env), STATE_NAME)
        if args.action == "save":
            save(runner, state, args.home, args.repo)
            err.write("suite-gate session: snapshot saved to %s\n" % state)
            return 0
        if args.action == "check":
            result = check(runner, state, args.home, args.repo)
            out.write(json.dumps(result, indent=2, sort_keys=True) + "\n" if args.json
                      else report(result, state))
            if args.hook and result["exit"] != 2:
                os.remove(state)
            return result["exit"]
        # run: save, the command with its own standard streams, then check.
        command = args.argv
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            raise ToolError("session run: give the command after --")
        save(runner, state, args.home, args.repo)
        try:
            status = subprocess.call(command)
        except OSError as exc:
            raise ToolError("cannot run %s: %s" % (command[0], exc))
        result = check(runner, state, args.home, args.repo)
        err.write(report(result, state))
        if args.json:
            out.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result["exit"] if result["exit"] else status
    except ToolError as exc:
        err.write("suite-gate session: %s\n" % exc)
        return 2
