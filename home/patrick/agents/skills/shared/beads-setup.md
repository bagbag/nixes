## Beads setup

Run once per repository with the user's confirmation:

```sh
bd init --stealth --prefix <project>
bd config set create.require-description true
bd config set validation.on-close error
bd config set no-git-ops false
```

- Use stealth initialization: exclusions go to `.git/info/exclude`; plain init
  stages agent files and replaces `core.hooksPath`.
- Require descriptions and close reasons of 20+ characters. Leave Git authority
  with the user and repository through `no-git-ops false`.
- Inspect init's new `.git/info/exclude` lines; remove patterns hiding project
  files (1.3 adds `*.db`). Beads data lives under `.beads/`.
- Run `bd prime` once; the session hook injects guidance from the next session.
