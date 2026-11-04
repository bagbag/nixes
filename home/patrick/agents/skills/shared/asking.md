## Asking the user

Run for every question round and every approval request (ratification, apply);
a release runs the decide protocol's Release instead, whose engine asks the
approval. Give each step's output compactly.

1. **Scope.** Compose the round under the global instructions' Ask in rounds.
   Group by default: take every ready question sharing a premise, root cause,
   consumer concept, flow, or the module and sources its grounding reads; a
   round of a single question names why none shares one. Without a proposal,
   start from the highest-[priority](../shared/board-core.md#priority)
   unblocked question. When the user flagged one instance, find all of its
   kind, including earlier rulings.
   Output: the round's decisions; the instance list where one was flagged.
2. **Check.** In a round run through `protocol` (decide protocol Round), the
   engine sequences the passes and caps the loop: follow its output and report
   each pass's changes in its pass report. Otherwise invoke the
   step-back and ground skills on the whole set, in that order; invoke
   challenge-rulings last, before the questions or the approval request.
   Invoke each through the runtime's skill mechanism (Claude's Skill tool; in
   Codex, read its `SKILL.md`). Scale each pass to stakes: one line for a local,
   reversible round. Repeat step-back and ground over the whole set until a
   pass changes nothing, also after challenge-rulings changes something; a
   changed premise, ruling, option or question set counts as a change. A pass
   that would revise a user's ruling raises it as a question under
   decision-protocol Changed premises.
   Derive process questions from the root fix; step up an abstraction level
   when all options feel wrong. Classify sequencing and process choices as the
   planning session's call.
   Write no chat line for a pass that changes nothing; put its `checked` list
   only in its pass report.
   Output: each invocation and what it changed; what stays unsure, as
   questions.
3. **Walk through.** Outside a round (retro, role, Accept): in chat, readable
   without arc context: items and ids in brackets, the answered question (and
   the posed one if different), one line per decision-protocol step and every
   choice. Define each term, tool feature
   or earlier artifact an option relies on in one clause at first use (what it
   is, where it runs); drop arguments that do not apply to the case. Disclose
   your own rulings: entailed decisions, defect-fix behaviors, dropped or
   narrowed parts, framing choices (excluded options, accepted premises,
   question bundling). Give each its strongest realistic alternative, the
   cleanliness test, principle or correctness property that alternative fails,
   and evidence; scale from one line to a mini decision packet by stakes. In an
   approval request, repeat the list with later rulings.
   In a round, put a term to define in the question's `note` and your own
   rulings in its `rulings`.
   Output: the walkthrough, ending with an offer to ask; in a round, none.
4. **Ask.** Once the user accepts, ask under
   [Question format](#question-format): adopt the end state, then one question
   per contested choice and every ruling you cannot ground, no cap per round.
   Output: the questions.

## Standing rules

- In plans, records, summaries and texts you write, disclose what each choice
  and claim rests on: the user's words, quoted; the evidence that grounds it
  (source, doc, run or ruling); or your call. Verify or ask anything else
  before stating it; quote only what the user wrote.
- End every explanation with an offer to ask.

<!-- @include shared/question-format.md -->
