#!/usr/bin/env bash
# Advances the nixpkgs-nodejs pin in flake.nix to the nixos-unstable tip when
# that ships a newer nodejs_26 whose whole closure is on cache.nixos.org.
# Edits flake.nix and flake.lock only; never touches git.
set -euo pipefail

check_only=0
if [[ $# -eq 1 && $1 == --check ]]; then
  check_only=1
elif [[ $# -ne 0 ]]; then
  echo "Usage: $0 [--check]" >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${root}"

package=nodejs_26           # overlay in modules/flake-parts/workarounds.nix
system=aarch64-darwin       # platform of every host using that overlay
cache=https://cache.nixos.org
pin_re='^([[:space:]]*nixpkgs-nodejs\.url = "github:NixOS/nixpkgs/)([0-9a-f]{40})(";)'

die() {
  echo "$*" >&2
  exit 1
}

# "<version> <output path>..." of the package at a nixpkgs rev
describe() {
  nix eval --raw "github:NixOS/nixpkgs/$1#legacyPackages.${system}.${package}" --apply \
    'p: p.version + " " + builtins.concatStringsSep " " (map (o: p.${o}.outPath) p.outputs)'
}

matches="$(grep -cE "${pin_re}" flake.nix || true)"
[[ ${matches} -eq 1 ]] || die "Expected exactly one nixpkgs-nodejs.url pin in flake.nix, found ${matches}."
current="$(sed -nE "s|${pin_re}.*|\2|p" flake.nix)"

# Resolve the tip once; evaluating a moving ref could differ from what gets written.
candidate="$(git ls-remote https://github.com/NixOS/nixpkgs refs/heads/nixos-unstable | cut -f1)"
[[ ${candidate} =~ ^[0-9a-f]{40}$ ]] || die "Could not resolve the nixos-unstable tip."

if [[ ${candidate} == "${current}" ]]; then
  echo "Up to date: pin is the nixos-unstable tip (${candidate:0:12})."
  exit 0
fi

old="$(describe "${current}")"
new="$(describe "${candidate}")"
old_version="${old%% *}"
new_version="${new%% *}"
[[ ${old_version} =~ ^[0-9A-Za-z.+_-]+$ && ${new_version} =~ ^[0-9A-Za-z.+_-]+$ ]] || die "Unexpected version strings: '${old_version}' '${new_version}'."

order="$(nix eval --raw --expr "toString (builtins.compareVersions \"${old_version}\" \"${new_version}\")")"
if [[ ${order} != -1 ]]; then
  echo "No newer ${package} at the nixos-unstable tip (pinned ${old_version}, tip ${new_version})."
  exit 0
fi

closure_size=0
for out in ${new#* }; do
  closure="$(nix path-info -r --store "${cache}" "${out}" 2>/dev/null)" ||
    die "${package} ${new_version} is not fully cached on ${cache}: ${out}"
  closure_size=$((closure_size + $(wc -l <<<"${closure}")))
done
echo "${package} ${old_version} -> ${new_version} (${candidate:0:12}): ${closure_size} closure paths cached on ${cache}."

if [[ ${check_only} -eq 1 ]]; then
  echo "Update available; rerun without --check to apply."
  exit 0
fi

backup="$(mktemp -d)"
cp flake.nix flake.lock "${backup}/"

apply() {
  sed -E "s|${pin_re}|\1${candidate}\3|" "${backup}/flake.nix" >flake.nix
  nix flake lock

  # Only the nixpkgs-nodejs node may change; anything else means the lock drifted.
  changed="$(
    OLD="${backup}/flake.lock" NEW="${root}/flake.lock" nix eval --impure --raw --expr '
      let
        read = v: (builtins.fromJSON (builtins.readFile (builtins.getEnv v))).nodes;
        a = read "OLD";
        b = read "NEW";
      in
      builtins.concatStringsSep " " (builtins.filter (n: (a.${n} or null) != (b.${n} or null)) (builtins.attrNames (a // b)))'
  )"
  [[ ${changed} == nixpkgs-nodejs ]] || {
    echo "flake.lock changed beyond nixpkgs-nodejs: ${changed}" >&2
    return 1
  }
  locked="$(
    NEW="${root}/flake.lock" nix eval --impure --raw --expr \
      '(builtins.fromJSON (builtins.readFile (builtins.getEnv "NEW"))).nodes.nixpkgs-nodejs.locked.rev'
  )"
  [[ ${locked} == "${candidate}" ]] || {
    echo "flake.lock pins ${locked}, expected ${candidate}." >&2
    return 1
  }
}

if ! apply; then
  cp "${backup}/flake.nix" "${backup}/flake.lock" .
  rm -rf "${backup}"
  die "Update failed; flake.nix and flake.lock restored."
fi
rm -rf "${backup}"

echo "Updated flake.nix and flake.lock. Nothing was staged or committed."
