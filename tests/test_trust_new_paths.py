"""suite-gate gate: the trust-path check reports only the paths REF adds to the merge base."""
import os
import shutil
import subprocess
import tempfile
import unittest

from suite_gate import gate
from tests.test_mcp import PINNED, installed

# A pull request title in a run: line under pull_request_target reaches the secret.
GREET = """on: pull_request_target
jobs:
  greet:
    runs-on: ubuntu-latest
    steps:
      - name: Greet
        run: echo "${{ github.event.pull_request.title }}"
        env:
          TOKEN: ${{ secrets.%s }}
"""


def git(repo, *args):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"] + list(args),
                   cwd=repo, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@unittest.skipUnless(installed().get("trust-path") == PINNED["trust-path"],
                     "needs trust-path from requirements-tools.txt")
class NewPathsTests(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        git(self.repo, "init", "-q", "-b", "main")
        self.commit("main", {".github/workflows/greet.yml": GREET % "OLD"})

    def commit(self, branch, files):
        if branch != "main":
            git(self.repo, "checkout", "-q", "-b", branch, "main")
        for path, text in files.items():
            full = os.path.join(self.repo, *path.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(text)
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", branch)
        git(self.repo, "checkout", "-q", "main")

    def trust(self, ref):
        result = gate.gate(self.repo, "main", ref)
        return [c for c in result["checks"] if c["tool"] == "trust-path"][0], result

    def test_path_already_on_the_base_is_not_reported(self):
        self.commit("edit", {".github/workflows/greet.yml": GREET % "OLD" + "# edited\n"})
        check, _ = self.trust("edit")
        self.assertEqual((check["status"], check["result"]["findings"], check["result"]["exit"]),
                         ("ran", [], 0))

    def test_path_the_branch_adds_is_reported(self):
        self.commit("add", {".github/workflows/other.yml": GREET % "NEW"})
        check, result = self.trust("add")
        found = check["result"]["findings"]
        self.assertEqual(sorted(f["record"]["sink"] for f in found),
                         ["permissions:default", "secrets.NEW"])
        self.assertEqual(set(f["record"]["workflow"] for f in found), {".github/workflows/other.yml"})
        self.assertEqual(check["result"]["exit"], 1)
        self.assertEqual(result["verdict"], "fail")
