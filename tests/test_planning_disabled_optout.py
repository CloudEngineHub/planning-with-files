"""Issue #195: PLANNING_DISABLED=1 per-invocation opt-out.

A one-shot session (codex exec, CI bot, sub-orchestrator) that merely shares a
cwd with an incomplete plan must be able to opt out of every hook: no plan
injection, no stop followup, no plan-file mutation. These tests run the real
hook scripts in a temp dir containing a legacy root task_plan.md (the exact
attachment path the issue reports) with and without the env var.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CODEX_HOOKS = REPO / ".codex" / "hooks"
SCRIPTS = REPO / "scripts"

PLAN = "# Test Plan\n### Phase 1: something\n**Status:** in_progress\n"


def run_sh(script: Path, cwd: Path, disabled: bool) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("PLANNING_DISABLED", None)
    if disabled:
        env["PLANNING_DISABLED"] = "1"
    return subprocess.run(
        ["sh", str(script)],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


class PlanningDisabledOptOutTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self._tmp.name)
        (self.cwd / "task_plan.md").write_text(PLAN, encoding="utf-8")
        (self.cwd / "progress.md").write_text("progress line\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # --- Codex hooks (the platform #195 reports against) ---

    def test_codex_user_prompt_submit_stays_silent_when_disabled(self) -> None:
        baseline = run_sh(CODEX_HOOKS / "user-prompt-submit.sh", self.cwd, disabled=False)
        self.assertIn("ACTIVE PLAN", baseline.stdout)
        disabled = run_sh(CODEX_HOOKS / "user-prompt-submit.sh", self.cwd, disabled=True)
        self.assertEqual(disabled.stdout.strip(), "")
        self.assertEqual(disabled.returncode, 0)

    def test_codex_stop_emits_no_followup_when_disabled(self) -> None:
        baseline = run_sh(CODEX_HOOKS / "stop.sh", self.cwd, disabled=False)
        self.assertIn("followup_message", baseline.stdout)
        disabled = run_sh(CODEX_HOOKS / "stop.sh", self.cwd, disabled=True)
        self.assertEqual(disabled.stdout.strip(), "")
        self.assertEqual(disabled.returncode, 0)

    def test_codex_pre_tool_use_still_allows_but_skips_context(self) -> None:
        disabled = run_sh(CODEX_HOOKS / "pre-tool-use.sh", self.cwd, disabled=True)
        self.assertIn('"decision": "allow"', disabled.stdout)
        self.assertEqual(disabled.stderr.strip(), "")

    def test_codex_post_tool_use_stays_silent_when_disabled(self) -> None:
        disabled = run_sh(CODEX_HOOKS / "post-tool-use.sh", self.cwd, disabled=True)
        self.assertEqual(disabled.stdout.strip(), "")

    def test_codex_session_start_stays_silent_when_disabled(self) -> None:
        disabled = run_sh(CODEX_HOOKS / "session-start.sh", self.cwd, disabled=True)
        self.assertEqual(disabled.stdout.strip(), "")

    def test_codex_pre_compact_stays_silent_when_disabled(self) -> None:
        disabled = run_sh(CODEX_HOOKS / "pre-compact.sh", self.cwd, disabled=True)
        self.assertEqual(disabled.stdout.strip(), "")

    def test_codex_adapter_reports_not_attached_when_disabled(self) -> None:
        sys.path.insert(0, str(CODEX_HOOKS))
        try:
            import codex_hook_adapter as adapter
        finally:
            sys.path.pop(0)
        old = os.environ.pop("PLANNING_DISABLED", None)
        try:
            self.assertTrue(adapter.is_session_attached(self.cwd, None))
            os.environ["PLANNING_DISABLED"] = "1"
            self.assertFalse(adapter.is_session_attached(self.cwd, None))
        finally:
            os.environ.pop("PLANNING_DISABLED", None)
            if old is not None:
                os.environ["PLANNING_DISABLED"] = old

    # --- Canonical dispatchers (Claude Code and mirrors) ---

    def test_inject_plan_stays_silent_when_disabled(self) -> None:
        baseline = run_sh(SCRIPTS / "inject-plan.sh", self.cwd, disabled=False)
        self.assertIn("ACTIVE PLAN", baseline.stdout)
        disabled = run_sh(SCRIPTS / "inject-plan.sh", self.cwd, disabled=True)
        self.assertEqual(disabled.stdout.strip(), "")

    def test_gate_stop_stays_silent_when_disabled(self) -> None:
        disabled = run_sh(SCRIPTS / "gate-stop.sh", self.cwd, disabled=True)
        self.assertEqual(disabled.stdout.strip(), "")
        self.assertEqual(disabled.returncode, 0)

    def test_check_complete_stays_silent_when_disabled(self) -> None:
        baseline = run_sh(SCRIPTS / "check-complete.sh", self.cwd, disabled=False)
        self.assertNotEqual(baseline.stdout.strip(), "")
        disabled = run_sh(SCRIPTS / "check-complete.sh", self.cwd, disabled=True)
        self.assertEqual(disabled.stdout.strip(), "")

    # --- Acceptance criterion from #195: plan files byte-for-byte unchanged ---

    def test_plan_files_unchanged_after_disabled_hook_pass(self) -> None:
        for script in [
            CODEX_HOOKS / "session-start.sh",
            CODEX_HOOKS / "user-prompt-submit.sh",
            CODEX_HOOKS / "pre-tool-use.sh",
            CODEX_HOOKS / "post-tool-use.sh",
            CODEX_HOOKS / "stop.sh",
            CODEX_HOOKS / "pre-compact.sh",
            SCRIPTS / "inject-plan.sh",
            SCRIPTS / "gate-stop.sh",
            SCRIPTS / "check-complete.sh",
        ]:
            run_sh(script, self.cwd, disabled=True)
        self.assertEqual((self.cwd / "task_plan.md").read_text(encoding="utf-8"), PLAN)
        self.assertEqual(
            (self.cwd / "progress.md").read_text(encoding="utf-8"), "progress line\n"
        )

    # --- Every distributed copy carries the guard ---

    def test_all_check_complete_copies_carry_the_guard(self) -> None:
        copies = list(REPO.glob("**/check-complete.sh")) + list(
            REPO.glob("**/check-complete.ps1")
        )
        self.assertGreater(len(copies), 10)
        for copy in copies:
            if "node_modules" in copy.parts:
                continue
            text = copy.read_text(encoding="utf-8", errors="replace")
            self.assertIn(
                "PLANNING_DISABLED",
                text,
                f"missing opt-out guard: {copy.relative_to(REPO)}",
            )


if __name__ == "__main__":
    unittest.main()
