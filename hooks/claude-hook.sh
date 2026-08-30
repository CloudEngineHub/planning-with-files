#!/bin/sh
# Claude Code plugin lifecycle dispatcher.
#
# Plugin execution is deliberately rooted only at CLAUDE_PLUGIN_ROOT. The
# standalone skill keeps its own activation-scoped frontmatter hooks, while
# this launcher is the single plugin-level lifecycle route.

set -u

[ "${PLANNING_DISABLED:-}" = "1" ] && exit 0

EVENT="${1:-}"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}"
[ -n "$PLUGIN_ROOT" ] || exit 0

SCRIPTS_DIR="${PLUGIN_ROOT}/scripts"
INJECT_PLAN="${SCRIPTS_DIR}/inject-plan.sh"
GATE_STOP="${SCRIPTS_DIR}/gate-stop.sh"
RESOLVE_PLAN_DIR="${SCRIPTS_DIR}/resolve-plan-dir.sh"
SESSION_CATCHUP="${SCRIPTS_DIR}/session-catchup.py"

# JSON-string encode bounded, trusted hook output without requiring Python or
# Node. The planning scripts already bound injected project data; this removes
# remaining JSON-forbidden control bytes and preserves line boundaries.
json_string() {
    tr '\001-\011\013-\037' ' ' \
        | awk 'BEGIN { first = 1 }
            {
                gsub(/\\/, "\\\\")
                gsub(/"/, "\\\"")
                if (!first) printf "\\n"
                printf "%s", $0
                first = 0
            }'
}

emit_context() {
    _event_name="$1"
    _context="$2"
    [ -f "$INJECT_PLAN" ] || exit 0
    _output=$(sh "$INJECT_PLAN" "--context=${_context}" 2>/dev/null) || exit 0
    [ -n "$_output" ] || exit 0
    _encoded=$(printf '%s' "$_output" | json_string)
    printf '{"hookSpecificOutput":{"hookEventName":"%s","additionalContext":"%s"}}\n' \
        "$_event_name" "$_encoded"
}

active_plan_dir() {
    _resolved=""
    if [ -f "$RESOLVE_PLAN_DIR" ]; then
        _resolved=$(sh "$RESOLVE_PLAN_DIR" 2>/dev/null) || _resolved=""
    fi
    if [ -n "$_resolved" ] && [ -f "${_resolved}/task_plan.md" ]; then
        printf '%s\n' "$_resolved"
    elif [ -f task_plan.md ]; then
        printf '%s\n' "."
    fi
}

emit_session_start() {
    [ -f "$INJECT_PLAN" ] && [ -f "$RESOLVE_PLAN_DIR" ] || exit 0
    _plan_dir=$(active_plan_dir) || exit 0
    [ -n "$_plan_dir" ] && [ -f "${_plan_dir}/task_plan.md" ] || exit 0

    _catchup=""
    # Prefer `python` on Windows because the WindowsApps `python3` alias can be
    # discoverable yet non-functional. Unix hosts fall through to python3.
    _python=$(command -v python 2>/dev/null || command -v python3 2>/dev/null || true)
    if [ -n "$_python" ] && [ -f "$SESSION_CATCHUP" ]; then
        _catchup=$("$_python" "$SESSION_CATCHUP" --no-history "$PWD" 2>/dev/null) || _catchup=""
    fi
    _context=$(sh "$INJECT_PLAN" --context=userprompt 2>/dev/null) || exit 0
    if [ -n "$_catchup" ] && [ -n "$_context" ]; then
        _output="${_catchup}
${_context}"
    elif [ -n "$_catchup" ]; then
        _output="$_catchup"
    else
        _output="$_context"
    fi
    [ -n "$_output" ] || exit 0
    _encoded=$(printf '%s' "$_output" | json_string)
    printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' "$_encoded"
}

emit_system_message() {
    _message="$1"
    [ -n "$_message" ] || exit 0
    _encoded=$(printf '%s' "$_message" | json_string)
    printf '{"systemMessage":"%s"}\n' "$_encoded"
}

case "$EVENT" in
    session-start)
        # Startup, resume, clear, and post-compact restoration share the same
        # bounded planning context. Catch-up runs first when Python is present.
        # With no active plan, both operations remain silent.
        emit_session_start
        ;;
    user-prompt-submit)
        emit_context "UserPromptSubmit" "userprompt"
        ;;
    pre-tool-use)
        emit_context "PreToolUse" "pretool"
        ;;
    post-tool-use)
        [ -f "$RESOLVE_PLAN_DIR" ] || exit 0
        _plan_dir=$(active_plan_dir) || exit 0
        [ -n "$_plan_dir" ] && [ -f "${_plan_dir}/task_plan.md" ] || exit 0
        emit_system_message "[planning-with-files] Update progress.md with what you just did. If a phase is now complete, update task_plan.md status."
        ;;
    pre-compact)
        [ -f "$INJECT_PLAN" ] || exit 0
        _output=$(sh "$INJECT_PLAN" --context=precompact 2>/dev/null) || exit 0
        emit_system_message "$_output"
        ;;
    stop)
        # Do not read stdin here. gate-stop must receive Claude's original Stop
        # payload so stop_hook_active can prevent recursive continuation.
        [ -f "$GATE_STOP" ] || exit 0
        _output=$(sh "$GATE_STOP" 2>/dev/null) || exit 0
        [ -n "$_output" ] || exit 0
        case "$_output" in
            '{"decision":"block"'*) printf '%s\n' "$_output" ;;
            *) emit_system_message "$_output" ;;
        esac
        ;;
    *)
        exit 0
        ;;
esac

exit 0
