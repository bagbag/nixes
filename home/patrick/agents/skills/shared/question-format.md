## Question format

- Ask top-down: direction first (goal, outcome, principle), then the
  criteria and behavior it leaves open, then the remaining specific
  decisions; each level is its own batch, whose answers set the next level's
  premises, and levels the context already settles are skipped. Show each
  option's observable result with concrete cases; where the user cannot state
  a rule, ask a few cases and derive it. Name the decisions each answer
  settles and derive them. Present them for one confirmation per rule (a rule
  question settles the items one answer settles the same way) and per kind,
  never together with board actions, acceptance or release; ask each you are
  unsure is the only realistic clean option as its own question. Write or act
  on them only after that. Ask a mechanism question only where the answers
  leave several clean mechanisms.
- In the walkthrough a rule question gives each settled item one line: how
  the rule applies and its own evidence. An item failing a Recommendation
  strength criterion gets its own question.
- Ask one question per remaining decision. Present each in chat first: the
  problem in one plain sentence; realistic consumer scenarios (the simple case
  and each case where the options' outcomes differ); every option's for,
  against and footguns, with a short consumer example for code, API or shape
  choices; the recommendation first, marked under the decision protocol's
  Recommendation strength, with any reviewer disagreement. Name items in plain
  words; put ids in brackets.
- The asked question is one plain self-contained sentence (no ids, file names
  or option letters), numbered like its chat entry. Option labels are 1-4
  words without letters, each with a one-line description of what changes;
  each option's code example is its preview. Title = the decision it settles
  as a short question, in words a reader without the discussion follows;
  header = a topic noun; a round's summary = its topic in plain words, without
  ids or workflow words.
- Ask with the runtime's structured-question tool where it has one, using your
  own option labels, four questions per call and further calls for the rest.
  Otherwise number the questions and letter the options so the user can answer
  "1b, 2a", or "yes" to accept every recommendation.
- Confirm an ambiguous answer term's reading in one line before building on
  it.
- When the user answers with a criterion instead of an option, restart under
  the decision protocol's Changed premises
  (`$HOME/.agents/skills/shared/decision-protocol.md`) before asking again.
- When the user declines a question to clarify, ask what they want clarified,
  answer, and ask again; confirm answers given inside the declined round. After
  two declines, re-check the premise.
