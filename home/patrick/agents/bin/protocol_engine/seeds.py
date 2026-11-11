"""Next: the seeds of the next round and the stored proposal."""
from __future__ import annotations

import re

from .base import PROPOSAL_ROUNDS, ProtocolError, SEEDS, SUMMARY_MAX, TEXT_LIMIT, TITLE_LIMIT, lines
from . import words
from .boards import foreign_holds, view_rows
from .engine import Context, fail
from .questions import refuse_all
from .collect import dependency_order, items_text, open_items, priority_of, read_open


# Next: the ranked seeds of the next round and the model's stored proposal (decide.md Release 7, Next).

def seeds(ctx: Context, found: dict, position: dict) -> list[dict]:
    """The top open decision questions to start a round from: unblocked, not held by another live session; members of
    an open milestone first, then priority, then the work they hold (`board position`), prerequisites first as in Select."""
    items = view_rows(found, 'questions')
    live, _ = foreign_holds(ctx, items, position)
    member = {}
    for milestone in found.get('milestones') or []:
        scoped = ctx.board.json('health', '--json', '--root', milestone['id'], '--items', 'questions')
        for item in view_rows(scoped, 'questions'):
            member.setdefault(item['id'], milestone['id'])
    holds = {item['id']: item for item in position.get('questionsHoldingWork') or []}
    pool = [{'key': item['id'], 'id': item['id'], 'title': item.get('title', ''), 'priority': item.get('priority'),
             'blockedBy': [], 'holds': (holds.get(item['id']) or {}).get('holds') or 0,
             'holdsAll': (holds.get(item['id']) or {}).get('holdsAll') or 0, 'milestone': member.get(item['id'])}
            for item in items if not item.get('blockedBy') and item['id'] not in live]
    ordered = dependency_order(pool, lambda c: (c['milestone'] is None, priority_of(c), -c['holds'], -c['holdsAll'], c['key']))
    return ordered[:SEEDS]


def topic_counts(items: list[dict]) -> list[str]:
    """Open questions per topic label and priority, `orm-schema-migrations 7 p1, 7 p2`, the largest topic first
    (r24-q104, q105): the lead weighs priority against how many questions a round settles. A topic label only approximates a
    premise, so a count is an upper bound for a round on it; a question with two topic labels counts under both."""
    questions = [item for item in items if item['view'] == 'questions']
    if not questions:
        return []
    tally: dict[str, dict[int, int]] = {}
    for item in questions:
        for topic in [label.removeprefix('topic:') for label in item['labels'] if label.startswith('topic:')] or ['(no topic)']:
            by_priority = tally.setdefault(topic, {})
            by_priority[priority_of(item)] = by_priority.get(priority_of(item), 0) + 1
    return words.topic_counts_lines(sorted(tally.items(), key=lambda row: (-sum(row[1].values()), row[0])))


def inbox_text(found: dict) -> tuple[str, set[str]]:
    """decide.md's Inbox step on a shared board, from `board health --json`'s queue lists: the finds held for
    the session's person (filed for another person) and the person's inbox. Returns the text and the find ids, which the
    open-item list leaves out."""
    queues = found.get('queues') or {}
    held, inbox = queues.get('toSend') or [], queues.get('inbox') or []
    if not held and not inbox:
        return '', set()
    return words.inbox_text(held, inbox), {item['id'] for item in held}


def next_text(ctx: Context) -> str:
    """decide.md Release 7: what the next round or step can start from. The open-item list (waiting questions, in_review
    designs, ready milestones, finished epics, what waits on the user) comes whole the first time between compactions, from
    one board read with the seeds; the model's judgment is the recommendation."""
    found, position = read_open(ctx) if ctx.board else ({}, {})
    seeded = seeds(ctx, found, position) if ctx.board else []
    items, elsewhere, waiting = open_items(ctx, found, position) if ctx.board else ([], {}, [])
    inbox, finds = inbox_text(found)
    waiting = [item for item in waiting if item['id'] not in finds]
    return lines(
        inbox,
        words.SEEDS_HEAD if ctx.board else '',
        *([words.seed_line(seed, priority_of(seed)) for seed in seeded] or ([words.SEEDS_NONE] if ctx.board else [])),
        items_text(ctx, items, elsewhere, waiting),
        *(topic_counts(items) if ctx.board else []),
        *words.proposal_text(proposal_rows(ctx.state.get('proposal'))),
        words.next_recommend(),
    )


PROPOSAL_FIELDS = {'title', 'summary', 'estimate', 'why', 'fresh', 'ids'}
QUESTION_NAME = re.compile(r'(?<![\w-])q\d+\b')  # a round's question id
ITEM_CANDIDATE = re.compile(r'\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+(?:\.\d+)*\b')  # hyphenated words: an id only when the board knows it


def names_in(ctx: Context, text: str, known: dict[str, bool]) -> list[str]:
    """The question ids and board items a text names, in reading order. A hyphenated word is a board item only when the board
    shows it (`step-back` is a word); `known` caches the reads. Without a board nothing is an item."""
    found = [(match.start(), match.group()) for match in QUESTION_NAME.finditer(text)]
    for match in ITEM_CANDIDATE.finditer(text) if ctx.board else ():
        word = match.group()
        if word not in known:
            try:
                ctx.board.checked('show', word, '--json', '--field', 'status')
                known[word] = True
            except ProtocolError:
                known[word] = False  # the board refuses an unknown id
        if known[word]:
            found.append((match.start(), word))
    return list(dict.fromkeys(name for _, name in sorted(found)))


def lead_titles(ctx: Context, ids: list[str], where: str) -> tuple[dict[str, str], list[str]]:
    """The board's title of each leading id; an id the board does not know is an error (`start round <ids>` needs them open)."""
    if not ctx.board:
        return {}, [f'{where}: `ids` need a board (a round names open board items)']
    titles, errors = {}, []
    for qid in dict.fromkeys(ids):
        try:
            titles[qid] = ((ctx.board.json('show', qid, '--json', '--field', 'title').get(qid) or {}).get('title') or '').strip()
        except ProtocolError:
            errors.append(f'{where}: `ids` names {qid}, which the board does not know')
    return titles, errors


def proposal_errors(ctx: Context, raw) -> tuple[list[str], dict[int, dict[str, str]]]:
    """Every error in a proposal (structure, plain words, leading ids against the board) and the leading ids' titles per row."""
    if not isinstance(raw, dict):
        return ['stdin must be an object with `rounds`'], {}
    errors = [f"unknown fields {', '.join(sorted(set(raw) - {'rounds'}))}"] if set(raw) - {'rounds'} else []
    rounds = raw.get('rounds', [])
    if not isinstance(rounds, list):
        return [*errors, '`rounds` must be a list'], {}
    if len(rounds) > PROPOSAL_ROUNDS:
        errors.append(f'`rounds` holds at most {PROPOSAL_ROUNDS}, not {len(rounds)}')
    titles, known = {}, {}
    for index, one in enumerate(rounds):
        where = f'rounds[{index}]'
        if not isinstance(one, dict):
            errors.append(f'{where}: must be an object')
            continue
        if set(one) - PROPOSAL_FIELDS:
            errors.append(f"{where}: unknown fields {', '.join(sorted(set(one) - PROPOSAL_FIELDS))}")
        ids = one.get('ids')
        if ids is not None and (not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i.strip() for i in ids)):
            errors.append(f'{where}: `ids`, when given, lists the question ids that must lead')
        elif ids:
            titles[index], lead_errors = lead_titles(ctx, [i.strip() for i in ids], where)
            errors += lead_errors
        for field, limit in (('title', TITLE_LIMIT), ('summary', SUMMARY_MAX), ('why', TEXT_LIMIT)):
            if not isinstance(one.get(field), str) or not one[field].strip():
                errors.append(f'{where}: `{field}` must be a non-empty string')
            elif len(one[field]) > limit:
                errors.append(f'{where}: `{field}` is {len(one[field])} characters, over the limit of {limit}')
            elif field != 'why' and (named := names_in(ctx, one[field], known)):
                errors.append(f"{where}: `{field}` names {', '.join(named)}: say it in plain words, without ids")
        estimate = one.get('estimate')
        if not (isinstance(estimate, dict) and set(estimate) == {'questions', 'unblocks'}
                and all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in estimate.values())):
            errors.append(f'{where}: `estimate` is your estimate as whole numbers: {{"questions": n, "unblocks": n}}')
        if not isinstance(one.get('fresh'), bool):
            errors.append(f'{where}: `fresh` must be true or false')
    return errors, titles


def set_proposal(ctx: Context, report: dict) -> str:
    if ctx.round and ctx.round['step'] != 'closed':
        fail(f"{ctx.round['protocol']} {ctx.round['id']} is open: propose the next rounds once it closes")
    errors, titles = proposal_errors(ctx, report)
    refuse_all([f'next --set: {error}' for error in errors])
    proposal = {'rounds': [{'title': one['title'].strip(), 'summary': one['summary'].strip(),
                            'estimate': {'questions': one['estimate']['questions'], 'unblocks': one['estimate']['unblocks']},
                            'why': one['why'].strip(), 'fresh': one['fresh'],
                            **({'ids': [i.strip() for i in one['ids']], 'idTitles': titles[index]} if one.get('ids') else {})}
                           for index, one in enumerate(report.get('rounds', []))]}
    ctx.state['proposal'] = proposal
    ctx.store.log({'round': None, 'event': 'proposed', 'rounds': [one['title'] for one in proposal['rounds']]})
    return words.proposal_stored(proposal_rows(proposal))


def proposal_rows(proposal: dict | None) -> list[dict] | None:
    """The rows of a stored proposal that show and start, in the order `show --json` exposes them and the console numbers them
    (a row without a title shows nowhere); None when no proposal is stored."""
    if not proposal:
        return None
    return [one for one in proposal.get('rounds') or [] if isinstance(one, dict) and str(one.get('title') or '').strip()]


def proposal_row(ctx: Context, number: int, topic: str | None, ids: list[str]) -> dict:
    """Row `number` (1-based) of the stored proposal, for `start round --proposal`; its topic and ids come from the row."""
    if topic:
        fail("--proposal takes the row's topic: not with --topic")
    if ids:
        fail("--proposal takes the row's ids: not with ids of your own")
    rows = proposal_rows(ctx.state.get('proposal'))
    if rows is None:
        fail('no proposal stored: `protocol next --set` stores one')
    if not 1 <= number <= len(rows):
        fail(f'no proposal row {number}: the stored proposal has {len(rows)}')
    return rows[number - 1]
