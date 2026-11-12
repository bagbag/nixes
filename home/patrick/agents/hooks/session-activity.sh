#!/usr/bin/env bash
# session-activity: SubagentStart, SubagentStop and PreToolUse (every tool)
# hook (Claude Code, Codex) that records activity in the payload's session
# registry. SubagentStart and a worker's tool call (payload with agent_id)
# create or touch the worker's marker, SubagentStop deletes it; the session's
# own tool calls touch its activity file. board reads them: mine marks the
# holds of stopped workers WORKER STOPPED, position derives idle marks, and the
# capacity line counts active workers. Always exits 0 and stays fast (no board
# calls): a failing SubagentStop hook can keep the worker running, and
# PreToolUse runs before every tool call.
# Codex 0.166 (probed 2026-10-31): the matcher-less group fires for every tool (shell,
# apply_patch); a worker's payload carries the parent's session_id and agent_id = its CODEX_THREAD_ID.
set -uo pipefail

input=$(cat) || exit 0
command -v jq >/dev/null 2>&1 || exit 0
# One jq call; agent_type is "-" when the payload has no such key. The unit
# separator keeps empty fields (read collapses runs of whitespace separators).
fields=$(jq -r '[.hook_event_name // "", .agent_id // "", .session_id // "",
  (if has("agent_type") then .agent_type // "" else "-" end)] | map(tostring) | join("\u001f")' <<<"$input" 2>/dev/null) || exit 0
IFS=$'\x1f' read -r event agent_id session_id agent_type <<<"$fields"
case $event in
  SubagentStop) command=worker-ended ;;
  SubagentStart) command=worker-started ;;
  PreToolUse) command=session-active ;;
  *) exit 0 ;;
esac
# Claude Code's internal agents (prompt suggestions, /btw) carry an empty
# agent_type; they hold nothing. Start and Stop payloads carry the key; a
# PreToolUse payload may not.
if [[ "$command" == session-active ]]; then
  if [[ -n "$agent_id" ]]; then
    [[ -n "$agent_type" ]] || exit 0
    command=worker-active
  fi
else
  [[ -n "$agent_id" && -n "$agent_type" && "$agent_type" != - ]] || exit 0
fi

session_lead=${AGENT_SESSION_LEAD_COMMAND:-$HOME/.agents/bin/session-lead-mode}
arguments=("$command")
[[ "$command" == session-active ]] || arguments+=("$agent_id")
if [[ -n "$session_id" ]]; then
  # The payload names the session; the inherited environment can name an
  # outer one (a Claude session started from Codex keeps CODEX_SESSION_ID).
  CODEX_SESSION_ID='' CODEX_THREAD_ID='' CLAUDE_CODE_SESSION_ID=$session_id \
    bash "$session_lead" "${arguments[@]}" >/dev/null 2>&1
else
  bash "$session_lead" "${arguments[@]}" >/dev/null 2>&1
fi
exit 0
