#!/usr/bin/env bash
export LC_NUMERIC=C  # ensure '.' decimal separator for printf %f
input=$(cat)

command -v jq >/dev/null 2>&1 || { printf '\033[31m[missing: jq]\033[0m'; exit 0; }

mapfile -t vals < <(jq -r '
 (.cwd // .workspace.current_dir // ""),
 (.model.display_name // ""),
 (.context_window.used_percentage // ""),
 (.context_window.total_input_tokens // 0),
 (.context_window.total_output_tokens // 0),
 (.context_window.cache_read_input_tokens // 0),
 (.context_window.cache_creation_input_tokens // 0),
 (.rate_limits.five_hour.used_percentage // ""),
 (.rate_limits.five_hour.resets_at // ""),
 (.rate_limits.seven_day.used_percentage // ""),
 (.rate_limits.seven_day.resets_at // "")
' <<<"$input")
cwd=${vals[0]}
model=${vals[1]}
used=${vals[2]}
total_input=${vals[3]}
total_output=${vals[4]}
cache_read=${vals[5]}
cache_creation=${vals[6]}
five_hour=${vals[7]}
five_hour_resets=${vals[8]}
seven_day=${vals[9]}
seven_day_resets=${vals[10]}

printf -v now '%(%s)T' -1

# Session timer (persists across renders via PPID-keyed temp file)
session_file="/tmp/claude-session-${PPID}"
if [ ! -f "$session_file" ]; then
 printf '%s' "$now" > "$session_file"
fi
read -r session_start < "$session_file"
session_secs=$(( now - session_start ))
session_hrs=$(( session_secs / 3600 ))
session_mins=$(( (session_secs % 3600) / 60 ))
if (( session_hrs > 0 )); then
 printf -v session_time '%dh%02dm' "$session_hrs" "$session_mins"
else
 printf -v session_time '%dm' "$session_mins"
fi

# Git branch (optional)
git_branch=""
if [ -n "$cwd" ] && command -v git >/dev/null 2>&1 && git -C "$cwd" rev-parse --git-dir >/dev/null 2>&1; then
 git_branch=$(git -C "$cwd" -c core.hooksPath=/dev/null symbolic-ref --short HEAD 2>/dev/null || git -C "$cwd" rev-parse --short HEAD 2>/dev/null)
fi

# Display dir: ~ for HOME, strip ~/projects/, drop trailing component if it equals branch
display_dir=${cwd/#$HOME/\~}
display_dir=${display_dir/#\~\/projects\//}
if [ -n "$git_branch" ]; then
 last_component=${display_dir##*/}
 [ "$last_component" = "$git_branch" ] && display_dir=${display_dir%/*}
fi

# Model name: "Claude Opus 4.7 (1M context)" -> "Opus 4.7 1M"
model=${model#Claude }
model=${model//(/}
model=${model//)/}
model=${model// context/}
model=${model//  / }
model=${model% }

# Family color
case $model in
 Opus*)   model_color=$'\033[35m' ;;   # magenta
 Sonnet*) model_color=$'\033[36m' ;;   # cyan
 Haiku*)  model_color=$'\033[32m' ;;   # green
 *)       model_color=$'\033[37m' ;;
esac

# Pre-built 10-char bar templates for cheap substring slicing
BAR_FULL='██████████'
BAR_GHOST='▒▒▒▒▒▒▒▒▒▒'
BAR_EMPTY='░░░░░░░░░░'

make_bar() {
 local pct=$1
 local filled=$(( (pct * 10 + 50) / 100 ))
 (( filled > 10 )) && filled=10
 local empty=$(( 10 - filled ))
 _bar="${BAR_FULL:0:filled}${BAR_EMPTY:0:empty}"
}

make_rate_bar() {
 local pct=$1 expected=$2
 local filled=$(( (pct * 10 + 50) / 100 ))
 (( filled > 10 )) && filled=10
 local ghost_end=$(( (expected * 10 + 50) / 100 ))
 (( ghost_end > 10 )) && ghost_end=10
 (( ghost_end < filled )) && ghost_end=$filled
 local ghost=$(( ghost_end - filled ))
 local empty=$(( 10 - ghost_end ))
 _bar="${BAR_FULL:0:filled}${BAR_GHOST:0:ghost}${BAR_EMPTY:0:empty}"
}

# Linearly extrapolate end-of-period usage from current usage and elapsed fraction
calc_expected() {
 local pct=$1 resets_at=$2 period_secs=$3
 _expected=$pct
 [ -z "$resets_at" ] && return
 local period_start=$(( resets_at - period_secs ))
 local elapsed=$(( now - period_start ))
 (( elapsed <= 0 )) && return
 _expected=$(( pct * period_secs / elapsed ))
}

fmt_countdown() {
 local resets_at=$1
 _countdown=""
 [ -z "$resets_at" ] && return
 local secs=$(( resets_at - now ))
 if (( secs <= 0 )); then _countdown=now; return; fi
 local days=$(( secs / 86400 ))
 local hrs=$(( (secs % 86400) / 3600 ))
 local mins=$(( (secs % 3600) / 60 ))
 if (( days > 0 )); then
   printf -v _countdown '%dd%dh' "$days" "$hrs"
 elif (( hrs > 0 )); then
   printf -v _countdown '%dh%dm' "$hrs" "$mins"
 else
   printf -v _countdown '%dm' "$mins"
 fi
}

# Green <70%, yellow >=70%, orange >=85%, red >=95%
quota_color() {
 local pct=$1
 if   (( pct >= 95 )); then _color=$'\033[31m'
 elif (( pct >= 85 )); then _color=$'\033[38;5;208m'
 elif (( pct >= 70 )); then _color=$'\033[33m'
 else                       _color=$'\033[32m'
 fi
}

# Inverted: higher cache-hit is better
cache_color() {
 local pct=$1
 if   (( pct >= 90 )); then _color=$'\033[32m'
 elif (( pct >= 70 )); then _color=$'\033[33m'
 elif (( pct >= 40 )); then _color=$'\033[38;5;208m'
 else                       _color=$'\033[31m'
 fi
}

fmt_tokens() {
 local n=$1
 if (( n >= 1000000 )); then
   printf -v _tokens '%d.%dM' $((n / 1000000)) $(( (n % 1000000) / 100000 ))
 elif (( n >= 1000 )); then
   printf -v _tokens '%dk' $((n / 1000))
 else
   _tokens=$n
 fi
}

DIM=$'\033[2m'
RESET=$'\033[0m'
BLUE=$'\033[34m'
GREEN=$'\033[32m'
MAGENTA=$'\033[35m'
ORANGE=$'\033[38;5;208m'
SEP=" ${DIM}│${RESET} "

out=""
add_part() {
 if [ -n "$out" ]; then out="${out}${SEP}$1"; else out=$1; fi
}

# Location
loc=""
[ -n "$display_dir" ] && loc="${BLUE}${display_dir}${RESET}"
if [ -n "$git_branch" ]; then
 [ -n "$loc" ] && loc="$loc "
 loc="${loc}${GREEN}on ${RESET}${MAGENTA}${git_branch}${RESET}"
fi
[ -n "$loc" ] && add_part "$loc"

# Model
[ -n "$model" ] && add_part "${model_color}${model}${RESET}"

# Session
add_part "${DIM}${session_time}${RESET}"

# Context window
if [ -n "$used" ]; then
 printf -v used_int '%.0f' "$used"
 make_bar "$used_int"
 quota_color "$used_int"
 add_part "${DIM}ctx${RESET} ${_color}${_bar} ${used_int}%${RESET}"
fi

# Token totals
if { (( total_input > 0 )) || (( total_output > 0 )); }; then
 fmt_tokens "$total_input";  in_fmt=$_tokens
 fmt_tokens "$total_output"; out_fmt=$_tokens
 add_part "${DIM}${in_fmt}↑${out_fmt}↓${RESET}"
fi

# Cache-hit ratio
cache_total=$(( cache_read + cache_creation + total_input ))
if (( cache_read > 0 && cache_total > 0 )); then
 cache_pct=$(( cache_read * 100 / cache_total ))
 cache_color "$cache_pct"
 add_part "${DIM}cache${RESET} ${_color}${cache_pct}%${RESET}"
fi

# 5h rate limit
if [ -n "$five_hour" ]; then
 printf -v five_int '%.0f' "$five_hour"
 calc_expected "$five_int" "$five_hour_resets" 18000;     five_expected=$_expected
 fmt_countdown "$five_hour_resets";                       countdown=$_countdown
 quota_color "$five_expected";                            color=$_color
 make_rate_bar "$five_int" "$five_expected";              bar=$_bar
 suffix="${color}${bar} ${five_int}%${RESET}"
 (( five_expected > 100 )) && suffix="${suffix} ${ORANGE}⚠ ${five_expected}%${RESET}"
 [ -n "$countdown" ] && suffix="${suffix} ${countdown}"
 add_part "${DIM}5h${RESET} ${suffix}"
fi

# 7d rate limit
if [ -n "$seven_day" ]; then
 printf -v seven_int '%.0f' "$seven_day"
 calc_expected "$seven_int" "$seven_day_resets" 604800;   seven_expected=$_expected
 fmt_countdown "$seven_day_resets";                       countdown=$_countdown
 quota_color "$seven_expected";                           color=$_color
 make_rate_bar "$seven_int" "$seven_expected";            bar=$_bar
 suffix="${color}${bar} ${seven_int}%${RESET}"
 (( seven_expected > 100 )) && suffix="${suffix} ${ORANGE}⚠ ${seven_expected}%${RESET}"
 [ -n "$countdown" ] && suffix="${suffix} ${countdown}"
 add_part "${DIM}7d${RESET} ${suffix}"
fi

printf '%s' "$out"
