# Protocol engine

Reference for `bin/protocol` and `bin/protocol_engine/`; the README links here. Rounds and releases: [decide](../skills/role/protocols/decide.md).

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
Round from the pre-pass to Record) and `release` (its Release).
A reversal is a revision record: a superseded ruling is put back only by recording a new revision (`board ruling revise <id>`); `board reopen` refuses a superseded ruling and says so. A question whose Related outcome supersedes a record links it at Record
(`board ruling record --replaces`); the old record is superseded when the new ruling comes into force (r9-q33): at release for a
decided ruling, or at Record for an away ruling written with `--unratified`. Waiting items and a pending revision move to the new
record, the engine moves the settled items; the dialog names it by id and title. Related may mark any decided record this way,
a hit or not, by naming its id under `outcomes` (only a recorded ruling; a
record another live session holds is refused). `board ruling record <id> <file> [--replaces <old>[,<old>]...]` writes the record and no comment copies of
the replaced text. `--replaces` is one rerunnable command for what the record replaces: it judges every old before the first write (a decided or released one is linked, one closed and superseded by it is done, anything else is refused; for an away record a live other session's hold is refused, a gone session's taken), writes the revision links with the status, then, for an away record only, supersedes each old (`board ruling supersede`'s effects); a rerun after a stop derives what is done from the board alone. `board ruling release` supersedes every old the released record revises; a replaced decided draft named in the same release is superseded, not released, and releasing it alone while a live record revises it is refused. `board ruling supersede` stays for a rule (`--partial`) and by hand. The engine's Record makes this one call with every record the question closes; the board's history (`board bd history`) keeps earlier versions (r16-q95).
A round:

- Collect classifies every pasted point and the board items in the round's
  scope; `start round --discussion` takes the pasted points alone, and
  `--no-board` (required without a board; a switch, no path) writes the records as files
  with no board reads or writes, in the repository's private
  folder `${XDG_DATA_HOME:-~/.local/share}/agents/decisions/<repo>/`, which `protocol records` prints (`<repo>`
  is the repository's scratch folder name; a release takes the files there too, the
  folder's newest round when no ids are named, which may be another session's).
  Such a round's id comes from a counter in that folder, so sessions never share
  one; a record file is created, never overwritten; `--topic` heads each record
  (`Topic: …`). Items another live session holds
  stay out, named in one line; a gone session's hold is offered, marked.
  `start round <ids>` names the open items to look at first (an id that is closed,
  held by another live session or no item a round offers is refused by name);
  `--topic '<title>: <summary>'` starts a topic round and `--proposal <n>` starts
  row n of the stored proposal (see `protocol next`);
  the engine keeps every open item either way, so a round can classify an id it
  did not print. The open-item list prints whole, grouped under a heading per view
  and status, the first time between compactions that `protocol next` or a
  round's pre-pass needs it, and at every topic round's pre-pass. After that
  a step prints the named ids, the counts
  per kind and the command that lists everything (`board health --items
  <COLLECT_VIEWS>`, plus `board position` for ready milestones and finished
  epics), and a bare round's pre-pass is told to list before it selects. A restart, a
  Related step and the pass report format name that command where a round's scope
  widens.
- Select claims the selected items (a gone session's hold through `board
  take`); Stage requires a plain round title and
  summary and, per question, a plain title, `problem` (what is decided and why
  now), `root` (record-only, never printed: "cause; end state", or "does not apply: <why>"; the
  goal check may update it and the record keeps it as `## Root`), 2-4 options each with
  `for` and `against`, the recommended option and its strength under decision-protocol.md Recommendation strength
  (a lean names its cause, a strong one carries the five-criterion checklist).
  The Stage text states the lengths to keep to (round `summary` 240, `title` 60, question
  `text` 160, `header` 12, option `description` 150; above a target and within its
  limit (title 75, text 240, description 200) a report is accepted with one warning
  line per field (`q62: title is 68 characters; keep it to about 60 (refused over
  75)`; a round's `title` and `overview` get the same band: 60/75 and 160/240), for the fields the call sets (a new question: all; an update: the ones it
  carries); a report is refused above text 240, title 75, description 200, or summary 240
  and header 12, naming the measured length, and prints no warnings; all built from the
  engine's constants) and who reads each field; every option of a code, API, naming or
  shape choice carries an `example`, printed as a code block under its For/Against before the
  dialog, never in it; a `preview` is
  refused with a pointer to `example`, so a question staged with one waits until a pass renames
  it (r10-q37, q38; no engine check that examples are present, r10-q39). `cases` (the cases that must and must not work), `premises`
  (what it rests on), `rulings` (the lead's own rulings, each with a release's four fields) and `note`
  are optional and print only when present (r27-q123); an engine-built approval or cap question
  carries no parts. The round
  description may carry one `overview` line (at most 240 characters; warned over 160). A refused
  Stage report, or a new question in a pass report, lists every error at once;
  an update that touches `problem`, `cases`, `premises`, `options` or `rulings` repeats the checks for
  them (`note` is presentation: it re-issues the batch without a loop).
- The text before a dialog (r24-q99, r30-q141) is rendered by the engine into the batch's
  `notice` (`show --json`): per question, numbered like the dialog, its
  title and its parts in order, a blank line between parts: `Problem:`, `Cases:`,
  the items a rule question settles one line each (`Settles:`), the board ids it holds up (`Holds up:`, one line, when set), `Premises:`, the options,
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
  errors. A pass that finds a point entailed retires its question with
  `{"id", "remove": true, "reason", "ruling": {ruling, why, alternative, fails, evidence}}`: the
  question then stays in the round as answered by that ruling (origin `session`: the session's disclosed ruling), so it
  still covers its point, even when it was the only cover. It lists in `show` (`retired`, and the `show` text), prints
  once ahead of the next batch's questions as `My ruling: … (retired <id> for <keys>, entailed: <reason>)`, and
  Record writes it as a record of its own like any answered question (a board item is recorded and closed by the same
  path; its Decision is the ruling, with the reason, the covered keys and `## Own rulings`). The release lists a record
  of this session's retired points with the own rulings as `sure` without a report. A removal without `ruling`
  that leaves a key uncovered stays refused. A merge or split is such an update set (set `settles`, add the rule
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
  that record, so `board ruling release --closes` closes it; one still open afterwards
  follows the partial-failure path. A `--no-board` round only names the settled
  points in the record file. `show --json` questions carry `settles`.
- A question's optional `holds` (list of board ids; absent or empty: none) names the items it holds up
  (board-core.md "Questions and rulings"): Record passes `--holds <ids>` (or `--holds none`) to the
  `board ruling revise` or `board create --graph` (a decision node) that creates its record, which records the
  blocks edges (the settled items' inherited links above are separate). It is content: an update of it
  counts as a change; `show --json` questions carry `holds`.
- Every round opens with the pre-pass (step `prepass`, before Collect; r1-q7): the
  engine queues a `step-back` pass with the lenses `goal decisions` and the focus `pre-pass over the round's points`
  (`pre-pass on <subject>`), over the pasted points and the board items listed as read at `start`. It is the rough overview
  of the whole set (direction; points that are off or rest on an unclear premise, asked first; the cut under
  question-format), where the path pass after staging judges each drafted question. Its report `{"pass": "step-back",
  "summary", "points"?, "verdict"?}` takes `points` entries: no `id` adds a point, a pasted point's `id` rewords it (`text`)
  or drops it (`drop`, with a `reason`), and `first` marks a pasted point or an open board item to ask before the rest
  (Select leads with it and says "ask first"; Stage names it so dependents wait on it). A board item is not reworded or
  dropped there (unclassified at Collect, or cut at Stage). The pass needs an observed run carrying the pending id, like the
  release's scoped pass. `start round --subject <id|text>` names the artifact the round judges (a design, a result, a
  proposal); `show --json` carries `subject`. The pre-pass then assesses it (decide.md Round 1) and reports a
  verdict (required with a subject, refused without one); its findings are added points (r1-q1, q2, q6). `--subject` is refused with `--proposal` (the row brings its
  own topic and items) and on `start release`. Stage's text points to the cut in question-format.md and adds its
  mechanics (the first part keeps the item, the others are drafts).
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
  changes nothing goes to Record, and a round with nothing answered skips it. It is invoked
  and scoped as the answered questions and my rulings on them (`challenge-rulings q1 q2 and my
  rulings on them`; r7-q27), and its updates may change the `rulings` of an answered,
  unrecorded question and nothing else of it (the answer and its options stay the user's; any
  other field is refused, `protocol restart` is the way): each change is logged
  (`rulings-changed`), the record carries it in its Own rulings (marked), and the release asks
  the user about a record with such a change, even when every own ruling is sure and the
  approval was typed or pressed (`ruling changed after the answer: <id>`).
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
  question they work on; the challenge after the answers covers the answered set and my rulings on it,
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
  out once per step kind between compactions. A refused `step` reprints only the
  formats its step offers that the session was not told since its last compaction
  (`state['told']`, `format:<kind>`), and adds one line, "The report format:
  `protocol show` prints it again.", when it left one out; a refused `edit` or chat
  `answer` always repeats its own format. The dialog JSON always prints. In Claude sessions a
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
  settled) by the classes of unattended.md, and names `session activate
  solo` for a person who is back. `act` takes the recommendation as the answer
  (origin `away`, which no verb accepts from a caller, so no person origin can pass as
  it): Record then asks `reversal` beside the rationale and rule owner, writes a
  `## Reversal` section, runs `board ruling record … --unratified`, which releases the
  ruling and files a related `Confirm or revise` question, and the
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
  `protocol:<session>:<round>:<question>` (also through `board ruling revise --external-ref`),
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
  questions whose `waitsOn` reaches it with it; the Record step lists them. A result that
  landed before Record is taken there (r7-q26): the Record report `{"updates": [{"id",
  "waitsFor": null, "premises"?}]}` (instead of `records`; nothing else of the question
  changes) frees the question, which takes the scoped check of a released held question, is
  asked in the same round and recorded after its answer (logged `freed`).
  `protocol defer` (stdin `{"question", "quote", "until"?}`; where `edit` applies, the quote
  checked the same way) defers a question the person asked to put off and the questions
  waiting on it, through chains (an answer already given to one goes; a batch holding one
  comes back without it; `until` is a date or duration `bd` reads). Record has no `defer`
  input (a report with one is refused) and files every deferral through one writer: on a board
  the question's item (a decision created for a draft, never a revision) is unclaimed and
  `board defer <id> --reason <the quote> [--until <date>]`d, outside waits too (no date);
  `recorded` is set only after the defer succeeds, so a rerun creates nothing twice. A round
  without a board files nothing: the history (`deferred`) and the Closed text note it. `protocol
  restart` of a deferred question takes it back, with the questions deferred with it. A
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
  `revised`: the engine runs `board ruling record <id> <file>` (a failure refuses
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
- Release runs `board ruling release` with the answered closes, then the other
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
model's own spike or review, disclosed in the report; at Record too, above) or `edit` with the
person's quote; a freed question gets the scoped check of an edited one before
it is asked. `restart`
takes answered dependents along, through chains, and names them. Questions go out
in listed order, four at a time; a new question goes last, or ahead of the one
its `before` names, and existing questions stay put. `show <ids>` prints
questions whole, and a record carries the question's premises as `## Premises` and its root as `## Root`.
The quote check of `edit` and chat answers also accepts a dialog note.
`protocol answer --origin chat` takes an answer to any undecided question of the open round (draft, held,
ready or asked): the quote must appear in a message the person sent after the question went out, or in any
message of the round when it never went out. The record then adds `Checks skipped: answered in chat while
<status>, before it was asked; no <pass> pass had covered it` (and unanswered premises or a pending
`waitsFor`). The answered question leaves its batch, the check loop's scopes (answered questions drop out of
them) and its dependents are released as by any answer.

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
(about 60 characters, refused over 75; a title in between is stored with a warning line) and `summary` (one sentence, 240) are plain words: a question id
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
<summary>' [ids]` keeps the topic on the round. Either way the pre-pass prints the whole open list every
time, and Collect carries the steer to group by default (a round takes every ready question
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
compaction prints everything again. A `checked` line is one line of about 120 characters (the pass format and each pass's scope line say so);
one over 120 and within 250 is accepted with a warning line, one over 250 is refused (strong reasons are still re-sent each challenge run).

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
