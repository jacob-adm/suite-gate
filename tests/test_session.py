# SPDX-License-Identifier: Apache-2.0
"""suite-gate session: glassbox persist before and after an agent session."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from suite_gate import mcp, session
from suite_gate.envelope import validate

from tests.test_mcp import glassbox_ready

ROOT = Path(__file__).resolve().parent.parent


def cli(*args, stdin="", env=None):
    env = dict(os.environ if env is None else env, PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, "-m", "suite_gate", "session"] + list(args), input=stdin,
                          env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=300)


@unittest.skipUnless(glassbox_ready(), "needs glassbox 0.6.0 or later on PATH")
class Session(unittest.TestCase):
    """Real glassbox on a temporary home: only the home's own locations are compared."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="suite-gate-session-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.state = os.path.join(self.tmp, "s.snapshot")
        self.env = dict(os.environ, XDG_STATE_HOME=os.path.join(self.tmp, "state"))

    def write(self, name, text):
        with open(os.path.join(self.home, name), "w") as handle:
            handle.write(text)

    def home_findings(self, result):
        """Findings under the temporary home; machine-wide locations can change on their own."""
        return [(f["rule"], f["severity"], f["message"]) for f in result["findings"]
                if f["evidence"]["path"].startswith("~/")]

    def test_save_then_check_reports_added_changed_removed(self):
        self.write(".zshrc", "a\n")
        self.write(".profile", "a\n")
        self.assertEqual(cli("save", "--state", self.state, "--home", self.home).returncode, 0)
        self.write(".zshrc", "b\n")
        os.remove(os.path.join(self.home, ".profile"))
        self.write(".bashrc", "x\n")
        proc = cli("check", "--state", self.state, "--home", self.home, "--json")
        result = json.loads(proc.stdout)
        self.assertEqual(validate(result), [])
        self.assertEqual(proc.returncode, result["exit"])
        self.assertEqual(sorted(self.home_findings(result)), [
            ("glassbox.persist.added", "high",
             "Persistence point ~/.bashrc (shell startup) was added since the snapshot"),
            ("glassbox.persist.changed", "high",
             "Persistence point ~/.zshrc (shell startup) changed since the snapshot"),
            ("glassbox.persist.removed", "info",
             "Persistence point ~/.profile (shell startup) was removed since the snapshot"),
        ])

    def test_text_report(self):
        cli("save", "--state", self.state, "--home", self.home)
        self.write(".zshrc", "x\n")
        proc = cli("check", "--state", self.state, "--home", self.home)
        self.assertEqual(proc.returncode, 1)
        lines = proc.stdout.splitlines()
        self.assertTrue(lines[0].startswith("suite-gate session: 1 added, 0 changed, 0 removed since "))
        self.assertIn("  Persistence point ~/.zshrc (shell startup) was added since the snapshot",
                      lines)

    def test_run_reports_what_the_command_left(self):
        script = "echo out; echo x > %s/.zshrc; exit 3" % self.home
        proc = cli("run", "--state", self.state, "--home", self.home, "--", "sh", "-c", script)
        self.assertEqual((proc.returncode, proc.stdout), (1, "out\n"))
        self.assertIn("was added since the snapshot", proc.stderr)

    def test_run_passes_the_command_status_through_when_nothing_changed(self):
        proc = cli("run", "--state", self.state, "--home", self.home, "--", "sh", "-c", "exit 3")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("0 added, 0 changed", proc.stderr)

    def test_run_needs_a_command(self):
        proc = cli("run", "--state", self.state, "--home", self.home, "--")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("give the command after --", proc.stderr)

    def test_hook_keeps_one_snapshot_per_session_and_removes_it(self):
        hook = json.dumps({"session_id": "abc-123", "hook_event_name": "SessionStart"})
        self.assertEqual(cli("save", "--hook", "--home", self.home, stdin=hook, env=self.env).returncode, 0)
        path = os.path.join(self.tmp, "state", "suite-gate", "sessions", "abc-123.snapshot")
        self.assertTrue(os.path.isfile(path))
        self.write(".zshrc", "x\n")
        end = json.dumps({"session_id": "abc-123", "hook_event_name": "SessionEnd"})
        proc = cli("check", "--hook", "--home", self.home, stdin=end, env=self.env)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(os.path.exists(path))

    def test_check_without_a_snapshot_is_an_error(self):
        proc = cli("check", "--state", self.state, "--home", self.home)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no snapshot at", proc.stderr)

    def test_default_state_file(self):
        proc = cli("save", "--home", self.home, env=self.env)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "state", "suite-gate",
                                                    "session.snapshot")))


class Rules(unittest.TestCase):
    def test_hook_input_must_carry_a_usable_session_id(self):
        for text in ("not json", "[]", "{}", '{"session_id": "../../etc/x"}',
                     '{"session_id": ""}', '{"session_id": 7}'):
            with self.subTest(text):
                with self.assertRaises(mcp.ToolError):
                    session.hook_state(text, {"XDG_STATE_HOME": "/s"})
        self.assertEqual(session.hook_state('{"session_id": "a-1.b_2"}', {"XDG_STATE_HOME": "/s"}),
                         os.path.join("/s", "suite-gate", "sessions", "a-1.b_2.snapshot"))

    def test_state_dir_without_xdg(self):
        self.assertTrue(session.state_dir({}).endswith(os.path.join(".local", "state", "suite-gate")))

    def test_missing_glassbox_is_an_error(self):
        bare = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, bare, True)
        proc = cli("save", "--state", os.path.join(bare, "s"), env=dict(os.environ, PATH=bare))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("glassbox is not installed", proc.stderr)

    def test_state_and_hook_are_exclusive(self):
        self.assertEqual(cli("save", "--state", "x", "--hook").returncode, 2)


if __name__ == "__main__":
    unittest.main()
