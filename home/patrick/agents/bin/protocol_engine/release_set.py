"""Release: the record set, starting a release and the Re-check step."""
from __future__ import annotations

import re
from pathlib import Path

from .base import lines, utcnow
from . import words
from .store import next_id
from .boards import held_decided
from .engine import Context, fail
from .told import forget_runs, report_hint
from .away import SWITCH_TO_SOLO


# Release: decide.md Release run like a round (r3-q7): the engine sequences the steps, takes approval only from a
# person origin, checks the owners, and runs board release, supersede and the answered closes. The reports carry
# the judgment. The run uses the round slot (state['round']) with the next run id (r4-q17).

HIT_CLASSES = {
    'revises': 'earlier ruling it revises or contradicts, closed included (supersede it)',
    'answers': 'open question it duplicates or answers (merge, or the engine closes it)',
    'premise': 'open question its own premise rests on (the record leaves the set)',
    'assumes': 'open item assuming the old state (board block <item> --on <record> --reason "<revised clause>")',
    'deferred': 'deferred item assuming the old state, or one it unblocks (relate it; comment the revised clause)',
    'held': 'item another session holds on the same concepts (comment or hand off)',
    'doc': "doc stating the old rule (a design-target doc: owner write now; a README or skill: owner write, or a task when it changes with the work)",
}
REACHES = ('contained', 'spreads')  # no "unsure": unsure is spreads (r4-q14, fails closed)


TOUCHES = ('own', 'decision')  # a contained change: only the model's own parts keeps the record; unsure is decision (r8-q36)
APPROVE, HOLD = 'Release', 'Hold'
SCOPED_PASSES = ('step-back', 'ground')  # once per release on the revised records, before the approval (r8-q36)


def in_set(ctx: Context) -> list[str]:
    """The records the release carries: in the set, or revised (kept with a corrected record text)."""
    return [rec['id'] for rec in ctx.round['set'] if rec['state'] in ('set', 'revised')]


def revised(ctx: Context) -> list[str]:
    return [rec['id'] for rec in ctx.round['set'] if rec['state'] == 'revised']


def scoped_records(ctx: Context) -> list[str]:
    """The revised records whose Decision text changed: only these get the scoped passes (r24-q102)."""
    return [rec['id'] for rec in ctx.round['set'] if rec['state'] == 'revised' and rec.get('decisionChanged', True)]


def decision_text(text: str) -> str | None:
    found = re.search(r'^## Decision[ \t]*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    return ' '.join(found.group(1).split()) if found else None


def decision_changed(ctx: Context, rid: str, path: str) -> bool:
    """Whether a corrected record's Decision differs from the board's; anything unreadable counts as changed."""
    raw = ctx.board.json('show', rid, '--json', '--field', 'description')
    before = decision_text((raw.get(rid) or {}).get('description') or '')
    try:
        after = decision_text((Path(ctx.board.repo or '.') / path).read_text(encoding='utf-8'))
    except OSError:
        return True
    return before is None or after != before


def set_record(ctx: Context, rid: str) -> dict:
    return next((rec for rec in ctx.round['set'] if rec['id'] == rid), None) or fail(f'{rid} is not in this release')


def release_label(ctx: Context) -> str:
    """`the session's records`, or the named ids: the run's title in the pane and the headline."""
    return words.release_label(bool(ctx.round.get('source')), [rec['id'] for rec in ctx.round['set']])


def default_set(ctx: Context) -> list[str]:
    """What a bare release takes (r13 q50): the decided records this session holds, read from the board now, minus the ones
    a release dropped or stopped (`dropReasons`, cleared by a re-recording or a release)."""
    held = held_decided(ctx.board)
    dropped = ctx.state.get('dropReasons') or {}
    ids = [rid for rid in held if rid not in dropped]
    if not ids:
        fail('no default set: ' + (f"every decided record this session holds ({', '.join(held)}) was dropped or stopped by a "
                                   'release: it goes to a round first' if held else 'this session holds no decided records')
             + '; name the ids: `protocol start release <id> …`')
    return ids


def start_release(ctx: Context, ids: list[str]) -> None:
    """The set (r4-q12, r13 q50): the named ids, else the decided records this session holds, minus the dropped. Ids
    another live session holds are refused; a gone session's hold is taken, unheld records are claimed."""
    if ctx.away:
        fail(f'only the person approves a release: {SWITCH_TO_SOLO}')
    if ctx.board is None:
        fail('a release needs a board: run it in the repository whose board holds the records; '
             'a --no-board round closes at Record')
    source = None
    if not ids:
        source, ids = 'the session', default_set(ctx)
    ids = list(dict.fromkeys(ids))
    found = ctx.board.json('show', *ids, '--json', '--field', 'status', '--field', 'issue_type', '--field', 'title',
                           '--field', 'assignee')
    rows = {rid: found.get(rid) or {} for rid in ids}
    undecided = [rid for rid in ids if rows[rid].get('issue_type') != 'decision' or rows[rid].get('status') != 'decided']
    if undecided:
        fail('not decided records: ' + ', '.join(f"{rid} ({rows[rid].get('status')} {rows[rid].get('issue_type')})"
                                                  for rid in undecided))
    me = ctx.board.actor.split('/', 1)[0]
    foreign = [rid for rid in ids if rows[rid].get('assignee') and rows[rid]['assignee'].split('/', 1)[0] != me]
    gone = []
    if foreign:
        marks = {h['id']: h.get('mark') for h in ctx.board.json('position', '--json').get('held') or []}
        live = [rid for rid in foreign if marks.get(rid) != 'gone']
        if live:
            fail('held by another live session: ' + ', '.join(f"{rid} ({rows[rid]['assignee']})" for rid in live)
                 + '; ask it to hand them off, or name other ids')
        gone = foreign
    claim = [rid for rid in ids if rid not in gone and rows[rid].get('assignee') != ctx.board.actor]
    if gone:
        ctx.board.checked('take', *gone)
    if claim:
        ctx.board.checked('claim', *claim)
    forget_runs(ctx)
    ctx.state['round'] = {
        'id': next_id(ctx.state, 'round', 'r'), 'protocol': 'release', 'step': 'recheck', 'startedAt': utcnow(),
        'repo': ctx.board.repo, 'scope': 'release', 'source': source, 'title': None, 'summary': None,
        # the round keys the shared views and the ask machinery read
        'records': None, 'items': [], 'points': [], 'classes': {}, 'selected': [], 'questions': [], 'check': {},
        'pending': None, 'observed': {}, 'batch': None, 'batchSeq': 0, 'responses': [], 'messages': [],
        'set': [{'id': rid, 'title': rows[rid].get('title') or '', 'state': 'set', 'reason': None} for rid in ids],
        'checks': {}, 'supersedes': [], 'closes': {}, 'rulings': None, 'conditional': None, 'approval': None,
        'owners': {}, 'done': [], 'retry': False, 'stopped': None, 'outcome': None, 'scoped': {'done': []},
    }
    ctx.round['title'] = release_label(ctx)
    ctx.log('start', protocol='release', repo=ctx.board.repo, records=ids, taken=gone, source=source)
    ctx.go('recheck')


def set_rows(ctx: Context) -> list[str]:
    return [words.set_row(rec) for rec in ctx.round['set'] if rec['state'] in ('set', 'revised')]


def drop(ctx: Context, rid: str, reason: str) -> None:
    """A record leaves the set (a contained change, or a premise still open); it stays decided and held for a round.
    The set changed: a conditional approval lapses (r4-q16)."""
    r = ctx.round
    rec = set_record(ctx, rid)
    rec.update(state='dropped', reason=reason)
    r['conditional'] = None
    r['supersedes'] = [sup for sup in r['supersedes'] if sup['new'] != rid]
    r['closes'] = {q: [x for x in recs if x != rid] for q, recs in r['closes'].items() if [x for x in recs if x != rid]}
    ctx.log('record-dropped', record=rid, reason=reason)


def revise(ctx: Context, rid: str, change: str, changed_decision: bool = True) -> None:
    """A contained change of the model's own parts: the record stays in the release, its corrected text written. The
    approval no longer rests on what the person saw: a conditional approval lapses (r8-q36)."""
    rec = set_record(ctx, rid)
    rec.update(state='revised', reason=words.revise_reason(change), change=change,
               decisionChanged=rec.get('decisionChanged', False) or changed_decision)
    ctx.round['conditional'] = None
    ctx.log('record-revised', record=rid, reason=change)


def stop(ctx: Context, reason: str, ids: list[str], hold: bool = False) -> str:
    """Nothing releases; the records stay decided and held; the close names the round they go to (r4-q14). A person's Hold
    (r14 q52) goes to a round on what it was held for, so it drops nothing and a later bare release takes the rest."""
    r = ctx.round
    for rid in ids:
        set_record(ctx, rid)['state'] = 'changed'
    r['conditional'] = None
    r['stopped'] = {'reason': reason, 'hold': hold,
                    'ids': [rec['id'] for rec in r['set'] if rec['state'] in ('set', 'revised', 'changed', 'dropped')]}
    ctx.log('release-stopped', reason=reason, records=ids)
    return 'closed'


def apply_changes(ctx: Context, raw, where: str, every: bool, scope: list[str] | None = None) -> str | None:
    """Per record `unchanged`, or {change, reach, why, touches, file?}: contained (with `why` no other ruling moves)
    either keeps the record revised (touches own: the model's own rationale, evidence or clause; `file` is the corrected
    record text, which `board record` writes) or drops it (touches decision); spreads stops the run. Returns 'closed'
    when the run stops."""
    if not isinstance(raw, dict):
        fail(f'{where}: map each record id to "unchanged" or {{"change", "reach", "why", "touches"}}')
    current = in_set(ctx) if scope is None else scope  # a scoped pass maps the revised records only
    unknown = [rid for rid in raw if rid not in current]
    missing = [rid for rid in current if rid not in raw] if every else []
    if unknown or missing:
        fail(f"{where}: " + '; '.join(part for part in (
            f"not in the {'set' if scope is None else 'revised records'}: {', '.join(unknown)}" if unknown else '',
            f"no line for {', '.join(missing)}" if missing else '') if part))
    spreads, contained = [], []
    for rid, value in raw.items():
        if value == 'unchanged':
            continue
        if not isinstance(value, dict) or not str(value.get('change') or '').strip():
            fail(f'{where}.{rid}: "unchanged", or {{"change": "<what changed>", "reach": "contained" or "spreads"}}')
        if value.get('reach') not in REACHES:
            fail(f'{where}.{rid}: reach is contained or spreads; unsure is spreads')
        if value['reach'] == 'contained':
            if not str(value.get('why') or '').strip():
                fail(f'{where}.{rid}: a contained change names `why` no other ruling of the set or the board moves; '
                     'otherwise it spreads')
            if value.get('touches') not in TOUCHES:
                fail(f'{where}.{rid}: a contained change says what it touches: touches is "own" (only your own rationale, '
                     'evidence or a clause the chosen option did not state; the record stays, corrected) or "decision" '
                     '(what the user decided; the record leaves the set); unsure is decision')
            if value['touches'] == 'own' and not (isinstance(value.get('file'), str) and value['file'].strip()):
                fail(f'{where}.{rid}: an own change gives `file`, the path of the corrected record text')
        (spreads if value['reach'] == 'spreads' else contained).append((rid, value))
    if spreads:
        return stop(ctx, words.spreads_reason(spreads), [rid for rid, _ in spreads])
    # The board writes come first and all-or-nothing for the state: a failure refuses the report, so it is sent again
    # (board record rewrites the same text).
    decisions = {rid: decision_changed(ctx, rid, value['file'].strip()) for rid, value in contained if value['touches'] == 'own'}
    for rid, value in contained:
        if value['touches'] == 'own':
            result = ctx.board.run('record', rid, value['file'].strip())
            if result.returncode != 0:
                fail(f"{where}.{rid}: `board record {rid} {value['file']}` exited {result.returncode}: "
                     + (result.stderr.strip() or result.stdout.strip()) + '; fix the file and report again')
    for rid, value in contained:
        if value['touches'] == 'own':
            revise(ctx, rid, value['change'], decisions[rid])
        else:
            drop(ctx, rid, words.drop_changed(value['change']))
    if not in_set(ctx):
        return stop(ctx, words.EMPTY_SET, [])
    return None


def recheck_text(ctx: Context) -> str:
    return lines(
        words.recheck_intro(ctx.round['id'], release_label(ctx)),
        *([words.BARE_RELEASE] if ctx.round.get('source') else []),
        *set_rows(ctx),
        report_hint(ctx, 'recheck', words.recheck_example(in_set(ctx)[:1])),
    )


def recheck_accept(ctx: Context, report: dict) -> str:
    raw = report.get('records')
    changed = [rid for rid, value in raw.items() if value != 'unchanged'] if isinstance(raw, dict) else []
    ctx.log('rechecked', unchanged=len(raw or {}) - len(changed), changed=changed)  # queued: a refusal drops it
    return apply_changes(ctx, raw, 'records', every=True) or 'board-check'
