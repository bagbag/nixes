- Check reuse of existing helpers, types and mechanisms; for more than two new
  ones, delegate one `explore` pass covering all of them when viable,
  otherwise search inline.
- Report refactoring opportunities in touched code and immediate neighbors
  (duplication, near-copies of existing helpers, missing or generalizable
  helpers) with call sites and expected simplification, separate from findings
  and verdicts; the invoker decides on extraction.
