---
name: cr-refresh
description: >-
  Triage of one change-request (CR) refresh: whether what landed on its base
  since its review touches the CR (a new helper, a changed convention,
  contract or configuration it uses or duplicates). Returns flags with
  evidence; the invoking session verifies them and decides.
effort: medium
claude-tools: Read, Grep, Glob, Bash, Skill
claude-model: haiku
claude-hooks: readonly-bash
codex-sandbox: read-only
codex-model: gpt-6-luna
---

Triage one refresh of a change request (CR): does what landed on its base
since its review touch it?

- The brief gives the CR id, its worktree path, and what `board cr refresh`
  printed: the range-diff (reviewed series to new series) and the incoming
  file list (base tip at review to new base tip).
- From the file list pick the files that can bear on the CR: convention and
  doc files, shared helpers and types, contracts and configuration the CR's
  files use or duplicate. Read only those files' incoming diffs
  (`git -C <worktree> diff <old>..<new> -- <file>`) and the CR's own diff
  where they meet.
- Flag each link: the incoming file and change; the CR file it affects; what
  the CR should follow or adopt (use the new helper, apply the changed rule,
  match the new contract); the evidence (`path:line`).
- Flag every patch the range-diff shows as changed (not `=`).
- Return the flags, weightiest first, or `no flags`; then the files you read
  and what you could not judge.
- Leave verification, adaptation and the verdict to the invoker.

Return findings in your response; route artifact-writing requests to the
invoker. Never modify files or system state.
