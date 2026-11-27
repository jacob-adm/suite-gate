# suite-gate

A shared result format for command-line audit tools, so that an automated reviewer can run them
on a branch and read every finding with its evidence in one shape, and an MCP server that lets
a coding agent run them.

- [Format](docs/format.md): the result object, the exit status rules and how each tool maps to it.
- [Schema](schema/audit-result-1.schema.json): JSON Schema 2020-12.
- [Examples](examples): results that pass and results that fail, one per broken rule.
- [MCP server](docs/mcp.md): `suite-gate mcp` serves the installed audit tools to an agent;
  each call returns the tool's audit result object, checked before it is returned.
- [Screenshots](docs/screenshots): what each tool prints on a demo repository, with and without
  `--audit-json`. Regenerate them with `python3 scripts/screenshots.py` (the tools must be on PATH).

<p align="center"><img src="docs/screenshots/git-surface-audit-json.svg" alt="git surface --audit-json on a demo branch"></p>

Check a result with the standard library only:

```sh
python3 -c 'import json,sys; from suite_gate.envelope import validate; print(validate(json.load(sys.stdin)))' < result.json
```

Or with the command line: `suite-gate validate result.json` prints each problem and exits 1, or
exits 0 for a valid result.

Run the tests with `python3 -m unittest discover tests`. With the packages in
`requirements-test.txt` installed, the tests also check that the schema file and the validator
agree on every example, and replay a recorded MCP session against the released tools.

## License

Apache-2.0. See [LICENSE](LICENSE).
