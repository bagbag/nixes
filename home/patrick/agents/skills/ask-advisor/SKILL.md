---
name: ask-advisor
description: >-
  Ask the advisor for refinements and sign-off on the current result.
argument-hint: "[focus and follow-ups]"
disable-model-invocation: true
---

# Ask advisor

<!-- @include shared/rerun.md -->

1. Make the result durable (files written).
   Output: the written paths.
2. Re-read the changed files yourself.
   Output: the files re-read.
3. Ask the advisor for refinements and sign-off; without an advisor tool, ask a
   fresh `second-opinion` agent for strict sign-off.
   Output: the advisor's verdict.
4. Adopt each refinement that is the only realistic clean option; question me
   on the rest.
   Output: adopted refinements; the questions.
5. Report the verdict, adopted refinements and disagreements.
   Output: the report.
