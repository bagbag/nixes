#!/usr/bin/env bash
# bd-guard: PreToolUse(Bash) gate for beads commands.
# - Denies bd run in parallel (xargs -P, GNU parallel, a trailing &): each bd
#   call holds the embedded database and blocks every other beads command.
# - In lead-mode sessions, denies bd commands outside a few reads without
#   `--actor` (or a BEADS_ACTOR= prefix), so the audit trail names the writer.
set -euo pipefail

input=$(cat)
command -v jq >/dev/null 2>&1 || exit 0
cmd=$(jq -r '.tool_input.command // ""' <<<"$input")
[[ "$cmd" == *bd* ]] || exit 0

deny() {
  jq -cn --arg r "bd-guard: $1" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

# Quoted text is data, except that xargs often wraps bd in a quoted sh -c.
stripped=$(sed -E "s/'[^']*'//g"' ; s/"[^"]*"//g' <<<"$cmd")
if grep -Eq "(xargs[^|;]*(-P|--max-procs)|parallel)[^|;]*[[:space:]'\"]bd[[:space:]]" <<<"$cmd" ||
  sed -E 's/[0-9]*>&[0-9-]*|&>//g' <<<"$stripped" | grep -Eq '(^|[[:space:];|(])bd[[:space:]][^;]*[^&]&([^&]|$)'; then
  deny 'parallel bd calls block other beads commands. Run bd serially in the foreground; read inventories with one `bd list --all --limit 0 --json`.'
fi

# Without a payload session id, session-lead-mode falls back to the session env.
session_id=$(jq -r '.session_id // ""' <<<"$input")
mode=$(bash "${AGENT_SESSION_LEAD_COMMAND:-$HOME/.agents/bin/session-lead-mode}" get $session_id 2>/dev/null || true)
[[ -n "$mode" ]] || exit 0
[[ "$cmd" =~ (--actor|BEADS_ACTOR=|BD_ACTOR=|--help|--dry-run) ]] && exit 0

segments=$stripped
for delimiter in '&&' '||' ';' '|' '&' '(' ')'; do
  segments=${segments//"$delimiter"/$'\n'}
done
while read -r -a words; do
  ((${#words[@]})) || continue
  set -- "${words[@]}"
  while (($#)) && [[ "$1" =~ ^(.*=.*|then|do|else)$ ]]; do shift; done
  [[ "${1:-}" == bd ]] || continue
  shift
  [[ "${1:-}" == -C ]] && shift 2
  [[ "${1:-}" =~ ^(dep|gate|config)$ && "${2:-}" =~ ^(list|tree|cycles|show|check|get)$ ]] && continue
  case "${1:-}" in
    list | show | ready | search | history | count | children | query | blocked | stale | status | memories | prime | help | version | diff | events | graph | find-duplicates | info | where | export | '' | -*) ;;
    *) deny "\`bd $1\` without an actor. Re-run it with \`--actor <mode or worker>\` or a \`BEADS_ACTOR=<mode or worker> \` prefix ($mode for this session's own writes)." ;;
  esac
done <<<"$segments"
