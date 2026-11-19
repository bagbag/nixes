# Drain the battery to a target percentage while the charger stays plugged in,
# then re-enable the power adapter. Detaches into the background, so the
# terminal can be closed. Packaged as `drain-battery` by default.nix, which
# supplies the shebang and strict mode.
#
#   drain-battery [target]   start (default target: 80)
#   drain-battery --stop     stop a running drain and re-enable the adapter
#   drain-battery --status   show the drain and the adapter state
#
# Needs `batt` (native charge-limit mode). The charge limit is not changed.
# If the Mac loses power mid-drain the adapter stays disabled: run
# `batt adapter enable`.

state_dir="${TMPDIR:-/tmp}/drain-battery"
pidfile="$state_dir/pid"
logfile="$state_dir/log"
poll_seconds=30

# Prints the pid only when it is a live drain process, not a pid reused since a crash.
running_pid() {
  [[ -f $pidfile ]] || return 1
  local pid
  pid=$(<"$pidfile")
  [[ $(ps -p "$pid" -o command= 2>/dev/null) == *"--child"* ]] && echo "$pid"
}

charge() {
  batt status | awk '/Current charge/ { gsub("%", "", $3); print $3 }'
}

case "${1:-}" in
  --status)
    if pid=$(running_pid); then echo "drain running (pid $pid), log: $logfile"; else echo "no drain running"; fi
    batt adapter status 2>&1 | sed 's/.*msg=//'
    exit 0
    ;;
  --stop)
    if pid=$(running_pid); then
      kill "$pid" # the child's trap re-enables the adapter
      for _ in {1..20}; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
      done
      echo "stopped"
    else
      echo "no drain running"
    fi
    exit 0
    ;;
  --child)
    target=$2
    sleep_pid=""
    echo $$ >"$pidfile"
    trap 'kill "$sleep_pid" 2>/dev/null || true; batt adapter enable; rm -f "$pidfile"' EXIT
    trap 'exit 0' INT TERM HUP
    batt adapter disable
    # An empty or failed charge reading ends the loop and re-enables the adapter.
    while current=$(charge) && [[ $current -gt $target ]]; do
      echo "$(date '+%H:%M:%S') charge ${current}% > ${target}%"
      # Background sleep + wait lets a signal run the trap at once.
      sleep "$poll_seconds" &
      sleep_pid=$!
      wait "$sleep_pid"
    done
    echo "$(date '+%H:%M:%S') done at ${current:-unknown}%"
    exit 0
    ;;
esac

target=${1:-80}
if ! [[ $target =~ ^[0-9]+$ ]] || ((target < 1 || target > 99)); then
  echo "target must be 1-99" >&2
  exit 2
fi

mkdir -p "$state_dir"
if pid=$(running_pid); then echo "already running (pid $pid)" >&2; exit 1; fi

current=$(charge)
((current > target)) || { echo "charge ${current}% is already at or below ${target}%" >&2; exit 1; }

# caffeinate keeps the Mac awake for the duration; nohup survives terminal close.
nohup caffeinate -i bash "$0" --child "$target" >"$logfile" 2>&1 &
disown
echo "draining from ${current}% to ${target}% in the background (log: $logfile; stop: drain-battery --stop)"
