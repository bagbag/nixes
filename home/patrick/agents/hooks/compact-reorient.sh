#!/usr/bin/env bash
# compact-reorient: restore the session's registered role after compaction or
# resume in Codex and Claude Code. role/SKILL.md owns the role -> protocol
# file mapping and project-memory.md the recovery steps; this hook names the
# role and prints that file's Recovery section. A deciding session's
# protocol engine learns of the compaction (`protocol compacted`), so what it
# printed before prints in full again.
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

session_cmd=${AGENT_SESSION_COMMAND:-$HOME/.agents/bin/session}
session_id=$(jq -r '.session_id // empty' <<<"$input")
registration='{}'
if [[ -n "$session_id" ]]; then
  registration=$(bash "$session_cmd" show "$session_id" 2>/dev/null || true)
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
  # Codex has no console mod: its open protocol round comes back here (Claude's console owns that recovery).
  protocol=${AGENT_PROTOCOL_COMMAND:-$HOME/.agents/bin/protocol}
  if [[ "$(jq -r '.tool // ""' <<<"$registration")" == codex && -x "$protocol" ]]; then
    line=$("$protocol" --session "$session_id" status --line 2>/dev/null || true)
    [[ -z "$line" || "$line" == "protocol: no open round" ]] || message+=" $line"
  fi
  case "$role" in
    lead | solo | autopilot)
      if [[ ! -x "$protocol" ]] || ! "$protocol" --session "$session_id" compacted >/dev/null 2>&1; then
        message+=" \`protocol compacted\` failed: run it, or the engine keeps its texts short."
      fi ;;
  esac
fi

memory="$HOME/.agents/skills/shared/project-memory.md"
recovery=''
[[ ! -r "$memory" ]] || recovery=$(awk '/^## Recovery[[:space:]]*$/ {found = 1; next} found && /^## / {exit} found' "$memory")
if [[ -n "${recovery//[[:space:]]/}" ]]; then
  message+=" Recovery (\`\$HOME/.agents/skills/shared/project-memory.md\`):"$'\n'"$recovery"
else
  message+=" Recover under \`\$HOME/.agents/skills/shared/project-memory.md\` Recovery."
fi

jq -cn --arg m "$message" \
  '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$m}}'
