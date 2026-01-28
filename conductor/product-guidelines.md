# Product Guidelines: Centralized NixOS Configuration

## Code Style & Architecture
- **Functional & Modular:** Configurations MUST be organized into small, focused modules. Use `imports`, `options`, and `config` blocks to maintain a clean separation of concerns.
- **Type Safety:** Custom modules SHOULD define clear schemas using `lib.mkOption` and appropriate `lib.types` to ensure configuration validity and provide helpful error messages.
- **Declarative Excellence:** Aim for pure, declarative Nix code. Avoid side effects and minimize the use of non-standard Nix features that reduce portability across the flake.
- **Formatting:** All Nix code MUST be formatted using `nixfmt` to ensure a consistent style throughout the repository.

## Documentation Standards
- **Self-Documenting Code:** Prioritize clear, semantic naming for variables and options. Use the `description` field in `mkOption` to provide context and usage instructions.
- **Strategic Comments:** Use inline comments to explain the "why" behind complex logic, specific hardware workarounds, or non-obvious configuration choices.

## Visual Identity
- **Unified Fleet Aesthetic:** Maintain a consistent visual identity across all managed devices using Stylix. Global settings for themes, fonts, and colors should be defined centrally and applied system-wide.

## Secret Management
- **Encryption First:** All sensitive data (API keys, passwords, private keys) MUST be managed using `agenix-rekey` with `ragenix`. Never commit unencrypted secrets to the repository.

## Project Integrity & Workflow
- **Module Completion:** A module is considered complete only when it is formatted, its secrets are secured, and it is correctly integrated/imported into the host or flake hierarchy.
- **Communication:** Commit messages and internal documentation should be technical, concise, and focused on providing clear context for changes.
