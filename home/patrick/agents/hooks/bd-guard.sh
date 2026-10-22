#!/usr/bin/env bash
# bd-guard: PreToolUse(Bash) gate for beads commands (bd and the board CLI).
# - On embedded boards, denies bd run in parallel (xargs -P, GNU parallel, a
#   trailing &): each bd call holds the embedded database and blocks every
#   other beads command. Boards whose .beads/metadata.json (searched from the
#   payload cwd upward) says "dolt_mode": "server" take concurrent calls.
# - Denies bare bd: agents run it as `board bd`, which sets the actor and
#   starts the server.
# - Prefixes a Claude subagent's board commands with `export BEADS_ACTOR=<actor>; `:
#   its id reaches only this payload; board derives every other actor from the
#   environment. A bare `VAR=x` prefix would reach only the first command of
#   `cd x && board ...`. Format: work-tracking.md#actors-and-holds.
# - Denies an explicit --actor, BEADS_ACTOR or BD_ACTOR that differs from the
#   derived actor; it would hold items outside the session's `board mine`.
set -euo pipefail

input=$(cat)
command -v jq >/dev/null 2>&1 || exit 0
original=$(jq -r '.tool_input.command // "" | if type == "array" then join(" ") else tostring end' <<<"$input")
[[ "$original" == *bd* || "$original" == *board* ]] || exit 0
cmd=${original//$'\\\n'/ }

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
beads='([^[:space:];&|()'\''"]*/)?(bd|board)'
# Newlines separate commands; joining lines first keeps multi-line quotes paired.
stripped=$(tr '\n' ';' <<<"$cmd" | sed -E "s/'[^']*'|\"[^\"]*\"//g")

server_board() {
  local dir
  dir=$(jq -r '.cwd // ""' <<<"$input")
  dir=${dir:-$PWD}
  while [[ -n "$dir" ]]; do
    if [[ -f "$dir/.beads/metadata.json" ]]; then
      board_root=$dir
      [[ $(jq -r '.dolt_mode // ""' "$dir/.beads/metadata.json" 2>/dev/null) == server ]]
      return
    fi
    [[ "$dir" == / ]] && return 1
    dir=$(dirname "$dir")
  done
  return 1
}

parallel_beads() {
  { grep -Eq '(^|[;&|(])[[:space:]]*(xargs([[:space:]][^;&|]*)?[[:space:]](-P|--max-procs)|parallel[[:space:]])' <<<"$stripped" &&
    grep -Eq "(^|[[:space:];&|('\"])$beads[[:space:]]" <<<"$cmd"; } ||
    sed -E 's/[0-9]*>&[0-9-]*|&>//g' <<<"$stripped" | grep -Eq "(^|[[:space:];|(])$beads[[:space:]][^;]*[^&]&([^&]|\$)"
}

if parallel_beads && ! server_board; then
  deny 'parallel board calls block each other on an embedded board. Run them serially in the foreground; read inventories with one `board bd export`.'
fi

# A command word, possibly quoted: after a separator, keyword, interpreter,
# assignment or `-c '` (sh -c '...').
position='(^|[;&|(`]|\$\(|-c[[:space:]]+['\''"]|(xargs|then|do|else|if|while|until|time|env|command|exec|nohup|bash|sh|zsh|python3?|!)[[:space:]]|[[:alnum:]_]+=[^[:space:]]*[[:space:]])'
word='([[:space:];&|)'\''"]|$)'
# Bare bd: quoted text is data, except `sh -c '...'` bodies, which run.
bare="$position[[:space:]]*([^[:space:];&|()'\"]*/)?bd$word"
bodies=$(grep -Eo -- "-c[[:space:]]+('[^']*'|\"[^\"]*\")" <<<"$cmd" | sed -E 's/^-c[[:space:]]+.(.*).$/\1/' || true)
if grep -Eq "$bare" <<<"$stripped" || { [[ -n "$bodies" ]] && grep -Eq "$bare" <<<"$bodies"; }; then
  deny 'run bd as `$HOME/.agents/bin/board bd <same args>`: it sets your actor and starts the board server.'
fi
grep -Eq "$position[[:space:]]*[\"']?$beads(\.py)?$word" <<<"$cmd" || exit 0

session_id=$(jq -r '.session_id // ""' <<<"$input")
[[ -n "$session_id" ]] || exit 0

actor=${session_id: -8}
agent_id=$(jq -r '.agent_id // ""' <<<"$input")
[[ -z "$agent_id" ]] || actor+="/${agent_id: -8}"

# Quoted text is data (comments may mention --actor); a quoted value is
# stripped to empty and so counts as differing.
while read -r explicit; do
  [[ -n "$explicit" ]] || continue
  value=${explicit#*[= ]}
  value=${value#"${value%%[![:space:]]*}"}
  [[ "$value" == "$actor" ]] ||
    deny "explicit actor \`${explicit}\` differs from your actor \`$actor\`. Drop it; board derives your actor."
done < <(grep -Eo "(--actor[=[:space:]]+|(BEADS_ACTOR|BD_ACTOR)=)[^[:space:];&|)]*" <<<"$stripped" || true)

# Claude subagents only (Codex payloads carry turn_id). Without a decision,
# Claude evaluates its permission rules against updatedInput.
[[ -n "$agent_id" ]] && jq -e '.turn_id == null' >/dev/null <<<"$input" || exit 0
prefix="export BEADS_ACTOR=$(printf '%q' "$actor"); "
[[ "$original" != "$prefix"* ]] || exit 0
jq -c --arg p "$prefix" --arg a "$actor" '
  {hookSpecificOutput:{hookEventName:"PreToolUse",
    updatedInput:(.tool_input | .command |= (if type == "array" then ["env", "BEADS_ACTOR=" + $a] + . else $p + . end))}}' <<<"$input"
