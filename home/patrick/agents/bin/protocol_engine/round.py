"""The `round` protocol: its step table, and the Check step text, which embeds ask_text (ask builds on check)."""
from __future__ import annotations

from .base import lines
from . import words
from .engine import Context, PROTOCOLS, Protocol, Step, questions
from .told import changed_rows, first_time
from .record import closed_enter, closed_text, record_accept, record_text
from .check import (
    challenge_report_format, check_accept, check_enter, options_ids, options_report_format, pass_report_format, rescope_ids, scope_text
)
from .ask import ask_accept, ask_enter, ask_text
from .collect import collect_accept, collect_text, select_accept, select_text
from .prepass import prepass_accept, prepass_enter, prepass_text
from .stage import related_accept, related_enter, related_text, stage_accept, stage_text


# Steps of `round`.

def pass_text(ctx: Context, command: str) -> str:
    args = (ctx.round['pending'] or {}).get('args') or ''
    if ctx.codex:
        return words.codex_pass(command, args)
    return words.HAND_OVER


def same_options_lines(ctx: Context) -> list[str]:
    """Open questions offering identical option labels, ignoring case and order (r33-q157): advice, once per group."""
    groups = {}
    for q in questions(ctx, 'draft', 'held', 'ready'):
        groups.setdefault(frozenset(o['label'].casefold() for o in q['options']), []).append(q['id'])
    said = []
    for ids in groups.values():
        if len(ids) > 1 and first_time(ctx, f"same-options:{ctx.round['id']}:{' '.join(ids)}"):
            said.append(words.same_options(ids))
    return said


def check_why(ctx: Context) -> str:
    """The Check title's closing words: why this pass runs now."""
    check = ctx.round['check']
    challenge = check.get('challenge') or {}
    return (words.CHECK_PLAIN
            if not ctx.codex else  # Claude's model reads no pass sequence: the pass's own skill and argument say what it is (r34-q165)
            words.CHECK_AFTER_ANSWERS
            if challenge.get('kind') == 'answers' else
            words.check_raised(challenge['ids'])
            if challenge.get('kind') == 'raised' else
            words.LEAN_JOB
            if check.get('focusing') else
            words.CHECK_LAST
            if check['expect'] == 'challenge-rulings' else
            words.check_path_scoped(rescope_ids(ctx))
            if check.get('pathScoped') else
            words.CHECK_PATH_NOW
            if check.get('pathNow') else
            words.check_options_scoped(options_ids(ctx, rescope_ids(ctx)))
            if check.get('optionsScoped') else
            words.CHECK_OPTIONS_NOW
            if check.get('optionsNow') else
            words.check_refine_scoped(rescope_ids(ctx))
            if check.get('refineScoped') else
            words.CHECK_REFINE_NOW
            if check.get('refineNow') else
            words.CHECK_PLAIN)


def check_text(ctx: Context) -> str:
    r, check = ctx.round, ctx.round['check']
    if r['batch']:
        return ask_text(ctx)
    if check['paused']:
        return words.check_paused(r['id'], check['cycle'])
    command = check['expect']
    every = {q['id']: words.check_row(q) for q in r['questions']}
    changed = changed_rows(ctx, r['id'], every)
    rows = [*changed, words.questions_counted(len(every), len(changed))]  # only what differs from the last output, then the count
    return lines(
        words.check_title(r['id'], f"{check['cycle']}/{check['cap']}" if ctx.codex else None) + check_why(ctx),
        *rows,
        *same_options_lines(ctx),
        pass_text(ctx, command),
        scope_text(ctx, command),
        pass_report_format(ctx, command),
        options_report_format(ctx) if check.get('optionsNow') else '',
        challenge_report_format(ctx) if command == 'challenge-rulings' else '',
    )


ROUND = Protocol('round', [
    Step('prepass', prepass_text, prepass_accept, prepass_enter),
    Step('collect', collect_text, collect_accept),
    Step('select', select_text, select_accept),
    Step('stage', stage_text, stage_accept),
    Step('related', related_text, related_accept, related_enter),
    Step('check', check_text, check_accept, check_enter),
    Step('ask', ask_text, ask_accept, ask_enter),
    Step('record', record_text, record_accept),
    Step('closed', closed_text, None, closed_enter),
], after_ask='record')
PROTOCOLS['round'] = ROUND
