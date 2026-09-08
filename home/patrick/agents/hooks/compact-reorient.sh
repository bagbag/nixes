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

message+=" Preserve the current task and newer user instructions. When continuing project work, follow entry-point or active-board links to the canonical project goal and applicable topic goal and milestone, then recover current execution state from the board and handover. Reconcile the active plan and next action with those commitments and existing authority. Resume an existing arc only when it remains the current authorized task; reuse completed pre-flight work while its evidence remains applicable. Read further linked contracts and evidence when they govern that action. Verify the current working tree and recorded next action to ground recovery in current evidence."

jq -cn --arg m "$message" \
  '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$m}}'
