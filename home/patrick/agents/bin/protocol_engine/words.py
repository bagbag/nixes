"""Every text the engine prints for a model or the person: step texts, notes, report formats, headlines and log lines. The
model is hooks/words.ts in the console mod. A text is a constant, or a function taking the plain values it interpolates;
the modules decide what to say and call it. Error and refusal messages stay where they are raised, as do texts written to
board items and record files (record_file, parked_text) and the CLI help. Imports base only."""
from __future__ import annotations

import re

from .base import (
    ALL_LENSES, AWAY, BATCH, CHECK_CAP, DESCRIPTION_MAX, HEADER_MAX, LIST_COMMAND, PROPOSAL_ROUNDS, SEEDS, STRONG_CRITERIA, SUMMARY_MAX,
    TEXT_LIMIT, TEXT_MAX, THINK_MORE, TITLE_MAX, cut, json_block, lines, plural
)


# Shared pieces.

MERGE_TEST = ('Merge questions only when no sensible answer would treat them differently: an option that splits them means separate '
              'questions, and a shared premise puts them in one round, not one question.')  # skills/shared/question-format.md owns the test
LEAN_JOB = ' (the lean pass: aim each lean named in the argument at strong, decision-protocol.md Recommendation strength).'
HAND_OVER = 'End your turn with one short line: what changed, or "No change." The console runs the next pass, not you.'  # r8-q30
PICK_DETAIL = ('Count a pick as the answer when the rest of the reply or note questions only a detail the pick doesn\'t hinge on; '
               'leave the question open only when the doubt could change the pick. Record the pick (typed: the ["answer"] call with '
               'the option\'s label), then add the detail as a new question through `protocol edit` instead of folding it into the '
               'picked one; the pick\'s record names that question.')  # answer first: an edit sends a typed question out again
THINK_MORE_LINE = ('No answer yet: its checks redo it aiming for a strong recommendation, with a consumer walk and a probe, '
                   'then it comes back.')  # the consumer walk and the probe are the lean pass's (r38-q213)


def report_hint(example) -> str:
    return f'Report with `protocol step` (stdin JSON), e.g. {json_block(example)}'


# Round: the Check step (round.py).

def codex_pass(command: str, args: str) -> str:
    scope = f'with the argument `{args}` (lenses, the questions to strengthen, then any focus)' if args else 'on the whole round'
    return f'Run the {command} skill now {scope} (read its SKILL.md), then report the pass.'


def same_options(ids: list[str]) -> str:
    named = f"{', '.join(ids[:-1])} and {ids[-1]}"
    return f'{named} offer identical options. Merge them only if no sensible answer would treat them differently.'


def check_paused(round_id: str, cycle: int) -> str:
    return f"Round {round_id} · Check paused by the user at cycle {cycle}. `protocol resume` continues it."


def check_row(q: dict) -> str:
    return (f"- {q['id']} {q['status']}{' (' + q['kind'] + ')' if q['kind'] != 'decision' else ''}: {q['text']}"
            + (f" — {held_detail(q)}" if q['status'] == 'held' else ''))


def questions_counted(n: int, changed: int) -> str:
    return f'{plural(n, "question")}, {changed} listed above as new or changed (protocol show lists them)' if changed else f'{plural(n, "question")}, none changed (protocol show lists them)'


def check_title(round_id: str, cycle: str | None) -> str:
    """`cycle`: `n/cap` for Codex, which reads the pass sequence; Claude's model does not."""
    return f"Round {round_id} · Check" + ('' if cycle is None else f' cycle {cycle}')


CHECK_AFTER_ANSWERS = (' (after the last answer: challenge your own rulings in this round and what the open questions take from the answers, not the strong marks of answered questions; a finding is a new question, '
                       'checked before it is asked).')
CHECK_PLAIN = '.'
CHECK_LAST = ' (last before the batch).'
CHECK_PATH_NOW = " (the round's path pass: goal and foundations, before the drafts settle)."
CHECK_OPTIONS_NOW = " (the round's options pass: radically different ways to the outcome, before the drafts settle)."
CHECK_REFINE_NOW = " (the round's refine pass: the lenses named in the argument)."


def check_raised(ids: list[str]) -> str:
    return f" (the strong recommendation raised on {' '.join(ids)})."


def check_path_scoped(ids: list[str]) -> str:
    return f" (the path pass on the restarted questions {' '.join(ids)}: goal and foundations)."


def check_options_scoped(ids: list[str]) -> str:
    return f" (the options pass on the restarted questions {' '.join(ids)}: other ways to the outcome)."


def check_refine_scoped(ids: list[str]) -> str:
    return f" (the refine pass on the restarted questions {' '.join(ids)}: the lenses named in the argument)."


# Check: pass arguments, the cap dialog and the report formats (check.py).

def think_more_goal(head: str, ids: list[str]) -> str:
    """The Think more goal appended to a pass argument (r38-q213): one line without quotes, so a typed rerun matches it."""
    many = len(ids) > 1
    return (f"{head}; Think more on {' '.join(ids)}: the lean{'s' if many else ''} fell short, try to get "
            + ('reasoned strong recommendations' if many else 'a reasoned strong recommendation'))


CAP_HEADER = 'Check cap'
CAP_DESCRIPTIONS = {'Continue': f'{CHECK_CAP} more step-back and ground cycles', 'Ask now': 'Ask the current questions as they stand',
                    'Pause': 'Stop the loop; protocol resume continues it'}  # by CAP_CHOICES label


def cap_question(round_id: str, cycle: int) -> str:
    return f"Round {round_id}: the check loop ran {cycle} cycles and still changes the questions. How to go on?"


WAITS_FOR = ('`waitsFor` names the outside result a question waits for (a spike, a review, the person\'s own try, another '
             'session\'s ruling) and where it lands: it holds the question out of the batches. Set it to null once the result is in; '
             'the question is checked again before it goes out. Still waiting at Record, it is deferred with the questions that wait on it.')


def held_detail(q: dict) -> str:
    """What a held question waits on: its premise questions, the outside result it waits for (r8-q31), or both."""
    return '; '.join([*([f"waits on {', '.join(q['waitsOn'])}"] if q.get('waitsOn') else []),
                      *([f"waits for {q['waitsFor']}"] if q.get('waitsFor') else [])])


def pass_format(command: str) -> str:
    return lines(
        'After the pass, report each change as a per-question update: changed fields, a new question (no id; it goes last, '
        'or ahead of the question its `before` names), or '
        '{"id", "remove": true, "reason"}; report an empty list when nothing changed. Raise a change that would revise a '
        "user's ruling as a new question. "
        f'{WAITS_FOR} Name a hold you set for your own spike or review in `summary`. {MERGE_TEST} A merge is one rule question (`settles`: the keys it settles); split an item out when the rule\'s application to it is open. '
        f'A question that widens the round\'s scope: list the open items with `{LIST_COMMAND}`.',
        'Key `checked` by question: for each id the step names as this pass\'s scope, what you examined in it this run, one line of about 120 characters (an update '
        'to it covers it too); `round` holds a round-wide note, the only entry an empty scope needs.',
        'Report with `protocol step` (stdin JSON), e.g. ' + json_block({
            'pass': command, 'updates': [{'id': 'q1', 'premises': '<revised premise>'}],
            'checked': {'q2': '<what you examined in it this run>', 'round': '<optional round-wide note>'},
            'summary': '<one line: what the pass found>'}))


def pass_scope(ids: list[str], strong: list[str] | None) -> str:
    """The pending pass's scope (r4-q15, q16); `strong`: the strong ids a challenge-rulings pass re-derives, None for other passes."""
    head = (f"This pass covers {' '.join(ids)}: a `checked` entry (what you examined in it this run) or an update for each."
            if ids else 'Nothing changed since this pass last ran: `checked` needs only a `round` note.')
    if strong is None:
        return head
    verdicts = (f" In `verdicts`, re-send the `strongBecause` of each of {' '.join(strong)}, re-derived this run, or lower it to lean."
                if strong else '')
    return head + verdicts + ' List your own rulings in `rulings` (an empty list when there is none).'


def start_scope(ids: list[str], strong: list[str] | None, explored: list[str]) -> str:
    """The scope as the pass starts (r9-q36), appended to its expanded skill text: pass_scope's line, which it supersedes, and
    for an options pass the ids `explored` covers."""
    return (f"Use this scope, not one printed earlier. {pass_scope(ids, strong)}"
            + (f" Give `explored` an entry for each of {' '.join(explored)} and no other." if explored else ''))


def challenge_format() -> str:
    """challenge-rulings adds `verdicts` and `rulings` to its report: told apart from the pass format, like the options pass's."""
    return ('Add to a challenge-rulings report `verdicts`: for each strong question the step names (answered ones after the last answer are not), its `strongBecause` re-derived '
            'this run (an update lowering it to lean or re-sending it covers it too); and `rulings`: each own ruling in this round as '
            '{"question", "ruling", "why", "alternative", "fails", "evidence", "sure": true or false}, an empty list when there is '
            'none. e.g. ' + json_block({
                'pass': 'challenge-rulings', 'updates': [], 'checked': {'q2': '<what you examined in it this run>'},
                'verdicts': {'q2': {'strongBecause': {name: 'true: <evidence>' for name in STRONG_CRITERIA}}},
                'rulings': [{'question': 'q2', 'ruling': '<your ruling>', 'why': '<what it meets without a material trade-off>',
                             'alternative': '<its strongest alternative>', 'fails': '<the test the alternative fails>',
                             'evidence': '<source, run or item>', 'sure': True}],
                'summary': '<one line>'}))


def options_format() -> str:
    """The options pass adds `explored` to its report: told apart from the pass format, which a session is told once."""
    return lines(
        'The options pass also reports `explored` (its entries cover its questions): for each question the argument covers, the radically different ways you found '
        '(other mechanisms, other owners, removing the need; not variants) as {"idea", "verdict": "kept" or "dropped", "why"}, or '
        'one sentence saying why no other way exists. A dropped idea names the stated constraint or sourced fact that rules it out '
        'and prints under the question\'s options; a kept one shows in the options or the recommendation. e.g. ' + json_block({
            'pass': 'step-back', 'updates': [], 'explored': {'q1': [{'idea': '<another mechanism>', 'verdict': 'dropped',
                                                                      'why': '<the constraint or fact>'}], 'q2': '<why no other way exists>'},
            'checked': {}, 'summary': '<one line>'}))


# Pre-pass (prepass.py).

PREPASS_EXAMPLE = {'pass': 'step-back', 'summary': '<one line: what the pre-pass found>',
                   'points': [{'id': 'pt1', 'text': '<reworded or split-off part>'}, {'id': 'pt2', 'drop': True, 'reason': '<why>'},
                              {'text': '<new point or finding>', 'first': True}, {'id': '<open item id>', 'first': True}],
                   'verdict': '<with a --subject: its verdict>'}


def prepass_instructions(round_id: str, subject: str | None, codex: bool, args: str, rows: list[str]) -> str:
    return lines(
        f"Round {round_id} · Pre-pass (decide.md Round 1): a step-back over the whole point set. "
        + (f'Run the step-back skill now with the argument `{args}` (read its SKILL.md), then report the pass.' if codex else HAND_OVER),
        '- Judge the direction, the points that are off or rest on an unclear premise (asked first), and the cut under question-format.md.',
        *([f"- Subject: {subject}. Report its verdict and findings (findings are points); for a design, re-ground it against current "
           'source and make drift its own finding.'] if subject else []),
        '- The point set:' if rows else '- The point set is empty: a finding or a missing point is a new one.',
        *rows,
        '- `points` entries: no `id` adds a point; a pasted point\'s `id` rewords it (`text`) or drops it (`drop`, `reason`); a split '
        'rewords one part and adds the others; `first` marks a pasted point or open item to ask first.')


# Collect and Select (collect.py).

VIEW_LABELS = {  # the views Collect offers, in listing order (`collect_enter`): heading, name in the counts
    'decided': ('decided, awaiting release', 'decided'), 'questions': ('open questions', 'open questions'),
    'ratification': ('awaiting ratification', 'awaiting ratification'), 'toAccept': ('to accept (designs in review)', 'to accept'),
    'toReview': ('to review (work in review)', 'to review'),
    'forUser': ('waiting on the user', 'waiting on the user'), 'readyMilestone': ('ready milestones', 'ready milestones'),
    'finishedEpic': ('finished epics (close one whose acceptance names the user)', 'finished epics'),
}


def item_row(item: dict) -> str:
    return (f"- {item['id']}" + (f" [{item['type']}]" if item.get('type') not in (None, 'decision') else '')
            + (f", held by {item['heldBy']}" if item.get('heldBy') else '') + f": {item['title']}")


def items_whole(total: int, named: list[str] | None, groups: list[tuple[str, str, list[dict]]], waiting: list[dict],
                elsewhere: dict[str, list[str]]) -> str:
    """The open-item list, whole: `groups` are (heading, status, rows) in listing order."""
    out = [f'Open items ({total}):'] + ([f"Named for this round: {', '.join(named)}."] if named else [])
    for heading, status, rows in groups:
        out += [f'{heading} · {status} ({len(rows)}):', *map(item_row, rows)]
    if waiting:
        out += [f'waiting on the user · held by the user, not offered ({len(waiting)}):', *map(item_row, waiting)]
    out += [f"Held by live session {holder}, not offered: {', '.join(ids)}" for holder, ids in elsewhere.items()]
    return '\n'.join(out)


def items_counted(named_rows: list[dict] | None, counts: str, bare: bool) -> str:
    """The open-item list after it was told: the named items, the counts per kind and the command that lists them again."""
    return lines(
        *(['Named:', *map(item_row, named_rows)] if named_rows is not None else []),
        f'Open items: {counts or "none"} (listed earlier). List them again with `{LIST_COMMAND}`, '
        'and `board position` for the ready milestones and finished epics.' + (' List them before you select.' if bare else ''))


GROUP_BY = 'every ready question sharing a premise, root cause, consumer concept, flow, or the module and sources the grounding reads'
GROUP_STEER = f'Group by default: the round takes {GROUP_BY} (`board related` finds them); a round of a single question names why no other shares one.'


def collect_intro(round_id: str) -> str:
    return (f"Round {round_id} · Collect (decide.md Round 1): classify every pasted point and the board items in this "
            "round's scope (asking.md Scope): ruled (cite its owner), planning (the planning session's call), own (your "
            "ruling), user (the user's decision); unclassified board items stay out of this round. Check pasted points "
            "against the current tree.")


def collect_topic(topic: str) -> str:
    return f'Topic: {topic}. {GROUP_STEER}'


def collect_empty(has_board: bool) -> str:
    return '- (no open items' + ('' if has_board else ': no board here') + '; add pasted points)'


def collect_point(point: dict) -> str:
    return f"- {point['id']} [pasted]: {point['text']}"


def collect_unclassified(missing: list[str]) -> str:
    return f"Unclassified pasted points: {', '.join(missing) or 'none'}."


COLLECT_EXAMPLE = {'classes': {'<id>': {'class': 'ruled', 'owner': 'docs/x.md#rule'}, '<id2>': 'user'},
                   'points': [{'text': '<another point>', 'class': 'user'}]}


def select_row(key: str, priority, klass, blocked_by: list[str], title: str, first: bool = False) -> str:
    return (f"- {key} p{priority} ({klass})" + (' ask first' if first else '')
            + (f" waits on {', '.join(blocked_by)}" if blocked_by else '') + f": {title}")


def select_intro(round_id: str, topic: str | None, single: bool) -> str:
    return (f"Round {round_id} · Select one round (asking.md Scope)"
            + (f" on the topic: {topic}" if topic else '')
            + f': {GROUP_BY}, a named question leading; ' + ('a round of a single question names why no other shares one. ' if single else
                                                             'start from the highest-priority unblocked question. ')
            + 'Candidates in order:')


SELECT_NONE = '- none: report {"select": []} to close the round'


# Stage and Related (stage.py).

def stage_instructions(round_id: str, selected: list[str], has_board: bool, proposed: bool, first: list[str] | None = None) -> str:
    """`proposed`: the round took its title and summary from a stored proposal; `first`: the selected keys the pre-pass marked to ask first."""
    return lines(
        f"Round {round_id} · Stage the questions for {', '.join(selected)} under asking.md Question format"
        + (". The round keeps the proposal's `title` and `summary`; report a `round` with both to replace them "
           "where the selected questions differ from the proposal." if proposed else ', with a round `title` and `summary`.'),
        '- Ids: a board item keeps its id in `board`; a pasted point or new '
        'question is a draft (`board`: null, `for`: the point id)' + (', created on the board at Record' if has_board else '') + '.',
        '- `settles` lists the items '
        f'one answer settles the same way (a rule question); an open decision outside the selection named there or in `board` joins the round. {MERGE_TEST}',
        f'- `waitsOn` names the questions a decision rests on; it holds a dependent back until its premise is answered; {WAITS_FOR}',
        '- Cut under question-format.md: the first part keeps the item in `board`, the others are drafts (`for`: the item or point id); '
        'a detail `waitsOn` the direction it rests on.',
        *([f"- Asked first (the pre-pass): {', '.join(first)}; the questions resting on them wait on theirs."] if first else []),
        '- Each question carries the parts the '
        'engine prints before its dialog, in your own words. Printed parts say what is decided and what each option means for the person '
        '(what they would see, what it costs), each thing once, in plain words; how it was found (sources, measurements beyond the deciding '
        'number, who said what) and how it gets built go to the record.',
        '- Required: `problem` (what is decided and why now) and per option `for` and `against`; '
        'on every option of a code, API, naming or shape choice, an `example`: a few lines of the code as written under that option, printed below it (question-format.md).',
        '- Optional, printed only when present: `cases` (the concrete cases that must and must not work), `premises` (what it rests on), '
        '`rulings` (each ruling of yours with why it meets the goals without a material trade-off, its strongest alternative, what that fails and the evidence, which only the record keeps) and `note` (a term to define, anything else); '
        'a round may carry one `overview` line across '
        'its questions. A rule question\'s `premises` says how the rule applies to each settled item; the engine prints each item\'s id and title.',
        '- Mark each recommendation '
        'under decision-protocol.md Recommendation strength: strong sets `strongBecause` '
        f"{', '.join(STRONG_CRITERIA)} each to \"true: <evidence>\" (\"does-not-apply: <reason>\" for consumerWalk "
        'and rulingsChallenged); lean sets `leanBecause` with cause preference (`detail`: what it depends on; `flipsIf`: what you would have to value '
        'to pick another option) or evidence.',
        '- `priorRulings` holds one entry per released ruling a recommendation rests on or Related linked: '
        '{"ruling", "verdict": "holds" or "fails", "why"}; judge the options as if no ruling existed first; an answer from this round stays a premise.',
        f'- Order: questions go out in the listed order, {BATCH} at a time.',
        f'- Lengths in characters and who reads each field: round `summary` {SUMMARY_MAX} (pane header); `title` {TITLE_MAX} (pane row; a question\'s '
        f"is also the board item's title); `text` {TEXT_MAX}, without a number (the engine numbers the dialog; it is the dialog "
        f"question and the board item's Question); `header` "
        f'{HEADER_MAX} (dialog chip); option `label`, `description` {DESCRIPTION_MAX}.')


def stage_dropped(dropped: dict[str, str]) -> list[str]:
    return ['A release dropped or held back these records earlier (the reason says what changed; ask what it leaves open):',
            *(f'- {key}: {reason}' for key, reason in dropped.items())]


def stage_example(first_selected: str | None) -> dict:
    return {'round': {'title': '<what this round decides>', 'summary': '<the topic in plain words>',
                      'overview': '<optional: one line across the questions>'},
            'questions': [{'key': 'a', 'board': None, 'for': first_selected,
                           'settles': [], 'text': '<question>?',
                           'title': '<the decision as a short question>', 'header': '<topic noun>',
                           'kind': 'decision',
                           'problem': '<what is decided and why now>', 'cases': '<optional: the cases that must and must not work>',
                           'options': [{'label': 'A', 'description': '…', 'for': '<for>', 'against': '<against>',
                                        'example': '<code under A>'},
                                       {'label': 'B', 'description': '…', 'for': '<for>', 'against': '<against>',
                                        'example': '<code under B>'}],
                           'premises': '<optional: grounded premises>', 'rulings': [{'ruling': '<your ruling>', 'why': '<what it meets, why no material trade-off remains>', 'alternative': '<strongest alternative>',
                                                                                    'fails': '<what it fails>', 'evidence': '<source>'}],
                           'note': '<optional>', 'recommendation': 'A', 'strength': 'lean',
                           'leanBecause': {'cause': 'evidence', 'detail': '<the unchecked fact and how to check it>'},
                           'waitsOn': []}]}


def related_instructions(round_id: str) -> str:
    return lines(
        f"Round {round_id} · Related: each new draft's board hits need an outcome before asking:",
        '- duplicate or extend: the question takes that item over, in place (the same question answered again);',
        '- relate: link at Record;',
        '- supersedes: a different question, or one replacing several records; Record closes each decided record it '
        'replaces once the answer is recorded, and opens a released one as a revision, replaced at release; a change to '
        'one clause is no replacement;',
        '- unrelated.',
        'Mark `supersedes` on any decided record the question replaces, a hit or '
        'not (name the id under outcomes). Inspect with `board show <id>`; comment on or hand off overlaps '
        'other sessions hold. Also search the exact names of the modules, APIs and sibling cases the options build on '
        f'(`board related <terms>`). A hit that widens the round: list the open items with `{LIST_COMMAND}`.')


def related_row(q: dict, hit: dict) -> str:
    return f"- {q['id']} ({q['title']}) overlaps {hit['id']}"


# Ask: the dialog and the Ask step (ask.py).

def lean_cause(because: dict) -> str:
    """What a lean recommendation depends on: an unchecked fact (`evidence`) or the person's call."""
    return 'Unverified' if because.get('cause') == 'evidence' else 'Your call'


def lean_description(because: dict, description: str) -> str:
    """The recommended option's description in the dialog, opening with what the lean rests on."""
    return f"{lean_cause(because)}: {because.get('detail')}" + (f' — {description}' if description else '')


def dialog_text(text: str, replaced: str, number: int | None) -> str:
    text = f"{text} {replaced}".rstrip()
    return f'{number}. {text}' if number else text


def replaced_text(closes: list[str], revised: str | None, named) -> str:
    """The records a question replaces, added to the dialog's question text; `named` gives an id with its title."""
    return '; '.join(filter(None, [f"Recording it closes {', '.join(map(named, closes))}" if closes else '',
                                   f"{named(revised)} is replaced at release" if revised else ''])) + ('.' if closes or revised else '')


def not_asked(broken: dict[str, str]) -> str:
    return 'Not asked yet: ' + '; '.join(broken.values()) + f". Fix {', '.join(broken)} in a pass of its " \
           'own: call the ground skill on it (that Skill call counts as the observed run), then report the pass.'


EDIT_STDIN = '{"updates": [...], "quote": "<the user\'s exact words>"}'
CHAT_STDIN = '{"question": "<q id>", "answer": "<the answer>", "quote": "<the user\'s exact words>"}'
EDIT_WORDS = 'a question the edit adds or whose recommendation it changes is checked before it is asked.'
EDIT_FORMAT = f'Edit format: `protocol edit` with stdin {EDIT_STDIN}.'
CHAT_FORMAT = f'Chat answer format: stdin {CHAT_STDIN}.'


def away_ask_row(q: dict) -> str:
    return f"- {q['id']}: {q['text']} Recommendation: {q.get('recommendation')} ({q.get('strength')})"


def away_ask_intro(round_id: str) -> str:
    return (f"Round {round_id} · Ask (away: the role is autopilot, so no dialog opens, nothing prints and the person is not asked). "
            'Settle each question by the Authority classes of unattended.md: `act` takes the recommendation as the answer (Record then asks '
            'its rationale, rule owner and reversal), `park` leaves it open and unassigned on the board for the person; a question waiting '
            'on a parked one parks with it. If the person is back, run `session-lead-mode activate solo` first.')


def settle_example(first: list[str]) -> dict:
    return {'settle': {qid: 'act' for qid in first} | {'<id>': 'park'}}


def ask_reading(round_id: str) -> str:
    return (f"Round {round_id} · Ask: the next batch waits for your reading of the user's reply: then `protocol step` "
            'with {} (or a pass report) issues it.')


def ask_no_batch(round_id: str) -> str:
    return f"Round {round_id} · Ask: no batch out. `protocol step` with {{}} issues the next one."


def ask_order(numbered: bool) -> str:
    return ', in this order' + (', numbered like the dialog' if numbered else '')


CONSOLE_OPENS = ('write one short line that questions are coming, nothing about their content, and end your turn; a message tells you when you have something to do. '
                 'After a reply the person typed instead of picking: answer it as the turn\'s last text and end the turn. '
                 'If a console message asks you to open the dialog: call AskUserQuestion with the input `protocol show` gives.')


def ask_lead(round_id: str, marker: str, cap: bool, codex: bool, numbered: bool) -> str:
    return f"Round {round_id} · " + (f"Check cap reached: {'ask the user how to go on.' if codex else CONSOLE_OPENS}" if cap else
                                     f"Ask batch {marker}" + (f' (show the user the text below first, then ask{ask_order(numbered)}).' if codex else f': {CONSOLE_OPENS}'))


def approval_why(reasons: list[str]) -> str:
    return f" The dialog stays short; why it asks: {'; '.join(reasons)}."


def codex_answer_how(marker: str, first_question: str) -> str:
    return ('Then record the reply: `protocol answer --origin model-reported` with stdin '
            + json_block({'marker': marker, 'answers': {first_question: "<the user's own words, quoted verbatim>"}})
            + ". Key each answer by the question's exact text and quote only what the user wrote; leave out questions "
            'the user did not answer. If the user declines, run `protocol decline --origin model-reported` with stdin '
            + json_block({'marker': marker, 'partial': None}) + '. To apply a change the user asked for to a question, '
            f'run `protocol edit` (stdin {EDIT_STDIN}); ' + EDIT_WORDS)


def codex_answer_again(marker: str) -> str:
    return f"Record the reply as before: `protocol answer --origin model-reported` (or `decline`), marker {marker}."


def text_to_show(notice: str) -> str:
    return f'Text to show first:\n{notice}'


def ask_exactly(batch_questions: list[dict]) -> str:
    return f'Ask the user exactly these questions: {json_block(batch_questions)}'


def dialog_input(order: str, tool_input: dict) -> str:
    return f'AskUserQuestion input{order}: {json_block(tool_input)}'


def claude_answer_how(first_id: str | None) -> str:
    return (f'To apply a change the user asked for to a question before they answer, use `protocol edit` (stdin {EDIT_STDIN}); '
            + EDIT_WORDS +
            ' A pass report updates questions only for a pass.\n'
            'Record an answer the user types in chat with the protocol tool\'s ["answer"] (through Bash, `protocol '
            'answer --origin chat`) and stdin '
            + json_block({'question': first_id if first_id else '<q id>', 'answer': '<the answer>',
                          'quote': "<the user's exact words>"}) + '.')


def approval_reasons(rulings: list[dict] | None, records: list[dict]) -> list[str]:
    """Why the approval is asked (unsure rulings, revised records, records that left the set): for the model and the Log."""
    return [f"unsure: {x['record']} {x['ruling']}" for x in rulings or [] if not x['sure']] + \
           [f"revised: {rec['id']} ({rec['change']})" for rec in records if rec['state'] == 'revised'] + \
           [f"left the set: {rec['id']} ({rec['reason']})" for rec in records if rec['state'] in ('dropped', 'changed')]


# Record, Closed and the notes around them (record.py).

def record_row(q: dict, note: str | None, prior: str | None = None) -> str:
    return (f"- {q['id']}{' ' + q['board'] if q['board'] else ' (draft)'}: {q['text']}\n  answer ({q['origin']}): "
            f"{q['answer']}" + (f"\n  note: {note}" if note else '')
            + (f"\n  revises the record on its item in place: it keeps that record's Question and Alternatives; give `decision` "
               "and `rationale` for the revised record. The record now:\n"
               + '\n'.join(f'    {line}' if line else '' for line in prior.strip().splitlines()) if prior else '')
            + (f"\n  rule question, settles {', '.join(q['settles'])}: name each in the rationale or decision with how the "
               'rule applies' if q.get('settles') else '')
            + (f"\n  recording closes {', '.join(q['replaces'])}: name each in the rationale or decision with what the new "
               'record keeps or changes' if q.get('replaces') else '')
            + ('\n  away answer: the record also needs `reversal`, the steps that undo it (a `## Reversal` section; the record is '
               'written as needs_ratification)' if q['origin'] == AWAY else ''))


def waits_on_deferred(premise: str, reason: str, outside: bool) -> str:
    """Why a question whose premise waits on an outside result is deferred with it at Record (r8-q31)."""
    return f"waits on {premise}, which " + (f'waits for {reason}' if outside else reason)


def record_deferred(qid: str, reason: str, outside: bool) -> str:
    """A question Record defers because it still waits on an outside result (`outside`), or on a question that does."""
    return f"- {qid}: deferred at Record, it " + (f'waits for {reason}' if outside else reason)


def revise_needs_decision(qid: str, item: str) -> str:
    return (f"records.{qid}: {item} already holds a decision record, which this one revises in place: give `decision`, "
            'the revised Decision (the record step prints the current one)')


def record_intro(round_id: str) -> str:
    return (f"Round {round_id} · Record (board-coordination.md#rulings). Check each answer against the option's "
            'wording; an answer stating a criterion restarts the affected questions instead (`protocol restart <ids>`).')


RECORD_GIVE = ('Give each a rationale and its rule owner; decision and alternatives default to the answer and the options '
               'not chosen. A question the user deferred goes under `defer` with the reason.')


def record_example(first: list[dict]) -> dict:
    return {'records': {q['id']: {'rationale': '<why, with provenance>', 'ruleOwner': '<path#anchor>',
                                  **({'reversal': '<the steps that undo it>'} if q['origin'] == AWAY else {})}
                        for q in first}, 'defer': {}}


def not_recorded(errors: list[str]) -> str:
    return 'Not recorded (fix and report again; recorded questions stay recorded):\n' + '\n'.join(errors)


def claims_not_released(error, release: list[str]) -> str:
    return f"Claims not released ({error}); run `board unclaim {' '.join(release)}`."


def counts_unavailable(error) -> str:
    return f'Board counts unavailable ({error}); run `board health`.'


def supersede_exited(old: str, item: str, returncode: int, output: str) -> str:
    return f"`board supersede {old} --with {item}` closed {old} but exited {returncode}: {output}"


def abandoned_records(kept: list[str]) -> str:
    """What an abandoned round leaves behind: records written before the abandon stay decided (r24-q108)."""
    return f"recorded {', '.join(kept)} stay decided" if kept else 'nothing recorded'


def board_line(counts: dict | None, has_board: bool) -> str:
    """The board's counts as last read (`counts` None: not read this run)."""
    if not counts:
        return 'No board counts.' if has_board else ''

    def part(key: str, label: str) -> str:
        """One count as the board prints it (r21-q141): what can be taken now, then `(h held, k wait)` without zero parts."""
        found = counts[key]
        rest = [f'{n} {word}' for n, word in ((found.get('held', 0), 'held'), (found['waiting'], 'wait')) if n]
        return f"{found['ready']} {label}" + (f" ({', '.join(rest)})" if rest else '')
    return 'Board: ' + ', '.join(part(key, label) for key, label in BOARD_LINE_LABELS) + '.'


BOARD_LINE_LABELS = (('questions', 'open questions'), ('decided', 'decided awaiting release'), ('toPlan', 'released to plan'),
                     ('toReview', 'to review'), ('toAccept', 'to accept'), ('forUser', 'waiting on the user'))


def closed_done(q: dict) -> str:
    return (f"- {q['id']} → {q['recorded'] if q['recorded'] not in ('file',) else q['recordFile']}"
            + (f", closed {', '.join(q['closed'])}" if q.get('closed') else ''))


def closed_parked(q: dict) -> str:
    return f"- {q['id']} parked → {q['parked']}: open and unassigned for the person"


def closed_next(count: int) -> str:
    return f"Next: a release (decide.md Release) takes {release_takes(count)}, on the user's /release-round or request."


def release_takes(count: int) -> str:
    """What a bare release takes, for the closed round's text."""
    return (f"all {plural(count, 'decided record')} this session holds, minus dropped ones; "
            'name ids to take fewer')


def round_closed(round_id: str) -> str:
    return f"Round {round_id} closed."


# Verbs: the notes after an answer, a decline, a restart (verbs.py).

def chat_recorded(qid: str) -> str:
    return f'Recorded the chat answer to {qid} with its quote.'


def declined_note(marker: str, reason: str, partial: dict, cap: bool) -> str:
    note = f"Batch {marker} {reason}: nothing recorded; its questions are back to ready."
    if partial:
        note += (' Answers given inside the declined batch (confirm them in the next batch, do not record them): '
                 + '; '.join(f'{text!r}: {answer!r}' for text, answer in partial.items()))
    return note + (' Ask the user what to change, or `protocol step` with {} to ask again.' if not cap
                   else ' The check loop is paused: `protocol resume` continues it.')


def cap_own_words(answer: str) -> str:
    return f'The user answered the cap question in their own words: "{answer}". Loop paused; act on it, then ' \
           '`protocol resume` or restart questions.'


CAP_CONTINUED = 'Continue: more check cycles.'
CAP_PAUSED = 'Paused: `protocol resume` continues the check loop.'
CAP_ASK_NOW = 'Ask now: the questions go out as they stand.'

ANSWER_THINK_MORE = f'{THINK_MORE}: its checks rerun'
ANSWER_NONE = 'no answer, asked again'


def answer_typed(reply: str) -> str:
    return f'typed, not an answer yet: {reply}'


def answer_pick(pick: str, recommended: bool) -> str:
    return f"{pick} ({'recommended' if recommended else 'not recommended'})"


def answered_row(index: int, count: int, title: str, outcome: str) -> str:
    number = f'{index + 1}. ' if count > 1 else ''
    return f"{number}{title}{' ' if title.endswith('?') else ': '}{outcome}"


def answered_rows(rows: list[str]) -> str:
    return '\n'.join(['Your answers:', *rows])


def answers_recorded(done: list[str], origin: str) -> str:
    return f"Recorded answers to {', '.join(done)} ({origin})."


def answer_noted(qid: str, pick: str, note: str) -> str:
    return f'{qid}: picked "{pick}" with the note "{note}".'


ANSWER_ROUTES = ('Act on each part of the user\'s words above: an option it picks → the ["answer"] call with the option\'s '
                 'label and that text as quote; a criterion → `protocol restart <ids>`; a change to the questions → '
                 '`protocol edit` (updates + the quote); another request (explain, step back, ground, …) → run it; a reply that '
                 'changes a question (its recommendation included) → call a pass\'s skill on it, then report that pass. Restate '
                 'a part in one line when it could be read more than one way.')
ANSWER_ROUTES_AGAIN = "Act on each part of the user's words above by the routes you were given."  # r13-q79; the full note again after a compaction
NOTE_RECORD = 'A note no route takes stays in the record.'


def answer_typed_note(qid: str, typed: str) -> str:
    return f'{qid}: the user typed "{typed}" instead of picking an option; read it before {qid} goes out again.'


def answer_response(response: str) -> str:
    return f'The user also wrote: "{response}", tied to no question.'


def answers_unanswered(ids: list[str]) -> str:
    return f"Unanswered, back to ready: {', '.join(ids)}."


FOLLOW_UP = ('The user asked for another round of questions: ask what they want asked, and stage it '
             '(a criterion restarts the affected questions).')


def answer_reading(typed: list[str]) -> str:
    return ('The next batch waits for your reading of these: `protocol step` with {} (or a pass report) issues it'
            + (f", {', '.join(typed)} in it." if typed else '.'))


def answer_rethink(rethink: list[str]) -> str:
    return f"{', '.join(rethink)}: {THINK_MORE}, so the checks rerun on them aiming for a strong recommendation."


def restart_resting(resting: list[str]) -> str:
    return f"Restarted with it, their answers rested on it: {', '.join(resting)}."


def restart_widens() -> str:
    return f'A restart that widens the round: list the open items with `{LIST_COMMAND}`.'


# Read views: the Log, show, status, history and the headline (views.py).

def batch_number(marker: str | None) -> str:
    """`round:r6:4` → `4`: the Log and the headline are per round."""
    return (marker or '?').rsplit(':', 1)[-1]


def pass_words(e: dict) -> str:
    """`q3, q5 changed`, `no change`."""
    ids, added, changes = e.get('questions'), e.get('added'), e.get('changes') or 0
    parts = [f"{', '.join(ids)} changed"] if ids else []
    parts += [f"{', '.join(added)} added"] if added else []
    return ', '.join(parts) if parts else f'{changes} changes' if changes else 'no change'


def classified_words(e: dict) -> str:
    tally = e.get('classes') or {}
    return f"classified {plural(sum(tally.values()), 'point')}" + (': ' + ', '.join(f'{n} {name}' for name, n in tally.items()) if tally else '')


NO_CHANGE = re.compile(r'^\s*no changes?\b[:.]?\s*', re.IGNORECASE)


def pass_label(e: dict) -> str:
    """`ground`, `step-back (path)`, `ground (lean q39 q40)`: the pass and, when it ran as one of the sequence's
    scoped or named kinds, which, with the question or record ids it was scoped to."""
    detail = ' '.join(filter(None, [e.get('kind'), *(e.get('scoped') or [])]))
    return f"{e.get('command')} ({detail})" if detail else str(e.get('command'))


def log_text(event: dict) -> str | None:
    """One history event in plain words for the console's log, or None for events it leaves out."""
    e, kind = event, event['event']
    ids = lambda key: ', '.join(e.get(key) or []) or 'none'
    said = NO_CHANGE.sub('', e['summary']) if e.get('summary') else ''  # the headline says whether anything changed
    summary = f': {cut(said, 90)}' if said else ''
    return {
        'start': 'release started' if e.get('protocol') == 'release' else 'round started',
        'rechecked': f"re-check: {e.get('unchanged')} unchanged" + (f", {ids('changed')} changed" if e.get('changed') else ''),
        'record-dropped': f"dropped {e.get('record')}: {(e.get('reason') or '')[:80]}",
        'record-revised': f"revised {e.get('record')}: {(e.get('reason') or '')[:80]}",
        'release-stopped': f"stopped: {(e.get('reason') or '')[:90]}",
        'board-checked': f"board check: {plural(e.get('supersedes') or 0, 'supersede')}, {plural(len(e.get('closes') or []), 'answered question')}",
        'own-rulings': f"own rulings: {e.get('rulings')}, {e.get('unsure')} unsure",
        'approval-asked': 'approval asked' + (f": {cut('; '.join(e['reasons']), 90)}" if isinstance(e.get('reasons'), list) and e['reasons'] else ''), 'approved': f"approved ({e.get('origin')}, {e.get('how')})",
        'stamped': f"/release-round ({e.get('origin')}): approves if the checks hold",
        'owners-checked': f"owners checked: {plural(e.get('written') or 0, 'written path')}",
        # a clean release without closes is "released <ids>" (release-done) alone
        'board-release': f"board release {ids('records')}" + (f" closing {ids('closes')}" if e.get('closes') else '') + (f": exit {e.get('exit')}" if e.get('exit') else '')
        if e.get('exit') or e.get('closes') else None,
        'superseded': f"superseded {e.get('old')} by {e.get('new')}", 'release-done': f"released {ids('records')}", 'selected': f"selected {ids('selected')}", 'staged': f"staged {ids('questions')}",
        'related': f"{e.get('question')}: {len(e.get('hits') or [])} related items",
        'pass': f"{pass_label(e)}: {pass_words(e)}{summary}", 'classified': classified_words(e),
        'asked': f"asked {ids('questions')}", 'answered': f"answered {ids('questions')} ({e.get('origin')})" + (f"; typed {ids('typed')}" if e.get('typed') else ''),
        'decline': f"batch {batch_number(e.get('marker'))} {e.get('reason')}", 'restart': f"restarted {ids('questions')}",
        'continued': f"released {ids('questions')} from held: checked again before the next batch",
        'cap': f"cycle cap at {e.get('cycle')}" + (': the questions park' if e.get('away') else ''), 'cap-decision': f"cap: {e.get('choice')}",
        'settled': f"away: acted {ids('acted')}, parked {ids('parked')}", 'parked': f"parked {e.get('question')} → {e.get('board')}",
        'batch-withdrawn': f"batch {batch_number(e.get('marker'))} withdrawn for updates", 'recorded': f"recorded {e.get('question')} → {e.get('board') or 'file'}",
        'deferred': f"deferred {e.get('question')}", 'released': f"released {ids('items')}",
        'refused': f"refused {e.get('verb')}: {(e.get('error') or '')[:90]}", 'removed': f"removed {e.get('question')}",
        'edited': f"edited {ids('questions')} (your words)",
        'checking': f"{ids('questions')}: " + ('challenge-rulings on the raised strong mark' if e.get('kind') == 'raised'
                                               else 'checked before they are asked (added or re-recommended)'),
        'closed': 'release closed' if e.get('protocol') == 'release' else 'round closed', 'abandoned': f"abandoned at {e.get('step')}",
    }.get(kind)


def recorded_line(events: list[dict]) -> str:
    """Consecutive `recorded` events as one line: `recorded q39, q40 → fx-1, fx-2`, or `→ files` when none reached the board."""
    targets = list(dict.fromkeys(e.get('board') or 'file' for e in events))
    return f"recorded {', '.join(e.get('question') for e in events)} → " + ('files' if targets == ['file'] else ', '.join(targets))


def show_markdown(r: dict | None, counts: dict | None, next_step: str | None) -> str:
    """The round as markdown; `next_step`: the step's instructions, for recovery after a compaction (None once closed)."""
    if not r:
        return 'No round in this session.'
    check = r['check']
    noun = 'Release' if r['protocol'] == 'release' else 'Round'
    lines = [f"# {noun} {r['id']}{' · ' + r['title'] if r.get('title') else ''} · {r['step']}", '',
             *([r['summary'], ''] if r.get('summary') else []), *([f"Subject: {r['subject']}", ''] if r.get('subject') else [])]
    if r.get('set'):
        lines += ['| record | state | title |', '|---|---|---|',
                  *(f"| {rec['id']} | {rec['state']}{' (' + rec['reason'] + ')' if rec['reason'] else ''} | {rec['title']} |"
                    for rec in r['set']), '']
    if check.get('expect'):
        last = ', '.join(f"{k} {v['changes']} ({v['origin']})" for k, v in check.get('last', {}).items()) or 'none yet'
        lines.append(f"Check cycle {check['cycle']}/{check['cap']}; last passes: {last}.")
    if r['pending']:
        lines.append(f"Pending: /{r['pending']['command']} ({r['pending']['id']}).")
    if r['batch']:
        lines.append(f"Batch out: {r['batch']['marker']}.")
    lines += ['', '| id | board | status | kind | question | answer |', '|---|---|---|---|---|---|']
    for q in r['questions']:
        overlap = ''.join(f" (overlaps {h['id']}: {h['outcome'] or 'open'})" for h in q['overlaps'])
        lines.append(f"| {q['id']} | {q['board'] or 'draft'} | {q['status']}"
                     + ((f" on {', '.join(q['waitsOn'])}" if q['waitsOn'] else '') + (f", waits for {q['waitsFor']}" if q.get('waitsFor') else '')
                        if q['status'] == 'held' else '')
                     + f" | {q['kind']} | {q['text']}{overlap} | {q['answer'] or ''} |")
    if counts:
        lines += ['', 'Board: ' + ', '.join(f'{k} {v}' for k, v in counts.items())]
    if next_step is not None:
        lines += ['', '## Next step', '', next_step]
    return '\n'.join(lines)


def status_line(r: dict | None) -> str:
    if not r or r['step'] == 'closed':
        return 'protocol: no open round'
    tally = {}
    for q in r['questions']:
        tally[q['status']] = tally.get(q['status'], 0) + 1
    parts = [f"{'release' if r['protocol'] == 'release' else 'round'} {r['id']}", r['step']]
    if r['step'] == 'check' and r['check'].get('expect'):
        parts[-1] += f" {r['check']['cycle']}/{r['check']['cap']}"
    if r['pending']:
        parts.append(f"pending /{r['pending']['command']} ({r['pending']['id']})")
    if r['batch']:
        parts.append(f"batch {r['batch']['marker']} out")
    parts.append('questions ' + (', '.join(f'{n} {s}' for s, n in tally.items()) or 'none'))
    if r.get('set'):
        states = {}
        for rec in r['set']:
            states[rec['state']] = states.get(rec['state'], 0) + 1
        parts.append('records ' + ', '.join(f'{n} {state}' for state, n in states.items()))
    parts.append("`protocol show` repeats the step's instructions")
    return 'protocol: ' + ' · '.join(parts)


def history_none() -> str:
    return 'no protocol history'


def history_row(session, round_id, s: dict) -> str:
    def counts(table):
        return ', '.join(f'{k} {v}' for k, v in sorted(table.items())) or 'none'
    return (f"{session} {round_id}: passes {counts(s['passes'])}; changed something {counts(s['changed'])}; "
            f"answers {counts(s['answers'])}; declines {s['declines']}; "
            f"restarts {'; '.join(s['restarts']) or 'none'}; cap {', '.join(s['caps']) or 'not reached'}")


NEXT_RELEASE = 'release (/release-round or ask)'
NEXT_CAP = 'your call on the cycle cap'
NEXT_PAUSED = 'check paused; `protocol resume` continues'
NEXT_CHALLENGE_LAST = 'challenge-rulings, last before asking'
NEXT_ASK_AWAY = 'act or park per question'
NEXT_STEPS = {'prepass': 'the pre-pass over the points', 'select': 'select', 'stage': 'stage the questions', 'related': 'resolve related items', 'ask': 'the next batch',
              'record': 'record the answers', 'recheck': 're-check the records', 'board-check': 'the board check',
              'own-rulings': 'your own rulings', 'owners': 'owner writes', 'release': 'rerun the release'}  # by step


def next_round_on(ids: list[str]) -> str:
    return f"a round on {', '.join(ids)}"


def next_answers(console: bool, has_notice: bool, number: str) -> str:
    """`console`: Claude, whose lead's turn ends while the console prints the parts, if any, and opens the dialog."""
    return f"{('the console to print, then ' if has_notice else 'the console to open the dialog, then ') if console else ''}your answers (batch {number})"


def next_challenge(kind: str, ids: list[str]) -> str:
    return 'challenge-rulings ' + ('after the last answer' if kind == 'answers' else 'on the raised strong ' + ' '.join(ids))


def next_phase(kind: str, ids: list[str] | None) -> str:
    """`, path pass`, `, refine pass q1 q2`: `ids` None for the round-wide pass."""
    return f', {kind} pass' + (' ' + ' '.join(ids) if ids is not None else '')


NEXT_LEAN = ', lean pass'


def next_check(expect: str, phase: str, cycle: int, cap: int) -> str:
    return f"{expect}{phase}, cycle {cycle}/{cap}"


def next_scoped(command: str, args: str) -> str:
    return f"{command} pass on the revised {args}"


def next_classify(points: int, items: int) -> str:
    return 'classify ' + ' and '.join(plural(n, name) for name, n in (('point', points), ('item', items)) if n)


def headline_label(round_id: str, release: bool, title: str | None) -> str:
    """`r5 release · the session's records` for a release, else the round id."""
    return f"{round_id} release · {title}" if release else round_id


def headline(label: str, events: list[str], upcoming: str | None) -> str:
    return ' · '.join([label, *events, *([f'next: {upcoming}'] if upcoming else [])])


# Release: Re-check, Board check, Own rulings, Scoped, Approval, Owners, Closed (release*.py).

def release_label(source: bool, ids: list[str]) -> str:
    """`the session's records`, or the named ids: the run's title in the pane and the headline."""
    if source:
        return "the session's records"
    return ', '.join(ids[:3]) + (f' +{len(ids) - 3}' if len(ids) > 3 else '')


def set_row(rec: dict) -> str:
    return f"- {rec['id']}: {rec['title']}" + (' (revised)' if rec['state'] == 'revised' else '')


def drop_changed(change: str) -> str:
    return f"changed (contained): {change}"


def revise_reason(change: str) -> str:
    return f'changed (contained, own): {change}'


def spreads_reason(spreads: list[tuple[str, dict]]) -> str:
    return '; '.join(f"{rid} changed: {value['change']}" for rid, value in spreads)


EMPTY_SET = 'every record left the set'


def held_at_approval(origin: str) -> str:
    return f"held at approval ({origin})"


def premise_waits(waiting: list[str]) -> str:
    return f"its premise waits on {', '.join(waiting)}"


def blocker_waits(blockers: list[str], found: dict) -> str:
    return 'waits on ' + ', '.join(f"{b} ({found[b] or 'not found'})" for b in blockers)


TOUCHES_HINT = ('touches: "own" (only your own rationale, evidence, a clause the chosen option did not state, or a correction '
                "that follows a later decision of the user's in the set, which you name: the record stays, revised and shown as revised at "
                'approval; give `file`, the path of the corrected record text, which the engine writes with `board record`, and '
                'a scoped step-back and ground pass check it before the approval) or "decision" (what the user decided: '
                'the record leaves the set for a round); unsure is decision.')


def recheck_intro(round_id: str, label: str) -> str:
    return (f"Release {round_id} · Re-check (decide.md Release 1) {label}: compare each record with "
            "current items and source and with the set's other records; verify citations and counts. Where something "
            "changed since the decision, give its reach: contained (`why` no other ruling moves) or spreads (other rulings "
            'may move, or you are unsure: the run stops and the set goes to a round). A contained change says what it '
            f'{TOUCHES_HINT}')


BARE_RELEASE = ("A bare release takes the decided records this session holds, minus dropped ones; the ids named at start take "
                'fewer.')


def recheck_example(first: list[str]) -> dict:
    return {'records': {rid: 'unchanged' for rid in first}
            | {'<id>': {'change': '<what changed>', 'reach': 'contained', 'why': '<why nothing else moves>',
                        'touches': 'own', 'file': '<path of the corrected record text, for own>'}}}


def release_question_text(count: int, source: bool, unsure: list[dict], revised: list[dict]) -> str:
    """`Release 3 records? Unsure: tstdl-a (…) Revised: tstdl-b (…)`: an unsure ruling first (r14 q56), within the dialog
    limits whatever the set holds; the notice before the dialog prints each ruling in full."""
    counted = plural(count, 'record')
    text = f"Release the session's {counted}?" if source else f"Release {counted}?"
    unsure_text = '; '.join(f"{x['record']} ({x['ruling']})" for x in unsure)
    changes = '; '.join(f"{rec['id']} ({cut(rec['change'], 80)})" for rec in revised)
    return cut(' '.join(filter(None, [text, f'Unsure: {unsure_text}' if unsure_text else '', f'Revised: {changes}' if changes else ''])), TEXT_MAX)




def approval_title(label: str) -> str:
    return f'Release {label}'


APPROVE_HEADER = 'Release'
APPROVE_DESCRIPTION = 'Owner writes, then board release'
APPROVE_FILES_DESCRIPTION = 'Owner writes stay uncommitted for you, then the Released line goes into each record file'
HOLD_DESCRIPTION = 'Nothing releases; the records stay decided. Say why: a round takes what you held'


def approval_retry(approve: str, hold: str, typed: str) -> str:
    return (f"The approval needs the user's pick of {approve} or {hold}; they wrote \"{typed}\". "
            'Ask again (`protocol step` with {}).')


def approval_text(round_id: str, reasons: list[str]) -> str:
    return f"Release {round_id} · Approval: `protocol step` with {{}} continues." \
        + (f" The dialog asks because: {'; '.join(reasons)}." if reasons else '')


def stray_records(stray: list[str], now: dict) -> str:
    return ('Not released: ' + ', '.join(f'{rid} is {now[rid]}' for rid in stray)
            + '; settle them on the board, then `protocol step` with {}.')


def board_exited(argv: list[str], returncode: int, output: str) -> str:
    return f"`board {' '.join(argv)}` exited {returncode}:\n" + output


def supersede_failed(old: str, new: str, returncode: int, output: str) -> str:
    return f"`board supersede {old} --with {new}` exited {returncode}: " + output


def statuses_unavailable(error) -> str:
    return f'Board statuses unavailable after the writes ({error}); `protocol step` with {{}} rereads them.'


RELEASE_UNFINISHED = ('Release not finished: fix what the board reported, then `protocol step` with {} reruns '
                      'only what remains (released records, closed questions and done supersedes stay done).')


def release_waiting(round_id: str) -> str:
    return f"Release {round_id} · Release: waiting for a rerun (`protocol step` with {{}})."


def owners_intro(round_id: str, files: bool = False) -> str:
    return lines(
        f"Release {round_id} · Owner writes (decide.md Release 5): write each rule into its one owner, replacing the text it supersedes. "
        "A rule a topic's design-target doc or a project's convention owner (coding style, module authoring) states is written now, not pending; "
        'only READMEs, other skills and source may be pending.',
        "Name each path, with its anchor, in the record's `## Rule owner` (rewrite the record with `board record <id> <file>`)."
        if not files else
        "Name each path, with its anchor, in the record file's `## Rule owner`. Relative paths start at the directory the release "
        'started in. Owner writes stay uncommitted for the user: no commit by the engine or the session. A `pending` item needs a board.',
        'Report per record its owners: written {path, anchor} (path: a repo path from the board root, or absolute/~; an installed file '
        'by its installed path), none {reason}, or pending {item} (an open board item).')


def owners_example(first: str) -> dict:
    return {'owners': {first: [{'written': {'path': 'docs/x.md', 'anchor': 'the-rule'}},
                               {'pending': {'item': '<task id>'}}]}}


def memory_missing(name: str, path) -> str:
    return f'{name}: the `## {name}` section of {path} is missing; read it before writing durable docs.'


def memory_heading(name: str, body: str) -> str:
    return f'## {name} (project-memory.md)' + body.rstrip()


def kept_words(held: bool) -> str:
    """What a release that ends unreleased leaves: a board's records stay held by the session; record files only unreleased."""
    return 'decided and held' if held else 'decided, without a Released line'


def release_closed_held(round_id: str, board: str, held: bool = True) -> str:
    return '\n'.join([
        f"Release {round_id} held: nothing released; the records stay {kept_words(held)}.",
        'Next: ask what it was held for, then a round on those records, or on the set when the reason spreads to the others '
        '(`protocol start round`; its check loop opens with step-back). A later `protocol start release` takes the rest.', board])


def release_closed_stopped(round_id: str, reason: str, ids: list[str], board: str, held: bool = True) -> str:
    joined = ', '.join(ids)
    return '\n'.join([
        f"Release {round_id} stopped: {reason}. Nothing released; {joined} stay {kept_words(held)}.",
        f'Next: a round on {joined} (`protocol start round`, then classify and select them; its check loop opens '
        'with step-back).', board])


def release_closed(r: dict, board: str) -> str:
    dropped = [rec for rec in r['set'] if rec['state'] == 'dropped']
    outcome = r.get('outcome') or {'closed': [], 'open': []}
    return '\n'.join([
        f"Release {r['id']} closed.",
        *(f"- released {rec['id']}: {rec['title']}" + (f" (revised: {rec['change']})" if rec.get('change') else '')
          for rec in r['set'] if rec['state'] == 'released'),
        *(f"- superseded {sup['old']} by {sup['new']}" + (f" (rule: {sup['partial']})" if sup['partial'] is not None else '')
          for sup in r['supersedes']),
        *(f"- closed {q}: answered by released {', '.join(r['closes'][q])}" for q in outcome['closed']),
        *(f"- dropped {rec['id']} ({rec['reason']}): it stays decided and held for a round" for rec in dropped),
        board,
        'Next (decide.md Release 7): run `protocol next`.'
        + (f" Dropped records go to a round: {', '.join(rec['id'] for rec in dropped)}." if dropped else '') + ' Wait for the user.',
    ])


BOARD_CHECK_SKIPPED = 'Board check skipped: record files of a --no-board round have no board.'
RECHECK_FILES = 'Without a board the engine copies the `file` of an own change over the record file.'


def files_not_released(failed: list[str]) -> str:
    return ('Released block not written: ' + '; '.join(failed)
            + '; fix that, then `protocol step` with {} writes what remains (a file that has the block stays as it is).')


def release_files_closed(r: dict) -> str:
    dropped = [rec for rec in r['set'] if rec['state'] == 'dropped']
    return '\n'.join([
        f"Release {r['id']} closed.",
        *(f"- released {rec['id']}: {rec['title']} ({rec['file']})" + (f" (revised: {rec['change']})" if rec.get('change') else '')
          for rec in r['set'] if rec['state'] == 'released'),
        *(f"- dropped {rec['id']} ({rec['reason']}): it stays unreleased for a round" for rec in dropped),
        'Owner writes stay uncommitted for the user. Next (decide.md Release 7): run `protocol next`.'
        + (f" Dropped records go to a round: {', '.join(rec['id'] for rec in dropped)}." if dropped else '') + ' Wait for the user.',
    ])


def release_approved(round_id: str) -> str:
    return f"Release {round_id} is approved already."


def release_stamped(round_id: str) -> str:
    return (f"Release {round_id}: the /release-round approves it if every own ruling is sure and no record "
            'leaves the set or is revised; otherwise a dialog asks.')


def release_abandoned(headline_line: str, messages: list[str], round_id: str, held: bool = True) -> str:
    return '\n'.join([headline_line, *messages, f"Release {round_id} abandoned at its step; nothing released, "
                      f'the records stay {kept_words(held)}; `protocol start release` takes them again.'])


def round_abandoned(headline_line: str, messages: list[str], round_id: str, note: str) -> str:
    return '\n'.join([headline_line, *messages, f"Round {round_id} abandoned at its step; {note}."])


def board_check_intro(round_id: str) -> str:
    return (f"Release {round_id} · Board check (decide.md Release 2): run `board related <terms>` across the set, "
            'closed items and canonical docs included (`--docs <paths>`), and act on every hit. Report per record one '
            'entry per hit class ("none", or rows {item, action}):')


def hit_class_row(name: str, meaning: str) -> str:
    return f'- {name}: {meaning}'


def unlinked_revisions(unlinked: list[dict]) -> str:
    return ("Unlinked revisions the set's texts name (`board check`; a question missed them): "
            + '; '.join(f"{row['id']} {row['word']} {row['other']}: `board supersede {row['old']} --with {row['new']}`"
                        for row in unlinked) + '. Treat each as a `revises` hit of the record that replaces the other.')


def prefilled(rid: str, settled: list[str]) -> str:
    return (f"Pre-filled: {rid} answers {', '.join(settled)} (the items its rule question settled): the engine adds the "
            f"answers and the closes.")


def not_closed(rid: str, items: list[str]) -> str:
    return (f"Not closed: {rid} marks {', '.join(items)} as settled, but only an open question closes as answered. Correct a "
            'record it changes at Re-check (relate) or replace it (supersedes).')


BOARD_CHECK_NAMES = ('Name the supersedes and the answered questions: the engine runs `board supersede` and closes those questions '
                     'after the release ("Answered by released <record>"); every other action is yours. A ruling the check changes '
                     f'goes under `changed` with its reach and, when contained, what it {TOUCHES_HINT}')


def board_check_example(first: str, names) -> dict:
    return {'checks': {first: {**{name: 'none' for name in names},
                               'answers': [{'item': '<question>', 'action': 'answered: close'}]}},
            'supersedes': [{'old': '<record>', 'new': first, 'partial': '<rule, or leave out>'}],
            'closes': {'<question>': [first]}, 'changed': {}}


def unlinked_unavailable(error) -> str:
    return f'Unlinked revisions unavailable ({error}); run `board check`.'


def own_rulings_intro(round_id: str) -> str:
    return (f"Release {round_id} · Own rulings (decide.md Release 3): list every ruling you made in the set with "
            "the disclosure fields of `$HOME/.agents/skills/shared/asking.md`: the ruling, what it meets without a material trade-off, its strongest realistic alternative, the test or principle that "
            'alternative fails, and the evidence. Mark each `sure` only when it is entailed (decision-protocol.md Decision '
            'authority).')


def own_rulings_example(first: str) -> dict:
    return {'rulings': [{'record': first, 'ruling': '<your ruling>', 'why': '<what it meets, why no material trade-off remains>',
                         'alternative': '<strongest alternative>', 'fails': '<what it fails>',
                         'evidence': '<source>', 'sure': True}]}


def scoped_text(round_id: str, command: str, args: str, codex: bool) -> str:
    lead = (f"Release {round_id} · Scoped {command} pass (decide.md Release 1) on the revised records {args}: the "
            'corrected record text, each against its sources and the rest of the set. ')
    how = (f'Run the {command} skill now with the argument `{args}` (read its SKILL.md), then report the pass. '
           if codex else
           f'{HAND_OVER} ')
    return lead + how + 'Report each revised record as "unchanged" or a change as in the re-check (a change of your own ' \
                        "parts rewrites it again; a change to the user's decision drops it; a spread stops the run):"


def scoped_example(command, first: list[str]) -> dict:
    return {'pass': command, 'records': {rid: 'unchanged' for rid in first}
            | {'<id>': {'change': '<what changed>', 'reach': 'contained', 'why': '<why nothing else moves>',
                        'touches': 'own', 'file': '<path of the corrected record text, for own>'}},
            'summary': '<one line: what the pass found>'}


COMPACTED = 'Compaction recorded: the next steps print their full text again.'


# Next: the seeds, the open questions by topic and the stored proposal (seeds.py).

def seed_line(seed: dict, priority: int) -> str:
    return (f"- {seed['id']} · p{priority} · holds {seed['holds']}/{seed['holdsAll']} · "
            + (f"milestone {seed['milestone']}" if seed['milestone'] else 'no milestone') + f" · {seed['title']}")


def approx(n: int, word: str) -> str:
    return f"~{n} {word}{'' if n == 1 else 's'}"


def proposal_estimate(estimate) -> str:
    """The model's estimates of a stored row; a row stored before they existed has none."""
    if not isinstance(estimate, dict):
        return ''
    return f" · {approx(estimate.get('questions', 0), 'question')} · unblocks {approx(estimate.get('unblocks', 0), 'item')}"


def proposal_text(rows: list[dict] | None) -> list[str]:
    """A stored proposal's rows (`rows` None: none stored); a stored row may lack fields a later version wrote (a read never fails on it)."""
    if rows is None:
        return ['No proposal stored.']
    rows = [f"{index}. {r.get('title', '')}" + proposal_estimate(r.get('estimate')) + (f" · {r['summary']}" if r.get('summary') else '')
            + (f" · leads with {' '.join(r['ids'])}" if r.get('ids') else '')
            + f" · {'wants a fresh context' if r.get('fresh') else 'keeps the context'} · {r.get('why', '')}"
            for index, r in enumerate(rows, 1)]
    return ['Stored proposal' + (' (the first row is the recommended one):' if rows else ' (no rounds: the console offers a compaction when the context is large):'),
            *rows]


def topic_counts_lines(ordered: list[tuple[str, dict[int, int]]]) -> list[str]:
    """Open questions per topic label and priority, `orm-schema-migrations 7 p1, 7 p2`, the largest topic first
    (r24-q104, q105): the lead weighs priority against how many questions a round settles."""
    return ['Open questions by topic (a label approximates a premise: a round on it takes the part that shares one):',
            *(f"- {topic} " + ', '.join(f'{n} p{priority}' if priority != 9 else f'{n} unprioritized'
                                        for priority, n in sorted(by_priority.items())) for topic, by_priority in ordered)]


def inbox_text(held: list[dict], inbox: list[dict]) -> str:
    row = lambda item: (f"- {item['id']} [{item.get('type')}] for "
                        + ', '.join(label[len('for:'):] for label in item.get('labels') or [] if label.startswith('for:'))
                        + f": {item.get('title', '')}")
    return lines(
        'Inbox step (decide.md): show each item to the user, who picks; never decide these alone.',
        *([f'Finds held for you to check, filed for another person: send, keep or close ({len(held)}):', *map(row, held)] if held else []),
        *([f'Your inbox, sent to you: take, pass on or close with a reason ({len(inbox)}):', *map(row, inbox)] if inbox else []),
        'Keep or take: board route <you> <id>; send or pass on: board send <person> <id>.',
    )


SEEDS_HEAD = (f'Seeds for the next round (top {SEEDS} open questions, unblocked, not held by another live session; open-milestone '
              'members first, then priority, then the work they hold; holds: stopping at a milestone/everything downstream):')
SEEDS_NONE = '- none'


def next_recommend() -> str:
    return ('Recommend the next round or, when no question round leads, the other next step by priority and what it unblocks. '
            'Propose topics, not question sets. '
            'Rank the rows by priority and by how many questions each settles, and state the trade in `why`; a follow-up that '
            'reuses what was just read goes first, and milestone members stay ahead of the rest. '
            'Write `title` and `summary` for a reader who was not in the discussion: plain words, no code names, no board or question '
            'ids; `summary` is one sentence on what the round decides and what its questions share. '
            f'Lengths to keep to in characters: `title` about {TITLE_MAX}, `summary` {SUMMARY_MAX}, `why` {TEXT_LIMIT}. '  # r9-q34
            '`estimate`: the questions the round settles and the board items that wait on its answers, downstream included. '
            'Record the proposal with `protocol next --set` (stdin '
            + json_block({'rounds': [{'title': '<the topic in plain words>', 'summary': '<what the round decides and what its questions share>',
                                      'estimate': {'questions': 2, 'unblocks': 6},
                                      'why': '<why this topic, and the priority/size trade>', 'fresh': False,
                                      'ids': ['<a question that must lead (optional)>']}]})
            + f'): at most {PROPOSAL_ROUNDS} rounds, the one that reuses the read context first with fresh false, other topics with '
            'fresh true; `rounds` may be empty to offer only a compaction. Leave compaction out of what you tell the user. '
            "Present the rows in chat under asking.md's Question format. "
            'Start row n with `protocol start round --proposal <n>`.')


def proposal_topic(row: dict) -> str:
    """A proposal row's round topic: its title and summary (a row stored before summaries has the title alone)."""
    return f"{row['title']}: {row['summary']}" if row.get('summary') else row['title']


def proposal_stored(rows: list[dict]) -> str:
    return '\n'.join(['Stored.', *proposal_text(rows)])


# The text printed before a dialog (render.py): the question data owns the format.

def lean_line(q: dict) -> list[str]:
    """What a lean recommendation depends on, under its heading; a strong one's + line is its reason (r31-q147)."""
    if q.get('strength') != 'lean':
        return []
    because = q.get('leanBecause') or {}
    return [f"{lean_cause(because)}: {because.get('detail')}",
            *([f"What would change it: {because['flipsIf']}"] if because.get('flipsIf') else [])]


def options_text(q: dict) -> str:
    """The recommended option first (`Recommended (<strength>): <label>`), each option a bold heading with For and Against bullets and
    its example as a code block (r10-q37), a blank line between options (r30-q141, r32-q150; a leading `+` renders as a bullet, so the words tell them apart)."""
    shown = [o for o in q['options'] if 'for' in o or 'against' in o]
    best = next((o for o in shown if o['label'] == q.get('recommendation')), None) if q.get('strength') else None
    blocks = []
    for o in [*([best] if best else []), *(o for o in shown if o is not best)]:
        head = [f"**Recommended ({q['strength']}): {o['label']}**", *lean_line(q)] if o is best else [f"**{o['label']}**"]
        blocks.append('\n'.join([*head, f"- For: {o.get('for', '')}", f"- Against: {o.get('against', '')}",
                                 *([code_block(o['example'])] if (o.get('example') or '').strip() else [])]))
    return '\n\n'.join(blocks)


def code_block(text: str) -> str:
    """An option's example as a fenced block, the fence longer than any backtick run inside it."""
    longest = max((len(run) for run in re.findall(r'`+', text)), default=0)
    fence = '`' * max(3, longest + 1)
    return f"{fence}\n{text.strip(chr(10))}\n{fence}"


def dropped_text(q: dict) -> str:
    """The ideas the options pass dropped, one line each, under the options."""
    found = q.get('explored')
    return '\n'.join(f"- Dropped: {x['idea']} - {x['why']}" for x in found if x['verdict'] == 'dropped') if isinstance(found, list) else ''


def ruling_line(x: dict) -> str:
    """A ruling with all its disclosure fields: the record keeps them."""
    return f"{x['ruling'].strip()} Why: {x['why'].strip()} Alternative: {x['alternative'].strip()} Fails: {x['fails'].strip()} Evidence: {x['evidence'].strip()}"


def ruling_block(x: dict, record: str = '') -> str:
    """A ruling as printed: the ruling, why it is mine, the alternative and why not, without the evidence (r29-q136); `record`: its release record."""
    return '\n'.join([f"**My ruling:** {x['ruling'].strip()}" + (f' ({record})' if record else ''),
                      f"- Why: {x['why'].strip()}", f"- Instead: {x['alternative'].strip()}", f"- Why not: {x['fails'].strip()}"])


def prior_rulings_text(q: dict) -> str:
    """The earlier rulings as printed: how many held, and each that fails; the record keeps every line (r34-q163)."""
    prior = q.get('priorRulings') or []
    if not prior:
        return ''
    fails = [f"- Fails: {x['ruling'].strip()} - {x['why'].strip()}" for x in prior if x['verdict'] == 'fails']
    return '\n'.join([f'{len(prior) - len(fails)} held.', *fails])


PART_TITLES = {'problem': 'Problem', 'cases': 'Cases', 'settles': 'Settles', 'premises': 'Premises', 'note': 'Note', 'priorRulings': 'Earlier rulings',
               'corrections': 'Corrections', 'boardCheck': 'Board check'}
LIST_PARTS = ('settles', 'corrections', 'boardCheck')  # parts printed one line per entry
SELF_TITLED = ('options', 'dropped', 'rulings')  # parts whose lines say what they are (`Recommended:`, `Dropped:`, `My ruling:`)


def part_block(name: str, text: str) -> str:
    return text if name in SELF_TITLED else f'{PART_TITLES[name]}:' + ('\n' if name in LIST_PARTS else ' ') + text


def settled_line(key: str, title: str) -> str:
    return f"- {key}: {cut(title, TITLE_MAX)}".rstrip(': ')


def correction_revised(rec: dict) -> str:
    return f"- {rec['id']} revised: {rec['change']}"


def correction_left(rec: dict) -> str:
    return f"- {rec['id']} left the set: {rec['reason']}"


def check_superseded(sup: dict) -> str:
    return f"- {sup['old']} superseded by {sup['new']}" + (f" (rule: {sup['partial']})" if sup['partial'] is not None else '')


def check_closes(question: str, recs: list[str]) -> str:
    return f"- {question} closes, answered by {', '.join(recs)}"


def check_hit(rid: str, name: str, row: dict) -> str:
    return f"- {rid} {name}: {row['item']}: {row['action']}"


def ruling_record(x: dict) -> str:
    return f"{x['record']}, {'sure' if x['sure'] else 'unsure'}"


def changed_mark(names: list[str]) -> str:
    return f" (changed: {', '.join(PART_TITLES.get(name, name).lower() for name in names)})"


def batch_title(index: int, count: int, title: str, mark: str) -> str:
    return (f'{index + 1}. ' if count > 1 else '') + title + mark


def no_run(command: str, pending: dict | None) -> str:
    """A report with no observed run of its pass (r5-q17): run the pending pass when it is that command, else end the turn."""
    if pending and pending.get('command') == command:
        run = ' '.join(part for part in (f'/{command}', pending.get('args') or '') if part)
        return f'no /{command} ran since its last report: run `{run}` with the Skill tool, then report it'
    return (f'no /{command} ran since its last report: end your turn (the console runs a pass it has not run yet, and tells '
            'the person what to type for one it has)')
