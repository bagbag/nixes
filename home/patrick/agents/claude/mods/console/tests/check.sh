#!/bin/sh
# The mod's one check: tests, types, manifest. Run ./board-setup.sh first.
# `claude plugin validate` is non-strict here: it fails on errors, not on the catalog-only README/LICENSE/icon findings.
set -e
cd "$(dirname "$0")/.."
claude plugin test .
./.claude-plugin/types/node_modules/.bin/tsc --noEmit -p .
claude plugin validate .
