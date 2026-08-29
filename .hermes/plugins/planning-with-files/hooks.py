from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

from .constants import PROGRESS_TAIL_LINES, READ_PREVIEW_LINES
from .context_frame import frame_bytes, read_regular_bytes, select_lines, verified_frame
from .hook_state import add_reminder, pop_reminders, state_key
from .paths import normalize_cwd
from .planning_files import normalize_wall_clock


def _runtime_project_dir(kwargs: dict[str, Any]) -> Path | None:
    """Resolve the active Hermes project, never a cached import-time cwd."""
    try:
        from agent.runtime_cwd import resolve_agent_cwd
    except ImportError:
        return None
    else:
        try:
            candidate = resolve_agent_cwd()
        except (OSError, RuntimeError, ValueError):
            return None
    if not isinstance(candidate, Path):
        return None
    try:
        project = normalize_cwd(str(candidate))
        if not project.is_dir():
            return None
        return project
    except (OSError, RuntimeError, ValueError):
        return None


def _session_is_attached(project_dir: Path, session_id: str) -> bool:
    """Apply opt-in isolation once a project creates its sessions directory."""
    sessions_dir = project_dir / ".planning" / "sessions"
    try:
        info = sessions_dir.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        or not session_id
    ):
        return False
    try:
        sentinel = sessions_dir / f"{state_key(project_dir, session_id)}.attached"
        read_regular_bytes(sentinel, max_source_bytes=32)
        return True
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return False


def _has_regular_plan(project_dir: Path) -> bool:
    try:
        read_regular_bytes(project_dir / "task_plan.md", max_source_bytes=4 * 1024 * 1024)
        return True
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return False


def _session_id(kwargs: dict[str, Any]) -> str:
    """Use Hermes' session identity, with its documented tool task fallback."""
    return str(kwargs.get("session_id") or kwargs.get("task_id") or "")


def build_user_prompt_context(project_dir: Path) -> str:
    task_plan = project_dir / "task_plan.md"
    parts = ["[planning-with-files] ACTIVE PLAN — current state:"]
    try:
        parts.append(
            verified_frame(
                "plan",
                task_plan,
                attestation=project_dir / ".plan-attestation",
                mode=project_dir / ".mode",
                head=READ_PREVIEW_LINES,
            )
        )
    except (OSError, UnicodeError, ValueError) as exc:
        return f"[planning-with-files] context blocked: {exc}"
    try:
        progress_bytes = select_lines(
            read_regular_bytes(project_dir / "progress.md"), tail=PROGRESS_TAIL_LINES
        )
        normalized = normalize_wall_clock(
            progress_bytes.decode("utf-8", errors="replace")
        ).encode("utf-8")
        parts.append(frame_bytes("progress", normalized))
    except (FileNotFoundError, OSError, UnicodeError, ValueError):
        pass
    try:
        read_regular_bytes(project_dir / "findings.md", max_source_bytes=4 * 1024 * 1024)
        parts.append("[planning-with-files] Read findings.md for research context. Continue from the current phase.")
    except (FileNotFoundError, OSError, ValueError):
        pass
    return "\n\n".join(parts)


def pre_llm_call(**kwargs: Any) -> dict[str, str] | None:
    project_dir = _runtime_project_dir(kwargs)
    if project_dir is None or not _has_regular_plan(project_dir):
        return None
    user_message = str(kwargs.get("user_message", ""))
    session_id = _session_id(kwargs)
    if not _session_is_attached(project_dir, session_id):
        return None
    reminder_messages = pop_reminders(project_dir, session_id)
    context = build_user_prompt_context(project_dir)
    parts: list[str] = []
    if reminder_messages:
        parts.append("\n".join(reminder_messages))
    if context:
        parts.append(context)
    if not user_message.strip() and not kwargs.get("is_first_turn") and not reminder_messages:
        return None
    if not parts:
        return None
    return {"context": "\n\n".join(parts)}


def post_tool_call(**kwargs: Any) -> None:
    tool_name = str(kwargs.get("tool_name", ""))
    args = kwargs.get("args") or {}
    if tool_name == "write_file":
        if not args.get("path") or "content" not in args:
            return None
    elif tool_name == "patch":
        has_patch_payload = bool(args.get("patch"))
        has_replace_payload = bool(args.get("path")) and "old_string" in args and "new_string" in args
        if not (has_patch_payload or has_replace_payload):
            return None
    else:
        return None
    project_dir = _runtime_project_dir(kwargs)
    if project_dir is None or not _has_regular_plan(project_dir):
        return None
    session_id = _session_id(kwargs)
    if not _session_is_attached(project_dir, session_id):
        return None
    message = "[planning-with-files] Update progress.md with what you just did. If a phase is now complete, update task_plan.md status."
    add_reminder(project_dir, session_id, message)
    return None
