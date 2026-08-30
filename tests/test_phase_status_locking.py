"""Concurrency and fail-closed tests for the phase-status writer pair."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "skills" / "planning-with-files" / "scripts"
PHASE_SH = SCRIPT_DIR / "phase-status.sh"
PHASE_PS1 = SCRIPT_DIR / "phase-status.ps1"
ROOT_PHASE_SH = REPO_ROOT / "scripts" / "phase-status.sh"
ROOT_PHASE_PS1 = REPO_ROOT / "scripts" / "phase-status.ps1"
SH = shutil.which("sh")
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


class PhaseStatusLockFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="pwf-phase-lock-"))
        self.plan_dir = self.tmp / ".planning" / "p"
        self.plan_dir.mkdir(parents=True)
        (self.tmp / ".planning" / ".active_plan").write_text(
            "p\n", encoding="utf-8"
        )
        self.env = os.environ.copy()
        self.env["PLAN_ID"] = "p"
        self.write_plan(8)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    @property
    def plan_file(self) -> Path:
        return self.plan_dir / "task_plan.md"

    @property
    def lock_dir(self) -> Path:
        return self.plan_dir / ".pwf-locks" / "phase-status.lock"

    def write_plan(self, phases: int) -> None:
        body = ["# Task Plan"]
        for phase in range(1, phases + 1):
            body.extend(
                [f"### Phase {phase}: Work", "- **Status:** pending"]
            )
        self.plan_file.write_text("\n".join(body) + "\n", encoding="utf-8")

    def sh_command(self, phase: int, status: str = "complete") -> list[str]:
        assert SH is not None
        return [SH, str(PHASE_SH), str(phase), status]

    def ps_command(self, phase: int, status: str = "complete") -> list[str]:
        assert POWERSHELL is not None
        command = [POWERSHELL, "-NoProfile"]
        if os.name == "nt":
            command.extend(["-ExecutionPolicy", "Bypass"])
        command.extend(["-File", str(PHASE_PS1), str(phase), status])
        return command

    def run_command(self, command: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            command,
            cwd=self.tmp,
            env=self.env,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            timeout=12,
        )


class PhaseStatusLockStaticTests(unittest.TestCase):
    def test_root_and_canonical_writers_use_same_fail_closed_sentinel(self) -> None:
        for root_script, canonical_script in (
            (ROOT_PHASE_SH, PHASE_SH),
            (ROOT_PHASE_PS1, PHASE_PS1),
        ):
            with self.subTest(script=canonical_script.name):
                root_source = root_script.read_text(encoding="utf-8")
                canonical_source = canonical_script.read_text(encoding="utf-8")
                self.assertEqual(root_source, canonical_source)
                self.assertIn(".pwf-locks", canonical_source)
                self.assertIn("phase-status.lock", canonical_source)
                self.assertNotIn(".write_lock", canonical_source)
                self.assertNotIn("flock", canonical_source)

    def test_phase_read_occurs_after_lock_acquisition(self) -> None:
        shell_source = PHASE_SH.read_text(encoding="utf-8")
        self.assertLess(
            shell_source.index("acquire_lock\n"),
            shell_source.index("if ! grep -q"),
        )

        ps_source = PHASE_PS1.read_text(encoding="utf-8")
        self.assertLess(
            ps_source.index("$lock = Enter-PwfDirectoryLock"),
            ps_source.index("$lines = Get-Content"),
        )


@unittest.skipUnless(SH, "sh not available")
class ShellPhaseStatusLockTests(PhaseStatusLockFixture):
    def test_held_lock_times_out_without_plan_mutation_or_owner_removal(self) -> None:
        self.lock_dir.mkdir(parents=True)
        owner = self.lock_dir / ".owner"
        owner.write_text("external-owner\n", encoding="utf-8")
        before = self.plan_file.read_bytes()

        started = time.monotonic()
        result = self.run_command(self.sh_command(1))
        elapsed = time.monotonic() - started

        self.assertNotEqual(0, result.returncode)
        self.assertGreaterEqual(elapsed, 4.0)
        self.assertIn("Timed out waiting for lock", result.stderr)
        self.assertEqual(before, self.plan_file.read_bytes())
        self.assertEqual("external-owner", owner.read_text(encoding="utf-8").strip())
        self.assertTrue(self.lock_dir.is_dir())
        self.assertEqual([], list(self.plan_dir.glob("task_plan.md.tmp.*")))

    def test_concurrent_distinct_phase_updates_are_not_lost(self) -> None:
        processes = [
            subprocess.Popen(
                self.sh_command(phase),
                cwd=self.tmp,
                env=self.env,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for phase in range(1, 3)
        ]
        results = [process.communicate(timeout=15) for process in processes]

        failures = [
            (process.returncode, stdout, stderr)
            for process, (stdout, stderr) in zip(processes, results)
            if process.returncode != 0
        ]
        self.assertEqual([], failures)
        plan = self.plan_file.read_text(encoding="utf-8")
        self.assertEqual(2, plan.count("- **Status:** complete"))
        self.assertEqual(6, plan.count("- **Status:** pending"))
        self.assertFalse(self.lock_dir.exists())


@unittest.skipUnless(POWERSHELL and os.name == "nt", "Windows PowerShell unavailable")
class PowerShellPhaseStatusLockTests(PhaseStatusLockFixture):
    def test_held_shell_compatible_lock_fails_closed(self) -> None:
        self.lock_dir.mkdir(parents=True)
        owner = self.lock_dir / ".owner"
        owner.write_text("shell-owner\n", encoding="utf-8")
        before = self.plan_file.read_bytes()

        result = self.run_command(self.ps_command(1))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Timed out waiting for lock", result.stderr)
        self.assertEqual(before, self.plan_file.read_bytes())
        self.assertEqual("shell-owner", owner.read_text(encoding="utf-8").strip())
        self.assertTrue(self.lock_dir.is_dir())
        self.assertEqual([], list(self.plan_dir.glob("task_plan.md.tmp.*")))

    @unittest.skipUnless(SH, "sh not available")
    def test_shell_and_powershell_serialize_on_the_same_directory(self) -> None:
        commands = [
            self.sh_command(phase) if phase % 2 else self.ps_command(phase)
            for phase in range(1, 3)
        ]
        processes = [
            subprocess.Popen(
                command,
                cwd=self.tmp,
                env=self.env,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for command in commands
        ]
        results = [process.communicate(timeout=20) for process in processes]

        failures = [
            (process.returncode, stdout, stderr)
            for process, (stdout, stderr) in zip(processes, results)
            if process.returncode != 0
        ]
        self.assertEqual([], failures)
        plan = self.plan_file.read_text(encoding="utf-8")
        self.assertEqual(2, plan.count("- **Status:** complete"))
        self.assertEqual(6, plan.count("- **Status:** pending"))
        self.assertFalse(self.lock_dir.exists())


if __name__ == "__main__":
    unittest.main()
