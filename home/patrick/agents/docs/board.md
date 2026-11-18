# Board, shared boards and sessions

Reference for `bin/board` and `bin/session`; the README links here.

`board setup` ([beads-setup](../skills/shared/beads-setup.md#beads-setup)) owns a board's settings:
`TRAVELLING_CONFIG` (database, travels by sync), `LOCAL_CONFIG` (`.beads/config.yaml`, per clone),
`SERVER_CONFIG` and `SHARED_CONFIG` in `bin/board`. It creates a server-mode board with `bd init
--server --stealth` (`--embedded` opts out: embedded mode takes one writer at a time) or brings an
existing one to these values, printing each old and new value; `--server` converts an embedded board
in place (`to_server`: bd backup and restore, the old folder kept). It reports `.git/info/exclude`
lines matching tracked files; share and join apply the same lists. `no-git-ops` stays `true`, as stealth init sets it: bd 1.3's stealth handling keys on it
(with `false`, `bd doctor --fix` writes a project `.gitignore`).

Shared boards ([beads-setup](../skills/shared/beads-setup.md#shared-boards); queues: [board-core Routing](../skills/shared/board-core.md#routing)): only board's own mark, `.beads/board-shared.json`,
makes a board shared, so a board without it costs no bd call and a stray Dolt remote shares nothing.
`board share` (two steps: it says what goes out, `--yes` sends) and `board join` write it after the
first push or the clone; a failed join removes what it made. Every bd call sets `BD_NO_REMOTE_ADOPT=1`.
`board route`, `board send` and `board create --for` move items between queues and inboxes (`for:`
labels; every send stamps `sent_at` metadata, and an inbox item's row and `waitingSince` count from
it); `board move` flattens to a fresh repository, leaving a moved note (`custom.board.moved`) on
the old board that `Shared.check_moved` reads after each pull, so stale clones refuse writes until
`board join` rejoins them. `Shared` in `bin/board` owns sync: `before` pulls,
`after` opens the window, a detached `board _sync-wait` commits and syncs, and `.beads/board-sync/`
holds its locks, stamps and reported problem. `board bd` runs bd as a child (never an exec), to retry `foreign key conflicts`,
start the wait and add its warning to bd's read-only refusal. `Board.listed` applies the queue
filter, `parent_move_refusal` refuses a reparenting by a session that may not move items (and a change request's or its held items'), and `create_item` makes plain child
ids on every board. `board console` adds `sync` (the problem line) and `queueLine` (other queues,
unrouted with the count for you, blocking yours), both shown in the pane.
The console pane shows the repository's scratch line (`scratch status --line`, read on every refresh; nothing when empty or when scratch fails) as one informational line (no button; trashed folders expire by themselves, in every repository); no model context gets the line (r15-q83 revised).
`AGENT_BOARD_SYNC_SECONDS` shortens the window for tests. `bin/test-shared-board.py` runs the
behaviour through real clones and a local bare remote; the validator's `validate_shared_board` holds
the fake-bd checks the build sandbox can run.

`bin/board` (installed as `$HOME/.agents/bin/board`, not on `PATH`) is the
agents' only board interface: views and hand-offs from one snapshot sized to
the command (`Board.load`: a `bd list` of the non-closed items plus one
`bd show` of the held items' comments for status views, `bd export` for
`related`, `check` and the writes that read closed items, a `bd show` of only
the named items for `board show`), and `board bd <args>` for every other bd
command (`bd edit`, which blocks on an editor, is refused with the way on named). `board bd` runs bd with `--readonly` and rewrites nothing:
bd's reads (`list`, `ready`, `search`, `history`, `export` …) pass and bd refuses a write; board then prints bd's error and the board command that
does it (`board create`, `field`, `update`, `comment`, `close`, `reopen`, `claim`, `block`/`unblock`, `link`/`unlink`, `defer`/`undefer`, `gate`) and the
raw rule. `--readonly` does not catch every write: on a server-mode board `import`, `rename`, `config set` and `dolt remote add`/`dolt set` pass
(probed on bd 1.3.2; no further guard, by decision). `board bd --raw --yes <args>` runs bd without it, for a write no board command does or one the
user authorized; `--raw` alone prints that rule, runs nothing and exits 2. `show`, `view` and comment listings are refused naming `board show` (one
read path for items, whole items with `--json`). It starts a stopped
server on server-mode boards (bd's auto-start is off) and takes the actor from
`session actor`, the owner of the session identity
(`CODEX_SESSION_ID`/`CODEX_THREAD_ID`, else `CLAUDE_CODE_SESSION_ID`). Hooks
add: bd-guard denies bare `bd` and sets Claude subagents' own actors (without
it they act as their session, so in-session reviews by them are not
independent); session-register keeps workers from registering; the
session-start hook starts the server before `bd prime`, and on Claude
refreshes the session's registered process and project (`session alive`);
session-activity records activity as file mtimes: SubagentStart and a
worker's tool calls create or touch the worker's marker, SubagentStop deletes
it, and the session's own tool calls touch `<session>.active`. Probed on
Codex 0.166 (2026-10-31): SubagentStart fires on first spawn, the matcher-less
PreToolUse group fires for shell and apply_patch calls, a worker's payload
`session_id` is its parent's, and its `agent_id` equals its
`CODEX_THREAD_ID`, which the worker actor's suffix comes from.
`session activate` and `alive` record `project`, the resolved (realpath) folder of the
session's board, found through `board bd where` (its first line names the `.beads`; a git
worktree names the main checkout's); a failed lookup records none and the command still
succeeds, and `alive` corrects it at every Claude session start. `board position` lists a
session when it holds items here, or when its project is this board's and the later of its
registration and last activity is within 24 hours (a session with no project and no holds is
not listed; a project without a board has no session list); the per-kind session counts, the
pane and `board console` read that one list.
`board position` marks holders GONE when their session's process ended (Claude; Codex records no process: the
nearest `codex` ancestor can be a shared app-server or a per-command sandbox helper) or its registration was
pruned. `session activate` prunes
registrations idle 7 days (last activity, else registration) whose process ended or that record none,
appending their actors to the state dir's `ended` file (`session ended` prints it); a hold of an
ended actor with no registration shows GONE, `held elsewhere` included (r3-q17). Registration writes and the
prune hold one `lockf` lock (`$state/.lock`, freed when its holder dies; the prune re-reads each registration
under it and skips when the lock is busy); `list` is a pure read, activity writes stay unlocked, and `list`
prints a registration it cannot parse as `{"unreadable": <file>}`. `board` derives idle from the
holder's last tool call (else the item's update) and shows
`workers <active>/<cap>`. `board mine` marks holds of the caller's workers
without a marker WORKER STOPPED once the session's `.active` exists (only the
owner knows whether it continues the worker). `claim`, `handover`, `return`,
`block`, `mine` and `queue` print a capacity line for dispatching sessions
below the worker cap with ready work. The cap is 3 unless
`session activate --workers <n>` sets the session's own, which a
later role switch keeps; a non-lead session row's select in the console pane
sets it with no model turn (`set-workers`); Codex's thread limits lower it.
The cap also limits holds (r13-q71): `board claim` refuses a task, bug, design or spike that would take
the claiming actor past it (counted per actor: in-progress work items only, not decisions or in-review
items) unless `--force "<reason>"`; a takeover of a work item held in progress (the session's own worker, or
`board take`) counts the same way and takes `--force` past the cap (r16-q93); position, mine, claim and check flag a forced hold `FORCED: <reason>`
(item metadata `forced_hold_by`/`forced_hold`, shown while that actor holds it). A held work item
with no update (fields, notes, comments) for an hour is `STALE` in position, mine, check and the
holder's claim output (r13-q76); nothing is refused. An unregistered session has no cap; one whose own registration file
exists but is unreadable is refused by `board claim` and `board take` until it registers again (r3-q16). Registration takes `--pulls` for every role;
lead, solo and agent are presets, and a session's pulls add to its preset for bare claims, handles
and capacity (r13-q61). `board create` and `board field apply` refuse a task, bug, design or
spike whose description, design, acceptance or notes is over 2000 characters (naming field and size; the refusal says how to cut, r3-q14); an update that shrinks an over-limit field
or only replaces paths in it (same tokens and whitespace, each changed token holding a `/`; the rewrite after a scratch move) passes, and decision records are not limited (r13-q74, r16-q96). Comments a session writes are held to
the same 2000 (`board comment <id>... (-m <text> | -f <file>)`, `-f -` for stdin; `board handover` evidence, `board return`
findings, `board block` reasons); the board's own packets are exempt: the protocol engine's autopilot
park adds its packet with `board comment … --board-packet` (r16-q87).
`board close <id>... --reason "<why>"` refuses a reason under bd's 20 characters before calling bd, and a change request
(`board cr land` or `reject` closes it).
`--force` closes past open blockers. The other writes `board bd` no longer carries have verbs: `board update <id>... [--title] [--priority] [--label L]...
[--unlabel L]... [--parent P|""]` (a `queue:` or `for:` label goes through `send`, `route` or `create --for`; `--parent` keeps a change request and its held
items where they are), `board link <a> <b> --type T` and `board unlink <a> <b>` (links that hold nothing up; a blocking one is `board block` /
`board unblock <ids> --on <blocker>`, whose `--reason` a work item needs and a decision or gate blocker or a milestone item does not),
`board reopen <id>...` (not a change request), `board defer <id>... --reason [--until]` / `board undefer`, and `board gate create|resolve`. Refused
calls of these verbs exit 2, as every verb that writes an item from its flags does (`REFUSAL_EXIT_2` in `bin/board` is the list). Plain
`board show` prints the item's newest 5 comments, each cut at 2000 characters with a pointer to
`board show <id> --comments`, which prints them whole (r16-q88, q89); it prints item metadata
`deep_review=<path>`, the failure path a review escalated, as `deep-review: <path>` (r16-q94, r7-q28).
`board field export <id>... [--field F]...` (fields description, design, acceptance (`acceptance_criteria`), notes; default all
four, empty ones too) writes `<scratch>/fields/<id>/<field>.md` and one hidden `.base.json` per item folder with each field's
hash, and prints the paths; edit the files in place, then `board field apply <id>... [--field F]...` makes one `bd update` per item
with its changed fields, under the same size limit, and removes the files. An item is refused whole (files kept, exit 2) when an edited field
changed on the board since its export or an edited file is empty; an unedited file is never written, moved on the board or not: it is only removed; items are independent.
Export never overwrites an export edited since and not applied (it names apply and discard); an untouched one is refreshed.
`board field discard <id>...` removes the exports. The flow replaces rewriting a field from memory. Reading stays `board show --field`; `board show <ids> --json` without `--field` prints whole items `{id: item}` with comments.
`board create [<title>] [--type T] [--parent ID] [--label L]... [--priority N] [--description-file F|-] [--design-file F] [--acceptance-file F]
[--deps type:ID]... [--holds ID|none]... [--metadata k=v]... [--status S] [--assignee A] [--for PERSON]` builds one node of a bd graph plan; `--graph <plan.json>`
takes a whole plan (no node flags beside it). Both pass the plan checks (types, a change request's look or view equal to the project default,
decisions naming what they hold up, queue labels, `--for`: top-level nodes, your queue, held for you, a shared board only, the size
limit of a work item's long fields) and go to `bd create --graph --json`; the ids print (`key id` per node for `--graph`). Node field names are
bd's graph JSON (`acceptance_criteria`, `parent_id`/`parent_key`, `deps: [{target, type}]`; bd ignores an unknown key silently): `--deps blocks:ID`
makes ID wait on the new item (as `bd create --deps`), a bare ID or `blocked-by:ID` makes it wait on ID. The links `create`, `link`, `ruling revise|supersede|record` write meet one set of rules (`block` writes its own wait, `update --parent` meets the same parent-move test, and bd writes `supersede` and gate links itself): an existing item made to wait on a new one gets `board block`'s effects, and only where block needs no
reason (a decision or gate as the new item, a milestone as the waiting one), else the create is refused (exit 2) naming `board block <id> --on <new> --reason`; `supersedes` and `tracks` links belong to
the ruling verbs; a plan edge needs a new item at one end; a node without a description is refused; `--parent` copies the parent's labels
except its queue (bd copies none for a graph node). `--limit 0` is every row of a view;
`related --docs`, `--holds`, `--deps`, `--label`, `--field`, `--section` and `health --items` repeat and take commas (`--closes` repeats, one `QUESTION=RECORD[,RECORD]` each, its comma separates records); options do not abbreviate; `--limit` and `--offset` are 0 or more. A refusal of `create`, `comment`, `close` and `field` exits 2, as `board bd` does. `board close --force` is bd's: it closes a blocked item or an epic with open children. `create` refuses `--status closed` (close it with a reason) and takes `-p P0..P4`; a plan with a key bd would drop silently, labels that are not a list of strings, or an edge that is not an object is refused. `board help <verb>` prints that verb's help and example.
`board wait [--timeout <s>]` blocks until a bare `board claim` would have a candidate for the session (its pulls, minus its own
hand-overs; one helper serves both), prints `claimable: <id> (<kind>) <title>` and exits 0 without claiming. It polls every 60 s,
exits 3 at the timeout and 1 when the session's registration is gone. Run it with the shell tool's background mode, not a
30-minute monitor; a candidate that `claim` then refuses (a git or worktree failure) is `claim`'s message to act on.
`board check` encodes the board-core
conventions mechanically; change both in the same change, so drifted boards
surface in `board health` and move through `/board-migrate`.
`board create` / `create --graph` node metadata are refused when the value equals the
project default (an unreadable default lets bd answer); `board setup` that changes `look` or `view` prints, under the
`old -> new` line, the open CRs keeping their own value, each with the first line of its description, design or notes naming the
setting (`no reason in its text` otherwise) and a note when it now equals the default (r10-q52).
`ITEM_TYPES` in `bin/board` is the one list of item types (board-core.md Kinds, a test compares them):
`board create` (flags or `--graph`) and `update --type` refuse any other type, `question` is refused naming
`--type decision` (never rewritten), and `board check` flags a live item of another type (class `unknown-type`).
Metadata `no_code=1`, set at creation (`create --metadata` or a graph node), marks work that changes no code
(r10-q50): it may be claimed outside a CR and `board check` drops its `no-cr` flag; `update --set-metadata no_code`
is refused. A CR whose branch has no commits of its own lands on its passed review in either look, with no
ratification and no Accept (a stacked one with its base); a design checkpoint is the exception.
Landing and design ratifications are child tasks titled after their change request. Their metadata
(`ratification=landing|design`) identifies the kind; see [Change requests](../skills/shared/change-requests.md#change-requests)
for the active-item deduplication rule.
`board review open <cr|ratification>` opens the item for the user's review in its own worktree (`<main>/.worktrees/<id>`), on its own branch
(r6-q24, r6-q25; accept.md User review) and prints the folder to open on stdout (the worktree's single root `*.code-workspace` file,
else the folder). It refuses (lead, solo or person only) a request not waiting for its Accept (`needs_acceptance`: in work, in agent review or
returned) or held by an agent session, a worktree mid a rebase, merge, cherry-pick, revert or bisect, with uncommitted changes, or off its
branch, and a remote named `board` that is not the board's (the board's own has the disabled push address; a stale url of it, after the checkout moved, is repaired). It moves nothing in git: no detach, no reset, no marker. It records the tip it
opens at in the item's metadata `opened_tip`, makes the remote `board` when missing (url the main checkout, `remote.board.pushurl`
`no-push://the-board-lands-requests`, which no `git-remote-no-push` helper serves, so any push fails; fetch `+refs/heads/*:refs/remotes/board/*`),
sets the branch's upstream to `board/<base branch>` (a stacked request's base is its parent's branch; with `branch.<name>.rebase=false` and `mergeOptions=--ff-only`, so a plain Pull, whatever the user's global `pull.rebase`, fast-forwards or fails and never rewrites reviewed commits) and fetches `board` (pruned; VS Code's
auto-fetch is off by default), so VS Code shows the request's commits as Outgoing Changes, the user's edits as Changes and a moved base as
Incoming. The board fetches `board` again whenever it moves a base (a landing, any rebase of a branch) and re-points the upstream of a
stacked request open for review to the target when its base lands; deleting a branch removes its `branch.<name>` config. Opening an item that
is already open changes nothing it holds (its `opened_tip` stays, so the user's commits and uncommitted edits stay theirs; a missing worktree
is made again from the branch; the uncommitted-changes refusal applies to the first open only). Open does not refresh: Accept brings in a moved
base. A ratification opens `.worktrees/<ratification id>` on a new branch `ratify/<id>` at its landed tip, with the same remote and upstream
(`board/<target>`). From Open until the user's Accept or Return (a ratification: its verdict) the item is held: `claim` for work, review or
refresh (the deciding session's accept claim takes it), `handover` and `cr refresh` (its holder's too) refuse it (`refuse_open`), and the queue
offers no review or refresh for it (`cr_claimable`; no refresh work). The user's edits are their commits after `opened_tip` plus the uncommitted
changes (tracked and new, not ignored files, staged or not, through a throwaway index: `review_edits_tree`); `review_read` reads them live. The
opened tip must still be an ancestor of the branch, and `opened..tip` must hold no merge commit and no commit of the base branch (a merging or fast-forwarding Pull brought them in; they are never the user's edits): otherwise `board cr land`, `board return`, `board cr edits`, `ratify` and `board show` (which prints the reason) refuse with the way back, `git -C <worktree> reset --hard <opened sha>` (it drops the user's commits after it, so they re-apply them), so a rewrite of reviewed work never passes as the user's edit. `board return` and `board cr land` end an unedited review
(`opened_tip` cleared) and refuse one holding edits, naming the `cr edits --commit` line, and `land` on a stale check names `cr edits … --commit`
before `cr refresh`, since a refresh refuses an open review.
`board cr edits <cr> --tip <sha> [--commit -m <msg> [--gate '<cmd>' | --no-gate '<reason>' | --checks]]` works on an item open for review
(r15-q75..q79, r6-q24, r6-q25); `<sha>` is the tip it was opened at (`opened`). Without `--commit` it prints the edits (the commits after it and the
uncommitted changes, against `<sha>`) and refuses another tip or an item not open. `--commit` records every commit after the opened tip in the CR's
`review_edits` metadata (each its own `{commit}`), commits the uncommitted changes as one more (exactly the files on disk, `commit-tree`; the hand-staged
ones too; `-m` needed only then): author the repository's `user.name`/`user.email`, committer the session, no trailer. The record comes first, the branch
then moves by compare-and-swap (`update-ref`, a branch that moved meanwhile commits nothing and unrecords), the worktree's index follows (`reset`), and
`opened_tip` is cleared before any check or rebase that can stop, so the refresh that follows is allowed. Every gate first rebases onto the base
(`checked_sync`). With no edits `--commit` only
ends the review (clears `opened_tip`; no message, no check): the Accept and Return of an unedited review. `--gate` runs the command in the CR worktree and stores it as a targeted check for
that tip (`check_kind=targeted`, `check_command`, output); `--no-gate` stores `check_kind=none` with the reason; `--checks`, the default, reuses `sync_branch` (rebase, setup, project checks, no new failures) and stores a normal full check.
`handover`, `cr refresh` and `ratify … edits` take the same option (`gate_options`, `checked_sync`; r11-q38). Both show as such (`board queue`: `check current (targeted: …)`, the console's `check.kind`) and
land only for that tip. A full check (`handover`, `refresh`) clears the kind. The review stays current past its tip while
every later commit is a recorded edit commit or its replay (`edits_only`, `is_replay`: replaying the recorded change onto the commit's
parent by 3-way merge gives exactly its tree, so a rebase keeps it, and a copied message, a reindent or the same change at another place
does not; `refresh --review-holds` skips such commits and requires every reviewed commit to be such a replay too, `replays`). A
failing gate leaves the commit, stores the failure and the CR waiting for the user. A CR with no stored review whose own commits (base
tip..tip) are all recorded edit commits is reviewed (`review_current`), so it lands on that Accept without an agent review.
A conflict on a recorded edit commit (a rebase of any such request, a follow-up's included) is no special path: the request stays an
ordinary CR mid its own board rebase, status as for any request waiting for the user (the follow-up is `needs_acceptance`, never
`in_review`; `cr_claimable` keeps a CR whose rebase stopped on a recorded edit commit out of the refresh queue, a stop on any other commit stays refresh work); the deciding session claims it,
merges with the user (resolve, `git add`, `board cr refresh`), and the user's confirmation is `board cr edits <cr> --merged <commit>`
(alone; lead, solo or person; the commit is on the branch past its fork point and carries the author and time of a recorded edit commit,
which a rebase and a conflict merge keep): it replaces the pre-rebase entry in `review_edits` with the merged commit, so the edit-only rule covers it
(checks run, the user's Accept lands it). Without it the merged commit counts as an agent change (`is_replay` fails for it). When a refresh or any rebase
the board continues goes past such a stopped edit commit (`resume_rebase`), it prints that exact `board cr edits <cr> --merged <commit>` step.
On a ratification `--commit` turns its worktree into a follow-up CR's (r1-q5, r6-q24): the follow-up is created (linked
`discovered-from` the ratification, `look` before, forked at the landed tip), its branch `cr/<id>` is made at the user's last commit (their commits after the
landed tip, plus their uncommitted changes as one more, all recorded in `review_edits`), the worktree moves to it, `ratify/<id>` is deleted (the
branch is renamed in separate compare-and-swap steps, each rerunnable) and the worktree moves to `.worktrees/<follow-up id>`, then the board rebases it onto the target and stores its check as
it would for `--checks` (or the `--gate` / `--no-gate` for the rebased tip) and sets it to `needs_acceptance`, waiting for the user's Accept; a
failing check keeps it there marked failed, a rebase that stops or a failed setup too (exit 1, see above). The follow-up is created held by the
ratifying session until it waits for the user (nobody claims it during setup and checks), and the worktree moves last: a failure before
it could be used closes a new follow-up again; a failure at a later step leaves it standing, and a rerun of the verdict reuses it and
redoes what is left from wherever the worktree stands, needing no review.
The board is the one reader of what a review holds (r1-q3): `board show <item>` of a CR (any status) or a ratification open for review prints
`open for your review: opened at <tip>; not edited` or `…; edited (<files>): not yet recorded as yours`; `board console` carries the same per request
and per ratification (several reviews open at once) as `review: {opened, edited, files} | null` on each `crs[]` and `ratifications[]` row (`opened`: the
tip it was opened at; `edited`: true / false, null when it could not be read: an amended opened tip, a missing worktree; `files`: the paths that differ
from `opened`), null while not open. There is no top-level `reviewTree`, and no `heldInReviewView` (an open item is the held one). The pane keeps no copy
of any of it: Accept and Return read `review` from the board JSON only and name the board commands (`board cr land <cr> --tip <the tip>`; `board cr edits <cr>
--tip <review.opened>` while `review.edited`); edits made after the board's last read are caught by the board's own refusal of `land` and `return`, which
names the line; `edited` null (unreadable) makes the pane refuse.
`board ratify <ratification> yes|edits|no [-m <msg>] [--gate '<cmd>' | --no-gate '<reason>' | --checks]` is the user's verdict on a
ratification item (r1-q6; a lead or solo session or a person only): `yes` closes it (without `-m` the reason is `Ratified change request
<id>: <title>`, long enough for bd's 20-character minimum) and removes its worktree and `ratify/<id>` branch (refused while they hold the
user's edits: commits after the landed tip or uncommitted changes); `edits` runs `cr edits --commit` on it (`-m` defaults to a stock message), which starts the follow-up that waits for
the Accept, and closes it; `no` needs `-m <reason>`, files the follow-up CR the user asked for (open, its description the reason),
closes the item with it and removes the worktree and branch when they hold no edits.
`board create --type decision` (also `--graph` plans holding a decision) and `board ruling revise` hold items up by their blocking links
however made (r3-q16): `--holds <id>[,<id>…]` (the shorthand), `--deps blocks:<id>`, a plan's edges or node deps that make an item wait on
a decision node. `board` reads them before creating: a decision with none needs `--holds none` (which stands alone, refused beside a link),
the held items must exist and be open, and after the create every link gets the effects of `board block <item> --on <question>` (the wait
commented, the creator's claimed item handed back); bd never sees `--holds`, and `--holds` ids with a plan are held by every decision of
it. `board ruling revise` takes `--holds` or `--deps blocks:<id>` (no graph). Rounds pass their questions' `holds` to the same step (Record).
A CR whose worktree is mid a rebase, merge, cherry-pick, revert or bisect the board did not start (marker files `rebase-merge`,
`rebase-apply`, `MERGE_HEAD`, `CHERRY_PICK_HEAD`, `REVERT_HEAD`, `BISECT_START` in the worktree's git dir, read by file existence; a rebase is the
board's when its `onto` equals the CR's `rebase_onto`) leaves the claim queue (`cr_claimable`), `board claim` refuses it, `board check`
lists it as `cr-git-state`, and `board console` gives the row a `git-state` problem.
Each `crs[]` row's `problems` lists what holds the request up with the step that clears it, `{kind, text, next: {action, command?, paths?}}`
(`cr_problems`): `setup-failed` (claim again), `git-state` (its owner ends it), `check` (any state but current) and `review-stale` while it waits for the
Accept, never for a design checkpoint, which lands nothing (`refresh` with the command on the refresh work only, `merge` when stopped on the user's
edit commit, else `wait`), `waits` (`wait`) for each unlanded parent and lifted wait of a request waiting for its Accept (`accept_waits`: the
console hides its Accept, the next claim passes it, a named claim still takes it to return or reject), `land-blocked` (`ask-user`, the paths). A hold is no problem: the row's `holder` says it, and the console marks it while
the request waits for the Accept. The console maps the problems to marks and the Update button; `board queue` and `board show` print the same
problems with their step. A rebase the board started and stopped on a conflict stays claimable: `sync_branch` (handover, `cr refresh`, `cr edits
--commit`) refuses while unmerged paths remain and otherwise runs `git rebase --continue` with `GIT_EDITOR=true` itself (r1-q2, q4).
Board-made commits and branch moves (`commit-tree`, `rebase --onto`/`--continue`, `merge --ff-only`) run no git hooks; what a hook
enforces belongs in `custom.board.checks` (r11-q39); board-migrate step 4 asks per project about a commit hook running the same checks (r11-q40).
`health`, `position` and `related` take `--json` (every row; `related`
keeps `--limit` per list) for the engine and the console; text output stays
unchanged. `board console` prints the console pane's JSON (health counts,
`mine` items, `position` sessions and holds with their marks) from one
snapshot.
`board ruling release <ids> --closes <question>=<record>[,<record>]` releases the
decided rulings (already released ones count as done, so a rerun retries only
a failed revise supersede), then closes the answered questions in dependency
order with "Answered by released <record>", forcing only past rulings of the
call, questions it closed before and released rulings; any other open blocker
leaves the question open (exit 1). A released blocker holds neither a decided
record nor an answered question, only the open items it changes.
`board position` and `board holders` print `holds a/b`: `a` counts a milestone as
one item and stops there, which tells a milestone's members apart; `b` counts
everything downstream. Lists sort by `a`, then `b`; JSON gives `holds` and `holdsAll`.
`session state-dir` names the state dir; the engine and the console
ask it instead of restating the location.
`session find <id>` resolves an id by file names alone (works for ended sessions): the board
actor is the last 8 characters of the session id, which Claude (`projects/<project>/<id>.jsonl`),
Codex (`sessions/Y/M/D/rollout-<time>-<id>.jsonl`) and the scratch folder (`sessions/<actor>`)
carry. Takes 6 or more characters; prints `claude|codex|scratch <path>` per match; exit 1 on a miss.

Every multi-verb tool answers `help` (each verb with one example) and prints
the same for a bare call, exit 0: `board`, `protocol`, `session` and `scratch` (r15-q88). `protocol help`
lists the verbs sessions run (`*`: the accepted `--origin` depends on the caller) before
`console only:`; `protocol help <verb>` (and `protocol <verb> -h`) prints that verb's arguments,
example and stdin forms, `help step` every report form by step. Both come from the frozen
`base.Verb` records (`base.VERBS`: audience, origins, summary, example, names of its stdin
forms; a record missing a part fails at import), which the parser's registration and
`require_origin` also read. The stdin forms are the dataclasses of `protocol_engine/schema.py`:
the one declaration of each form's field names, types and required/optional, read by the checks,
refusal text and help; prose (`words.py`) and rules across fields stay code. A step's report
refuses a key its step's forms do not name (`schema.unknown_keys`, in `cli.py` before the step
reads it; r7-q26): the refusal names the steps or verbs that take the key, so a pass report sent
to Record fails instead of passing as empty records. An unknown
`board` verb that the installed bd knows (`bd <verb> --help` exits 0) fails with exit 2 and
`board: no verb 'ready'; run: board bd ready <args>`; a verb that moved into a group
points to `board cr land` or `board ruling release`; nothing runs or forwards, and a word bd
does not know keeps argparse's error (r15-q90).

## Beads features the board avoids

The board deliberately avoids some beads features (bd 1.3.1); re-check
before adopting them:

- `external:` dependencies never block: no production code calls
  `ResolveExternalProjectPath`, so upstream waits use a local human gate.
- `bd human respond`/`dismiss` close on answer; questions close once their
  released ruling is planned.
- `bd close --suggest-next` lists only what one close unblocked; next steps
  follow priority and decision clusters.
- Claim leases, `bd heartbeat` and `bd reclaim`: nothing reads the 5-minute
  leases, and `bd reclaim` would free every held item. Holds end only as
  board core's [Actors and holds](../skills/shared/board-core.md#actors-and-holds)
  describes.

`bd lint` checks `decision` descriptions for the record sections (built-in
Rationale and Alternatives Considered; configured Question, Decision, Rule
owner); board core's
[Questions and rulings](../skills/shared/board-core.md#questions-and-rulings)
owns the record lifecycle. Closed records keep their shape (board-migrate
Invariants).
