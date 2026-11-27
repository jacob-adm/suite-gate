# SPDX-License-Identifier: Apache-2.0
"""Inputs for the recorded MCP session: a git repository, two sdists and a results file.

Everything is built the same way on every run (fixed names, contents, author and dates), so
the audit tools give the same output and the session replays byte for byte.
"""
import io
import json
import os
import subprocess
import tarfile

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
}

WORKFLOW = """on: pull_request_target
jobs:
  greet:
    runs-on: ubuntu-latest
    steps:
      - name: Post greeting
        run: echo "${{ github.event.pull_request.title }}"
        env:
          TOKEN: ${{ secrets.BOT_TOKEN }}
"""


def env(home):
    """The environment the server and tools run in: no user or system git config."""
    out = {k: v for k, v in os.environ.items()
           if not k.startswith(("GIT_", "PYTHON")) and k not in ("HOME",)}
    out.update(GIT_ENV, HOME=home)
    return out


def _git(repo, home, *args):
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull]
                   + list(args), cwd=repo, env=env(home), check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _write(repo, files):
    for name, text in files.items():
        path = os.path.join(repo, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="\n") as handle:
            handle.write(text)


def _commit(repo, home, message, files):
    _write(repo, files)
    _git(repo, home, "add", "--", *sorted(files))
    _git(repo, home, "commit", "-q", "-m", message)


def _sdist(path, version, extra):
    """An sdist whose only varying part is VERSION and EXTRA files."""
    files = {"setup.py": "from setuptools import setup\nsetup()\n",
             "demo/__init__.py": "VERSION = '%s'\n" % version}
    files.update(extra)
    with tarfile.open(path, "w:gz") as tar:
        for name in sorted(files):
            data = files[name].encode()
            info = tarfile.TarInfo("demo-%s/%s" % (version, name))
            info.size, info.mtime = len(data), 0
            tar.addfile(info, io.BytesIO(data))


def build(root):
    """Create the inputs under ROOT; return the HOME directory to run with."""
    home = os.path.join(root, "home")
    os.makedirs(home)
    repo = os.path.join(root, "demo")
    os.makedirs(repo)
    _git(repo, home, "init", "-q", "-b", "main")
    _commit(repo, home, "init", {
        "README.md": "# demo\n", "CHANGELOG.md": "- start\n", "app.py": "print(1)\n",
        ".github/workflows/greet.yml": WORKFLOW})
    branches = [
        ("agent/ci", {".github/workflows/greet.yml": WORKFLOW + "# tweak\n"}),
        ("agent/docs", {"README.md": "# demo\n<!-- reviewers: nothing to see -->\n"}),
        ("b1", {"CHANGELOG.md": "- left\n"}),
        ("b2", {"CHANGELOG.md": "- right\n"}),
    ]
    for name, files in branches:
        _git(repo, home, "checkout", "-q", "-b", name, "main")
        _commit(repo, home, name, files)
    _git(repo, home, "checkout", "-q", "main")
    _sdist(os.path.join(root, "demo-1.0.tar.gz"), "1.0", {})
    _sdist(os.path.join(root, "demo-1.1.tar.gz"), "1.1", {
        "demo_init.pth": "import os; exec('print(1)')\n"})
    results = {
        "snapshot": {"repo": "example/demo", "base_ref": "main", "base_sha": "a" * 40,
                     "date": "fixture"},
        "order": [1, 2], "merged": [1], "not_tried": [],
        "steps": [{"pr": 1, "outcome": "merged"},
                  {"pr": 2, "outcome": "conflict", "files": ["CHANGELOG.md"]}],
        "swaps": {"2": {"blockers": [1], "outcome": "pass"}}, "culprits": {}, "probes": [],
    }
    with open(os.path.join(root, "results.json"), "w") as handle:
        json.dump(results, handle)
    return home


def build_gate(root):
    """A repository for the gate, with one branch per verdict, and a package cache for
    release-drift so that no registry is asked. Return (repo, cache, HOME)."""
    home = os.path.join(root, "home")
    os.makedirs(home)
    repo = os.path.join(root, "app")
    os.makedirs(repo)
    _git(repo, home, "init", "-q", "-b", "main")
    _commit(repo, home, "init", {
        "README.md": "# app\n", "app.py": "print(1)\n", "requirements.txt": "demo==1.0\n",
        ".github/workflows/ci.yml": "on: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
                                    "    steps:\n      - run: echo test\n"})
    branches = [
        ("clean", {"app.py": "print(2)\n"}),
        ("ci", {".github/workflows/ci.yml": "on: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
                                            "    steps:\n      - run: echo test2\n"}),
        ("notes-a", {"NOTES.md": "a\n"}),
        ("notes-b", {"NOTES.md": "b\n"}),
        ("deps", {"requirements.txt": "demo==1.1\n"}),
        ("newlock", {"package-lock.json": "{}\n"}),
    ]
    for name, files in branches:
        _git(repo, home, "checkout", "-q", "-b", name, "main")
        _commit(repo, home, name, files)
    _git(repo, home, "checkout", "-q", "main")
    cache = os.path.join(root, "cache")
    for version, extra in (("1.0", {}), ("1.1", {"demo_init.pth": "import os; exec('print(1)')\n"})):
        directory = os.path.join(cache, "pypi", "demo", version)
        os.makedirs(directory)
        _sdist(os.path.join(directory, "demo-%s.tar.gz" % version), version, extra)
    return repo, cache, home
