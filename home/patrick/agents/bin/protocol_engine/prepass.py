"""The round's Pre-pass step: one step-back over the whole point set (and the subject, if any) before Collect."""
from __future__ import annotations

from .base import lines
from . import words
from .collect import read_listing
from .engine import Context, fail
from .questions import refuse_all
from .store import next_id
from .told import report_hint

PREPASS_LENSES = 'goal decisions'  # the step-back skill's lenses for the whole picture; the focus text after them says what this pass is
SUBJECT_ARG = 60  # characters of the subject the pending pass's argument carries; the step text carries it whole


def prepass_args(r: dict) -> str:
    subject = ' '.join((r.get('subject') or '').split())
    return f"{PREPASS_LENSES}; pre-pass " + (f"on {subject[:SUBJECT_ARG]}" if subject else "over the round's points")


def prepass_enter(ctx: Context) -> str | None:
    read_listing(ctx)
    ctx.set_pending('step-back', prepass_args(ctx.round))
    return None


def prepass_text(ctx: Context) -> str:
    r = ctx.round
    pending = r['pending'] or {}
    rows = [words.collect_point(p) for p in r['points']] + [words.item_row(i) for i in r['items']]
    return lines(
        words.prepass_instructions(r['id'], r.get('subject'), ctx.codex, pending.get('args') or '', rows),
        report_hint(ctx, 'prepass', words.PREPASS_EXAMPLE),
    )


def prepass_accept(ctx: Context, report: dict) -> str:
    r = ctx.round
    pending = r['pending'] or {}
    command = report.get('pass')
    if command != pending.get('command'):
        fail(f"`pass` is {pending.get('command')}, the pre-pass waiting; the questions' passes follow Stage")
    if not ctx.codex:  # Codex has no console to observe its runs
        if command not in r['observed']:
            fail(words.no_run(command, pending))
        if r['observed'][command].get('pending') != pending.get('id'):
            fail(f"/{command} ran without the pre-pass argument (`{pending.get('args')}`)")
    origin = (r['observed'].get(command) or {}).get('origin', 'model')
    errors = []
    if not isinstance(report.get('summary'), str) or not report['summary'].strip():
        errors.append('`summary`: one line on what the pre-pass found')
    if r.get('subject') and not (isinstance(report.get('verdict'), str) and report['verdict'].strip()):
        errors.append(f"`verdict`: the subject's verdict in a sentence (the round judges {r['subject']})")
    if not r.get('subject') and report.get('verdict') is not None:
        errors.append('`verdict` belongs to a round with a --subject')
    entries = report.get('points', [])
    if not isinstance(entries, list):
        errors.append('`points` is a list of entries')
        entries = []
    pasted = {p['id']: p for p in r['points']}
    items = {i['id'] for i in r['items']}
    edits, added, first, dropped = {}, [], [], {}
    for index, entry in enumerate(entries):
        at = f'points[{index}]'
        if not isinstance(entry, dict):
            errors.append(f'{at}: must be an object')
            continue
        text, pid = entry.get('text'), entry.get('id')
        if text is not None and not (isinstance(text, str) and text.strip()):
            errors.append(f'{at}: `text` is a non-empty string')
        elif pid is None:
            if text is None:
                errors.append(f'{at}: a new point needs `text`')
            else:
                added.append((text.strip(), bool(entry.get('first'))))
        elif pid in pasted:
            if entry.get('drop'):
                if not str(entry.get('reason') or '').strip():
                    errors.append(f'{at}: dropping {pid} needs a `reason`')
                if entry.get('first') or text is not None:
                    errors.append(f'{at}: {pid} is dropped: no `first` or `text` with it')
                dropped[pid] = str(entry.get('reason') or '').strip()
            elif text is not None:
                edits[pid] = text.strip()
            if entry.get('first') and not entry.get('drop'):
                first.append(pid)
        elif pid in items:
            if entry.get('drop') or text is not None:
                errors.append(f'{at}: {pid} is a board item: only `first` applies (it leaves the round unclassified at Collect, or is cut at Stage)')
            elif entry.get('first'):
                first.append(pid)
        else:
            errors.append(f'{at}: {pid} is no pasted point or open item of this round')
    refuse_all(errors)
    for pid, text in edits.items():
        pasted[pid]['text'] = text
    r['points'] = [p for p in r['points'] if p['id'] not in dropped]
    new = []
    for text, is_first in added:
        pid = next_id(ctx.state, 'point', 'pt')
        r['points'].append({'id': pid, 'text': text})
        new.append(pid)
        if is_first:
            first.append(pid)
    r['first'] = list(dict.fromkeys(first))
    r['observed'].pop(command, None)
    r['pending'] = None
    ctx.log('pass', command=command, changes=len(edits) + len(dropped) + len(new), questions=[*edits, *dropped], added=new,
            origin=origin, summary=report['summary'].strip(), kind='pre-pass', first=r['first'], verdict=report.get('verdict'))
    return 'collect'
