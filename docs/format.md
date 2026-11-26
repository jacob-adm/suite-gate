# Audit result format 1

One JSON object describes one run of one audit tool. A tool writes it only when asked, with an
opt-in flag; its default output, its existing `--json` output and its exit status do not change.

The schema is [schema/audit-result-1.schema.json](../schema/audit-result-1.schema.json) (JSON
Schema 2020-12). The rules in [Exit status](#exit-status) cannot be written in JSON Schema;
`suite_gate.envelope.validate` checks both the schema and those rules with the standard library
only. Examples that pass are in [examples/valid](../examples/valid), and examples that fail, one
per broken rule, are in [examples/invalid](../examples/invalid).

## Object

| Key | Type | Meaning |
| --- | --- | --- |
| `format` | `"audit-result/1"` | This format. A change that breaks a reader gets a new number. |
| `tool` | object | `name` (lower case, digits and `-`) and `version` of the tool that ran. |
| `target` | object | What was audited: `kind` (`repository`, `artifact`, `package` or `host`), `name`, and optionally `ref` and `base`. |
| `exit` | 0, 1 or 2 | The tool's exit status for this run. |
| `findings` | array | One object per record the tool reported, in the tool's order. |
| `errors` | array | One object per error: `message`, and `path` when the error concerns one file. |

No other keys are allowed at any level except inside `record`.

## Finding

| Key | Type | Meaning |
| --- | --- | --- |
| `rule` | string | `<tool>.<name>`, lower case, for example `git-surface.ci`. Stable across versions of a tool. |
| `severity` | `high`, `medium`, `low` or `info` | Set by the tool's fixed mapping from rule to severity, never by a model. `info` is listed but is not a finding. |
| `message` | string | One line a person can read. |
| `evidence` | object | Where to look, with at least one of: `path`, `line` (from 1; needs `path`), `commit` (full 40- or 64-character lower-case hex id), `ref`, `url` (`https` only). |
| `record` | object | The tool's existing `--json` record for this finding, unchanged, so no information is lost. |

Evidence names only what the tool itself reported or resolved. A tool that does not know a line
number leaves `line` out rather than guess.

## Exit status

Every audit tool exits like `grep`, and the result must say the same thing:

| `exit` | Rule |
| --- | --- |
| 2 | `errors` is not empty. Findings from the parts that could be read are still listed. |
| 1 | `errors` is empty and at least one finding is not `info`. |
| 0 | `errors` is empty and every finding, if any, is `info`. |

A result whose `exit` breaks these rules is invalid. A reader that only needs a verdict can use
`exit`; a reader that needs the reason uses `findings` and `errors`.

## Mapping from each tool

The planned mapping. Each tool's opt-in flag builds the result from the records it already
prints, and the change that adds the flag to a tool confirms its row against those records:

| Tool | `target.kind` | `rule` from | `evidence` from | `info` records |
| --- | --- | --- | --- | --- |
| git-surface | `repository` | `class` | `path`, `ref` | none |
| trust-path | `repository` | `sink` | `workflow` file path, `ref` with `--ref` | none |
| release-drift | `artifact` or `package` | `category` and `status` | `path` | `file` records and categories listed as informational |
| git-overlap | `repository` | record kind | `path`, branch refs | none |
| pr-merge-audit | `repository` | record kind | commit, PR `url` | none |
| glassbox | `host` | command and `change` | `path` | removed items |

The severity of each rule is fixed per tool and documented in that tool's own commands page when
its flag ships.
