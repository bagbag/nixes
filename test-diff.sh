#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 0 ]]; then
  echo "Usage: $0" >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${root}"

host="$(hostname -s)"
if [[ ! "${host}" =~ ^[[:alnum:]._-]+$ ]]; then
  echo "Refusing unexpected hostname: ${host}" >&2
  exit 2
fi

if [[ ! -e /run/current-system ]]; then
  echo "/run/current-system is unavailable; run this on the machine being compared." >&2
  exit 1
fi

if nix eval --no-write-lock-file --raw ".#nixosConfigurations.${host}.config.system.build.toplevel.drvPath" >/dev/null 2>&1; then
  configuration="nixosConfigurations"
elif nix eval --no-write-lock-file --raw ".#darwinConfigurations.${host}.config.system.build.toplevel.drvPath" >/dev/null 2>&1; then
  configuration="darwinConfigurations"
else
  echo "No NixOS or nix-darwin configuration named '${host}' exists in this flake." >&2
  exit 1
fi

candidate="$(nix build --no-link --print-out-paths ".#${configuration}.${host}.config.system.build.toplevel")"

echo "== NVD package diff: /run/current-system -> ${configuration}.${host} =="
nix run nixpkgs#nvd -- diff /run/current-system "${candidate}"

echo
echo "== Nix closure diff =="
nix store diff-closures /run/current-system "${candidate}"

live_commands="$(mktemp)"
candidate_commands="$(mktemp)"
trap 'rm -f "${live_commands}" "${candidate_commands}"' EXIT

collect_commands() {
  local target="$1"
  shift
  for directory in "$@"; do
    if [[ -d "${directory}" ]]; then
      for command in "${directory}"/*; do
        if [[ -x "${command}" && ! -d "${command}" ]]; then
          basename "${command}"
        fi
      done
    fi
  done | sort -u >"${target}"
}

user="$(id -un)"
candidate_home_path=""
if nix eval --no-write-lock-file --raw ".#${configuration}.${host}.config.home-manager.users.\"${user}\".home.path" >/dev/null 2>&1; then
  candidate_home_path="$(nix eval --no-write-lock-file --raw ".#${configuration}.${host}.config.home-manager.users.\"${user}\".home.path")"
fi

collect_commands "${live_commands}" \
  /run/current-system/sw/bin \
  "/etc/profiles/per-user/${user}/bin" \
  "${HOME}/.nix-profile/bin"
collect_commands "${candidate_commands}" \
  "${candidate}/sw/bin" \
  "${candidate_home_path}/bin"

echo
echo "== PATH command diff for ${user} (system plus Home Manager) =="
echo "Removed commands:"
comm -23 "${live_commands}" "${candidate_commands}" || true
echo "Added commands:"
comm -13 "${live_commands}" "${candidate_commands}" || true
