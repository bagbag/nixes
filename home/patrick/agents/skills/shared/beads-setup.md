## Beads setup

Run once per repository, with the user's confirmation:

```sh
bd init --stealth --prefix <project>   # ignores via .git/info/exclude; plain init stages agent files and replaces core.hooksPath
bd config set create.require-description true
bd config set validation.on-close error   # close reasons of 20+ characters
bd config set no-git-ops false   # prime defers git to user and repo authority instead of forbidding it
```

Then review the lines init added to `.git/info/exclude` and remove those that
would hide project files (1.3 adds `*.db`); beads keeps its data under
`.beads/`. Run `bd prime` once; the session hook injects it from the next
session on.
