"""The round's Collect and Select steps and the open-item lists."""
from __future__ import annotations

from .base import CLASSES, COLLECT_VIEWS, ProtocolError, lines
from . import words
from .store import next_id
from .boards import claim_items, foreign_holds, read_counts, view_rows
from .engine import Context, fail
from .told import first_time, report_hint


def items_text(ctx: Context, items: list[dict], elsewhere: dict[str, list[str]], waiting: list[dict],
               named: list[str] | None = None, bare: bool = False, whole: bool = False) -> str:
    """The open-item list: whole the first time between compactions that `protocol next` or a round's pre-pass needs it,
    its rows grouped under a heading per view and status (r18-q68, q69); `whole` (a topic round's pre-pass) prints it
    whole every time (r24-q104). Later the named ids, the counts per kind and the command that lists them again; `bare`
    adds that a bare round lists before it selects."""
    if not items and not elsewhere and not waiting:
        return ''
    if first_time(ctx, 'items') or whole:
        groups: dict[tuple[str, str], list[dict]] = {}
        for item in items:
            groups.setdefault((item['view'], str(item['status'])), []).append(item)
        listed = [(heading, status, rows) for view, (heading, _) in words.VIEW_LABELS.items()
                  for (group_view, status), rows in groups.items() if group_view == view]
        return words.items_whole(len(items) + len(waiting), named, listed, waiting, elsewhere)
    by_id = {item['id']: item for item in items}
    tally = {view: sum(1 for item in [*items, *waiting] if item['view'] == view) for view in words.VIEW_LABELS}
    counts = ', '.join(f'{n} {words.VIEW_LABELS[view][1]}' for view, n in tally.items() if n)
    return words.items_counted([by_id[rid] for rid in named or [] if rid in by_id] if named else None, counts, bare)


def collect_text(ctx: Context) -> str:
    r = ctx.round
    named = r.get('named') or []
    points = [words.collect_point(point) for point in r['points']]
    missing = [p['id'] for p in r['points'] if p['id'] not in r['classes']]
    topic = r.get('topic')
    listing = items_text(ctx, r['items'], r.get('heldElsewhere') or {}, r.get('waiting') or [], named)  # the pre-pass printed the list
    return lines(
        words.collect_intro(r['id']),
        *([words.collect_topic(topic)] if topic else []),
        listing or (words.collect_empty(bool(ctx.board)) if not points else ''),
        *points,
        words.collect_unclassified(missing),
        report_hint(ctx, 'collect', words.COLLECT_EXAMPLE),
    )


def collect_accept(ctx: Context, report: dict) -> str:
    r = ctx.round
    for raw in report.get('points') or []:
        point = {'text': raw} if isinstance(raw, str) else raw
        if not isinstance(point, dict) or not str(point.get('text') or '').strip():
            fail('points: each needs a text')
        pid = next_id(ctx.state, 'point', 'pt')
        r['points'].append({'id': pid, 'text': point['text']})
        if point.get('class'):
            r['classes'][pid] = {'class': point['class'], 'owner': point.get('owner')}
    classes = report.get('classes') or {}
    if not isinstance(classes, dict):
        fail('`classes` must map ids to a class')
    keys = {i['id'] for i in r['items']} | {p['id'] for p in r['points']}
    for key, value in classes.items():
        if key not in keys:
            fail(f'classes: unknown id {key}')
        value = {'class': value} if isinstance(value, str) else value
        if not isinstance(value, dict) or value.get('class') not in CLASSES:
            fail(f"classes.{key}: class must be one of {', '.join(CLASSES)}")
        if value['class'] == 'ruled' and not str(value.get('owner') or '').strip():
            fail(f'classes.{key}: an already ruled point cites its owner')
        r['classes'][key] = {'class': value['class'], 'owner': value.get('owner')}
    missing = sorted({p['id'] for p in r['points']} - set(r['classes']))
    if missing:
        fail(f"every pasted point needs a class; unclassified: {', '.join(missing)}")
    tally = {}
    for value in r['classes'].values():
        tally[value['class']] = tally.get(value['class'], 0) + 1
    ctx.log('classified', classes=tally)
    return 'select'


def priority_of(c: dict) -> int:
    return c['priority'] if c.get('priority') is not None else 9


def dependency_order(pool: list[dict], rank) -> list[dict]:
    """Prerequisites (`blockedBy` keys inside the pool) before their dependents, otherwise by `rank`, a sort key per
    entry: the one ordering Select's candidates and `protocol next`'s seeds share."""
    keys = {c['key'] for c in pool}
    ordered, seen = [], set()

    def visit(c, path=()):
        if c['key'] in seen or c['key'] in path:
            return
        for blocker in c.get('blockedBy') or []:
            if blocker in keys:
                visit(next(x for x in pool if x['key'] == blocker), (*path, c['key']))
        seen.add(c['key'])
        ordered.append(c)

    for c in sorted(pool, key=rank):
        visit(c)
    return ordered


def candidates(ctx: Context) -> list[dict]:
    """Points for the user (and own rulings to confirm); prerequisites before their dependents, then by priority."""
    r = ctx.round
    def scoped(key: str) -> bool:  # unclassified board items stay out of this round
        return r['classes'].get(key, {}).get('class') in ('user', 'own')

    pool = [{**item, 'key': item['id'], 'source': 'board'} for item in r['items'] if scoped(item['id'])]
    pool += [{'key': p['id'], 'id': p['id'], 'title': p['text'], 'priority': 9, 'blockedBy': [], 'source': 'pasted'}
             for p in r['points'] if scoped(p['id'])]
    first = set(r.get('first') or [])  # the pre-pass's ask-first points lead (prerequisites still come before their dependents)
    return dependency_order(pool, lambda c: (c['key'] not in first, priority_of(c), c['key']))


def select_text(ctx: Context) -> str:
    rows = [words.select_row(c['key'], c.get('priority', '?'), ctx.round['classes'].get(c['key'], {}).get('class'),
                             c.get('blockedBy') or [], c['title'], c['key'] in (ctx.round.get('first') or []))
            for c in candidates(ctx)]
    return lines(
        words.select_intro(ctx.round['id'], ctx.round.get('topic'), bool(ctx.round.get('topic') or ctx.round.get('named'))),
        *(rows or [words.SELECT_NONE]),
        report_hint(ctx, 'select', {'select': [c['key'] for c in candidates(ctx)[:2]] or ['<id>']}),
    )


def select_accept(ctx: Context, report: dict) -> str:
    chosen = report.get('select')
    if not isinstance(chosen, list) or not all(isinstance(i, str) for i in chosen):
        fail('`select` must be a list of candidate ids')
    pool = {c['key']: c for c in candidates(ctx)}
    unknown = [key for key in chosen if key not in pool]
    if unknown:
        fail(f"not a candidate: {', '.join(unknown)}")
    for key in chosen:
        waiting = [b for b in pool[key].get('blockedBy') or [] if b in pool and b not in chosen]
        if waiting:
            fail(f"{key} waits on {', '.join(waiting)}: select its prerequisite too (stage {key} waiting on it) or leave {key}")
    if not chosen:
        return 'closed'
    claims = [key for key in chosen if pool[key]['source'] == 'board']
    taken = [key for key in claims if pool[key].get('heldBy')]  # a gone session's hold: take it over, as the release does
    if taken and ctx.board:
        ctx.board.checked('take', *taken)
        ctx.round['claimed'] = [*ctx.round.get('claimed', []), *taken]
    if claims and ctx.board and [key for key in claims if key not in taken]:
        claim_items(ctx, [key for key in claims if key not in taken])
    ctx.log('selected', selected=chosen, claimed=claims if ctx.board else [])
    ctx.round['selected'] = list(chosen)
    return 'stage'


OPEN_VIEWS = ('decided', 'questions', 'ratification', 'toAccept', 'toReview', 'forUser')  # `board health --json` item views Collect offers


def read_open(ctx: Context) -> tuple[dict, dict]:
    """The board reads the open-item list comes from: `board health` for COLLECT_VIEWS, and `board position`."""
    return ctx.board.json('health', '--json', '--items', COLLECT_VIEWS), ctx.board.json('position', '--json')


def open_items(ctx: Context, found: dict, position: dict) -> tuple[list[dict], dict[str, list[str]], list[dict]]:
    """(items, elsewhere, waiting): every open item Collect offers, once under the first view that has it, the ids another
    live session holds by holder, and the items assigned to the user. Another live session's holds stay out (board claim
    refuses them), and so do the user's, which the list shows apart; a gone session's hold stays, marked: a deciding
    session takes it over (board take), as the release does."""
    seen = {}
    row = lambda item, view: {'id': item['id'], 'view': view, 'status': item.get('status'), 'type': item.get('type'),
                              'title': item.get('title', ''), 'priority': item.get('priority'),
                              'labels': item.get('labels') or [], 'blockedBy': item.get('blockedBy') or []}
    for view in OPEN_VIEWS:
        for item in view_rows(found, view):
            seen.setdefault(item['id'], row(item, view))
    for view, key in (('readyMilestone', 'readyMilestones'), ('finishedEpic', 'finishedEpics')):
        for item in position.get(key) or []:
            seen.setdefault(item['id'], row(item, view))
    live, gone = foreign_holds(ctx, [item for view in OPEN_VIEWS for item in view_rows(found, view)], position)
    for rid, holder in gone.items():
        seen[rid]['heldBy'] = f'{holder} (gone)'
    elsewhere, waiting = {}, []
    for rid, holder in live.items():
        if holder == 'user':
            waiting.append(seen[rid])
        else:
            elsewhere.setdefault(holder.split('/', 1)[0], []).append(rid)
        del seen[rid]
    return list(seen.values()), elsewhere, waiting


def named_errors(ctx: Context, named: list[str], items: list[dict], elsewhere: dict[str, list[str]], waiting: list[dict]) -> list[str]:
    """`start round <ids>`: each named id must be an open item the round offers; one a live session holds, a closed or an
    unknown one, and an open one no round offers are refused by name."""
    offered = {item['id'] for item in items}
    held = {rid: f'live session {holder}' for holder, ids in elsewhere.items() for rid in ids} | {item['id']: 'the user' for item in waiting}
    other = [rid for rid in named if rid not in offered and rid not in held]
    states = {}
    for rid in other:  # one read each: the board refuses a read naming an unknown id as a whole
        try:
            states |= ctx.board.json('show', rid, '--json', '--field', 'status')
        except ProtocolError:
            states[rid] = {'status': None}
    errors = []
    for rid in named:
        if rid in held:
            errors.append(f'{rid} is held by {held[rid]}')
        elif rid not in offered:
            status = (states.get(rid) or {}).get('status')
            errors.append(f'{rid} is ' + ('unknown' if status is None else 'closed' if status == 'closed'
                                          else f'{status}, an item no round offers'))
    return errors


def read_listing(ctx: Context) -> None:
    """The board's open items for the round (read as it starts, so a bad named id refuses `start round`); the pre-pass shows them
    and Collect classifies them."""
    if not ctx.board or ctx.round.get('scope') == 'discussion':
        return  # a discussion round's points come from the model; board items join through Related
    found, position = read_open(ctx)
    ctx.state['counts'] = read_counts(found)
    ctx.round['items'], ctx.round['heldElsewhere'], ctx.round['waiting'] = open_items(ctx, found, position)
    errors = named_errors(ctx, ctx.round.get('named') or [], ctx.round['items'], ctx.round['heldElsewhere'], ctx.round['waiting'])
    if errors:
        fail('start round: ' + '; '.join(errors))
