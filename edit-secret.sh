#!/run/current-system/sw/bin/bash
set -euo pipefail

secret="$1"

ragenix --rules "./secrets/secrets.nix" --edit "./secrets/${secret}.age" --editor "micro -eofnewline off"
