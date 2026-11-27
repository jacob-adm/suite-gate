# SPDX-License-Identifier: Apache-2.0
"""Command line: suite-gate mcp [--timeout SECONDS] | suite-gate validate [FILE]"""
import argparse
import json
import sys

from . import __version__, mcp
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
    v = sub.add_parser("validate", help="check an audit result object (FILE or standard input)")
    v.add_argument("file", nargs="?", metavar="FILE")
    args = p.parse_args(argv)
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
