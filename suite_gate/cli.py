# SPDX-License-Identifier: Apache-2.0
"""Command line: suite-gate gate | mcp | validate."""
import argparse
import json
import sys

from . import __version__, action, gate, mcp, session
from .envelope import validate


def main(argv=None):
    p = argparse.ArgumentParser(prog="suite-gate",
                                description="A shared result format for audit tools, and an MCP "
                                            "server that runs them.")
    p.add_argument("--version", action="version", version="suite-gate " + __version__)
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True
    m = sub.add_parser("mcp", help="serve the installed audit tools over MCP (stdio)")
    m.add_argument("--timeout", type=int, default=600, metavar="SECONDS",
                   help="longest one tool may run (default 600)")
    g = sub.add_parser("gate", help="one verdict for REF against BASE, from the rules file")
    g.add_argument("base", metavar="BASE")
    g.add_argument("ref", metavar="REF")
    g.add_argument("--repo", default=".", metavar="DIR", help="repository (default: .)")
    g.add_argument("--rules", metavar="FILE",
                   help="rules file, or a built-in name: default (local branches) or ci "
                        "(branches under origin/, for a CI checkout)")
    g.add_argument("--exclude", action="append", default=[], metavar="BRANCH",
                   help="leave BRANCH out of the overlap check (repeatable)")
    g.add_argument("--json", action="store_true", help="print the gate result object")
    g.add_argument("--lockfile-cache", metavar="DIR",
                   help="release-drift: read packages from DIR and query no registry")
    g.add_argument("--timeout", type=int, default=600, metavar="SECONDS",
                   help="longest one tool may run (default 600)")
    s = sub.add_parser("session", help="what an agent session left behind that runs later "
                                       "(glassbox persist before and after)")
    ss = s.add_subparsers(dest="action", metavar="ACTION")
    ss.required = True
    for name, text in (("save", "snapshot the persistence points before a session"),
                       ("check", "compare with the snapshot after a session"),
                       ("run", "snapshot, run COMMAND, compare")):
        p_ = ss.add_parser(name, help=text)
        where = p_.add_mutually_exclusive_group()
        where.add_argument("--state", metavar="FILE",
                           help="snapshot file (default: $XDG_STATE_HOME/suite-gate/session.snapshot)")
        where.add_argument("--hook", action="store_true",
                           help="read a Claude Code hook's JSON on standard input and keep one "
                                "snapshot per session_id")
        p_.add_argument("--home", metavar="DIR", help="glassbox: use DIR instead of $HOME")
        p_.add_argument("--repo", action="append", default=[], metavar="DIR",
                        help="glassbox: also watch DIR's git hooks, config and agent configs")
        p_.add_argument("--timeout", type=int, default=600, metavar="SECONDS")
        if name != "save":
            p_.add_argument("--json", action="store_true", help="print the audit result object")
        if name == "run":
            p_.add_argument("argv", nargs=argparse.REMAINDER, metavar="-- COMMAND")
    sub.add_parser("action", help="run the gate as a GitHub Actions step (reads GATE_* and "
                                  "GITHUB_* from the environment)")
    v = sub.add_parser("validate", help="check an audit result object (FILE or standard input)")
    v.add_argument("file", nargs="?", metavar="FILE")
    args = p.parse_args(argv)
    if args.command == "gate":
        try:
            result = gate.gate(args.repo, args.base, args.ref, args.rules,
                               mcp.Runner(args.timeout), args.lockfile_cache, args.exclude)
        except (gate.GateError, mcp.ToolError) as exc:
            sys.stderr.write("suite-gate: %s\n" % exc)
            return 2
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n" if args.json
                         else gate.render(result))
        return result["exit"]
    if args.command == "session":
        return session.main(args)
    if args.command == "action":
        return action.main()
    if args.command == "mcp":
        if args.timeout < 1:
            p.error("--timeout must be at least 1")
        mcp.serve(mcp.Runner(args.timeout), sys.stdin, sys.stdout)
        return 0
    try:
        text = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
        problems = validate(json.loads(text))
    except (OSError, ValueError) as exc:
        sys.stderr.write("suite-gate: %s\n" % exc)
        return 2
    for problem in problems:
        sys.stdout.write(problem + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
