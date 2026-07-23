#!/usr/bin/env bash
# compact-reorient: SessionStart(compact) reminder shared by Codex and Claude
# Code. It relies only on their common hook input/output contract.
set -euo pipefail

command -v jq >/dev/null 2>&1 || exit 0
input=$(cat)

event=$(jq -r '.hook_event_name // ""' <<<"$input")
source=$(jq -r '.source // ""' <<<"$input")
[[ "$event" == "SessionStart" && "$source" == "compact" ]] || exit 0

message="Compaction recovery: before continuing, re-orient from the project's agent instructions and any active board, handover, plan, or durable design docs. Verify the current working tree and recorded next action instead of relying on the compacted conversation."

jq -cn --arg m "$message" \
  '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$m}}'
