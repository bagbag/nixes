"""Release: the Board-check, Own-rulings and Scoped steps."""
from __future__ import annotations

import copy

from .base import NO_RUN, ProtocolError, lines
from . import words
from .boards import statuses
from .engine import Context, fail
from .questions import DISCLOSURE
from .told import report_hint
from .release_set import HIT_CLASSES, SCOPED_PASSES, apply_changes, drop, in_set, scoped_records, set_rows, stop


def board_check_enter(ctx: Context) -> None:
    """The revisions the set's records name without a link (`board check --json`: a question missed them), read once on
    entering the step and listed in its text."""
    found = []
    try:
        rows = ctx.board.json('check', '--json')
        found = [row for row in (rows.get('unlinkedRevisions') if isinstance(rows, dict) else None) or []
                 if row.get('id') in in_set(ctx) or row.get('other') in in_set(ctx)]
    except ProtocolError as error:
        ctx.messages.append(words.unlinked_unavailable(error))
    ctx.round['unlinked'] = found


def board_check_text(ctx: Context) -> str:
    unlinked = ctx.round.get('unlinked') or []
    return lines(
        words.board_check_intro(ctx.round['id']),
        *(words.hit_class_row(name, meaning) for name, meaning in HIT_CLASSES.items()),
        *set_rows(ctx),
        *([words.unlinked_revisions(unlinked)] if unlinked else []),
        *(words.prefilled(rid, settled) for rid, settled in settled_in_set(ctx).items()),
        *(words.not_closed(rid, items) for rid, items in settled_split(ctx)[1].items()),
        words.BOARD_CHECK_NAMES,
        report_hint(ctx, 'board-check', words.board_check_example((in_set(ctx) or ['<id>'])[0], HIT_CLASSES)),
    )


def settled_split(ctx: Context) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """The set's rule records and the board items their questions settled (recorded in this session's state): (the ones
    still open questions, which the release closes as answered; the others, named with their status and left alone: a
    decided record or a question closed meanwhile is no open question to close)."""
    recorded = ctx.state.get('settles') or {}
    mine = {rid: recorded[rid] for rid in in_set(ctx) if recorded.get(rid)}
    status = statuses(ctx, [item for items in mine.values() for item in items]) if mine else {}
    keep = {rid: [item for item in items if status.get(item) == 'open'] for rid, items in mine.items()}
    skip = {rid: [f"{item} ({status.get(item) or 'unknown'})" for item in items if status.get(item) != 'open'] for rid, items in mine.items()}
    return {rid: items for rid, items in keep.items() if items}, {rid: items for rid, items in skip.items() if items}


def settled_in_set(ctx: Context) -> dict[str, list[str]]:
    return settled_split(ctx)[0]


def prefill_settled(ctx: Context, checks: dict, closes: dict) -> tuple[dict, dict]:
    """Adds, for each settled item of a rule record in the set, the answers row `answered: close` and the close by that
    record, so `board release --closes` closes it. The report's own rows and closes stay."""
    checks, closes = copy.deepcopy(checks), copy.deepcopy(closes)
    for rid, settled in settled_in_set(ctx).items():
        classes = checks.get(rid)
        if not isinstance(classes, dict):
            continue  # the shape check names it
        rows = classes.get('answers')
        rows = [] if rows in (None, 'none') else rows
        if not isinstance(rows, list):
            continue
        for item in settled:
            if not any(isinstance(row, dict) and row.get('item') == item for row in rows):
                rows.append({'item': item, 'action': 'answered: close'})
            if isinstance(closes.get(item), list):
                closes[item] = list(dict.fromkeys([*closes[item], rid]))
            elif item not in closes:
                closes[item] = [rid]
        classes['answers'] = rows
    return checks, closes


def hit_items(checks: dict, rid: str, name: str) -> set[str]:
    rows = checks[rid][name]
    return set() if rows == 'none' else {row['item'] for row in rows}


def board_check_accept(ctx: Context, report: dict) -> str:
    r = ctx.round
    checks = report.get('checks')
    if not isinstance(checks, dict):
        fail('`checks` maps each record to its hit classes')
    if isinstance(report.get('closes') or {}, dict):
        checks, merged = prefill_settled(ctx, checks, report.get('closes') or {})
        report = {**report, 'closes': merged}
    current = in_set(ctx)
    problems = [f'no board check for {rid}' for rid in current if rid not in checks]
    problems += [f'{rid} is not in the set' for rid in checks if rid not in current]
    for rid, classes in checks.items():
        if not isinstance(classes, dict):
            problems.append(f'checks.{rid}: map each hit class to "none" or rows')
            continue
        problems += [f'checks.{rid}: no `{name}` entry ("none" allowed)' for name in HIT_CLASSES if name not in classes]
        problems += [f'checks.{rid}: unknown hit class {name}' for name in classes if name not in HIT_CLASSES]
        for name, rows in classes.items():
            if rows != 'none' and not (isinstance(rows, list) and rows and all(
                    isinstance(row, dict) and str(row.get('item') or '').strip() and str(row.get('action') or '').strip()
                    for row in rows)):
                problems.append(f'checks.{rid}.{name}: "none" or rows {{"item", "action"}}')
    if problems:
        fail('board check: ' + '; '.join(problems))
    supersedes = report.get('supersedes') or []
    closes = report.get('closes') or {}
    if not isinstance(supersedes, list) or not isinstance(closes, dict):
        fail('`supersedes` is a list of {old, new, partial?}; `closes` maps questions to the records answering them')
    for index, sup in enumerate(supersedes):
        if not isinstance(sup, dict) or not all(isinstance(sup.get(k), str) and sup[k].strip() for k in ('old', 'new')) \
                or not isinstance(sup.get('partial', ''), (str, type(None))):
            problems.append(f'supersedes[{index}]: {{"old", "new", "partial": "<rule>" (optional)}}')
        elif sup['new'] not in current:
            problems.append(f"supersedes[{index}]: {sup['new']} is not in the set")
        elif sup['old'] not in hit_items(checks, sup['new'], 'revises'):
            problems.append(f"supersedes[{index}]: {sup['old']} is no `revises` hit of {sup['new']}")
    for question, recs in closes.items():
        if not isinstance(recs, list) or not recs or not all(isinstance(x, str) for x in recs):
            problems.append(f'closes.{question}: the records answering it, as a list')
        elif [x for x in recs if x not in current]:
            problems.append(f"closes.{question}: not in the set: {', '.join(x for x in recs if x not in current)}")
        elif [x for x in recs if question not in hit_items(checks, x, 'answers')]:
            problems.append(f"closes.{question}: no `answers` hit of {', '.join(x for x in recs if question not in hit_items(checks, x, 'answers'))}")
    if not problems and (closes or supersedes):
        problems += board_targets(ctx, list(closes), [sup['old'] for sup in supersedes])
    if problems:
        fail('board check: ' + '; '.join(problems))
    r['checks'] = checks
    r['supersedes'] = [{'old': sup['old'], 'new': sup['new'], 'partial': sup.get('partial')} for sup in supersedes]
    r['closes'] = {question: list(dict.fromkeys(recs)) for question, recs in closes.items()}
    ctx.log('board-checked', supersedes=len(supersedes), closes=sorted(closes))
    stopped = apply_changes(ctx, report.get('changed') or {}, 'changed', every=False)
    if stopped:
        return stopped
    for rid in in_set(ctx):  # decide.md: an open question its premise rests on holds the record
        waiting = sorted(hit_items(checks, rid, 'premise'))
        if waiting:
            drop(ctx, rid, words.premise_waits(waiting))
    # board release refuses a record waiting on an unsettled item outside the set: it leaves the set now, while the
    # report can still change, not after the approval (a blocker dropped here can drop its dependents in turn).
    blocked = {item['id']: item.get('blockedBy') or []
               for item in (ctx.board.json('health', '--json', '--items', 'decided').get('items') or {}).get('decided') or []}
    while True:
        waiting = {rid: [b for b in blocked.get(rid, []) if b not in in_set(ctx)] for rid in in_set(ctx)}
        waiting = {rid: blockers for rid, blockers in waiting.items() if blockers}
        if not waiting:
            break
        found = statuses(ctx, [b for blockers in waiting.values() for b in blockers])
        for rid, blockers in waiting.items():
            drop(ctx, rid, words.blocker_waits(blockers, found))
    if not in_set(ctx):
        return stop(ctx, words.EMPTY_SET, [])
    return 'own-rulings'


def board_targets(ctx: Context, closes: list[str], olds: list[str]) -> list[str]:
    """The answered closes and supersedes must exist, and each close be an open question this session may close: the
    conditions under which `board release --closes` refuses, checked while the report can still change."""
    try:
        found = ctx.board.json('show', *dict.fromkeys([*closes, *olds]), '--json', '--field', 'status', '--field',
                               'issue_type', '--field', 'assignee')
    except ProtocolError as error:
        return [f'closes and supersedes: {error}']
    me = ctx.board.actor.split('/', 1)[0]
    problems = []
    for question in closes:
        row = found.get(question) or {}
        if row.get('status') == 'closed':
            continue  # closed already: the release skips it
        if row.get('issue_type') != 'decision' or row.get('status') not in ('open', 'in_progress'):
            problems.append(f"closes.{question}: {row.get('status')} {row.get('issue_type')}, not an open question")
        elif row.get('assignee') and row['assignee'].split('/', 1)[0] != me:
            problems.append(f"closes.{question}: held by {row['assignee']}; hand it off first (comment, or ask its "
                            'session), or leave it out')
    return problems


def own_rulings_text(ctx: Context) -> str:
    return lines(
        words.own_rulings_intro(ctx.round['id']),
        *set_rows(ctx),
        report_hint(ctx, 'own-rulings', words.own_rulings_example((in_set(ctx) or ['<id>'])[0])),
    )


def own_rulings_accept(ctx: Context, report: dict) -> str:
    rulings = report.get('rulings')
    if not isinstance(rulings, list):
        fail('`rulings` lists every ruling you made in the set (an empty list when there is none)')
    current = in_set(ctx)
    for index, ruling in enumerate(rulings):
        if not isinstance(ruling, dict) or ruling.get('record') not in current:
            fail(f'rulings[{index}]: `record` names a record of the set')
        missing = [k for k in DISCLOSURE if not str(ruling.get(k) or '').strip()]
        if missing or not isinstance(ruling.get('sure'), bool):
            fail(f"rulings[{index}]: needs {', '.join(missing) or 'the fields'} and `sure` true or false")
    ctx.round['rulings'] = rulings
    ctx.log('own-rulings', rulings=len(rulings), unsure=sum(1 for x in rulings if not x['sure']))
    return 'scoped'


def scoped_args(ctx: Context) -> str:
    return ' '.join(scoped_records(ctx))


def scoped_enter(ctx: Context) -> str | None:
    """The scoped step-back, then ground, on the revised records (r8-q36), once per release: the pending pass waits for
    its report; without revised records, or once both ran, the approval follows."""
    r = ctx.round
    done = r.setdefault('scoped', {'done': []})['done']
    command = next((one for one in SCOPED_PASSES if one not in done), None)
    if command is None or not scoped_records(ctx):
        ctx.set_pending(None)
        return 'approval'
    args = scoped_args(ctx)
    if (r['pending'] or {}).get('command') != command or r['pending'].get('args') != args:
        ctx.set_pending(command, args)
    return None


def scoped_text(ctx: Context) -> str:
    r = ctx.round
    pending = r['pending'] or {}
    command, args = pending.get('command'), pending.get('args')
    return lines(words.scoped_text(r['id'], command, args, ctx.codex),
                 report_hint(ctx, 'scoped', words.scoped_example(command, scoped_records(ctx)[:1])))


def scoped_accept(ctx: Context, report: dict) -> str:
    r = ctx.round
    pending = r['pending'] or {}
    command = report.get('pass')
    if command != pending.get('command'):
        fail(f"`pass` is {pending.get('command')}, the scoped pass waiting; the other follows its report")
    if not ctx.codex:  # Codex has no console to observe its runs
        if command not in r['observed']:
            fail(NO_RUN.format(command=command))
        if r['observed'][command].get('pending') != pending.get('id'):
            fail(f"/{command} ran without the revised records as its argument (`{pending.get('args')}`)")
    origin = (r['observed'].get(command) or {}).get('origin', 'model')
    raw = report.get('records')
    ids = scoped_records(ctx)
    changed = [rid for rid, value in raw.items() if value != 'unchanged'] if isinstance(raw, dict) else []
    ctx.log('pass', command=command, changes=len(changed), questions=changed, added=[], origin=origin,
            summary=report.get('summary'), scope='release', records=ids,
            kind='scoped', scoped=ids)  # queued: a refusal drops it
    stopped = apply_changes(ctx, raw, 'records', every=True, scope=ids)
    r['observed'].pop(command, None)
    r['scoped']['done'].append(command)  # once per release: a later revision does not re-arm the pair
    r['pending'] = None
    return stopped or 'scoped'
