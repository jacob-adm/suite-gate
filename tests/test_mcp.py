# SPDX-License-Identifier: Apache-2.0
"""The MCP server: a recorded session replayed against the released audit tools, and its rules."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from suite_gate import __version__, mcp
from suite_gate.envelope import validate

from tests import session_fixture

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "mcp"
# The released versions the recording was made with (requirements-test.txt).
PINNED = {"git-surface": "0.5.0", "trust-path": "0.10.0", "release-drift": "0.7.0",
          "git-overlap": "0.7.0", "pr-merge-audit": "2.3.0"}


def installed():
    """{tool: version} for the Python audit tools on PATH."""
    runner = mcp.Runner(60)
    return {t: runner.version(t, c) for t, c in mcp.COMMANDS if t in PINNED}


def serve(lines, env):
    """Run `python -m suite_gate mcp` on LINES; return its stdout."""
    env = dict(env, PYTHONPATH=str(ROOT))
    proc = subprocess.run([sys.executable, "-m", "suite_gate", "mcp"], input=lines, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                          timeout=600)
    return proc.stdout


@unittest.skipUnless(installed() == PINNED, "needs the audit tools in requirements-test.txt")
class RecordedSession(unittest.TestCase):
    """Fixture inputs, the released tools, and the session recorded with them."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="suite-gate-mcp-")
        cls.root = os.path.realpath(cls.tmp)
        cls.env = session_fixture.env(session_fixture.build(cls.root))
        # The root as it appears inside a JSON string.
        cls.token = json.dumps(cls.root)[1:-1]
        requests = (FIXTURES / "requests.jsonl").read_text().replace("{ROOT}", cls.token)
        cls.out = serve(requests, cls.env)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def replies(self):
        return [json.loads(line) for line in self.out.splitlines()]

    def test_replays_recorded_session_exactly(self):
        """Replies equal the recording byte for byte, apart from the root path and our version."""
        got = self.out.replace(self.token, "{ROOT}")
        want = (FIXTURES / "responses.jsonl").read_text()
        recorded = json.loads(want.splitlines()[0])["result"]["serverInfo"]["version"]
        got = got.replace('"version":"%s"' % __version__, '"version":"%s"' % recorded, 1)
        self.assertEqual(got, want)

    def test_every_tool_result_is_a_valid_audit_result(self):
        """Each successful call returns an object the validator accepts, as text and structure."""
        results = [r["result"] for r in self.replies()
                   if "result" in r and "structuredContent" in r["result"]]
        self.assertGreaterEqual(len(results), 9)
        for result in results:
            doc = result["structuredContent"]
            self.assertEqual(validate(doc), [])
            self.assertEqual(json.loads(result["content"][0]["text"]), doc)
            self.assertFalse(result["isError"])

    def test_findings_are_the_tools_own(self):
        """The server adds nothing: a call equals the tool run by hand."""
        by_id = {r["id"]: r for r in self.replies()}
        doc = by_id[3]["result"]["structuredContent"]
        proc = subprocess.run([shutil.which("git-surface"), "--audit-json", "main"],
                              input=b"agent/ci\nagent/docs\nb1\n", cwd=os.path.join(self.root, "demo"),
                              env=self.env, stdout=subprocess.PIPE)
        self.assertEqual(doc, json.loads(proc.stdout))
        self.assertEqual(doc["exit"], proc.returncode)

    def test_errors_are_tool_errors_not_results(self):
        """Bad arguments and unknown tools are isError results with a reason."""
        by_id = {r["id"]: r for r in self.replies()}
        for i, text in ((13, "argument refs: must not start with '-'"),
                        (15, "unknown argument: extra"), (16, "unknown tool 'no_such_tool'")):
            with self.subTest(i):
                self.assertTrue(by_id[i]["result"]["isError"])
                self.assertEqual(by_id[i]["result"]["content"][0]["text"], text)
        self.assertIn("is not a directory", by_id[14]["result"]["content"][0]["text"])
        # An unknown BASE is the tool's own error object (exit 2), returned as a result.
        doc = by_id[12]["result"]["structuredContent"]
        self.assertEqual((doc["exit"], doc["findings"]), (2, []))
        self.assertEqual(by_id[18]["error"]["code"], -32601)
        self.assertEqual(by_id[None]["error"]["code"], -32700)


def glassbox_ready():
    runner = mcp.Runner(30)
    version = runner.version("glassbox", "glassbox")
    return version is not None and mcp._at_least(version, mcp.MINIMUM["glassbox"])


@unittest.skipUnless(glassbox_ready(), "needs glassbox 0.6.0 or later on PATH")
class Glassbox(unittest.TestCase):
    """glassbox reach and persist, outside the recording: their location lists differ by OS."""

    def test_reach_and_persist(self):
        home = tempfile.mkdtemp(prefix="suite-gate-gb-")
        self.addCleanup(shutil.rmtree, home, True)
        os.makedirs(os.path.join(home, ".ssh"))
        runner = mcp.Runner(120)
        doc = mcp.call(runner, "glassbox_reach", {"home": home})
        self.assertEqual(validate(doc), [])
        ssh = [f for f in doc["findings"] if f["evidence"]["path"] == "~/.ssh"]
        self.assertEqual((ssh[0]["rule"], ssh[0]["severity"]), ("glassbox.reach.readable", "high"))
        snapshot = os.path.join(home, "snap")
        subprocess.run([shutil.which("glassbox"), "persist", "--save", snapshot, "--home", home],
                       check=True, stdout=subprocess.PIPE)
        with open(os.path.join(home, ".zshrc"), "w") as handle:
            handle.write("x\n")
        doc = mcp.call(runner, "glassbox_persist", {"since": snapshot, "home": home})
        self.assertEqual(validate(doc), [])
        zshrc = [f for f in doc["findings"] if f["evidence"]["path"] == "~/.zshrc"]
        self.assertEqual((zshrc[0]["rule"], zshrc[0]["severity"]), ("glassbox.persist.added", "high"))


class Rules(unittest.TestCase):
    """Argument checks and the checks on what a tool prints, without running a tool."""

    def call(self, name, args, runner=None):
        return mcp.call(runner or mcp.Runner(5), name, args)

    def test_option_like_and_unsafe_values_are_refused(self):
        for value in ("-x", "--output=f", "a\nb", "a\tb", "", 3):
            with self.subTest(value):
                with self.assertRaises(mcp.ToolError):
                    mcp._text({"k": value}, "k")

    def test_pairs_must_be_two_refs(self):
        for pairs in ([], [["a"]], [["a", "b", "c"]], "a b", [["a", "-b"]]):
            with self.subTest(pairs):
                with self.assertRaises(mcp.ToolError):
                    mcp._pairs({"pairs": pairs})

    def test_registry_must_be_known(self):
        with self.assertRaises(mcp.ToolError) as ctx:
            self.call("release_drift_provenance", {"registry": "cargo", "name": "x", "old": "1",
                                                   "new": "2"})
        self.assertIn("pypi or npm", str(ctx.exception))

    def test_missing_tool_says_how_to_install(self):
        runner = mcp.Runner(5)
        old = os.environ.get("PATH", "")
        os.environ["PATH"] = tempfile.mkdtemp()
        try:
            with self.assertRaises(mcp.ToolError) as ctx:
                runner.exe("trust-path", "trust-path")
        finally:
            os.environ["PATH"] = old
        self.assertEqual(str(ctx.exception),
                         "trust-path is not installed: pip install 'trust-path>=0.8.1'")

    def test_output_that_is_not_an_audit_result_is_an_error(self):
        """A tool too old for --audit-json, or one printing an invalid object, is refused."""
        script = [sys.executable, "-c"]
        runner = mcp.Runner(30)
        with self.assertRaises(mcp.ToolError) as ctx:
            runner.audit("trust-path", script + ["import sys; sys.stderr.write('no such flag\\n'); "
                                                 "sys.exit(2)"])
        self.assertEqual(str(ctx.exception), "trust-path did not print an audit result (exit 2): "
                                             "no such flag; --audit-json needs trust-path 0.8.1 "
                                             "or later")
        bad = json.dumps({"format": "audit-result/1"})
        with self.assertRaises(mcp.ToolError) as ctx:
            runner.audit("trust-path", script + ["print(%r)" % bad])
        self.assertIn("not a valid audit-result/1", str(ctx.exception))

    def test_exit_status_must_match_the_object(self):
        doc = {"format": "audit-result/1", "tool": {"name": "trust-path", "version": "0.8.1"},
               "target": {"kind": "repository", "name": "x"}, "exit": 0, "findings": [],
               "errors": []}
        runner = mcp.Runner(30)
        argv = [sys.executable, "-c", "import sys; print(%r); sys.exit(1)" % json.dumps(doc)]
        with self.assertRaises(mcp.ToolError) as ctx:
            runner.audit("trust-path", argv)
        self.assertIn("exited 1", str(ctx.exception))
        argv[-1] = "print(%r)" % json.dumps(dict(doc, tool={"name": "glassbox", "version": "1"}))
        with self.assertRaises(mcp.ToolError):
            runner.audit("trust-path", argv)

    def test_timeout_is_a_tool_error(self):
        with self.assertRaises(mcp.ToolError) as ctx:
            mcp.Runner(1).run([sys.executable, "-c", "import time; time.sleep(5)"])
        self.assertIn("did not finish within 1 seconds", str(ctx.exception))

    def test_versions_compare_numerically(self):
        self.assertTrue(mcp._at_least("0.10.0", "0.8.1"))
        self.assertFalse(mcp._at_least("0.7.9", "0.8.1"))
        self.assertFalse(mcp._at_least("unknown", "0.8.1"))

    def test_every_tool_is_read_only_and_schemas_list_their_arguments(self):
        tools = mcp.tools()
        self.assertEqual(len(tools), 1 + len(mcp.TOOLS))
        for tool in tools:
            self.assertTrue(tool["annotations"]["readOnlyHint"])
            self.assertFalse(tool["inputSchema"].get("additionalProperties", False))
        network = {t["name"] for t in tools if t["annotations"]["openWorldHint"]}
        self.assertEqual(network, {"gate", "release_drift_lockfile", "release_drift_provenance"})


if __name__ == "__main__":
    unittest.main()
