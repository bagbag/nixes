## Beads setup

With the user's confirmation, run `$HOME/.agents/bin/board setup` in the
repository; it is safe to rerun. Without a board it runs `bd init --stealth`
(embedded; `--server` for a board to share later; `--prefix` overrides the
origin repository's name), then the settings; an existing board keeps its mode
and prefix and gets missing and differing settings set. `bin/board` owns the
settings.

- Initialize a board only through `board setup` or `board join`: their stealth
  init keeps exclusions in `.git/info/exclude`, while plain `bd init` stages
  agent files and replaces `core.hooksPath`.
- Remove the exclude lines setup reports as matching tracked project files
  (1.3 adds `*.db`), unless new files like them should stay hidden.
- On a shared board, the settings in the database travel by sync; each person
  reruns `board setup` for the local ones in `.beads/config.yaml`.

## Shared boards

Run these on the user's request. Only `board share` and `board join` make a
board shared (they write `.beads/board-shared.json`); `board` then syncs it and
applies queues ([Routing](../shared/board-core.md#routing)). A Dolt remote alone
shares nothing; `board` runs bd with `BD_NO_REMOTE_ADOPT=1`, so bd never adopts
git origin itself.

- `board share [url]` says what goes out and changes nothing;
  `board share --yes` shares (default remote: the project's repository) and
  labels the unlabelled top-level items `queue:<sharer>`.
- `board join [url]` clones the board into a new `.beads/`; an existing board
  stays as it is unless it moved ([History](#history)).
- Both are safe to repeat and need the person: `git config [--global]
  agents.person <name>`, labels `queue:<name>`.
- `board` commits and syncs by itself about 60 seconds after a write, in a
  detached process (ending the session needs no sync), and pulls before
  commands; `board bd sync` syncs at once.

### When sync stops

A stopped sync prints one `board: sync …` line with its fix; work continues
unless beads refuses the write.

| Problem | Fix |
|---|---|
| Merge conflict | `board bd conflicts show`, `board bd conflicts resolve <id> --ours\|--theirs`, `board bd sync`. One side deleted the row: `--all --table issues`. `--all` alone fails when a dependency row conflicts. |
| Both sides created one id | `board bd sql "CALL DOLT_MERGE('--abort')"`, `board bd rename <id> <new id>`, `board bd sync`. |
| Repeated failures, stuck | `board bd sync` shows the error: remote access, network, or uncommitted changes (`board bd dolt commit`). |

Never create items with `--id` or dotted children on a shared board: `board`'s
plain ids prevent collisions, and parent.N ids stop sync.

### History

`board` warns at about 1 GB of local store. A flatten moves the board to a
fresh private repository with at least one commit, agreed with everyone:

1. Everyone: `board bd sync`, then stop writing.
2. One person, from a terminal or a lead or solo session: `board move <url>`.
3. Others: once `board` refuses writes, `board join <url>`; it keeps the old
   `.beads/` and names the `board bd import` for items written after the move.
   New joiners name the new url too.
4. Once everyone rejoined (a stale clone's sync hangs without the old data),
   delete the old board data:
   `git push <old url> --delete refs/dolt/data refs/heads/__dolt_remote_info__`.

Never run `bd dolt remote reset-data` (it deletes the remote's data and hung in
4 of 5 runs) or flatten in place (on GitHub it lost the board data).

### Versions

Upgrade bd and Dolt together, agreed between everyone; one person migrates and
pushes. At a person's terminal `board bd` keeps bd's prompts and doesn't
retry: rerun a write failing with `foreign key conflicts` by hand. On an
upgrade, recheck beads issues 4796 and 7839 and PR 7849, and rerun
`bin/test-shared-board.py`: its soak shows whether bd still raises the
`foreign key conflicts` error `board` retries (`WRITE_RETRY_ERROR`); retire the
retry when it no longer does.
