#!/usr/bin/env bash
# Builds the agent setup tarball for someone without this nix config and copies it out of the store.
# Usage: ./build-agent-setup.sh [output-folder]   (default: your home folder)
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
output=${1:-$HOME}
[ -d "$output" ] || { echo "not a folder: $output" >&2; exit 1; }

# A flake build sees tracked files only, so an untracked one would be missing without any error.
untracked=$(git ls-files --others --exclude-standard -- home/patrick/agents home/patrick/agents-package.nix home/patrick/claude home/patrick/codex modules/flake-parts flake.nix)
if [ -n "$untracked" ]; then
  echo "stage these first, the build can't see them:" >&2
  echo "$untracked" >&2
  exit 1
fi

built=$(nix build .#agent-setup --no-link --print-out-paths)
tarball=$(ls "$built"/*.tar.gz)
target=$output/$(basename "$tarball")
cp -f "$tarball" "$target"
chmod u+w "$target"
echo "$target"
case $target in *-dirty.tar.gz) echo "note: built with uncommitted changes" >&2 ;; esac
