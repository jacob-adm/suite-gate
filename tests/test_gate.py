# SPDX-License-Identifier: Apache-2.0
"""suite-gate gate: verdicts from the released tools on a fixture repository, and the rules."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from suite_gate import gate, mcp
from suite_gate.envelope import validate

from tests import session_fixture
from tests.test_mcp import PINNED, installed

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(installed() == PINNED, "needs the audit tools in requirements-test.txt")
class Verdicts(unittest.TestCase):
    """One branch per verdict; release-drift reads a package cache, so no registry is asked."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="suite-gate-gate-")
        root = os.path.realpath(cls.tmp)
        cls.repo, cls.cache, home = session_fixture.build_gate(root)
        cls.env = dict(session_fixture.env(home), PYTHONPATH=str(ROOT))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_gate(self, ref, *extra, env=None):
        proc = subprocess.run([sys.executable, "-m", "suite_gate", "gate", "--repo", self.repo,
                               "--lockfile-cache", self.cache, "--json", "main", ref] + list(extra),
                              env=env or self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True)
        result = json.loads(proc.stdout) if proc.stdout else None
        if result is not None:
            self.assertEqual(result["exit"], proc.returncode)
            for check in result["checks"]:
                if "result" in check:
                    self.assertEqual(validate(check["result"]), [])
        return proc, result

    def statuses(self, result):
        return [(c["tool"], c["status"]) for c in result["checks"]]

    def test_clean_branch_passes(self):
        proc, result = self.run_gate("clean")
        self.assertEqual((proc.returncode, result["verdict"]), (0, "pass"))
        self.assertEqual(self.statuses(result), [("git-surface", "ran"), ("trust-path", "skipped"),
                                                 ("release-drift", "skipped"), ("git-overlap", "ran")])
        self.assertEqual(result["changed"], ["app.py"])

    def test_workflow_change_fails_and_runs_trust_path(self):
        proc, result = self.run_gate("ci")
        self.assertEqual((proc.returncode, result["verdict"]), (1, "fail"))
        trust = [c for c in result["checks"] if c["tool"] == "trust-path"][0]
        self.assertEqual((trust["status"], trust["reason"]), ("ran", "changed: .github/workflows/ci.yml"))
        surface = [c for c in result["checks"] if c["tool"] == "git-surface"][0]["result"]
        self.assertEqual([(f["rule"], f["severity"]) for f in surface["findings"]],
                         [("git-surface.ci", "high")])

    def test_overlap_alone_warns(self):
        proc, result = self.run_gate("notes-a")
        self.assertEqual((proc.returncode, result["verdict"]), (0, "warn"))
        overlap = [c for c in result["checks"] if c["tool"] == "git-overlap"][0]["result"]
        self.assertEqual(overlap["findings"][0]["message"], "notes-a and notes-b both change NOTES.md")

    def test_lockfile_upgrade_runs_release_drift(self):
        proc, result = self.run_gate("deps")
        self.assertEqual((proc.returncode, result["verdict"]), (1, "fail"))
        drift = [c for c in result["checks"] if c["tool"] == "release-drift"][0]
        self.assertEqual((drift["path"], drift["reason"]), ("requirements.txt", "changed: requirements.txt"))
        high = [f["message"] for f in drift["result"]["findings"] if f["severity"] == "high"]
        self.assertEqual(high, ["demo 1.0 -> 1.1: New .pth file demo_init.pth, with an import line "
                                "that Python runs at every start"])

    def test_new_lockfile_is_skipped_with_its_reason(self):
        _, result = self.run_gate("newlock")
        drift = [c for c in result["checks"] if c["tool"] == "release-drift"][0]
        self.assertEqual((drift["status"], drift["reason"]),
                         ("skipped", "package-lock.json added; nothing to compare"))

    def test_results_are_the_tools_own(self):
        """The gate adds nothing to a finding: git-surface run by hand gives the same object."""
        _, result = self.run_gate("ci")
        embedded = [c for c in result["checks"] if c["tool"] == "git-surface"][0]["result"]
        proc = subprocess.run([shutil.which("git-surface"), "--audit-json", "main"], input="ci\n",
                              cwd=self.repo, env=self.env, stdout=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(embedded, json.loads(proc.stdout))

    def test_result_names_rules_and_commits(self):
        _, result = self.run_gate("clean")
        data = Path(gate.DEFAULT_RULES).read_bytes()
        self.assertEqual(result["rules"], {"name": "default", "version": 1,
                                           "sha256": hashlib.sha256(data).hexdigest()})
        head = subprocess.run(["git", "-C", self.repo, "rev-parse", "clean"], stdout=subprocess.PIPE,
                              universal_newlines=True, env=self.env).stdout.strip()
        self.assertEqual(result["ref"], {"name": "clean", "commit": head})

    def test_text_output(self):
        proc = subprocess.run([sys.executable, "-m", "suite_gate", "gate", "--repo", self.repo,
                               "--lockfile-cache", self.cache, "main", "ci"], env=self.env,
                              stdout=subprocess.PIPE, universal_newlines=True)
        lines = proc.stdout.splitlines()
        self.assertEqual(lines[0], "FAIL: ci into main (rules default 1)")
        self.assertIn("  trust-path     ran      nothing found (changed: .github/workflows/ci.yml)", lines)
        self.assertEqual(lines[-1], "high   git-surface.ci  ci modifies CI file .github/workflows/ci.yml"
                                    "  [.github/workflows/ci.yml]")

    def test_documented_example_is_real_output(self):
        proc = subprocess.run([sys.executable, "-m", "suite_gate", "gate", "--repo", self.repo,
                               "--lockfile-cache", self.cache, "main", "ci"], env=self.env,
                              stdout=subprocess.PIPE, universal_newlines=True)
        text = (ROOT / "docs" / "gate.md").read_text()
        block = text.split("For the `ci` branch", 1)[1].split("```\n", 1)[1].split("```", 1)[0]
        self.assertEqual(block, proc.stdout)

    def test_missing_tools_make_an_error_verdict(self):
        """With no audit tool on PATH every check errors, and the gate cannot pass."""
        bare = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, bare, True)
        os.symlink(shutil.which("git"), os.path.join(bare, "git"))
        proc, result = self.run_gate("clean", env=dict(self.env, PATH=bare))
        self.assertEqual((proc.returncode, result["verdict"]), (2, "error"))
        surface = result["checks"][0]
        self.assertEqual(surface["error"], "git-surface is not installed: pip install 'git-surface>=0.4.0'")

    def test_unknown_ref_is_a_usage_error(self):
        proc, result = self.run_gate("nope")
        self.assertEqual((proc.returncode, result), (2, None))
        self.assertEqual(proc.stderr, "suite-gate: not a commit: nope\n")


def check(tool="git-surface", severities=(), exit=None, status="ran"):
    """A check entry holding a result with findings of SEVERITIES."""
    findings = [{"severity": s} for s in severities]
    found = any(s != "info" for s in severities)
    result = {"findings": findings, "exit": exit if exit is not None else (1 if found else 0)}
    return {"tool": tool, "status": status, "result": result}


class Precedence(unittest.TestCase):
    """fail, then error, then warn, then pass."""

    def setUp(self):
        self.rules = gate.load_rules()[0]

    def test_order(self):
        cases = [
            ([check(severities=["low"]), check(severities=["high"])], "fail"),
            ([check(exit=2), check(severities=["high"])], "fail"),
            ([check(exit=2), check(severities=["medium"])], "error"),
            ([{"tool": "x", "status": "error", "error": "e"}, check(severities=["low"])], "error"),
            ([check(severities=["medium", "info"])], "warn"),
            ([check(severities=["info"]), {"tool": "x", "status": "skipped"}], "pass"),
            ([], "pass"),
        ]
        for checks, want in cases:
            with self.subTest(want=want, checks=checks):
                self.assertEqual(gate.verdict(checks, self.rules), want)

    def test_rules_decide_what_fails(self):
        rules = dict(self.rules, verdict={"fail": ["high", "medium"], "warn": ["low"]})
        self.assertEqual(gate.verdict([check(severities=["medium"])], rules), "fail")


class Rules(unittest.TestCase):
    def write(self, rules):
        path = os.path.join(tempfile.mkdtemp(), "rules.json")
        self.addCleanup(shutil.rmtree, os.path.dirname(path), True)
        with open(path, "w") as handle:
            json.dump(rules, handle)
        return path

    def test_default_rules_load(self):
        rules, sha, path = gate.load_rules()
        self.assertEqual((rules["name"], rules["version"]), ("default", 1))
        self.assertEqual([c["tool"] for c in rules["checks"]],
                         ["git-surface", "trust-path", "release-drift", "git-overlap"])

    def test_bad_rules_are_refused(self):
        base = json.loads(Path(gate.DEFAULT_RULES).read_text())
        cases = [
            (dict(base, extra=1), "rules: unknown key extra"),
            (dict(base, format="gate-rules/2"), "rules.format: not gate-rules/1"),
            (dict(base, checks=[{"tool": "nmap"}]), "rules.checks[0].tool: one of"),
            (dict(base, checks=[{"tool": "git-overlap"}]), "others is required for git-overlap"),
            (dict(base, checks=[{"tool": "git-surface", "others": "refs/heads/"}]),
             "unknown key others for git-surface"),
            (dict(base, checks=[{"tool": "trust-path", "when_changed": ["("]}]),
             "rules.checks[0].when_changed:"),
            (dict(base, verdict={"fail": ["high"], "warn": ["high"]}), "cannot both fail and warn"),
            (dict(base, verdict={"fail": ["critical"], "warn": []}), "rules.verdict.fail:"),
            (dict(base, version="1"), "version (an integer)"),
        ]
        for rules, text in cases:
            with self.subTest(text):
                with self.assertRaises(gate.GateError) as ctx:
                    gate.load_rules(self.write(rules))
                self.assertIn(text, str(ctx.exception))

    def test_gate_through_mcp_reports_errors_as_tool_errors(self):
        with self.assertRaises(mcp.ToolError) as ctx:
            mcp.call(mcp.Runner(5), "gate", {"repo": tempfile.gettempdir(), "base": "main",
                                             "ref": "-x"})
        self.assertIn("must not start with '-'", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
