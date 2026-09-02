#!/bin/bash
# planning-with-files: Post-tool-use hook for Codex

# issue #195: per-invocation opt-out for one-shot/CI sessions.
[ "${PLANNING_DISABLED:-}" = "1" ] && exit 0

HOOK_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
PLAN_DIR="$(sh "${HOOK_DIR}/resolve-plan-dir.sh" 2>/dev/null)"
# An explicit PLAN_ID is a binding, not a hint (issue #237). When the shared
# resolver rejected one it emits nothing, and the legacy-root fallback below
# would answer for a plan the operator never named. Stay silent instead; the
# once-per-turn user-prompt-submit hook carries the notice.
[ -z "$PLAN_DIR" ] && [ -n "${PLAN_ID:-}" ] && exit 0
PLAN_FILE="${PLAN_DIR:+${PLAN_DIR}/}task_plan.md"

if [ -f "$PLAN_FILE" ]; then
    echo "[planning-with-files] Update progress.md with what you just did. If a phase is now complete, update task_plan.md status."
fi
exit 0
