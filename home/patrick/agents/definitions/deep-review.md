---
name: deep-review
description: >-
  Independent adversarial review on a stronger model, same method as review.
  Use only on escalation from a review, at the retry limit, or on the user's
  request. May write the review to an assigned path.
effort: high
claude-tools: Agent, Read, Edit, Write, Grep, Glob, Bash, WebSearch, WebFetch, Skill
claude-model: opus
codex-sandbox: workspace-write
codex-model: gpt-6.1-sol
---

<!-- @include shared/review-method.md -->
