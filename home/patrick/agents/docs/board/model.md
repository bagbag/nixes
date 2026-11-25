# Board model

What `bin/board` and `bin/session` do and why; the README links here. The code is the source of truth: the tables below are printed from it (`model_tables` in `bin/board`) and `bin/test-agent-configs.py` (contract group) keeps this file's copy equal. [Write rules](#write-rules) is the exception: that table is the contract the code and its tests follow (nixes-jczod). Prose says only what the code cannot show. Skills under `skills/` keep procedure and judgment and name these rules; they are not installed beside this file, so a rule a session must follow without it is in the verb's refusal or help.

Absorbs the risk-tiered workflow (release r2). Parts not yet built are marked **planned** with their change request.

## Principles

- One lifecycle level: the change request (CR) owns work and review; items are structured parts without their own lifecycle.
- One meaning per status; every lifecycle ends in `closed` with an outcome, stored as the record's `outcome` metadata (a record closed before the migration may carry none: history is not rewritten).
- Bookkeeping vs content: what code (a rule, verb, queue, script) reads, or a next step must act on exactly, is a field or record. Prose is for a reader's judgment. Nothing reads a fact out of prose to decide state or routing; nothing actionable lives only in prose.
- Code is declarative: one table per type and one transition function (`move`) writing status and holder through bd compare-and-set. Writers, queue, check and help read the tables: `agents board help` prints the statuses and outcomes by type and each verb's `--help` prints its rows (`states_table`, `verb_rules`), which is how sessions see the model; this document is the maintainers' design. No state-machine library: `bin/board` and the setup bundle stay stdlib-only.
- Guards are enforced at the write, not restated: a rule the board can check at one command lives in that command (refusal, next step, help). `check` reports only shapes that came from outside the verbs (direct bd edits, a clone's sync).
- Every write verb refuses a board without the model marker `custom.board.model` (the model version, `MODEL` in `bin/board`) and names `/board-migrate`. Reads and raw bd stay open so migration can inspect and convert. Two writes are exempt, named in `MODEL_EXEMPT` beside `require_model` with their reasons: `setup` (it creates the board or brings its settings to the current model, so the marker cannot be its precondition) and `join` (it fetches a board whose marker travels with the database). `setup` writes the marker on a board it creates; an existing board gets it last from board-migrate (`convert-stored-forms.py --mark`), never from a setup rerun. A CR that changes stored forms raises `MODEL` and adds its conversions to the converter, which reads `MODEL` from `bin/board` and refuses a board whose marker is higher. `READS` holds the verbs that write no record of their own (a read verb in `CR_AWARE` still runs `settle_landed` at its start: `command start` in the verb table); `share` and `relocate` (`SYNCS_ITSELF`: they sync themselves, so no window opens after them) and every other write refuse like any write.

## Types

| Type | What it is |
|---|---|
| change request | Commit work: one branch, one reviewed range, one Accept. |
| item | A structured part of exactly one CR (a bd `task` inside a CR). Kind (bug, feature, design, cleanup) is a `kind:` label: no rule reads it. |
| task | Standalone work that commits nothing (research, a spike, an outside step): a bd `task` outside any CR (`--no-commit`). `create` and a graph node refuse a work task without a change-request parent (a milestone or task parent is refused) unless `--no-commit`, and `create` refuses `--parent` with `--no-commit`; `move <task> --to <CR>` clears the mark (the only route from no-commit to commit work). |
| decision | A question, then a ruling; also an agent's two-way choice. |
| gate | A step only a person takes (`await_type` human; label `for:<person>` on a shared board). Gates are human only: no timer or event gate. |
| milestone | A goal the user accepts; CRs are parts of it (`agents board move <cr> --to <milestone>`). It waits on nothing. |

No epic (topic labels and milestones group), no standalone review type or status, no work assigned to the user. Filing places an item in a CR. A plan graph (`create --graph`) files a planned set; `create` takes no status or holder. The verbs `file`, `add`, `task` and `ask` replace single-item `create`: **planned** (nixes-5smx7).

## Lifecycles

The first table below gives each type's statuses and the outcomes its closing rows record. In prose:

- **Change request:** `open` → `in_review` → `passed` → `closed` (landed or dropped). `passed` is review passed, landing pending: with `look` `before` it waits for the user's Accept; with `look` `after` it lands at once, or when its base lands if it stacks on an unlanded base (derived, not stored). Return (a reviewer, or the user at Accept) turns each finding into an open item of the CR and sets it back to `open`. A non-blocking finding is filed as its own work or dropped. A planner returns an in-review CR when a new ruling changes it (`return --ruling`): the ruling's consequences become items.
- **Item:** `open` → `closed` (done or dropped). The worker closes each item it did; dropped when a ruling makes it moot. An item has no holder and no review: its CR's holder decides who writes it.
- **Task:** `open` → `closed` (done or dropped), holdable.
- **Decision:** `open` (a question; it can wait and be waited on) → `decided` (answered or ruled and recorded, not yet binding: a wait on it stays unmet until release) → `in_force` (a ruling) → `closed`. Outcomes: `dropped` (never ruled), `planned` (carried into work: planning closes the ruling, citing the CRs or tasks it made), `superseded` (a later ruling replaces it, or another ruling answered the question). `rejected` (an agent's choice the user rejected) arrives with `ratify` (**planned**, nixes-cop95); no row writes it yet.
- **Gate:** `open` → `closed` (resolved). **Milestone:** `open` → `closed` (accepted), by a lead or solo session with the user (the table: `attended`).
- **Reopen** needs the authority of close: the item rows, milestone, gate and decision rows say so. A task's reopen row reads `holder / user / deciding+gone`, close's own (see the table).

A **choice record** (**planned**, nixes-cop95) is an agent's two-way choice: the option taken, the one not taken, why, how to reverse it and the CR it shaped. It is in force at once with `ratified` unset; `ratify <ids…> yes|no` sets it, or closes it as rejected and files the recorded reversal as a CR. Today `agents board ruling record --unratified` writes such a record with a `## Reversal` and a `Confirm or revise` question linked by `relates-to`.

The protocol engine owns a round (questions asked, quotes, staged text); the board owns the record's stage, so an answer survives a session that never resumes and no other session asks it again.

### Change request fields

`look` (`before` | `after`; the project default, overridable per CR), `view` (`code` | `result`: how the console shows a landing), `base` and `base_sha`, `plan_first` (a reason: the CR needs planning before anyone implements it; set by base rejection and by board-migrate for migrated loose work, cleared by the plan claim, and an open CR carrying it is `plan` work), `hold` (below), the stored `check` and `review` evidence, and `deep_review` (the path a review escalated to a deep review: set by `unclaim --deep-review <path>` under the hold, cleared only by the reviewer's pass; `unclaim`, `return` and the author's handover keep it; nixes-df7kf, nixes-fy01y). A look-after default for new boards is **planned** (nixes-8b15o); this project stays `before`.

- **Stacking:** a CR may stack on any `passed` CR (its base is that CR's branch; `stackable` in `bin/board`: not one in agent review). A passed look-after CR waiting for its own base is a base too: landing the first base lands each look-after CR stacked on it in turn, and a look-before one stays for its Accept with its base reset to the target; a CR on an unlanded, unstackable base is not ready. "Its base allows it" means the base has landed, or is stackable and this CR stacks on it. When the base lands the stacked CR's base becomes the target.
- **Refresh:** when the base moves a CR's stored check is stale; a `passed` look-after CR with a stale check does not land with its base but becomes refresh work (rebase, check again) for its holder or the queue.
- **Handover:** the board runs the configured check and stores it; the range, the check and the item outcomes are the evidence; an optional prose note carries judgment evidence. Handover refuses while any item is open, naming them and `close <ids>`; it never closes items itself. A waiting item: unclaim with `--resume` (the CR is ready again when the wait is met) or the planner moves it into its own CR.
- A CR whose branch has no commits of its own lands on its passed review in either look, with no Accept (a stacked one with its base).
- Design text lands with its implementation in the same CR; direction choices (scope, one-way doors) are questions asked before the work. A separate design CR is the exception and names its reason ([ordinary-design-requests.md](ordinary-design-requests.md)).

## Tables

Printed by `model_tables()`; the test compares this block with it exactly. `Held before` is the holder the write expects (`-` none, `you` the caller's session, `*` any), `Held after` the holder it leaves (`=` unchanged; `-` on a close row too: the closed record keeps its closer as assignee, history that no rule reads as a hold); `+` joins parts that must all hold, `/` separates alternatives. Which pull a bare claim serves stays with `claim`; the worker cap, claim readiness, the check pair and the review are [Write rules](#write-rules) cells.

<!-- model-tables -->
| Type | Statuses | Outcomes when closed |
|---|---|---|
| change request | open, in_review, passed, deferred, closed | landed, dropped |
| task | open, deferred, closed | done, dropped |
| item | open, closed | done, dropped |
| decision | open, decided, in_force, deferred, closed | superseded, dropped, planned |
| milestone | open, closed | accepted |
| gate | open, closed | resolved |

| Command | Type | From | To | Held before | Held after | Who | Guards | Outcomes |
|---|---|---|---|---|---|---|---|---|
| claim | change request | open | = | - | you | agent | - | - |
| claim | change request | in_review | = | - | you | agent+non-author | - | - |
| claim | change request | passed | = | - | you | agent | - | - |
| claim for work | change request | open | = | you | you | agent | - | - |
| take | change request | open, in_review, passed | = | * | you | agent+holder+non-author / agent+deciding+gone+non-author | - | - |
| unclaim | change request | open, in_review, passed | = | * | - | holder / user / deciding+gone | - | - |
| handover | change request | open | in_review | you | - | agent | in-work, items-closed, not-open-for-review | - |
| handover --no-agent-review | change request | open | passed | you | - | agent | in-work, items-closed, look-before, not-open-for-review | - |
| handover (reviewer passes) | change request | in_review | passed | you | - | agent | items-closed | - |
| send to review | change request | passed | in_review | * | - | holding / deciding / user | unheld-or-yours | - |
| return | change request | in_review | open | * | - | agent+holder | held-by-you | - |
| return | change request | passed | open | * | - | deciding / user | unheld-or-yours | - |
| return --ruling | change request | in_review | open | you | - | planner | - | - |
| landing | change request | open, in_review, passed | closed | * | - | anyone | - | landed |
| cr reject | change request | open, in_review, passed, deferred | closed | * | - | attended / user | reason, items-closed, no-waiters | dropped |
| base rejected | change request | open, in_review, passed | open | * | - | anyone | - | - |
| defer | change request | open | deferred | * | - | planner+holder / deciding / user | no-hung-waiters | - |
| undefer | change request | deferred | open | - | - | deferrer | no-deferred-target | - |
| claim | task | open | = | - | you | agent | - | - |
| take | task | open | = | * | you | agent+holder / agent+deciding+gone | - | - |
| unclaim | task | open | = | * | - | holder / user / deciding+gone | - | - |
| close | task | open | closed | * | - | holder / user / deciding+gone | reason, no-waiters | done, dropped |
| reopen | task | closed | open | * | - | holder / user / deciding+gone | no-dropped-target | - |
| close | item | open | closed | * | - | holding / user / deciding+unheld / deciding+gone / planner+unheld | reason, no-waiters | done, dropped |
| reopen | item | closed | open | * | - | holding / user / deciding+unheld / deciding+gone / planner+unheld | open-parent, no-dropped-target | - |
| defer | task | open | deferred | * | - | planner+holder / deciding / user | no-hung-waiters | - |
| undefer | task | deferred | open | - | - | deferrer | no-deferred-target | - |
| defer | decision | open | deferred | * | - | planner+holder / deciding / user | no-hung-waiters | - |
| undefer | decision | deferred | open | - | - | deferrer | no-deferred-target | - |
| claim | decision | open, decided | = | - | you | agent | - | - |
| claim | decision | in_force | = | - | you | planner | - | - |
| take | decision | open, decided, in_force | = | * | you | agent+holder / agent+deciding+gone | - | - |
| unclaim | decision | open, decided, in_force | = | * | - | holder / user / deciding+gone | - | - |
| ruling record | decision | open, decided | decided | you | = | holder | - | - |
| ruling record --unratified | decision | open, decided, in_force | in_force | you | = | holder | settled-premises | - |
| ruling release | decision | decided | in_force | * | - | attended / user | settled-premises | - |
| supersede | decision | open, decided, in_force, closed | closed | * | - | deciding / user | - | superseded |
| close | decision | open, decided | closed | * | - | deciding+holder / deciding+gone / user | reason | dropped, superseded |
| close | decision | in_force | closed | * | - | planner+holding / deciding+holder / deciding+gone / user | reason | planned |
| claim | milestone | open | = | - | you | attended | - | - |
| take | milestone | open | = | * | you | attended+holder / attended+gone | - | - |
| unclaim | milestone | open | = | * | - | holder / user / deciding+gone | - | - |
| close | milestone | open | closed | * | - | attended+holder / attended+gone / user | reason | accepted |
| reopen | milestone | closed | open | * | - | attended+holder / attended+gone / user | - | - |
| reopen | decision | closed | open | * | - | deciding+holder / deciding+gone / user | not-superseded, no-dropped-target | - |
| close | gate | open | closed | * | - | attended / user | reason | resolved |
| reopen | gate | closed | open | * | - | attended / user | - | - |

| Who word | Means |
|---|---|
| anyone | anyone |
| agent | an agent session |
| user | the user |
| deciding | a deciding session (lead, solo or autopilot) |
| holder | the holder's session (or anyone while it is unheld) |
| gone | once the holder's session is gone, or the user agrees (take or unclaim --agreed) |
| non-author | not the actor that handed it over or that actor's session itself, unless the user agrees (claim --agreed) |
| planner | a session pulling plan (the session itself, not its workers) |
| deferrer | the deferrer's side (the deferring session or a deciding session; a user's deferral, or one without a deferrer, is a lead or solo session's or the user's) |
| holding | the session holding it |
| unheld | while it is unheld |
| attended | a lead or solo session (not autopilot: it leaves these moves, the user's to make or hard to undo, to the user; unattended protocol) |
<!-- /model-tables -->

Guards: `reason` (a non-blank reason), `items-closed` (no open item), `look-before` (only a look-before CR passes without agent review), `not-open-for-review` (end the user's review first), `no-waiters` (a close as dropped leaves no open or deferred record waiting on it: unlink the wait, wait on the keeper, or close them in the same call), `not-superseded` (a superseded ruling is put back by a revision record), `no-dropped-target` (a reopened record waits on nothing closed dropped), `settled-premises` (a record moves into `in_force` only when nothing it waits on is open outside `in_force` and no live record revises it, unless the same call brings them into force: `status.release-holds`), `no-hung-waiters` (a deferral leaves no live record waiting on it: `blocks.target`), `no-deferred-target` (an undeferral leaves nothing it reopens waiting on a deferred record, unless the same call undefers that too: `blocks.target`), `open-parent` (a reopened item's change request is open), `in-work` (an author hands over work in hand: hold `work`, not a planner's hold), `unheld-or-yours` (sending a passed CR to review or returning it waits while another session holds it, a refresh), `held-by-you` (an in-review CR is returned by the reviewer holding it). Each guard names its Write-rules cell (`GUARDS`).

## Authority

The table's `Who` column is the authority; this is its shape. Item writes (close, reopen, wait, move, and every field write: `update`, `field apply`) read the CR that holds the item; one writer per write kind applies it (`move`, `write_edges`, `write_fields` in `bin/board`; `put_meta` writes only the keys of the `meta.*` rows owned by its callers). A test allows each bd write verb only in its owner. Which rule guards which data, its owner and the cells each write verb's tests cover: [Write rules](#write-rules).

- A session claims, hands over and unclaims its work. Its workers hold under its actor. Deciding sessions are `lead`, `solo` and `autopilot` (`DECIDING_ROLES`).
- Review claim, pass and Return follow the `non-author` word; every claim path checks it.
- Authority follows what a move risks, as the unattended protocol classes it. Two-way moves (sending a passed CR back to review, the Return of a `passed` CR) are for any deciding session, autopilot included, or the user. The `attended` word (a lead or solo session, or the user) covers the moves autopilot leaves to the user: rejecting a CR (one-way: it closes, and no CR reopen exists), releasing a ruling, closing or reopening a gate, and claiming, taking, closing or reopening a milestone. Accept (landing a `passed` look-before CR) is the user's through a lead or solo session (landing is `anyone` in the table; its command is the gate).
- Taking or freeing another session's hold: the user, or a deciding session once the holder is gone (`--agreed` records the user's word).
- Planner Return on a ruling, and defer and undefer of its own deferrals: the session pulling plan itself, not its workers (nixes-sm4es). Undeferring a user's deferral (or one that records no deferrer) needs the user, through a lead or solo session; autopilot undefers only its own.
- The writes to an item of a CR nobody holds come from the user, a deciding session or a planner (the plan-pulling session itself, nixes-sm4es: its waits, moves, updates and closes of items); any other session claims the CR first. A planner never writes an item of a held CR: it comments the change on the CR, and its ruling stays in force until the hold ends. A deciding session also waits an item of a held CR. Filing a new item into a CR needs an open one (`create --parent` refuses a landed or dropped CR) and is a write to its items: its holder, the user, a planner or a deciding session files one, held or not (`ITEM_CREATE`; nixes-308o2, nixes-0an9j), and handover then refuses until the holder closes it or a deciding session moves it; any other session files the work as a no-commit task, as a new CR with its items in one `create --graph`, or comments on the CR (nixes-psxz8; the refusal names these routes). A CR the same plan creates is its creator's to fill. Comments and `relates-to` links are free of the hold rule: they hold nothing up (nixes-dy2u0). A held CR, task, decision or milestone guards its own writes the same way (nixes-7mt77): its fields, labels and parent moves need `ITEM_WRITE` read on the record itself (its holder, the user, or a deciding session once the holder is gone), and its waits `ITEM_WAIT` (adds `deciding`); an unheld record is free.
- Exceptions the table does not carry: autopilot never accepts or ratifies (acceptance needs the user; the unattended protocol owns it; `autopilot_barred` keeps it out of the queue's accept work, and `assignee.ready` refuses its claim by id) and runs the agent rows unattended; `MODEL_EXEMPT` names the writes that need no marker.

## Holding

- The holder field, written by compare-and-set (`update --assignee <actor> --if-assignee ''`, in `move`). Status never says who works. The holder is always a session's actor; a user step is a human gate.
- Holdable: CRs, tasks, decisions and milestones (a round holds its questions). Items are not holdable: holding the CR holds its items.
- CR metadata `hold` says how it is held: `work` (the holder works it in its worktree) or `plan` (a planner holds it without a worktree). `claim` writes it and every release clears it; an implement claim of a plan-held CR turns it into work, with a worktree and setup as a fresh claim. `move` owns the key (that claim is one of its rows); `put_meta` refuses it.
- A session registers a role and pulls (`plan`, `implement`, `review`; no design pull: design lands with its implementation in the same CR, and review runs as its own pull, so sessions on different models split implement and review). Its workers hold under its actor. Liveness decides whether a hold is gone; freeing follows Authority.
- **Stale holds** are surfaced, never freed by a timer or a new state (nixes-lleg9; code **planned**, nixes-qzzc1): `queue` and `health` print a `stale: assess` line for a hold gone quiet; `take` and `unclaim` of another session's work hold refuse without `--agreed` and show the worktree state (dirty, ahead) and the last comment in that refusal, and a take of a GONE hold prints them; a held record with no worktree shows the last comment only. The lead's judged step is plan.md step 1 (nixes-b8y69). `prune_days` is registry cleanup, not liveness.
- A close is one compare-and-set write of status `closed`, the outcome and the holder (a closer takes a record another actor holds, which `bd close` requires; no `--force` for that), checked against the status and holder just read; bd validates the close in that write (open children, blockers). `bd close` then only records the reason (which bd wants at 20 or more characters, so `board` refuses a shorter one before writing). A refused close writes nothing. A forced close (landing, `cr reject`, `gate resolve`, a question answered past its blockers) cannot combine `--force` with a compare-and-set in bd, so its guard takes the record instead: holder becomes the closer (`--assignee <closer> --if-assignee <current>`, with the outcome), releasing first when the closer already holds it (a take of one's own record changes nothing), then `bd close --force` records the reason. A second closer's guard expects a holder that is gone and is refused as changed meanwhile. If bd then refuses the close, the guard is undone (the previous holder and the metadata it set are put back), so a refused close leaves the record as it was (the undo is best effort, and a process that dies between the guard and the close leaves an open record held by the closer with its outcome set; neither can be closed without bd support for `--force` with a compare-and-set); the other window is the release of a closer's own record, in which another session may claim it, and the closer's retake then fails as changed meanwhile. The closed record keeps the closer as its assignee, which is history, not a hold.
- The worker cap (3, or `agents session activate --workers <n>`, lowered by Codex's thread limits) counts the open tasks one actor holds; `claim --force "<reason>"` goes past it and the hold shows `FORCED: <reason>` (metadata `forced_hold_by`, `forced_hold`). A bare claim at the cap passes such an item and names the command. A held task with no update for an hour is `STALE`. An unregistered session has no cap; one whose registration exists but is unreadable is refused until it registers again.

## Waits

One relation, written on the waiter, with a short "for" (content): "X waits on Y for …" (`agents board wait <item> --on <target> --for "<input>"`). Every write and dry run prints the sentence. A cycle is refused at the write (`wait-cycle` in `check` covers what came from outside). Waiters: an item, a whole CR (scope: every item, present and future), a task, a question. Milestones do not wait. Every writer (wait, create, plan graphs, gate create, ruling revise and supersede) meets the same rules, a new record at either end included: nothing waits on a deferred record or one in a deferred CR (set aside, it would never end), on an `external:` target (it never blocks), or on a record closed dropped (a question excepted: it releases its waiters; naming the keeper is the fix), and an in-force ruling waits only for its planning (a live decision, an in-force ruling until it is planned and closed, or a human gate).

| Waits on | Met when |
|---|---|
| an item in the same CR | it closes (done; an item closed dropped is refused while an open or deferred record waits on it) |
| another CR, or one of its items | that CR lands, or the waiter's CR stacks on it; `cr reject` is refused while an open or deferred record waits on it or its items |
| a question | it closes: planned (planning may rewrite the waiter, so in force is not enough), dropped or superseded |
| a gate | it is resolved |
| a task | it is closed done (a task closed dropped is refused while an open or deferred record waits on it) |

A wait is met only by a delivering close, so nothing closes dropped under an open or deferred waiter (`close` and `cr reject` name each waiter and the fix: unlink, wait on the keeper, or close it in the same call) and no wait names a record closed dropped (`wait`, `create --deps` and graph edges refuse a new one; `reopen` refuses a record that waits on one, naming unlink). A close of several ids is all or none: every id's whole close (row, authority, guards) is checked before the first write. Defer's own rule stays live waiters only. `check` reports a wait on a dropped record (`dropped-blocker`) only when it was written outside the verbs.

## Readiness

- CR: unheld, its base allows it, every CR-scope wait met, and either an open item is ready or no item is open (its next step is handover).
- Task, question: unheld, waits met; outside any CR it cannot stack, so a wait on another CR's item holds it until that CR lands.
- A CR waits as a whole only for CR-scope waits; what an item waits on holds the item. A CR stacks on at most one base: its own (a CR-scope wait's) when it has one, else its items' only candidate; two CR-scope bases hold the CR, and an item's other base holds that item.
- Pulls: `plan` (rulings in force, tasks, a CR marked `plan_first`: rejected base, migrated loose work), `implement` (a ready open CR), `review` (an `in_review` CR, refresh work). A bare `claim` takes what the session's role and pulls route; a claim by id checks no pull. Deciding sessions also take questions, `passed` CRs waiting for Accept and ready milestones. Inside a session, dispatch may pick a worker agent by an item's kind label.
- Claim order: priority P0 first, then planning (rulings in force, a `plan_first` CR, no-commit tasks), milestone work, review and refresh, Accept, the rest; within a tier priority, then unlock rank (board-coordination).

## Deferral

- `deferred` = set aside, blocked by nothing, off the queue: someday or maybe, no condition. Only an explicit `undefer` reopens it.
- Applies to CRs, tasks and questions. To set one item aside, move it into its own CR first.
- A condition on another record or event is a wait, not a deferral: `defer` takes no condition. The round engine follows it: an answer resting on an open premise waits on it (nixes-rzfij), it is never deferred. `defer` refuses an item that live items wait on (they would hang), naming the fix. `undefer` refuses a record that would wait on a deferred one again; undefer both in one call, or unlink the wait.
- A deferral records who deferred (`deferred_by`: `user` for the user, a lead or solo session acting for them, or a migrated deferral that records none; else the deferring session's actor, autopilot's included) and an optional `revisit` day (a board field; not bd's `defer_until`, so bd never wakes it). Due is derived at read (revisit <= today): a due user deferral shows in the user's view, a due session deferral as plan work. It stays deferred until undeferred: parked work never starts unasked. Only the deferrer's side undefers. `defer --until` sets the day.

## Relations and fields

part of (item in its CR, CR in a milestone: the only parent pairs), supersedes, context (`relates-to`, ruling context). A duplicate is a `relates-to` link to the original and a close with outcome `dropped` whose reason names it. Found-in is a field on the found record (`--found-in`), so bd's one link per pair stays free for the real relation; `discovered-from` is refused, naming it. bd's blocking link spellings are refused, naming `wait`; a parent changes only through `move` (`link` refuses `parent-child`, `unlink` a parent edge, and a plan a parent for an existing record, each naming `move`); every edge meets one set of rules, `edge_rules` in `bin/board`, whichever bd write carries it ([Write rules](#write-rules)); `create`, `--graph` and `link` write only the relations here, and a plan edge or `--deps` type outside them is refused; `check` flags a link type the board does not write (`unknown-link`) and metadata outside `BOARD_METADATA` (`unknown-metadata`). Retired metadata keys and the earlier `related` link are board-migrate's to convert; the board keeps no repair for them (`check` has no `--fix`).

## Write rules

Every rule is keyed to the data it guards, not to the verb that writes it (nixes-jczod). Each one runs in its row's owner on every write of that data, for a new record and an existing one. The first table is the contract: a row is an edge kind, a field or a metadata key, spelled as bd stores it, and each rule has a cell id `<row>.<rule>`. `New` covers a record the same call creates; `Existing` covers one already on the board. Each of the two columns holds exactly one token:

- `runs`: the named owner runs the rule for every writer of that case. A rule that runs only in a verb's own code, or only on some writers, is a gap, not `runs`.
- `n/a`: the case cannot arise.
- `gap Gn`: the code does not meet the rule yet; [Gaps](#gaps) says what it does today.
- `open Qn`: waits on a ruling. None is open: the six points of the deep review (nixes-oijml) are ruled in nixes-7mt77 (Q3: a hold guards the held record's own writes), nixes-df7kf and nixes-7oqkc (Q1, Q2, Q4 checkpoint, Q5, Q6) and nixes-lleg9 (stale holds).

An owner column names where the rule must run: a function, not a verb; a function in parentheses is the owner's helper that holds the check. Every refusal is built by `refuse(cell, text)` naming its cell, and only inside a function of that cell's Owner column; an input error (malformed whatever the board holds: an unknown id, the wrong record type for the verb, bad flags, files or plan shape) by `bad_input`, and a failure of the environment (git, bd, the server, setup, a lost compare-and-set) or of the board's invariants by `fault` (nixes-h1igl). A refusal a verb prints for one id before it goes on to the next is such an object too (nixes-mfglk). The rules group checks the form only: no bare `BoardError`, every `refuse` names a cell of this table and stands in one of its owners, every printed refusal is a `BoardError`, and a rule cell's case runs its verb (a static reach case is left to the bookkeeping cells and a listed few). Whether a refusal is a rule or an input error is the author's judgment, which review checks (nixes-3d4pu): a board-data rule built with `bad_input` passes the test. A writer allowlist is one cell per owner: `write_fields` writes only `--title`, `--priority`, `--add-label`, `--remove-label`, `--body-file`, `--design-file`, `--acceptance`, `--notes`, `--external-ref`, `--spec-id`, `--estimate`, and `--set-metadata`/`--unset-metadata` of `no_commit`, `look` and `view` (plus `sent_at` for `send`); every other bd update flag (`--metadata`, `--set-labels`, `--status`, `--assignee`, `--type`, `--parent` and the rest) is refused. `put_meta` writes only the keys of the `meta.*` rows owned by its callers and refuses every other key, as it already refuses the settings. Both allowlists are cells: `fields.allowlist` and `meta.allowlist`.

An explicit `actor` argument is a non-empty actor or None (derive it); `''` is refused as internal. The user is a caller with no session environment; a session whose actor cannot be derived is refused (`actor.none`).

| Row (data) | Cell | Rule | Owner | New | Existing |
|---|---|---|---|---|---|
| `parent-child` | `parent-child.only-move` | An existing record's parent changes only by `move` (nixes-j65oa). `link` refuses `parent-child`, `unlink` refuses a parent edge, and a plan refuses a parent for an existing record. | `edge_rules` | n/a | runs |
| | `parent-child.kind-fit` | Only a task is a child of a CR, and only a CR is a child of a milestone; every other pair is refused (nixes-s378b, nixes-7oqkc). A decision, gate or milestone has no parent: `ruling revise` has no `--parent`, and a revision or confirmation inherits none. | `edge_rules` | runs | runs |
| | `parent-child.work-needs-cr` | A work task's parent is a CR (`loose_work_refusal`). A no-commit task has no parent. | `edge_rules` | runs | runs |
| | `parent-child.open-parent` | The parent is not closed. | `edge_rules` | runs | runs |
| | `parent-child.one-parent` | A record has exactly one parent (Types: an item of exactly one CR). | `edge_rules` | runs | runs |
| | `parent-child.item-create` | Entering a CR is a write to its items (`ITEM_CREATE`): the holder, the user, a planner or a deciding session, held or not (nixes-308o2, nixes-0an9j). A CR the same plan creates is its creator's to fill. | `edge_rules` | runs | runs |
| | `parent-child.leave` | Only an open record changes its parent; leaving a CR needs `ITEM_WRITE` on that CR, and the item must be unheld (`parent_move_refusal`). | `edge_rules` (`parent_move_refusal`) | n/a | runs |
| | `parent-child.enter` | A task enters a CR only open and unheld: an item has no deferral or hold of its own (Deferral, Holding), so a deferred or held task is refused, naming `undefer` or `unclaim`, after the hold rule (another session's hold is refused as `held-record.write`). | `edge_rules` | n/a | runs |
| | `parent-child.cr-stays` | A CR keeps its parent and moves only into a milestone. | `edge_rules` (`parent_move_refusal`) | n/a | runs |
| | `parent-child.queue` | On a shared board, only a lead, solo or person moves an item into another queue by its parent. | `edge_rules` (`parent_move_refusal`) | n/a | runs |
| | `parent-child.no-commit` | Entering a CR clears `no_commit` in the same write (nixes-x62oy). | `write_edges` | n/a | runs |
| | `parent-child.owner` | No other writer: `write_fields` refuses `--parent`. | `write_fields` | n/a | runs |
| | `parent-child.refusal-text` | A refusal by `item-create` names routes that work: a no-commit task, a new CR with its items in one `create --graph`, or a comment (nixes-psxz8). | `edge_rules` | runs | runs |
| `blocks` (a wait) | `blocks.writers` | A wait is written only as a wait: `wait`, `waits_on` and `--deps`, `--holds`, `gate create`, and the ruling verbs. `link` refuses one, and bd's link words are refused, naming `wait`. | `edge_rules` (`refuse_old_link`) | runs | runs |
| | `blocks.target` | Nothing waits on a deferred record, on a record in a deferred CR, or on a record closed dropped, a question excepted (nixes-ze5lx). Held when a wait is written, when a waited-on record moves into a deferred CR (`move`), when a record is deferred (`move`'s guard `no-hung-waiters` on the defer rows, every id before the first write: `deferred_waiters`, a question is refused only when an in-work unit would hang on it, any other record when a live record waits on it), and when a record is undeferred (guard `no-deferred-target` on the undefer rows: it, or an open item of a CR, waits on a deferred record or an item of a deferred CR that the same call does not undefer: `deferred_targets`). A plan's new record sits in the CR the plan gives it. | `edge_rules` (`wait_target_refusal`), `move` (`deferred_waiters`, `deferred_targets`) | runs | runs |
| | `blocks.external` | An `external:` wait target is refused at every writer: it never blocks (Operation notes, Beads features the board avoids), and upstream waits use a human gate (nixes-7oqkc). | `edge_rules` (`wait_target_refusal`) | runs | runs |
| | `blocks.waiter` | A milestone waits on nothing. An in-force ruling waits only for its planning: a live decision, another in-force ruling until it is planned and closed (nixes-r0e01), or a human gate. Checked on the wait write; a record coming into force has only in-force waits (`status.release-holds`). | `edge_rules` (`wait_target_refusal`) | runs | runs |
| | `blocks.cycle` | No cycle in the lifted wait graph (waits between items of different CRs count as waits between the CRs; a plan's new records sit in the CRs it gives them), after any write that changes it: a wait added (`wait`, plan `deps`, `waits_on` and edges, `--holds`, `gate create`, supersede waits) or an item's CR changed (`move`). Checked before the first write. | `edge_rules` (`wait_cycle`) | runs | runs |
| | `blocks.hold` | Adding or removing an item's wait needs `ITEM_WAIT` on its CR. A held non-item waiter: `held-record.wait`. | `edge_rules` | n/a | runs |
| | `blocks.for` | A wait on work needs a for, whichever writer adds it; a plan file names a for on every wait (`load_plan`). An existing record made to wait on a new work item is refused, naming `wait`. | `edge_rules`, `wait_one`, `load_plan` | runs | runs |
| | `blocks.pair` | One edge per pair; a `relates-to` link gives way to a wait. | `edge_rules` | n/a | runs |
| | `blocks.no-dropped-close` | A close as dropped (`close`, `cr reject`) is refused while an open or deferred record waits on the record or its items (nixes-ze5lx). Several ids are all checked before the first write. A mid-call conflict names what closed and any dead wait (nixes-i2cgg). | `move` (guard `no-waiters`) | n/a | runs |
| | `blocks.reopen` | `reopen` refuses a record that waits on a dropped one (guard `no-dropped-target`). | `move` | n/a | runs |
| `relates-to` | `relates-to.free` | Free of the hold rule (nixes-dy2u0). | `edge_rules` | runs | runs |
| | `relates-to.types` | `link` writes only `LINK_VERB_TYPES`, and a plan or `--deps` writes only `PASS_LINKS`; the retired words `related` and `discovered-from` are refused naming their replacement. | `edge_rules` (`refuse_old_link`) | runs | runs |
| | `relates-to.pair` | One link per pair (`link`, `ruling record`). | `edge_rules` | n/a | runs |
| `supersedes` | `supersedes.ruling-only` | Only the ruling verbs write or remove it: `--partial` through `write_edges`, and a full supersede through bd supersede inside `move`. | `edge_rules`, `move` | n/a | runs |
| | `supersedes.row` | A full supersede is `move`'s `supersede` row. A superseded ruling comes back only through a revision (guard `not-superseded`). | `move` | n/a | runs |
| | `supersedes.who` | Writing or removing a supersedes edge, partial or full, needs the supersede row's Who (deciding or user), checked before the first write: a refused supersede leaves no carried `tracks` edge, `board.revises_rule` or wait behind. | `edge_rules` (`supersede_who_refusal`) | n/a | runs |
| | `supersedes.hold` | Every writer of the edge (`ruling record`, `ruling release`, `ruling supersede`, partial included) is refused by another live session's hold on the record, and a gone session's hold is taken first (`gone_hold`); `ruling record` and `ruling release` check every record they supersede before their first write, and `ruling check-replaces` previews it for Stage. | `hold_refusal` (called by supersede_pair, the writers' common path, replaced_checks, release and check_replaces) | n/a | runs |
| `tracks` (a revision) | `tracks.ruling-only` | Only the ruling verbs write or remove it (`revise`, `record --replaces`, and the carried revisions of `supersede` and `release`). | `edge_rules` | runs | runs |
| | `tracks.one-revision` | A record revises at most one record or rule. | `one_revision_refusal` (called by replaced_checks and check_replaces), `carry_revisions` | runs | runs |
| | `tracks.revisable` | A revision or a replacement takes a ruling: decided, in force, or closed planned; not an open question, a closed one, or one already superseded. | `replaceable_refusal` (called by revise, replaced_checks and check_replaces) | n/a | runs |
| `status`, `close_reason` | `status.row` | The `MOVES` row for the command, type and status, with its held rule, `Who` and guards, written in one compare-and-set. bd's own blockers and children are seen before a multi-id call writes. A verb checks its row, held rule and guards first (`move(..., write=False)`, or `table_refusal` for the `Who` alone) and keeps only what the row cannot read as its own cell: status and holder checks live here alone (nixes-0yida); `non-author` is `self_review_refusal`. | `move` (`refuse_held`, `table_refusal`, `self_review_refusal`) | n/a | runs |
| | `status.who-planner` | `planner` means the plan-pulling session itself (`actor == session`), as `deciding` does (nixes-sm4es). This applies to every row and tuple using the word (`ITEM_WRITE`, `ITEM_CREATE`, `DEFER`), with one copy of the check (`authority_part`). | `authority_part` | runs | runs |
| | `status.open-parent` | An open record's parent is open: `reopen` refuses an item of a closed CR. | `move` | n/a | runs |
| | `status.owner` | No other writer: `write_fields` refuses `--status`/`-s`, `--claim` and `--defer`. | `write_fields` | runs | runs |
| | `status.release-holds` | A record comes into force (`ruling release`, `ruling record --unratified`) only on settled premises: nothing it waits on is open outside `in_force`, and no live record revises it, unless the same call brings them into force too (nixes-9cbib, r9-q33). Applied on the move from `open` or `decided`; an in-force re-record keeps its planning waits. `health`'s `blockedBy` reads the same list (`release_holds`). | `move` (guard `settled-premises`, `release_holds_refusal`) | n/a | runs |
| | `status.items-closed` | A CR is handed over, passed or rejected only with every item closed (guard `items-closed`); `handover`, `land_core` and `prepare_land` check it before their checks run, and `cr reject` names the dropped close. | `move` (`open_item_refusal`), `reject` | n/a | runs |
| | `status.not-open-for-review` | While the user's review is open (`opened_tip`), `handover` (guard `not-open-for-review`), a claim and `cr refresh` refuse the CR. | `move` (`refuse_open`) | n/a | runs |
| | `status.return` | `return --ruling`: before the claim that reserves it, a CR in review (the row's From; its Held is then the caller), and an in-force ruling the caller holds that an open item of the CR waits on. The claim and return rows check the rest. | `reserve_planner_return` | n/a | runs |
| | `status.land` | `cr land`: a lead, solo or person; a passed CR, unheld or the caller's, whose stacked base has landed; a CR passed without agent review lands only the series the user saw. | `land` (`prepare_land`) | n/a | runs |
| | `status.landing` | A landing needs a landed base, a passing check stored for the current pair and a review covering the series (an uncovered passed CR goes back to agent review). | `land_core` | n/a | runs |
| | `status.refresh` | `cr refresh`: a CR in work, in review or passed, unheld or the caller's. | `refresh` | n/a | runs |
| | `status.release` | `ruling release --closes`: each question it closes is an open question, unheld or the caller's, checked for every id before the first write (stricter than the `close` row, which `close` shares). | `release` | n/a | runs |
| `assignee` | `assignee.row` | Only claim, take, unclaim and the closing rows write it, by compare-and-set (non-author, gone). A claim or take past the worker cap is refused without `--force` (`cap_refusal`). `create` takes no holder. | `move`, `cap_refusal` | runs | runs |
| | `assignee.ready` | A claim by id takes only a record ready for a pull (Readiness): a milestone whose work is done, a record other than a CR whose waits are met, a CR some pull admits (`cr_problems` says why not, and the user's open review); autopilot never claims a CR waiting for the user's Accept. | `ready_refusal` | n/a | runs |
| | `assignee.work-needs-cr` | A work task outside any CR is not claimed (`work_item_refusal`); an item is held with its CR (`item_hold_refusal`). | `work_item_refusal`, `item_hold_refusal` | n/a | runs |
| | `assignee.stale-evidence` | `take` and `unclaim` of another session's work hold refuse without `--agreed` and show the worktree state (dirty, ahead) and the last comment in that refusal (a GONE hold: in the take's output); a held record with no worktree shows the last comment only (nixes-lleg9; Holding). | `elsewhere_refusal` | n/a | gap G25 |
| | `assignee.owner` | `write_fields` refuses `--assignee` and `--if-*`. | `write_fields` | n/a | runs |
| `issue_type` | `issue_type.types` | Only board types; a gate only through `gate create`. | `create_plan` (`type_refusal`) | runs | n/a |
| | `issue_type.owner` | `write_fields` refuses `--type`. | `write_fields` | n/a | runs |
| any bd update flag | `fields.allowlist` | `write_fields` writes only the flags listed above and refuses every other (`--metadata`, `--set-labels`, `--force`, `--description` and the rest). | `write_fields` (`field_pairs`, `field_values`) | n/a | runs |
| a held CR, task, decision or milestone (the record itself) | `held-record.write` | Its fields, labels and parent moves (a held CR into a milestone) need `ITEM_WRITE` read on the record: its holder, the user, or a deciding session once the holder is gone. An unheld record is free (nixes-7mt77). `share`'s first queue label on an unlabelled top-level record passes this rule (nixes-3se1p: before a share every holder is the user's own session); `route` and `send` stay under it. | `write_fields`, `edge_rules` | n/a | runs |
| | `held-record.wait` | Adding or removing a wait of a held record needs `ITEM_WAIT` read on the record (`ITEM_WRITE` plus `deciding`). An unheld record is free (nixes-7mt77). | `edge_rules` | n/a | runs |
| `title`, `priority`, `description`, `design`, `acceptance_criteria`, `notes`, `external_ref`, `spec_id`, `estimate` | `content.hold` | Writes to an item need `ITEM_WRITE` on its CR. | `write_fields` | n/a | runs |
| | `content.size` | A work task's long fields stay within `FIELD_LIMIT` unless the write shrinks them or only changes paths. Decisions are exempt. | `create_plan` (new), `write_fields` (`field_values`, existing) | runs | runs |
| | `content.export` | `field apply` refuses a field that moved since its export, or an empty file. | `field_apply_one` | n/a | runs |
| `labels` | `labels.hold` | A label write to an item needs `ITEM_WRITE` on its CR. | `write_fields` | n/a | runs |
| | `labels.form` | A label has a known prefix, a `kind:` from `KIND_LABELS`, and no status word. | `create_plan` (new), `write_fields` (`field_values`, existing) | runs | runs |
| `queue:`, `for:` labels | `queue.route` | Only `route`, `send`, `create --for`, `gate create --for` and the creator's own queue on a parentless node change these; `update` refuses them. | `write_fields` (`field_values`), `create_plan` | runs | runs |
| | `queue.attended` | `route`, `send`, and a plan putting work in another person's queue: a lead, solo or person only. | `attended_issues`, `plan_queue_refusal` | runs | runs |
| | `queue.top-level` | `send` takes only a top-level item: one with a parent takes its parent's queue. | `send` | n/a | runs |
| | `queue.claim` | On a shared board a session takes or reserves only what is in its person's queue; an unrouted item waits for a lead's route. | `foreign_claim` | n/a | runs |
| | `queue.owner` | Every label write goes through the label owner. `share` checks every write, its labels included, before its first push, so a refusal leaves nothing half-done (nixes-3se1p). | `write_fields` | n/a | runs |
| comments | `comments.size` | A session's comment stays within `FIELD_LIMIT` whichever verb writes it, and a verb whose comment follows its other writes checks it before them (`refuse_long_comment`); `--board-packet` is exempt. Comments are free of the hold rule. | `comment` (`refuse_long_comment`) | runs | runs |
| | `comments.owner` | `comment()` is the one comment writer: it passes the text to bd on stdin (`-f -`) and runs `comments.size`, and `comment_command` and every verb that comments call it (nixes-7oqkc). | `comment` | runs | runs |
| `no_commit`, `look`, `view` | `setting.values` | `setting_refusal`: `no_commit` on a task only, `look`/`view` on a CR from their value sets, never the project default. | `create_plan` (new), `write_fields` (`field_values`, existing) | runs | runs |
| | `setting.who` | `update` sets them only from a lead, solo or person, on an unheld record: `no_commit` outside any CR, `look`/`view` on an open CR. | `write_fields` (`field_values`) | n/a | runs |
| any metadata key | `meta.allowlist` | `put_meta` writes only the keys of the `meta.*` rows whose owner is a caller of `put_meta` (not `move`, `write_fields` or board-migrate) and refuses every other key. | `put_meta` | n/a | runs |
| `outcome`, `deferred_by`, `revisit` | `meta.move-keys` | Written only with `move`'s row: the closing row (reopen clears `outcome`), `defer` and `undefer`. `put_meta` and `write_fields` (`--metadata`, `--set-metadata`, `--unset-metadata`) refuse them. | `move`, `write_fields` (`field_values`) | n/a | runs |
| `hold`, `author` | `meta.holder-keys` | `move` writes both: `hold` by the claim rows (an implement claim of one's own plan-held CR is a `MOVES` row, held `you` to `you`, writing `hold=work`) and cleared by every release, `author` by the hand-over. `put_meta` refuses them (nixes-7oqkc). | `move` | n/a | runs |
| `found_in` | `meta.found-in` | Set at creation to a known record; `discovered-from` is refused. | `create_plan` | runs | n/a |
| `board.revises_rule` | `meta.revises-rule` | Written only by the ruling verbs (`revise --partial`, `carry_revisions`). | `create_ruling_revision`, `carry_revisions` | runs | runs |
| `sent_at` | `meta.sent-at` | `send` stamps it in the same bd update as its `for:` label, every send, a pass-on and a repeat included; the label and its stamp never diverge. `put_meta` refuses it. | `write_fields` | n/a | runs |
| `landing` | `meta.landing` | Written only by landing; it decides that a CR has landed. | `land_core` | n/a | runs |
| `check_at`, `check_base_count`, `check_base_tip`, `check_command`, `check_kind`, `check_new`, `check_output`, `check_reason`, `check_result`, `check_tip`, `check_tip_count` | `meta.check` | The stored check is written only where the check runs; it decides landing and refresh. | `sync_branch`, `store_gate` | n/a | runs |
| `review_tip`, `review_base_tip`, `opened_tip`, `reviewing_tip`, `review_edits`, `no_agent_review_reason` | `meta.review` | Review currency and the open review: `review_tip`, `review_base_tip` and `no_agent_review_reason` by `handover`; `opened_tip` by `review_open`, `end_review` and `land_core`; `review_edits` by `record_edits`, `cr_edits` and `record_merged`; `reviewing_tip` by the claim rows and `handover`. | `handover`, `review_open`, `end_review`, `land_core`, `record_edits`, `cr_edits`, `record_merged`, `move` | n/a | runs |
| | `meta.seen-tip` | A reviewer's pass records `review_tip` only for the tip its reviewer saw (`reviewing_tip`, set by the review claim): a tip that moved since, by a rebase onto a new base or new commits, refuses the pass and records the new tip as seen. | `handover` | n/a | runs |
| `user_seen_tip`, `user_seen_base_tip` | `meta.user-review` | The user's last-seen range. | `review_open`, `prepare_land` | n/a | runs |
| the user's review of a CR (its opened tip and edits) | `meta.review-unrecorded` | A user review holding edits not yet recorded refuses `cr land`, `return` and `cr request-review` until `cr edits --commit` records them. | `refuse_unrecorded` | n/a | runs |
| | `meta.review-open` | `review open`: a lead, solo or person, on a passed CR no agent session holds at work. | `review_open` | n/a | runs |
| | `meta.edits` | `cr edits`: a passed CR with the user's review open at `--tip`; `--commit` and `--merged` by a lead, solo or person, the CR unheld or theirs; `--merged` records only the merge of a recorded edit commit. | `cr_edits`, `edits_target`, `record_merged` | n/a | runs |
| `base`, `base_sha`, `rebase_onto`, `rebase_from` | `meta.base` | Stacking: written where a base is chosen, refreshed or landed. | `open_worktree`, `adopt_stack_base`, `sync_branch`, `finish_landing`, `reject` | n/a | runs |
| `plan_first` | `meta.plan-first` | A rejected base sets it; the plan claim clears it. | `reject`, `move` | n/a | runs |
| `resume` | `meta.resume` | One owner: `move` sets it on unclaim and clears it in the claim row. `unclaim` of one's own work in progress needs `--resume`, and `--resume` hands back only one's own work (`resume_refusal`). | `move`, `resume_refusal` | n/a | runs |
| `forced_hold_by`, `forced_hold` | `meta.forced` | Written only by a forced claim. | `mark_forced` | n/a | runs |
| `since`, `setup_sha` | `meta.info` | `since` orders the queue within a tier and `setup_sha` decides whether setup reruns; neither decides status, authority or landing. | `move`, `reject`, `ensure_setup` | n/a | runs |
| `deep_review` | `meta.deep-review` | Written by `unclaim --deep-review <path>` under the CR's hold (`put_meta`); cleared only by the reviewer's pass (`handover` of an `in_review` CR by a non-author); `unclaim`, `return` and the author's `handover` keep it (nixes-df7kf, nixes-fy01y). review.md's step uses it. | `unclaim`, `handover` | n/a | runs |
| `checkpoint` | `meta.checkpoint` | A legacy key owned by board-migrate (`convert-design-checkpoints.py`); `check` flags it (`cr-checkpoint`). No board verb writes it. | board-migrate | n/a | n/a |
| `custom.board.*` (`target`, `setup`, `checks`, `look`, `view`, `model`, `shared`, `moved`) | `config.owner` | `setup` writes the settings, and the model marker on a board it creates (board-migrate's converter marks an existing one). `share` and `join` write the shared config (`set_config`) and `shared`; `relocate` (`move_board`) writes `moved`. They are not records. | `setup`, `share`, `join`, `move_board` | runs | runs |
| the database (init, backup, dolt commit, push, pull, remote, sync, flatten) | `db.owner` | Run by `setup`, `share`, `join`, `relocate` (`move_board`), `Shared.before` (pull) and `_sync-wait` (commit and sync). They are not records. Only a lead, solo or person relocates a board. | `setup`, `share`, `join`, `move_board`, `Shared.before`, `_sync-wait` | runs | runs |
| any (raw) | `raw.door` | `bd --raw --yes` runs bd without the board's rules, by design (board-core). `bd` alone runs `--readonly`. The protocol engine reaches bd only through `board`, and its one `board bd` is a `list`, so no allowlist covers it (nixes-k7617). | `run_bd` | n/a | n/a |
| any write | `actor.none` | A missing actor never stands for the user: an explicit `actor` is a non-empty actor or None, `''` is refused, and a session whose actor cannot be derived is refused. | `acting` (run by `move`, `write_fields`, `edge_rules`, `create_plan`, `table_refusal`, `may_attend`, `caller`) | runs | runs |

### Gaps

What the code does today where a cell reads `gap Gn`. nixes-fmf56 closed G1-G24; G25 is nixes-qzzc1's.

| Gap | Today |
|---|---|
| G25 | Not built: the stale-hold evidence in `take`/`unclaim` and the `stale: assess` line (nixes-qzzc1, nixes-b8y69). |


### Verbs

`Verb` is the name the parser gives it. `Input form` is one of `any`, `parent`, `deps-id`, `deps-type`, `holds`, `graph`, `for`, `label`, `setting`, `content`, `replaces`, `unratified`, `partial`, `ruling`, `finding`, `deep-review`, `resume`, `agreed`, `look-after`, `one-id`, `ids`, `conflict`, `same-cr`, `other-cr`, `cr`, `refused-flag`. `Kinds` is `any` or a list of `task`, `no-commit`, `cr`, `decision`, `gate`, `milestone`. `Cells` holds cell ids and `row.{a, b}` groups only. A test checks that every parser write verb and every non-verb writer has a row, that every cell is named by a row or is writer-less (`meta.checkpoint`), and that each (verb, input form, kind, cell) has a test: the `rules` group of `bin/test-agent-configs.py`, which parses both tables and fails on a token other than `runs` or `n/a` outside the open gaps. A refusal case passes only when its own cell refuses (the reported refusal, else the last one a printing verb built); a flag the verb's parser lacks is refused by the parser. The same group reads `bin/board`'s source: it fails on a bare `BoardError(`, on a `refuse` naming no cell of this table, and on a `refuse` outside its cell's Owner; `move`'s guards name their cells in `GUARDS`.

| Verb | Input form | Kinds | Cells |
|---|---|---|---|
| `create` | any | any | issue_type.types, content.size, labels.form, setting.values, meta.found-in, assignee.row, actor.none |
| `create` | parent | any | parent-child.{kind-fit, work-needs-cr, open-parent, item-create, refusal-text} |
| `create` | deps-id | any | blocks.{writers, target, external, waiter, cycle, for}, comments.size |
| `create` | holds | decision | blocks.{target, waiter, cycle, hold}, held-record.wait |
| `create` | deps-type | any | relates-to.types, tracks.ruling-only, supersedes.ruling-only |
| `create` | label | any | queue.route |
| `create` | for | any | queue.{route, attended} |
| `create` | graph | any | parent-child.{kind-fit, work-needs-cr, open-parent, item-create, refusal-text, one-parent, only-move}, blocks.{writers, target, external, waiter, cycle, for}, queue.{route, attended}, issue_type.types, content.size, labels.form, setting.values, meta.found-in, comments.size |
| `move` | any | task | parent-child.{kind-fit, item-create, leave, open-parent, cr-stays, queue, no-commit}, blocks.{target, cycle}, held-record.write, actor.none |
| `move` | any | no-commit | parent-child.{kind-fit, item-create, enter, leave, open-parent, cr-stays, queue, no-commit}, blocks.{target, cycle}, held-record.write, actor.none |
| `move` | any | cr | parent-child.{cr-stays, queue, leave, open-parent}, held-record.write, actor.none |
| `move` | any | decision, gate, milestone | parent-child.{kind-fit, leave}, actor.none |
| `wait` | same-cr | any | blocks.{writers, target, external, waiter, cycle, hold, for, pair}, held-record.wait, status.row, actor.none, comments.size |
| `wait` | other-cr | any | blocks.{writers, target, external, waiter, cycle, hold, for, pair}, held-record.wait, status.row, actor.none, comments.size |
| `wait` | cr | cr | blocks.{writers, target, external, waiter, cycle, for, pair}, held-record.wait, status.row, actor.none, comments.size |
| `link` | any | any | relates-to.{free, types, pair}, parent-child.only-move, blocks.writers, supersedes.ruling-only, tracks.ruling-only, actor.none |
| `unlink` | any | any | blocks.hold, held-record.wait, parent-child.only-move, supersedes.ruling-only, tracks.ruling-only, relates-to.free, actor.none |
| `update` | content | any | content.hold, held-record.write, actor.none, fields.allowlist |
| `update` | label | any | labels.{hold, form}, queue.route, held-record.write, fields.allowlist |
| `update` | setting | any | setting.{values, who}, fields.allowlist |
| `update` | refused-flag | any | status.owner, assignee.owner, issue_type.owner, parent-child.owner, meta.move-keys, fields.allowlist |
| `field apply` | any | any | content.{hold, size, export}, held-record.write, fields.allowlist, actor.none |
| `route` | any | any | queue.attended, labels.hold, held-record.write, fields.allowlist, actor.none |
| `send` | any | any | queue.{attended, top-level}, meta.sent-at, held-record.write, fields.allowlist, actor.none |
| `comment` | any | any | comments.{size, owner}, actor.none |
| `close` | one-id | any | status.row, blocks.no-dropped-close, meta.move-keys, actor.none |
| `close` | ids | any | status.row, blocks.no-dropped-close |
| `close` | conflict | any | blocks.no-dropped-close |
| `reopen` | any | task, decision, gate, milestone | status.{row, open-parent}, blocks.reopen, supersedes.row, meta.move-keys, actor.none |
| `defer` | any | task, cr, decision | status.row, blocks.target, meta.move-keys, comments.size, actor.none |
| `undefer` | any | task, cr, decision | status.row, blocks.target, meta.move-keys, actor.none |
| `claim` | any | any | status.row, assignee.{row, ready, work-needs-cr}, status.who-planner, meta.{holder-keys, review, plan-first, resume, forced}, meta.allowlist, actor.none |
| `claim` | agreed | any | comments.size |
| `take` | any | any | status.row, assignee.{row, stale-evidence, work-needs-cr}, queue.claim, meta.{holder-keys, review}, actor.none |
| `take` | agreed | any | comments.size |
| `unclaim` | any | any | status.row, assignee.{row, stale-evidence}, meta.{holder-keys, resume, review}, meta.deep-review, actor.none |
| `unclaim` | resume | any | meta.{resume, deep-review}, comments.size |
| `unclaim` | agreed | any | comments.size |
| `unclaim` | deep-review | cr | meta.deep-review, meta.allowlist |
| `handover` | any | cr | status.{row, items-closed, not-open-for-review}, meta.{holder-keys, review, seen-tip, check, deep-review}, comments.size, meta.allowlist, actor.none |
| `handover` | look-after | cr | status.row, meta.{landing, check, base, review} |
| `return` | any | cr | status.row, meta.{review, info, review-unrecorded, deep-review}, comments.size, actor.none |
| `return` | ruling | cr | status.{row, who-planner, return}, assignee.row, queue.claim, meta.holder-keys |
| `return` | finding | task | parent-child.{kind-fit, open-parent, work-needs-cr, item-create}, labels.form, queue.route |
| `cr request-review` | any | cr | status.row, meta.{review, review-unrecorded}, comments.size, meta.info, actor.none |
| `cr refresh` | any | cr | status.{row, refresh, not-open-for-review}, meta.{landing, review, base, check, info, allowlist}, actor.none |
| `cr edits` | any | cr | status.row, meta.{review, check, base, info, allowlist, edits}, actor.none |
| `review open` | any | cr | meta.{review, user-review, allowlist, review-open}, actor.none |
| `cr land` | any | cr | status.{row, land, landing, items-closed}, meta.{landing, review, user-review, base, review-unrecorded}, comments.size, meta.allowlist, actor.none |
| `cr reject` | any | cr | status.{row, items-closed}, blocks.no-dropped-close, meta.{base, plan-first, info}, comments.size, actor.none |
| `gate create` | any | gate | blocks.{target, waiter, cycle, hold}, issue_type.types, held-record.wait, actor.none |
| `gate create` | for | gate | queue.route |
| `gate resolve` | any | gate | status.row, actor.none |
| `ruling record` | any | decision | status.row, assignee.row, actor.none |
| `ruling record` | replaces | decision | tracks.{ruling-only, one-revision, revisable}, supersedes.{ruling-only, row, who, hold} |
| `ruling record` | unratified | decision | status.release-holds, assignee.row, parent-child.kind-fit, relates-to.types, supersedes.{ruling-only, row, who, hold} |
| `ruling revise` | any | decision | tracks.{ruling-only, revisable}, actor.none |
| `ruling revise` | holds | decision | blocks.{waiter, hold}, held-record.wait |
| `ruling revise` | label | decision | labels.form, queue.route |
| `ruling revise` | partial | decision | meta.revises-rule |
| `ruling release` | any | decision | status.{row, release-holds, release}, supersedes.{ruling-only, row, hold}, blocks.{waiter, cycle}, assignee.row, actor.none |
| `ruling supersede` | any | decision | supersedes.{ruling-only, row, who, hold}, blocks.{target, waiter, cycle}, tracks.one-revision, meta.revises-rule, actor.none |
| `ruling supersede` | partial | decision | supersedes.{ruling-only, who, hold}, comments.size |
| `setup` | any | any | config.owner, db.owner |
| `share` | any | any | config.owner, db.owner, queue.owner, held-record.write, actor.none |
| `join` | any | any | config.owner, db.owner |
| `relocate` | any | any | config.owner, db.owner |
| `_sync-wait` | any | any | db.owner |
| `Shared.before` | any | any | db.owner |
| `command start` | any | cr | status.row, meta.base, actor.none |
| `bd` | any | any | raw.door |

`command start` is `settle_landed`, which runs before every `CR_AWARE` command, `health`, `queue`, `position`, `console`, `check` and `mine` included: it finishes a landing (`finish_landing`: the landing move and the stacked CRs' `base`), not on a board without the current model marker (`model_value`), where reads stay open and write nothing. `Shared.before` and `_sync-wait` are the other writers that are not parser verbs. `field export`, `field discard` and `ruling check-replaces` have no cells: they write no record (`check-replaces` reads, but it is not in `READS`).

## After the fact (look after)

- "Landed since your last look": derived from landed CRs and one marker per person; each row shows the outcome and how to see it. **Planned** (nixes-cop95).
- `agents board cr diff <id>` shows a landed CR's range (the landing is a fast-forward, so the range stays intact on the target) and `review open <id>` opens a landed CR with that range as upstream; edits there become a follow-up CR. **Planned** (nixes-cop95): today `review open` takes a `passed` look-before CR.
- No landing ratification task and no separate confirmation question: the user ratifies choice records.

## Risk tiers

- Reversible work proceeds: the agent takes the safe default, records each choice that had a realistic alternative, and the user judges it afterwards.
- One-way doors and scope changes are asked up front and hold only the affected item.
- Landing on the local target is reversible. The user's gate sits on the irreversible actions: push, install or rebuild, a migration run on real data, messages to outside parties. A CR gets `look` `before` only with a named one-way or scope reason.

## Scenarios the tests cover

1. Bug filed → CR with one item → claim, commit, close, handover → review passes → look after lands.
2. Look before; the user Returns with two findings → two items → fixed, closed, re-review → Accept → land.
3. Item B waits on a question while A is ready → A done; handover refuses on B → unclaim, or the planner moves B; when planning closes the ruling as planned, ready again.
4. A no-commit probe is a task; the question waits on it; the CR with only the waiting item is not ready; the probe runs on its own. A probe that commits is an item and makes the CR ready.
5. CR2 needs CR1's code: waits on CR1, met by stacking on passed CR1 or its landing.
6. Someday work → deferred; "remind me Monday" → deferred with revisit Monday, shown as due then, nothing starts by itself.
7. A user step ("rotate the API key" before deploy) → a human gate the CR waits on; it shows in the user's view.
8. A worker crashes holding a CR → a deciding session takes the dead session's hold; a CR whose items are all closed is ready for handover.
9. Two sessions claim at once → compare-and-set lets one win.
10. A planner adds an item mid-work → handover refuses until the holder closes it or a deciding session moves it; nothing is closed unseen.
11. A duplicate: `link <dup> <original> --type relates-to`, then `close <dup> --outcome dropped --reason "duplicate of <original>: …"`; the original stays open and the link stays.

## Operation notes

### Setup and settings

`agents board setup` owns a board's settings: `TRAVELLING_CONFIG` (database, travels by sync), `LOCAL_CONFIG` (`.beads/config.yaml`, per clone), `SERVER_CONFIG` and `SHARED_CONFIG` in `bin/board`. It creates a server-mode board with `bd init --server --stealth` (`--embedded` opts out: embedded mode takes one writer at a time) or brings an existing one to these values, printing each old and new value; `--server` converts an embedded board in place (bd backup and restore, the old folder kept). It reports `.git/info/exclude` lines matching tracked files. `no-git-ops` stays `true`, as stealth init sets it: bd 1.3's stealth handling keys on it (with `false`, `bd doctor --fix` writes a project `.gitignore`). A setup that changes `look` or `view` prints, under the `old -> new` line, the open CRs keeping their own value. Item settings (`create --no-commit|--look|--view`, `update --no-commit|--look|--view`; `""` drops one) are metadata; `update` changes them only from a lead, solo or person, on an unheld record. A look or view equal to the project default is refused.

### bd and the hooks

`bin/board` is the agents' only board interface: views and hand-offs from one snapshot sized to the command (`Board.load`), and `agents board bd <args>` for every other bd command. `agents board bd` runs bd with `--readonly`: reads pass and bd refuses a write, then board prints bd's error and the board command that does it, and the raw rule. `--readonly` does not catch every write: on a server-mode board `import`, `rename`, `config set` and `dolt remote add`/`dolt set` pass (probed on bd 1.3.2; no further guard, by decision). `agents board bd --raw --yes <args>` runs bd without it, for a write no board command does or one the user authorized; `--raw` alone prints that rule, runs nothing and exits 2. `show`, `view` and comment listings are refused naming `agents board show`. It starts a stopped server on server-mode boards (bd's auto-start is off), runs bd as a child, never an exec (to retry `foreign key conflicts`, start the sync window and add its warning), and takes the actor from `agents session actor`. Every bd call sets `BD_NO_REMOTE_ADOPT=1`. Board-made commits and branch moves (`commit-tree`, `rebase --onto`/`--continue`, `merge --ff-only`) run no git hooks: what a hook enforces belongs in `custom.board.checks`.

Hooks: bd-guard denies bare `bd` and sets Claude subagents' own actors (without it they act as their session, so in-session reviews by them are not independent); session-register keeps workers from registering; the session-start hook starts the server before `bd prime` and refreshes the session's registered process and project (`agents session alive`); session-activity records activity as file mtimes (SubagentStart and a worker's tool calls touch the worker's marker, SubagentStop deletes it, the session's own tool calls touch `<session>.active`). Probed on Codex 0.166: SubagentStart fires on first spawn, the matcher-less PreToolUse group fires for shell and apply_patch calls, a worker's payload `session_id` is its parent's and its `agent_id` equals its `CODEX_THREAD_ID`, which the worker actor's suffix comes from.

### Beads features the board avoids (bd 1.3.1; re-check before adopting)

- `external:` dependencies never block: no production code calls `ResolveExternalProjectPath`, so upstream waits use a local human gate.
- `bd human respond`/`dismiss` close on answer; questions close once their ruling is planned.
- `bd close --suggest-next` lists only what one close unblocked; next steps follow priority and decision clusters.
- Claim leases, `bd heartbeat` and `bd reclaim`: nothing reads the 5-minute leases, and `bd reclaim` would free every held item.

`bd lint` checks `decision` descriptions for the record sections (built-in Rationale and Alternatives Considered; configured Question, Decision, Rule owner). The Decide protocol owns the record lifecycle; closed records keep their shape (board-migrate Invariants).

### Sessions

`agents session activate` and `alive` record `project`, the resolved folder of the session's board, found through `agents board bd where` (a git worktree names the main checkout's); a failed lookup records none and the command still succeeds. `position` lists a session when it holds items here, or when its project is this board's and its last registration or activity is within 24 hours. It marks holders GONE when their session's process ended (Claude; Codex records no process: the nearest `codex` ancestor can be a shared app-server or a per-command sandbox helper) or their registration was pruned. `session activate` prunes registrations idle 7 days whose process ended or that record none, appending their actors to the state dir's `ended` file (`agents session ended`); a hold of an ended actor with no registration shows GONE. Registration writes and the prune hold one `lockf` lock (`$state/.lock`, freed when its holder dies; the prune re-reads each registration under it and skips when the lock is busy); `list` is a pure read and prints a registration it cannot parse as `{"unreadable": <file>}`. Idle derives from the holder's last tool call, else the record's update. `agents board mine` marks holds of the caller's workers without a marker WORKER STOPPED once the session's `.active` exists. `claim`, `handover`, `return`, `wait`, `mine` and `queue` print a capacity line for dispatching sessions below the worker cap with ready work. A role sets the authority (`ROLE_KINDS`); the stored pulls set the work: `session activate` stores the role's preset (lead: plan; solo, autopilot: all three; agent: none), `--pulls` sets them, `--without` drops some, and a later activate without either keeps the stored ones. `agents session find <id>` resolves an id by file names alone: the actor is the last 8 characters of the session id, which Claude, Codex and the scratch folder carry.

### Shared boards

Only board's own mark, `.beads/board-shared.json`, makes a board shared, so a board without it costs no bd call and a stray Dolt remote shares nothing. `share` (two steps: it says what goes out, `--yes` sends) and `join` write it after the first push or the clone; a failed join removes what it made. `route`, `send` and `create --for` move items between queues and inboxes (`for:` labels; every send stamps `sent_at`, and an inbox item's row and `waitingSince` count from it). `relocate` flattens to a fresh repository and leaves a moved note (`custom.board.moved`) that `Shared.check_moved` reads after each pull, so stale clones refuse writes until `join` rejoins them. `Shared` in `bin/board` owns sync: `before` pulls, `after` opens the window, a detached `board _sync-wait` commits and syncs, and `.beads/board-sync/` holds its locks, stamps and reported problem. `AGENT_BOARD_SYNC_SECONDS` shortens the window for tests. `bin/test-shared-board.py` runs the behaviour through real clones and a local bare remote, which the build sandbox cannot: the change-request gate (`board-checks.sh`) runs it. `Board.listed` applies the queue filter and `parent_move_refusal` refuses a reparenting by a session that may not move items (and of a CR or its held items). `create_item` makes plain child ids on every board.

### Field exports, limits and comments

`agents board field export|apply|discard` replaces rewriting a field from memory: export writes `<scratch>/fields/<id>/<field>.md` and one hidden `.base.json` per item with each field's hash; `apply` makes one `bd update` per item with its changed fields and removes the files. An item is refused whole (files kept, exit 2) when an edited field changed on the board since its export or an edited file is empty. Export never overwrites an export edited since and not applied. `create` and `field apply` refuse a work record whose description, design, acceptance or notes is over 2000 characters (the refusal says how to cut); an update that shrinks an over-limit field, or only replaces paths in it, passes; decision records are not limited. Comments a session writes are held to the same 2000; the board's own packets are exempt (`--board-packet`). Plain `show` prints the newest 5 comments cut at 2000 characters; `--comments` prints them whole. Refused calls of the write-by-flags verbs exit 2 (`REFUSAL_EXIT_2`).

### Queue, watch and ruling verbs

`agents board watch` blocks until a bare `claim` would have a candidate (polls every 60 s, exits 3 at the timeout and 1 when the session's registration is gone) and claims nothing; run it in the shell tool's background mode. `create --type decision` (also a plan holding a decision) and `ruling revise` hold items up by waits, however made: `--holds <id>[,<id>…]` or a plan's edges (`--deps` refuses the word `blocks`); a decision with none needs `--holds none`. `ruling release <ids> --closes <question>=<record>` releases the decided rulings, then closes the answered questions in dependency order; any other open blocker leaves the question open (exit 1). `ruling record --replaces` supersedes the old ruling when the new one comes into force. `position` and `holders` print `holds a/b` (`a` stops at a milestone, `b` counts everything downstream). The unlock rank in the CR queue uses the complete dependency graph even in a scoped queue.

### Review and landing

`agents board review open <cr>` opens a `passed` CR for the user in its own worktree (`<main>/.worktrees/<id>`) on its own branch and prints the folder to open. It refuses (lead, solo or person only) a CR that is not `passed`, one held by an agent session, a worktree mid a rebase, merge, cherry-pick, revert or bisect, with uncommitted changes, or off its branch. It moves nothing in git: no detach, no reset. It records the tip in `opened_tip` and, for a new review, the user's look as `user_seen_tip` and `user_seen_base_tip`; a validated `cr land --tip --base` also records the seen tip. Open makes the remote `board` when missing (url the main checkout, `pushurl` `no-push://the-board-lands-requests`, which no helper serves, so any push fails; fetch `+refs/heads/*:refs/remotes/board/*`) and sets the branch's upstream to `board/<base branch>` with `branch.<name>.rebase=false` and `mergeOptions=--ff-only`, so a plain Pull fast-forwards or fails and never rewrites reviewed commits. The commits show as Outgoing, the user's edits as Changes, a moved base as Incoming. The board fetches `board` again whenever it moves a base and re-points a stacked review's upstream when its base lands. Opening one already open changes nothing it holds. Open does not refresh: Accept brings in a moved base. From Open until the user's Accept or Return the CR is held: `claim`, `handover` and `cr refresh` refuse it, and the queue offers no review or refresh for it.

The user's edits are their commits after `opened_tip` plus the uncommitted changes (tracked and new, not ignored files, through a throwaway index: `review_edits_tree`). The opened tip must still be an ancestor of the branch, and `opened..tip` must hold no merge commit and no commit of the base branch; otherwise `cr land`, `return`, `cr edits` and `show` refuse with the way back (`git -C <worktree> reset --hard <opened sha>`, which drops the user's commits after it, so they re-apply them). `return` and `cr land` end an unedited review (`opened_tip` cleared) and refuse one holding edits, naming the `cr edits --commit` line.

`agents board cr edits <cr> --tip <sha> [--commit -m <msg> [--gate '<cmd>' | --no-gate '<reason>' | --checks]]`: without `--commit` it prints the edits; `--commit` records every commit after the opened tip in the CR's `review_edits` metadata, commits the uncommitted changes as one more (author the repository's `user.name`/`user.email`, committer the session), moves the branch by compare-and-swap (a branch that moved meanwhile commits nothing and unrecords), and clears `opened_tip` before any check or rebase that can stop. Every gate first rebases onto the base (`checked_sync`). `--gate` stores a targeted check for that tip (`check_kind=targeted`), `--no-gate` stores `check_kind=none` with the reason, `--checks` (default) a full check; `handover` and `cr refresh` take the same option. A recorded edit commit stays covered by the review (`is_replay`: replaying the recorded change onto the commit's parent by 3-way merge gives exactly its tree). A conflict on one is no special path: the CR stays an ordinary CR mid its own board rebase, the deciding session merges with the user, and the user's confirmation is `cr edits <cr> --merged <commit>`, which replaces the pre-rebase entry in `review_edits`. A CR with no stored review whose own commits are all recorded edit commits is reviewed (`review_current`).

A CR whose worktree is mid a rebase, merge, cherry-pick, revert or bisect the board did not start (marker files in the worktree's git dir; a rebase is the board's when its `onto` equals the CR's `rebase_onto`) leaves the claim queue, `claim` refuses it and `check` lists it as `cr-git-state`. A rebase the board started and stopped on a conflict stays claimable: `sync_branch` refuses while unmerged paths remain and otherwise runs `git rebase --continue` itself.

### Console and refusals

`agents board console` prints the console pane's JSON from one snapshot (health counts, `mine`, `position` sessions and holds, `sync` and `queueLine`). Each `crs[]` row's `problems` lists what holds the CR up with the step that clears it, `{kind, text, next: {action, command?, paths?}}` (`cr_problems`): `setup-failed`, `git-state`, `check`, `waits`, `land-blocked`. A refusal (`BoardError`) carries its steps in the same shape; `report_error` prints the reason, then one `next: <step>` line per step, on stderr after flushing stdout. `health`, `position`, `related` and `check` take `--json` (every row). The console pane reads review state from the board's JSON only (`review: {opened, edited, files}`); edits made after the board's last read are caught by the board's own refusal of `land` and `return`. More: [console.md](../console.md).

Every multi-verb tool answers `help` (each verb with one example) and prints the same for a bare call, exit 0: `board`, `protocol`, `session` and `scratch`. `protocol help` and the stdin forms come from the frozen `base.Verb` records and `protocol_engine/schema.py` (see [protocol-engine.md](../protocol-engine.md)). An unknown `board` verb that the installed bd knows fails with exit 2 and `board: no verb 'ready'; run: agents board bd ready <args>`; nothing runs or forwards.
