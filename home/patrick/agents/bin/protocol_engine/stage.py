"""The round's Stage and Related steps."""
from __future__ import annotations

from .base import OUTCOMES, ProtocolError, REVISES, REVISES_RULE, lines
from . import words
from .boards import related_hits, split_holds
from .engine import Context, by_id, fail, premise_status, unresolved
from .questions import (
    coverage_errors, describe, describe_errors, join_outside, new_question, non_decision_errors, refuse_all, shared_board_errors,
    resolve_waits, unique_texts
)
from .told import report_hint
from .check import gate_ask


def titled(ctx: Context) -> bool:
    """The round has its title and summary already (from a stored proposal): Stage replaces them only when its report names new ones."""
    return bool(ctx.round.get('title') and ctx.round.get('summary'))


def stage_text(ctx: Context) -> str:
    r = ctx.round
    dropped = {key: (ctx.state.get('dropReasons') or {})[key] for key in r['selected'] if key in (ctx.state.get('dropReasons') or {})}
    return lines(
        words.stage_instructions(r['id'], r['selected'], bool(ctx.board), titled(ctx), [k for k in r.get('first') or [] if k in r['selected']]),
        *(words.stage_dropped(dropped) if dropped else []),
        report_hint(ctx, 'stage', words.stage_example(r['selected'][0] if r['selected'] else None)),
    )


def stage_accept(ctx: Context, report: dict) -> str:
    raw = report.get('questions')
    errors = describe_errors(report.get('round'), 'stage', required=not titled(ctx))
    if not isinstance(raw, list):
        fail('; '.join([*errors, '`questions` must be a list']))
    keys = {}
    for index, item in enumerate(raw):
        try:
            if not isinstance(item, dict):
                fail(f'questions[{index}]: must be an object')
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
    join_outside(ctx)
    refuse_all(coverage_errors(ctx) + shared_board_errors(ctx) + non_decision_errors(ctx, [q['board'] for q in ctx.round['questions'] if q.get('board')]))
    if not ctx.round['questions']:
        fail('stage at least one question')
    for q in ctx.round['questions']:
        q['status'] = premise_status(ctx, q)
    ctx.log('staged', questions=[q['id'] for q in ctx.round['questions']])
    return 'related'


def related_enter(ctx: Context) -> str | None:
    for q in ctx.round['questions']:
        if q['board'] is None and not q['searched'] and q['status'] != 'answered':
            if ctx.board:
                known = {hit['id'] for hit in q['overlaps']}
                hits = related_hits(ctx.board, f"{q['title']}\n{q['text']}")
                q['overlaps'] += [{'id': hit, 'title': title, 'outcome': None} for hit, title in hits if hit not in known]
                ctx.log('related', question=q['id'], hits=[hit for hit, _ in hits])
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
    Record could not carry out: a record that is no ruling, a foreign live hold (`board supersede` has no holder
    check), more than one revision to carry onto the new record."""
    hits = [h['id'] for h in q['overlaps'] if h['outcome'] == 'supersedes']
    q['replaces'], q['revises'] = [], None
    if not hits:
        return
    rows = ctx.board.json('show', *hits, '--json', '--field', 'status', '--field', 'issue_type', '--field', 'assignee',
                          '--field', 'dependencies', '--field', 'metadata', '--field', 'title')
    for hit in q['overlaps']:  # the dialog names each record it replaces by its title
        if hit['id'] in hits:
            hit['title'] = (rows.get(hit['id']) or {}).get('title') or hit['title']
    problems = [f"{hit} is {(rows.get(hit) or {}).get('status')} {(rows.get(hit) or {}).get('issue_type')}, not a ruling"
                for hit in hits if (rows.get(hit) or {}).get('issue_type') != 'decision'
                or (rows.get(hit) or {}).get('status') in (None, 'open', 'in_progress')]
    if problems:
        fail(f"{q['id']}: supersedes needs a recorded ruling: " + '; '.join(problems))
    replaces = [hit for hit in hits if rows[hit]['status'] == 'decided']
    released = [hit for hit in hits if hit not in replaces]
    if len(released) > 1:
        fail(f"{q['id']}: a question revises at most one released record ({', '.join(released)}); split the question")
    held = split_holds(ctx, {hit: rows[hit].get('assignee') or '' for hit in replaces})[0]
    if held:
        fail(f"{q['id']}: {', '.join(f'{rid} (held by {holder})' for rid, holder in held.items())} would close at Record, "
             'and another live session holds it; ask that session to hand it off (board unclaim), or choose another outcome')
    # Record moves a closed record's pending revision to the new record, which keeps one revision (target and rule).
    carried = {(dep['depends_on_id'], (rows[hit].get('metadata') or {}).get(REVISES_RULE))
               for hit in replaces for dep in rows[hit].get('dependencies') or []
               if dep['issue_id'] == hit and dep['type'] == REVISES}
    if len({*carried, *((rid, None) for rid in released)}) > 1:
        fail(f"{q['id']}: the new record would revise more than one record or rule "
             f"({', '.join(sorted(f'{t}' + (f' ({r})' if r else '') for t, r in {*carried, *((rid, None) for rid in released)}))}); "
             'a record keeps one revision: split the question')
    q['replaces'], q['revises'] = replaces, released[0] if released else None


def related_accept(ctx: Context, report: dict) -> str:
    outcomes = report.get('outcomes')
    if not isinstance(outcomes, dict):
        fail('`outcomes` must map question ids to {hit id: outcome}')
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
        takeover = [h['id'] for h in q['overlaps'] if h['outcome'] in ('duplicate', 'extend')]
        if len(takeover) > 1 or (takeover and any(h['outcome'] == 'supersedes' for h in q['overlaps'])):
            fail(f'{qid}: one question takes over at most one item, and not while it supersedes another')
        resolve_replaced(ctx, q)
    missing = unresolved(ctx)
    if missing:
        fail('outcomes missing: ' + ', '.join(f"{q['id']}→{hit['id']}" for q, hit in missing))
    return gate_ask(ctx) if ctx.round['check'].get('converged') else 'check'
