---
name: release-round
description: >-
  Approve releasing the last round's decided records, or the named ones, if
  every check holds.
argument-hint: "[record ids] [focus and follow-ups]"
disable-model-invocation: true
---

# Release round

<!-- @include shared/rerun.md -->

Release is approved when all your own rulings are sure (the only realistic
clean option), everything else is clean too, and no record leaves the set or
changes; otherwise the release asks me.

Run the release through `protocol` under Release in
`$HOME/.agents/skills/role/protocols/decide.md`, giving the outputs of its
Re-check, Board check and Own rulings steps. The console has already started
it (on the argument's ids, else the last closed round's records) or stamped
the open one; without an open release, start it
(`protocol start release [<ids>]`). A round still open finishes first.
