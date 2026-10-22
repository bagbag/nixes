#!/usr/bin/env bash
# compact-reorient: restore the session's registered role after compaction or
# resume in Codex and Claude Code. role/SKILL.md owns the role -> protocol
# file mapping and project-memory.md the recovery steps; this hook names the
# role and points there.
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
registration='{}'
if [[ -n "$session_id" ]]; then
  registration=$(bash "$session_lead" show "$session_id" 2>/dev/null || true)
  [[ -n "$registration" ]] || registration='{}'
fi
role=$(jq -r '.role // ""' <<<"$registration")

message="Session recovery: before continuing, re-orient from the project's agent instructions."
if [[ -n "$role" ]]; then
  pulls=$(jq -r '(.pulls // []) | join(", ")' <<<"$registration")
  actor=$(jq -r '.actor // ""' <<<"$registration")
  message="Session recovery: this session is registered as role \`$role\`"
  [[ -z "$pulls" ]] || message+=" pulling $pulls"
  message+=" with board actor \`$actor\`. Before continuing, reload \`\$HOME/.agents/skills/role/SKILL.md\` completely and every protocol file it lists for \`$role\`, and follow them within the current task. Then re-orient from the project's agent instructions."
fi

message+=" Recover under \`\$HOME/.agents/skills/shared/project-memory.md\` Recovery and closure."

jq -cn --arg m "$message" \
  '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$m}}'
