# nix-darwin: agent instructions

## Testing

- Passes before hand-over run only the targeted tests covering what they touch:
  `nix develop .#agent-tests --command python3 -B -m pytest -n auto -m <group> home/patrick/agents/bin/test-agent-configs.py`
  (or `-k <test>`; the groups are the markers in `home/patrick/agents/pytest.ini`) and
  `python3 -B home/patrick/agents/bin/test-shared-board.py --only <name>,<name>`.
- The shared-board suite's `--shared` groups (sharing, sync) and `--migrate` groups (board-migrate) run on request,
  not in the full check: when a change touches what they cover (see the suite's docstring).
- The full check (`./board-checks.sh`) runs once per change request, on its final tree before Accept.
- Work released mid-change (`agents board unclaim --resume`) runs no full check.
- Rerun mutants or probes only when a review asks for them.
