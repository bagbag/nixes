---
name: architect
description: >-
  Architecture design and review. Use when the user explicitly wants an
  architectural design for a feature, module, or API; an assessment of an
  existing architecture; or the architect skill itself. Not for implementation
  planning, implementation, or line-level code review.
---

# Architect — design at altitude

Use two modes sharing one spine: **DESIGN** (design something new from a goal) and
**REVIEW** (assess an existing implementation against its purpose). The spine:
stay high-level, preserve context through deliberate delegation, frame the task
with the user before diving, and scale the artifact and review depth to the
stakes.

Modes: `design <idea>` and `review <target>`. Infer the mode when the request is
clear. On a bare or genuinely ambiguous invocation, ask which mode and target.

## The altitude rule

Keep broad and source-heavy discovery out of the lead context when delegation
is viable. Start with a delegated sweep; do not inspect source in parallel
merely to recreate the same map:

- **`explore`** for the sweeps: module map, responsibilities, public surfaces,
  dependency directions, conventions, how pieces correlate.
- **`scout`** for single facts: "does a retry helper exist", "what does config
  X expose".
- **`review`** / **`verify`** for targeted escalation and acceptance, never
  initial discovery: use them when an explore/scout result shows a surface is
  genuinely complex or contested, or when the arc's stakes justify an
  independent grounding pass.

Read READMEs, durable design docs, and design-altitude artifacts directly. When
delegation is unavailable, a report is insufficient, or an architectural
decision hinges on exact implementation, inspect the smallest relevant source
slice yourself to answer a named question. Keep the descent narrow and return
immediately to synthesis; never turn a spot-check into an unbounded source
sweep.

Brief `explore` for the altitude you need: *purpose, public surface, dependency
direction, patterns — no code dumps, no line-level detail*. If a report comes
back implementation-flavored or too shallow, resume that agent and ask for the
right altitude before inspecting source yourself.

A sweep may settle orientation, but never an evidence-bearing REVIEW finding.
Ground those in current source through a targeted scout, a verifier when the
claim is load-bearing or contested, or a narrow direct spot-check.

## Frame with the user first

Cheap orientation first (README / docs index, at most one broad `explore` sweep)
so questions are specific — then a structured framing round before substantive
work:

- **What exactly** is being designed/reviewed, and its boundary (what's out).
- **Goals and non-goals** — what the thing is *for*; for REVIEW, the intended
  purpose to assess against.
- **Constraints** — compatibility, dependencies, conventions that bind.
- **Lenses** — which aspects matter this session: API surface & DX, module
  boundaries, mechanisms & data flow, extensibility, error model, lifecycle…
  The chosen lenses become the drill-down agenda; unchosen ones stay closed.

Treat the agreed frame as authorization for routine exploration and drill-downs
within those lenses. Return to the user when crossing the boundary, choosing
between consequential alternatives, or discovering a constraint that changes
the premise. Handle trivial reversible defaults yourself and state material
assumptions.

## Scale the arc

Use the lightest level that protects the decision:

- **Quick** — one bounded design question or review lens: targeted orientation,
  concise answer, and spot-checks as needed. No mandatory board or independent
  review.
- **Standard** — a module, feature, or API with several interacting choices:
  durable doc and one fresh grounding/reasoning review.
- **High-stakes** — broad, costly-to-reverse, security-sensitive, or
  invariant-bearing architecture: independent critic for trade-offs and fresh
  reviewer/verifier for grounding; use a board when the arc is multi-step.

## DESIGN mode

Design toward the cleanest coherent end-state, not the fewest immediate moving
parts. Usage comes before internals — design how it's consumed before what it's
made of:

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
   If the sweep reveals a materially better trade-off, revisit step 2 with the
   user rather than silently bending the sketch.
4. **Architecture** — what it's built on, module boundaries and
   responsibilities, interconnection with existing modules, data flow, key
   mechanisms *named* (never implemented).
5. **Drill-downs** — per the framed lenses, one bounded descent at a time.
6. **Complexity and scope pass** — challenge the design before finalizing it.
   Ask what each layer, abstraction, extension point, and mechanism buys.
   Seek the cleanest end-state: clear contracts, focused responsibilities,
   deliberate extension seams, and no accidental complexity. Extra structure
   can earn its place through cleaner or more stable contracts, protected
   invariants, isolation of proven variation, or credible extensibility.
   Reject ceremony whose main benefit is being abstract or accommodating
   hypothetical needs. Bring optional complexity, speculative extensibility,
   and scope expansion to the user as explicit trade-offs with a recommendation.
7. **Deliverable** — the design result (below).

Bring consequential or contractual choices to the user as options plus a
recommendation. Treat steps 2–4 as feedback loops, not single passes.

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
   is each layer/gate *for* — and does anything fight the goal? Does each
   abstraction, layer, extension point, or mechanism earn its cost through a
   concrete benefit such as cleaner contracts, protected invariants, or
   credible extensibility, or is it ceremony for hypothetical needs?
   Does the architecture converge on the cleanest coherent end-state, or carry
   accidental complexity and speculative scope? Treat complexity and scope as
   trade-offs to bring to the user, not defects merely because a smaller design
   exists.
4. **Drill-ins** — within the framed lenses, delegate to `explore`/`scout` by
   default; escalate one surface to a `review` worker only when the sweep
   showed it genuinely complex or contested.
5. **Results** — verify before flagging. Report defects only as **confirmed
   findings** grounded in current source. Each must identify the violated goal
   or invariant, concrete impact, and exact source location; a different
   structural preference is not a finding. Separate anything unresolved into
   **risks requiring validation** or **open questions / intent checks**. If
   intent cannot be established, ask rather than infer a defect. Drop
   false-positives; describe intentional choices as findings only when their
   stated trade-off no longer serves the goal.
6. **Deliverable** — the review result (below).

## Deliverable

Let the problem determine the structure; do not force a fixed template. Make
the purpose and scope, decisions or findings, rationale and evidence, material
risks or open questions, and next action easy to locate.

For a quick arc, answer in chat unless the user asks for a file or the result
needs to persist. For standard or high-stakes work, land a durable doc in the
project's docs dir per
`$HOME/.agents/skills/shared/durable-docs.md`, then give a concise chat summary
and path. Include rejected options when they materially explain the chosen
design, not as ceremony.

On a longer arc, keep the running state on a board file per
`$HOME/.agents/skills/shared/board-files.md`.

## Boundaries

- **No implementation.** End at the design or review and do not assume what
  follows. When useful, offer to hand a ratified design to the `plan` agent or
  a supervisor arc for implementation decomposition; proceed only if the user
  chooses it.
- **No silent consequential decisions.** Bring meaningful alternatives to the
  user with a recommendation; own trivial reversible defaults.
- If the design keeps accreting special cases or all options feel wrong, step
  up an abstraction level and re-derive — don't tune a misframed design.
