"""--forge: trust-path runs with Gitea's or Forgejo's rules, and the built-in rules
run it when their workflow directories change. A recording runner stands in for
the tools, so no audit tool needs to be installed."""
import os
import shutil
import subprocess
import tempfile
import unittest

from suite_gate import gate, mcp


class RecordingRunner(object):
    """Records each tool call and answers with an empty audit result."""

    def __init__(self):
        self.calls = []

    def exe(self, tool, command):
        return command

    def run(self, argv, stdin=b"", cwd=None):
        self.calls.append(argv)
        return 0, b"", b""

    def audit(self, tool, argv, stdin=b"", cwd=None):
        self.calls.append(argv)
        return {"format": "audit-result/1", "tool": {"name": tool, "version": "0"},
                "target": {"kind": "repository", "name": "r"}, "exit": 0, "findings": [],
                "errors": []}

    def trust_path(self):
        return [c for c in self.calls if c[0] == "trust-path"]


def git_out(repo, *args):
    return subprocess.run(["git"] + list(args), cwd=repo, check=True, stdout=subprocess.PIPE,
                          universal_newlines=True).stdout.strip()


def git(repo, *args):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"] + list(args),
                   cwd=repo, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class ForgeTests(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        git(self.repo, "init", "-q", "-b", "main")
        with open(os.path.join(self.repo, "README.md"), "w") as f:
            f.write("r\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "init")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def branch_changing(self, name, path):
        git(self.repo, "checkout", "-q", "-b", name, "main")
        full = os.path.join(self.repo, *path.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write("on: push\njobs:\n  j:\n    runs-on: x\n    steps:\n      - run: echo\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", name)
        git(self.repo, "checkout", "-q", "main")

    def run_gate(self, ref, **kw):
        runner = RecordingRunner()
        result = gate.gate(self.repo, "main", ref, runner=runner, **kw)
        status = [c for c in result["checks"] if c["tool"] == "trust-path"][0]
        return status, runner.trust_path()

    def test_gitea_and_forgejo_workflow_changes_run_trust_path(self):
        for path in (".gitea/workflows/ci.yml", ".forgejo/workflows/ci.yml",
                     ".github/workflows/ci.yml"):
            with self.subTest(path):
                name = path.split("/")[0].lstrip(".")
                self.branch_changing(name, path)
                status, calls = self.run_gate(name)
                self.assertEqual((status["status"], status["reason"]), ("ran", "changed: " + path))
                # REF, then the merge base, whose paths are left out
                self.assertEqual([c[c.index("--ref") + 1] for c in calls],
                                 [git_out(self.repo, "rev-parse", name),
                                  git_out(self.repo, "rev-parse", "main")])

    def test_forge_is_passed_to_trust_path_and_github_adds_nothing(self):
        self.branch_changing("ci", ".gitea/workflows/ci.yml")
        for forge in ("gitea", "forgejo"):
            with self.subTest(forge):
                _, calls = self.run_gate("ci", forge=forge)
                self.assertEqual(len(calls), 2)
                for argv in calls:
                    self.assertEqual(argv[argv.index("--forge") + 1], forge)
                    self.assertLess(argv.index("--forge"), argv.index("--"))
        for kw in ({}, {"forge": "github"}):
            _, calls = self.run_gate("ci", **kw)
            self.assertFalse(any("--forge" in argv for argv in calls))

    def test_unknown_forge_is_refused(self):
        with self.assertRaises(gate.GateError):
            gate.gate(self.repo, "main", "main", runner=RecordingRunner(), forge="gitlab")


class McpForgeTests(unittest.TestCase):
    def test_trust_path_tool_passes_forge(self):
        tmp = tempfile.mkdtemp()
        try:
            for args, want in (({}, None), ({"forge": "github"}, None),
                               ({"forge": "forgejo"}, "forgejo")):
                runner = RecordingRunner()
                mcp._trust_path(runner, dict(args, dir=tmp))
                argv = runner.calls[0]
                self.assertEqual(argv[argv.index("--forge") + 1] if "--forge" in argv else None,
                                 want, args)
            with self.assertRaises(mcp.ToolError):
                mcp._trust_path(RecordingRunner(), {"dir": tmp, "forge": "gitlab"})
        finally:
            shutil.rmtree(tmp)

    def test_schemas_offer_forge(self):
        for tool in ("gate", "trust_path"):
            schema = mcp.TOOLS[tool][1]
            self.assertEqual(schema["properties"]["forge"]["enum"], ["github", "gitea", "forgejo"])
            self.assertNotIn("forge", schema["required"])


if __name__ == "__main__":
    unittest.main()
