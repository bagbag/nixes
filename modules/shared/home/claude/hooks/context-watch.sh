#!/usr/bin/env bash
# context-watch: warn a session as it approaches auto-compaction.
#
# Every session gets baseline "compaction is near" warnings. Sessions that opt
# into a mode get richer, mode-specific guidance; a session opts in by writing
# its mode to /tmp/claude-context-watch/<session_id>.mode — the supervisor and
# autopilot skills do this on invocation.
#
#   default:    no opt-in — last-warning rungs only (compaction imminent).
#   supervisor: 35 42 50, then +5 up to 80 -> recommend compaction.
#   autopilot:  no fixed rungs — steered entirely by the last-warnings.
#   every mode: last-warning rungs at the compaction point -5/-2/-1.
# Rungs are one-shot, re-armed when usage drops (e.g. after compaction).
#
# The compaction point is ESTIMATED as autoCompactWindow minus a reserve
# (CONTEXT_WATCH_RESERVE_PCT, a percent of that window, default 10) so warnings land
# before auto-compaction actually fires, not right at it -- Claude Code itself
# keeps output headroom below autoCompactWindow, so the real trigger is a bit
# under the configured budget. Rung thresholds are percentages of the full
# model window. Messages carry no numbers -- they go into the model's context,
# so they state only what to do, not telemetry the user already sees.
#
# Tunable resolution (first hit wins):
#   window   CONTEXT_WATCH_WINDOW env > 1M assumed (every non-Haiku model is 1M)
#   acw      CLAUDE_CODE_AUTO_COMPACT_WINDOW env > settings.autoCompactWindow > window
#   reserve  CONTEXT_WATCH_RESERVE_PCT env > settings.env.CONTEXT_WATCH_RESERVE_PCT > 10
set -euo pipefail

command -v jq >/dev/null 2>&1 || exit 0
input=$(cat)
settings="$HOME/.claude/settings.json"
dir=/tmp/claude-context-watch

# Read a value: env override wins, else settings.json at <jq-path>, else default.
setting() {  # <jq-path> <env-override> <default>
  local val=${2:-}
  [[ -z "$val" ]] && val=$(jq -r "$1 // empty" "$settings" 2>/dev/null || true)
  printf '%s' "${val:-$3}"
}

# --- hook payload -----------------------------------------------------------
session_id=$(jq -r '.session_id // empty'         <<<"$input")
transcript=$(jq -r '.transcript_path // empty'    <<<"$input")
event=$(jq -r '.hook_event_name // "PostToolUse"' <<<"$input")
[[ -n "$session_id" && -n "$transcript" && -f "$transcript" ]] || exit 0

mode=default
[[ -f "$dir/$session_id.mode" ]] && mode=$(<"$dir/$session_id.mode")

# --- window (percentage base) -----------------------------------------------
# Every current model (Opus, Sonnet, Fable) has a 1M window; only Haiku is
# smaller, and it runs only short mechanical tasks. The hook payload carries no
# model or context size to detect from, so assume 1M — override with
# CONTEXT_WATCH_WINDOW (e.g. a Haiku-only launcher) if ever needed.
window=${CONTEXT_WATCH_WINDOW:-1000000}
[[ "$window" =~ ^[0-9]+$ ]] || window=1000000

# --- estimated compaction point (percent of window) -------------------------
acw=$(setting '.autoCompactWindow' "${CLAUDE_CODE_AUTO_COMPACT_WINDOW:-}" "$window")
[[ "$acw" =~ ^[0-9]+$ ]] || acw=$window
(( acw > window )) && acw=$window
reserve=$(setting '.env.CONTEXT_WATCH_RESERVE_PCT' "${CONTEXT_WATCH_RESERVE_PCT:-}" 10)
{ [[ "$reserve" =~ ^[0-9]+$ ]] && (( reserve < 100 )); } || reserve=10
eff_acw=$(( acw - acw * reserve / 100 ))
(( eff_acw < 1 )) && eff_acw=$acw
compact_pct=$(( eff_acw * 100 / window ))
imminent_pct=$(( compact_pct - 5 ))

# --- rungs ------------------------------------------------------------------
case "$mode" in
  supervisor) rungs=(35 42 50 55 60 65 70 75 80) ;;
  *)          rungs=() ;;   # autopilot + default: steered by the last-warnings
esac
for off in 5 2 1; do
  r=$(( compact_pct - off ))
  (( r > 0 )) && rungs+=("$r")
done

mkdir -p "$dir"

# --- one-shot window-fit check (opt-in modes only) --------------------------
# autopilot wants a lean window (cheap, frequent compaction; handover+ORIENT
# makes it free); supervisor arcs want a large one (the ladder assumes deep
# context). Warn once, judged against the real compaction point.
fitflag="$dir/$session_id.fitwarn"
if [[ ( "$mode" == "autopilot" || "$mode" == "supervisor" ) && ! -f "$fitflag" ]]; then
  fitmsg=""
  if [[ "$mode" == "autopilot" ]] && (( eff_acw > 400000 )); then
    fitmsg="context-watch: this autopilot session compacts around ${eff_acw} tokens — a large window makes every turn slower and costlier as context grows. Record the effective window in the journal, and recommend launching this routine with the lean default (no claude-full, no window override) in the ratification report."
  elif [[ "$mode" == "supervisor" ]] && (( eff_acw < 500000 )); then
    fitmsg="context-watch: this supervisor session compacts early (~${eff_acw} tokens) — a long arc will auto-compact repeatedly. Tell the user: relaunch via claude-full for this arc, or keep the board/docs continuously synced."
  fi
  if [[ -n "$fitmsg" ]]; then
    : >"$fitflag"
    jq -cn --arg e "$event" --arg m "$fitmsg" \
      '{hookSpecificOutput:{hookEventName:$e,additionalContext:$m}}'
    exit 0
  fi
fi

# --- current usage ----------------------------------------------------------
# Most recent assistant API call's usage (input + cache). Scan tail backwards,
# first valid wins.
tokens=""
while IFS= read -r line; do
  t=$(jq -r 'try (.message.usage | select(.input_tokens != null)
        | (.input_tokens + (.cache_read_input_tokens // 0) + (.cache_creation_input_tokens // 0)))
        // empty' <<<"$line" 2>/dev/null) || t=""
  if [[ -n "$t" ]]; then tokens=$t; break; fi
done < <(tail -c 512000 "$transcript" | grep '"usage"' | tac || true)
[[ -n "$tokens" ]] || exit 0
pct=$(( tokens * 100 / window ))

# --- ladder state -----------------------------------------------------------
# Highest rung at or below current usage.
current=0
for r in "${rungs[@]}"; do (( pct >= r )) && current=$r; done

# One state file per transcript: a subagent's PostToolUse carries its own
# transcript under the same session and must not consume the main ladder.
state="$dir/$session_id.$(basename "$transcript").last"
last=0
[[ -f "$state" ]] && last=$(<"$state")

# Usage dropped below the announced rung (compaction/clear): re-arm silently.
if (( current < last )); then echo "$current" >"$state"; exit 0; fi
# Otherwise announce only when crossing up to a higher rung (one-shot).
(( current > last )) || exit 0
echo "$current" >"$state"

# --- message ----------------------------------------------------------------
# default mode only ever reaches the imminent branch (its rungs are just the
# last-warnings); the mid/low branches fire only for opt-in modes on a large
# window, where the ladder spreads out.
msg=""
if (( current >= imminent_pct )); then
  case "$mode" in
    supervisor) msg="context-watch: auto-compaction is IMMINENT. Bring every coordination doc fully in sync NOW and keep it in sync with every further change: when compaction runs, nothing of value may exist only in this session." ;;
    autopilot)  msg="context-watch: auto-compaction is IMMINENT. Refresh the handover note and journal NOW and keep them in sync with every further change (checkpoint-commit only when the tree is coherent); when compaction runs, ORIENT from the note to re-ground." ;;
    *)          msg="context-watch: auto-compaction is imminent — the conversation will be condensed automatically. Keep working; if you are maintaining any docs, notes, or a plan/handover file, bring them in sync now so nothing important survives only in this conversation." ;;
  esac
elif (( current <= 60 )); then
  case "$mode" in
    supervisor) msg="context-watch: compacting early is an economy measure — it keeps speed and quality up and quota burn down. Recommend it to the user at the next natural pause (sync coordination docs first), and check what's bloating: inline reads a worker should have done, verbose tool output kept in-context." ;;
    autopilot)  msg="context-watch: refresh the handover note at the next milestone and keep delegating reads to workers — small context keeps every turn faster, sharper, and cheaper." ;;
  esac
else
  case "$mode" in
    supervisor) msg="context-watch: context is deep now — it degrades speed and quality and burns quota every turn. Actively steer to a cheap-loss point and recommend compaction; bring every coordination doc fully in sync first (board, index, decision log)." ;;
    autopilot)  msg="context-watch: run the handover protocol now — WRITE/refresh the handover note and journal (checkpoint-commit only at the next coherent state), then continue working; when auto-compaction fires, ORIENT from the note to re-ground." ;;
  esac
fi

if [[ -n "$msg" ]]; then
  jq -cn --arg e "$event" --arg m "$msg" \
    '{hookSpecificOutput:{hookEventName:$e,additionalContext:$m}}'
fi
