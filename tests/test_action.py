# SPDX-License-Identifier: Apache-2.0
"""suite-gate action and action.yml: the gate as a GitHub Actions step."""
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from suite_gate import action, gate

from tests import session_fixture
from tests.test_mcp import PINNED, installed

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(installed() == PINNED, "needs the audit tools in requirements-test.txt")
class PullRequestCheckout(unittest.TestCase):
    """A clone of the gate fixture as actions/checkout leaves it for a pull request: every
    branch under origin/, HEAD detached at the pull request's head."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="suite-gate-action-")
        root = os.path.realpath(cls.tmp)
        repo, cls.cache, home = session_fixture.build_gate(root)
        cls.env = session_fixture.env(home)
        cls.origin = repo

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def checkout(self, head, *extra):
        work = tempfile.mkdtemp(dir=self.tmp)
        subprocess.run(["git", "clone", "-q", *extra, "file://" + self.origin, work], check=True,
                       env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "-C", work, "checkout", "-q", "--detach", "origin/" + head],
                       check=True, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return work

    def run_action(self, head, work=None, **gate_env):
        work = work or self.checkout(head)
        temp = tempfile.mkdtemp(dir=self.tmp)
        files = {k: os.path.join(temp, k) for k in ("summary.md", "output.txt")}
        env = dict(self.env, PYTHONPATH=str(ROOT), GITHUB_WORKSPACE=work, GITHUB_BASE_REF="main",
                   GITHUB_HEAD_REF=head, RUNNER_TEMP=temp, GITHUB_STEP_SUMMARY=files["summary.md"],
                   GITHUB_OUTPUT=files["output.txt"], GATE_LOCKFILE_CACHE=self.cache, **gate_env)
        proc = subprocess.run([sys.executable, "-m", "suite_gate", "action"], cwd=work, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        read = {k: Path(v).read_text() if os.path.exists(v) else None for k, v in files.items()}
        return proc, read

    def test_workflow_change_fails_with_an_annotation(self):
        proc, files = self.run_action("ci")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertTrue(proc.stdout.startswith("FAIL: HEAD into origin/main (rules ci 1)\n"))
        self.assertIn("::error file=.github/workflows/ci.yml,title=git-surface.ci (high)::"
                      "HEAD modifies CI file .github/workflows/ci.yml\n", proc.stdout)
        self.assertIn("verdict=fail\n", files["output.txt"])
        self.assertIn("## suite-gate: FAIL", files["summary.md"])
        self.assertIn("| high | `git-surface.ci` | HEAD modifies CI file .github/workflows/ci.yml |",
                      files["summary.md"])

    def test_result_file_is_the_gate_result(self):
        proc, files = self.run_action("clean")
        path = re.search(r"^result=(.+)$", files["output.txt"], re.M).group(1)
        import json
        result = json.loads(Path(path).read_text())
        self.assertEqual((result["format"], result["verdict"]), ("gate-result/1", "pass"))

    def test_own_branch_is_not_an_overlap_but_others_are(self):
        proc, files = self.run_action("notes-a")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("verdict=warn\n", files["output.txt"])
        self.assertIn("::warning file=NOTES.md,title=git-overlap.overlap (low)::"
                      "HEAD and origin/notes-b both change NOTES.md\n", proc.stdout)
        self.assertNotIn("origin/notes-a", proc.stdout)

    def test_clean_pull_request_passes(self):
        proc, files = self.run_action("clean")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("verdict=pass\n", files["output.txt"])
        self.assertNotIn("::error", proc.stdout)
        self.assertNotIn("::warning", proc.stdout)

    def test_rules_file_from_the_repository(self):
        rules = Path(gate.BUILTIN["ci"]).read_text().replace('"fail": ["high"]', '"fail": []')
        rules = rules.replace('"warn": ["medium", "low"]', '"warn": ["high", "medium", "low"]')
        work = self.checkout("ci")
        Path(work, "gate-rules.json").write_text(rules)
        proc, files = self.run_action("ci", work=work, GATE_RULES="gate-rules.json")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("verdict=warn\n", files["output.txt"])
        self.assertIn("::warning file=.github/workflows/ci.yml", proc.stdout)

    def test_shallow_checkout_is_an_error(self):
        work = self.checkout("ci", "--depth", "1", "--no-single-branch")
        proc, files = self.run_action("ci", work=work)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("::error title=suite-gate::the checkout is shallow; check out with "
                      "fetch-depth: 0", proc.stdout)
        self.assertIsNone(files["output.txt"])

    def test_no_base_outside_a_pull_request(self):
        work = self.checkout("ci")
        env = {"GITHUB_WORKSPACE": work, "PATH": os.environ["PATH"]}
        out = io.StringIO()
        self.assertEqual(action.main(env, out), 2)
        self.assertIn("no base: set the base input", out.getvalue())


class Annotations(unittest.TestCase):
    rules = {"verdict": {"fail": ["high"], "warn": ["medium"]}}

    def result(self, findings, errors=False):
        check = {"tool": "t", "status": "ran", "reason": "r",
                 "result": {"findings": findings, "errors": []}}
        checks = [check] + ([{"tool": "x", "status": "error", "reason": "r",
                              "error": "x is not installed"}] if errors else [])
        return {"checks": checks}

    def test_levels_and_escaping(self):
        findings = [
            {"rule": "a.b", "severity": "high", "message": "50% done\nnext",
             "evidence": {"path": "dir/a,b:c.py", "line": 7}},
            {"rule": "a.c", "severity": "medium", "message": "m", "evidence": {"path": "x"}},
            {"rule": "a.d", "severity": "low", "message": "ignored", "evidence": {"path": "x"}},
            {"rule": "a.e", "severity": "info", "message": "ignored", "evidence": {"path": "x"}},
            {"rule": "a.f", "severity": "high", "message": "home", "evidence": {"path": "~/.ssh"}},
        ]
        self.assertEqual(action.annotations(self.result(findings, errors=True), self.rules), [
            "::error file=dir/a%2Cb%3Ac.py,line=7,title=a.b (high)::50%25 done%0Anext",
            "::warning file=x,title=a.c (medium)::m",
            "::error title=a.f (high)::home",
            "::error title=x did not run::x is not installed",
        ])

    def test_summary_escapes_table_cells(self):
        result = {"verdict": "warn", "ref": {"name": "r", "commit": "a" * 40},
                  "base": {"name": "b", "commit": "b" * 40},
                  "rules": {"name": "ci", "version": 1},
                  "checks": [{"tool": "t", "status": "ran", "reason": "always runs",
                              "result": {"errors": [], "findings": [
                                  {"rule": "t.x", "severity": "medium", "message": "a | b",
                                   "evidence": {"path": "p", "line": 3, "commit": "c" * 40}}]}}]}
        text = action.summary(result)
        self.assertIn("| medium | `t.x` | a \\| b | p:3 @ cccccccccccc |", text)
        self.assertIn("| t | ran (always runs) | 1 medium |", text)


class ActionYml(unittest.TestCase):
    """action.yml follows the rules of the tested workflows: pinned actions, no expression in a
    script, inputs passed through env."""

    def setUp(self):
        self.text = (ROOT / "action.yml").read_text()

    def test_actions_are_pinned_to_a_commit(self):
        uses = re.findall(r"uses: (\S+)", self.text)
        self.assertTrue(uses)
        for ref in uses:
            self.assertRegex(ref, r"@[0-9a-f]{40}$")

    def test_no_expression_inside_a_script(self):
        runs = re.findall(r"^\s*run: (.*)$", self.text, re.M)
        self.assertEqual(len(runs), 2)
        for line in runs:
            self.assertNotIn("${{", line)

    def test_files_it_installs_exist(self):
        self.assertIn('-r "$ACTION_PATH/requirements-tools.txt"', self.text)
        tools = (ROOT / "requirements-tools.txt").read_text().split()
        self.assertEqual(tools, ["%s==%s" % (t, v) for t, v in PINNED.items()
                                 if t != "pr-merge-audit"])

    def test_builtin_ci_rules_differ_only_in_branches_and_name(self):
        default = Path(gate.BUILTIN["default"]).read_text()
        ci = Path(gate.BUILTIN["ci"]).read_text()
        self.assertEqual(ci.replace('"ci"', '"default"').replace("refs/remotes/origin/", "refs/heads/"),
                         default)


if __name__ == "__main__":
    unittest.main()
