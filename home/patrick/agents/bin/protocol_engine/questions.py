"""Validation of question content and the model's question updates."""
from __future__ import annotations

import re

from .base import (
    CONTENT, DESCRIPTION_LIMIT, HEADER_MAX, KINDS, LEAN_CAUSES, MAY_NOT_APPLY, PRESENTATION, ProtocolError, STRENGTHS,
    STRONG_CRITERIA, SUMMARY_MAX, TEXT_LIMIT, TITLE_LIMIT
)
from .store import next_id
from .boards import claim_items, split_holds
from .engine import Context, by_id, fail, premise_status, questions


# Validation of question content (AskUserQuestion's limits).

OPTIONAL_PARTS = ('cases', 'premises', 'note')  # text parts printed only when present
PARTS = ('problem', 'cases', 'premises', 'options', 'rulings')


def part_errors(q: dict, where: str, fields: tuple[str, ...] = PARTS) -> list[str]:
    """The parts the engine prints before the dialog (r27-q123): `problem` and per option `for` and `against` are required; `cases`,
    `premises`, `rulings` and `note` are the lead's own words, printed only when present (`rulings`, when given, with the four
    DISCLOSURE fields each). `fields` names the parts to check (a new question: all; an update: the ones it touches)."""
    errors = []
    if 'problem' in fields and not (isinstance(q.get('problem'), str) and q['problem'].strip()):
        errors.append(f'{where}: `problem` must be a non-empty string (what is decided and why now)')
    errors += [f'{where}: `{field}` must be a string or left out' for field in OPTIONAL_PARTS
               if (field in fields or field == 'note') and q.get(field) is not None and not isinstance(q[field], str)]
    if 'options' in fields and isinstance(q.get('options'), list):
        errors += [f'{where}: option {o.get("label")!r} needs `for` and `against`, each a non-empty string'
                   for o in q['options'] if isinstance(o, dict)
                   and not all(isinstance(o.get(side), str) and o[side].strip() for side in ('for', 'against'))]
    rulings = q.get('rulings')
    if 'rulings' in fields and rulings is not None:
        if not isinstance(rulings, list) or not all(isinstance(x, dict) and all(isinstance(x.get(k), str) and x[k].strip() for k in DISCLOSURE)
                                                    for x in rulings):
            errors.append(f"{where}: `rulings`, when given, lists your own rulings, each with {', '.join(DISCLOSURE)}")
    return errors


def question_errors(q: dict, where: str, marks: bool = True, parts: tuple[str, ...] = ()) -> list[str]:
    """Every break of AskUserQuestion's limits and, with `marks`, of the recommendation, its strength and its backing
    (a complete question: Stage, a new question, asking; an update checks the marks only when it touches them); `parts`
    names the printed parts that must be present (Stage and a new question: all; an update: the ones it touches)."""
    errors = part_errors(q, where, parts) if parts else []
    for field in ('text', 'title', 'header'):
        if not isinstance(q.get(field), str) or not q[field].strip():
            errors.append(f'{where}: `{field}` must be a non-empty string')
    for field, limit in (('text', TEXT_LIMIT), ('title', TITLE_LIMIT), ('header', HEADER_MAX)):
        if isinstance(q.get(field), str) and len(q[field]) > limit:
            errors.append(f'{where}: {field} {q[field]!r} is {len(q[field])} characters, over the limit of {limit}')
    if isinstance(q.get('text'), str) and re.match(r'\s*\d+[.)]\s', q['text']):
        errors.append(f'{where}: `text` carries no number (the engine numbers the dialog)')
    options = q.get('options')
    valid = isinstance(options, list) and 2 <= len(options) <= 4 \
        and all(isinstance(o, dict) and isinstance(o.get('label'), str) and o['label'].strip()
                and isinstance(o.get('description', ''), str) and isinstance(o.get('preview', ''), str) for o in options)
    if not valid:
        errors.append(f'{where}: `options` must be 2-4 objects with a label, a description and optionally a preview (text)')
    else:
        if len({o['label'] for o in options}) != len(options):
            errors.append(f'{where}: option labels must be unique')
        errors += [f'{where}: the description of option {o["label"]!r} is {len(o["description"])} characters, over the limit of {DESCRIPTION_LIMIT}'
                   for o in options if len(o.get('description', '')) > DESCRIPTION_LIMIT]
        if q.get('multiSelect') is True and any('preview' in o for o in options):
            errors.append(f'{where}: `preview` is for single-select questions: remove it or make the question single-select')
    if not isinstance(q.get('multiSelect', False), bool):
        errors.append(f'{where}: `multiSelect` must be a boolean')
    if q.get('kind', 'decision') not in KINDS:
        errors.append(f"{where}: `kind` must be one of {', '.join(KINDS)}")
    if not isinstance(q.get('waitsOn', []), list) or not all(isinstance(i, str) for i in q.get('waitsOn', [])):
        errors.append(f'{where}: `waitsOn` must be a list of question ids')
    if q.get('board') is not None and not isinstance(q['board'], str):
        errors.append(f'{where}: `board` must be a board id or null')
    if not isinstance(q.get('settles') or [], list) or not all(isinstance(i, str) and i for i in q.get('settles') or []):
        errors.append(f'{where}: `settles` must be a list of selected keys (board ids or pasted point ids)')
    if not marks:
        return errors
    labels = {o['label'] for o in options} if valid else set()
    if (valid and q.get('recommendation') not in labels) or q.get('strength') not in STRENGTHS:
        errors.append(f"{where}: `recommendation` names one option's label and `strength` is lean or strong (the dialog marks both)")
    if q.get('strength') == 'strong':
        claims = q.get('strongBecause') if isinstance(q.get('strongBecause'), dict) else {}
        for name, meaning in STRONG_CRITERIA.items():
            value = claims.get(name)
            allowed = ('true', 'does-not-apply') if name in MAY_NOT_APPLY else ('true',)
            if not (isinstance(value, str) and re.match(rf"({'|'.join(allowed)}): \S", value)):
                errors.append(f"{where}: strong is a claim: `strongBecause.{name}` is \"{' or '.join(f'{a}: …' for a in allowed)}\" "
                              f"({meaning}); if it does not hold, the recommendation is a lean")
    because = q.get('leanBecause')
    if q.get('strength') == 'lean' and not (isinstance(because, dict) and because.get('cause') in LEAN_CAUSES
                                            and isinstance(because.get('detail'), str) and because['detail'].strip()):
        errors.append(f'{where}: a lean names its cause: `leanBecause` {{"cause": "preference" (what the choice depends on) or '
                      '"evidence" (the unchecked fact and how to check it), "detail": "…"}')
    elif q.get('strength') == 'lean' and because['cause'] == 'preference' and not (isinstance(because.get('flipsIf'), str) and because['flipsIf'].strip()):
        errors.append(f'{where}: a preference lean says what you would have to value to pick another option: `leanBecause.flipsIf`')
    prior = q.get('priorRulings')
    if prior is not None and not (isinstance(prior, list) and all(isinstance(x, dict) and x.get('verdict') in ('holds', 'fails') and all(isinstance(x.get(k), str) and x[k].strip() for k in ('ruling', 'why')) for x in prior)):
        errors.append(f'{where}: `priorRulings` lists {{"ruling", "verdict": "holds" or "fails", "why"}}')
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


def check_question(q: dict, where: str, marks: bool = True, parts: tuple[str, ...] = ()) -> None:
    refuse_all(question_errors(q, where, marks, parts))


def new_question(ctx: Context, raw: dict, where: str) -> dict:
    unknown = set(raw) - set(CONTENT) - {'key'}
    errors = [f"{where}: unknown fields {', '.join(sorted(unknown))}"] if unknown else []
    q = {'id': next_id(ctx.state, 'question', 'q'), 'board': None, 'kind': 'decision', 'multiSelect': False,
         'waitsOn': [], 'for': None, 'settles': [], 'premises': None, 'priorRulings': None, 'recommendation': None, 'strength': None,
         'leanBecause': None, 'strongBecause': None,
         **{k: v for k, v in raw.items() if k != 'key'},
         'status': 'draft', 'overlaps': [], 'searched': False, 'answer': None, 'round': ctx.round['id']}
    refuse_all(errors + question_errors(q, where, parts=PARTS))
    q['options'] = [{'label': o['label'], 'description': o.get('description', ''), 'for': o['for'].strip(), 'against': o['against'].strip(),
                     **({'preview': o['preview']} if 'preview' in o else {})} for o in q['options']]
    for field in ('problem', 'cases', 'note'):
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
    if gone:
        ctx.board.checked('take', *gone)
        r['claimed'] = [*r.get('claimed', []), *gone]
    if free := [key for key in outside if key not in gone]:
        claim_items(ctx, free)
    r['selected'] = [*r['selected'], *outside]
    r['items'] = [*r['items'], *({'id': key, 'title': rows[key].get('title') or '', 'status': rows[key].get('status')} for key in outside)]
    ctx.log('joined', items=outside)


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


def apply_updates(ctx: Context, updates) -> int:
    """Applies a report's per-question updates, all or none (r23-q95): one refusal lists every error, and a refused call
    saves nothing. Returns the number of questions added, removed or changed in substance (PRESENTATION edits apply but do
    not count); `ctx.applied` lists the question of each update that applied."""
    if not isinstance(updates, list):
        fail('`updates` must be a list')
    changes, keys, errors, placed = 0, {}, [], []
    for index, update in enumerate(updates):
        try:
            changed, qid = apply_update(ctx, update, f'updates[{index}]', keys)
        except ProtocolError as error:
            errors.append(str(error))
            continue
        if qid:
            (ctx.applied if 'id' in update else ctx.added).append(qid)
            if 'id' not in update and update.get('before') is not None:
                placed.append((qid, update['before'], f'updates[{index}]'))
        changes += changed
    refuse_all(errors)
    for qid, before, where in placed:
        place_before(ctx, qid, keys.get(before, before), where)
    resolve_waits(ctx, keys)
    unique_texts(ctx)
    join_outside(ctx)
    refuse_all(coverage_errors(ctx) + non_decision_errors(ctx, [u['board'] for u in updates if isinstance(u, dict) and u.get('board')]))  # a merge or split is several updates: the set is checked once, after all of them
    for q in questions(ctx, 'draft', 'held', 'ready'):
        q['status'] = premise_status(ctx, q)
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


def apply_update(ctx: Context, update, where: str, keys: dict) -> tuple[int, str]:
    """One update; returns (1 for a substantive change, else 0; the question's id)."""
    if not isinstance(update, dict):
        fail(f'{where}: must be an object')
    if 'id' not in update:
        before = update.get('before')
        if before is not None and not isinstance(before, str):
            fail(f'{where}: `before` must be a question id')
        q = new_question(ctx, {k: v for k, v in update.items() if k != 'before'}, where)
        ctx.round['questions'].append(q)
        keys[update.get('key') or q['id']] = q['id']
        q['status'] = 'draft'
        return 1, q['id']
    q = by_id(ctx, update['id'])
    if q['status'] in ('asked', 'answered'):
        fail(f"{where}: {q['id']} is {q['status']}; restart it first (protocol restart {q['id']})")
    if update.get('remove'):
        ctx.round['questions'].remove(q)
        ctx.log('removed', question=q['id'], reason=update.get('reason'))
        return 1, q['id']
    unknown = set(update) - set(CONTENT) - {'id', 'reason'}
    if unknown:
        fail(f"{where}: unknown fields {', '.join(sorted(unknown))}")
    merged = {**q, **{k: v for k, v in update.items() if k in CONTENT}}
    check_question(merged, f"{where} ({q['id']})", marks=any(k in update for k in MARK_FIELDS),
                   parts=tuple(k for k in PARTS if k in update))
    if not any(merged.get(k) != q.get(k) for k in CONTENT):
        return 0, None
    if merged['board'] is None and (merged['text'] != q['text'] or merged['title'] != q['title']):
        merged['searched'] = False  # search again; known outcomes stay
    plain = lambda options: [{'label': o['label'], 'description': o.get('description', ''), 'for': o.get('for'), 'against': o.get('against')}
                             for o in options]  # previews are presentation
    substantive = any((plain(merged[k]) != plain(q[k]) if k == 'options' else merged.get(k) != q.get(k))
                      for k in CONTENT if k not in PRESENTATION)
    if q.get('printed') is not None and merged.get('recommendation') != q.get('recommendation'):
        ctx.log('late-change', question=q['id'], was=q.get('recommendation'), now=merged.get('recommendation'))  # the person had seen it: bin/round-report counts these
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


DISCLOSURE = ('ruling', 'alternative', 'fails', 'evidence')  # asking.md Walk through: own rulings
