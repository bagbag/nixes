"""The round's Record and Closed steps and the board writes behind them."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .base import AWAY, ProtocolError, lines, taken_over, utcnow
from . import schema, words
from .boards import held_decided, read_counts, statuses
from .engine import Context, by_id, fail, questions
from .questions import apply_updates, board_keys, refuse_all
from .render import question_parts
from .told import report_hint


# Record: the engine writes each record and runs board ruling record (which lints it).

def note_of(q: dict) -> bool:
    return isinstance(q.get('annotations'), dict) and bool(str(q['annotations'].get('notes') or '').strip())


def deferrals(ctx: Context) -> dict[str, dict]:
    """Every question Record defers (r9-q40), by id: those the person deferred with `protocol defer` (and the questions deferred
    with them), the held ones still waiting on an outside result (r8-q31), and the held ones whose `waitsOn` reaches one of
    these (r11-q42). Each holds `reason`, `until` (a date bd reads, or None), `kind` (person, outside, chain) and for a question
    deferred with another `with`."""
    held = {q['id']: q for q in questions(ctx, 'held') if not q.get('recorded')}
    found = {q['id']: {'reason': q['deferral']['reason'], 'until': q['deferral']['until'], 'kind': 'person', 'with': q['deferral'].get('with')}
             for q in questions(ctx, 'deferred') if not q.get('recorded')}
    found.update({qid: {'reason': q['waitsFor'], 'until': None, 'kind': 'outside'} for qid, q in held.items() if q.get('waitsFor')})
    grew = True
    while grew:
        grew = False
        for qid, q in held.items():
            premise = next((other for other in q.get('waitsOn') or [] if other in found), None)
            if qid not in found and premise:
                found[qid] = {'reason': words.waits_on_deferred(premise, found[premise]['reason'], found[premise]['kind']),
                              'until': found[premise]['until'], 'kind': 'chain'}
                grew = True
    return found


def record_target(q: dict) -> str | None:
    """The existing item a question records onto: its `board`, its own or the hit it took over at Related."""
    return q['board']


def section(text: str, name: str) -> str:
    match = re.search(rf'^## {re.escape(name)}\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    return match.group(1).strip() if match else ''


def prior_record(ctx: Context, q: dict) -> str | None:
    """The decision record already on the question's item, read once and kept on the question so a rerun after a partial
    write still sees the record from before (agents r11-q42: Record revises it in place, it does not replace it)."""
    if 'priorRecord' not in q:
        item = record_target(q)
        text = None
        if ctx.board and item:
            try:
                row = ctx.board.json('show', item, '--json', '--field', 'description').get(item) or {}
            except ProtocolError:
                row = {}
            text = str(row.get('description') or '')
            text = text if section(text, 'Decision') and section(text, 'Question') else None
        q['priorRecord'] = text
    return q['priorRecord']


def record_text(ctx: Context) -> str:
    todo = [q for q in questions(ctx, 'answered') if not q.get('recorded')]
    rows = [words.record_row(q, q['annotations']['notes'].strip() if note_of(q) else None, prior_record(ctx, q)) for q in todo]
    return lines(
        words.record_intro(ctx.round['id']),
        *rows,
        *(words.record_deferred(qid, found) for qid, found in deferrals(ctx).items()),
        *([words.record_landed(outside)] if (outside := [qid for qid, found in deferrals(ctx).items() if found['kind'] == 'outside']) else []),
        words.RECORD_GIVE,
        report_hint(ctx, 'record', words.record_example(todo[:1])),
    )


def write_record(q: dict, path: Path, text: str) -> None:
    """A record file is created, never overwritten; only the rerun of a Record that wrote this question's file already rewrites it.
    A file holding the very text is done: a crash between the write and the state save left it, and the rerun goes on."""
    if q.get('recordFile') == str(path):
        path.write_text(text, encoding='utf-8')
        return
    try:
        with open(path, 'x', encoding='utf-8') as out:
            out.write(text)
    except FileExistsError:
        if path.read_text(encoding='utf-8', errors='replace') != text:
            fail(f'{path} exists: a record file is never overwritten')


def record_file(q: dict, fields: dict, topic: str | None = None) -> str:
    chosen = q['answer'] or ''
    # AskUserQuestion answers carry the chosen labels (comma-joined for multiSelect) or the user's own words.
    picked = {part.strip() for part in chosen.split(',')}
    prior = q.get('priorRecord')  # revised in place: the record keeps the question it decided and its alternatives
    alternatives = fields.get('alternatives') or (section(prior, 'Alternatives Considered') if prior else '') or '\n'.join(
        f"- {o['label']}: {o['description']}".rstrip(': ') for o in q['options'] if o['label'] not in picked)
    dropped = [f"- Dropped: {x['idea']} - {x['why']}" for x in q.get('dropped', [])]
    alternatives = '\n'.join([alternatives, *(line for line in dropped if line not in alternatives.splitlines())]).strip()
    question = section(prior, 'Question') if prior else q['text']
    source = {'dialog': 'User (dialog)', 'chat': 'User (chat)', 'model-reported': 'User (model-reported)',
              AWAY: 'Away round (autopilot took the recommendation; no person answered)',
              'session': "Session's disclosed ruling (the point is entailed; no person answered)"}[q['origin']]
    quoted = f"{source}, {q.get('answeredAt', utcnow())[:10]}: \"{q.get('quote') or chosen}\""
    if q.get('strength') == 'strong' and isinstance(q.get('strongBecause'), dict):
        quoted = 'Recommended (strong): ' + '; '.join(f'{k} {v}' for k, v in q['strongBecause'].items()) + '\n\n' + quoted
    if q.get('retired'):
        covers = f" Covers {', '.join(q['retired']['covers'])}." if q['retired']['covers'] else ''
        quoted += f"\n\nRetired as entailed: {q['retired']['reason']}.{covers}"
    if q.get('skipped'):
        quoted += f"\n\nChecks skipped: {q['skipped']}."
    return ((f"Topic: {' '.join(topic.split())}\n\n" if topic else '') + f"## Question\n{question}\n\n## Alternatives Considered\n{alternatives or '- none offered'}\n\n"
            f"## Decision\n{fields.get('decision') or chosen}\n\n## Rationale\n{fields['rationale'].strip()}\n\n{quoted}\n\n"
            + (f"## Premises\n{q['premises'].strip()}\n\n" if (q.get('premises') or '').strip() else '')
            + (f"## Root\n{q['root'].strip()}\n\n" if (q.get('root') or '').strip() else '')
            + ('## Own rulings\n' + '\n'.join(f'- {words.ruling_line(x)}' for x in q['rulings'])
               + ('\n\n' + words.RULINGS_CHANGED if q.get('rulingsChanged') else '') + '\n\n' if q.get('rulings') else '')
            + ('## Earlier rulings\n' + '\n'.join(f"- {x['ruling'].strip()}: {x['verdict']}. {x['why'].strip()}" for x in q['priorRulings']) + '\n\n' if q.get('priorRulings') else '')
            + f"## Rule owner\n{fields['ruleOwner'].strip()}\n"
            + (f"\n## Reversal\n{fields['reversal'].strip()}\n" if q['origin'] == AWAY else '')
            + (f"Reopen the questions it closed: `agents board reopen {' '.join(board_keys(q.get('settles')))}`.\n"
               if q['origin'] == AWAY and board_keys(q.get('settles')) else ''))


def mark_changed_rulings(ctx: Context, q: dict, record: str) -> None:
    """The record whose own rulings changed after the user's answer (r7-q27): the release asks the person about it."""
    if q.get('rulingsChanged'):
        ctx.state.setdefault('rulingChanges', {})[record] = q['id']


def record_tag(ctx: Context, q: dict) -> str:
    return f"protocol:{ctx.store.session}:{ctx.round['id']}:{q['id']}"


def tagged_item(ctx: Context, tag: str) -> str | None:
    """The oldest item carrying `tag`: bd does not keep an external ref unique, and a Record cut after a create
    wrote its item lost the id, so the rerun looks it up before it creates."""
    rows = ctx.board.json('bd', 'list', '--external-ref', tag, '--all', '--brief', '--json')
    return min(rows, key=lambda row: (row.get('created_at') or '', row['id']))['id'] if rows else None


def record_board_command(ctx: Context, q: dict, path: Path, body: str | None = None, plain: bool = False,
                        dry_run: bool = False) -> list[str]:
    """Build the board command that creates or revises this question's decision record."""
    packet = path.with_suffix('.packet.md')
    packet.write_text(body or f"## Question\n{q['text']}\n\nOptions: " + '; '.join(o['label'] for o in q['options'])
                      + f"\n\nStaged in round {ctx.round['id']}.\n", encoding='utf-8')
    tag = record_tag(ctx, q)
    holds = ','.join(q.get('holds') or []) or 'none'
    revised = None if plain else q.get('revises') or next(iter(q.get('replaces') or []), None)
    suffix = ['--dry-run'] if dry_run else []
    if revised:
        return ['ruling', 'revise', revised, '--title', q['title'], '--body-file', str(packet), '--external-ref', tag,
                '--holds', holds, *suffix]
    plan = packet.with_suffix('.plan.json')
    plan.write_text(json.dumps({'nodes': [{'key': 'question', 'title': q['title'], 'type': 'decision', 'external_ref': tag,
                                           'description': packet.read_text(encoding='utf-8')}]}), encoding='utf-8')
    return ['create', '--graph', str(plan), '--holds', holds, *suffix]


def board_item(ctx: Context, q: dict, path: Path, body: str | None = None, plain: bool = False) -> str:
    """The board id the record goes to: the question's item, else the draft created (or opened as a revision); `body`: the
    new item's text (a parked question's parts), else the question and its options; `plain`: a new decision item, never a revision
    of a record (a deferred question closes nothing and takes over only an open item)."""
    item = q['board']
    if item and plain and taken_over(q):  # a deferral never moves a decided, released or closed record: only an open item is taken over
        status = (ctx.board.json('show', item, '--json', '--field', 'status').get(item) or {}).get('status')
        item = item if status == 'open' else None
    if item:
        return item
    tag = record_tag(ctx, q)
    if found := tagged_item(ctx, tag):
        q['board'] = found
        # A rerun after a create whose wait edges did not all land: board wait is idempotent, an item closed meanwhile needs none.
        held = [item for item, status in statuses(ctx, list(q.get('holds') or [])).items() if status != 'closed'] if q.get('holds') else []
        if held:
            ctx.board.checked('wait', *held, '--on', found, '--for', f'{found} holds it up until answered or its ruling is planned.')
        return found
    # The released record it revises, else the first record it replaces: the new question is linked to it (its topic labels
    # come from it; a decision has no parent); `ruling record --replaces` links the other records it replaces.
    revised = None if plain else q.get('revises') or next(iter(q.get('replaces') or []), None)
    output = ctx.board.checked(*record_board_command(ctx, q, path, body, plain))
    new = output.strip() if revised else tagged_item(ctx, tag)  # the create output is not parsed, so find its id by tag
    if not new:
        fail(f"{q['id']}: the board returned no id for the new question")
    q['board'] = new
    return new


def settled_blockers(ctx: Context, q: dict) -> list[str]:
    """The premises a rule question's record inherits from the items it settles: what those items wait on (a released ruling holds what it
    changes until planned, so closing the settled items must not drop their premises). `ruling record --waits-on` writes them; what waits on a
    settled question the board hands to the record when it closes it (`--answers`, or the release's `--closes`)."""
    settled = board_keys(q.get('settles'))
    if not settled:
        return []
    rows = ctx.board.json('show', *settled, '--json', '--field', 'dependencies')
    return sorted({dep['depends_on_id'] for row in rows.values() for dep in (row or {}).get('dependencies') or []
                   if dep.get('type') == 'blocks' and dep.get('issue_id') in settled and dep['depends_on_id'] not in settled
                   and dep['depends_on_id'] != q['board'] and not dep['depends_on_id'].startswith('external:')})


def premise_first(ctx: Context, todo: list[dict]) -> tuple[list[dict], dict[str, list[str]], dict[str, set[str]]]:
    """Record's order (nixes-9cbib): an answer comes after the questions of this Record its premises name, in-round (`waitsOn`) or, for an
    away answer, inherited (a blocker of an item it settles that is another question's item or settled item), so a premise is recorded
    before the record that rests on it; otherwise the listed order. Returns the order, each away answer's inherited premises and each
    question's premises among this Record's questions."""
    inherited = {q['id']: settled_blockers(ctx, q) for q in todo if q['origin'] == AWAY} if ctx.board else {}
    ids = {q['id'] for q in todo}

    def premises(q: dict) -> set[str]:
        board = set(inherited.get(q['id'], []))
        return {p['id'] for p in todo if p is not q and (p['id'] in (q.get('waitsOn') or []) or
                                                          (board and (p['board'] in board or board & set(board_keys(p.get('settles'))))))} & ids

    rests = {q['id']: premises(q) for q in todo}
    order, left = [], list(todo)
    while left:
        ready = next((q for q in left if not rests[q['id']] - {o['id'] for o in order}), left[0])  # a circle keeps the listed order
        order.append(ready)
        left.remove(ready)
    return order, inherited, rests


def open_premises(ctx: Context, q: dict, inherited: list[str]) -> list[str]:
    """The premises of an answer open outside in force now (the release rule's open, status.release-holds): its inherited ones (an
    away answer's) and the items of the round's questions it `waitsOn`."""
    items = list(dict.fromkeys([*inherited, *(item for other in q.get('waitsOn') or [] if (item := by_id(ctx, other).get('board')))]))
    return [rid for rid, status in statuses(ctx, items).items() if status not in ('closed', 'in_force')] if items else []


def stands_complete(ctx: Context, item: str, waits_on: list[str], answers: list[str]) -> bool:
    """An away record's board call finished (ruling record unclaims last): in force or decided, free, its premises waited on, its answered questions closed."""
    row = ctx.board.json('show', item, '--json', '--field', 'status', '--field', 'assignee', '--field', 'dependencies').get(item) or {}
    waited = {dep['depends_on_id'] for dep in row.get('dependencies') or [] if dep.get('issue_id') == item and dep.get('type') == 'blocks'}
    return row.get('status') in ('in_force', 'decided') and not row.get('assignee') and set(waits_on) <= waited \
        and all(status == 'closed' for status in statuses(ctx, answers).values())


def link_record(ctx: Context, q: dict) -> None:
    """Relates the question's item to its `relate` hits; retried on a rerun until it succeeded once (a pair already linked is left). Free of
    the hold rule and holding nothing up, so it may follow the record. The replaced records are not here: `ruling record --replaces` links
    them; the premises and the answered questions' waits are `ruling record`'s too (nixes-ymay1)."""
    if not q.get('linked'):
        item = q['board']
        relate = [h['id'] for h in q['overlaps'] if h['outcome'] == 'relate']
        if relate:  # the links already there are read once, only when there is a link to make
            have = {frozenset((dep['issue_id'], dep['depends_on_id'])) for row in ctx.board.json('show', item, '--json', '--field', 'dependencies').values()
                    for dep in (row or {}).get('dependencies') or []}
            relate = [hit for hit in relate if frozenset((item, hit)) not in have]
        for hit in relate:
            ctx.board.checked('link', item, hit, '--type', 'relates-to')
    q['linked'] = True


def names_id(text: str, key: str) -> bool:
    return re.search(rf'(?<![\w.-]){re.escape(key)}(?![\w-]|\.\w)', text) is not None


def move_settled(ctx: Context, item: str, keys: list[str]) -> None:
    """The items a record settles, which stay claimed until a release closes them by that record."""
    settles = ctx.state.setdefault('settles', {})
    settles[item] = list(dict.fromkeys([*settles.get(item, []), *keys]))


def deferred_text(ctx: Context, q: dict, found: dict) -> str:
    """What a deferred question's new board item carries: the question with its parts, and why it was deferred."""
    parts = '\n\n'.join(words.part_block(name, text) for name, text in question_parts(ctx, q).items())
    return (f"## Question\n{q['text']}\n\n{parts}\n\nDeferred in round {ctx.round['id']}: {found['reason']}"
            + (f" (until {found['until']})" if found['until'] else '') + '\n')


def waiting_text(ctx: Context, q: dict, premises: list[str], proposed: str) -> str:
    """What an away answer resting on open premises leaves on its item: the question with its parts, what it waits on and the answer
    proposed, for the round that takes the question up once they settle (nixes-rzfij)."""
    parts = '\n\n'.join(words.part_block(name, text) for name, text in question_parts(ctx, q).items())
    return f"## Question\n{q['text']}\n\n{parts}\n\n{words.premise_wait(ctx.round['id'], premises)}\n\n{proposed}\n"


def file_premise_wait(ctx: Context, q: dict, premises: list[str], proposed: str, folder: Path) -> None:
    """An away answer on open premises stays an open question waiting on them (nixes-rzfij): its item (a decision created for a draft,
    never a revision) carries the proposed answer, in its text or, on an existing item, a comment, is unclaimed, and waits on each
    premise (`board wait`); the board brings it back when they close. A rerun repeats only what is left: the comment once, the waits
    as the board keeps them (board wait is idempotent)."""
    path = folder / f"{ctx.round['id']}-{q['id']}.md"
    text = waiting_text(ctx, q, premises, proposed)
    before = q['board']
    item = board_item(ctx, q, path, text, plain=True)
    done = q.setdefault('premiseWait', {'item': item, 'on': premises, 'commented': item != before})  # a new item carries the text already
    if not done['commented']:
        packet = path.with_suffix('.packet.md')
        packet.write_text(text, encoding='utf-8')
        ctx.board.checked('comment', item, '-f', str(packet), '--board-packet')  # the board's own packet: exempt from the comment limit
        done['commented'] = True
    claimed = ctx.round.get('claimed', [])
    if item in claimed:
        ctx.board.checked('unclaim', item)
        claimed.remove(item)
    for premise in done['on']:
        ctx.board.checked('wait', item, '--on', premise, '--for', words.PREMISE_FOR)
    q['recorded'] = 'waiting'
    ctx.log('waiting', question=q['id'], board=item, on=done['on'])


def file_deferral(ctx: Context, q: dict, found: dict, folder: Path) -> None:
    """The one writer of a deferral (r9-q40): on a board the question's item (a decision created for a draft) is unclaimed and
    `bd defer`red with the reason and `until`; without one (r9-q41) nothing is filed and the history and Closed text note it.
    A rerun after a failure repeats only what is left: the item is found by its tag, and `recorded` follows the defer."""
    if ctx.board:
        item = board_item(ctx, q, folder / f"{ctx.round['id']}-{q['id']}.md", deferred_text(ctx, q, found), plain=True)
        claimed = ctx.round.get('claimed', [])
        if item in claimed:
            ctx.board.checked('unclaim', item)
            claimed.remove(item)
        ctx.board.checked('defer', item, '--reason', found['reason'], *(['--until', found['until']] if found['until'] else []))
        q['deferralItem'] = item
    q['recorded'] = 'deferred'
    ctx.log('deferred', question=q['id'], reason=found['reason'], until=found['until'], board=q.get('deferralItem'))


def checkpoint(ctx: Context) -> None:
    """Saves the round and flushes the history after each question: a Record cut mid-way (the console's time limit) keeps
    the ids it created, and the rerun with the same report continues from there."""
    ctx.store.save(ctx.state)
    ctx.store.flush()


LANDED_FIELDS = ('id', 'waitsFor', 'premises')


def free_landed(ctx: Context, report: dict) -> str:
    """A result a held question waits for landed before Record (r7-q26): its `updates` entry clears `waitsFor` (and may set
    `premises`); the question takes the scoped check the freed ones take (r11-q42) and is asked in this round, so the report records
    nothing. A result that does not land is still deferred below (r8-q31, r23-q91)."""
    if 'records' in report:
        fail(words.RECORD_OR_UPDATES)
    schema.require(schema.Record, report, 'updates')
    waiting = {q['id'] for q in questions(ctx, 'held') if q.get('waitsFor') and not q.get('recorded')}
    errors = []
    for index, update in enumerate(report['updates']):
        where = f'updates[{index}]'
        if set(update) - set(LANDED_FIELDS):
            errors.append(f"{where} takes only `id`, `waitsFor` (null) and `premises`: the question is checked again after it")
        elif update.get('id') not in waiting:
            errors.append(f"{where}: {update.get('id')} is not waiting for an outside result")
        elif 'waitsFor' not in update or update['waitsFor'] is not None:
            errors.append(f'{where}: `waitsFor` must be null: the result landed (one that did not stays waiting and Record defers the question)')
    refuse_all(errors)
    apply_updates(ctx, report['updates'])
    ctx.log('freed', questions=list(dict.fromkeys(ctx.applied)))
    return 'ask'


def record_accept(ctx: Context, report: dict) -> str:
    if 'updates' in report:
        return free_landed(ctx, report)
    schema.require(schema.Record, report)
    records = report.get('records') or {}
    found = deferrals(ctx)
    waiting = [f"{q['id']} on {', '.join(q['waitsOn'])}" for q in questions(ctx, 'held')
               if q['id'] not in found and not q.get('recorded')]
    if waiting:  # waitsOn refuses a circle and an unknown id, and an answer releases its dependents: nothing should reach this
        fail(f"questions still wait at Record: {'; '.join(waiting)}. A question waits only within its round: `protocol abandon`")
    todo = [q for q in questions(ctx, 'answered') if not q.get('recorded')]
    done = {q['id'] for q in questions(ctx, 'answered') if q.get('recorded')}  # a rerun of the same report skips them
    for qid in records:
        if qid not in {q['id'] for q in todo} | done:
            fail(f'{qid}: not an answered question awaiting its record')
    missing = [q['id'] for q in todo if q['id'] not in records]
    if missing:
        fail(f"records missing for {', '.join(missing)}")
    for qid, fields in records.items():
        if not isinstance(fields, dict) or (bad := schema.problems(schema.RecordEntry, fields, 'rationale', 'ruleOwner')):
            fail(f"records.{qid}: {bad[0] if isinstance(fields, dict) else schema.text_of(schema.RecordEntry, 'rationale')}")
        if bad := schema.problems(schema.RecordEntry, fields, 'reversal', 'decision'):
            fail(f'records.{qid}: {bad[0]}')
        if by_id(ctx, qid)['origin'] == AWAY and not str(fields.get('reversal') or '').strip():
            fail(f'records.{qid}: an away answer needs a `reversal` (the steps that undo it, executable without remembered context)')
        if prior_record(ctx, by_id(ctx, qid)) and not str(fields.get('decision') or '').strip():
            fail(words.revise_needs_decision(qid, record_target(by_id(ctx, qid))))
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
                unnamed.append(f"records.{q['id']}: replaces {', '.join(unsaid)}: name each in the rationale or "
                               'decision with what the new record keeps or changes')
    if unnamed:
        fail('; '.join(unnamed))
    folder = Path(ctx.round['records']) if ctx.round.get('records') else ctx.store.dir / 'records'
    folder.mkdir(parents=True, exist_ok=True)
    errors, failed = [], set()
    todo, inherited, rests = premise_first(ctx, todo)
    for q in todo:
        if stuck := sorted(rests[q['id']] & failed):  # a premise of this Record not recorded: the rerun records them in order
            errors.append(words.premise_not_recorded(q['id'], stuck))
            failed.add(q['id'])
            continue
        unsettled = open_premises(ctx, q, inherited.get(q['id'], [])) if ctx.board else []
        if unsettled and q['origin'] == AWAY:
            try:
                file_premise_wait(ctx, q, unsettled, words.proposed_answer(q, records[q['id']]), folder)
            except ProtocolError as error:
                errors.append(f"{q['id']}: {error}")
                failed.add(q['id'])
            checkpoint(ctx)
            continue
        path = folder / f"{ctx.round['id']}-{q['id']}.md"
        write_record(q, path, record_file(q, records[q['id']], None if ctx.board else ctx.round.get('topic')))
        q['recordFile'] = str(path)
        if not ctx.board:
            q['recorded'] = 'file'
            mark_changed_rulings(ctx, q, path.stem)
            ctx.log('recorded', question=q['id'], board=None, file=str(path), ok=True)
            checkpoint(ctx)
            continue
        try:
            item = board_item(ctx, q, path)
            away = q['origin'] == AWAY
            # Every record it replaces is linked; an unratified record is released at once, so it supersedes them now, the released
            # one it revises included; any other record supersedes them at its release (r9-q33).
            replaces = list(dict.fromkeys([*(q.get('replaces') or []), *([q['revises']] if away and q.get('revises') else [])]))
            # One call writes the record, its premises (the settled items' blockers still open, and a person's open premises) and, for an away
            # ruling, the closes of the questions it settles, then releases the hold: no other session sees it before its waits stand (nixes-ymay1).
            inherited_open = [b for b, status in statuses(ctx, inherited.get(q['id']) or settled_blockers(ctx, q)).items() if status != 'closed'] \
                if board_keys(q.get('settles')) else []
            waits_on = list(dict.fromkeys([*inherited_open, *unsettled]))
            answers = board_keys(q.get('settles')) if away else []
            if not (away and stands_complete(ctx, item, waits_on, answers)):  # else a rerun after the board call: only the engine's own steps are left
                ctx.board.checked('claim', item)  # a rerun's own hold: board claim keeps it ("already held")
                ctx.board.checked('ruling', 'record', item, str(path), *(['--unratified'] if away else []),
                                  *(['--replaces', ','.join(replaces)] if replaces else []), *(['--waits-on', ','.join(waits_on)] if waits_on else []),
                                  *(['--answers', ','.join(answers)] if answers else []))
            link_record(ctx, q)
            if q['origin'] != AWAY and board_keys(q.get('settles')):
                move_settled(ctx, item, board_keys(q['settles']))  # the release closes them
            for old in replaces:  # the items the old record settles move to the new record, or they stay claimed with no release to close them
                move_settled(ctx, item, ctx.state.get('settles', {}).pop(old, []))
            q['recorded'] = item
            mark_changed_rulings(ctx, q, item)
            if q.get('retired'):  # the release lists it with the own rulings, sure (r3-q18)
                ctx.state.setdefault('sessionRulings', {})[item] = {'record': item, **q['rulings'][0], 'sure': True}
            (ctx.state.get('dropReasons') or {}).pop(item, None)  # a re-recorded record is back in the default set
        except ProtocolError as error:
            errors.append(f"{q['id']}: {error}")
            failed.add(q['id'])
        ctx.log('recorded', question=q['id'], board=q['board'], file=str(path), ok=bool(q.get('recorded')))
        superseded = (q.get('replaces') or []) + ([q['revises']] if q.get('revises') else []) if q['origin'] == AWAY else []
        for old in [one for one in superseded if q.get('recorded') and one not in q.setdefault('reported', [])]:  # after the record's own line
            q['reported'].append(old)
            ctx.log('superseded', question=q['id'], old=old, new=q['board'], partial=None)
        checkpoint(ctx)
    for q in ctx.round['questions']:  # in listed order; a failure leaves the rest to the rerun
        if q['id'] in found and not q.get('recorded'):
            try:
                file_deferral(ctx, q, found[q['id']], folder)
            except ProtocolError as error:
                errors.append(f"{q['id']}: {error}")
            checkpoint(ctx)
    if errors:
        ctx.messages.append(words.not_recorded(errors))
        return 'record'
    return 'closed'


def abandon_note(round_questions: list[dict]) -> str:
    """What an abandoned round leaves behind: records written before the abandon stay decided (r24-q108)."""
    kept = [q.get('board') or q['id'] for q in round_questions if q.get('recorded') not in (None, 'deferred', 'waiting')]
    return words.abandoned_records(kept)


def release_claims(ctx: Context) -> None:
    """A hold ends with its work: the round releases what it claimed and did not record (deferred, waiting on a premise, held for the next
    round's Select, removed, or the round abandoned). Best effort: the round closes either way."""
    done = [q for q in ctx.round['questions'] if q.get('recorded') not in (None, 'deferred', 'waiting', 'file')]
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
        counts, held = read_counts(found), held_decided(ctx.board, found)
    except ProtocolError as error:
        ctx.messages.append(words.counts_unavailable(error))
        return False
    ctx.state['counts'] = counts
    dropped = ctx.state.get('dropReasons') or {}
    ctx.state['releasable'] = sum(1 for rid in held if rid not in dropped)
    return True


def closed_enter(ctx: Context) -> None:
    r = ctx.round
    r['pending'], r['batch'] = None, None
    release_claims(ctx)
    if ctx.board and refresh_board(ctx):
        r['countsAt'] = utcnow()
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
