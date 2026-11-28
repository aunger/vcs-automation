#!/usr/bin/env python3
"""Checks .claude/orchestrate.json.

Runs the orchestrate plugin's check_config.py, fetched at the commit
.claude/vcs-automation-tools pins, over the file; that case skips when the fetch
fails, except in CI. Also checks the file against this repository's workflows.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / ".claude" / "orchestrate.json"
MARKETPLACE = ROOT / ".claude" / "vcs-automation-tools" / ".claude-plugin" / "marketplace.json"
WORKFLOWS = ROOT / ".github" / "workflows"
MERGE_GATE = "Administrative merge holds (not failure)"
GIT_TIMEOUT_SECONDS = 120


def load_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def workflow_check_names() -> set:
    """Return every job's check name across the workflows: its `name:`, else its id."""
    names = set()
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        jobs = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("jobs") or {}
        for job_id, job in jobs.items():
            names.add(str(job.get("name", job_id) if isinstance(job, dict) else job_id))
    return names


class FetchFailed(Exception):
    """The pinned commit could not be fetched."""


def pinned_check_config(directory: str) -> str:
    """Return check_config.py at the commit the marketplace pins for orchestrate."""
    marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    [source] = [p["source"] for p in marketplace["plugins"] if p["name"] == "orchestrate"]
    url = "https://github.com/%s.git" % source["url"]
    git = shutil.which("git")
    git_dir = os.path.join(directory, "pinned.git")

    def run(*args: str) -> str:
        # --git-dir, so an inherited GIT_DIR cannot redirect it.
        return subprocess.run(
            [git, "--git-dir", git_dir, *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=GIT_TIMEOUT_SECONDS,
        ).stdout

    try:
        if git is None:
            raise FileNotFoundError("git is not on PATH")
        run("init", "-q", "--bare", git_dir)
        run("fetch", "-q", "--depth", "1", url, source["sha"])
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
        detail = getattr(error, "stderr", None) or error
        raise FetchFailed(f"could not fetch {url} at {source['sha']}: {detail}") from error
    # A missing file fails the test rather than skipping it.
    return run("show", f"FETCH_HEAD:{source['path']}/scripts/check_config.py")


class TestCommittedConfig(unittest.TestCase):
    def test_check_config_accepts_it_without_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            try:
                script = pinned_check_config(directory)
            except FetchFailed as error:
                if os.environ.get("CI"):
                    self.fail(str(error))
                self.skipTest(str(error))
            check = os.path.join(directory, "check_config.py")
            with open(check, "w", encoding="utf-8") as handle:
                handle.write(script)
            completed = subprocess.run(
                [sys.executable, check, str(CONFIG)], capture_output=True, text=True, check=False
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertNotIn("warning:", completed.stdout)

    def test_every_named_check_is_a_workflow_job(self):
        missing = sorted(set(load_config()["named_checks"]) - workflow_check_names())
        self.assertEqual(missing, [], "named checks no workflow job produces")

    def test_the_merge_gate_is_ignored_and_not_a_named_check(self):
        config = load_config()
        self.assertIn(MERGE_GATE, workflow_check_names())
        self.assertNotIn(MERGE_GATE, config["named_checks"])
        self.assertIsNotNone(re.search(config["ignored_check_regex"], MERGE_GATE))

    def test_the_repository_is_this_one(self):
        self.assertEqual(load_config()["repository"], "aunger/vcs-automation")


if __name__ == "__main__":
    unittest.main()
