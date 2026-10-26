#!/usr/bin/env bash
# worker-status: SubagentStop and SubagentStart hook (Claude Code, Codex) that
# marks the stopped worker in its session's registry and unmarks it when it
# starts or resumes, so board mine marks the holds of stopped workers WORKER
# STOPPED for that session. Always exits 0: a failing SubagentStop hook can
# keep the worker running.
set -uo pipefail

input=$(cat) || exit 0
command -v jq >/dev/null 2>&1 || exit 0
agent_id=$(jq -r '.agent_id // ""' <<<"$input" 2>/dev/null) || exit 0
agent_type=$(jq -r '.agent_type // ""' <<<"$input" 2>/dev/null) || exit 0
session_id=$(jq -r '.session_id // ""' <<<"$input" 2>/dev/null) || exit 0
case $(jq -r '.hook_event_name // ""' <<<"$input" 2>/dev/null) in
  SubagentStop) command=worker-ended ;;
  SubagentStart) command=worker-started ;;
  *) exit 0 ;;
esac
# Claude Code's internal agents (prompt suggestions, /btw) stop with an empty
# agent_type; they hold nothing.
[[ -n "$agent_id" && -n "$agent_type" ]] || exit 0

session_lead=${AGENT_SESSION_LEAD_COMMAND:-$HOME/.agents/bin/session-lead-mode}
if [[ -n "$session_id" ]]; then
  # The payload names the session; the inherited environment can name an
  # outer one (a Claude session started from Codex keeps CODEX_SESSION_ID).
  CODEX_SESSION_ID='' CODEX_THREAD_ID='' CLAUDE_CODE_SESSION_ID=$session_id \
    bash "$session_lead" "$command" "$agent_id" >/dev/null 2>&1
else
  bash "$session_lead" "$command" "$agent_id" >/dev/null 2>&1
fi
exit 0
