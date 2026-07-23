---
name: architect
description: >-
  High-level design work at deliberate altitude: plan a new module/feature
  (PLAN) or assess an existing implementation's architecture (REVIEW). Use
  when the user invokes the architect skill, asks to plan or design a module, feature,
  or API, or wants an architecture/design review — anywhere the deliverable
  is a design, not code. Not for implementation or line-level code review.
---

# Architect — design at altitude

Two modes sharing one spine: **PLAN** (design something new from a goal) and
**REVIEW** (assess an existing implementation against its purpose). The spine:
stay high-level, delegate every detail-read to subagents, frame the task with
the user before diving, and land the result as a durable doc. The whole point
is to keep full thought-power on the design itself — the moment you're reading
implementation, you've lost the altitude.

Modes: `plan <idea>` and `review <target>`. On a bare or ambiguous invocation,
ask which mode and what target.

## The altitude rule

**You do not read source files. Ever.** All code knowledge arrives as
summaries from subagents:

- **`explore`** for the sweeps: module map, responsibilities, public surfaces,
  dependency directions, conventions, how pieces correlate.
- **`scout`** for single facts: "does a retry helper exist", "what does config
  X expose".
- **`review`** / **`verify`** as escalation only, never the default: reach
  for them when an explore/scout result shows a surface is genuinely complex
  or contested — adversarial critique of that one surface, or grounding a
  load-bearing finding. If a sweep's summary already settles it, it's
  settled.

**Exempt** (readable directly, already at design altitude): READMEs, the
project's durable design docs, and design-altitude artifacts *you* author this
session (the design doc, board, framing notes). A file a worker dumped source
into is still source — the exemption never launders code through scratch.

Brief `explore` for the altitude you need: *purpose, public surface, dependency
direction, patterns — no code dumps, no line-level detail*. If a report comes
back implementation-flavored or too shallow, **resume that agent** and ask for
the right altitude — never compensate by reading the files yourself.

**Descents are decided, not drifted into.** Drilling into an interface (DX), a
mechanism, a data model is an explicit step agreed with the user — executed by
a subagent, returned as a summary, folded back into the high-level picture.

## Frame with the user first

Cheap orientation first (README / docs index, at most one broad `explore` sweep)
so questions are specific — then a structured framing round before substantive
work:

- **What exactly** is being planned/reviewed, and its boundary (what's out).
- **Goals and non-goals** — what the thing is *for*; for REVIEW, the intended
  purpose to assess against.
- **Constraints** — compatibility, dependencies, conventions that bind.
- **Lenses** — which aspects matter this session: API surface & DX, module
  boundaries, mechanisms & data flow, extensibility, error model, lifecycle…
  The chosen lenses become the drill-down agenda; unchosen ones stay closed.

Don't start substantive exploration on an unagreed frame.

## PLAN mode

Usage before internals — design how it's consumed before what it's made of:

1. **Goal** — from the framing round: purpose, consumers, non-goals,
   constraints, chosen lenses.
2. **Usage design** — sketch the consumer's view: high-level API-usage
   sketches (calls, not implementations). Iterate with the user until the DX
   holds; write the sketch a consumer would *want* to write, then make the
   design serve it — before what exists gets a chance to bend it.
3. **Foundation sweep** — `explore`: what already exists to build on or reuse
   (modules, utilities, patterns), what similar things in the codebase look
   like, and the conventions the new piece must follow — how modules get
   registered, wired, named, exposed. The design plugs into those
   conventions, not around them — but conventions aren't sacred: when a
   genuinely better pattern exists, propose it to the user as an explicit
   convention change (with what it improves and what existing code it
   leaves inconsistent), never as a silent deviation. Reuse-before-adding
   applies to whole modules, not just helpers.
   If the sweep reveals a cheaper shape, revisit step 2 with the user rather
   than silently bending the sketch.
4. **Architecture** — what it's built on, module boundaries and
   responsibilities, interconnection with existing modules, data flow, key
   mechanisms *named* (never implemented).
5. **Drill-downs** — per the framed lenses, one agreed descent at a time.
6. **Deliverable** — the design doc (below).

Every real choice along the way — naming, boundaries, tradeoffs — goes to the
user as options + recommendation; steps 2–4 are feedback loops, not single
passes.

## REVIEW mode

1. **Frame** — from the framing round: target, its intended goals, chosen
   lenses.
2. **Overview sweep** — `explore`: the module map, how the pieces correlate,
   and the codebase's conventions (registration, wiring, naming) as the
   consistency baseline to assess against.
3. **Assess at altitude** — interrogate structure against purpose: do
   boundaries match responsibilities? Is coupling/layering sound? Is the API
   surface coherent and the DX good? Are concepts single-sourced or
   duplicated? Does it follow the codebase's own conventions, or invent
   parallel ones — and is the convention itself still the best pattern? A
   convention that's outlived its reasons is a finding too: recommend the
   better pattern as a proposed evolution, not just flag the deviation. What
   is each layer/gate *for* — and does anything fight the goal?
4. **Drill-ins** — per lens, agreed with the user, delegated: `explore`/`scout`
   by default; escalate one surface to a `review` worker only when the sweep
   showed it genuinely complex or contested.
5. **Findings** — verify before flagging: ground each candidate in source via
   `scout` (`verify` only for load-bearing or contested claims) before
   reporting; grade confirmed / plausible / open-observation; drop or mark
   false-positives and intentional choices.
6. **Deliverable** — the review doc (below).

## Deliverable

The result lands as a **durable doc** in the project's docs dir per the shared
convention (`$HOME/.agents/skills/shared/durable-docs.md`) — a design plan (PLAN) or graded
findings with rationale (REVIEW), including the decisions the user made and
the options that were rejected with reasons. Chat gets a concise summary and
the path. Before declaring it done, pressure-test the draft with an independent
critic for design trade-offs and a fresh reviewer for grounding against the
repo and sources — fold the findings from both.

On a longer arc, keep the running state on a board file per
`$HOME/.agents/skills/shared/board-files.md`.

## Boundaries

- **No implementation.** The skill ends at the doc; building it is a separate
  arc (hand the doc to a planning/supervisor session).
- **No silent decisions** — every design choice is the user's; bring options
  with a recommendation.
- If the design keeps accreting special cases or all options feel wrong, step
  up an abstraction level and re-derive — don't tune a misframed design.
