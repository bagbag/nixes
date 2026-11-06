"""Next: the seeds of the next round and the stored proposal."""
from __future__ import annotations

from .base import PROPOSAL_ROUNDS, SEEDS, TEXT_LIMIT, TITLE_LIMIT, json_block, lines
from .boards import foreign_holds
from .engine import Context, fail
from .questions import refuse_all
from .collect import dependency_order, items_text, open_items, priority_of, read_open


# Next: the ranked seeds of the next round and the model's stored proposal (decide.md Release 7, Next).

def seeds(ctx: Context, found: dict, position: dict) -> list[dict]:
    """The top open decision questions to start a round from: unblocked, not held by another live session; members of
    an open milestone first, then priority, then the work they hold (`board position`), prerequisites first as in Select."""
    items = (found.get('items') or {}).get('questions') or []
    live, _ = foreign_holds(ctx, items, position)
    member = {}
    for milestone in found.get('milestones') or []:
        scoped = ctx.board.json('health', '--json', '--root', milestone['id'], '--items', 'questions')
        for item in (scoped.get('items') or {}).get('questions') or []:
            member.setdefault(item['id'], milestone['id'])
    holds = {item['id']: item for item in position.get('questionsHoldingWork') or []}
    pool = [{'key': item['id'], 'id': item['id'], 'title': item.get('title', ''), 'priority': item.get('priority'),
             'blockedBy': [], 'holds': (holds.get(item['id']) or {}).get('holds') or 0,
             'holdsAll': (holds.get(item['id']) or {}).get('holdsAll') or 0, 'milestone': member.get(item['id'])}
            for item in items if not item.get('blockedBy') and item['id'] not in live]
    ordered = dependency_order(pool, lambda c: (c['milestone'] is None, priority_of(c), -c['holds'], -c['holdsAll'], c['key']))
    return ordered[:SEEDS]


def seed_line(seed: dict) -> str:
    return (f"- {seed['id']} · p{priority_of(seed)} · holds {seed['holds']}/{seed['holdsAll']} · "
            + (f"milestone {seed['milestone']}" if seed['milestone'] else 'no milestone') + f" · {seed['title']}")


def proposal_text(proposal: dict | None) -> list[str]:
    """A stored proposal's rows; a stored row may lack fields a later version wrote (a read never fails on it)."""
    if not proposal:
        return ['No proposal stored.']
    rows = [f"{index}. {r.get('title', '')}" + (f" · {r['premise']}" if r.get('premise') else '')
            + (f" · leads with {' '.join(r['ids'])}" if r.get('ids') else '')
            + f" · {'wants a fresh context' if r.get('fresh') else 'keeps the context'} · {r.get('why', '')}"
            for index, r in enumerate(proposal.get('rounds') or [], 1)]
    return ['Stored proposal' + (' (the first row is the recommended one):' if rows else ' (no rounds: the console offers a compaction when the context is large):'),
            *rows]


def topic_counts(ctx: Context, items: list[dict]) -> list[str]:
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
    ordered = sorted(tally.items(), key=lambda row: (-sum(row[1].values()), row[0]))
    return ['Open questions by topic (a label approximates a premise: a round on it takes the part that shares one):',
            *(f"- {topic} " + ', '.join(f'{n} p{priority}' if priority != 9 else f'{n} unprioritized'
                                        for priority, n in sorted(by_priority.items())) for topic, by_priority in ordered)]


def inbox_text(found: dict) -> tuple[str, set[str]]:
    """decide.md's Inbox step on a shared board, from `board health --json`'s queue lists: the finds held for
    the session's person (filed for another person) and the person's inbox. Returns the text and the find ids, which the
    open-item list leaves out."""
    queues = found.get('queues') or {}
    held, inbox = queues.get('toSend') or [], queues.get('inbox') or []
    if not held and not inbox:
        return '', set()
    row = lambda item: (f"- {item['id']} [{item.get('type')}] for "
                        + ', '.join(label[len('for:'):] for label in item.get('labels') or [] if label.startswith('for:'))
                        + f": {item.get('title', '')}")
    return lines(
        'Inbox step (decide.md): show each item to the user, who picks; never decide these alone.',
        *([f'Finds held for you to check, filed for another person: send, keep or close ({len(held)}):', *map(row, held)] if held else []),
        *([f'Your inbox, sent to you: take, pass on or close with a reason ({len(inbox)}):', *map(row, inbox)] if inbox else []),
        'Keep or take: board route <you> <id>; send or pass on: board send <person> <id>.',
    ), {item['id'] for item in held}


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
        f'Seeds for the next round (top {SEEDS} open questions, unblocked, not held by another live session; open-milestone '
        'members first, then priority, then the work they hold; holds: stopping at a milestone/everything downstream):'
        if ctx.board else '',
        *([seed_line(seed) for seed in seeded] or (['- none'] if ctx.board else [])),
        items_text(ctx, items, elsewhere, waiting),
        *(topic_counts(ctx, items) if ctx.board else []),
        *proposal_text(ctx.state.get('proposal')),
        'Recommend the next round or, when no question round leads, the other next step by priority and what it unblocks. '
        'Propose topics, not question sets: a row names a topic and its premise, and the round selects its questions at Collect. '
        'Rank the rows by priority and by how many questions each settles, and state the trade in `why`; a follow-up that '
        'reuses what was just read goes first, and milestone members stay ahead of the rest. '
        'Record the proposal with `protocol next --set` (stdin '
        + json_block({'rounds': [{'title': '<the topic in plain words>', 'premise': '<the premise its questions share>',
                                  'why': '<why this topic, and the priority/size trade>', 'fresh': False,
                                  'ids': ['<a question that must lead (optional)>']}]})
        + f'): at most {PROPOSAL_ROUNDS} rounds, the one that reuses the read context first with fresh false, other topics with '
        'fresh true; `rounds` may be empty to offer only a compaction. Do not tell the user a round will compact. '
        "Start a row with `protocol start round --topic '<title>: <premise>'`.",
    )


PROPOSAL_FIELDS = {'title', 'premise', 'why', 'fresh', 'ids'}


def proposal_errors(raw) -> list[str]:
    if not isinstance(raw, dict):
        return ['stdin must be an object with `rounds`']
    errors = [f"unknown fields {', '.join(sorted(set(raw) - {'rounds'}))}"] if set(raw) - {'rounds'} else []
    rounds = raw.get('rounds', [])
    if not isinstance(rounds, list):
        return [*errors, '`rounds` must be a list']
    if len(rounds) > PROPOSAL_ROUNDS:
        errors.append(f'`rounds` holds at most {PROPOSAL_ROUNDS}, not {len(rounds)}')
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
        for field, limit in (('title', TITLE_LIMIT), ('premise', TEXT_LIMIT), ('why', TEXT_LIMIT)):
            if not isinstance(one.get(field), str) or not one[field].strip():
                errors.append(f'{where}: `{field}` must be a non-empty string')
            elif len(one[field]) > limit:
                errors.append(f'{where}: `{field}` is {len(one[field])} characters, over the limit of {limit}')
        if not isinstance(one.get('fresh'), bool):
            errors.append(f'{where}: `fresh` must be true or false')
    return errors


def set_proposal(ctx: Context, report: dict) -> str:
    if ctx.round and ctx.round['step'] != 'closed':
        fail(f"{ctx.round['protocol']} {ctx.round['id']} is open: propose the next rounds once it closes")
    refuse_all([f'next --set: {error}' for error in proposal_errors(report)])
    proposal = {'rounds': [{'title': one['title'].strip(), 'premise': one['premise'].strip(), 'why': one['why'].strip(),
                            'fresh': one['fresh'], **({'ids': [i.strip() for i in one['ids']]} if one.get('ids') else {})}
                           for one in report.get('rounds', [])]}
    ctx.state['proposal'] = proposal
    ctx.store.log({'round': None, 'event': 'proposed', 'rounds': [one['title'] for one in proposal['rounds']]})
    return '\n'.join(['Stored.', *proposal_text(proposal)])
