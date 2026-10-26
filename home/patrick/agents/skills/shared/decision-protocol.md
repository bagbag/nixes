## Decision protocol

Run before each consequential question, ruling or recommendation. Use one line
per step for a local, reversible choice.

1. **Top-down:** derive intended behavior from the goal and user principles:
   concept, owning module, consumer use.
2. **Bottom-up:** establish current behavior from authoritative sources. Verify
   each premise; use probes or documentation for runtime claims. Probe the
   production path with its real source types, not a stand-in. Show the
   decider only measured figures and verified claims; mark the rest unverified.
3. **Root fix:** identify gaps between intended and current behavior. Resolve
   the question that settles dependent questions; fix the cause of symptoms.
   For each mechanism the framing assumes (conversion, wrapper, listener,
   observer, or a check, approval, grant or stop), ask why it exists and
   whether an upstream owner can produce the right result at its source; a
   mechanism whose need disappears is the root fix. For a proposed guard or
   check, show the concrete failure it catches (code and error) and fix what it
   finds at the cause; the guard only prevents recurrence. A failure an option
   triggers (compiler depth limit, crash, performance cliff) is a clue to a
   defect: name its suspected cause, propose tracking the root-cause search (a
   board item where one exists) and still weigh it against the option.
4. **End state:** derive the smallest clean, coherent result as if designed
   fresh, under the project's quality criterion (e.g. consumer DX for a library),
   independent of effort, churn, earlier rulings, docs and their reasoning;
   list the revisions it implies as information, not cost. Show consumer use,
   size, replacements and breakage. Apply the global instructions' six
   Cleanliness tests and the [End-state criteria](#end-state-criteria).
5. **Options:** compare materially different approaches, including alternatives
   outside the posed framing: rank, decisive trade-offs, strongest downside,
   conditions changing the recommendation. Screen each choice in the selected
   option: behavior, failure handling, naming, exposure, scope limits and
   documented non-features. Construct its strongest alternative. Treat any
   realistic, coherent alternative as contested, even when worse or revising
   an earlier ruling or convention; include alternatives from other sources.
   When realistic scenarios favor different options, add "support both" (a
   default plus an opt-in) as an option.
6. **Premises:** list what the recommendation rests on: facts, consumer
   needs, absences (a gap, an unhandled case, a missing rule or owner),
   current contracts and earlier rulings. Give each its evidence: `path:line`,
   probe output, or the contract or ruling re-derived on its merits with its
   current status (superseded, closed, revised by a later ruling). Verify an
   absence by searching its owner docs and, where a board exists,
   `board related <terms> --docs <paths>`. Verify each unverified premise now
   or ask it first as its own question; base no ruling or recommendation on an
   assumption. Turn each released ruling the end state revises into a
   question.
7. **Decide:** apply [Decision authority](#decision-authority). Bring contested
   choices, options and a recommendation to the decider.

### Decision authority

The decider is the user unless the active role protocol or agent definition
names another; either may adapt the handling. Apply the stricter row when
uncertain.

| Choice | Handling |
|---|---|
| Trivial: reversible, consumer-invisible, sets no convention | Decide; mention in one line. |
| Entailed: no other realistic, coherent alternative; meets ratified goals, constraints and principles without material residual trade-off | Decide; report with one-line reason. |
| Other reversible: semantics, naming, contracts, conventions, trade-offs | Ask the decider. |
| Irreversible, outward-facing or scope-changing | Ask the decider; act only on confirmation. |

Reviewer agreement is evidence, not authority; it settles no product, semantic,
risk or scope trade-off.

### End-state criteria

- Question existing and proposed parts; keep each part that one realistic
  consumer scenario needs, including external library consumers without
  in-repo call sites. Smallness ranks options serving the same uses; it never
  drops a part such a scenario needs. Use in-repo call-site counts to size
  changes, not to establish consumer need.
- For each option, name the consumer or failure each part (log, option,
  status, mechanism) serves, drop parts without one, and roughly estimate its
  size in lines and files.
- Separate required properties from mechanisms; compare mechanisms by those
  properties.
- Reuse platform and module capabilities. For coordination, use platform state,
  lifecycle, failure and retry semantics before parallel state. Follow analogous
  module patterns or state the reason for divergence.
- Justify each added durable concept, abstraction, workflow boundary,
  coordination mechanism or acceptance layer by its current or committed
  consumer, the realistic failure or contract instability it prevents, and why
  existing types, transactions, constraints or focused invariants fall short;
  accept cleaner contracts, protected integrity, proven variation or credible
  extensibility as benefits.
- Implement for a current consumer. For a later committed consumer, keep a clean
  additive path and defer, unless deferral would replace a semantic identity or
  boundary required now or leave a plausible integrity failure.
- Check footguns, failure modes, performance, latency and resource
  retention/leaks.
- Keep implicit behavior ("magic") only where it is the realistic default and
  a real DX win; make the rest explicit.
- Reassess existing designs, documents and decisions against the goal. Retain
  supported commitments; name each revision, its evidence and affected finished
  work.

### Concern classes

| Class | Definition | Handling |
|---|---|---|
| Current blocker | Violates committed behavior, an enduring current contract or realistic integrity under supported workloads. | Blocks acceptance. |
| Deferred committed requirement | Later committed behavior, addable without replacing current architecture. | Record its activation condition; keep out of current scope. |
| Speculative concern | No committed consumer or plausible supported-workload failure. | Labeled observation until evidence justifies action. |

A recommendation expanding structure states its cumulative cost, its effect on
the walking skeleton and why a smaller coherent option fails. When findings
repeatedly add structure without executable progress, re-derive the premise.

### Others' input

- While deciding, prior rulings, docs and contracts are evidence: they never
  narrow the option set or settle an open question. Released rules bind
  implementation until a new ruling revises them.
- At any step, verify others' proposals, options and verdicts against sources
  and the derived end state; form your own option set, treating their
  constraints and framing as evidence, not premises.
- Assess each hybrid independently for retained benefits and combined costs.
- Treat agreement after shared framing or a lead-authored amendment as correlated
  evidence. Distinguish facts from preferences; preserve material disagreement
  and return trade-offs with a recommendation.

### Changed premises

- On a changed problem from a later step, answer or new evidence, restart at
  Top-down and record the changed premise and its effect.
