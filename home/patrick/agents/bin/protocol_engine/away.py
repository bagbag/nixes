"""Away rounds: settling questions while nobody can answer."""
from __future__ import annotations

from pathlib import Path

from .base import AWAY, SETTLES, utcnow
from .engine import Context, by_id, fail, premise_status, questions, touch
from .questions import refuse_all
from .render import question_parts
from . import words
from .record import board_item


# Away rounds (r28-q126, q128, r29): while the role is autopilot nobody can answer, so Ask opens no batch, dialog or print; the
# model reports `act` (the recommendation is the answer; Record writes it as needs_ratification with its reversal) or `park`
# (an open, unassigned decision on the board) per question. unattended.md Authority owns which question gets which.

SWITCH_TO_SOLO = 'run `session-lead-mode activate solo` first'


def away_guard(ctx: Context) -> None:
    """What an away round cannot do: a release (only the person approves) and a round without a board (nothing would track its
    records for ratification, nor hold its parked questions)."""
    if ctx.round['protocol'] == 'release':
        fail(f'only the person approves a release: {SWITCH_TO_SOLO}, or `protocol abandon` (nothing releases; `start release` takes the same records again)')
    if ctx.board is None:
        fail(f'an away round records and parks on the board, and this round has none (--no-board): {SWITCH_TO_SOLO}, or `protocol abandon`')


def parked_text(ctx: Context, q: dict) -> str:
    """What a parked question's board item carries: the question with the parts the person would have seen, recommendation included."""
    parts = '\n\n'.join(words.part_block(name, text) for name, text in question_parts(ctx, q).items())
    waits = [by_id(ctx, other)['title'] for other in q.get('waitsOn') or []]
    return (f"## Question\n{q['text']}\n\n{parts}\n\nParked in round {ctx.round['id']} while the person was away (autopilot): "
            'the recommendation was not acted on.\n' + (f"Waits on: {'; '.join(waits)}.\n" if waits else ''))


def link_parked(ctx: Context) -> None:
    """The board shows each wait between parked questions as a plain link: blocking would outlast the answer (r31-q145)."""
    for q in questions(ctx, 'parked'):
        done = q.setdefault('linked', [])
        for other in q.get('waitsOn') or []:
            target = by_id(ctx, other).get('parked')
            if target and other not in done:
                ctx.board.checked('bd', 'dep', 'add', q['parked'], target, '-t', 'relates-to')
                done.append(other)


def park(ctx: Context, q: dict) -> None:
    """The question stays (or becomes) an open, unassigned decision on the board with its parts and recommendation."""
    folder = Path(ctx.round['records']) if ctx.round.get('records') else ctx.store.dir / 'records'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{ctx.round['id']}-{q['id']}.md"
    text = parked_text(ctx, q)
    existing = q['board'] or next((h['id'] for h in q['overlaps'] if h['outcome'] in ('duplicate', 'extend')), None)
    item = board_item(ctx, q, path, text)
    if existing:  # the item exists already; the parts go in as a comment
        packet = path.with_suffix('.packet.md')
        packet.write_text(text, encoding='utf-8')
        ctx.board.checked('bd', 'comments', 'add', item, '-f', str(packet))
    claimed = ctx.round.get('claimed', [])
    if item in claimed:
        ctx.board.checked('unclaim', item)
        claimed.remove(item)
    q.update(status='parked', parked=item)
    ctx.log('parked', question=q['id'], board=item)


def park_waiting(ctx: Context) -> None:
    """A question waiting on a parked one parks too (through chains)."""
    while True:
        gone = {q['id'] for q in questions(ctx, 'parked')}
        waiting = [q for q in questions(ctx, 'held', 'draft', 'ready') if gone & set(q.get('waitsOn') or [])]
        if not waiting:
            link_parked(ctx)
            return
        for q in waiting:
            park(ctx, q)


def away_prepare(ctx: Context) -> None:
    away_guard(ctx)
    park_waiting(ctx)


def away_settle(ctx: Context, report: dict) -> str:
    settle = report.get('settle')
    ready = [q for q in questions(ctx, 'ready') if not q.get('typed')]
    if not isinstance(settle, dict):
        fail('`settle` maps each question to "act" or "park"')
    errors = [f'settle: no entry for {q["id"]}' for q in ready if q['id'] not in settle]
    errors += [f'settle: {qid} is not waiting to be settled' for qid in settle if qid not in {q['id'] for q in ready}]
    errors += [f'settle.{qid}: "act" or "park"' for qid, value in settle.items() if value not in SETTLES]
    refuse_all(errors)
    now = utcnow()
    acted = [q for q in ready if settle[q['id']] == 'act']
    for q in acted:
        q.update(status='answered', answer=q['recommendation'], origin=AWAY, answeredAt=now, quote=None)
        ctx.state['answers'][q['id']] = q['recommendation']
    before = {q['id'] for q in questions(ctx, 'parked')}
    for q in ready:
        if settle[q['id']] == 'park':
            park(ctx, q)
    if acted:
        ctx.round['check']['challenged'] = False  # the answers are news to the last challenge-rulings run
        touch(ctx, [q['id'] for q in acted])
    for q in questions(ctx, 'draft', 'held', 'ready'):
        q['status'] = premise_status(ctx, q)
    park_waiting(ctx)
    ctx.log('settled', acted=[q['id'] for q in acted], parked=[q['id'] for q in questions(ctx, 'parked') if q['id'] not in before])
    return 'ask'


def away_cap(ctx: Context) -> str:
    """The check cap while away: no cap dialog, the round's unsettled questions park."""
    away_guard(ctx)
    ctx.round['pending'] = None
    ctx.log('cap', cycle=ctx.round['check']['cycle'], away=True)
    for q in questions(ctx, 'draft', 'held', 'ready'):
        park(ctx, q)
    link_parked(ctx)
    return 'ask'
