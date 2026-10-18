## Beads setup

Run once per repository with the user's confirmation:

```sh
bd init --stealth --prefix <project>
bd config set create.require-description true
bd config set validation.on-close error
bd config set no-git-ops false
bd config set status.custom "decided:wip,released:active,in_review:wip,needs_ratification:wip"
bd config set events-journal true
bd config set audit.enabled true
```

- Use stealth initialization: exclusions go to `.git/info/exclude`; plain init
  stages agent files and replaces `core.hooksPath`.
- Require descriptions and close reasons of 20+ characters. Leave Git authority
  with the user and repository through `no-git-ops false`.
- Inspect init's new `.git/info/exclude` lines; remove patterns hiding project
  files (1.3 adds `*.db`). Beads data lives under `.beads/`.
- Read board-wide changes with `bd events tail <seq>`; `audit.enabled` (a
  warned but honoured key in bd 1.3) feeds `.beads/interactions.jsonl` for
  activity views.
