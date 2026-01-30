# Implementation Plan: Track macbook_20260130

## Phase 1: Infrastructure and Structural Refactoring
The goal of this phase is to prepare the repository for multi-platform support (NixOS and macOS) and integrate `nix-darwin`.

- [x] Task: Integrate `nix-darwin` into `flake.nix`
    - [x] Add `nix-darwin` to flake inputs.
    - [x] Add `aarch64-darwin` to the `systems` list in `flake-parts`.
- [x] Task: Restructure modules for platform independence
    - [x] Identify and move platform-agnostic logic (e.g., shell aliases, git config) to a shared module layer.
    - [x] Ensure `nixosModules` remains specific to NixOS.
- [x] Task: Initialize `macbook` host configuration
    - [x] Create `hosts/macbook/host.nix` for darwin-specific settings.
    - [x] Define `darwinConfigurations.macbook` in `flake.nix`.
- [x] Task: Conductor - User Manual Verification 'Phase 1' (Protocol in workflow.md)

## Phase 2: macOS System Configuration and Services
This phase focuses on configuring macOS-specific features and system services.

- [x] Task: Configure macOS System Defaults
    - [x] Implement Dock and Finder preferences in `hosts/macbook/host.nix`.
    - [x] Enable TouchID for `sudo` authentication.
- [x] Task: Set up Syncthing Service
    - [x] Enable Syncthing and configure it as a launchd service using `nix-darwin`.
- [x] Task: Initialize Font Management
    - [x] Implement declarative font installation for macOS.
- [x] Task: Conductor - User Manual Verification 'Phase 2' (Protocol in workflow.md)

## Phase 3: Application Management and Home Manager
This phase handles the installation of requested apps and ensures user environment consistency.

- [x] Task: Integrate Homebrew and App Store (`mas`)
    - [x] Enable `homebrew` management in `nix-darwin`.
    - [x] Configure `homebrew.casks` for Firefox and Spotify.
    - [x] Set up `homebrew.masApps` for App Store integration.
- [x] Task: Connect Home Manager to `nix-darwin`
    - [x] Import `home-manager` darwin module.
    - [x] Configure `home-manager.users` for the MacBook user, reusing `modules/home/home.nix`.
- [x] Task: Verify User Environment Consistency
    - [x] Ensure Zsh and common tools are correctly symlinked and configured on macOS.
- [x] Task: Conductor - User Manual Verification 'Phase 3' (Protocol in workflow.md)

## Phase 4: Final Validation and Cleanup
- [x] Task: Run `darwin-rebuild check` and `nix flake check`.
- [x] Task: Verify all acceptance criteria from `spec.md`.
- [x] Task: Conductor - User Manual Verification 'Phase 4' (Protocol in workflow.md)
