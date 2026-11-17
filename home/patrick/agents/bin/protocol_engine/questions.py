"""Validation of question content and the model's question updates."""
from __future__ import annotations

import re

from .base import (
    DESCRIPTION_LIMIT, DESCRIPTION_MAX, HEADER_MAX, KINDS, MAY_NOT_APPLY, ProtocolError, STAGED_KINDS, STRENGTHS,
    STRONG_CRITERIA, SUMMARY_MAX, TEXT_LIMIT, TEXT_MAX, TITLE_LIMIT, TITLE_MAX, band_warning, taken_over, utcnow
)
from . import schema
from .schema import CONTENT, PRESENTATION, SCHEDULING
from .store import next_id
from .boards import split_holds, take_and_claim
from .engine import Context, by_id, fail, premise_status, questions, touch


# Validation of question content (AskUserQuestion's limits).

OPTIONAL_PARTS = ('cases', 'premises', 'note')  # text parts printed only when present
PARTS = ('problem', 'root', 'cases', 'premises', 'options', 'rulings')  # `root` is record-only: required, never printed


def part_errors(q: dict, where: str, fields: tuple[str, ...] = PARTS) -> list[str]:
    """The parts the engine prints before the dialog (r27-q123): `problem` and per option `for` and `against` are required; `cases`,
    `premises`, `rulings` and `note` are the lead's own words, printed only when present (`rulings`, when given, with the
    DISCLOSURE fields each). `fields` names the parts to check (a new question: all; an update: the ones it touches)."""
    wanted = [f for f in ('problem', 'root', *OPTIONAL_PARTS, 'rulings') if f in fields or f == 'note']
    errors = [f'{where}: {text}' for text in schema.problems(schema.Question, q, *wanted)]
    if 'options' in fields and isinstance(q.get('options'), list):
        errors += [f'{where}: option {o.get("label")!r} needs `for` and `against`, each a non-empty string'
                   for o in q['options'] if isinstance(o, dict) and schema.problems(schema.Option, o, 'for', 'against')]
    return errors


def question_errors(q: dict, where: str, marks: bool = True, parts: tuple[str, ...] = ()) -> list[str]:
    """Every break of AskUserQuestion's limits and, with `marks`, of the recommendation, its strength and its backing
    (a complete question: Stage, a new question, asking; an update checks the marks only when it touches them); `parts`
    names the printed parts that must be present (Stage and a new question: all; an update: the ones it touches)."""
    errors = part_errors(q, where, parts) if parts else []
    errors += [f'{where}: {text}' for text in schema.problems(schema.Question, q, 'text', 'title', 'header')]
    for field, limit in (('text', TEXT_LIMIT), ('title', TITLE_LIMIT), ('header', HEADER_MAX)):
        if isinstance(q.get(field), str) and len(q[field]) > limit:
            errors.append(f'{where}: {field} {q[field]!r} is {len(q[field])} characters, over the limit of {limit}')
    if isinstance(q.get('text'), str) and re.match(r'\s*\d+[.)]\s', q['text']):
        errors.append(f'{where}: `text` carries no number (the engine numbers the dialog)')
    options = q.get('options')
    valid = isinstance(options, list) and 2 <= len(options) <= 4 and all(
        isinstance(o, dict) and not schema.problems(schema.Option, o, 'label', 'description', 'example') for o in options)
    if not valid:
        errors.append(f"{where}: {schema.text_of(schema.Question, 'options')}")
    else:
        if len({o['label'] for o in options}) != len(options):
            errors.append(f'{where}: option labels must be unique')
        errors += [f'{where}: the description of option {o["label"]!r} is {len(o["description"])} characters, over the limit of {DESCRIPTION_LIMIT}'
                   for o in options if len(o.get('description', '')) > DESCRIPTION_LIMIT]
        if any('preview' in o for o in options):  # r10-q37
            errors.append(f'{where}: rename `preview` to `example`')
    errors += [f'{where}: {text}' for text in schema.problems(schema.Question, q, 'multiSelect', 'waitsOn', 'waitsFor', 'board', 'settles', 'holds')]
    if q.get('kind', 'decision') not in KINDS:  # the form lists what a session stages; a stored release approval has the other kind
        errors.append(f"{where}: {schema.text_of(schema.Question, 'kind')}")
    if not marks:
        return errors
    labels = {o['label'] for o in options} if valid else set()
    if (valid and q.get('recommendation') not in labels) or q.get('strength') not in STRENGTHS:
        errors.append(f"{where}: `recommendation` names one option's label and `strength` is lean or strong (the dialog marks both)")
    if q.get('strength') == 'strong':
        errors += strong_errors(q.get('strongBecause'), where)
    because = q.get('leanBecause')
    if q.get('strength') == 'lean' and not (isinstance(because, dict) and not schema.problems(schema.LeanBecause, because, 'cause', 'detail')):
        errors.append(f'{where}: a lean names its cause: `leanBecause` {{"cause": "preference" (what the choice depends on) or '
                      '"evidence" (the unchecked fact and how to check it), "detail": "…"}')
    elif q.get('strength') == 'lean' and because['cause'] == 'preference' and (
            because.get('flipsIf') is None or schema.problems(schema.LeanBecause, because, 'flipsIf')):
        errors.append(f'{where}: a preference lean says what you would have to value to pick another option: `leanBecause.flipsIf`')
    errors += [f'{where}: {text}' for text in schema.problems(schema.Question, q, 'priorRulings')]
    return errors


def strong_errors(claims, where: str) -> list[str]:
    """A strong mark's `strongBecause`: each criterion a claim with its evidence (STRONG_CRITERIA)."""
    claims = claims if isinstance(claims, dict) else {}
    errors = []
    for name, meaning in STRONG_CRITERIA.items():
        value = claims.get(name)
        allowed = ('true', 'does-not-apply') if name in MAY_NOT_APPLY else ('true',)
        if not (isinstance(value, str) and re.match(rf"({'|'.join(allowed)}): \S", value)):
            errors.append(f"{where}: strong is a claim: `strongBecause.{name}` is \"{' or '.join(f'{a}: …' for a in allowed)}\" "
                          f"({meaning}); if it does not hold, the recommendation is a lean")
    return errors


def refuse_all(errors: list[str]) -> None:
    """One refusal listing every error, so a report is fixed once."""
    if errors:
        fail('; '.join(errors))


def non_decision_errors(ctx: Context, items: list[str]) -> list[str]:
    """A question records on its board item, and only a decision takes a record (r24-q100). An unreadable item is left to
    Record's own check."""
    if not ctx.board or not items:
        return []
    try:
        rows = ctx.board.json('show', *dict.fromkeys(items), '--json', '--field', 'issue_type')
    except ProtocolError:
        return []
    return [f"{item} is a {kind}, not a decision: stage a draft (`board`: null, `for`: its point or selected key); "
            'the answer becomes its own decision record'
            for item in dict.fromkeys(items) if (kind := (rows.get(item) or {}).get('issue_type')) not in (None, 'decision')]


def unknown_fields(where: str, unknown: set) -> str:
    """`explored` belongs to the report, not to an update (agents r11-q48)."""
    hint = ('; `explored` goes at the report\'s top level, keyed by question id (an options pass only), not inside an update'
            if 'explored' in unknown else '')
    return f"{where}: unknown fields {', '.join(sorted(unknown))}{hint}"


def check_question(q: dict, where: str, marks: bool = True, parts: tuple[str, ...] = ()) -> None:
    refuse_all(question_errors(q, where, marks, parts))


def question_warnings(q: dict, fields) -> list[str]:
    """Warnings for the `fields` a call sets that run over their target and within their limit (question_errors' limits): a new
    question sets all of them, an update the ones it carries, so an untouched field is not warned again. Call after the checks pass."""
    warnings = []
    for field, target, limit in (('title', TITLE_MAX, TITLE_LIMIT), ('text', TEXT_MAX, TEXT_LIMIT)):
        if field in fields and isinstance(q.get(field), str):
            warnings += band_warning(f"{q['id']}: {field}", len(q[field]), target, limit)
    if 'options' in fields and isinstance(q.get('options'), list):
        for o in q['options']:
            warnings += band_warning(f"{q['id']}: the description of option {o['label']!r}", len(o.get('description', '')), DESCRIPTION_MAX, DESCRIPTION_LIMIT)
    return warnings


def new_question(ctx: Context, raw: dict, where: str) -> dict:
    unknown = set(raw) - set(CONTENT) - {'key'}
    errors = [unknown_fields(where, unknown)] if unknown else []
    q = {'id': next_id(ctx.state, 'question', 'q'), 'board': None, 'kind': 'decision', 'multiSelect': False,
         'waitsOn': [], 'waitsFor': None, 'for': None, 'settles': [], 'holds': [], 'premises': None, 'priorRulings': None, 'recommendation': None, 'strength': None,
         'leanBecause': None, 'strongBecause': None,
         **{k: v for k, v in raw.items() if k != 'key'},
         'status': 'draft', 'overlaps': [], 'searched': False, 'answer': None, 'round': ctx.round['id']}
    if raw.get('kind', 'decision') in KINDS and raw.get('kind', 'decision') not in STAGED_KINDS:  # the engine asks the release approval; a ruling of the lead's is an ordinary question (r22-q168)
        errors.append(f"{where}: `kind` must be one of {', '.join(STAGED_KINDS)}: a ruling of yours is an ordinary question with a recommendation "
                      'and a mark, and only the release approval is confirm-own-rulings, which the engine asks')
    refuse_all(errors + question_errors(q, where, parts=PARTS))
    ctx.messages += question_warnings(q, CONTENT)
    q['options'] = [{'label': o['label'], 'description': o.get('description', ''), 'for': o['for'].strip(), 'against': o['against'].strip(),
                     **({'example': o['example']} if 'example' in o else {})} for o in q['options']]
    for field in ('problem', 'root', 'cases', 'note', 'waitsFor'):
        if isinstance(q.get(field), str):
            q[field] = q[field].strip()
    return q


def unique_texts(ctx: Context) -> None:
    texts = [q['text'].strip() for q in ctx.round['questions']]
    dupes = sorted({t for t in texts if texts.count(t) > 1})
    if dupes:
        fail(f'question texts must be unique (answers are keyed by text): {dupes[0]!r}')


def resolve_waits(ctx: Context, keys: dict[str, str]) -> None:
    known = {q['id'] for q in ctx.round['questions']} | set(ctx.state['answers'])
    errors = []
    for q in ctx.round['questions']:
        q['waitsOn'] = [keys.get(ref, ref) for ref in q.get('waitsOn') or []]
        for ref in q['waitsOn']:
            if ref == q['id']:
                errors.append(f"{q['id']}: waitsOn names itself")
            elif ref not in known:
                errors.append(f"{q['id']}: waitsOn names {ref}, no question here: " + (
                    'a removed question goes from `waitsOn` in the same report' if QUESTION_ID.fullmatch(ref)
                    else 'a `key` holds only inside the report that defines it; later reports use the question id'))
    refuse_all(errors)
    waits = {q['id']: q['waitsOn'] for q in ctx.round['questions']}

    def loop(qid: str, path: tuple[str, ...]) -> tuple[str, ...] | None:
        if qid in path:
            return (*path[path.index(qid):], qid)
        return next(filter(None, (loop(other, (*path, qid)) for other in waits.get(qid, []))), None)

    cycle = next(filter(None, (loop(qid, ()) for qid in waits)), None)
    if cycle:
        fail(f"waitsOn runs in a circle, so none of them could be asked: {' → '.join(cycle)}")


QUESTION_ID = re.compile(r'q\d+')
POINT = re.compile(r'pt\d+')  # a pasted point's key (next_id 'point'); every other selected key is a board item or a held question


def board_keys(keys) -> list[str]:
    return [key for key in keys or [] if not POINT.fullmatch(key)]


def settles_status_errors(q_keys: list[tuple[str, str]], status: dict[str, str | None]) -> list[str]:
    """`settles` names open questions only: the release closes them as answered. A decided or released record an answer
    changes is related (Related `relate`, corrected at the release's Re-check) or replaced (`supersedes`)."""
    return [f"{qid}: settles {key}, which is {status[key]}: name only open questions in `settles` (the release closes them as "
            f"answered); relate a {status[key]} record the answer changes (Related `relate`, corrected at Re-check) or "
            "replace it (`supersedes`)" for qid, key in q_keys if status.get(key) not in (None, 'open')]


def join_outside(ctx: Context) -> None:
    """An open decision named in an unanswered question's `board` or `settles` joins the round, claimed as at Select: a live
    session's hold is refused, a gone session's taken over; closed, unknown and non-decision items are refused. A boardless
    round has nothing to join: coverage_errors refuses its unknown keys."""
    r = ctx.round
    if not ctx.board or not r['selected']:
        return
    known = {*r['selected'], *(p['id'] for p in r['points'])}
    named = [key for q in questions(ctx, 'draft', 'held', 'ready') for key in ([q['board']] if q['board'] else []) + (q.get('settles') or [])]
    outside = [key for key in dict.fromkeys(named) if key not in known]
    if not outside:
        return
    rows = ctx.board.json('show', *outside, '--json', '--field', 'issue_type', '--field', 'status', '--field', 'title', '--field', 'assignee')
    errors = [f'{key} is unknown or closed, so it cannot join the round' for key in outside if (rows.get(key) or {}).get('status') in (None, 'closed')]
    settling = [(q['id'], key) for q in questions(ctx, 'draft', 'held', 'ready') for key in q.get('settles') or [] if key in outside]
    errors += settles_status_errors([(qid, key) for qid, key in settling if (rows.get(key) or {}).get('status') != 'closed'],
                                    {key: (rows.get(key) or {}).get('status') for key in outside})
    errors += non_decision_errors(ctx, outside)
    live, gone = split_holds(ctx, {key: (rows.get(key) or {}).get('assignee') or '' for key in outside})
    errors += [f'{key} is held by {holder}, a live session, so it cannot join the round' for key, holder in live.items()]
    refuse_all(errors)
    take_and_claim(ctx, list(gone), [key for key in outside if key not in gone])
    r['selected'] = [*r['selected'], *outside]
    r['items'] = [*r['items'], *({'id': key, 'title': rows[key].get('title') or '', 'status': rows[key].get('status')} for key in outside)]
    ctx.log('joined', items=outside)


def shared_board_errors(ctx: Context) -> list[str]:
    """A board item takes one question's record: Record writes each question onto its `board`, so a second one would
    replace the first's record (agents r11-q41)."""
    owner, errors = {}, []
    for q in ctx.round['questions']:
        item = q.get('board')
        if item and owner.setdefault(item, q['id']) != q['id']:
            errors.append(f"{q['id']}: {item} is already {owner[item]}'s item, and a second record on it would replace the first: "
                          f"relate it, or merge the two questions if they are one decision" if taken_over(q) else
                          f"{q['id']}: board {item} is already {owner[item]}'s item; stage it as a draft (`board`: null, "
                          f'`for`: "{item}")')
    return errors


def coverage_errors(ctx: Context) -> list[str]:
    """The rule-question invariants of the round's question set: `settles` names selected keys other than the
    question's own `board`/`for`, no key twice; and every selected key is covered by a
    question's `board`, `for`, id or `settles`. Empty outside Stage and Check (nothing selected)."""
    r = ctx.round
    selected, errors = set(r['selected']), []
    if not selected:
        return errors
    own = {}
    for q in r['questions']:
        for key in (q['board'], q['for']):
            if key:
                own.setdefault(key, q['id'])
    settled = {}
    for q in r['questions']:
        keys = q.get('settles') or []
        for key in dict.fromkeys(keys):
            if key not in selected:
                errors.append(f"{q['id']}: settles {key}, which is not selected")
            elif key in (q['board'], q['for']):
                errors.append(f"{q['id']}: {key} is its own `board`/`for`, not settled by it")
            elif key in own:
                errors.append(f"{q['id']}: settles {key}, which is the `board`/`for` of {own[key]}: remove {own[key]} or drop {key} from `settles`")
            elif settled.setdefault(key, q['id']) != q['id']:
                errors.append(f"{q['id']}: settles {key}, which {settled[key]} settles already")
        if len(set(keys)) != len(keys):
            errors.append(f"{q['id']}: `settles` lists a key twice")
    errors += settles_status_errors([(q['id'], key) for q in r['questions'] for key in dict.fromkeys(q.get('settles') or [])],
                                    {item['id']: item.get('status') for item in r['items']})
    covered = set(own) | set(settled) | {q['id'] for q in r['questions']}
    missing = [key for key in r['selected'] if key not in covered]
    if missing:
        errors.append(f"no question covers {', '.join(missing)} (board items in `board`, pasted points in `for`, or in a rule "
                      "question's `settles`)")
    return errors


MARK_FIELDS = ('recommendation', 'strength', 'leanBecause', 'strongBecause', 'options')


def apply_updates(ctx: Context, updates, answered_rulings: bool = False) -> int:
    """Applies a report's per-question updates, all or none (r23-q95): one refusal lists every error, and a refused call
    saves nothing. Returns the number of questions added, removed or changed in substance (PRESENTATION and SCHEDULING edits apply but do
    not count); `ctx.applied` lists the question of each update that applied. `answered_rulings`: the pass after the last answer, whose
    updates may also change the `rulings` of an answered, unrecorded question (r7-q27)."""
    if not isinstance(updates, list):
        fail('`updates` must be a list')
    changes, keys, errors, placed, touched = 0, {}, [], [], []
    for index, update in enumerate(updates):
        try:
            changed, qid = apply_update(ctx, update, f'updates[{index}]', keys, answered_rulings)
        except ProtocolError as error:
            errors.append(str(error))
            continue
        if qid:
            (ctx.applied if 'id' in update else ctx.added).append(qid)
            touched.append(qid)
            if 'id' not in update and update.get('before') is not None:
                placed.append((qid, update['before'], f'updates[{index}]'))
        changes += changed
    refuse_all(errors)
    for qid, before, where in placed:
        place_before(ctx, qid, keys.get(before, before), where)
    resolve_waits(ctx, keys)
    unique_texts(ctx)
    join_outside(ctx)
    refuse_all(coverage_errors(ctx) + shared_board_errors(ctx) + non_decision_errors(ctx, [u['board'] for u in updates if isinstance(u, dict) and u.get('board')]))  # a merge or split is several updates: the set is checked once, after all of them
    for q in questions(ctx, 'draft', 'held', 'ready'):
        q['status'] = premise_status(ctx, q)
    if touched:
        touch(ctx, touched)
    return changes


def place_before(ctx: Context, qid: str, target: str, where: str) -> None:
    """A new question's `before` (r23-q98): it goes ahead of a question still to be asked; existing questions stay put (q94)."""
    listed = ctx.round['questions']
    other = next((q for q in listed if q['id'] == target), None)
    if other is None:
        fail(f'{where}: `before` names no question of this round: {target}')
    if other['status'] in ('asked', 'answered'):
        fail(f"{where}: `before` names {target}, which is {other['status']}")
    q = next(one for one in listed if one['id'] == qid)
    listed.remove(q)
    listed.insert(listed.index(other), q)


def retire(ctx: Context, q: dict, update: dict, where: str) -> None:
    """A pass finds the question's point entailed (r3-q18): the question stays in the round as answered by the session's
    disclosed ruling (origin `session`), so it covers its point, shows, is walked through once and is recorded like any answered
    question (board item included); the release lists its ruling with the own rulings."""
    if not str(update.get('reason') or '').strip():
        fail(f'{where}: a retiring `ruling` needs the `reason` the point is entailed')
    selected = set(ctx.round['selected'])
    ruling = {k: update['ruling'][k].strip() for k in DISCLOSURE}
    covers = [key for key in dict.fromkeys([q['board'], q['for'], *(q.get('settles') or [])]) if key in selected]
    q.pop('unchecked', None)
    q.update(status='answered', answer=ruling['ruling'], origin='session', quote=None, answeredAt=utcnow(), rulings=[ruling],
             retired={'reason': update['reason'].strip(), 'covers': covers})
    ctx.state['answers'][q['id']] = q['answer']


def change_rulings(ctx: Context, q: dict, update: dict, where: str) -> tuple[int, str]:
    """After the last answer my rulings on an answered question may change; the answer and its options stay the user's (r7-q27).
    Logged, and the record and the release carry it: the release asks the user even when every ruling is sure."""
    if q.get('retired'):
        fail(f"{where}: {q['id']} is retired: its ruling is its answer (the engine lists it with the own rulings)")
    if extra := set(update) - {'id', 'rulings'}:
        fail(f"{where}: {q['id']} is answered; this pass may change only its `rulings`, not {', '.join(sorted(extra))} "
             f"(anything else: restart it first, protocol restart {q['id']})")
    if 'rulings' not in update:
        return 0, q['id']
    rulings = update['rulings'] or []
    refuse_all(part_errors({**q, 'rulings': rulings}, f"{where} ({q['id']})", ('rulings',)))
    if rulings == (q.get('rulings') or []):
        return 0, q['id']
    ctx.log('rulings-changed', question=q['id'], was=q.get('rulings') or [], now=rulings)
    q.update(rulings=rulings, rulingsChanged=True)
    return 1, q['id']


def apply_update(ctx: Context, update, where: str, keys: dict, answered_rulings: bool = False) -> tuple[int, str]:
    """One update; returns (1 for a substantive change, else 0; the question's id)."""
    if not isinstance(update, dict):
        fail(f'{where}: must be an object')
    if bad := schema.problems(schema.Update, update, 'id', 'remove', 'reason', 'before', 'ruling'):
        fail(f'{where}: {bad[0]}')
    if update.get('ruling') and not update.get('remove'):
        fail(f'{where}: `ruling` goes with `remove`: it retires the question as your disclosed ruling')
    if 'id' not in update:
        q = new_question(ctx, {k: v for k, v in update.items() if k != 'before'}, where)
        ctx.round['questions'].append(q)
        keys[update.get('key') or q['id']] = q['id']
        q['status'] = 'draft'
        return 1, q['id']
    q = by_id(ctx, update['id'])
    if answered_rulings and q['status'] == 'answered' and not q.get('recorded'):
        return change_rulings(ctx, q, update, where)
    if q['status'] in ('asked', 'answered'):
        fail(f"{where}: {q['id']} is {q['status']}; restart it first (protocol restart {q['id']})")
    if update.get('remove'):
        if update.get('ruling'):
            retire(ctx, q, update, where)
            ctx.log('retired', question=q['id'], reason=update.get('reason'))
            return 1, q['id']
        ctx.round['questions'].remove(q)
        ctx.log('removed', question=q['id'], reason=update.get('reason'))
        return 1, q['id']
    unknown = set(update) - set(CONTENT) - {'id', 'reason'}
    if unknown:
        fail(unknown_fields(where, unknown))
    merged = {**q, **{k: [] if v is None and k in ('waitsOn', 'settles', 'holds') else v for k, v in update.items() if k in CONTENT}}  # the lists new_question defaults to []
    check_question(merged, f"{where} ({q['id']})", marks=any(k in update for k in MARK_FIELDS),
                   parts=tuple(k for k in PARTS if k in update))
    ctx.messages += question_warnings(merged, update)
    if isinstance(merged.get('waitsFor'), str):
        merged['waitsFor'] = merged['waitsFor'].strip()
    if not any(merged.get(k) != q.get(k) for k in CONTENT):
        return 0, None
    if merged['board'] is None and (merged['text'] != q['text'] or merged['title'] != q['title']):
        merged['searched'] = False  # search again; known outcomes stay
    plain = lambda options: [{'label': o['label'], 'description': o.get('description', ''), 'for': o.get('for'), 'against': o.get('against')}
                             for o in options]  # examples are presentation (r10-q37)
    substantive = any((plain(merged[k]) != plain(q[k]) if k == 'options' else merged.get(k) != q.get(k))
                      for k in CONTENT if k not in (*PRESENTATION, *SCHEDULING))
    if q.get('printed') is not None and merged.get('recommendation') != q.get('recommendation'):
        ctx.log('late-change', question=q['id'], was=q.get('recommendation'), now=merged.get('recommendation'))  # the person had seen it: bin/round-report counts these
    if q.get('waitsFor') and not merged.get('waitsFor'):
        merged['unchecked'] = 'scoped'  # freed: no pass covered it while held, so it takes the scoped check before it is asked
    q.update(merged)
    return int(substantive), q['id']


def describe_errors(raw, where: str, required: bool) -> list[str]:
    if raw is None and not required:
        return []
    if not isinstance(raw, dict) or not all(isinstance(raw.get(k), str) and raw[k].strip() for k in ('title', 'summary')):
        return [f'{where}: `round` needs a plain-words "title" and a "summary" of what this round decides']
    errors = [f'{where}: round {field} is {len(raw[field])} characters, over the limit of {limit}' for field, limit in
              (('title', TITLE_LIMIT), ('summary', SUMMARY_MAX)) if len(raw[field]) > limit]
    overview = raw.get('overview')
    if overview is not None and not (isinstance(overview, str) and overview.strip() and len(overview) <= TEXT_LIMIT):
        errors.append(f'{where}: round `overview` is one line of at most {TEXT_LIMIT} characters, or left out')
    return errors


def describe(ctx: Context, raw, where: str, required: bool) -> None:
    """The round's title and summary: the topic in plain words, no ids; an optional `overview` line printed with the first batch."""
    refuse_all(describe_errors(raw, where, required))
    if raw is not None:
        ctx.round.update(title=raw['title'].strip(), summary=raw['summary'].strip())
        if raw.get('overview') is not None:
            ctx.round['overview'] = raw['overview'].strip()
        ctx.messages += band_warning('round title', len(ctx.round['title']), TITLE_MAX, TITLE_LIMIT)
        ctx.messages += band_warning('round overview', len(ctx.round.get('overview', '')), TEXT_MAX, TEXT_LIMIT) if raw.get('overview') is not None else []


DISCLOSURE = schema.names(schema.Disclosure)


def disclosure_error(ruling: dict, where: str, form) -> str | None:
    """An own ruling as disclosed for a check (the release's own rulings, a challenge-rulings report): DISCLOSURE and `sure`."""
    missing = [k for k in DISCLOSURE if schema.problems(form, ruling, k)]
    if missing or schema.problems(form, ruling, 'sure', due=('sure',)):
        return f"{where}: needs {', '.join(missing) or 'the fields'} and `sure` true or false"
    return None
