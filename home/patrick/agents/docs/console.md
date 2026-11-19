# Console mod

Reference for `claude/mods/console/`; the README links here.

`claude/mods/console/` is the Claude Code console mod, built into the Nix store
and linked at `~/.claude/mods/console`; it is loaded through
`CLAUDE_CODE_PLUGIN_DIRS` in `~/.claude/settings.json`. `./board-setup.sh`
generates the installed Claude Code API declarations into the ignored
`.claude-plugin/types/` directory by loading a hook-free stub in watched,
headless mode. Setup requires `claude`, Nix-provided `tsc`, and `timeout` on
`PATH`; it fails if any prerequisite or generated declaration is missing. Run
setup before the console check when working outside the board runner. It registers
the `protocol` tool (`mcp__console__protocol`, stamping session and origin; it
refuses the model the verbs the console relays,
`pending` since the console runs the next pass (r8-q28), and `scope` since the console appends its line to a starting pass's text (r9-q36)), runs the
engine's pending pass and the issued batch's question text (`/console-questions`) at each turn's end, gates and captures round dialogs,
runs a built-in command sent during a turn (`/compact`, which Claude Code delivers to the model as text) when the turn ends,
relays the person's chat messages, presses and a typed or pressed
`/release-round` (conditional approval), and keeps the round through
compaction. Its round features act for lead, solo and autopilot. A `protocol` call reads as two rows in the chat: its arguments and
the engine's headline. Every call may run up to ten minutes (`$.process.run`'s maximum); one that fails or is cut answers the model
with the error and that it may have run in part (read `protocol show` before running it again; a Record step runs again safely).
A press only claims its run: its engine, board, git and VS Code work runs after the press returns (the host cuts a
press hook off after 10 s; a call can wait that long on an embedded board or the session lock a Record step holds).
A change-request or ratification press acts on the request in the row you clicked, with no lookup of its own (land and your session re-check every consequence, and say when it no longer waits; r1-q5, r9-q29).
The one check command: `claude/mods/console/tests/check.sh` (plugin tests, `tsc --noEmit` from `PATH`, `claude plugin validate`; the tests folder is stripped from the installed mod).
Esc at a turn end stops the pass loop; a successful compaction right after reruns the stopped pass once (not a skipped or precompute
one; a pass given up as stuck is never rerun). `/console-continue` (r7-q24) runs the turn-end decision on demand: it queues the pending pass (a stopped, asked-for or noted
run of it included) unless a run of it is queued already (a run the host refused counts as none), reopens the issued batch past the
repeat guard, else wakes the model at the open step with `protocol status --line`; during a turn it runs at the turn's end (Esc drops it); logged as `nudged`. Only a console-started pass counts as the round's pass; invoking a Skill alone does not. A pass skill that starts (console-run or typed command; not a stale queued run, nor a subagent's) gets the engine's scope and first-time report instructions appended to its expanded text; an engine failure leaves the text as it is (r9-q36). The Console pane (`/console` shows it as text;
`/console-item <id>` prints an item's summary in the chat; `/console-questions` prints the issued batch's text) shows Board
(counts, the ready items for you (id, type, title; 3 show, the rest fold behind `+N more`), sessions with runtime and pull initials, `auto` for autopilot,
this session's items under `this session holds`, stale holds, live workers; the counts split by who acts, `you` (for you, to accept, to ratify,
decided, questions) then `agents` (to plan, to design, to implement, to review: what a claim gives each pull, refresh work under review), zeros dim; in a project without a board, a dim `no board` beside the title and nothing else, while a failing board keeps its error), Change requests
(only the requests waiting for you and those in work (being built or under agent review), in the accept-queue order (board-coordination.md#change-request-queue; in-work rows by created); the banner counts `N to accept · N in work · N wait on your answers · N queued` (zero parts left out; waiting on your answers: queued requests whose work unit waits on an unreleased decision), the queued ones listed nowhere in the pane; two lines per request under a legend of the bar colors (design teal, code orange, result blue, in work green; only the kinds present): a bar in the first cell of the title line colored by kind (its hover names the stage), the title in bold and the buttons at the right edge, plain and separated by bullets as in Decide and Actions (Walk through (a design or a result view) or Open (code, `board review open` and then VS Code) in the accent color, Accept in a dimmed green, Return dim, Update in the accent color where a problem's `next.action` is `refresh` (the board's refresh work) in a deciding session, which dispatches the refresh, or a review session, which runs it); every second request sits on a darker stripe (`STRIPE` in `hooks/pane.tsx`, a fixed color made for dark themes); on line two the id dim, the effective priority dim (the hover names what raised it) and `unblocks N` (open work, designs, questions and requests waiting on it directly or through others; milestones and epics not counted) when N > 0, each in a column as wide as the widest shown request, the milestone it is work of dim (it shrinks first on a narrow pane), then flush against the right edge the problem marks the board's `problems` give (setup failed, mid a git operation, review stale, land blocked; `held by …` in warning color), the review mark, the new-failure count only above 0 and the check state unless it is a plain `checks current` or none ran yet, as on a request in work (the opened summary keeps both); the parts stand two cells apart (`PART_GAP` in `hooks/pane.tsx`); a to-ratify row with a landed range has an Open (`board review open` on the ratification) that opens that range on its `ratify/<id>` branch for your review (r10-q50); 3 show, the rest and the to-ratify list fold behind `+N more`; ids show without the board's own prefix, while presses and prompts keep the full id (`board` resolves a bare id to the board prefix); the opened summary adds the accept stage, look, view, the
failure counts, the quiet marks (lands with; `in review` / `in review, edited` while the request is open for your review, read from the row's `review`) and each new failure as a `vscode://file` link), Round: while no run is open and the engine's `next`
offers something, the banner reads `the next step, proposed` over the proposals (one row per proposed round: `[ Start ] <title> · ~N questions ·
unblocks ~M items`, plus `· compacts first` for a
`fresh` round while the context is at 150k tokens or more
(`$.session.usage()`; no reading counts as small, and a compact-only row, a
stored proposal without rounds, shows only then too), the first row recommended
in the theme's `suggestion` color; the summary is a dim wrapping second line, the
model's `why` the Start's hover hint; a click on a row that names ids lists the
leading questions by title, each opening its item; Release Round and a compact-only proposal show here too; none of it while the role is
autopilot, which nobody starts a round or a release for), else the open run (title,
summary, step words, questions: up to 10 of any kind show whole, beyond that 10
show, the asked ones and the 2 latest answered first, then upcoming, held and
older answered ones, and the rest fold behind their toggles; each with their recommendation on hover and, after the title, a mark (`◆
strong`, `your call`, `unverified`), the answer on answered rows (`→ …`, cut;
the title truncates, the answer and marks keep their line) and `↻ <pass>` for
the questions the most recent pass report changed; a release lists its records
with their state, and a stopped release its reason and next round), Controls
(the passes, with the pending one marked next or running; Step Back runs the
full protocol, optionally with a focus, and Ground runs the full ground pass;
Decide (Question Me, Intake running
`/round-intake`, which asks for your list, Continue while a round is open, doing what `/console-continue` does (but an idle press hands a batch to the model to open)
and in the `suggestion` color while the session is idle and nothing has queued or started the pending pass, Challenge Rulings, Explain); Actions,
whose Release Round and Compact take the `suggestion` color exactly when the
proposals offer them, and which hold the role button: Autopilot while solo, Solo while
autopilot, each running the `/role` command (the host refuses a prompt text starting with `/`);
a lead or agent session has none; Release Round is hidden while autopilot) and the round's Log, newest first, the last 10
lines with a `+N more` toggle for the whole round. Every press shows at once: a
pressed command (Actions, Decide, Start, the pass and question buttons) reads `· starting…` after its label until
its skill expands (`· queued` while a turn runs, which the host waits out); a change-request or ratification
press draws its button inverse and its hover hint reads `<verb> · <step>…` (reading the board,
opening your review, opening VS Code) while it works, so no row gains a line (r7-q26), a press meanwhile toasts that one is at work (single flight; a press older than 3 minutes gives way), and a successful Open toasts `<id> is opening in
VS Code (<path>)`, since `code` returns before its window shows; a refusal of `board review open` is the toast, as the board said it. The pane runs no git: Accept and Return read the row's `review` from the board JSON (the tip `review.opened` and `review.edited` for the edits), failing closed when the board showed a review it could not read (`edited` null); edits typed after the board's last read are caught by the board's own refusal of `land` and `return`; every press ends with a board refresh (r3-q14), never one before the action. A retired point (r3-q18) reads `→ my ruling: <ruling>` in the round, its reason in the hover. A click on an item id (board
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
decided ·` with Release Round, or Compact), nothing when nothing is offered (an open dialog does not hide it, r2-q10). Start runs `/start-round <n>` (bare: row 1) without a
stamp: the press is the go-ahead, not an approval like `/release-round`. A row
that compacts first compacts (keeping the proposal's title in the summary), then
starts, whether pressed or typed (a `/start-round` hook answers the typed command
and compacts on a later tick: the host refuses a compaction inside the hook); a
skipped or failed compaction starts nothing and says so with a notice naming the
command.
`/console` prints a line per proposal below the board (`<n>. <first line> ·
<summary> · type /start-round <n>`); the idle-agent notification goes out
once per idle episode across consoles, and so does the accept notification for
a request that newly reaches to-accept (not those waiting when the console
starts; an agent session gets none; its marker goes when the request leaves
to-accept). The model's `protocol` tool reads as one transcript row: the engine's headline, or on a
failed call its reason (`refused: <engine message>` on exit 1, `usage error: <argparse message>` on exit 2);
the model receives the whole result, opening `protocol exited N.`. It idles without a registered role or a
drawing surface and fails open except for recovery. Test it with `claude
plugin test home/patrick/agents/claude/mods/console`.
