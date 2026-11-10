---
name: deep-review
description: >-
  Independent adversarial review on a stronger model, same method as review.
  Use for an escalation after the retry limit, a plan, design or contract, or
  work where a bug would be hidden (play, tests and the type checker miss it)
  and costly (a named harm such as to users, data, security or a published
  contract); everyday diff review stays with review. May write the review to
  an assigned path.
effort: high
claude-tools: Agent, Read, Edit, Write, Grep, Glob, Bash, WebSearch, WebFetch, Skill
claude-model: opus
codex-sandbox: workspace-write
codex-model: gpt-6.1-sol
---

<!-- @include shared/review-method.md -->
