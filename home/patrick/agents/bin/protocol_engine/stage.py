"""The round's Stage and Related steps."""
from __future__ import annotations

from .base import (
    BATCH, DESCRIPTION_MAX, HEADER_MAX, LIST_COMMAND, MERGE_TEST, OUTCOMES, ProtocolError, REVISES, REVISES_RULE,
    STRONG_CRITERIA, SUMMARY_MAX, TEXT_MAX, TITLE_MAX, lines
)
from .boards import related_hits, split_holds
from .engine import Context, by_id, fail, premise_status, unresolved
from .questions import (
    coverage_errors, describe, describe_errors, join_outside, new_question, non_decision_errors, refuse_all,
    resolve_waits, unique_texts
)
from .told import report_hint
from .check import gate_ask


def stage_text(ctx: Context) -> str:
    r = ctx.round
    dropped = {key: (ctx.state.get('dropReasons') or {})[key] for key in r['selected'] if key in (ctx.state.get('dropReasons') or {})}
    return lines(
        f"Round {r['id']} · Stage the questions for {', '.join(r['selected'])} under asking.md Question format, "
        'with a round `title` and `summary`. A board item keeps its id in `board`; a pasted point or new '
        'question is a draft (`board`: null, `for`: the point id)' + (', created on the board at Record' if ctx.board
                                                                        else '') + '. `settles` lists the items '
        f'one answer settles the same way (a rule question); an open decision outside the selection named there or in `board` joins the round. {MERGE_TEST} `waitsOn` names the questions a '
        'decision rests on; kind confirm-own-rulings asks the user to confirm your rulings. Each question carries the parts the '
        'engine prints before its dialog, in your own words. Printed parts say what is decided and what each option means for the person '
        '(what they would see, what it costs), each thing once, in plain words; how it was found (sources, measurements beyond the deciding '
        'number, who said what) and how it gets built go to the record. Required: `problem` (what is decided and why now) and per option `for` and `against`. '
        'Optional, printed only when present: `cases` (the concrete cases that must and must not work), `premises` (what it rests on), '
        '`rulings` (each ruling of yours with why it meets the goals without a material trade-off, its strongest alternative, what that fails and the evidence, which only the record keeps) and `note` (a term to define, anything else); '
        'a round may carry one `overview` line across '
        'its questions. A rule question\'s `premises` says how the rule applies to each settled item; the engine prints each item\'s id and title. Mark each recommendation '
        'under decision-protocol.md Recommendation strength: strong sets `strongBecause` '
        f"{', '.join(STRONG_CRITERIA)} each to \"true: <evidence>\" (\"does-not-apply: <reason>\" for consumerWalk "
        'and rulingsChallenged); lean sets `leanBecause` with cause preference (`detail`: what it depends on; `flipsIf`: what you would have to value '
        'to pick another option) or evidence. `priorRulings` holds one entry per released ruling a recommendation rests on or Related linked: '
        '{"ruling", "verdict": "holds" or "fails", "why"}; judge the options as if no ruling existed first; an answer from this round stays a premise. Questions go out in the listed '
        f'order, {BATCH} at a time; `waitsOn` holds a dependent back until its premise is answered. Lengths to keep to in characters and who '
        f'reads each field: round `summary` {SUMMARY_MAX} (pane header); `title` {TITLE_MAX} (pane row; a question\'s '
        f"is also the board item's title); `text` {TEXT_MAX}, without a number (the engine numbers the dialog; it is the dialog "
        f"question and the board item's Question); `header` "
        f'{HEADER_MAX} (dialog chip); option `label`, `description` {DESCRIPTION_MAX} and optional `preview` (dialog; '
        'single-select questions only).',
        *(['A release dropped or held back these records earlier (the reason says what changed; ask what it leaves open):',
           *(f'- {key}: {reason}' for key, reason in dropped.items())] if dropped else []),
        report_hint(ctx, 'stage', {'round': {'title': '<what this round decides>', 'summary': '<the topic in plain words>',
                                             'overview': '<optional: one line across the questions>'},
                     'questions': [{'key': 'a', 'board': None, 'for': r['selected'][0] if r['selected'] else None,
                                    'settles': [], 'text': '<question>?',
                                    'title': '<the decision as a short question>', 'header': '<topic noun>',
                                    'kind': 'decision',
                                    'problem': '<what is decided and why now>', 'cases': '<optional: the cases that must and must not work>',
                                    'options': [{'label': 'A', 'description': '…', 'for': '<for>', 'against': '<against>',
                                                 'preview': '<code example>'},
                                                {'label': 'B', 'description': '…', 'for': '<for>', 'against': '<against>'}],
                                    'premises': '<optional: grounded premises>', 'rulings': [{'ruling': '<your ruling>', 'why': '<what it meets, why no material trade-off remains>', 'alternative': '<strongest alternative>',
                                                                       'fails': '<what it fails>', 'evidence': '<source>'}],
                                    'note': '<optional>', 'recommendation': 'A', 'strength': 'lean',
                                    'leanBecause': {'cause': 'evidence', 'detail': '<the unchecked fact and how to check it>'},
                                    'waitsOn': []}]}),
    )


def stage_accept(ctx: Context, report: dict) -> str:
    raw = report.get('questions')
    errors = describe_errors(report.get('round'), 'stage', required=True)
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
    describe(ctx, report.get('round'), 'stage', required=True)
    resolve_waits(ctx, keys)
    unique_texts(ctx)
    join_outside(ctx)
    refuse_all(coverage_errors(ctx) + non_decision_errors(ctx, [q['board'] for q in ctx.round['questions'] if q.get('board')]))
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
    rows = [f"- {q['id']} ({q['title']}) overlaps {hit['id']}" for q, hit in unresolved(ctx)]
    return lines(
        f"Round {ctx.round['id']} · Related: each new draft's board hits need an outcome before asking: duplicate or "
        'extend (the question takes that item over, in place: the same question answered again), relate (link at Record), '
        'supersedes (a different question, or one replacing several records: Record closes each decided record it '
        'replaces once the answer is recorded, and opens a released one as a revision, replaced at release; a change to '
        'one clause is no replacement), unrelated. Mark `supersedes` on any decided record the question replaces, a hit or '
        'not (name the id under outcomes). Inspect with `board show <id>`; comment on or hand off overlaps '
        'other sessions hold. Also search the exact names of the modules, APIs and sibling cases the options build on '
        f'(`board related <terms>`). A hit that widens the round: list the open items with `{LIST_COMMAND}`.',
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
