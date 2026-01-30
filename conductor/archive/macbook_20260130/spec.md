# Specification: Track macbook_20260130

## Overview
Introduce a new host "macbook" to the centralized configuration flake. This host is an M4 (2025) MacBook running macOS, which will be managed declaratively using `nix-darwin`. The goal is to achieve high consistency with existing NixOS hosts while leveraging macOS-specific features.

## Functional Requirements
- **Architecture Support:** Add support for `aarch64-darwin` to the flake.
- **nix-darwin Integration:** Incorporate `nix-darwin` as a flake input and create a `darwinConfigurations` output for the "macbook" host.
- **Application Management:**
    - Install and configure Firefox and Spotify.
    - Install and configure Syncthing, managed as a `launchd` service.
    - Integrate Homebrew for GUI applications and `mas` for Mac App Store apps.
- **System Configuration:**
    - Configure macOS system defaults (Dock, Finder, etc.).
    - Enable TouchID for `sudo` authentication.
    - Declarative font management consistent with the fleet.
- **User Environment:**
    - Integrate `home-manager` with `nix-darwin` to manage user dotfiles and settings.
    - Ensure a consistent shell environment (Zsh, coreutils) with existing hosts.

## Non-Functional Requirements
- **Modularity:** Refactor the existing module structure to distinguish between shared (Nix/Home Manager) and platform-specific (NixOS vs. Darwin) configurations.
- **Consistency:** Maintain a unified visual aesthetic using Stylix (if supported on Darwin) or equivalent declarative theming.
- **Performance:** Ensure that `nix-darwin` and `home-manager` operations do not negatively impact macOS system performance.

## Acceptance Criteria
- [ ] The `nix-darwin` configuration for "macbook" builds successfully (`darwin-rebuild build`).
- [ ] Firefox, Spotify, and Syncthing are installed and functional.
- [ ] Syncthing starts automatically as a macOS service.
- [ ] Homebrew and App Store integrations are correctly initialized.
- [ ] TouchID can be used for `sudo` in the terminal.
- [ ] User settings (Zsh, dotfiles) are consistent with NixOS hosts.

## Out of Scope
- Native NixOS installation on M4 (Asahi Linux).
- Complex macOS-specific software licensing management.
- Integration with Apple MDM (Mobile Device Management).
