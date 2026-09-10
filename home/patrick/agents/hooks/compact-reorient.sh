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

message="Session recovery: before continuing, re-orient from the project's agent instructions."
case "$mode" in
  autopilot | supervisor)
    skill_path="$HOME/.agents/skills/$mode/SKILL.md"
    message="Session recovery: the \`$mode\` skill remains active for this session. Before continuing, reload \`$skill_path\` completely and follow it within the current task. Then re-orient from the project's agent instructions."
    ;;
esac

message+=" Preserve the current task and newer user instructions. Recover the current approved checkpoint, next authorized work, deferrals and return boundary from the current-only board (or handover if no board exists); use handover for recovery anchors and caveats. Consult the linked canonical project goal and applicable topic goal and milestone; reconcile the next action with those commitments and existing authority. Keep later product acceptance in its approved sequence. Resume an existing arc only when it remains the current authorized task. Check the working tree and relevant evidence; reuse applicable pre-flight results."

jq -cn --arg m "$message" \
  '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$m}}'
