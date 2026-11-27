# SPDX-License-Identifier: Apache-2.0
"""Command line: suite-gate gate | mcp | validate."""
import argparse
import json
import sys

from . import __version__, gate, mcp
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
    g.add_argument("--rules", metavar="FILE", help="rules file (default: the built-in rules)")
    g.add_argument("--json", action="store_true", help="print the gate result object")
    g.add_argument("--lockfile-cache", metavar="DIR",
                   help="release-drift: read packages from DIR and query no registry")
    g.add_argument("--timeout", type=int, default=600, metavar="SECONDS",
                   help="longest one tool may run (default 600)")
    v = sub.add_parser("validate", help="check an audit result object (FILE or standard input)")
    v.add_argument("file", nargs="?", metavar="FILE")
    args = p.parse_args(argv)
    if args.command == "gate":
        try:
            result = gate.gate(args.repo, args.base, args.ref, args.rules,
                               mcp.Runner(args.timeout), args.lockfile_cache)
        except (gate.GateError, mcp.ToolError) as exc:
            sys.stderr.write("suite-gate: %s\n" % exc)
            return 2
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n" if args.json
                         else gate.render(result))
        return result["exit"]
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
