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
cmd=${cmd//$'\\\n'/ }

# Heredoc bodies are data too (commit messages, scripts).
heredoc='<<-?[[:space:]]*["'\'']?([A-Za-z_][A-Za-z0-9_]*)'
body='' tag=''
while IFS= read -r line; do
  if [[ -n "$tag" ]]; then
    [[ "${line#"${line%%[![:space:]]*}"}" == "$tag" ]] && tag=''
    continue
  fi
  body+="$line"$'\n'
  [[ "$line" != *'<<<'* && "$line" =~ $heredoc ]] && tag=${BASH_REMATCH[1]}
done <<<"$cmd"
cmd=$body

deny() {
  jq -cn --arg r "bd-guard: $1" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

# Quoted text is data, except that xargs often wraps bd in a quoted sh -c.
stripped=$(sed -E "s/'[^']*'|\"[^\"]*\"//g" <<<"$cmd")
if { grep -Eq '(^|[;&|(])[[:space:]]*(xargs([[:space:]][^;&|]*)?[[:space:]](-P|--max-procs)|parallel[[:space:]])' <<<"$stripped" &&
  grep -Eq "(^|[[:space:];&|('\"])bd[[:space:]]" <<<"$cmd"; } ||
  sed -E 's/[0-9]*>&[0-9-]*|&>//g' <<<"$stripped" | grep -Eq '(^|[[:space:];|(])bd[[:space:]][^;]*[^&]&([^&]|$)'; then
  deny 'parallel bd calls block other beads commands. Run bd serially in the foreground; read inventories with one `bd list --all --limit 0 --json`.'
fi

# Without a payload session id, session-lead-mode falls back to the session env.
session_id=$(jq -r '.session_id // ""' <<<"$input")
mode=$(bash "${AGENT_SESSION_LEAD_COMMAND:-$HOME/.agents/bin/session-lead-mode}" get $session_id 2>/dev/null || true)
[[ -n "$mode" ]] || exit 0
[[ "$cmd" =~ (BEADS_ACTOR=|BD_ACTOR=) ]] && exit 0

segments=$stripped
for delimiter in '&&' '||' ';' '|' '&' '(' ')'; do
  segments=${segments//"$delimiter"/$'\n'}
done
while read -r -a words; do
  ((${#words[@]})) || continue
  set -- "${words[@]}"
  while (($#)) && [[ "$1" =~ ^(.*=.*|if|elif|while|until|then|do|else|!|\{|time|env|command|exec|nohup)$ ]]; do shift; done
  [[ "${1:-}" == bd ]] || continue
  [[ " $* " =~ [[:space:]](--actor|--help|--dry-run|--readonly)[=[:space:]] ]] && continue
  shift
  while [[ "${1:-}" == -* ]]; do
    case $1 in
      -C | --db | --database) shift $(($# < 2 ? $# : 2)) ;;
      *) shift ;;
    esac
  done
  [[ "${1:-}" =~ ^(dep|gate|config|epic|human|kv|memory|backup|dolt)$ && "${2:-}" =~ ^(list|tree|cycles|show|check|get|status|close-eligible)$ ]] && continue
  [[ "${1:-}" == comments && "${2:-}" != add ]] && continue
  [[ "${1:-}" =~ ^(doctor|orphans)$ && ! " $* " =~ [[:space:]](--fix|-f)[=[:space:]] ]] && continue
  case "${1:-}" in
    list | show | ready | search | history | count | children | query | blocked | stale | status | memories | prime | help | version | diff | events | graph | find-duplicates | info | where | export | lint | types | stats | '' | -* | [0-9]'>'* | '>'* | '<'* | '$'*) ;;
    *) deny "\`bd $1\` without an actor. Re-run it with \`--actor <mode or worker>\` or a \`BEADS_ACTOR=<mode or worker> \` prefix ($mode for this session's own writes)." ;;
  esac
done <<<"$segments"
