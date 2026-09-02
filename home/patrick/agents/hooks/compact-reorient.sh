#!/usr/bin/env bash
# compact-reorient: restore session-scoped lead instructions after compaction
# or resume in Codex and Claude Code.
set -euo pipefail

command -v jq >/dev/null 2>&1 || exit 0
input=$(cat)

event=$(jq -r '.hook_event_name // ""' <<<"$input")
source=$(jq -r '.source // ""' <<<"$input")
[[ "$event" == "SessionStart" ]] || exit 0
case "$source" in
  compact | resume) ;;
  *) exit 0 ;;
esac

session_lead=${AGENT_SESSION_LEAD_COMMAND:-$HOME/.agents/bin/session-lead-mode}
session_id=$(jq -r '.session_id // empty' <<<"$input")
if [[ -n "$session_id" ]]; then
  mode=$(bash "$session_lead" get "$session_id" 2>/dev/null || true)
else
  mode=$(bash "$session_lead" get 2>/dev/null || true)
fi

message="Session recovery: before continuing, re-orient from the project's agent instructions and any active board, handover, plan, or durable design docs. Verify the current working tree and recorded next action instead of only relying on compacted or remembered conversation state."
case "$mode" in
  autopilot | supervisor)
    skill_path="$HOME/.agents/skills/$mode/SKILL.md"
    message="Session recovery: the \`$mode\` skill remains active for this session. Before continuing, reload \`$skill_path\` completely and follow it. Resume the existing arc; do not restart completed pre-flight work. Then re-orient from the project's agent instructions and active board, handover, plan, or durable design docs. Verify the current working tree and recorded next action instead of only relying on compacted or remembered conversation state."
    ;;
esac

jq -cn --arg m "$message" \
  '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$m}}'
