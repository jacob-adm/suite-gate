# SPDX-License-Identifier: Apache-2.0
"""suite-gate validate and the command line."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def cli(*args, data=None):
    return subprocess.run([sys.executable, "-m", "suite_gate"] + list(args), cwd=ROOT, input=data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)


class Validate(unittest.TestCase):
    def test_valid_file_exits_0(self):
        out = cli("validate", "examples/valid/git-surface-finding.json")
        self.assertEqual((out.returncode, out.stdout), (0, ""))

    def test_invalid_file_prints_each_problem_and_exits_1(self):
        out = cli("validate", "examples/invalid/exit-0-with-finding.json")
        self.assertEqual(out.returncode, 1)
        self.assertEqual(out.stdout, "result.exit: is 0, must be 1 with 1 finding(s) above info\n")

    def test_standard_input(self):
        text = (ROOT / "examples" / "valid" / "clean.json").read_text()
        self.assertEqual(cli("validate", data=text).returncode, 0)

    def test_unreadable_input_exits_2(self):
        for args, data in ((("validate", "no-such-file.json"), None), (("validate",), "not json")):
            with self.subTest(args):
                out = cli(*args, data=data)
                self.assertEqual(out.returncode, 2)
                self.assertTrue(out.stderr.startswith("suite-gate: "))

    def test_mcp_timeout_must_be_positive(self):
        self.assertEqual(cli("mcp", "--timeout", "0").returncode, 2)


if __name__ == "__main__":
    unittest.main()
