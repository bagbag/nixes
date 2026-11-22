"""The round's Stage and Related steps."""
from __future__ import annotations

from .base import OUTCOMES, ProtocolError, TAKEOVER, lines
from . import schema, words
from .boards import question_holds, related_hits
from .engine import Context, by_id, fail, premise_status, unresolved
from .questions import (
    admit_question_set, describe, describe_errors, draft_only_holds, new_question, refuse_all, resolve_waits, unique_texts
)
from .told import report_hint
from .check import gate_ask


def titled(ctx: Context) -> bool:
    """The round has its title and summary already (from a stored proposal): Stage replaces them only when its report names new ones."""
    return bool(ctx.round.get('title') and ctx.round.get('summary'))


def stage_text(ctx: Context) -> str:
    r = ctx.round
    dropped = {key: (ctx.state.get('dropReasons') or {})[key] for key in r['selected'] if key in (ctx.state.get('dropReasons') or {})}
    existing = {item['id'] for item in r.get('items') or []}
    holds = question_holds(ctx, [key for key in r['selected'] if key in existing])
    return lines(
        words.stage_instructions(r['id'], r['selected'], bool(ctx.board), titled(ctx), [k for k in r.get('first') or [] if k in r['selected']]),
        *(f"Existing board question {qid}: open blocks {text}." for qid, text in holds.items()),
        *(words.stage_dropped(dropped) if dropped else []),
        report_hint(ctx, 'stage', words.stage_example(r['selected'][0] if r['selected'] else None)),
    )


def stage_accept(ctx: Context, report: dict) -> str:
    raw = report.get('questions')
    errors = describe_errors(report.get('round'), 'stage', required=not titled(ctx))
    if shape := schema.problems(schema.Stage, report, 'questions'):
        fail('; '.join([*errors, *shape]))
    keys = {}
    for index, item in enumerate(raw):
        try:
            if not isinstance(item, dict):
                fail(f'questions[{index}]: must be an object')
            if item.get('board') and 'holds' in item:
                errors.append(draft_only_holds(f'questions[{index}]'))
                continue
            q = new_question(ctx, item, f'questions[{index}]')
        except ProtocolError as error:
            errors.append(str(error))
            continue
        ctx.round['questions'].append(q)
        keys[item.get('key') or q['id']] = q['id']
    refuse_all(errors)
    describe(ctx, report.get('round'), 'stage', required=not titled(ctx))
    resolve_waits(ctx, keys)
    unique_texts(ctx)
    if not ctx.round['questions']:
        fail('stage at least one question')
    admit_question_set(ctx, ctx.round['questions'])
    for q in ctx.round['questions']:
        q['status'] = premise_status(ctx, q)
    ctx.log('staged', questions=[q['id'] for q in ctx.round['questions']])
    return 'related'


def related_enter(ctx: Context) -> str | None:
    for q in ctx.round['questions']:
        if not q['searched'] and q['status'] != 'answered':
            if ctx.board:
                known = {hit['id'] for hit in q['overlaps']}
                if q['board']:
                    rows = ctx.board.json('show', q['board'], '--json', '--field', 'dependencies')
                    linked = {(dep['issue_id'], dep['depends_on_id']) for row in rows.values()
                              for dep in (row or {}).get('dependencies') or []
                              if dep.get('type') in ('relates-to', 'related')}
                    hits = sorted({b if a == q['board'] else a for a, b in linked})
                    titles = ctx.board.json('show', *hits, '--json', '--field', 'title') if hits else {}
                    found = [(hit, (titles.get(hit) or {}).get('title') or '') for hit in hits]
                else:
                    found = related_hits(ctx.board, f"{q['title']}\n{q['text']}")
                q['overlaps'] += [{'id': hit, 'title': title, 'outcome': None} for hit, title in found if hit not in known]
                ctx.log('related', question=q['id'], hits=[hit for hit, _ in found])
            q['searched'] = True
    if unresolved(ctx):
        return None
    return gate_ask(ctx) if ctx.round['check'].get('converged') else 'check'


def related_text(ctx: Context) -> str:
    rows = [words.related_row(q, hit) for q, hit in unresolved(ctx)]
    return lines(
        words.related_instructions(ctx.round['id']),
        *rows,
        report_hint(ctx, 'related', {'outcomes': {q['id']: {hit['id']: 'unrelated'} for q, hit in unresolved(ctx)[:1]}}),
    )


def resolve_replaced(ctx: Context, q: dict) -> None:
    """What the question's `supersedes` hits mean, read from the board: a decided (unreleased) record closes at Record
    (`q['replaces']`); a released one is revised, replaced at its release (`q['revises']`, at most one). Refuses what
    `board ruling check-replaces` refuses, before the user answers; Record repeats mutable checks against its new id."""
    hits = [h['id'] for h in q['overlaps'] if h['outcome'] == 'supersedes']
    q['replaces'], q['revises'] = [], None
    if not hits:
        return
    result = ctx.board.json('ruling', 'check-replaces', *hits)
    for hit in q['overlaps']:  # the dialog names each record it replaces by its title
        if hit['id'] in hits:
            hit['title'] = result['titles'].get(hit['id']) or hit['title']
    q['replaces'], q['revises'] = result['replaces'], result['revises']


def related_accept(ctx: Context, report: dict) -> str:
    schema.require(schema.Related, report)
    outcomes = report['outcomes']
    for qid, hits in outcomes.items():
        q = by_id(ctx, qid)
        if not isinstance(hits, dict):
            fail(f'outcomes.{qid}: must map hit ids to an outcome')
        for hit_id, outcome in hits.items():
            hit = next((h for h in q['overlaps'] if h['id'] == hit_id), None)
            if hit is None:
                if outcome != 'supersedes':
                    fail(f'outcomes.{qid}: {hit_id} is no hit of {qid} (only `supersedes` may name a decided record the search missed)')
                hit = {'id': hit_id, 'title': '', 'outcome': None}  # resolve_replaced reads its title and refuses what is no ruling
                q['overlaps'].append(hit)
            if outcome not in OUTCOMES:
                fail(f"outcomes.{qid}.{hit_id}: outcome must be one of {', '.join(OUTCOMES)}")
            hit['outcome'] = outcome
        takeover = [h['id'] for h in q['overlaps'] if h['outcome'] in TAKEOVER]
        if len(takeover) > 1 or (takeover and any(h['outcome'] == 'supersedes' for h in q['overlaps'])):
            fail(f'{qid}: one question takes over at most one item, and not while it supersedes another')
        if takeover and q.get('holds'):
            fail(draft_only_holds(f'{qid} (takes over {takeover[0]})'))
        resolve_replaced(ctx, q)
        # the item it records onto from here on (one place holds it): a takeover, else the question's own item from before Related
        own = q.setdefault('ownBoard', q['board'])
        q['board'] = takeover[0] if takeover else own
    missing = unresolved(ctx)
    if missing:
        fail('outcomes missing: ' + ', '.join(f"{q['id']}→{hit['id']}" for q, hit in missing))
    admit_question_set(ctx, [q for q in ctx.round['questions'] if q.get('revises') or q.get('replaces')])
    return gate_ask(ctx) if ctx.round['check'].get('converged') else 'check'
