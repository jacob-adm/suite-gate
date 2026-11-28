# Gate

`suite-gate gate BASE REF` runs the audit tools a rules file names on the changes REF makes
since its merge base with BASE, and gives one verdict: `pass`, `warn`, `fail` or `error`. The
verdict follows fixed rules; no model takes part. Every finding is kept as its tool wrote it,
with its rule, severity, sentence and evidence; the one change is that trust-path's result leaves
out the paths already at the merge base (see [Rules](#rules)).

```
suite-gate gate [--repo DIR] [--rules FILE] [--json] [--lockfile-cache DIR] [--forge FORGE] [--timeout SECONDS] BASE REF
```

For the `ci` branch of the test fixture, whose only change is to a CI workflow:

```
FAIL: ci into main (rules default 1)
  git-surface    ran      1 high (always runs)
  trust-path     ran      nothing found (changed: .github/workflows/ci.yml)
  release-drift  skipped  no changed lockfile
  git-overlap    ran      nothing found (against 5 other branch(es) under refs/heads/)
high   git-surface.ci  ci modifies CI file .github/workflows/ci.yml  [.github/workflows/ci.yml]
```

The first line is the verdict. Then one line per check: whether it ran, was skipped or failed
to run, and why. Then each finding above `info`, most severe first, with its path and line.

<p align="center"><img src="diagrams/gate.svg" alt="How the gate picks its checks and reaches a verdict"></p>

The checks and conditions are the built-in rules; a rules file can change them. By default
`high` fails and `medium` and `low` warn.

## Rules

The built-in rules ([suite_gate/rules/default.json](../suite_gate/rules/default.json)):

| Check | When | Runs |
| --- | --- | --- |
| git-surface | always | `git surface --audit-json BASE` on REF |
| trust-path | a changed path matches `^\.github/workflows/`, `^\.gitea/workflows/` or `^\.forgejo/workflows/` | `trust-path --audit-json --ref REF` and the same at the merge base, with `--forge FORGE` when it is given. Only the paths REF adds are kept: a finding whose record is also at the merge base is left out, and the result's `exit` is 0 when none is left. If the merge base cannot be read, every path at REF is kept and the reason says so |
| release-drift | for each changed lockfile (`package-lock.json`, `npm-shrinkwrap.json`, `uv.lock`, `poetry.lock`, `requirements*.txt`) | `release-drift lockfile --audit-json` on its version at the merge base and at REF; a lockfile added or deleted by REF is skipped, since there is nothing to compare |
| git-overlap | always, if another branch exists under `refs/heads/` | `git footprint BASE` of REF and every other branch there, then `git overlap --audit-json --with REF` |

and the verdict: `high` fails; `medium` and `low` warn.

For a repository whose CI runs on Gitea or Forgejo, `--forge gitea` or `--forge forgejo` makes
trust-path apply that forge's workflow rules: which workflow directory it runs, its context
names and events (see trust-path's
[Gitea and Forgejo](https://github.com/jacob-adm/trust-path/blob/main/docs/commands.md#gitea-and-forgejo)).
It needs trust-path 0.9.0 or later. Without `--forge`, or with `--forge github`, trust-path is run
as before.

`--rules FILE` replaces the built-in rules with a file of the same shape:

```json
{
  "format": "gate-rules/1",
  "name": "default",
  "version": 1,
  "checks": [
    {"tool": "git-surface"},
    {"tool": "trust-path",
     "when_changed": ["^\\.github/workflows/", "^\\.gitea/workflows/", "^\\.forgejo/workflows/"]},
    {"tool": "release-drift", "for_each_changed": ["(^|/)(package-lock\\.json|...)$"]},
    {"tool": "git-overlap", "others": "refs/heads/"}
  ],
  "verdict": {"fail": ["high"], "warn": ["medium", "low"]}
}
```

- `checks` run in order. `tool` is one of `git-surface`, `trust-path`, `release-drift` and
  `git-overlap`. Patterns are Python regular expressions searched in each changed path.
- trust-path takes an optional `when_changed`; without it, it always runs. release-drift needs
  `for_each_changed`. git-overlap needs `others`, a ref prefix.
- `verdict.fail` and `verdict.warn` are lists of `high`, `medium` and `low`; a severity cannot be
  in both. A severity in neither does not affect the verdict.
- `ignore_paths`, optional, is a list of regular expressions. A finding whose path matches one
  does not count toward the verdict: a built bundle such as `dist/assets/index.js` can be left out
  this way. The finding is not removed. It stays in its tool's result unchanged, is listed under
  `ignored` in the gate result, and is counted on an `ignored` line of the text report. For a
  release-drift lockfile check the path matched is the lockfile's, since the finding's own path is
  inside the downloaded package. A check that could not run is never ignored.
- `warn_rules`, optional, is a list of rule ids such as `git-surface.ci`. A finding whose rule is
  listed and whose severity is in `verdict.fail` warns instead of failing; it still counts and is
  annotated as a warning. Use it for a rule that is too noisy to fail on in your repository, and
  remove the rule from the list when it is not. Findings of other rules are unchanged.
- Any other key, or a value of the wrong shape, is refused before anything runs (exit 2).

Change `name` or `version` when you change the rules: both, and the file's SHA-256, are in every
gate result, so a verdict always says which rules gave it.

## Verdict

From the findings of every check, in this order:

| Verdict | When | Exit |
| --- | --- | --- |
| `fail` | a finding has a severity in `verdict.fail` and its rule is not in `warn_rules` | 1 |
| `error` | otherwise, a check could not run (a tool missing, too old or timed out) or a tool reported an error | 2 |
| `warn` | otherwise, a finding has a severity in `verdict.warn`, or in `verdict.fail` with its rule in `warn_rules` | 0 |
| `pass` | otherwise | 0 |

A `fail` stands even when another check errored: what was found is certain. An error without
such a finding is `error`, never `pass`, because part of the branch was not checked.

If the gate cannot start (a bad rules file, BASE or REF not a commit, an argument that starts
with `-`), it writes one line to standard error and exits 2 without a result.

## JSON

With `--json` the gate prints one object:

| Key | Value |
| --- | --- |
| `format` | `gate-result/1` |
| `rules` | `name`, `version` and `sha256` of the rules file |
| `base`, `ref` | each `name` as given and the full `commit` it named |
| `merge_base` | the commit the changes are taken from |
| `changed` | the changed paths, sorted |
| `ignored` | each finding above `info` that the rules' `ignore_paths` left out of the verdict: `tool`, `rule`, `severity`, `path` (empty when none) |
| `checks` | one object per check run or skipped, in order: `tool`, `status` (`ran`, `skipped` or `error`), `reason`, `path` for a lockfile, `result` (the tool's audit result object; for trust-path, without the paths already at the merge base) or `error` (why it could not run) |
| `verdict`, `exit` | as above |

## Network

release-drift's lockfile check downloads both versions of each upgraded package from its
registry and asks the registry how each was published. `--lockfile-cache DIR` reads packages
from DIR instead (the layout of `release-drift lockfile --cache`) and asks no registry; the
tests use it. The other checks read only the repository.

## MCP

The MCP server's `gate` tool runs the gate with the built-in rules and returns the same object;
see [MCP server](mcp.md).
