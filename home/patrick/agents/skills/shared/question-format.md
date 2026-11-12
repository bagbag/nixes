## Question format

- Ask top-down: direction first (goal, outcome, principle), then the criteria
  and behavior it leaves open, then the remaining specific decisions. Each level
  is its own batch; skip levels the context already settles.
- Show each option's observable result with concrete cases; where the user cannot
  state a rule, ask a few cases and derive it.
- Name the decisions each answer settles and derive them. Present them for one
  confirmation per rule (a rule question settles the items one answer settles the
  same way), one ruling per confirmation, never together with board actions,
  acceptance or release. Write or act on them only after that.
- Merge questions only when no sensible answer would treat them differently: an
  option that splits them means separate questions, and a shared premise puts
  them in one round, not one question.
- Cut while staging: a board item or point asking several decisions whose
  parts rest on different premises becomes one question per part; ask the
  direction before the details resting on it.
- Ask each derived decision you are unsure is the only realistic clean option as
  its own question; bundle into one question only rulings with no realistic
  alternative.
- Ask a mechanism question only where the answers leave several clean mechanisms.
- In the walkthrough a rule question gives each settled item one line: how
  the rule applies and its own evidence. An item failing a Recommendation
  strength criterion gets its own question.
- Ask one question per remaining decision. Outside a round, present each as a
  turn's last text and ask in the next turn: the
  problem in one plain sentence; realistic consumer scenarios (the simple case
  and each case where the options' outcomes differ); every option's for,
  against and footguns, with a short consumer example on every option of a
  code, API, naming or shape choice; the recommendation first, marked under
  the decision protocol's Recommendation strength, with any reviewer
  disagreement. Name items in plain words; put ids in brackets.
- The asked question is one plain self-contained sentence (no ids, file names
  or option letters), numbered like its chat entry. Every option is an
  answer, not a request. Option labels are 1-4 words without letters, each
  with a one-line description of what changes.
  Code examples go in the chat entry; dialogs carry no previews. Title = the
  decision it settles as a short question, in words a reader without the
  discussion follows; header = a topic noun; a round's summary = its topic in
  plain words, without ids or workflow words.
- In printed question text, say what is decided and what each option means for
  the person (what they would see, what it costs), each thing once, in plain
  words. Keep how it was found (sources, measurements beyond the deciding
  number, who said what) and how it gets built for the record.
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
