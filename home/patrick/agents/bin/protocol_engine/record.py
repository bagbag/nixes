"""The round's Record and Closed steps and the board writes behind them."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .base import AWAY, ProtocolError, REVISES, lines, utcnow
from . import words
from .boards import COUNT_KEYS, held_decided, split_holds, statuses
from .engine import Context, by_id, fail, questions
from .questions import board_keys
from .told import report_hint


# Record: the engine writes each record and runs board record (which lints it).

def note_of(q: dict) -> bool:
    return isinstance(q.get('annotations'), dict) and bool(str(q['annotations'].get('notes') or '').strip())


def waiting_outside(ctx: Context) -> dict[str, str]:
    """The held questions still waiting on an outside result at Record (r8-q31), by id with the reason they are deferred:
    the `waitsFor` text, and for a question whose `waitsOn` reaches one, that chain (deferred with it, r11-q42)."""
    held = {q['id']: q for q in questions(ctx, 'held') if not q.get('recorded')}
    reasons = {qid: q['waitsFor'] for qid, q in held.items() if q.get('waitsFor')}
    grew = True
    while grew:
        grew = False
        for qid, q in held.items():
            premise = next((other for other in q.get('waitsOn') or [] if other in reasons), None)
            if qid not in reasons and premise:
                reasons[qid] = words.waits_on_deferred(premise, reasons[premise], bool(held[premise].get('waitsFor')))
                grew = True
    return reasons


def record_text(ctx: Context) -> str:
    todo = [q for q in questions(ctx, 'answered') if not q.get('recorded')]
    rows = [words.record_row(q, q['annotations']['notes'].strip() if note_of(q) else None) for q in todo]
    return lines(
        words.record_intro(ctx.round['id']),
        *rows,
        *(words.record_deferred(qid, reason, bool(by_id(ctx, qid).get('waitsFor'))) for qid, reason in waiting_outside(ctx).items()),
        words.RECORD_GIVE,
        report_hint(ctx, 'record', words.record_example(todo[:1])),
    )


def record_file(q: dict, fields: dict) -> str:
    chosen = q['answer'] or ''
    # AskUserQuestion answers carry the chosen labels (comma-joined for multiSelect) or the user's own words.
    picked = {part.strip() for part in chosen.split(',')}
    alternatives = fields.get('alternatives') or '\n'.join(
        f"- {o['label']}: {o['description']}".rstrip(': ') for o in q['options'] if o['label'] not in picked)
    source = {'dialog': 'User (dialog)', 'chat': 'User (chat)', 'model-reported': 'User (model-reported)',
              AWAY: 'Away round (autopilot took the recommendation; no person answered)'}[q['origin']]
    quoted = f"{source}, {q.get('answeredAt', utcnow())[:10]}: \"{q.get('quote') or chosen}\""
    if q.get('strength') == 'strong' and isinstance(q.get('strongBecause'), dict):
        quoted = 'Recommended (strong): ' + '; '.join(f'{k} {v}' for k, v in q['strongBecause'].items()) + '\n\n' + quoted
    return (f"## Question\n{q['text']}\n\n## Alternatives Considered\n{alternatives or '- none offered'}\n\n"
            f"## Decision\n{fields.get('decision') or chosen}\n\n## Rationale\n{fields['rationale'].strip()}\n\n{quoted}\n\n"
            + (f"## Premises\n{q['premises'].strip()}\n\n" if (q.get('premises') or '').strip() else '')
            + ('## Own rulings\n' + '\n'.join(f'- {words.ruling_line(x)}' for x in q['rulings']) + '\n\n' if q.get('rulings') else '')
            + ('## Earlier rulings\n' + '\n'.join(f"- {x['ruling'].strip()}: {x['verdict']}. {x['why'].strip()}" for x in q['priorRulings']) + '\n\n' if q.get('priorRulings') else '')
            + f"## Rule owner\n{fields['ruleOwner'].strip()}\n"
            + (f"\n## Reversal\n{fields['reversal'].strip()}\n" if q['origin'] == AWAY else '')
            + (f"Reopen the questions it closed: `board bd reopen {' '.join(board_keys(q.get('settles')))}`.\n"
               if q['origin'] == AWAY and board_keys(q.get('settles')) else ''))


def record_tag(ctx: Context, q: dict) -> str:
    return f"protocol:{ctx.store.session}:{ctx.round['id']}:{q['id']}"


def tagged_item(ctx: Context, tag: str) -> str | None:
    """The oldest item carrying `tag`: bd does not keep an external ref unique, and a Record cut after a create
    wrote its item lost the id, so the rerun looks it up before it creates."""
    rows = ctx.board.json('bd', 'list', '--external-ref', tag, '--all', '--brief', '--json')
    return min(rows, key=lambda row: (row.get('created_at') or '', row['id']))['id'] if rows else None


def board_item(ctx: Context, q: dict, path: Path, body: str | None = None) -> str:
    """The board id the record goes to: the question's item, else the draft created (or opened as a revision); `body`: the
    new item's text (a parked question's parts), else the question and its options."""
    if q['board']:
        return q['board']
    takeover = next((h['id'] for h in q['overlaps'] if h['outcome'] in ('duplicate', 'extend')), None)
    if takeover:
        q['board'] = takeover
        return takeover
    tag = record_tag(ctx, q)
    if found := tagged_item(ctx, tag):
        q['board'] = found
        return found
    packet = path.with_suffix('.packet.md')
    packet.write_text(body or f"## Question\n{q['text']}\n\nOptions: " + '; '.join(o['label'] for o in q['options'])
                      + f"\n\nStaged in round {ctx.round['id']}.\n", encoding='utf-8')
    # The released record it revises, else the first record it closes: the new question is linked to it (parent and topic
    # labels come from it) until Record closes it; link_record links the other records it closes the same way.
    revised = q.get('revises') or next(iter(q.get('replaces') or []), None)
    if revised:
        new = ctx.board.checked('revise', revised, '--title', q['title'], '--body-file', str(packet), '--external-ref', tag).strip()
    else:
        created = json.loads(ctx.board.checked('bd', 'create', '--type', 'decision', '--title', q['title'],
                                               '--body-file', str(packet), '--external-ref', tag, '--json') or '{}')
        new = created.get('id') if isinstance(created, dict) else None
    if not new:
        fail(f"{q['id']}: the board returned no id for the new question")
    q['board'] = new
    return new


def inherited_blocks(ctx: Context, q: dict) -> list[str]:
    """`bd batch` operations that give a rule question's record the `blocks` links of the items it settles (a released
    ruling blocks what it changes until planned, so closing the settled items must not unblock their dependents): the
    open items a settled item blocks wait on the record, and the open items a settled item waits on block the record.
    Edges among the settled items, to the record itself or to an item the record is linked to already are left."""
    settled = board_keys(q.get('settles'))
    if not settled:
        return []
    item = q['board']
    rows = ctx.board.json('show', *settled, item, '--json', '--field', 'dependencies')
    edges = {(dep['issue_id'], dep['depends_on_id'], dep['type']) for row in rows.values()
             for dep in (row or {}).get('dependencies') or []}
    linked = {frozenset((a, b)) for a, b, _ in edges if item in (a, b)}
    skip = {*settled, item}
    waiting = sorted({a for a, b, kind in edges if kind == 'blocks' and b in settled and a not in skip})
    blockers = sorted({b for a, b, kind in edges if kind == 'blocks' and a in settled and b not in skip
                       and not b.startswith('external:')})
    others = [*waiting, *blockers]
    open_items = {other for other, status in statuses(ctx, others).items() if status != 'closed'} if others else set()
    return [*(f'dep add {w} {item} blocks' for w in waiting if w in open_items and frozenset((w, item)) not in linked),
            *(f'dep add {item} {b} blocks' for b in blockers if b in open_items and frozenset((item, b)) not in linked)]


def link_record(ctx: Context, q: dict) -> None:
    """Relates the question's item to its `relate` hits and gives it the inherited blocks, in one batch; retried on a
    rerun until it succeeded once. bd keeps one edge per pair: a blocks link wins over a relate."""
    if not q.get('linked'):
        blocks = inherited_blocks(ctx, q)
        taken = {frozenset(op.split()[2:4]) for op in blocks}
        relate = [h['id'] for h in q['overlaps'] if h['outcome'] == 'relate' and frozenset((q['board'], h['id'])) not in taken]
        # A record the question closes stays linked (as a revision) until Record closes it: a Record that stops before the
        # close leaves a link `board release` refuses to pass, not two unrelated decided records.
        linked_now = q.get('revises') or next(iter(q.get('replaces') or []), None)
        pending = [old for old in q.get('replaces') or [] if old != linked_now]
        operations = [*(f"dep add {q['board']} {hit} relates-to" for hit in relate), *blocks,
                      *(f"dep add {q['board']} {old} {REVISES}" for old in pending)]
        if operations:
            ctx.board.checked('bd', 'batch', '-m', f"protocol: link {q['board']}", '--json', stdin=''.join(f'{op}\n' for op in operations))
    q['linked'] = True


def names_id(text: str, key: str) -> bool:
    return re.search(rf'(?<![\w.-]){re.escape(key)}(?![\w-]|\.\w)', text) is not None


def close_settled_away(ctx: Context, q: dict, item: str) -> None:
    """An away ruling is in force, so the questions it settles close when it is recorded; no release follows, and its reversal
    reopens them (r31-q143). Repeatable: a rerun closes what is left."""
    done = q.setdefault('closedSettled', [])
    for key in board_keys(q.get('settles')):
        if key not in done:
            ctx.board.checked('bd', 'close', key, '--reason', f'Settled by away ruling {item}, awaiting ratification')
            done.append(key)


def move_settled(ctx: Context, item: str, keys: list[str]) -> None:
    """The items a record settles, which stay claimed until a release closes them by that record."""
    settles = ctx.state.setdefault('settles', {})
    settles[item] = list(dict.fromkeys([*settles.get(item, []), *keys]))


def close_replaced(ctx: Context, q: dict, item: str) -> None:
    """Closes each decided record the recorded question replaces: `board supersede <old> --with <item>` once `item` is
    written and decided (it closes the old record and blocks the items waiting on it on the new one; a pending revision
    of the old record moves to the new one). The items the old record settles move to the new record, or they stay
    claimed with no release to close them. Repeatable: a record closed already is done. A hold of a gone session is
    taken; a live one's is refused."""
    todo = [old for old in q.get('replaces') or [] if old not in q.setdefault('closed', [])]
    if not todo:
        return
    rows = ctx.board.json('show', *todo, '--json', '--field', 'status', '--field', 'assignee')
    held = split_holds(ctx, {old: (rows.get(old) or {}).get('assignee') or '' for old in todo if (rows.get(old) or {}).get('status') != 'closed'})
    if held[0]:
        fail(f"{', '.join(f'{rid} (held by {holder})' for rid, holder in held[0].items())} closes with this record, and another "
             'live session holds it; ask that session to hand it off (board unclaim), then report again')
    for old in todo:
        status = (rows.get(old) or {}).get('status')
        if status == 'closed':
            pass
        elif status != 'decided':
            fail(f"{old} is {status}, not decided: it changed since Related, so it cannot close here")
        else:
            if old in held[1]:
                ctx.board.checked('take', old)
            result = ctx.board.run('supersede', old, '--with', item)
            after = (ctx.board.json('show', old, '--json', '--field', 'status').get(old) or {}).get('status')
            if after != 'closed':  # a failure before bd closed it; a later failure (blocks) leaves it closed
                fail(f"`board supersede {old} --with {item}` exited {result.returncode}: {(result.stderr or result.stdout).strip()}")
            if result.returncode != 0:
                ctx.messages.append(words.supersede_exited(old, item, result.returncode, (result.stderr or result.stdout).strip()))
        move_settled(ctx, item, ctx.state.get('settles', {}).pop(old, []))
        q['closed'].append(old)


def checkpoint(ctx: Context) -> None:
    """Saves the round and flushes the history after each question: a Record cut mid-way (the console's time limit) keeps
    the ids it created, and the rerun with the same report continues from there."""
    ctx.store.save(ctx.state)
    ctx.store.flush()


def record_accept(ctx: Context, report: dict) -> str:
    records, deferred = report.get('records') or {}, report.get('defer') or {}
    if not isinstance(records, dict) or not isinstance(deferred, dict):
        fail('`records` and `defer` map question ids to objects and reasons')
    outside = waiting_outside(ctx)
    waiting = [f"{q['id']} on {', '.join(q['waitsOn'])}" for q in questions(ctx, 'held')
               if q['id'] not in outside and not q.get('recorded')]
    if waiting:  # waitsOn refuses a circle and an unknown id, and an answer releases its dependents: nothing should reach this
        fail(f"questions still wait at Record: {'; '.join(waiting)}. A question waits only within its round: `protocol abandon`")
    todo = [q for q in questions(ctx, 'answered') if not q.get('recorded')]
    done = {q['id'] for q in questions(ctx, 'answered') if q.get('recorded')}  # a rerun of the same report skips them
    for qid in [*records, *deferred]:
        if qid not in {q['id'] for q in todo} | done:
            fail(f'{qid}: not an answered question awaiting its record')
    missing = [q['id'] for q in todo if q['id'] not in records and q['id'] not in deferred]
    if missing:
        fail(f"records missing for {', '.join(missing)}")
    for qid, fields in records.items():
        if not isinstance(fields, dict) or not all(str(fields.get(k) or '').strip() for k in ('rationale', 'ruleOwner')):
            fail(f'records.{qid}: needs rationale and ruleOwner')
        if by_id(ctx, qid)['origin'] == AWAY and not str(fields.get('reversal') or '').strip():
            fail(f'records.{qid}: an away answer needs a `reversal` (the steps that undo it, executable without remembered context)')
    # A question asked once its premise was answered rests on that answer: when the premise is deferred instead (the
    # engine learns of a deferral only here), the dependent's answer has no settled premise: it is deferred or restarted too (r11-q42).
    put_off = set(deferred) | set(outside) | {q['id'] for q in ctx.round['questions'] if q.get('recorded') == 'deferred'}
    resting = [f"{qid} rests on deferred {', '.join(w for w in q['waitsOn'] if w in put_off)}"
               for q in todo if (qid := q['id']) in records and any(w in put_off for w in q['waitsOn'])]
    if resting:
        fail('; '.join(resting) + ': defer it too, or restart it (`protocol restart <id>`) to ask it on a settled premise')
    unnamed = []
    for q in todo:  # a rule question's record names each item it settles (the release closes them by it)
        if q['id'] in records:
            said = ' '.join(str(records[q['id']].get(k) or '') for k in ('rationale', 'decision'))
            gone = [key for key in q.get('settles') or [] if not names_id(said, key)]
            if gone:
                unnamed.append(f"records.{q['id']}: the rule question settles {', '.join(gone)}; name each in the rationale or "
                               'decision with how the rule applies')
            unsaid = [old for old in q.get('replaces') or [] if not names_id(said, old)]
            if unsaid:  # the closed record's reader finds its replacement here, and the reader of this record what it replaced
                unnamed.append(f"records.{q['id']}: recording closes {', '.join(unsaid)}; name each in the rationale or "
                               'decision with what the new record keeps or changes')
    if unnamed:
        fail('; '.join(unnamed))
    folder = Path(ctx.round['records']) if ctx.round.get('records') else ctx.store.dir / 'records'
    folder.mkdir(parents=True, exist_ok=True)
    errors = []
    for qid, reason in outside.items():  # still waiting on an outside result: deferred with its reason, nothing asked again
        by_id(ctx, qid)['recorded'] = 'deferred'
        ctx.log('deferred', question=qid, reason=reason)
        checkpoint(ctx)
    for q in todo:
        if q['id'] in deferred:
            q['recorded'] = 'deferred'
            ctx.log('deferred', question=q['id'], reason=deferred[q['id']])
            checkpoint(ctx)
            continue
        path = folder / f"{ctx.round['id']}-{q['id']}.md"
        path.write_text(record_file(q, records[q['id']]), encoding='utf-8')
        q['recordFile'] = str(path)
        if not ctx.board:
            q['recorded'] = 'file'
            ctx.log('recorded', question=q['id'], board=None, file=str(path), ok=True)
            checkpoint(ctx)
            continue
        try:
            item = board_item(ctx, q, path)
            link_record(ctx, q)
            ctx.board.checked('claim', item)
            ctx.board.checked('record', item, str(path), *(['--status', 'needs_ratification'] if q['origin'] == AWAY else []))
            if q['origin'] == AWAY:
                close_settled_away(ctx, q, item)
            elif board_keys(q.get('settles')):
                move_settled(ctx, item, board_keys(q['settles']))  # the release closes them
            close_replaced(ctx, q, item)  # a failed close leaves the question unrecorded: the rerun retries what is left
            q['recorded'] = item
            (ctx.state.get('dropReasons') or {}).pop(item, None)  # a re-recorded record is back in the default set
        except ProtocolError as error:
            errors.append(f"{q['id']}: {error}")
        ctx.log('recorded', question=q['id'], board=q['board'], file=str(path), ok=bool(q.get('recorded')))
        for old in [one for one in q.get('closed') or [] if one not in q.setdefault('reported', [])]:  # after the record's own line
            q['reported'].append(old)
            ctx.log('superseded', question=q['id'], old=old, new=q['board'], partial=None)
        checkpoint(ctx)
    if errors:
        ctx.messages.append(words.not_recorded(errors))
        return 'record'
    return 'closed'


def abandon_note(round_questions: list[dict]) -> str:
    """What an abandoned round leaves behind: records written before the abandon stay decided (r24-q108)."""
    kept = [q.get('board') or q['id'] for q in round_questions if q.get('recorded') not in (None, 'deferred')]
    return words.abandoned_records(kept)


def release_claims(ctx: Context) -> None:
    """A hold ends with its work: the round releases what it claimed and did not record (deferred, held for the next
    round's Select, removed, or the round abandoned). Best effort: the round closes either way."""
    done = [q for q in ctx.round['questions'] if q.get('recorded') not in (None, 'deferred', 'file')]
    recorded = {q['board'] for q in done} | {key for q in done for key in q.get('settles') or []}  # settled items stay held to the release, or an away ruling closed them
    release = [item for item in dict.fromkeys(ctx.round.get('claimed', [])) if item not in recorded]
    if not release or not ctx.board:
        return
    try:
        ctx.board.checked('unclaim', *release)
        ctx.log('released', items=release)
    except ProtocolError as error:
        ctx.messages.append(words.claims_not_released(error, release))


def refresh_board(ctx: Context) -> bool:
    """Reads the board's counts and the size of a bare release (the decided records this session holds, minus the
    dropped), saved for the Board line and `next.release`; `show` never reads the board. Best effort: a failing read must
    not lose the board writes this call made."""
    try:
        found = ctx.board.json('health', '--json', '--items', 'decided')
    except ProtocolError as error:
        ctx.messages.append(words.counts_unavailable(error))
        return False
    ctx.state['counts'] = {key: (found.get('counts') or {}).get(key, 0) for key in COUNT_KEYS}
    dropped = ctx.state.get('dropReasons') or {}
    ctx.state['releasable'] = sum(1 for rid in held_decided(ctx.board, found) if rid not in dropped)
    return True


def closed_enter(ctx: Context) -> None:
    r = ctx.round
    r['pending'], r['batch'] = None, None
    release_claims(ctx)
    r['closedAt'] = utcnow()
    if ctx.board and refresh_board(ctx):
        r['countsAt'] = r['closedAt']
    ctx.log('closed', recorded=[q['id'] for q in r['questions'] if q.get('recorded')])


def closed_text(ctx: Context) -> str:
    r = ctx.round
    done = [words.closed_done(q) for q in r['questions'] if q.get('recorded')]
    counts = ctx.state.get('counts')
    parked = [words.closed_parked(q) for q in r['questions'] if q['status'] == 'parked']
    return '\n'.join([
        words.round_closed(r['id']), *done, *parked,
        words.board_line(counts if counts and r.get('countsAt') else None, bool(ctx.board)),
        *([words.closed_next(waiting['count'])] if (waiting := release_next(ctx)) else []),
    ])


def release_next(ctx: Context) -> dict | None:
    """The bare release's size as the last board read left it (`refresh_board`); `show` never reads the board."""
    count = ctx.state.get('releasable') or 0
    return {'count': count} if count else None
