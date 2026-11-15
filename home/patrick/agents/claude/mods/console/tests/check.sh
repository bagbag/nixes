#!/bin/sh
# The mod's one check: tests, types, manifest. Run from anywhere; it works in the mod folder.
# `claude plugin validate` is non-strict here: it fails on errors, not on the catalog-only README/LICENSE/icon findings.
set -e
cd "$(dirname "$0")/.."
claude plugin test .
pnpx --package typescript tsc --noEmit -p .
claude plugin validate .
