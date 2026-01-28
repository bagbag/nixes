# Development Workflow: Centralized NixOS Configuration

## Core Principles
- **Manual Control:** The developer maintains full control over the Git lifecycle. Automated commits are disabled.
- **Reproducibility:** All changes must be valid Nix configurations that can be successfully built/evaluated.
- **Traceability:** Task summaries are recorded using Git Notes for clear documentation of progress.

## Quality Standards
- **Validation:** Every change must pass `nix flake check` or a dry-run activation before being considered complete.
- **Formatting:** Code must be formatted with `nixfmt`.
- **Secret Security:** Verify that all sensitive configuration is correctly encrypted via `ragenix`.

## Task Management
- **Manual Checkpointing:** The developer is responsible for committing changes at logical milestones.
- **Summary Recording:** Conductor will use Git Notes to attach task-specific metadata and summaries to the relevant commits.

## Phase Completion
- Upon completing a phase (a collection of tasks), the developer should perform a full system validation or deployment to ensure all components integrate correctly.