## Question format

- Ask one question per decision. Present each in chat first: the problem in
  one plain sentence; realistic consumer scenarios (the simple case and each
  case where the options' outcomes differ); every option's for, against and
  footguns, with a short consumer example for code, API or shape choices; the
  recommendation first, marked strong or lean, with any reviewer
  disagreement. Name items in plain words; put ids in brackets.
- Keep the asked question short: one sentence that points to its chat entry
  by number or id, short option labels with a one-line description each, and
  each option's code example as its preview.
- Ask with the runtime's structured-question tool where it has one, using your
  own option labels, four questions per call and further calls for the rest.
  Otherwise number the questions and letter the options so the user can answer
  "1b, 2a".
- Confirm an ambiguous answer term's reading in one line before building on
  it.
- When the user answers with a criterion instead of an option, restart under
  the decision protocol's Changed premises
  (`$HOME/.agents/skills/shared/decision-protocol.md`) before asking again.
- When the user declines a question to clarify, ask what they want clarified,
  answer, and ask again; confirm answers given inside the declined round. After
  two declines, re-check the premise.
