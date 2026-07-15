#!/usr/bin/env bash
# git-stash-guard: PreToolUse(Bash) two-step gate on `git stash` for the main
# agent. First hit (no marker) -> deny + reflection prompt: reconsider whether
# the stash is truly needed (drop the non-essential step — lint, format, an
# incidental check — that made you want a clean tree). Only if genuinely
# required, re-run the SAME command prefixed with the marker env var; that
# re-run returns "ask", so Claude Code surfaces its permission prompt and the
# user approves/denies live. Read-only `git stash list|show` pass through.
#
# The marker is an env-var prefix, not a `#` comment: the login shell is zsh,
# which does not treat `#` as a command-line comment, so a trailing `#marker`
# would reach git as a pathspec and break the stash. An unknown env var is
# inert to git and harmless in both bash and zsh.
set -euo pipefail

input=$(cat)
command -v jq >/dev/null 2>&1 || exit 0
cmd=$(jq -r '.tool_input.command // ""' <<<"$input")
[[ -n "$cmd" ]] || exit 0

MARKER='CLAUDE_ALLOW_STASH=1'

# Strip quoted segments so a `git stash` inside a string/grep pattern is data,
# not a command (costs a quote-the-verb bypass; acceptable for a gate).
q=$(sed -E "s/'[^']*'//g"' ; s/"[^"]*"//g' <<<"$cmd")

# Only act on real `git stash` invocations.
grep -Eq '(^|[;&|[:space:]])git[[:space:]]+stash([[:space:]]|$)' <<<"$q" || exit 0
# Read-only stash inspection is always fine.
grep -Eq '(^|[;&|[:space:]])git[[:space:]]+stash[[:space:]]+(list|show)([[:space:]]|$)' <<<"$q" && exit 0

emit() {
  jq -cn --arg d "$1" --arg r "$2" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:$d,permissionDecisionReason:$r}}'
  exit 0
}

if [[ "$cmd" == *"$MARKER"* ]]; then
  emit ask "git-stash-guard: marker present — surfacing the stash to the user for approval."
else
  emit deny "git-stash-guard: pause before stashing. git stash is easy to forget and lose, so first ask whether you actually need it: can you finish on the current working tree, or drop the non-essential step (lint, format, an incidental check) that made you want a clean tree? If a stash is genuinely required to proceed, re-run the EXACT same command prefixed with '$MARKER ' (e.g. \`$MARKER git stash push -m wip\`); that re-run will ask the user to approve. Do not add the marker reflexively — only when the stash is truly necessary."
fi
