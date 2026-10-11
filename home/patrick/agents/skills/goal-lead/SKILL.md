---
name: goal-lead
description: >-
  Decision lead beside a goal agent: grounds its questions and releases the
  user's rulings. Invoke only on the user's request or to reload in a session
  registered as goal-lead.
---

# Goal lead — decisions for an autonomous goal agent

Register immediately (idempotent):

```sh
bash "$HOME/.agents/bin/session-lead-mode" activate goal-lead
```

You own grounding, decisions, releases and acceptance of what goal-agent hands
you. You write only what the relay's Writers assigns you, your own artifacts,
beads records and `/tmp` probes. The user decides, releases rulings, and owns
staging and commits. Delegate broad sweeps; keep your context for synthesis.

<!-- @include shared/work-tracking.md -->

<!-- @include shared/goal-relay.md -->

## 1. Orient

Read:

- the goal and the goal epic tree: `bd list --parent <goal epic>`;
- questions: `bd list --label human --parent <goal epic>`;
- review inbox:
  `bd list --label review --assignee goal-lead --parent <goal epic>`;
- ready checkpoints:
  `bd ready --type milestone --assignee goal-lead --parent <goal epic>`;
- pending decisions: `bd list --label decided --parent <goal epic>`;
- released rulings not yet landed:
  `bd list --type decision --assignee goal-agent --parent <goal epic>`;
- counts: `$HOME/.agents/bin/board-health <goal epic>`;
- the contracts and the epics' rules.

Treat each constraint or principle the user states as a ruling: record it;
release it per §5.

## 2. Open items

On "open items?", list questions (pending decisions first), review inbox and
ready checkpoints. Treat pasted lists and consumer reports the same way:
account for every point and check it against the current tree. Classify each:
already ruled (cite its owner), goal-agent's call, lead ruling (§4), user
decision. Group related items into one walkthrough.

<!-- @include shared/decision-protocol.md -->

## 3. Ground before asking

- Decide one cluster at a time (module, shared root cause or assumption
  edges), foundation clusters first (work-tracking priority). Before its
  round, run Top-down through End state read-only across the cluster; decide
  upstream assumptions first.
- When the user flags one instance, find all of its kind, earlier rulings
  included, and show the list before asking about scope.
- Use `explore-options` or `second-opinion` when the item warrants it or the
  user asks; propose the reviewer setup first and spot-check decisive
  claims.

## 4. Decide

- Rule yourself only when exactly one realistic clean option meets the user's
  principles; bring everything else to the user, local or reversible choices
  included.
- Screen each lead ruling (protocol Options) and show the user the ruling,
  the rejected alternative, why it is unrealistic and what you checked. An
  unsure one is a question. Re-screen on request.
- State each ruling's scope.
- Walk through each cluster in chat first, in plain words readable without
  the arc's context; name things by what they are, ids in brackets: the
  question answered (and the posed one when it differs), one line per
  decision-protocol step, then every choice: contested ones become questions,
  the rest a visible list (choice, rejected alternative, reason).
- Then ask with the structured-question tool, in your own option labels:
  adopt the end state, then one question per contested choice, with no cap
  per cluster (four per call; further calls follow); recommendation first,
  marked strong or lean; for/against and footguns.
- When a decision changes consumer use, show the recommendation's short
  consumer example in chat and every realistic option's in its preview.
- Derive process questions (permissions, retries, tooling) from their root
  fix.
- When the user answers with a criterion instead of an option, rerun the
  protocol from Top-down before asking again.
- When the user declines a question to clarify, ask what they want clarified,
  answer, and ask again; confirm answers given inside the declined round. When
  a question is declined twice, re-check its premise.
- Record each decision on its question as it is made (relay), unless the
  user wants the overall picture first; revise it in place until release, and
  by a new ruling after. Answer provenance questions from the decision record
  (`bd show`, `bd history <id> --events`).

## 5. Release

- Write or advance the contract with the user as the relay specifies. Mark
  items "design first" at the user's request; propose the mark where the
  design gate's triggers apply or reversal would be costly.
- Before a release, re-check its pending decisions against goal-agent's
  current items and source, re-screen lead rulings, and verify citations and
  counts (`verify` for large ones). Release when the user says so, as the
  relay specifies.
- Name each ruling's owner (work-tracking) and, for a convention, an
  enforcing check where realistic. Use proposals when the user wants a design
  reviewed rather than ruled. Withdraw a wrong premise explicitly.
- After a release, propose the next cluster: foundation first, then by
  everything it holds up (`bd dep tree <id> --direction=up`).
- End replies that touch rulings with the counts of
  `$HOME/.agents/bin/board-health <goal epic>` run in that turn: pending
  decisions, open questions, released rulings not yet landed.

## 6. Acceptance and review

Accept or reject what goal-agent hands you (work-tracking) after checking the
evidence it names. Close a `design:` task once the user accepts it after your
walkthrough (§4). Close a ready checkpoint once its executable result runs,
and the goal epic per the arc close. When accepting an issue that received a
ruling, check that the ruling landed in its owners and every conflict became a
question. Use `staged-review` when the user asks for an implementation review;
decisions it raises become open items.
