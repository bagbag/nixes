#!/run/current-system/sw/bin/bash
set -euo pipefail

# Ensure we are in the flake root
cd "$(dirname "$0")"

echo "Running agenix rekey..."
nix run .#agenix-rekey.x86_64-linux.rekey -- -a

echo "Rekeying complete."
