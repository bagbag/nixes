"""The round's Record and Closed steps and the board writes behind them."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .base import AWAY, ProtocolError, lines, utcnow
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
    """The existing item a question records onto: its own, else the hit Record takes over (board_item)."""
    return q['board'] or next((h['id'] for h in q.get('overlaps') or [] if h['outcome'] in ('duplicate', 'extend')), None)


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


TOPIC_LINE = re.compile(r'\ATopic: (.*)\n')


def record_topic(path: Path) -> str | None:
    """The topic a record file's header names; a file of an old topic folder has the folder's name."""
    head = path.read_text(encoding='utf-8')[:2000]
    return found[1] if (found := TOPIC_LINE.match(head)) else None


def topic_records(folder: Path, topic: str) -> list[Path]:
    """The record files of `topic` in the records folder, archive subfolders included (read-only: each names its topic by its folder)."""
    wanted = ' '.join(topic.split())
    files = sorted(path for path in folder.rglob('*.md') if path.is_file()) if folder.is_dir() else []
    return [path for path in files if (path.relative_to(folder).parts[0] if path.parent != folder else record_topic(path)) == wanted]


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
            + (f"Reopen the questions it closed: `board reopen {' '.join(board_keys(q.get('settles')))}`.\n"
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


def board_item(ctx: Context, q: dict, path: Path, body: str | None = None, plain: bool = False) -> str:
    """The board id the record goes to: the question's item, else the draft created (or opened as a revision); `body`: the
    new item's text (a parked question's parts), else the question and its options; `plain`: a new decision item, never a revision
    of a record (a deferred question closes nothing and takes over only an open item)."""
    if q['board']:
        return q['board']
    takeover = next((h['id'] for h in q['overlaps'] if h['outcome'] in ('duplicate', 'extend')), None)
    if takeover and plain:  # a deferral never moves a decided, released or closed record: only an open item is taken over
        status = (ctx.board.json('show', takeover, '--json', '--field', 'status').get(takeover) or {}).get('status')
        takeover = takeover if status in ('open', 'in_progress') else None
    if takeover:
        q['board'] = takeover
        return takeover
    tag = record_tag(ctx, q)
    if found := tagged_item(ctx, tag):
        q['board'] = found
        # A rerun after a create whose block edges did not all land: board block is idempotent, an item closed meanwhile needs none.
        held = [item for item, status in statuses(ctx, list(q.get('holds') or [])).items() if status != 'closed'] if q.get('holds') else []
        if held:
            ctx.board.checked('block', *held, '--on', found, '--reason', f'{found} holds it up until answered or its ruling is planned.')
        return found
    packet = path.with_suffix('.packet.md')
    packet.write_text(body or f"## Question\n{q['text']}\n\nOptions: " + '; '.join(o['label'] for o in q['options'])
                      + f"\n\nStaged in round {ctx.round['id']}.\n", encoding='utf-8')
    # The released record it revises, else the first record it closes: the new question is linked to it (parent and topic
    # labels come from it) until `ruling record --replaces` closes it, which links and closes the other records it replaces.
    holds = ','.join(q.get('holds') or []) or 'none'
    revised = None if plain else q.get('revises') or next(iter(q.get('replaces') or []), None)
    if revised:
        new = ctx.board.checked('ruling', 'revise', revised, '--title', q['title'], '--body-file', str(packet), '--external-ref', tag, '--holds', holds).strip()
    else:
        plan = packet.with_suffix('.plan.json')
        plan.write_text(json.dumps({'nodes': [{'key': 'question', 'title': q['title'], 'type': 'decision', 'external_ref': tag,
                                               'description': packet.read_text(encoding='utf-8')}]}), encoding='utf-8')
        ctx.board.checked('create', '--graph', str(plan), '--holds', holds)
        new = tagged_item(ctx, tag)  # by the tag, as a rerun after a cut create finds it: the create's output is not parsed
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
    """Relates the question's item to its `relate` hits and gives it the inherited blocks; retried on a rerun until it succeeded once
    (a pair already linked is left). bd keeps one edge per pair: a blocks link wins over a relate. The replaced records are not here:
    `ruling record --replaces` links and closes them."""
    if not q.get('linked'):
        item = q['board']
        blocks = inherited_blocks(ctx, q)
        taken = {frozenset(op.split()[2:4]) for op in blocks}
        relate = [h['id'] for h in q['overlaps'] if h['outcome'] == 'relate' and frozenset((item, h['id'])) not in taken]
        if relate:  # the links already there are read once, only when there is a link to make
            have = {frozenset((dep['issue_id'], dep['depends_on_id'])) for row in ctx.board.json('show', item, '--json', '--field', 'dependencies').values()
                    for dep in (row or {}).get('dependencies') or []}
            relate = [hit for hit in relate if frozenset((item, hit)) not in have]
        for hit in relate:
            ctx.board.checked('link', item, hit, '--type', 'relates-to')
        for op in blocks:  # `dep add <waiting> <blocker> blocks`: the hold board block makes
            _, _, waiting, blocker, _ = op.split()
            reason = [] if blocker == item else ['--reason', f'{item} waits on {blocker} as the items it settles did.']
            ctx.board.checked('block', waiting, '--on', blocker, *reason)
    q['linked'] = True


def names_id(text: str, key: str) -> bool:
    return re.search(rf'(?<![\w.-]){re.escape(key)}(?![\w-]|\.\w)', text) is not None


def close_settled_away(ctx: Context, q: dict, item: str) -> None:
    """An away ruling is in force, so the questions it settles close when it is recorded; no release follows, and its reversal
    reopens them (r31-q143). Repeatable: a rerun closes what is left."""
    done = q.setdefault('closedSettled', [])
    for key in board_keys(q.get('settles')):
        if key not in done:
            ctx.board.checked('close', key, '--reason', f'Settled by away ruling {item}, awaiting ratification')
            done.append(key)


def move_settled(ctx: Context, item: str, keys: list[str]) -> None:
    """The items a record settles, which stay claimed until a release closes them by that record."""
    settles = ctx.state.setdefault('settles', {})
    settles[item] = list(dict.fromkeys([*settles.get(item, []), *keys]))


def deferred_text(ctx: Context, q: dict, found: dict) -> str:
    """What a deferred question's new board item carries: the question with its parts, and why it was deferred."""
    parts = '\n\n'.join(words.part_block(name, text) for name, text in question_parts(ctx, q).items())
    return (f"## Question\n{q['text']}\n\n{parts}\n\nDeferred in round {ctx.round['id']}: {found['reason']}"
            + (f" (until {found['until']})" if found['until'] else '') + '\n')


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
                unnamed.append(f"records.{q['id']}: recording closes {', '.join(unsaid)}; name each in the rationale or "
                               'decision with what the new record keeps or changes')
    if unnamed:
        fail('; '.join(unnamed))
    folder = Path(ctx.round['records']) if ctx.round.get('records') else ctx.store.dir / 'records'
    folder.mkdir(parents=True, exist_ok=True)
    errors = []
    for q in todo:
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
            link_record(ctx, q)
            ctx.board.checked('claim', item)
            replaces = q.get('replaces') or []
            result = ctx.board.run('ruling', 'record', item, str(path), *(['--status', 'needs_ratification'] if q['origin'] == AWAY else []),
                                   *(['--replaces', ','.join(replaces)] if replaces else []))
            if result.returncode != 0:
                left = [old for old, status in statuses(ctx, replaces).items() if status != 'closed']
                if left or not replaces:  # the record or a close did not happen: the rerun picks up what is left
                    fail(f"`board ruling record {item}` exited {result.returncode}: {(result.stderr or result.stdout).strip()}")
                ctx.messages.append(words.record_exited(item, result.returncode, (result.stderr or result.stdout).strip()))  # all closed: only the items waiting on the old ones are not blocked
            if q['origin'] == AWAY:
                close_settled_away(ctx, q, item)
            elif board_keys(q.get('settles')):
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
        ctx.log('recorded', question=q['id'], board=q['board'], file=str(path), ok=bool(q.get('recorded')))
        for old in [one for one in (q.get('replaces') or []) if q.get('recorded') and one not in q.setdefault('reported', [])]:  # after the record's own line
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
