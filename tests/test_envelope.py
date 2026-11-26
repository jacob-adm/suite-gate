# SPDX-License-Identifier: Apache-2.0
import copy
import json
import unittest
from pathlib import Path

from suite_gate.envelope import validate

ROOT = Path(__file__).resolve().parent.parent
VALID = sorted((ROOT / "examples" / "valid").glob("*.json"))
INVALID = sorted((ROOT / "examples" / "invalid").glob("*.json"))

# Each invalid example and the problem validate() must name for it.
EXPECTED = {
    "bad-severity": "findings[0].severity: not one of",
    "bad-target-kind": "target.kind: not one of",
    "empty-evidence": "findings[0].evidence: empty",
    "exit-0-with-finding": "result.exit: is 0, must be 1",
    "exit-1-info-only": "result.exit: is 1, must be 0",
    "exit-1-with-error": "result.exit: is 1, must be 2",
    "exit-3": "result.exit: not 0, 1 or 2",
    "http-url": "findings[0].evidence.url: not an https URL",
    "line-without-path": "findings[0].evidence.line: needs path",
    "missing-record": "findings[0]: missing record",
    "short-commit": "findings[0].evidence.commit: not a full hex object id",
    "unknown-key": "result: unknown key verdict",
    "wrong-format": "result.format: not audit-result/1",
}

# Invalid only by the exit rules, which the JSON Schema cannot express.
EXIT_RULES_ONLY = {"exit-0-with-finding", "exit-1-info-only", "exit-1-with-error"}


def load(path):
    return json.loads(path.read_text())


class ExampleTests(unittest.TestCase):
    def test_examples_present(self):
        self.assertGreaterEqual(len(VALID), 5)
        self.assertEqual(sorted(EXPECTED), [p.stem for p in INVALID])

    def test_valid_examples_pass(self):
        for path in VALID:
            with self.subTest(path.name):
                self.assertEqual(validate(load(path)), [])

    def test_invalid_examples_fail_for_their_reason(self):
        for path in INVALID:
            with self.subTest(path.name):
                problems = validate(load(path))
                self.assertTrue(any(EXPECTED[path.stem] in p for p in problems), problems)


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.doc = load(ROOT / "examples" / "valid" / "git-surface-finding.json")

    def test_not_an_object(self):
        self.assertEqual(validate([]), ["result: not an object"])

    def test_line_with_path_is_valid(self):
        self.doc["findings"][0]["evidence"] = {"path": "a.py", "line": 3}
        self.assertEqual(validate(self.doc), [])

    def test_line_zero_and_bool_rejected(self):
        for line in (0, True, 1.5):
            doc = copy.deepcopy(self.doc)
            doc["findings"][0]["evidence"] = {"path": "a.py", "line": line}
            with self.subTest(line=line):
                self.assertIn("findings[0].evidence.line: not an integer >= 1", validate(doc))

    def test_sha256_commit_accepted(self):
        self.doc["findings"][0]["evidence"]["commit"] = "a" * 64
        self.assertEqual(validate(self.doc), [])

    def test_uppercase_commit_rejected(self):
        self.doc["findings"][0]["evidence"]["commit"] = "A" * 40
        self.assertTrue(validate(self.doc))

    def test_error_wins_over_findings(self):
        self.doc["errors"] = [{"message": "ref has no merge base", "path": "x"}]
        self.doc["exit"] = 2
        self.assertEqual(validate(self.doc), [])

    def test_exit_rule_not_reported_on_broken_document(self):
        self.doc["findings"][0]["severity"] = "critical"
        self.doc["exit"] = 0
        problems = validate(self.doc)
        self.assertFalse(any(p.startswith("result.exit") for p in problems), problems)

    def test_bool_exit_rejected(self):
        self.doc["exit"] = True
        self.assertIn("result.exit: not 0, 1 or 2", validate(self.doc))

    def test_record_kept_as_given(self):
        self.doc["findings"][0]["record"] = {"anything": [1, {"nested": None}]}
        self.assertEqual(validate(self.doc), [])


try:
    import jsonschema
except ImportError:  # the agreement check needs the jsonschema package
    jsonschema = None


@unittest.skipIf(jsonschema is None, "jsonschema not installed")
class SchemaAgreementTests(unittest.TestCase):
    """The JSON Schema file and validate() agree on every example."""

    def setUp(self):
        schema = load(ROOT / "schema" / "audit-result-1.schema.json")
        jsonschema.Draft202012Validator.check_schema(schema)
        self.schema = jsonschema.Draft202012Validator(schema)

    def test_valid_examples_pass_schema(self):
        for path in VALID:
            with self.subTest(path.name):
                self.assertEqual(list(self.schema.iter_errors(load(path))), [])

    def test_invalid_examples(self):
        for path in INVALID:
            errors = list(self.schema.iter_errors(load(path)))
            with self.subTest(path.name):
                if path.stem in EXIT_RULES_ONLY:
                    self.assertEqual(errors, [])
                else:
                    self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
