# Nix Code Style Guide

## Principles
- **Declarative & Pure:** Avoid side effects. Let NixOS manage the state.
- **Modularity:** Break down configurations into small, reusable modules with `imports`.
- **Type Safety:** Use `lib.mkOption` with explicit `lib.types`.

## Formatting
- **nixfmt:** All code MUST be formatted with `nixfmt`.
- **Indentation:** Use 2 spaces for indentation.
- **Vertical Spacing:** Separate logical blocks with a single newline.

## Naming
- **Modules:** Use descriptive names for module files (e.g., `services/mongodb.nix`).
- **Options:** Use `camelCase` for custom option names.
- **Variables:** Use `kebab-case` or `camelCase` consistently within a module.

## Best Practices
- **Prefer `inherit`:** Use `inherit` to pass variables with the same name.
- **Avoid `with`:** Use explicit paths instead of `with` statements to avoid scope ambiguity, especially in large files.
- **mkDefault:** Use `lib.mkDefault` for default values in reusable modules to allow hosts to easily override them.
