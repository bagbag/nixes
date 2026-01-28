# Implementation Plan: Refactor Modularity

## Phase 1: Analysis & Infrastructure
- [x] Task: Audit existing `modules/` to identify host-specific hardcoding.
- [x] Task: Audit `hosts/nixstation/` to identify logic that should be moved to modules.
- [x] Task: Ensure `agenix-rekey` and `ragenix` are properly set up in `flake.nix`.
- [x] Task: Conductor - User Manual Verification 'Analysis & Infrastructure' (Protocol in workflow.md)

## Phase 2: Core Module Refactoring (Library Creation)
- [x] Task: Refactor `modules/` to be strictly generic and self-contained (no host-specific imports).
- [x] Task: Expose `nixosModules` in `flake.nix` outputs to formalize the library interface.
- [x] Task: Refactor `modules/common.nix` and `modules/base.nix` into option-based modules.
- [x] Task: Refactor `modules/user.nix` to use `mkOption` for user management.
- [x] Task: Refactor `modules/services.nix` and individual service modules to be configurable via options.
- [x] Task: Conductor - User Manual Verification 'Core Module Refactoring' (Protocol in workflow.md)

## Phase 3: Host Isolation
- [x] Task: Update `hosts/nixstation/host.nix` to remove logic and only set options defined in the new modules.
- [x] Task: Ensure `hardware-configuration.nix` remains the only place for hardware-specifics (using standard NixOS hardware modules where possible).
- [ ] Task: Conductor - User Manual Verification 'Host Isolation' (Protocol in workflow.md)

## Phase 4: Verification & Polish
- [x] Task: Run `nixfmt` on the entire project.
- [x] Task: Validate the configuration with `nix flake check`.
- [x] Task: Attempt a dry-run build for `nixstation` to ensure no regressions.
- [x] Task: Conductor - User Manual Verification 'Verification & Polish' (Protocol in workflow.md)
