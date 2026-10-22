#!/usr/bin/env bash
# session-register: PreToolUse(Bash) hook that keeps workers from registering
# a role. session-lead-mode takes the session from the environment, which a
# Claude subagent shares with its session; only this payload's agent_id tells
# them apart.
set -euo pipefail

input=$(cat)
command -v jq >/dev/null 2>&1 || exit 0
[[ -n "$(jq -r '.agent_id // ""' <<<"$input")" ]] || exit 0
cmd=$(jq -r '.tool_input.command // "" | if type == "array" then join(" ") else tostring end' <<<"$input")
# activate in command position (start, after an operator or an interpreter);
# mentions inside other commands' arguments (rg 'session-lead-mode activate') pass.
activate='(^|[;&|(`'$'\n'']|\$\()[[:space:]]*([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*((bash|sh)[[:space:]]+)?["'\'']?[^[:space:];&|<>()`'\''"]*session-lead-mode(\.sh)?["'\'']?[[:space:]]+activate([[:space:]]|$)'
[[ "$cmd" =~ $activate ]] || exit 0
jq -cn '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",
  permissionDecisionReason:"session-register: workers do not register a role; the session'"'"'s registration covers its workers."}}'
