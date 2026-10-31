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
- [Work tracking](skills/shared/work-tracking.md): board model, holds,
  routing, record shapes and `board` views; [board-migrate](skills/board-migrate/SKILL.md)
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

`bin/board.py` (installed as `$HOME/.agents/bin/board`, not on `PATH`) is the
agents' only board interface: views and hand-offs from one snapshot sized to
the command (`Board.load`: a `bd list` of the non-closed items plus one
`bd show` of the held items' comments for status views, `bd export` for
`related`, `check` and the writes that read closed items, a `bd show` of only
the named items for `board show`), and `board bd <args>` for every other bd
command. It starts a stopped
server on server-mode boards (bd's auto-start is off) and takes the actor from
`session-lead-mode actor`, the owner of the session identity
(`CODEX_SESSION_ID`/`CODEX_THREAD_ID`, else `CLAUDE_CODE_SESSION_ID`). Hooks
add: bd-guard denies bare `bd` and sets Claude subagents' own actors (without
it they act as their session, so in-session reviews by them are not
independent); session-register keeps workers from registering; the
session-start hook starts the server before `bd prime`, and on Claude
refreshes the session's registered process (`session-lead-mode alive`);
session-activity records activity as file mtimes: SubagentStart and a
worker's tool calls create or touch the worker's marker, SubagentStop deletes
it, and the session's own tool calls touch `<session>.active`. Probed on
Codex 0.166 (2026-10-31): SubagentStart fires on first spawn, the matcher-less
PreToolUse group fires for shell and apply_patch calls, a worker's payload
`session_id` is its parent's, and its `agent_id` equals its
`CODEX_THREAD_ID`, which the worker actor's suffix comes from.
`board position` marks holders GONE when their session's process ended
(Claude; Codex records no process: the nearest `codex` ancestor can be a
shared app-server or a per-command sandbox helper), derives idle from the
holder's last tool call (else the item's update) and shows
`workers <active>/<cap>`. `board mine` marks holds of the caller's workers
without a marker WORKER STOPPED once the session's `.active` exists (only the
owner knows whether it continues the worker). `claim`, `handover`, `return`,
`block`, `mine` and `queue` print a capacity line for dispatching sessions
below the worker cap with ready work. `board check` encodes the work-tracking
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
call and questions it closed before; any other open blocker leaves the
question open (exit 1).
`session-lead-mode state-dir` names the state dir; the engine and the console
ask it instead of restating the location.

`bin/protocol` (installed as `$HOME/.agents/bin/protocol`) is the protocol
engine of deciding sessions: it owns each session's protocol state in
`<state dir>/<session>.protocol/` (with an append-only `history.jsonl`) and
prints the next step, one call per step; `run_cli()` is the same CLI as a
function, which the tests call in-process. Its protocols are `round` (the
decide protocol's Round from Collect to Record) and `release` (its Release).
A round:

- Collect classifies every pasted point and the board items in the round's
  scope; `start round --discussion` takes the pasted points alone, and
  `--no-board <dir>` (required without a board) writes the records as files
  in `<dir>` with no board reads or writes.
- Select claims the selected items; Stage requires a plain round title and
  summary and, per question, a plain title, 2-4 options, the recommended
  option and its strength under decision-protocol.md Recommendation strength
  (a lean names its cause, a strong one carries the five-criterion checklist).
- Related searches each new draft and needs an outcome per hit.
- Check runs step-back and ground until a cycle changes nothing (cap 3 cycles,
  then a dialog), one focused `ground probe sources <ids>` pass on evidence
  leans, then challenge-rulings before every first batch. A pass that changes
  nothing lists what it `checked`; any pass report, also out of sequence or
  with a batch out, updates questions. Edits to title, header, strength or its
  backing alone re-issue the batch; other changes rerun the loop.
- Ask issues batches marked `metadata.source = round:<id>:<n>`: the
  recommended option first, labelled "(recommended, strong)" or
  "(recommended, lean)", a lean's description opening with what it rests on
  ("Unverified: …" or "Your call: …"). Answers
  count only from the person: `dialog` (relayed by the console), `chat` (the
  model's mapping, accepted when its quote appears in a message the console
  relayed with `say`) and, in Codex sessions only, `model-reported`. A
  dialog answer counts only as an option pick: typed text returns its
  question to the model with the words stored for the quote check (an
  option, a criterion or a request such as explain, which it runs before
  `step` asks again), and a pick's note reaches the model and Record.
- Record writes the records; closing or abandoning releases the claims the
  round made and did not record (a hold the session had before, such as a
  decided record, stays). Held questions carry to the next round while their
  board item stays open. A round that recorded board records closes naming
  the release.

A release runs in the same slot with the next run id (`r5 release · r4's
records`), one run per session, on a board only:

- `start release` takes the last closed round's board records still decided,
  `start release <ids>` others; ids another live (or idle) session holds are
  refused, a gone session's hold is taken, unheld records are claimed.
- Re-check and Board check give each changed record a reach: contained drops
  it from the set, spreads stops the run (nothing releases, the records stay
  decided and held, the close names the round for them). The board check
  names supersedes and answered questions; a premise hit drops the record.
- Own rulings mark each ruling sure or not. Approval comes from the person
  only: a typed or pressed `/release-round` (the console relays it as `pass
  --origin composer|bridge|press` with command `release-round`, which starts
  the release on the ids leading its arguments, else on the default set, or
  stamps the open one) approves when every ruling is sure
  and the set is unchanged; otherwise an engine-issued `confirm-own-rulings`
  question goes through the ask machinery (dialog, chat quote, Codex
  `model-reported`; only the Release or Hold pick counts).
- Owner writes checks each owner: written paths exist (repo paths from the
  board root, absolute and `~` as written; installed files as rendered),
  Markdown anchors match a GitHub heading slug or an explicit anchor, pending
  items are open, and the record's `## Rule owner` names each written path.
- Release runs `board release` with the answered closes, then the other
  supersedes; it reads statuses first and reruns only what remains after a
  failure.

Every step's output opens with a headline: the call's events in the Log's
words, then the next step (`r1 · ground: q3 changed, 1 not applied · next:
step-back, cycle 2/3`); the console shows it as the call's chat row.

`show --json` is the console's contract (version 1; its real output in six
states is `claude/mods/console/tests/engine-contract.ts`, regenerated with
`WRITE_CONSOLE_CONTRACT=1`): round title and summary, step progress, the
questions with their recommendation and strength, the batch, the round's
recent log, a release's `records` with their state, and `stopped` (the last
release's stop, shown while no run is open). `status --line` is the recovery line, which compact-reorient
appends for Codex sessions. `start` deletes other sessions' folders without
an open round after 30 days without changes.

`claude/mods/console/` is the Claude Code console mod, linked out of store as
`~/.claude/mods/console` and loaded through `CLAUDE_CODE_PLUGIN_DIRS` in
`~/.claude/settings.json`, so its edits hot-reload (Claude lays the API types
into its `.claude-plugin/types/`, ignored by Git). It registers the `protocol`
tool (`mcp__console__protocol`, stamping session and origin), runs the
engine's pending pass at each turn's end, gates and captures round dialogs,
relays the person's chat messages, presses and a typed or pressed
`/release-round` (conditional approval), and keeps the round through
compaction. A `protocol` call reads as two rows in the chat: its arguments
and the engine's headline. The Console pane (`/console`; `/console-item <id>`) shows Board
(counts, this session's items, sessions with runtime and pull initials, stale
holds, live workers), Round (title, summary, step words, questions capped at
10 with their recommendation on hover; a release lists its records with their
state, and a stopped release its reason and next round), Controls (the passes, with the
pending one marked next or running; Decide; Actions) and the round's Log,
newest first. A pane the person closed stays closed until `/console`. The band
above the prompt shows the round during one; the idle-agent notification goes
out once per idle episode across consoles. It idles without a registered role
or a drawing surface and fails open except for recovery. Test it with `claude
plugin test home/patrick/agents/claude/mods/console`.

The validator runs its groups (core, hooks, board, engine) as parallel child
processes (`--group <name>` runs one).

Work tracking deliberately avoids some beads features (bd 1.3.1); re-check
before adopting them:

- `external:` dependencies never block: no production code calls
  `ResolveExternalProjectPath`, so upstream waits use a local human gate.
- `bd human respond`/`dismiss` close on answer; questions close once their
  released ruling is planned.
- `bd close --suggest-next` lists only what one close unblocked; next steps
  follow priority and decision clusters.
- Claim leases, `bd heartbeat` and `bd reclaim`: nothing reads the 5-minute
  leases, and `bd reclaim` would free every held item. Holds end only as
  work tracking's [Actors and holds](skills/shared/work-tracking.md#actors-and-holds)
  describes.

`bd lint` checks `decision` descriptions for the record sections (built-in
Rationale and Alternatives Considered; configured Question, Decision, Rule
owner); work tracking's
[Questions and rulings](skills/shared/work-tracking.md#questions-and-rulings)
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
disagreement) and [asking](skills/shared/asking.md) (how deciding sessions
walk the user through a round).
[Question format](skills/shared/question-format.md) is tool-neutral; asking, role, question-me and retro include it.
The skills a user re-runs by mention include [rerun](skills/shared/rerun.md).

Tool-specific names are optional and default to the canonical `name`. Shared
`explore` overrides that default as Claude Code's `Explore` and Codex's
`explorer`; shared `plan` becomes Claude Code's `Plan` and remains lowercase
in Codex.
