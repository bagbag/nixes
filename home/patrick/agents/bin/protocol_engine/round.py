"""The `round` protocol: its step table, and the Check step text, which embeds ask_text (ask builds on check)."""
from __future__ import annotations

from .base import HAND_OVER, LEAN_JOB, lines, plural
from .engine import Context, PROTOCOLS, Protocol, Step, questions
from .told import cycle_key, first_time
from .record import closed_enter, closed_text, record_accept, record_text
from .check import check_accept, check_enter, options_ids, options_report_format, pass_report_format, rescope_ids
from .ask import ask_accept, ask_enter, ask_text
from .collect import collect_accept, collect_enter, collect_text, select_accept, select_text
from .stage import related_accept, related_enter, related_text, stage_accept, stage_text


# Steps of `round`.

def pass_text(ctx: Context, command: str) -> str:
    args = (ctx.round['pending'] or {}).get('args') or ''
    scope = f'with the argument `{args}` (lenses, the questions to strengthen, then any focus)' if args else 'on the whole round'
    if ctx.codex:
        return f'Run the {command} skill now {scope} (read its SKILL.md), then report the pass.'
    return HAND_OVER


def same_options_lines(ctx: Context) -> list[str]:
    """Open questions offering identical option labels, ignoring case and order (r33-q157): advice, once per group."""
    groups = {}
    for q in questions(ctx, 'draft', 'held', 'ready'):
        groups.setdefault(frozenset(o['label'].casefold() for o in q['options']), []).append(q['id'])
    said = []
    for ids in groups.values():
        if len(ids) > 1 and first_time(ctx, f"same-options:{ctx.round['id']}:{' '.join(ids)}"):
            named = f"{', '.join(ids[:-1])} and {ids[-1]}"
            said.append(f'{named} offer identical options. Merge them only if no sensible answer would treat them differently.')
    return said


def check_text(ctx: Context) -> str:
    r, check = ctx.round, ctx.round['check']
    if r['batch']:
        return ask_text(ctx)
    if check['paused']:
        return f"Round {r['id']} · Check paused by the user at cycle {check['cycle']}. `protocol resume` continues it."
    command = check['expect']
    rows = [f"- {q['id']} {q['status']}{' (' + q['kind'] + ')' if q['kind'] != 'decision' else ''}: {q['text']}"
            + (f" — waits on {', '.join(q['waitsOn'])}" if q['status'] == 'held' else '') for q in r['questions']]
    if not first_time(ctx, cycle_key(ctx, 'questions')):  # the cycle's first pass lists them, the others count them
        rows = [f'{plural(len(rows), "question")} (protocol show lists them)']
    challenge = check.get('challenge') or {}
    return lines(
        f"Round {r['id']} · Check" + ('' if not ctx.codex else f" cycle {check['cycle']}/{check['cap']}")
        + (' (after the last answer: challenge the answers and your own rulings in this round; a finding is a new question, '
           'checked before it is asked).'
           if challenge.get('kind') == 'answers' else
           f" (the strong recommendation raised on {' '.join(challenge['ids'])})."
           if challenge.get('kind') == 'raised' else
           LEAN_JOB
           if check.get('focusing') else
           '.'
           if not ctx.codex else  # Claude's model reads no pass sequence: the pass's own argument says what it is (r34-q165)
           ' (last before the batch).'
           if command == 'challenge-rulings' else
           f" (the path pass on the restarted questions {' '.join(rescope_ids(ctx))}: goal and foundations)."
           if check.get('pathScoped') else
           " (the round's path pass: goal and foundations, before the drafts settle)."
           if check.get('pathNow') else
           f" (the options pass on the restarted questions {' '.join(options_ids(ctx, rescope_ids(ctx)))}: other ways to the outcome)."
           if check.get('optionsScoped') else
           " (the round's options pass: radically different ways to the outcome, before the drafts settle)."
           if check.get('optionsNow') else
           f" (the refine pass on the restarted questions {' '.join(rescope_ids(ctx))}: the lenses named in the argument)."
           if check.get('refineScoped') else
           " (the round's refine pass: the lenses named in the argument)."
           if check.get('refineNow') else
           '.'),
        *rows,
        *same_options_lines(ctx),
        pass_text(ctx, command),
        pass_report_format(ctx, command),
        options_report_format(ctx) if check.get('optionsNow') else '',
    )


ROUND = Protocol('round', [
    Step('collect', collect_text, collect_accept, collect_enter),
    Step('select', select_text, select_accept),
    Step('stage', stage_text, stage_accept),
    Step('related', related_text, related_accept, related_enter),
    Step('check', check_text, check_accept, check_enter),
    Step('ask', ask_text, ask_accept, ask_enter),
    Step('record', record_text, record_accept),
    Step('closed', closed_text, None, closed_enter),
], after_ask='record')
PROTOCOLS['round'] = ROUND
