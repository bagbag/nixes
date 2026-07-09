#!/usr/bin/env bash
# context-watch: inject context-usage warnings into sessions that registered a
# mode. A session opts in by writing its mode to
# /tmp/claude-context-watch/<session_id>.mode ("supervisor" or "autopilot") —
# the supervisor and autopilot skills do this on invocation. Unregistered
# sessions get nothing.
#
# Ladders (one-shot per rung, re-armed when usage drops, e.g. after compaction):
#   supervisor: 35 42 50, then every 5 up to 80 -> recommend compaction
#   autopilot:  no fixed rungs — steered entirely by the last-warnings
# Both get last-warning rungs at compaction-point −5/−2/−1 (escalated message:
# compaction imminent, keep docs in sync with every change). For a lean
# autopilot launch (compact at 35%) that means steering starts at 30%.
set -euo pipefail

input=$(cat)
command -v jq >/dev/null 2>&1 || exit 0

session_id=$(jq -r '.session_id // empty' <<<"$input")
transcript=$(jq -r '.transcript_path // empty' <<<"$input")
event=$(jq -r '.hook_event_name // "PostToolUse"' <<<"$input")
[[ -n "$session_id" && -n "$transcript" && -f "$transcript" ]] || exit 0

dir=/tmp/claude-context-watch
mode_file="$dir/$session_id.mode"
[[ -f "$mode_file" ]] || exit 0
mode=$(<"$mode_file")

case "$mode" in
  supervisor) rungs=(35 42 50 55 60 65 70 75 80) ;;
  autopilot)  rungs=() ;;
  *) exit 0 ;;
esac


# Percentages are relative to the full model window — the same base the
# statusline uses — so the numbers match what the user sees. Auto-compaction
# fires at the autoCompactWindow point: 35% of the window under the lean
# settings default (350k), 90% under a claude-full launch (900k) — rungs above
# the session's compact point never fire. Priority: test override > model default.
window=${CONTEXT_WATCH_WINDOW:-}
if [[ -z "$window" ]]; then
  model=$(jq -r '.model // ""' "$HOME/.claude/settings.json" 2>/dev/null || echo "")
  case "$model" in *"[1m]"*) window=1000000 ;; *) window=200000 ;; esac
fi

# Auto-compaction point (as % of window). Env first: a session launched with
# CLAUDE_CODE_AUTO_COMPACT_WINDOW overrides the settings default, and hooks
# inherit the session env — so per-session windows are tracked automatically.
# Then settings autoCompactWindow, then full window (reactive at the wall).
# Last-warning rungs sit at fixed offsets below the point, escalated message.
acw=${CLAUDE_CODE_AUTO_COMPACT_WINDOW:-}
if [[ -z "$acw" ]]; then
  acw=$(jq -r '.autoCompactWindow // empty' "$HOME/.claude/settings.json" 2>/dev/null || true)
fi
[[ -n "$acw" ]] || acw=$window
(( acw > window )) && acw=$window
compact_pct=$(( acw * 100 / window ))
imminent_pct=$(( compact_pct - 5 ))

# One-shot window-fit check: autopilot wants a lean window (cheap frequent
# windows; handover+ORIENT makes compaction free), supervisor arcs want a
# large one (the ladder assumes deep context). Warn once on mismatch.
fitflag="$dir/$session_id.fitwarn"
if [[ ! -f "$fitflag" ]]; then
  fitmsg=""
  if [[ "$mode" == "autopilot" ]] && (( acw > 400000 )); then
    fitmsg="context-watch: this autopilot session runs with a large compaction window (${acw} tokens) — turns get slower and costlier as context grows. Record the effective window in the journal, and recommend launching this routine with the lean default (no claude-full, no window override) in the ratification report."
  elif [[ "$mode" == "supervisor" ]] && (( acw < 500000 )); then
    fitmsg="context-watch: this supervisor session runs with a lean compaction window (${acw} tokens) — a long arc will auto-compact early and repeatedly. Tell the user: relaunch via claude-full for this arc, or expect compaction at ~${compact_pct}% and keep the board/docs continuously synced."
  fi
  if [[ -n "$fitmsg" ]]; then
    : >"$fitflag"
    jq -cn --arg e "$event" --arg m "$fitmsg" \
      '{hookSpecificOutput:{hookEventName:$e,additionalContext:$m}}'
    exit 0
  fi
fi
for off in 5 2 1; do
  r=$(( compact_pct - off ))
  (( r > 0 )) && rungs+=("$r")
done

# Current context size = usage of the most recent assistant API call in the
# transcript (input + cache tokens). Scan the tail backwards, first valid wins.
tokens=""
while IFS= read -r line; do
  t=$(jq -r 'try (.message.usage | select(.input_tokens != null)
        | (.input_tokens + (.cache_read_input_tokens // 0) + (.cache_creation_input_tokens // 0)))
        // empty' <<<"$line" 2>/dev/null) || t=""
  if [[ -n "$t" ]]; then tokens=$t; break; fi
done < <(tail -c 512000 "$transcript" | grep '"usage"' | tac || true)
[[ -n "$tokens" ]] || exit 0

pct=$(( tokens * 100 / window ))

# Highest rung at or below current usage.
current=0
for r in "${rungs[@]}"; do (( pct >= r )) && current=$r; done

# State per transcript: subagent PostToolUse events carry their own transcript
# under the same session and must not re-arm or consume the main ladder.
state="$dir/$session_id.$(basename "$transcript").last"
last=0
[[ -f "$state" ]] && last=$(<"$state")

# Usage dropped below the announced rung (compaction/clear): re-arm silently.
if (( current < last )); then
  echo "$current" >"$state"
  exit 0
fi
(( current > last )) || exit 0
echo "$current" >"$state"

if (( current >= imminent_pct )); then
  case "$mode" in
    supervisor)
      msg="context-watch: ≈${pct}% of the context window used — auto-compaction (at ~${compact_pct}%) is IMMINENT. Bring every coordination doc fully in sync NOW and keep it in sync with every further change: when compaction runs, nothing of value may exist only in this session." ;;
    autopilot)
      msg="context-watch: ≈${pct}% of the context window used — auto-compaction (at ~${compact_pct}%) is IMMINENT. Refresh the handover note and journal NOW and keep them in sync with every further change (checkpoint-commit only when the tree is coherent); when compaction runs, ORIENT from the note to re-ground." ;;
  esac
elif (( current <= 60 )); then
  case "$mode" in
    supervisor)
      msg="context-watch: ≈${pct}% of the context window used. Compacting early is an economy measure — it keeps speed and quality up and quota burn down. Recommend it to the user at the next natural pause (sync coordination docs first), and check what's bloating: inline reads a worker should have done, verbose tool output kept in-context." ;;
    autopilot)
      msg="context-watch: ≈${pct}% of the context window used. Refresh the handover note at the next milestone and keep delegating reads to workers — small context keeps every turn faster, sharper, and cheaper." ;;
  esac
else
  case "$mode" in
    supervisor)
      msg="context-watch: ≈${pct}% of the context window used. Context at this level degrades speed and quality and burns quota every turn — actively steer to a cheap-loss point and recommend compaction; bring every coordination doc fully in sync first (board, index, decision log)." ;;
    autopilot)
      msg="context-watch: ≈${pct}% of the context window used. Run the handover protocol now: WRITE/refresh the handover note and journal (checkpoint-commit only at the next coherent state) — then continue working; when auto-compaction fires, ORIENT from the note to re-ground." ;;
  esac
fi

jq -cn --arg e "$event" --arg m "$msg" \
  '{hookSpecificOutput:{hookEventName:$e,additionalContext:$m}}'
