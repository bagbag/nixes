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
Missing targets, escaping paths, cycles, frontmatter markers, and malformed or
unresolved markers fail validation.

Keep role and authority limits and the `shared/rerun.md` include before each
skill's workflow; place other whole-file shared references after it and link
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
  [release-round](skills/release-round/SKILL.md) and
  [explain](skills/explain/SKILL.md) are user-invoked only. Their
  argument names the focus and follow-ups.
- [Retro](skills/retro/SKILL.md): rule proposals and regression cases.
- [Skill authoring](skills/skill-authoring/SKILL.md): invocation policy,
  trigger descriptions, frontmatter and style for skills, definitions and
  instructions; loaded while writing, user-invoked to review.

`bin/board` (installed as `$HOME/.agents/bin/board`, not on `PATH`) is the
agents' only board interface: views and hand-offs from one snapshot sized to
the command (`Board.load`: a `bd list` of the non-closed items plus one
`bd show` of the held items' comments for status views, `bd export` for
`related`, `check` and the writes that read closed items, a `bd show` of only
the named items for `board show`), and `board bd <args>` for every other bd
command (`bd edit`, which blocks on an editor, and `--readonly` are refused with
the way on named in one line). It starts a stopped
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
sets it with no model turn (`set-workers`); Codex's thread limits lower it. `board check` encodes the board-core
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
prints the next step, one call per step; `run_cli()` is the same CLI as a
function, which the tests call in-process. Its protocols are `round` (the
decide protocol's Round from Collect to Record) and `release` (its Release).
A question whose Related outcome supersedes a decided record closes it at Record
(`board supersede`: waiting items, settled items and a pending revision move to
the new record; the dialog names it by id and title); a released record is
revised and replaced at release. Related may mark any decided record this way,
a hit or not, by naming its id under `outcomes` (only a recorded ruling; a
record another live session holds is refused). `board record` on a decided
record keeps its old `## Decision` in a comment when that section changes.
A round:

- Collect classifies every pasted point and the board items in the round's
  scope; `start round --discussion` takes the pasted points alone, and
  `--no-board <dir>` (required without a board) writes the records as files
  in `<dir>` with no board reads or writes. Items another live session holds
  stay out, named in one line; a gone session's hold is offered, marked.
  `start round <ids>` names the open items to look at first (an id that is closed,
  held by another live session or no item a round offers is refused by name);
  `--topic '<title>: <premise>'` starts a topic round (see `protocol next`);
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
  engine's constants) and who reads each field; an option may carry a
  `preview` (single-select only). `cases` (the cases that must and must not work), `premises`
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
  (`My ruling:`, `Instead:`, `Why not:`) without its evidence, which only the
  record keeps (`## Own rulings` has all four fields). The Stage text states one
  rule for every printed part, with no length check on them: say what is decided and
  what each option means for the person (what they would see, what it costs), each
  thing once, in plain words; how it was found (sources, measurements beyond the
  deciding number, who said what) and how it gets built go to the record. A re-ask prints a question
  as `(changed)` with only the parts that differ from what the person saw (a
  snapshot per question, taken when a dialog for the batch comes back, so a batch
  withdrawn before its dialog opened prints whole; nothing changed: no text). A release
  approval prints its corrections (revised and dropped records), the board check
  (supersedes, closes, the other hit rows) and every own ruling in the same layout; a
  typed or pressed approval opens no dialog and prints nothing. In Claude
  sessions the console prints the notice, opens the dialog and records the answers
  with no model turn (r29-q138, r32-q149): when a batch is issued the lead writes
  nothing about the questions and ends its turn, and at the turn's end (not aborted,
  not a subagent's) the console runs `/console-questions`, whose hook prints the
  notice (its output draws whole between turns; the model reads that one copy, and an
  empty or repeated notice prints a short line) and opens the dialog. The host's
  `$.ui.ask` takes labels only, so it asks a placeholder and the console's
  AskUserQuestion hook swaps it for the issued batch (never drawing the placeholder).
  Plain picks then let a pending pass run; a typed reply, a note, a decline or anything
  else wakes the model with the answers, one line each, as the person's own words (no plugin frame), and the engine's text as a note. A `$` call
  skips the hook it came from, so that hook cannot print a next batch: the model's turn
  end does. If the swap never ran, a one-line message asks the lead to open the dialog
  with the input `protocol show` gives; so does a run of the command its hook never
  answered, after printing any new text as a notice. There is no Ask button. At most one dialog per
  batch marker opens until the person sends a new message (a composer or bridge message
  clears it). The dialog gate still blocks a
  marked dialog whose notice is not printed yet once, telling the lead to end its turn. After a
  reply the person typed instead of picking, the lead answers it as the turn's last
  text (restating it in one line when it could be read more than one way), never in
  the same turn as the dialog, and ends the turn; the console reopens the dialog, also
  when nothing new prints. The dialog options carry neither `for`
  nor `against`.
- A rule question settles several selected items (board ids or pasted
  points) that one answer settles the same way: its `settles` lists their
  keys, and the items need no question of their own (never on a
  confirm-own-rulings question; an item is settled once and is no other
  question's `board`/`for`). Invariant: every selected key is covered by a
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
- Check runs, per round: the path pass once (`step-back goal foundations`,
  which also digs into the real problem behind the ask and whether the design
  fixes its root; its changes flow on, and new or reworded drafts are searched
  through Related first), then the options pass once (`step-back options`, r30-q142:
  radically different ways, other mechanisms or owners or removing the need, each
  argued at its strongest; the report carries `explored`, per question a list of
  `{idea, verdict: kept|dropped, why}` or the reason there is no other way, and is
  refused without it; a `confirm-own-rulings` question is skipped; the dropped
  ideas print under the options), then step-back and
  ground until a cycle changes nothing (cap 5 cycles, then a dialog whose
  Continue adds 5; an open round keeps its stored cap), then the refine pair
  once (round-wide `step-back decisions clean overfit mechanics`, then
  `ground assumptions board sources probe`; a change in either reruns the Base
  loop under the cap, and the pair does not repeat), one targeted
  `ground assumptions sources probe <ids>` pass on every lean (evidence or
  preference: make it strong with evidence, or name what it rests on; no
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
  (the same scoped re-check follows an edit and a released held question), the Base loop round-wide, then
  `step-back decisions clean overfit mechanics <ids>` and
  `ground assumptions board sources probe <ids>` (changes rerun Base once),
  then the lean pass as usual. A pass (pressed, typed or model) whose argument names every lens
  of the path set, of the options set, of the refine step-back set or of the refine ground set
  counts as that pass for the round (a scoped rerun also needs the restarted ids
  in the argument), and a pending path, options or refine pass is
  accepted only after such a run (Codex: its report). The engine's lens lists
  (`ALL_LENSES`, `PATH_LENSES`, `OPTIONS_LENSES`, `REFINE_LENSES`) are checked against the
  skills and the console's words.ts. A
  pass that changes nothing lists what it `checked`; any pass report, also out
  of sequence or with a batch out, updates questions. Edits to title, header,
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
  user asked for: the quote must appear in a message the console relayed since
  the touched questions went out (Codex: verbatim), the updates validate as in
  a pass report, a batch that is out comes back and goes out again with no pass
  (rows read `↻ edit`), except an edit that only adds questions, which leaves it
  out. A new question or a changed recommendation stays out of the batches until
  the scoped check ran on it (at the hand-over below, at once when nothing else
  waits), and a recommendation raised to strong until one challenge-rulings pass
  ran on it (`challenge-rulings (raised <ids>)`); the other questions go out.
  Wording, options, premises, previews and a mark lowered to lean stay free. A
  pass report with a refused update holds the round: no batch goes out until the
  failed updates are resent in a pass report. An option's `preview` alone is
  presentation for a pass: its change re-issues the batch without rerunning the
  loop.
- Ask issues batches marked `metadata.source = round:<id>:<n>`: the
  recommended option first, labelled "(recommended, strong)" or
  "(recommended, lean)" (a release approval has no mark), a lean's description
  opening with what it rests on ("Unverified: …" or "Your call: …"; the prefix
  does not count toward the description limit). A batch of two or more is numbered (`1. `, `2. `) in
  the dialog text, which keys the answers. The engine renders the text printed
  before the dialog from the question data and owns its format (below); the
  Claude ask text tells the lead to write nothing about the questions and end its turn while the
  console prints them and sends the message that opens the dialog (the headline says
  `next: the console to print, then your answers`, or `the console to open the dialog` for an empty
  notice), the Codex ask text carries the text ("Text to show first") for the model to show, then asks. Answers
  count only from the person: `dialog` (relayed by the console), `chat` (the
  model's mapping, accepted when its quote appears in a message the console
  relayed with `say`) and, in Codex sessions only, `model-reported`. A
  dialog answer counts only as an option pick: typed text returns its
  question to the model with the words stored for the quote check (an
  option, a criterion or a request such as explain, which it runs before
  `step` asks again), and a pick's note reaches the model and Record.
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
  in as a draft and records its own item. Abandon names the records that stay
  decided.
- Record writes the records; closing or abandoning releases the claims the
  round made and did not record (a hold the session had before, such as a
  decided record, stays). A question waits only within its round: `waitsOn` refuses
  a circle, abandoning keeps no held question, and the board owns what a later
  round asks. A round that closes while the session holds decided
  board records closes naming the release.

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
batch by batch, and Record runs once, when nothing is left to ask. `restart`
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
"premise", "why", "fresh", "ids"?}]}`) stores the model's proposal while no round
is open: at most 3 rows, each a topic (`title` within 75 characters) and its
premise; `ids` optionally names questions that must lead; `fresh` marks a round
that reuses nothing read so far. An empty `rounds` offers only a compaction (the
console shows it while the context is large). Unknown fields, `compact`
included, are refused, every error in one refusal; a stored row of an older
engine still reads. `start round` clears the proposal. `start round --topic
'<title>: <premise>' [ids]` keeps the topic on the round: Collect prints the
whole open list every time, with the steer to group by default (a round takes
every ready question sharing a premise, root cause, flow or sources; a single
question names why none does), and Select repeats it. The release's close text
tells the model to run `protocol next`.

What a session was told is one record, `state['told']`, cleared by `protocol
compacted` (no stdin, open round or not; `hooks/compact-reorient.sh` calls it for a
deciding session of either tool and says so in the recovery message when it fails).
`show` and a release-round note never count as telling. The record holds: a step
kind's report format, the ask instructions around the dialog (the Codex form keeps
the marker and the verb in a clause), the open-item list, the Durable owners
and Closure sections of project-memory.md (printed at Owner writes from the
installed file; one line naming each that is missing), per check cycle the question
list of a check pass (later passes print `N questions (protocol show lists them)`). A
pass always gets the skill's full text; the engine cuts nothing. A new check run (`restart`, a rerun at Ask) and a
compaction print the question list again.

Every step's output opens with a headline: the call's events in the Log's
words, then the next step (`r1 · ground: q3 changed · next:
step-back, cycle 2/5`); the console shows it as the call's chat row.

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
`rounds`, present once a proposal is stored and empty when it proposes only a compaction; null when none). The engine-issued release approval question is `Release the
session's 3 records?`, an unsure ruling first and cut to fit, in full in the
Release option's preview (all reasons for asking go to the model's ask text and
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
tool (`mcp__console__protocol`, stamping session and origin), runs the
engine's pending pass and the issued batch's question text (`/console-questions`) at each turn's end, gates and captures round dialogs,
relays the person's chat messages, presses and a typed or pressed
`/release-round` (conditional approval), and keeps the round through
compaction. Its round features act for lead, solo and autopilot. A `protocol` call reads as two rows in the chat: its arguments and
the engine's headline. The Console pane (`/console` shows it as text;
`/console-item <id>` prints an item's summary in the chat; `/console-questions` prints the issued batch's text) shows Board
(counts, this session's items, sessions with runtime and pull initials, `auto` for autopilot, stale
holds, live workers), Suggestions while no run is open and the engine's `next`
offers something (one row per proposed round: `[ Start ] <title> · <premise> · <why>`,
plus `· leads with <ids>` when it names questions and `· compacts first` for a
`fresh` round while the context is at 150k tokens or more
(`$.session.usage()`; no reading counts as small, and a compact-only row, a
stored proposal without rounds, shows only then too), the first row recommended
in the theme's `suggestion` color; a click on a row that names ids lists them,
each opening its item; Release Round and a compact-only proposal show here too; none of it while the role is
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
for Step Back, without changing the selection; Decide; Actions,
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
recommended suggestion (`<title> ·` with Start, `M records
decided ·` with Release Round, or Compact), nothing while a dialog is
open or nothing is offered. Start sends `Start the next round: protocol start
round --topic '<title>: <premise>' <ids>` as your prompt; for a row that
compacts first it stores that message and runs `/compact` with no focus text; the
compaction hook keeps the message in the summary (the only text it adds) and
sends it once the compaction succeeded (a
skipped or failed compaction drops it with a notice; so do your next typed
prompt and a round start); the idle-agent notification goes out
once per idle episode across consoles. It idles without a registered role or a
drawing surface and fails open except for recovery. Test it with `claude
plugin test home/patrick/agents/claude/mods/console`.

The validator runs its groups (core, hooks, board, contract and the protocol
engine's parts `engine-<part>`, `PROTOCOL_PARTS`) as parallel child processes
(`--group <name>` runs one). Each engine part starts on a fresh fixture;
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
The skills a user re-runs by mention include [rerun](skills/shared/rerun.md).

Tool-specific names are optional and default to the canonical `name`. Shared
`explore` overrides that default as Claude Code's `Explore` and Codex's
`explorer`; shared `plan` becomes Claude Code's `Plan` and remains lowercase
in Codex.
