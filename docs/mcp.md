# MCP server

`suite-gate mcp` serves the installed audit tools to an MCP client (a coding agent, an IDE) over
standard input and output: JSON-RPC 2.0, one message per line, protocol version `2025-06-18`.
Each MCP tool runs one audit tool with `--audit-json` and returns its
[audit result object](format.md) unchanged.

## Set up

Install suite-gate and the audit tools you want the agent to have:

```sh
pip install .        # from a clone of this repository
pip install 'git-surface>=0.4.0' 'trust-path>=0.8.1' 'release-drift>=0.7.0' \
            'git-overlap>=0.7.0' 'pr-merge-audit>=2.3.0'
brew install jacob-adm/tap/glassbox   # or a GitHub release of glassbox 0.6.0 or later
```

Register the server with the client. For Claude Code:

```sh
claude mcp add suite-gate -- suite-gate mcp
```

For a client configured with JSON:

```json
{"mcpServers": {"suite-gate": {"command": "suite-gate", "args": ["mcp"]}}}
```

`--timeout SECONDS` sets the longest one tool may run (default 600). The tools must be on the
`PATH` the client gives the server. Call `list_audit_tools` to see which are installed and
ready.

## Tools

| Tool | Runs | Arguments |
| --- | --- | --- |
| `list_audit_tools` | `--version` of each tool | none |
| `gate` | `suite-gate gate BASE REF` with the built-in rules; see [Gate](gate.md) | `repo`, `base`, `ref` |
| `git_surface` | `git surface --audit-json BASE`, refs on standard input | `repo`, `base`, `refs` |
| `git_overlap` | `git footprint BASE`, then `git overlap --audit-json` | `repo`, `base`, `refs`, optional `with` |
| `git_pairmerge` | `git pairmerge --audit-json`, pairs on standard input | `repo`, `pairs` (`[[refA, refB], ...]`), optional `onto` |
| `trust_path` | `trust-path --audit-json DIR` | `dir`, optional `ref` |
| `release_drift_diff` | `release-drift diff --audit-json OLD NEW` | `old`, `new` (artifact files) |
| `release_drift_source` | `release-drift source --audit-json ARTIFACT --repo DIR --ref REF` | `artifact`, `repo`, `ref` |
| `release_drift_lockfile` | `release-drift lockfile --audit-json OLD NEW` (downloads) | `old`, `new` (lockfiles) |
| `release_drift_provenance` | `release-drift provenance --audit-json ...` (queries the registry) | `registry` (`pypi` or `npm`), `name`, `old`, `new` |
| `pr_merge_audit_report` | `pr-merge-audit report --audit-json --results FILE` | `results` |
| `glassbox_reach` | `glassbox reach --audit-json` | optional `home`, `since` |
| `glassbox_persist` | `glassbox persist --audit-json --since FILE` | `since`, optional `home`, `repos` |

Every tool is marked read-only: none of the options that write (`persist --save`, `report
--out`, `build --emit-branch`) is offered. The three that can reach the network
(`gate`, through release-drift, `release_drift_lockfile` and `release_drift_provenance`) are
marked `openWorldHint`.

## Results

A call that ran returns the audit result object as `structuredContent` and as JSON text, with
`isError` false. That includes exit 1 (findings) and the tool's own exit 2 object (for example an
unknown BASE): both are what the tool said, and the object carries the reason. The server checks
each object before returning it: it must pass `suite_gate.envelope.validate`, name the tool that
ran, and state the exit status the tool exited with.

A call that could not produce such an object is a tool error (`isError` true) with one line of
text:

- an argument that is missing, of the wrong type, or unknown, or a value that starts with `-`
  (it could be read as an option) or holds a TAB, line break or NUL;
- a `repo`, `dir` or `home` that is not a directory, or a file argument that is not a file;
- a tool that is not installed (the message says how to install it), that is too old to print
  the format (it names the minimum version), or that prints an object that does not validate;
- a run longer than `--timeout`.

The server runs each tool as a subprocess with an argument list, never through a shell, and
adds, removes or changes no finding.

## Tests

`tests/test_mcp.py` replays a recorded session (`tests/fixtures/mcp`) against the released
tools in `requirements-test.txt`, on inputs `tests/session_fixture.py` builds with fixed
contents, author and dates, and compares the replies byte for byte. glassbox is tested outside
the recording, because its location list differs by operating system. Without the tools
installed those tests are skipped; the CI job that installs them fails on any skip.
