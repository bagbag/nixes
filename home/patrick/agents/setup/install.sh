#!/usr/bin/env bash
# Installs the Claude Code + Codex agent setup into $HOME; runs on the bash 3.2 macOS ships. Idempotent. A rerun from a
# newer bundle removes what the last install shipped and this one no longer does, recorded in ~/.agents/setup-state.json.
# Usage: ./install.sh [--no-mod] [--dry-run]
#        ./install.sh --uninstall [--dry-run]
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
files=$here/files
state=$HOME/.agents/setup-state.json
bd_tested=1.3.1
mod_value='~/.claude/mods/console'
uninstall=0
no_mod=0
dry=0
for a in "$@"; do
  case $a in
    --uninstall) uninstall=1 ;;
    --no-mod) no_mod=1 ;;
    --dry-run) dry=1 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

fail() { echo "$1 (nothing changed)" >&2; exit 1; }

# Every path below is "$HOME/<relative path>"; removals rest on both parts.
case ${HOME:-} in
  /*) ;;
  *) fail "HOME is not an absolute path: '${HOME:-}'" ;;
esac
[ -d "$HOME" ] || fail "HOME is not a folder: $HOME"
[ ! "$HOME" -ef / ] || fail "HOME is the root folder"

# ---- 1. preflight: everything here stops before the first change ----
command -v jq >/dev/null || fail "missing required tool: jq"
if [ "$uninstall" = 0 ]; then
  for c in bash python3 bd; do
    command -v "$c" >/dev/null || fail "missing required tool: $c"
  done
  python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
    || fail "python3 is $(python3 --version 2>&1); the board tool needs 3.11 or newer"
  found=$(bd --version 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)
  [ "$found" = "$bd_tested" ] || echo "NOTE: board is tested with bd $bd_tested; found ${found:-an unknown version}." >&2
fi

for f in "$HOME/.claude/settings.json" "$HOME/.codex/hooks.json" "$state"; do
  [ ! -e "$f" ] || jq -e 'type == "object"' "$f" >/dev/null 2>&1 || fail "${f#"$HOME/"} is not a JSON object; fix it first"
done

work=$(mktemp -d)
pending=
trap 'rm -rf "$work"; [ -z "$pending" ] || rm -f "$pending"' EXIT
list=$work/shipped
old=$work/installed
if [ "$uninstall" = 1 ]; then
  : >"$list"
elif [ "$no_mod" = 1 ]; then
  (cd "$files" && find . -type f | sed 's|^\./||' | grep -v '^\.claude/mods/' | LC_ALL=C sort) >"$list"
else
  (cd "$files" && find . -type f | sed 's|^\./||' | LC_ALL=C sort) >"$list"
fi
if [ -e "$state" ]; then jq -r '.files[]' "$state" | LC_ALL=C sort >"$old"; else : >"$old"; fi
# The state file decides what gets removed, so a damaged entry must not reach outside the install's own folders.
if grep -Ev '^\.(claude|codex|agents)/' "$old" | grep -q . || grep -Eq '(^|/)\.\.(/|$)' "$old"; then
  fail "${state#"$HOME/"} lists a path outside ~/.claude, ~/.codex and ~/.agents; fix or delete it first"
fi

# A symlinked file or folder (for example into a read-only store or a dotfiles repo) cannot be replaced safely.
refuse_symlink() {
  local p=$1
  while [ "$p" != . ]; do
    [ ! -L "$HOME/$p" ] || fail "~/$p is a symlink; resolve it first"
    p=$(dirname "$p")
  done
}
for rel in .claude/settings.json .codex/hooks.json .agents/setup-state.json; do refuse_symlink "$rel"; done
while IFS= read -r rel; do refuse_symlink "$rel"; done < <(cat "$list" "$old")

# Settings and state are computed now: a merge that fails stops here, before any change.
empty_hooks=$work/no-hooks.json
echo '{"hooks": {}}' >"$empty_hooks"

# $1: claude|codex  $2: settings file  $3: hook template  $4: jq filter applied last. Drops this setup's registrations, last
# install's and this one's, keeps the rest; writes the result to $work/$1.json, left empty when the file stays as it is.
plan_settings() {
  local tool=$1 target=$2 template=$3 extra=$4 earlier='[]' source=$2 result=$work/$1.json
  [ ! -e "$state" ] || earlier=$(jq -c --arg t "$tool" '.hooks[$t] // []' "$state")
  if [ ! -e "$target" ]; then
    if [ "$uninstall" = 1 ]; then : >"$result"; return 0; fi
    source=$work/new.json
    echo '{}' >"$source"
  fi
  jq --slurpfile t "$template" --argjson earlier "$earlier" '
    ($t[0].hooks | [.[][].hooks[]?.command]) as $current
    | ($earlier + $current) as $drop
    | def strip: map(.hooks = ((.hooks // []) | map(select((.command // "") as $c | any($drop[]; . == $c) | not))))
                 | map(select(.hooks | length > 0));
      .hooks = ((.hooks // {}) as $old
        | ($old | keys) + ($t[0].hooks | keys) | unique
        | map({key: ., value: ((($old[.] // []) | strip) + ($t[0].hooks[.] // []))})
        | map(select(.value | length > 0)) | from_entries)
    | '"$extra" "$source" >"$result" 2>"$work/merge.err" \
    || fail "${target#"$HOME/"} has hooks the installer cannot merge: $(head -1 "$work/merge.err"); fix them first"
  if [ -e "$target" ] && [ "$(jq -cS . "$target")" = "$(jq -cS . "$result")" ]; then : >"$result"; fi
}

claude_template=$here/settings/claude-hooks.json
codex_template=$here/settings/codex-hooks.json
if [ "$uninstall" = 1 ]; then claude_template=$empty_hooks; codex_template=$empty_hooks; fi

env_filter=.
current_mod=""
[ ! -e "$HOME/.claude/settings.json" ] || current_mod=$(jq -r '.env.CLAUDE_CODE_PLUGIN_DIRS // ""' "$HOME/.claude/settings.json")
if grep -q '^\.claude/mods/' "$list"; then
  case $current_mod in
    "") env_filter='.env = ((.env // {}) + {CLAUDE_CODE_PLUGIN_DIRS: "'"$mod_value"'"})' ;;
    *mods/console*) ;;
    *) echo "NOTE: env.CLAUDE_CODE_PLUGIN_DIRS is already '$current_mod'; add $mod_value to it by hand." >&2 ;;
  esac
elif [ "$current_mod" = "$mod_value" ]; then
  env_filter='del(.env.CLAUDE_CODE_PLUGIN_DIRS) | if .env == {} then del(.env) else . end'
elif [ "$current_mod" != "${current_mod%mods/console*}" ]; then
  echo "NOTE: env.CLAUDE_CODE_PLUGIN_DIRS is '$current_mod'; remove $mod_value from it by hand." >&2
fi

plan_settings claude "$HOME/.claude/settings.json" "$claude_template" "$env_filter"
plan_settings codex "$HOME/.codex/hooks.json" "$codex_template" .

if [ "$uninstall" = 0 ]; then
  commands='[.hooks[][].hooks[]?.command]'
  jq -n --arg version "$(cat "$here/VERSION")" \
    --argjson files "$(jq -R . "$list" | jq -s .)" \
    --argjson claude "$(jq -c "$commands" "$claude_template")" \
    --argjson codex "$(jq -c "$commands" "$codex_template")" \
    '{version: $version, files: $files, hooks: {claude: $claude, codex: $codex}}' >"$work/state.json"
fi

# ---- 2. files: each replaced or removed one goes to the backup first ----
backup=$HOME/.agent-config-backup/$(date +%Y%m%d-%H%M%S)-$$
backed=0
changed=0

run() { if [ "$dry" = 1 ]; then echo "would: $*"; else "$@"; fi; }

backup_path() {
  local rel=$1
  [ -e "$HOME/$rel" ] || return 0
  backed=1
  run mkdir -p "$backup/$(dirname "$rel")"
  run cp -p "$HOME/$rel" "$backup/$rel"
}

while IFS= read -r rel; do
  if [ -e "$HOME/$rel" ] && cmp -s "$files/$rel" "$HOME/$rel"; then continue; fi
  changed=1
  backup_path "$rel"
  run mkdir -p "$HOME/$(dirname "$rel")"
  run cp -fp "$files/$rel" "$HOME/$rel"
  echo "install $rel"
done <"$list"

if grep -q '^\.claude/mods/' "$old" && ! grep -q '^\.claude/mods/' "$list"; then
  # Claude Code lays these into the mod's folder; they are no file of ours.
  run rm -rf "$HOME/.claude/mods/console/.claude-plugin/types"
fi
while IFS= read -r rel; do
  [ -e "$HOME/$rel" ] || continue
  changed=1
  backup_path "$rel"
  echo "remove  $rel"
  run rm -f "$HOME/$rel"
  [ "$dry" = 0 ] || continue
  d=$(dirname "$rel")
  while [ "$d" != . ] && rmdir "$HOME/$d" 2>/dev/null; do d=$(dirname "$d"); done
done < <(LC_ALL=C comm -23 "$old" "$list")

# ---- 3. settings: the merges planned above ----
# Puts $1's content at $2 through a new file of the installer's own beside it, keeping $2's mode: a leftover or planted
# name there is never followed, and a crash leaves the old content.
replace_file() {
  local dir
  dir=$(dirname "$2")
  mkdir -p "$dir"
  pending=$(mktemp "$dir/.$(basename "$2").XXXXXX")
  [ ! -e "$2" ] || cp -p "$2" "$pending"
  cat "$1" >"$pending"
  mv -f "$pending" "$2"
  pending=
}

# $1: claude|codex  $2: settings file
apply_settings() {
  local result=$work/$1.json rel=${2#"$HOME/"}
  [ -s "$result" ] || return 0
  changed=1
  echo "merge   $rel"
  [ "$dry" = 0 ] || return 0
  backup_path "$rel"
  replace_file "$result" "$2"
}

apply_settings claude "$HOME/.claude/settings.json"
apply_settings codex "$HOME/.codex/hooks.json"

# ---- 4. state: what the next run removes ----
if [ "$dry" = 0 ]; then
  if [ "$uninstall" = 1 ]; then rm -f "$state"; else replace_file "$work/state.json" "$state"; fi
fi

# ---- 5. the person shared boards route to ----
if [ "$uninstall" = 0 ] && [ "$dry" = 0 ] && command -v git >/dev/null && [ -z "$(git config --global --get agents.person || true)" ]; then
  if [ -t 0 ]; then
    printf 'Your name for shared boards (git config --global agents.person; blank skips): '
    read -r who || who=
    [ -z "$who" ] || git config --global agents.person "$who"
  else
    echo "NOTE: for shared boards, set your name: git config --global agents.person <name>." >&2
  fi
fi

[ "$backed" = 0 ] || [ "$dry" = 1 ] || echo "backup  $backup"
if [ "$uninstall" = 1 ]; then
  echo "done. Your earlier instructions, if any, are in ~/.agent-config-backup/. Restart Claude Code and Codex."
elif [ "$changed" = 0 ]; then
  echo "already up to date ($(cat "$here/VERSION"))."
else
  echo "done ($(cat "$here/VERSION")). Restart Claude Code and Codex; Codex asks you to trust the changed hooks."
fi
