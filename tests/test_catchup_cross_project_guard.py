"""Two projects that fold to one store directory must not read each other.

Claude Code names ~/.claude/projects entries by folding every character
outside [A-Za-z0-9-] to '-'. That mapping is lossy, so /home/dev/client.acme
and /home/dev/client-acme both land in -home-dev-client-acme and share a
single directory of transcripts. Since v3.8.2 the resolver folds the same way
Claude Code does, which means it now finds that shared directory instead of
missing it, so catchup has to decide which transcripts in it are actually
this project's.

The rule under test: a transcript is skipped only when it positively records
a different cwd. Transcripts that record none are kept, because the field is
not present in every generation of the format, and a directory whose
transcripts all belong to another project is reported rather than used.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_SCRIPT = REPO_ROOT / "scripts" / "session-catchup.py"

VICTIM = "/home/dev/client-acme"
DONOR = "/home/dev/client.acme"
CANARY = "ACME_MERGER_PRICE_IS_FOUR_HUNDRED_MILLION"


def guarded_scripts() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*session-catchup.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    scripts = []
    for rel in out:
        path = REPO_ROOT / rel
        if path.is_file() and "def filter_sessions_by_cwd" in path.read_text(encoding="utf-8"):
            scripts.append(path)
    return sorted(scripts)


def load_module(script_path: Path, alias: str):
    spec = importlib.util.spec_from_file_location(alias, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_session(directory: Path, name: str, cwd: str | None, body: str) -> Path:
    """A minimal transcript: optional cwd, a planning-file write, then a message."""
    path = directory / name
    lines = []
    first = {"type": "user", "message": {"content": "start of session " + name}}
    if cwd is not None:
        first["cwd"] = cwd
    lines.append(first)
    lines.append({
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "name": "Write",
             "input": {"file_path": (cwd or "/home/dev/x") + "/task_plan.md"}},
        ]},
    })
    lines.append({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": body}]},
    })
    path.write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )
    return path


class CrossProjectGuardTests(unittest.TestCase):
    """Unit level, run against every copy that carries the guard."""

    def setUp(self):
        self.scripts = guarded_scripts()
        self.assertTrue(self.scripts, "no copy exposes filter_sessions_by_cwd")

    def _each(self):
        for script in self.scripts:
            rel = script.relative_to(REPO_ROOT).as_posix()
            module = load_module(script, f"g_{abs(hash(str(script)))}")
            yield rel, module

    def test_foreign_only_store_yields_nothing_and_says_so(self):
        for rel, module in self._each():
            with self.subTest(copy=rel), tempfile.TemporaryDirectory() as tmp:
                d = Path(tmp)
                sessions = [write_session(d, "a.jsonl", DONOR, CANARY)]
                kept, notice = module.filter_sessions_by_cwd(sessions, VICTIM)
                self.assertEqual([], kept, f"{rel} kept another project's transcript")
                self.assertIsNotNone(notice, f"{rel} skipped silently")

    def test_mixed_store_keeps_only_this_project(self):
        for rel, module in self._each():
            with self.subTest(copy=rel), tempfile.TemporaryDirectory() as tmp:
                d = Path(tmp)
                foreign = write_session(d, "a.jsonl", DONOR, CANARY)
                mine = write_session(d, "b.jsonl", VICTIM, "my own work")
                kept, notice = module.filter_sessions_by_cwd([foreign, mine], VICTIM)
                self.assertEqual([mine], kept, f"{rel} did not isolate the project")
                self.assertIsNone(notice)

    def test_transcripts_without_a_cwd_are_kept(self):
        """Fail open: older transcripts carry no cwd and must still be recovered."""
        for rel, module in self._each():
            with self.subTest(copy=rel), tempfile.TemporaryDirectory() as tmp:
                d = Path(tmp)
                legacy = write_session(d, "a.jsonl", None, "legacy transcript")
                kept, notice = module.filter_sessions_by_cwd([legacy], VICTIM)
                self.assertEqual([legacy], kept, f"{rel} dropped a legacy transcript")
                self.assertIsNone(notice)

    def test_own_transcripts_pass_through_untouched(self):
        for rel, module in self._each():
            with self.subTest(copy=rel), tempfile.TemporaryDirectory() as tmp:
                d = Path(tmp)
                a = write_session(d, "a.jsonl", VICTIM, "one")
                b = write_session(d, "b.jsonl", VICTIM, "two")
                kept, notice = module.filter_sessions_by_cwd([a, b], VICTIM)
                self.assertEqual([a, b], kept)
                self.assertIsNone(notice)


class CrossProjectGuardEndToEndTests(unittest.TestCase):
    """Run the real script against a store shared by two projects."""

    def _run(self, home: Path, project: str) -> str:
        env = dict(os.environ)
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        env["PYTHONIOENCODING"] = "utf-8"
        env.pop("OPENCODE_DATA_DIR", None)
        proc = subprocess.run(
            [sys.executable, str(ROOT_SCRIPT), project],
            capture_output=True, text=True, env=env, timeout=60,
        )
        return proc.stdout + proc.stderr

    def test_victim_never_prints_the_other_projects_conversation(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            store = home / ".claude" / "projects" / "-home-dev-client-acme"
            store.mkdir(parents=True)
            # Both projects fold to this one directory. Only the donor has
            # transcripts, and they carry the secret.
            write_session(store, "a.jsonl", DONOR, CANARY)
            write_session(store, "b.jsonl", DONOR, CANARY + "_SECOND")

            output = self._run(home, VICTIM)
            self.assertNotIn(
                CANARY, output,
                "catchup disclosed another project's conversation",
            )

    def test_own_history_is_still_recovered_from_a_shared_store(self):
        """The guard must not cost the project its own transcripts.

        Rejecting the whole directory would be the easy fix and the wrong one:
        in a collision both projects live there permanently, so the victim
        would lose its own history for good.
        """
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            store = home / ".claude" / "projects" / "-home-dev-client-acme"
            store.mkdir(parents=True)
            write_session(store, "a.jsonl", DONOR, CANARY)
            time.sleep(0.05)
            write_session(store, "b.jsonl", VICTIM, "MY_OWN_PLANNING_NOTE")
            time.sleep(0.05)
            write_session(store, "c.jsonl", VICTIM, "MY_LATEST_TURN")

            output = self._run(home, VICTIM)
            self.assertNotIn(CANARY, output)
            self.assertIn(
                "MY_OWN_PLANNING_NOTE", output,
                "the guard dropped this project's own transcript",
            )


if __name__ == "__main__":
    unittest.main()
