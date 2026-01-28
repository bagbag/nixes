# Track Specification: Refactor Modularity

## Objective
Refactor the existing NixOS configuration to strictly separate reusable modules from host-specific implementations. The goal is to transform the repository from a single-host setup into a scalable fleet manager that can be used as a library.

## Context
Currently, the configuration is tailored to `nixstation`. With the requirement to support multiple devices and potentially export modules for external use, the codebase must be reorganized.

## Core Requirements
1.  **Strict Separation:**
    *   **Modules (`modules/`):** Must contain *generic* logic, service definitions, and `mkOption` declarations. They must NOT contain host-specific values (e.g., specific usernames, hardware paths, hardcoded IP addresses) unless they are sensible defaults overrideable by config.
    *   **Hosts (`hosts/`):** Must contain *only* configuration values (setting options defined in modules) and hardware-specific imports.

2.  **Type Safety:**
    *   All modules must define strict interfaces using `lib.mkOption` and `lib.types`.
    *   Validation should occur at evaluation time.

3.  **Secrets Management:**
    *   Integrate `agenix-rekey` structure to allow per-host secret encryption.

4.  **Standardization:**
    *   Apply `nixfmt` to all files.
    *   Ensure strict naming conventions (kebab-case for files, camelCase for options).

## Scope
- Refactoring existing files in `modules/`.
- Cleaning up `hosts/nixstation/`.
- Verifying the build of `nixstation` after refactoring.
