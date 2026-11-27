# Contributing

## Tests

```sh
python3 -m unittest discover -s tests
```

Without the audit tools installed, the suite checks the result format and its validator, the
rules file, the verdict precedence, the command line and the MCP server's argument checks; the
tests that run the tools are skipped. To run everything, install the released tools the tests
were recorded with:

```sh
pip install -r requirements-test.txt
python3 -m unittest discover -s tests
```

With them, the suite also replays a recorded MCP session byte for byte, runs the gate on a
fixture repository for each verdict, and checks that the JSON Schema and the validator agree on
every example. glassbox is not on PyPI: install it with Homebrew or from a
[release](https://github.com/jacob-adm/glassbox/releases) to run its tests too.

## Contributing

Changes reach `main` only through pull requests.

1. Fork the repository and create a branch.
2. Make the change with a test that fails without it, then run the tests with the tools installed.
3. Open a pull request against `main`. CI runs the tests on Linux, macOS and Windows with Python
   3.9 and 3.13, and once more with every audit tool installed, where no test may be skipped;
   the required checks must pass before merging. Pull requests are merged with a merge commit.

If a change alters what the MCP server returns, record the session again and review the
difference in `tests/fixtures/mcp/responses.jsonl` before committing it.

Keep suite-gate standard-library-only, and keep every verdict decided by the rules file.
