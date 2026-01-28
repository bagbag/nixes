# Implementation Plan: Add nixmobil Host

## Phase 1: Infrastructure & Hardware Modules
- [x] Task: Add `nixos-hardware` to `flake.nix` inputs.
- [x] Task: Create `modules/hardware/intel.nix` with options for Intel optimizations (Microcode, VA-API, P-State).
- [x] Task: Create `modules/hardware/laptop.nix` with options for power management (auto-cpufreq, thermald).
- [x] Task: Update `modules/default.nix` to export new hardware modules.
- [ ] Task: Conductor - User Manual Verification 'Infrastructure & Hardware Modules' (Protocol in workflow.md)

## Phase 2: Refactor Existing Host (nixstation)
- [x] Task: Update `hosts/nixstation/host.nix` to import `nixos-hardware` modules (AMD, P-State).
- [x] Task: Verify `nixstation` configuration integrity after hardware refactor.
- [ ] Task: Conductor - User Manual Verification 'Refactor Existing Host' (Protocol in workflow.md)

## Phase 3: Create nixmobil Host
- [x] Task: Create `hosts/nixmobil/` directory structure.
- [x] Task: Create generic/template `hosts/nixmobil/hardware-configuration.nix` and `disko.nix`.
- [x] Task: Create `hosts/nixmobil/host.nix` configuring the system as a desktop workstation with Intel and Laptop modules enabled.
- [x] Task: Add `nixmobil` to `nixosConfigurations` in `flake.nix`.
- [ ] Task: Conductor - User Manual Verification 'Create nixmobil Host' (Protocol in workflow.md)

## Phase 4: Final Verification
- [x] Task: Run `nixfmt` on all new files.
- [x] Task: Validate entire flake with `nix flake check`.
- [x] Task: Conductor - User Manual Verification 'Final Verification' (Protocol in workflow.md)
