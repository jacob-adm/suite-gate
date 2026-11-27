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


class Readme(unittest.TestCase):
    def test_version_shown_is_the_version(self):
        out = cli("--version").stdout
        text = (ROOT / "README.md").read_text()
        shown = text.split("suite-gate --version", 1)[1].split("```text\n", 1)[1].split("```", 1)[0]
        self.assertEqual(shown, out)

    def test_every_command_in_the_readme_exists(self):
        for command in ("gate", "mcp", "validate"):
            with self.subTest(command):
                self.assertEqual(cli(command, "--help").returncode, 0)


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
