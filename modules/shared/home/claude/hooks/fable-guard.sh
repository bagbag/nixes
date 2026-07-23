#!/usr/bin/env bash
# fable-guard: PreToolUse hook on the Agent tool. Enforces the agent instructions
# that Fable is never auto-selected for subagents — the main session already
# runs it; workers are cheaper tiers by design. Escape hatch: when the user
# explicitly requests Fable, the session flag below legitimizes it.
set -euo pipefail

input=$(cat)
command -v jq >/dev/null 2>&1 || exit 0

model=$(jq -r '.tool_input.model // ""' <<<"$input")
[[ "${model,,}" == *fable* ]] || exit 0

session_id=$(jq -r '.session_id // ""' <<<"$input")
flag="/tmp/claude-context-watch/${session_id}.fable-ok"
[[ -f "$flag" ]] && exit 0

jq -cn --arg r "fable-guard: Fable is never auto-selected for subagents (agent-instruction policy — the main session already runs it; route workers per the role roster). If the user explicitly requested Fable for this task, run: mkdir -p /tmp/claude-context-watch && touch $flag — then retry." \
  '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
