# Shared agent definitions

`definitions/` is the source of truth for custom agent roles. Its Markdown
files use Claude Code-compatible agent frontmatter as a practical superset;
the prompt body and canonical lowercase role name are shared by both tools.
Keep prompt wording provider-neutral; tool-specific settings belong in
frontmatter adapter fields.

`skills/` is the source and template tree for shared skills. Markdown files may
include another skills-root-relative Markdown file with a marker on its own
line:

```md
<!-- @include shared/decision-protocol.md -->
```

The build expands includes recursively into complete standalone skill files.
Agent definitions take the same markers, resolved against `skills/`
(`review` and `deep-review` share `shared/review-method.md`; `verify` takes
`shared/reuse-check.md`; every file-writing agent takes the report cap in
`shared/report.md`).
Missing targets, escaping paths, cycles, frontmatter markers, and malformed or
unresolved markers fail validation.

Keep role and authority limits before each skill's workflow; place whole-file
shared references after them and link
them from the relevant phases. Includes
retain their heading levels; use one H1 and flat reference sections.

The global instructions describe capabilities and responsibilities rather than
a particular tool's command syntax.

Load shared content per reader; every file in `skills/shared/` stays readable
on its own:

- Include content a skill acts on in every run; the rendered skill carries it,
  so reloading the skill after compaction restores it.
- Reference `$HOME/.agents/skills/shared/<file>` by path for readers without
  includes (agent definitions, `AGENTS.md`) and for conditional or
  single-section needs.
- Links only navigate loaded content: in-file anchors for included files,
  `../shared/` links for files the skill reads by path. Validation rejects
  other links and unresolved anchors.
- Role protocol files (`skills/role/protocols/`) are read by
  `$HOME/.agents/skills/role/protocols/<name>.md` path; they read shared
  files by path and link them as `../../shared/`. Skills name protocol paths
  in code spans instead of linking them.

Nix generates the Claude Code and Codex representations into the store, and
Home Manager links them at activation. It also renders the shared skill tree
into the store; generated files do not live in Git. Skill changes therefore
require `darwin-rebuild switch` before they become active.
Hooks, the `bin/` scripts (`board`, `session-lead-mode`), the hook
registrations and the global instructions (`AGENTS.md`) are linked out of
store to the working tree, so their edits are live at once; rendered skills,
agent definitions and newly added links change only at the switch.
After a switch that changes Codex hook entries, re-trust the changed hooks in
Codex; untrusted hooks do not run.

To inspect generated output manually:

```sh
output_dir=$(mktemp -d)
python3 home/patrick/agents/bin/generate-agent-configs.py \
  --target codex \
  --output "$output_dir"

python3 home/patrick/agents/bin/expand-skills.py \
  --source home/patrick/agents/skills \
  --output "$output_dir/skills"
```

To validate skills, generated formats, policies and hooks, use Python with
PyYAML (the Nix build provides it):

```sh
python3 home/patrick/agents/bin/test-agent-configs.py \
  home/patrick/agents
```

The generator translates portable fields to both formats. Each definition
declares its Codex model and sandbox; Claude-specific models, tools, and hooks
remain optional adapter fields. New roles therefore cannot accidentally
inherit write access or an unintended Codex model.

`effort` is the shared reasoning level; optional `claude-effort` and
`codex-effort` override it for one tool. The resolved value is validated per
tool, since only Codex accepts `ultra`.

Validation covers source instruction/description preservation, per-tool effort
resolution, generated permissions, and local hooks. Live runtime enforcement requires separate checks.

Each role's `codex-model` field owns its model selection; validation requires
an explicit, nonempty model without pinning a particular selection.

Scout and explore return discovery results in their responses. Other specialists
can write assigned artifacts directly. Native configurations provide file-write
tools and workspace access; role instructions confine edits to assigned
artifacts and temporary probes. Implementation changes belong to implementation
roles, except reported fixes an assessor is certain are the only realistic,
clean option. Claude's investigation shell guard is a deny-list; Codex uses its
native sandbox setting. Role instructions define assigned write zones.

Workflow owners:

- [Role](skills/role/SKILL.md): the user-invoked session entry. It registers
  the session's role (lead, agent with pulls, solo, autopilot) through
  `bin/session-lead-mode` and owns the role-to-protocol mapping.
- [Protocols](skills/role/protocols/): [decide](skills/role/protocols/decide.md)
  (rounds, release, acceptance of designs and user-judged outcomes),
  [plan](skills/role/protocols/plan.md) (released rulings into work, framing,
  cutting, briefing, dispatch, integration),
  [work](skills/role/protocols/work.md) (one design or implementation item),
  [review](skills/role/protocols/review.md) (independent review, review policy,
  evidence and gates) and
  [unattended](skills/role/protocols/unattended.md) (autopilot authority and
  parking). Sessions read them by path; compaction recovery names them again.
- [Board core](skills/shared/board-core.md) and
  [board coordination](skills/shared/board-coordination.md): board model, holds,
  routing, record shapes, epics, milestones and rulings; [board-migrate](skills/board-migrate/SKILL.md)
  moves a project from any starting state onto it, deriving the work from the gap to the target.
- Challenge skills: [step-back](skills/step-back/SKILL.md),
  [challenge-rulings](skills/challenge-rulings/SKILL.md) and
  [ground](skills/ground/SKILL.md) are model-invocable; the Check step of
  [asking](skills/shared/asking.md) invokes them (in a `protocol` round, in
  the engine's sequence);
  [ask-advisor](skills/ask-advisor/SKILL.md),
  [question-me](skills/question-me/SKILL.md),
  [release-round](skills/release-round/SKILL.md),
  [start-round](skills/start-round/SKILL.md),
  [round-intake](skills/round-intake/SKILL.md) (a list you hand over) and
  [explain](skills/explain/SKILL.md) are user-invoked only. Their
  argument names the focus and follow-ups.
- [Retro](skills/retro/SKILL.md): rule proposals and regression cases.
- [Skill authoring](skills/skill-authoring/SKILL.md): invocation policy,
  trigger descriptions, frontmatter and style for skills, definitions and
  instructions; loaded while writing, user-invoked to review.

`board setup` ([beads-setup](skills/shared/beads-setup.md#beads-setup)) owns a board's settings:
`TRAVELLING_CONFIG` (database, travels by sync), `LOCAL_CONFIG` (`.beads/config.yaml`, per clone),
`SERVER_CONFIG` and `SHARED_CONFIG` in `bin/board`. It creates a server-mode board with `bd init
--server --stealth` (`--embedded` opts out: embedded mode takes one writer at a time) or brings an
existing one to these values, printing each old and new value; `--server` converts an embedded board
in place (`to_server`: bd backup and restore, the old folder kept). It reports `.git/info/exclude`
lines matching tracked files; share and join apply the same lists. `no-git-ops` stays `true`, as stealth init sets it: bd 1.3's stealth handling keys on it
(with `false`, `bd doctor --fix` writes a project `.gitignore`).

Shared boards ([beads-setup](skills/shared/beads-setup.md#shared-boards), queues in
[Routing](skills/shared/board-core.md#routing)): only board's own mark, `.beads/board-shared.json`,
makes a board shared, so a board without it costs no bd call and a stray Dolt remote shares nothing.
`board share` (two steps: it says what goes out, `--yes` sends) and `board join` write it after the
first push or the clone; a failed join removes what it made. Every bd call sets `BD_NO_REMOTE_ADOPT=1`.
`board route`, `board send` and `board create --for` move items between queues and inboxes (`for:`
labels; every send stamps `sent_at` metadata, and an inbox item's row and `waitingSince` count from
it); `board move` flattens to a fresh repository, leaving a moved note (`custom.board.moved`) on
the old board that `Shared.check_moved` reads after each pull, so stale clones refuse writes until
`board join` rejoins them. `Shared` in `bin/board` owns sync: `before` pulls,
`after` opens the window, a detached `board _sync-wait` commits and syncs, and `.beads/board-sync/`
holds its locks, stamps and reported problem. On these boards `board bd` runs bd as a child instead
of exec'ing it, to retry `foreign key conflicts` and start the wait. `Board.listed` applies the queue
filter, `queue_guard` refuses moves and cross-queue claims, and `rewritten_create` makes plain child
ids on every board. `board console` adds `sync` (the problem line) and `queueLine` (other queues,
unrouted with the count for you, blocking yours), both shown in the pane.
`AGENT_BOARD_SYNC_SECONDS` shortens the window for tests. `bin/test-shared-board.py` runs the
behaviour through real clones and a local bare remote; the validator's `validate_shared_board` holds
the fake-bd checks the build sandbox can run.

`bin/board` (installed as `$HOME/.agents/bin/board`, not on `PATH`) is the
agents' only board interface: views and hand-offs from one snapshot sized to
the command (`Board.load`: a `bd list` of the non-closed items plus one
`bd show` of the held items' comments for status views, `bd export` for
`related`, `check` and the writes that read closed items, a `bd show` of only
the named items for `board show`), and `board bd <args>` for every other bd
command (`bd edit`, which blocks on an editor, and `--readonly` are refused with
the way on named in one line; a plain `bd show`, `view` or comment listing by
ids runs `board show`, and type `question` runs as `decision`, each with a
stderr note, r9-q35). It starts a stopped
server on server-mode boards (bd's auto-start is off) and takes the actor from
`session-lead-mode actor`, the owner of the session identity
(`CODEX_SESSION_ID`/`CODEX_THREAD_ID`, else `CLAUDE_CODE_SESSION_ID`). Hooks
add: bd-guard denies bare `bd` and sets Claude subagents' own actors (without
it they act as their session, so in-session reviews by them are not
independent); session-register keeps workers from registering; the
session-start hook starts the server before `bd prime`, and on Claude
refreshes the session's registered process and project (`session-lead-mode alive`);
session-activity records activity as file mtimes: SubagentStart and a
worker's tool calls create or touch the worker's marker, SubagentStop deletes
it, and the session's own tool calls touch `<session>.active`. Probed on
Codex 0.166 (2026-10-31): SubagentStart fires on first spawn, the matcher-less
PreToolUse group fires for shell and apply_patch calls, a worker's payload
`session_id` is its parent's, and its `agent_id` equals its
`CODEX_THREAD_ID`, which the worker actor's suffix comes from.
`session-lead-mode activate` and `alive` record `project`, the resolved (realpath) folder of the
session's board, found through `board bd where` (its first line names the `.beads`; a git
worktree names the main checkout's); a failed lookup records none and the command still
succeeds, and `alive` corrects it at every Claude session start. `board position` lists a
session when it holds items here, or when its project is this board's and the later of its
registration and last activity is within 24 hours (a session with no project and no holds is
not listed; a project without a board has no session list); the per-kind session counts, the
pane and `board console` read that one list.
`board position` marks holders GONE when their session's process ended
(Claude; Codex records no process: the nearest `codex` ancestor can be a
shared app-server or a per-command sandbox helper), derives idle from the
holder's last tool call (else the item's update) and shows
`workers <active>/<cap>`. `board mine` marks holds of the caller's workers
without a marker WORKER STOPPED once the session's `.active` exists (only the
owner knows whether it continues the worker). `claim`, `handover`, `return`,
`block`, `mine` and `queue` print a capacity line for dispatching sessions
below the worker cap with ready work. The cap is 3 unless
`session-lead-mode activate --workers <n>` sets the session's own, which a
later role switch keeps; a non-lead session row's select in the console pane
sets it with no model turn (`set-workers`); Codex's thread limits lower it.
The cap also limits holds (r13-q71): `board claim` refuses a task, bug, design or spike that would take
the claiming actor past it (counted per actor: in-progress work items only, not decisions or in-review
items) unless `--force "<reason>"`; a takeover of a work item held in progress (the session's own worker, or
`board take`) counts the same way and takes `--force` past the cap (r16-q93); position, mine, claim and check flag a forced hold `FORCED: <reason>`
(item metadata `forced_hold_by`/`forced_hold`, shown while that actor holds it). A held work item
with no update (fields, notes, comments) for an hour is `STALE` in position, mine, check and the
holder's claim output (r13-q76); nothing is refused. Registration takes `--pulls` for every role;
lead, solo and agent are presets, and a session's pulls add to its preset for bare claims, handles
and capacity (r13-q61). `board create` and `board bd create|update` refuse a task, bug, design or
spike whose description, design, acceptance or notes is over 2000 characters (naming field and size;
`--append-notes` counts the old notes plus the appended text); an update that shrinks an over-limit field
passes, and decision records are not limited (r13-q74, r16-q96). Comments a session writes are held to
the same 2000 (`board bd comments add` by text, `-f` or stdin, `board handover` evidence, `board return`
findings, `board block` reasons); the board's own packets are exempt: the protocol engine's autopilot
park adds its packet with `--board-packet`, which `board bd` strips before bd (r16-q87). Plain
`board show` prints the item's newest 5 comments, each cut at 2000 characters with a pointer to
`board show <id> --comments`, which prints them whole (r16-q88, q89); it prints item metadata
`deep_review=<harm>` as `deep-review: <harm>` (r16-q94).
`board check` encodes the board-core
conventions mechanically; change both in the same change, so drifted boards
surface in `board health` and move through `/board-migrate`.
`health`, `mine`, `position` and `related` take `--json` (every row; `related`
keeps `--limit` per list) for the engine and the console; text output stays
unchanged. `board console` prints the console pane's JSON (health counts,
`mine` items, `position` sessions and holds with their marks) from one
snapshot.
`board release <ids> --closes <question>=<record>[,<record>]` releases the
decided rulings (already released ones count as done, so a rerun retries only
a failed revise supersede), then closes the answered questions in dependency
order with "Answered by released <record>", forcing only past rulings of the
call, questions it closed before and released rulings; any other open blocker
leaves the question open (exit 1). A released blocker holds neither a decided
record nor an answered question, only the open items it changes.
`board position` and `board holders` print `holds a/b`: `a` counts a milestone as
one item and stops there, which tells a milestone's members apart; `b` counts
everything downstream. Lists sort by `a`, then `b`; JSON gives `holds` and `holdsAll`.
`session-lead-mode state-dir` names the state dir; the engine and the console
ask it instead of restating the location.

`bin/protocol` (installed as `$HOME/.agents/bin/protocol`) is the protocol
engine of deciding sessions: it owns each session's protocol state in
`<state dir>/<session>.protocol/` (with an append-only `history.jsonl`) and
prints the next step, one call per step; `run_cli()` (in `cli.py`) is the same
CLI as a function, which the tests call in-process. `bin/protocol` is a thin
entry; the engine is the `bin/protocol_engine/` package beside it, one module
per concern, layered so imports never cycle (`round.py` and `release.py`
register their protocols in `engine.PROTOCOLS`). `words.py` holds every text
the engine prints for a model or the person (step texts, notes, report formats,
headlines, log lines), shaped like the console's `hooks/words.ts`: constants
and functions taking the values they interpolate, imported by the modules that
decide what to say; error and refusal messages and the CLI help stay where
they are raised or defined. Its protocols are `round` (the decide protocol's
Round from Collect to Record) and `release` (its Release).
A question whose Related outcome supersedes a decided record closes it at Record
(`board supersede`: waiting items, settled items and a pending revision move to
the new record; the dialog names it by id and title); a released record is
revised and replaced at release. Related may mark any decided record this way,
a hit or not, by naming its id under `outcomes` (only a recorded ruling; a
record another live session holds is refused). `board record` writes the record and no comment copies of
the replaced text; the board's history (`board bd history`) keeps earlier versions (r16-q95).
A round:

- Collect classifies every pasted point and the board items in the round's
  scope; `start round --discussion` takes the pasted points alone, and
  `--no-board <dir>` (required without a board) writes the records as files
  in `<dir>` with no board reads or writes. Items another live session holds
  stay out, named in one line; a gone session's hold is offered, marked.
  `start round <ids>` names the open items to look at first (an id that is closed,
  held by another live session or no item a round offers is refused by name);
  `--topic '<title>: <summary>'` starts a topic round and `--proposal <n>` starts
  row n of the stored proposal (see `protocol next`);
  the engine keeps every open item either way, so a round can classify an id it
  did not print. The open-item list prints whole, grouped under a heading per view
  and status, the first time between compactions that `protocol next` or a
  round's Collect needs it; after that Collect prints the named ids, the counts
  per kind and the command that lists everything (`board health --items
  <COLLECT_VIEWS>`, plus `board position` for ready milestones and finished
  epics), and a bare round is told to list before it selects. A restart, a
  Related step and the pass report format name that command where a round's scope
  widens.
- Select claims the selected items (a gone session's hold through `board
  take`); Stage requires a plain round title and
  summary and, per question, a plain title, `problem` (what is decided and why
  now), 2-4 options each with
  `for` and `against`, the recommended option and its strength under decision-protocol.md Recommendation strength
  (a lean names its cause, a strong one carries the five-criterion checklist).
  The Stage text states the lengths to keep to (round `summary` 240, `title` 60, question
  `text` 160, `header` 12, option `description` 150; a report is refused only
  above text 240, title 75, description 200, or summary 240 and header 12, naming the
  measured length; all built from the
  engine's constants) and who reads each field; every option of a code, API, naming or
  shape choice carries an `example`, printed as a code block under its For/Against before the
  dialog, never in it; a `preview` is
  refused with a pointer to `example`, so a question staged with one waits until a pass renames
  it (r10-q37, q38; no engine check that examples are present, r10-q39). `cases` (the cases that must and must not work), `premises`
  (what it rests on), `rulings` (the lead's own rulings, each with a release's four fields) and `note`
  are optional and print only when present (r27-q123); an engine-built approval or cap question
  carries no parts. The round
  description may carry one `overview` line (at most 240 characters). A refused
  Stage report, or a new question in a pass report, lists every error at once;
  an update that touches `problem`, `cases`, `premises`, `options` or `rulings` repeats the checks for
  them (`note` is presentation: it re-issues the batch without a loop).
- The text before a dialog (r24-q99, r30-q141) is rendered by the engine into the batch's
  `notice` (`show --json`): per question, numbered like the dialog, its
  title and its parts in order, a blank line between parts: `Problem:`, `Cases:`,
  the items a rule question settles one line each (`Settles:`), `Premises:`, the options,
  the ideas the options pass dropped, the own rulings, `Note:`; the round's `overview` comes before the first
  block once. The options print as layered plain text: the recommended option first
  as `Recommended: <label>` with its reason on the next line (`Lean, your call: …`,
  `Lean, unverified: …`, or `Strong: ` and why the other options fail), then a `+` line with
  its for and a `-` line with its against, then every other option the same way
  under its label; no trailing recommendation line. A dropped idea (the options
  pass) is one `Dropped: <idea> - <why>` line each under the options. An own ruling is a block
  (`My ruling:`, `Why:`, `Instead:`, `Why not:`) without its evidence, which only the
  record keeps (`## Own rulings` has all five fields; `why`: what the ruling meets and why no
  material trade-off remains). The Stage text states one
  rule for every printed part, with no length check on them: say what is decided and
  what each option means for the person (what they would see, what it costs), each
  thing once, in plain words; how it was found (sources, measurements beyond the
  deciding number, who said what) and how it gets built go to the record. Every dialog has its questions' full text
  above it, re-asks and a reopened batch included; a question that changed since the
  person saw it (a snapshot per question, taken when a dialog for the batch comes back)
  names what moved, `(changed: options, premises)`. After a dialog the engine writes the
  line the person reads: per question its number, title and outcome, a pick marked
  `(recommended)` or `(not recommended)`, and a skip, a typed reply or Think more saying
  so. The console's own dialog sends that line to the model as its prompt, and the model's turn end runs a pending pass; the
  dialog hook records the answers and wakes the model itself right away, so a console reload while the dialog is open loses
  no wake-up, and only a decline Esc kept from saving is recorded and sent once the dialog closed. A release
  approval prints its corrections (revised and dropped records), the board check
  (supersedes, closes, the other hit rows) and every own ruling in the same layout; a
  typed or pressed approval opens no dialog and prints nothing. In Claude
  sessions the console prints the notice, opens the dialog and records the answers
  with no model turn (r29-q138, r32-q149): when a batch is issued the lead writes
  nothing about the questions and ends its turn, and at the turn's end (not aborted,
  not a subagent's) the console runs `/console-questions`, whose hook prints the
  notice (its output draws whole between turns; the model reads that one copy, and an
  empty or repeated notice prints a short line) and opens the dialog. The notice goes out by
  where the person is, the origin of their latest message (r14-q81): at the terminal the full
  questions are a row placed in the chat (`$.ui.place`, one id per batch, drawn as Markdown
  by the `Placed` render hook from text the console stores) that the model never reads, and
  the command prints the model a short list (number, title, recommendation, what changed);
  from the phone (the Remote Control bridge), before any message of the person, or on any
  other surface the full text prints. The row is placed one tick (1 ms) after the command
  answers, since at 0 ms it lands above the command line; where nothing draws the row a
  notice carries the text. Placed rows do not come back on `--resume`;
  `/console-questions` draws them again. The one-tick wait retires when the host offers a
  hook after a command's output row. The host's
  `$.ui.ask` takes labels only, so it asks a placeholder and the console's
  AskUserQuestion hook swaps it for the issued batch (never drawing the placeholder).
  The host credits a `$` call to its hook only while that hook runs and counts one it takes later as the whole
  console's, skipping every console hook (Claude Code 2.1.319); calls and the hook's return cross unordered. So the
  `/console-questions` hook returns only once the swap took the dialog (2 s at most), and the hook that queues
  `/console-questions` makes one more call before it returns.
  Every outcome then wakes the model with the answers, one line each, as the person's own words (no plugin frame), and the engine's
  text as a note; its turn end runs a pending pass or prints a next batch: the command hook has returned by then, so it
  can neither print the answers through a command nor the next batch. If the swap never ran, the host draws the stand-in
  question (`Open the questions for batch <marker>?`): Not now holds the batch until the person's next message, and a
  close, a timeout or Open the questions sends the lead a one-line message to open the dialog
  with the input `protocol ["show"]` prints, unchanged; so does a run of the command its hook never
  answered, after printing any new text as a notice. A dialog equal to the issued batch but
  without its marker (the input rebuilt by hand) counts as that batch (agents r11-q43). There is no Ask button. At most one dialog per
  batch marker opens until the person sends a new message (a composer or bridge message
  clears it) and none is open. The host queues what the console sends and cannot recall
  it, so a console action is checked where it is delivered: a queued pass run the round has left
  becomes a no-op as its skill expands, the console's own even after the model ran that pass itself (r8-q26: the console
  remembers each pass it queues until its command expands, for up to an hour; an expansion takes a record of the pass
  still pending first, else the oldest, and the model's own Skill calls leave the records alone), and a prompt or dialog outcome for a pass or batch the round has left
  is dropped, each logged with `dropped`; the person's own messages are never dropped.
  The dialog gate still blocks a marked dialog whose notice is not printed yet once,
  telling the lead to end its turn. After a reply the person typed instead of
  picking, the lead answers it as the turn's last text (restating it in one line
  when it could be read more than one way), never in the same turn as the dialog,
  and ends the turn; the console reopens the dialog, also
  when nothing new prints. A dialog result the model reads first (typed text, a note,
  a free reply, a follow-up request) holds every next batch (round `reading`): the
  lead's `step {}` or pass report, a chat answer, an edit or a restart releases it, so
  the typed question goes out again with the rest, a recommendation it changed applied. The dialog options carry neither `for`
  nor `against`.
- A rule question settles several selected items (board ids or pasted
  points) that one answer settles the same way: its `settles` lists their
  keys, and the items need no question of their own (an item is settled once
  and is no other question's `board`/`for`). Merge only when no sensible answer
  would treat them differently (`skills/shared/question-format.md`). Invariant: every selected key is covered by a
  question's `board`, `for` or `settles`; Stage and every update set (a pass
  report, `protocol edit`) is checked once after all its updates, and one that
  leaves a key uncovered is refused as a whole, naming the keys with the other
  errors. A merge or split is such an update set (set `settles`, add the rule
  question, `remove` the instance questions, or the reverse); only unanswered
  questions change. A merge counts as a change for the Base loop. Settled board
  items stay claimed by the round through Record into the release (a deferred
  or removed rule question releases them as any other claim). Record writes one
  record per rule (its own `board`, else a new decision item) and refuses one
  whose `rationale`/`decision` names no settled id; in the same `bd batch` as
  the `relate` links the record inherits the settled items' `blocks` links both
  ways (the open items a settled item blocks wait on the record, the open items
  it waits on block the record; links among the settled items, to the record or
  to an item it is linked to already are left, and a blocks link wins over a
  relate), because a released ruling blocks what it changes until planned. The
  release pre-fills, for each settled board item of a rule record in its set
  (this session's state), the answers row `answered: close` and the close by
  that record, so `board release --closes` closes it; one still open afterwards
  follows the partial-failure path. A `--no-board` round only names the settled
  points in the record file. `show --json` questions carry `settles`.
- Related searches each new draft and needs an outcome per hit.
- Check runs the full set on every question (r18-q120 reverted r13-q64's
  light start), per round: the path pass once (`step-back goal foundations`,
  which also digs into the real problem behind the ask and whether the design
  fixes its root; its changes flow on, and new or reworded drafts are searched
  through Related first), then the options pass once (`step-back options`, r30-q142:
  radically different ways, other mechanisms or owners or removing the need, plus
  the established practice, each argued at its strongest; the report carries
  `explored`, per question a list of `{idea, verdict: kept|dropped, why}` or the
  reason there is no other way, and is refused without it; a
  `confirm-own-rulings` question is skipped; the dropped ideas print under the
  options), then step-back and
  ground until a cycle changes nothing (cap 10 cycles, then a dialog whose
  Continue adds 10; an open round keeps its stored cap), then the refine pair
  once (round-wide `step-back decisions clean overfit mechanics`, then
  `ground assumptions board sources probe`; a change in either reruns the Base
  loop under the cap, and the pair does not repeat), one targeted
  `ground assumptions sources probe <ids>` pass on every lean (evidence or
  preference, r38-q213: redo it from scratch, walk a realistic consumer through
  it and test the deciding fact by a probe or count; a lean still resting on
  values comes back with the value question as its text, options unchanged; no
  loop), then challenge-rulings, last before a batch and again whenever a pass
  changed questions since its last run (its own changes rerun the Base loop,
  the cycle cap bounds the repeats, a run that changes nothing ends it). Once
  the last answer is in, a round (never a release) runs one challenge-rulings
  pass over the answered set before Record (`challenge-rulings (after
  answers)`): a finding is a new question that gets the scoped check below
  before it is asked, and the pass runs again after its answer; a pass that
  changes nothing goes to Record, and a round with nothing answered skips it.
  Base's own lenses
  (consumer, root-fix, bloat, gaps) are in none of the sets. The path, options and refine
  passes run once per round, flagged on the round: a check rebuilt at
  Ask does not repeat them. `protocol restart <ids>` (also several calls
  before the loop settles, ids accumulating) queues scoped reruns on the
  restarted questions, kept apart from the round's flags: a path pass
  `step-back goal foundations <ids>` first, an options pass `step-back options <ids>`
  (the same scoped re-check follows an edit, a released held question and a freed `waitsFor` one), the Base loop round-wide, then
  `step-back decisions clean overfit mechanics <ids>` and
  `ground assumptions board sources probe <ids>` (changes rerun Base once),
  then the lean pass as usual. A pass settles the pending pass only when its run carried the
  pending id: the console stamps `protocol pass` with the id when a run's command and arguments
  match the pending pass's (whitespace collapsed, wording and case exact), whoever started it
  (the engine's own run, a typed or pressed command, a model Skill call); the report of that
  run settles it (Codex: a report of the pending command). Any other
  report is an extra pass: its changes apply and restart the Base loop, the log labels it
  `extra`, and the pending pass still runs (a variant with other arguments, a lens press with
  focus text and a plain `/step-back` while the path pass waits are extra). The engine's lens lists
  (`ALL_LENSES`, `PATH_LENSES`, `OPTIONS_LENSES`, `REFINE_LENSES`) are checked against the
  skills and the console's words.ts. Every pass report keys `checked` by question
  for its scope (r4-q15, q16): what it examined in each this run; an update to a
  question covers it too, as do the options pass's `explored` entries, and a
  `round` note is the only entry an empty scope needs. The step names the scope;
  the engine refuses a gap, naming the missing ids. The scope can change between the
  step and the pass, so the console names it again as a pass starts (r9-q36): `scope`
  (origin `plugin`, changes nothing; stdin `{"command", "pending"?}`, `pending` the stamp
  of a run not recorded yet, else the recorded run's) prints `{"covers", "explored",
  "text"}` as the report check will work it out, `explored` the ids an options pass's
  `explored` covers (else null), and `text` the line, empty when there is nothing to name
  or no pass report is taken (no round open, or a step other than check and ask). A pass kind's first run covers
  every draft and ready question; a rerun of the Base step-back or ground, the lean
  pass, the loop's challenge-rulings and an extra pass (per command) cover the
  questions changed since that kind last ran (another pass's update, an edit, an
  answer, a restart, a release from held, a new question; its own changes do not
  count); a Base ground right after a Base step-back that updated no question, with nothing changed since that ground last ran, is skipped (r18-q121); the path, options and refine passes cover their scoped ids, else every
  question they work on; the challenge after the answers covers the answered set,
  the raised one its ids. An unchanged question resting on a changed one is
  outside a rerun's scope; every rerun still runs. challenge-rulings also re-sends,
  in `verdicts`, the `strongBecause` of each strong question in its scope (or an
  update lowers it to lean or re-sends it) and lists its own rulings in `rulings`,
  each `{question, ruling, why, alternative, fails, evidence, sure}`, validated as
  the release's. Any pass report, also out of sequence or with a batch out,
  updates questions. Edits to title, header,
  strength or its backing alone re-issue the batch; other changes rerun the
  loop. The Claude hand-off names no pass (the console runs it); Codex's names
  the skill to run (its full text, every pass). A step's report format goes
  out once per step kind between compactions, and with every refused report (a
  refused `step` repeats the formats its step offers; the dialog JSON always
  prints). In Claude sessions a
  pass report is accepted only after an observed run of that pass since its
  last report (the console's `pass` record, or a model Skill call). A report
  applies whole: a refused one, at any step, changes nothing, lists every error
  and leaves the run open for the resend. A question too long or
  invalid to ask (only one from before the limits can be) gets a plain message
  naming its error: the model shortens it in a pass of its own (its Skill call
  counts as the observed run); no pass runs automatically. `protocol edit` (stdin `{"updates", "quote"}`) applies a change the
  user asked for: the quote must appear in a message the console relayed in this
  round, one sent before the questions went out too (Codex: verbatim), the updates validate as in
  a pass report, a batch that is out comes back and goes out again with no pass
  (rows read `↻ edit`), except an edit that only adds questions, which leaves it
  out. A new question or a changed recommendation stays out of the batches until
  the scoped check ran on it (at the hand-over below, at once when nothing else
  waits), and a recommendation raised to strong until one challenge-rulings pass
  ran on it (`challenge-rulings (raised <ids>)`); the other questions go out.
  Wording, options, premises, examples and a mark lowered to lean stay free. At
  Record an edit is accepted too: its new questions take the scoped check and are
  asked, and the challenge after the answers runs again. A
  pass report with a refused update holds the round: no batch goes out until the
  failed updates are resent in a pass report. An option's `example` alone is
  presentation for a pass: its change re-issues the batch without rerunning the
  loop, and a question the person already saw shows it as changed.
- Ask issues batches marked `metadata.source = round:<id>:<n>`: the
  recommended option first, labelled "(recommended, strong)" or
  "(recommended, lean)" (a release approval has no mark), a lean's description
  opening with what it rests on ("Unverified: …" or "Your call: …"; the prefix
  does not count toward the description limit). A batch of two or more is numbered (`1. `, `2. `) in
  the dialog text, which keys the answers. The engine renders the text printed
  before the dialog from the question data and owns its format (below); the
  Claude ask text tells the lead to write one short line that questions are coming and end its turn while the
  console prints them and sends the message that opens the dialog (the headline says
  `next: the console to print, then your answers`, or `the console to open the dialog` for an empty
  notice), the Codex ask text carries the text ("Text to show first") for the model to show, then asks. Answers
  count only from the person: `dialog` (relayed by the console), `chat` (the
  model's mapping, accepted when its quote appears in a message the console
  relayed with `say`) and, in Codex sessions only, `model-reported`. A
  dialog answer counts only as an option pick: typed text returns its
  question to the model with the words stored for the quote check (an
  option, a criterion or a request such as explain, which it runs before
  `step` asks again), and a pick's note reaches the model and Record. The console
  reports each stale action it dropped (`dropped`, origin `plugin`; stdin
  `{"kind": "pass", "id"}` or `{"kind": "batch", "marker"}`): the history logs it,
  and a dropped pass run removes that pass's observed run, not a newer run of the
  same command. It logs each `/console-continue` or Continue press (`nudged`, origin
  `plugin`; stdin what it did: `{"pass": <id>}`, `{"batch": <marker>}`, both, `{"step": <step>}`, or `{}`
  when it queued, reopened and woke none of these), with no change to the round.
- Away rounds (r28-q126..q131, r29): the registered role says whether the person can
  answer, in Claude and Codex alike (the engine reads it from the registry entry as
  it reads the tool): `autopilot` means away, `solo` means back. At Ask while away
  there is no batch, dialog or print; the text asks for `settle` (stdin
  `{"settle": {"q1": "act", "q2": "park"}}`, an entry for every question waiting to be
  settled) by the classes of unattended.md, and names `session-lead-mode activate
  solo` for a person who is back. `act` takes the recommendation as the answer
  (origin `away`, which no verb accepts from a caller, so no person origin can pass as
  it): Record then asks `reversal` beside the rationale and rule owner, writes a
  `## Reversal` section, runs `board record … --status needs_ratification`, and the
  record's source line reads `Away round (autopilot took the recommendation; no
  person answered), <date>: "<option>"`. `park` leaves the question an open, unassigned
  decision on the board: an existing item is unclaimed and gets the question's parts
  and recommendation as a comment, a draft is created with them as its text, and
  a question waiting on a parked one parks with it (status `parked`, listed at the
  close). The check cap while away opens no cap dialog: the round's unsettled
  questions park. A batch still out when the role became autopilot is withdrawn at
  the next `step` and its questions settle as away (a cap batch parks them). `--no-board` and
  `start release` (a typed `/release-round` included) are refused under autopilot,
  naming the switch to solo, as is a release or a round without a board already open
  when the role changed. Settled items of an away record are unclaimed, not held for a
  release.
- Stage and any update refuse a `board` id that is no decision: the question goes
  in as a draft and records its own item. They also refuse a second question on a
  `board` id another question of the round holds, since Record would write both
  onto it and keep only the last (agents r11-q41); the second goes in as a draft
  with `for` naming the item. Abandon names the records that stay decided.
- A question recording onto an item that already holds a decision record (a
  ratification, a revision before release, a duplicate or extend hit) revises it in
  place: the Record step prints the record, the report must give `decision`, and the
  new record keeps the old Question and Alternatives (agents r11-q42). The text read
  first is kept on the question, so a rerun after a partial write sees the same.
- Record is safe to run again: each record it creates carries the external ref
  `protocol:<session>:<round>:<question>` (also through `board revise --external-ref`),
  looked up and reused before a create, and the round is saved after each question. A
  cut Record (the console's time limit) reports again with the same report: the
  questions already recorded are skipped, the rest continue. Unknown or unanswered
  ids still fail.
- Record writes the records; closing or abandoning releases the claims the
  round made and did not record (a hold the session had before, such as a
  decided record, stays). A question waits only within its round: `waitsOn` refuses
  a circle, abandoning keeps no held question, and the board owns what a later
  round asks. A question still held on an outside result (`waitsFor`, below) at
  Record is deferred with that text as its reason (logged `deferred`), and the
  questions whose `waitsOn` reaches it with it; the Record step lists them. A
  round that closes while the session holds decided board records closes naming
  the release.

A release runs in the same slot with the next run id (`r5 release · the
session's records`), one run per session, on a board only:

- `start release` takes the decided records this session holds (a worker's
  holds included, read from the board at the start), minus the records a release
  dropped or stopped on a spreading change; those stay out until a round records
  them again or a release releases them. A person's Hold and an abandoned release
  change none of this: a round takes what was held, and a later `start release`
  takes the rest;
  `start release <ids>` takes others; ids another live (or idle) session holds are
  refused, a gone session's hold is taken, unheld records are claimed.
- Re-check and Board check give each changed record a reach: contained, with
  `touches` `own` (only the model's rationale, evidence or a clause the chosen
  option did not state; `file` is the corrected record text) or `decision`
  (unsure counts as decision), or spreads. Contained + decision drops the
  record from the set (its reason shows at the next round's Stage); spreads
  stops the run (nothing releases, the records stay decided and held, the
  close names the round for them). Contained + own keeps the record
  `revised`: the engine runs `board record <id> <file>` (a failure refuses
  the report), a conditional approval lapses, and before the approval one
  scoped `step-back` then one scoped `ground` pass run on the revised ids
  whose `## Decision` text changed (a correction leaving it alone still asks)
  (console-started and observed like a round's passes; Codex is told to run
  the skill), each reporting the re-check's `records` shape (an own change
  rewrites again, a decision change drops, a spread stops). The pair runs
  once per release; a later revision does not re-arm it. The approval
  question and walkthrough name the revised records with their change. The
  board check names supersedes and answered questions; a premise hit drops
  the record.
- Own rulings mark each ruling sure or not. Approval comes from the person
  only: a typed or pressed `/release-round` (the console relays it as `pass
  --origin composer|bridge|press` with command `release-round`, which starts
  the release on the ids leading its arguments, else on the default set, or
  stamps the open one) approves when every ruling is sure
  and the set is unchanged (nothing dropped or revised); otherwise an engine-issued `confirm-own-rulings`
  question goes through the ask machinery (dialog, chat quote, Codex
  `model-reported`; only the Release or Hold pick counts).
- Owner writes checks each owner: written paths exist (repo paths from the
  board root, absolute and `~` as written; installed files as rendered),
  Markdown anchors match a GitHub heading slug or an explicit anchor, pending
  items are open, and the record's `## Rule owner` names each written path.
- Release runs `board release` with the answered closes, then the other
  supersedes; it reads statuses first and reruns only what remains after a
  failure.

When a batch's answers release held questions (every `waitsOn` answered), the
round continues with them instead of recording (so do questions an edit added or
re-recommended): Ask hands over to a scoped
rerun like `restart`'s (a fresh check cycle on their ids, answered questions
untouched; the path pass, the options pass, the Base loop, the refine pair on their ids, the lean
pass and `challenge-rulings`), then the next batch asks them; chains release
batch by batch, and Record runs once, when nothing is left to ask. A question
can also wait on a named outside result (r8-q31): `waitsFor`, a non-empty string
saying what (a spike, a review, the person's own try, another session's ruling)
and where it lands, holds it out of the batches like `waitsOn`, and its
dependents with it; `show`, the Check list and the pane's row name it ("waits
for …"). It is set and freed (`waitsFor`: null) through a pass report (the
model's own spike or review, disclosed in the report) or `edit` with the
person's quote; a freed question gets the scoped check of an edited one before
it is asked. `restart`
takes answered dependents along, through chains, and names them. Questions go out
in listed order, four at a time; a new question goes last, or ahead of the one
its `before` names, and existing questions stay put. `show <ids>` prints
questions whole, and a record carries the question's premises as `## Premises`.
The quote check of `edit` and chat answers also accepts a dialog note.

`protocol next` prints the top 5 seed questions of the next round (open
decisions, unblocked, not held by another live session; members of an open
milestone first, then priority, then the work they hold, in Select's ordering),
the open-item list (waiting questions, `in_review` designs, ready milestones,
finished epics, what waits on the user: whole the first time between
compactions, counts and the listing command after), the open questions by topic
label and priority (`orm-schema-migrations 7 p1, 7 p2`, every time, a question with two labels under both; the labels
come from `board health --json`, whose item rows carry `labels`) and the stored
proposal, and saves the board's count of a bare release; without a board it has no
seeds. `next` tells the lead to rank rows by priority and by how many questions
each settles, to state the trade in `why`, and to put a follow-up that reuses what
was just read first, to recommend the other next step when no question round leads,
and how to start a row. `protocol next --set` (stdin `{"rounds": [{"title",
"summary", "estimate": {"questions", "unblocks"}, "why", "fresh", "ids"?}]}`)
stores the model's proposal while no round is open: at most 3 rows. `title`
(75 characters) and `summary` (one sentence, 240) are plain words: a question id
(`q12`) or a board item in them is refused (a hyphenated word is an item only
when the board shows it). `estimate` holds the model's whole-number estimates:
questions settled, board items waiting on the answers. `ids` optionally names
questions that must lead; each must be on the board and is stored with its
title (`idTitles`). `fresh` marks a round that reuses nothing read so far. An
empty `rounds` offers only a compaction (the console shows it while the context
is large). Unknown fields, `compact` and the former `premise` included, are
refused, every error in one refusal; a row an older engine stored shows its
title alone. `start round` clears the proposal. `start round --proposal <n>`
starts row n: topic `<title>: <summary>`, the row's `ids` named, the row's title
and summary the round's; not with `--topic` or ids. Stage then requires `round`
only when the round has no title and summary. `start round --topic '<title>:
<summary>' [ids]` keeps the topic on the round. Either way Collect prints the whole open list every
time, with the steer to group by default (a round takes every ready question
sharing a premise, root cause, flow or sources; a single question names why none
does), and Select repeats it. The release's close text tells the model to run
`protocol next`.

What a session was told is one record, `state['told']`, cleared by `protocol
compacted` (no stdin, open round or not; `hooks/compact-reorient.sh` calls it for a
deciding session of either tool and says so in the recovery message when it fails).
`show` and a release-round note never count as telling. The record holds: a step
kind's report format, the ask instructions around the dialog (the Codex form keeps
the marker and the verb in a clause), the open-item list, the Durable owners
and Closure sections of project-memory.md (printed at Owner writes from the
installed file; one line naming each that is missing), the answer-routes note ("Act on
each part of the user's words", then a one-line pointer, r13-q79) and, beside the record, the
question rows last printed (`state['rows']`, r13-q66): a check pass prints only the rows that
differ from the last output, then `N questions, K listed above as new or changed (protocol
show lists them)`. A pass always gets the skill's full text; the engine cuts nothing. A
compaction prints everything again. A `checked` line is one line of about 120 characters; the
engine refuses one over 150 (strong reasons are still re-sent each challenge run).

Every step's output opens with a headline: the call's events in the Log's
words, then the next step (`r1 · related resolved · next: the next batch`); the
console shows it as the call's chat row. In Claude the pass sequence stays out of
what the model reads: no named next pass and no cycle in the headline or check text, only
`End your turn with one short line` and that the console runs the next pass, not the model (r8-q30). The pane shows `checking N/M`, `protocol show`
keeps the cycle, and Codex, which runs its passes itself, keeps them all.

`bin/round-report` prints passes by kind, how questions were answered, how often a
recommendation changed after the person saw it (the `late-change` event), the console's dropped actions and its continues
(`nudged`, by what each did);
`--since <time>` compares before and after a change, `--transcripts` adds tool use
and tokens per pass.

A lean question with room in its dialog also offers `Think more`: no answer, so
that question's checks rerun with no model reading and it comes back; the batch's
other answers are recorded. A pass argument reads `<lenses> on <ids>; <focus>`;
each rerun pass naming the question carries its goal as that focus
(`Think more on q138: the lean fell short, try to get a reasoned strong
recommendation`); `protocol show` keeps the lean the person saw (`thinkMore`), and
the goal ends when the question is asked again. Only the leading lens names and
ids count (`on` and the `;` optional). A question with four options has no room, and the person
types their request. A preference lean carries `leanBecause.flipsIf`, and `priorRulings`
lists each released ruling a recommendation rests on or the Related step linked, with
`holds` or `fails` and why: the record keeps them all, and the print shows how many
held and each that fails. An open decision named in an unanswered question's `board` or `settles`
joins the round and is claimed (a gone session's hold taken over, a live one's
refused). When a pass ends with no report, the console asks the model once, then tells
the person the round stopped and what to type.

`show --json` is the console's contract (version 1; its real output in ten
states is `claude/mods/console/tests/engine-contract.ts`, regenerated with
`WRITE_CONSOLE_CONTRACT=1`): round title and summary, step progress, the
questions with their recommendation and strength (and `changedBy`, the pass
whose most recent report changed them), the batch, the round's whole log (pass lines name their kind: `step-back
(path)`, `ground (lean q39 q40)`, scoped ids for a restart's or a release's
rerun; a leading "no change" of a summary is left out; consecutive `recorded`
lines merge), a release's `records` with their state, and `stopped` (the last release's stop,
shown while no run is open), and `next` (no run open: `{"release": {"count"}}` while the session holds decided
board records a bare release would take, counted at a round's or release's close
and by `protocol next` (`show` never reads the board), and the stored proposal's
`rounds` (each `title`, `summary`, `estimate`, `why`, `fresh`, `ids` and `idTitles`), present once a proposal is stored and empty when it proposes only a compaction; null when none). The engine-issued release approval question is `Release the
session's 3 records?`, an unsure ruling first and cut to fit; the text before the
dialog prints every ruling in full (all reasons for asking go to the model's ask text and
the Log). `start` with a release open refuses and says that for a question to the
user, `protocol abandon` releases nothing and `start release` takes the same
records again.
`answer` and `decline` print the show state with the note for the console's
`dialog` origin, and the note alone for `chat` and `model-reported`, which the
model reads. Headline pass summaries cut at a word boundary with `…`. `status --line` is
the recovery line, which compact-reorient appends for Codex sessions. `start`
deletes other sessions' folders without an open round after 30 days without
changes.

`claude/mods/console/` is the Claude Code console mod, linked out of store as
`~/.claude/mods/console` and loaded through `CLAUDE_CODE_PLUGIN_DIRS` in
`~/.claude/settings.json`, so its edits hot-reload (Claude lays the API types
into its `.claude-plugin/types/`, ignored by Git). It registers the `protocol`
tool (`mcp__console__protocol`, stamping session and origin; it refuses the model the verbs the console relays,
`pending` since the console runs the next pass (r8-q28), and `scope` since the console appends its line to a starting pass's text (r9-q36)), runs the
engine's pending pass and the issued batch's question text (`/console-questions`) at each turn's end, gates and captures round dialogs,
runs a built-in command sent during a turn (`/compact`, which Claude Code delivers to the model as text) when the turn ends,
relays the person's chat messages, presses and a typed or pressed
`/release-round` (conditional approval), and keeps the round through
compaction. Its round features act for lead, solo and autopilot. A `protocol` call reads as two rows in the chat: its arguments and
the engine's headline. Every call may run up to ten minutes (`$.process.run`'s maximum); one that fails or is cut answers the model
with the error and that it may have run in part (read `protocol show` before running it again; a Record step runs again safely).
Esc at a turn end stops the pass loop; a successful compaction right after reruns the stopped pass once (not a skipped or precompute
one; a pass given up as stuck is never rerun). `/console-continue` (r7-q24) runs the turn-end decision on demand: it queues the pending pass (a stopped, asked-for or noted
run of it included) unless a run of it is queued already (a run the host refused counts as none), reopens the issued batch past the
repeat guard, else wakes the model at the open step with `protocol status --line`; during a turn it runs at the turn's end (Esc drops it); logged as `nudged`. A model Skill call of a pass skill counts as the round's pass; a subagent's does not. A pass skill that starts (console-run, typed or the model's own Skill call; not a stale queued run, nor a subagent's) gets the engine's `scope` line appended to its expanded text, stamped for a model call as its run will be recorded; an engine failure leaves the text as it is (r9-q36). The Console pane (`/console` shows it as text;
`/console-item <id>` prints an item's summary in the chat; `/console-questions` prints the issued batch's text) shows Board
(counts, this session's items, sessions with runtime and pull initials, `auto` for autopilot, stale
holds, live workers), Suggestions while no run is open and the engine's `next`
offers something (one row per proposed round: `[ Start ] <title> · ~N questions ·
unblocks ~M items`, plus `· compacts first` for a
`fresh` round while the context is at 150k tokens or more
(`$.session.usage()`; no reading counts as small, and a compact-only row, a
stored proposal without rounds, shows only then too), the first row recommended
in the theme's `suggestion` color; the summary is a dim wrapping second line, the
model's `why` the Start's hover hint; a click on a row that names ids lists the
leading questions by title, each opening its item; Release Round and a compact-only proposal show here too; none of it while the role is
autopilot, which nobody starts a round or a release for), Round (title,
summary, step words, questions: up to 10 of any kind show whole, beyond that 10
show, the asked ones and the 2 latest answered first, then upcoming, held and
older answered ones, and the rest fold behind their toggles; each with their recommendation on hover and, after the title, a mark (`◆
strong`, `your call`, `unverified`), the answer on answered rows (`→ …`, cut;
the title truncates, the answer and marks keep their line) and `↻ <pass>` for
the questions the most recent pass report changed; a release lists its records
with their state, and a stopped release its reason and next round), Controls
(the passes, with the pending one marked next or running; Step Back offers
Base, Path (`goal foundations`), Options (`options`), Refine (`decisions clean overfit mechanics`)
and All (every lens in list order), Ground Base and All, each with the focus
for Step Back, without changing the selection; Decide (Question Me, Intake running
`/round-intake`, which asks for your list, Continue while a round is open, doing what `/console-continue` does (but an idle press hands a batch to the model to open)
and in the `suggestion` color while the session is idle and nothing has queued or started the pending pass, Challenge Rulings, Explain); Actions,
whose Release Round and Compact take the `suggestion` color exactly when the
Suggestions area offers them, and which hold the role button: Autopilot while solo, Solo while
autopilot, each running the `/role` command (the host refuses a prompt text starting with `/`);
a lead or agent session has none; Release Round is hidden while autopilot) and the round's Log, newest first, the last 10
lines with a `+N more` toggle for the whole round. A click on an item id (board
items, stale holds, release records) opens it inline below the row (`reading…`
meanwhile, the error in the error color if the read fails): up to 4 lines of
its `## Decision` (else the description's start, headings dropped), then a
facts line (type, priority, holder, labels, parent, link counts, comments,
`/console-item <id>`) whose hover lists the linked ids and a second click
closes it; a question's overlaps link opens the overlap ids and titles the
same way, each id opening its item; a rule question's `settles N` mark opens
the settled ids the same way (a pasted point has no item to open); one thing is
open at a time. A pane the
person closed stays closed until `/console`. The band above the prompt shows
the round during one (a release run the same way), with Solo beside the passes
while autopilot (and alone, `Autopilot · away`, with no run open), and with no run open the
recommended suggestion (the row's first line `·` with Start, `M records
decided ·` with Release Round, or Compact), nothing while a dialog is
open or nothing is offered. Start runs `/start-round <n>` (bare: row 1) without a
stamp: the press is the go-ahead, not an approval like `/release-round`. A row
that compacts first stores the command and runs `/compact` with no focus text;
the compaction hook keeps the proposal's title in the summary and runs the
command once the compaction succeeded (a skipped or failed compaction drops it
with a notice naming the command; so do your next typed prompt and a round
start).
`/console` prints a line per proposal below the board (`<n>. <first line> ·
<summary> · type /start-round <n>`); the idle-agent notification goes out
once per idle episode across consoles. It idles without a registered role or a
drawing surface and fails open except for recovery. Test it with `claude
plugin test home/patrick/agents/claude/mods/console`.

The validator runs its groups (core, hooks, board, contract and the protocol
engine's parts `engine-<part>`, `PROTOCOL_PARTS`) as parallel child processes
(`--group <name>` runs one). The switch's build runs only `--group core` (what
it generates: skills, definitions, rendered sizes) from a source without the
test-only files; the full validator is `nix flake check` (`checks.agent-configs`),
the gate to run before staging. The nix sandbox has no `bd`: in-process test
boards carry empty settings (`bare_deck`) instead of reading them through bd. Each engine part starts on a fresh fixture;
sections within a part share state in order, so a section that needs an earlier
one's rounds stays in its part.

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
  board core's [Actors and holds](skills/shared/board-core.md#actors-and-holds)
  describes.

`bd lint` checks `decision` descriptions for the record sections (built-in
Rationale and Alternatives Considered; configured Question, Decision, Rule
owner); board core's
[Questions and rulings](skills/shared/board-core.md#questions-and-rulings)
owns the record lifecycle. Closed records keep their shape (board-migrate
Invariants).

The `explore-options` skill coordinates `option-explorer` to develop a broad
solution space into realistic alternatives. It progressively screens and deepens
approaches, reports material exclusions, and leaves decisions to the invoker.
Sessions name triggers in their protocols; the skill owns how its result is
reused.

The `architect` skill coordinates the architecture specialist without
requiring a role. The agent owns design and review; `second-opinion` independently
challenges decisions. The lead selects each for a concrete question. `plan`
decomposes an agreed design into implementation work when decomposition or
integration needs specialist judgment; leads can write pattern-determined plans
and continuation deltas directly.

The [review protocol](skills/role/protocols/review.md) owns review gates and
acceptance evidence. The [decision protocol](skills/shared/decision-protocol.md)
owns default decision authority, end-state criteria and concern classes; agent
definitions read it at runtime. Shared files:
[reviewers](skills/shared/reviewers.md) (selection, briefing, independence,
disagreement), [asking](skills/shared/asking.md) (how deciding sessions
walk the user through a round) and
[upstream waits](skills/shared/upstream-waits.md) (read on demand from
board-coordination).
[Question format](skills/shared/question-format.md) is tool-neutral; asking, role, question-me and retro include it.

Tool-specific names are optional and default to the canonical `name`. Shared
`explore` overrides that default as Claude Code's `Explore` and Codex's
`explorer`; shared `plan` becomes Claude Code's `Plan` and remains lowercase
in Codex.

## Sharing the setup

`./build-agent-setup.sh [folder]` (flake root; default folder: home) runs
`nix build .#agent-setup` and copies out `claude-codex-setup-<date>-<rev>.tar.gz`
for someone without this nix config: new files must be tracked first, and a
`-dirty` version names a build with uncommitted changes. `../agents-package.nix` owns what ships and builds this
machine's links from the same lists, so a shipped hook or tool is added in one
place; hook registrations come from `../claude/settings.json` and
`../codex/hooks.json`, so only this setup's hooks belong in them.

`setup/install.sh` (its use: `setup/README.md`) runs on stock macOS bash 3.2; the
validator's hooks group holds the shipped shell to that and runs the installer in
a fake home. It refuses symlinked targets, so it never runs over this machine's
home-manager links. The `~/.agents/setup-state.json` it writes lists what it
installed, which is how an upgrade or `--uninstall` finds what to remove.
