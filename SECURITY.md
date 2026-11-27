# Security

suite-gate runs `git` (`rev-parse`, `merge-base`, `diff`, `show`, `for-each-ref`) and the
installed audit tools, each as a subprocess with an argument list, never through a shell. It
never writes to the repository it checks and never runs code from it: no hooks, no build, no
install. Arguments that start with `-` or hold a line break are refused before anything runs, so
a branch or path name cannot become an option. Every tool result is validated against the
result format before it is used, and a tool that fails is reported as an error, never as a pass.

The gate's release-drift check downloads packages and queries PyPI or npm when a lockfile
changed, unless `--lockfile-cache DIR` is given. Nothing else uses the network. The MCP server
offers no option that writes files. `suite-gate session` writes only its glassbox snapshot
(paths, categories and hashes, no contents) under `$XDG_STATE_HOME/suite-gate` or `--state`.

## Reporting a vulnerability

Please report security problems privately, through GitHub's "Report a vulnerability" button on the
repository's Security tab. Please do not open a public issue. You can expect a reply within a week.
