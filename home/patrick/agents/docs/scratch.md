# Scratch

Reference for `bin/scratch`; the README links here.

`bin/scratch` (installed as `$HOME/.agents/bin/scratch`) owns working files outside the
repositories: `${XDG_STATE_HOME:-~/.local/state}/agents/scratch/<repo>/` with `<repo>` the
resolved repository path (`--git-common-dir`, so worktrees share it) with `/` as `-`, a `.repo`
file naming that path and a `-2` suffix on a clash (r15-q71). Owners sit in the path:
`sessions/<actor>/`, `items/<board id>/`, `shared/<name>/` (r15-q84). Verbs (r15-q85/q86):
`dir [--for <id> | --shared <name>]` prints and creates a folder (outside a session `--for` or
`--shared` is required; `--for` needs a board and a known id); `trash` moves a path inside this
repository's folder to `.trash/<repo>/<name>/` (`-2`, `-3` on a clash; leading dots dropped from the name; the trash time is stored
in the entry; root and repo folders refused, links moved as links); `restore [<name> | <path>]` (lists
the trash without an argument; a path is where the entry was trashed from, `~`, absolute or relative, and the newest
entry of that path wins, which it says); `list [--all] [--json]` (`--all` flags gone
repositories for removal by hand, r15-q87); `status [--line]` (`--line`: what the trash holds, e.g.
`scratch: 3 trashed (1.0 GB), the first is deleted within 7 days (scratch restore)`, empty when nothing);
`sweep` (the expiry scan now, in the foreground, over every repository; prints one line per trashed entry: repo folder, path, size, idle days; r18-q97); `migrate` (the one-time move of the entries of every `.scratch` folder at any depth in the main tree and each worktree, except inside node_modules and .git, then the expiry scan at
once, listing what it trashed; board-migrate Scratch moves the decision records out before it and rewrites the old
paths on the board after it, with the scripts in `skills/board-migrate/scripts/`; r20-q99). Scratch cleans itself by age: the
background scan (hourly for the whole scratch root, marker `.cache/.scanned.json`, started by `dir` and `status`; it goes over every repository folder under that repository's lock folder, skipping a locked one, atomic per-repository cache; r18-q93)
trashes every ready entry in every repository, restorable from inside its own repository: a top-level entry of a session folder, or a whole shared folder,
unchanged for 14 days whoever owns it (change = the newest mtime or ctime of anything in it, so
`cp -a`, `tar x`, `rsync -a` and `restore` count as fresh; no session-registry read), and a top-level entry of an item folder unchanged for 14 days once its item is
closed or unknown to the board (r22-q102, revising r18-q95: an item's folder lives while the item is open). The board is read only for an idle item entry, once per item, in the repository
the folder belongs to; an unreachable board, a failing command or a gone repository keeps the entry, and a repository without `.beads` expires by time alone. Scratch also
removes an owner folder left empty and unchanged that long, by time alone (r15-q72, revised). Trash entries are deleted
after 7 days, counted from the time stored in the entry (its wrapper's mtime if that is unreadable). The
console shows the `status --line` text, nothing more (r15-q83). Codex's `writable_roots` grant `~/.local/state/agents` (scratch and sessions) and
`~/.local/share/agents/decisions`; Claude's `Edit` allow rules grant the scratch and records folders (the session tool writes sessions itself). Tests: `bin/test-scratch.py`.
