---
name: release-round
description: >-
  Approve releasing the last round's decided records, or the named ones, if
  every check holds.
argument-hint: "[record ids] [focus and follow-ups]"
disable-model-invocation: true
---

# Release round

Release is approved when all your own rulings are sure (the only realistic
clean option), every other record passes the Re-check, and no record leaves the
set or changes; otherwise the release asks me.

Run the release through `protocol` under Release in
`$HOME/.agents/skills/role/protocols/decide.md`, giving the outputs of its
Re-check, Board check and Own rulings steps. The console has already started
it (on the argument's ids, else every decided record this session holds that
no release dropped) or stamped the open one; without an open release, start it
(`protocol start release [<ids>]`).
