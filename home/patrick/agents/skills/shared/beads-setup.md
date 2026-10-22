## Beads setup

Run once per repository with the user's confirmation:

```sh
$HOME/.agents/bin/board bd init --stealth --prefix <project>
$HOME/.agents/bin/board bd config set create.require-description true
$HOME/.agents/bin/board bd config set validation.on-close error
$HOME/.agents/bin/board bd config set no-git-ops false
$HOME/.agents/bin/board bd config set status.custom "decided:wip,released:active,in_review:wip,needs_ratification:wip"
$HOME/.agents/bin/board bd config set types.custom "design"
$HOME/.agents/bin/board bd config set lint.sections.decision "Question,Decision,Rule owner"
$HOME/.agents/bin/board bd config set events-journal true
$HOME/.agents/bin/board bd config set events-journal-retain-days 30
```

- Use stealth initialization: exclusions go to `.git/info/exclude`; plain init
  stages agent files and replaces `core.hooksPath`.
- Require descriptions and close reasons of 20+ characters. Leave Git authority
  with the user and repository through `no-git-ops false`.
- Inspect init's new `.git/info/exclude` lines; remove patterns hiding project
  files (1.3 adds `*.db`). Beads data lives under `.beads/`.
- Server mode (`init --server`): `config set dolt.auto-start false`; `board`
  starts a stopped server.
