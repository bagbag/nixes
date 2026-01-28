# Technology Stack: Centralized NixOS Configuration

## Core Frameworks
- **Nix:** The functional programming language used for all system and package definitions.
- **NixOS:** The primary operating system, leveraging declarative configuration for reproducible builds.
- **Nix Flakes:** Enables hermetic builds and simplifies dependency management between system modules and external inputs.

## System Management
- **Home Manager:** Manages user-specific environments, dotfiles, and application settings in a declarative way.
- **Disko:** Declarative disk partitioning and formatting, ensuring consistent storage layouts across different hardware.

## Visuals & Identity
- **Stylix:** A universal theming engine for NixOS and Home Manager, providing a unified visual aesthetic (colors, fonts, wallpapers) across the entire fleet.

## Security & Secret Management
- **agenix-rekey:** Provides a robust workflow for re-keying secrets for multiple hosts.
- **ragenix:** A Rust-based implementation of `agenix` for fast and secure secret decryption during system activation.

## Hardware Support
- **NixOS Hardware:** Utilizing community or custom modules to optimize performance for specific components (e.g., AMD CPUs/GPUs).
