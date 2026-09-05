#!/usr/bin/env bash
# readonly-guard: PreToolUse(Bash) hook for specialist investigation commands.
# Artifact-writing roles use Edit/Write for assigned files. This deny-list
# raises the bar against shell mutations; it is not a sandbox. Role prompts
# own artifact scope and any explicitly permitted verification side effects.
set -euo pipefail

input=$(cat)
command -v jq >/dev/null 2>&1 || exit 0
cmd=$(jq -r '.tool_input.command // ""' <<<"$input")
[[ -n "$cmd" ]] || exit 0

deny() {
  jq -cn --arg r "readonly-guard: investigation shell mutation blocked: $1. Use file-editing tools for assigned artifacts. Return implementation work to the lead. If this command was read-only or an authorized verification check, report the rejection instead of working around the guard." \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

# Strip quoted segments first: a mutation verb or ">" inside quotes is data —
# grep patterns, awk expressions, commit-message searches — not a command.
# (Costs a quote-the-verb bypass; acceptable for a bar, not a sandbox.)
q=$(sed -E "s/'[^']*'//g"' ; s/"[^"]*"//g' <<<"$cmd")

# Output redirection: scrub harmless stderr/null forms first.
scrubbed=$(sed -E 's/2>&1//g; s/[&12]?>{1,2}[[:space:]]*\/dev\/(null|stderr|stdout)//g' <<<"$q")
[[ "$scrubbed" == *">"* ]] && deny "output redirection"

grep -Eq '(^|[;&|[:space:]])(rm|rmdir|unlink|mv|cp|dd|tee|touch|truncate|mkdir|ln|chmod|chown|kill|pkill|shred|install)([[:space:]]|$)' <<<"$q" \
  && deny "file/process mutation"
grep -Eq '(^|[;&|[:space:]])git[[:space:]]+(add|commit|push|pull|fetch|reset|checkout|switch|restore|stash|rebase|merge|cherry-pick|clean|revert|tag|am|apply|config|branch[[:space:]]+-[dDmM])([[:space:]]|$)' <<<"$q" \
  && deny "mutating git command"
grep -Eq 'sed[[:space:]]+[^|;]*-i' <<<"$q" && deny "in-place sed"
grep -Eq '(^|[;&|[:space:]])(npm|pnpm|yarn|pip|pipx|cargo|nix-env|nix)[[:space:]]+(install|add|remove|uninstall|profile)([[:space:]]|$)' <<<"$q" \
  && deny "package/system mutation"
grep -Eq '(^|[;&|[:space:]])(systemctl|service)[[:space:]]+(start|stop|restart|reload|enable|disable)([[:space:]]|$)' <<<"$q" \
  && deny "service mutation"
grep -Eq -- '-delete' <<<"$q" && deny "find -delete"
grep -Eq 'xargs[[:space:]].*(rm|mv|cp)([[:space:]]|$)' <<<"$q" && deny "xargs mutation"

exit 0
