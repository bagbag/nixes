"""The text printed before a dialog."""
from __future__ import annotations

from .base import TITLE_MAX, cut
from .engine import Context, by_id


# The text printed before a dialog (r24-q99): rendered from the question data, which owns the format. The console prints it as a
# system notice right before the dialog (the model never reads it); Codex has no console, so its ask text carries it.

def lean_line(q: dict) -> list[str]:
    """What a lean recommendation depends on, under its heading; a strong one's + line is its reason (r31-q147)."""
    if q.get('strength') != 'lean':
        return []
    because = q.get('leanBecause') or {}
    return [f"{'Unverified' if because.get('cause') == 'evidence' else 'Your call'}: {because.get('detail')}",
            *([f"What would change it: {because['flipsIf']}"] if because.get('flipsIf') else [])]


def options_text(q: dict) -> str:
    """The recommended option first (`Recommended (<strength>): <label>`), each option a bold heading with For and Against bullets, a
    blank line between options (r30-q141, r32-q150; a leading `+` renders as a bullet, so the words tell them apart)."""
    shown = [o for o in q['options'] if 'for' in o or 'against' in o]
    best = next((o for o in shown if o['label'] == q.get('recommendation')), None) if q.get('strength') else None
    blocks = []
    for o in [*([best] if best else []), *(o for o in shown if o is not best)]:
        head = [f"**Recommended ({q['strength']}): {o['label']}**", *lean_line(q)] if o is best else [f"**{o['label']}**"]
        blocks.append('\n'.join([*head, f"- For: {o.get('for', '')}", f"- Against: {o.get('against', '')}"]))
    return '\n\n'.join(blocks)


def dropped_text(q: dict) -> str:
    """The ideas the options pass dropped, one line each, under the options."""
    found = q.get('explored')
    return '\n'.join(f"- Dropped: {x['idea']} - {x['why']}" for x in found if x['verdict'] == 'dropped') if isinstance(found, list) else ''


def settled_lines(ctx: Context, q: dict) -> list[str]:
    """One line per item a rule question settles: its id and title, from the round's items and pasted points."""
    r = ctx.round
    titles = {item['id']: item.get('title', '') for item in r['items']} | {p['id']: p['text'] for p in r['points']}
    return [f"- {key}: {cut(titles.get(key, ''), TITLE_MAX)}".rstrip(': ') for key in q.get('settles') or []]


def ruling_line(x: dict) -> str:
    """A ruling with all its disclosure fields: the record keeps them."""
    return f"{x['ruling'].strip()} Why: {x['why'].strip()} Alternative: {x['alternative'].strip()} Fails: {x['fails'].strip()} Evidence: {x['evidence'].strip()}"


def ruling_block(x: dict, record: str = '') -> str:
    """A ruling as printed: the ruling, why it is mine, the alternative and why not, without the evidence (r29-q136); `record`: its release record."""
    return '\n'.join([f"**My ruling:** {x['ruling'].strip()}" + (f' ({record})' if record else ''),
                      f"- Why: {x['why'].strip()}", f"- Instead: {x['alternative'].strip()}", f"- Why not: {x['fails'].strip()}"])


def prior_rulings_text(q: dict) -> str:
    """The earlier rulings as printed: how many held, and each that fails; the record keeps every line (r34-q163)."""
    prior = q.get('priorRulings') or []
    if not prior:
        return ''
    fails = [f"- Fails: {x['ruling'].strip()} - {x['why'].strip()}" for x in prior if x['verdict'] == 'fails']
    return '\n'.join([f'{len(prior) - len(fails)} held.', *fails])


def question_parts(ctx: Context, q: dict) -> dict[str, str]:
    """The printed parts of a question by name, in print order (empty and absent parts left out)."""
    if ctx.round['protocol'] == 'release' and q['kind'] == 'confirm-own-rulings':
        return approval_parts(ctx)
    parts = {
        'problem': q.get('problem') or '', 'cases': q.get('cases') or '',
        'settles': '\n'.join(settled_lines(ctx, q)), 'premises': (q.get('premises') or '').strip(),
        'options': options_text(q), 'dropped': dropped_text(q),
        'rulings': '\n\n'.join(ruling_block(x) for x in q.get('rulings') or []),
        'priorRulings': prior_rulings_text(q),
        'note': (q.get('note') or '').strip(),
    }
    return {name: text for name, text in parts.items() if text}


PART_TITLES = {'problem': 'Problem', 'cases': 'Cases', 'settles': 'Settles', 'premises': 'Premises', 'note': 'Note', 'priorRulings': 'Earlier rulings',
               'corrections': 'Corrections', 'boardCheck': 'Board check'}
LIST_PARTS = ('settles', 'corrections', 'boardCheck')  # parts printed one line per entry
SELF_TITLED = ('options', 'dropped', 'rulings')  # parts whose lines say what they are (`Recommended:`, `Dropped:`, `My ruling:`)


def part_block(name: str, text: str) -> str:
    return text if name in SELF_TITLED else f'{PART_TITLES[name]}:' + ('\n' if name in LIST_PARTS else ' ') + text


def approval_parts(ctx: Context) -> dict[str, str]:
    """What the release's reports hold for the approval: corrections, the board check, own rulings (r24-q99)."""
    r = ctx.round
    corrections = [f"- {rec['id']} revised: {rec['change']}" for rec in r['set'] if rec['state'] == 'revised'] \
        + [f"- {rec['id']} left the set: {rec['reason']}" for rec in r['set'] if rec['state'] in ('dropped', 'changed')]
    board = [f"- {sup['old']} superseded by {sup['new']}" + (f" (rule: {sup['partial']})" if sup['partial'] is not None else '')
             for sup in r['supersedes']]
    board += [f"- {question} closes, answered by {', '.join(recs)}" for question, recs in r['closes'].items()]
    board += [f"- {rid} {name}: {row['item']}: {row['action']}" for rid, classes in (r.get('checks') or {}).items()
              for name, rows in classes.items() if rows != 'none' for row in rows
              if not (name == 'answers' and row['action'] == 'answered: close')]
    rulings = [ruling_block(x, f"{x['record']}, {'sure' if x['sure'] else 'unsure'}") for x in r['rulings'] or []]
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
        mark = f" (changed: {', '.join(PART_TITLES.get(name, name).lower() for name in changed)})" if changed else ''
        title = (f'{index + 1}. ' if len(chosen) > 1 else '') + q['title'] + mark
        blocks.append('\n\n'.join([f'**{title}**', *(part_block(name, text) for name, text in parts.items())]))
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
