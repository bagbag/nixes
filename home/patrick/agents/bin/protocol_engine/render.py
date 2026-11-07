"""The text printed before a dialog."""
from __future__ import annotations

from . import words
from .engine import Context, by_id


# The text printed before a dialog (r24-q99): rendered from the question data, which owns the format. The console prints it as a
# system notice right before the dialog (the model never reads it); Codex has no console, so its ask text carries it.

def settled_lines(ctx: Context, q: dict) -> list[str]:
    """One line per item a rule question settles: its id and title, from the round's items and pasted points."""
    r = ctx.round
    titles = {item['id']: item.get('title', '') for item in r['items']} | {p['id']: p['text'] for p in r['points']}
    return [words.settled_line(key, titles.get(key, '')) for key in q.get('settles') or []]


def question_parts(ctx: Context, q: dict) -> dict[str, str]:
    """The printed parts of a question by name, in print order (empty and absent parts left out)."""
    if ctx.round['protocol'] == 'release' and q['kind'] == 'confirm-own-rulings':
        return approval_parts(ctx)
    parts = {
        'problem': q.get('problem') or '', 'cases': q.get('cases') or '',
        'settles': '\n'.join(settled_lines(ctx, q)), 'premises': (q.get('premises') or '').strip(),
        'options': words.options_text(q), 'dropped': words.dropped_text(q),
        'rulings': '\n\n'.join(words.ruling_block(x) for x in q.get('rulings') or []),
        'priorRulings': words.prior_rulings_text(q),
        'note': (q.get('note') or '').strip(),
    }
    return {name: text for name, text in parts.items() if text}


def approval_parts(ctx: Context) -> dict[str, str]:
    """What the release's reports hold for the approval: corrections, the board check, own rulings (r24-q99)."""
    r = ctx.round
    corrections = [words.correction_revised(rec) for rec in r['set'] if rec['state'] == 'revised'] \
        + [words.correction_left(rec) for rec in r['set'] if rec['state'] in ('dropped', 'changed')]
    board = [words.check_superseded(sup) for sup in r['supersedes']]
    board += [words.check_closes(question, recs) for question, recs in r['closes'].items()]
    board += [words.check_hit(rid, name, row) for rid, classes in (r.get('checks') or {}).items()
              for name, rows in classes.items() if rows != 'none' for row in rows
              if not (name == 'answers' and row['action'] == 'answered: close')]
    rulings = [words.ruling_block(x, words.ruling_record(x)) for x in r['rulings'] or []]
    parts = {'corrections': '\n'.join(corrections), 'boardCheck': '\n'.join(board), 'rulings': '\n\n'.join(rulings)}
    return {name: text for name, text in parts.items() if text}


QUESTION_RULE = '\n\n---\n\n'  # a rule between questions, so each stands clear of the next (r32-q150)


def render_batch(ctx: Context, chosen: list[dict]) -> str:
    """The text for a batch: the round's overview line once, then per question all its parts, numbered like the dialog, so
    the text sits above every dialog however much scrolled by (r36-q195). A question the person saw before names the parts
    that differ from what `batch_seen` recorded they saw (r36-q196); a batch withdrawn before its dialog opened was never seen."""
    r = ctx.round
    blocks = []
    for index, q in enumerate(chosen):
        parts, before = question_parts(ctx, q), q.get('printed') or {}
        if not parts:
            continue
        changed = [name for name in (*parts, *(name for name in before if name not in parts)) if before and parts.get(name) != before.get(name)]
        mark = words.changed_mark(changed) if changed else ''
        title = words.batch_title(index, len(chosen), q['title'], mark)
        blocks.append('\n\n'.join([f'**{title}**', *(words.part_block(name, text) for name, text in parts.items())]))
    overview = (r.get('overview') or '').strip()
    if blocks and overview and r.get('overviewPrinted') != overview:
        blocks.insert(0, overview)
    return QUESTION_RULE.join(blocks)


def batch_seen(ctx: Context, batch: dict) -> None:
    """A dialog for the batch came back: the person saw what the batch printed."""
    for qid in batch['ids']:
        q = by_id(ctx, qid)
        q['printed'] = question_parts(ctx, q)
    if batch.get('notice') and ctx.round.get('overview'):
        ctx.round['overviewPrinted'] = ctx.round['overview'].strip()
