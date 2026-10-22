## Question format

- Ask one question per decision. Open with the problem in one plain sentence
  and two or three realistic consumer scenarios, including the simple case.
  Name items in plain words; put ids in brackets.
- Give every option its for, against and footguns. Put the recommendation
  first, marked strong or lean, with any reviewer disagreement.
- For code, API or shape choices, show the recommendation's short consumer
  example in chat and each option's example in its preview.
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
