#!/usr/bin/env bash
# readonly-guard: PreToolUse(Bash) hook carried by the read-only role agents
# (scout, Explore, verify, review, Plan) via their frontmatter. Their tool
# lists already exclude Edit/Write; this closes the Bash hole by denying
# mutating commands. A deny-list raises the bar, it is not a sandbox — the
# role prompts remain the semantic guard.
set -euo pipefail

input=$(cat)
command -v jq >/dev/null 2>&1 || exit 0
cmd=$(jq -r '.tool_input.command // ""' <<<"$input")
[[ -n "$cmd" ]] || exit 0

deny() {
  jq -cn --arg r "readonly-guard: this role is read-only — blocked: $1. Verify and report; never fix. If the command was genuinely read-only, note the false positive in your report instead of working around the guard." \
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
