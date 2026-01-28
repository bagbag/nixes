# Track Specification: Add nixmobil Host & Hardware Refactoring

## Overview
This track involves adding a new host configuration for `nixmobil` (a portable Intel-based workstation) and introducing generic hardware modules for laptop and Intel-specific optimizations. Additionally, the project will be refactored to utilize the `nixos-hardware` flake for both `nixstation` and `nixmobil`.

## Functional Requirements
1.  **Flake Infrastructure:**
    *   Add `nixos-hardware` to `flake.nix` inputs.
2.  **Generic Hardware Modules:**
    *   `modules/hardware/intel.nix`: Encapsulate Intel microcode, iGPU acceleration (VA-API), and `intel_pstate` scaling.
    *   `modules/hardware/laptop.nix`: Encapsulate laptop-specific optimizations including `auto-cpufreq` and `thermald`.
3.  **Host Configuration (`nixmobil`):**
    *   Create `hosts/nixmobil/host.nix` following the modular pattern.
    *   Configure `nixmobil` as a `desktop` system type.
    *   Import relevant `nixos-hardware` modules (e.g., `common-cpu-intel`, `common-pc-laptop-ssd`).
4.  **Refactoring (`nixstation`):**
    *   Update `nixstation` to use `nixos-hardware` (e.g., `common-cpu-amd`, `common-cpu-amd-pstate`).
    *   Ensure visual consistency via existing `Stylix` configuration.

## Non-Functional Requirements
- **Consistency:** Adhere to the `Functional & Modular` guidelines and naming conventions defined in `product-guidelines.md`.
- **Type Safety:** Use `lib.mkOption` for new hardware module toggles.

## Acceptance Criteria
- `nix flake check` passes.
- `nixosConfigurations.nixmobil` evaluates successfully.
- `nixosConfigurations.nixstation` evaluates successfully with `nixos-hardware` integration.
- Code is formatted with `nixfmt`.

## Out of Scope
- Actual physical deployment or disk partitioning (Disko configuration for `nixmobil` should be provided as a template).
