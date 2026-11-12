"""Read views: show, status, history, the log and the step output."""
from __future__ import annotations

import contextlib
import json
from datetime import datetime, timezone

from .base import CHECK_CAP, VERSION
from . import words
from .session import state_root
from .store import Store
from .engine import Context, PROTOCOLS, by_id, fail
from .record import release_next
from .check import options_ids, pending_view, rescope_ids
from .collect import candidates
from .seeds import proposal_rows


# Views

def progress(ctx: Context) -> dict:
    """What the console says about the step: Collect's open items and points, Select's candidates, the selection."""
    r = ctx.round
    keys = [i['id'] for i in r['items']] + [p['id'] for p in r['points']]
    return {'items': len(r['items']), 'points': len(r['points']),
            'classified': sum(1 for key in keys if key in r['classes']),
            'candidates': len(candidates(ctx)) if r['step'] == 'select' else None,
            'selected': list(r['selected'])}


def round_log(ctx: Context) -> list[dict]:
    """The whole round's history in the Log's words (the console shows the last lines and folds the rest)."""
    lines, run = [], []
    path = ctx.store.dir / 'history.jsonl'

    def moment(event: dict) -> str:
        return datetime.strptime(event['at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).astimezone().strftime('%H:%M')

    def flush() -> None:
        if run:
            lines.append({'at': moment(run[0]), 'text': words.recorded_line(run)})
            run.clear()

    for raw in path.read_text(encoding='utf-8').splitlines() if path.is_file() else []:
        with contextlib.suppress(ValueError):
            event = json.loads(raw)
            if event.get('round') != ctx.round['id']:
                continue
            if event['event'] == 'recorded':
                run.append(event)
            elif text := words.log_text(event):
                flush()
                lines.append({'at': moment(event), 'text': text})
    flush()
    return lines


def stopped_view(r: dict | None) -> dict | None:
    """A stopped release stays visible after it closed, until the next run starts: its records wait for a round."""
    stopped = (r or {}).get('stopped') if (r or {}).get('step') == 'closed' else None
    return {'run': r['id'], 'reason': stopped['reason'], 'ids': stopped['ids']} if stopped else None


def next_run(ctx: Context) -> dict | None:
    """What follows a close: the pending release and the model's stored proposal (`protocol next --set`)."""
    proposal = ctx.state.get('proposal')
    release = release_next(ctx)
    found = {**({'release': release} if release else {}),
             **({'rounds': proposal_rows(proposal) or []} if isinstance(proposal, dict) else {})}
    return found or None


def show_json(ctx: Context) -> dict:
    r = ctx.round
    base = {'version': VERSION, 'session': ctx.store.session, 'protocol': None, 'round': None, 'title': None,
            'summary': None, 'subject': None, 'step': None,
            'check': None, 'pending': None, 'questions': [], 'batch': None, 'counts': ctx.state.get('counts'),
            'progress': None, 'log': [], 'records': [], 'stopped': stopped_view(r), 'next': None}
    if not r or r['step'] == 'closed':  # contract-rulings R-B3: no open round
        return {**base, 'next': next_run(ctx)}
    check = r['check']
    return {**base, 'protocol': r['protocol'], 'round': r['id'], 'title': r.get('title'), 'summary': r.get('summary'),
            'subject': r.get('subject'), 'step': r['step'],
            'check': {'cycle': check.get('cycle', 0), 'cap': check.get('cap', CHECK_CAP), 'last': check.get('last', {})}
            if check.get('expect') else None,
            'pending': pending_view(ctx),
            'questions': [{'id': q['id'], 'board': q['board'], 'text': q['text'], 'title': q['title'], 'kind': q['kind'],
                           'status': q['status'], 'waitsOn': q['waitsOn'],
                           'waitsFor': q.get('waitsFor'), 'settles': q.get('settles') or [], 'overlaps': q['overlaps'],
                           'answer': q['answer'],
                           'answeredAt': q.get('answeredAt') if q['answer'] is not None else None,
                           'changedBy': (r.get('lastPass') or {}).get('pass') if q['id'] in (r.get('lastPass') or {}).get('questions', []) else None,
                           'recommendation': q.get('recommendation'), 'strength': q.get('strength'),
                           'leanBecause': q.get('leanBecause'), 'strongBecause': q.get('strongBecause')}
                          for q in r['questions']],
            'batch': {'marker': r['batch']['marker'], 'questions': r['batch']['questions'], 'notice': r['batch'].get('notice') or ''}
            if r['batch'] else None,
            'progress': progress(ctx) if r['protocol'] == 'round' else None, 'log': round_log(ctx),
            # a release run: its records with their state (set, dropped, changed, released) and reason
            'records': [{'id': rec['id'], 'title': rec['title'], 'state': rec['state'], 'reason': rec['reason']}
                        for rec in r.get('set') or []],
            'stopped': None, 'next': None}


def show_markdown(ctx: Context) -> str:
    r = ctx.round
    # recovery after compaction: the step's instructions
    return words.show_markdown(r, ctx.state.get('counts'), instructions(ctx) if r and r['step'] != 'closed' else None)


def show_questions(ctx: Context, ids: list[str]) -> str:
    """The named questions whole (r23-q89): what `show` leaves out, for a model that lost them to a compaction."""
    if not ctx.round:
        fail('no round in this session')
    return '\n\n'.join(json.dumps({key: value for key, value in by_id(ctx, qid).items() if value not in (None, [], '') and key != 'printed'},
                                   indent=1, ensure_ascii=False) for qid in ids)


def status_line(ctx: Context) -> str:
    return words.status_line(ctx.round)


def history_events(store: Store, everywhere: bool) -> list[dict]:
    files = sorted(state_root().glob('*.protocol/history.jsonl')) if everywhere else [store.dir / 'history.jsonl']
    events = []
    for path in files:
        with contextlib.suppress(FileNotFoundError):
            events += [json.loads(row) for row in path.read_text(encoding='utf-8').splitlines() if row.strip()]
    return events


def history_text(events: list[dict]) -> str:
    rounds: dict[tuple, dict] = {}
    for event in events:
        key = (event.get('session'), event.get('round'))
        if key[1] is None:
            continue
        summary = rounds.setdefault(key, {'passes': {}, 'changed': {}, 'restarts': [], 'declines': 0, 'caps': [],
                                          'answers': {}})
        kind = event['event']
        if kind == 'pass':
            origin = event.get('origin', 'model')
            summary['passes'][origin] = summary['passes'].get(origin, 0) + 1
            if event.get('changes'):
                summary['changed'][origin] = summary['changed'].get(origin, 0) + 1
        elif kind == 'restart':
            summary['restarts'].append(f"{','.join(event.get('questions', []))}" + (f" ({event['reason']})" if event.get('reason') else ''))
        elif kind == 'decline':
            summary['declines'] += 1
        elif kind == 'cap-decision':
            summary['caps'].append(event.get('choice'))
        elif kind == 'answered':
            origin = event.get('origin')
            summary['answers'][origin] = summary['answers'].get(origin, 0) + len(event.get('questions', []))
    if not rounds:
        return words.history_none()
    return '\n'.join(words.history_row(session, round_id, s) for (session, round_id), s in rounds.items())


def next_words(ctx: Context) -> str | None:
    """Where the round goes next, in the headline's words; None once it closed."""
    r = ctx.round
    if r['step'] == 'closed':
        if r['protocol'] == 'release':
            return words.next_round_on(r['stopped']['ids']) if r.get('stopped') else None
        return words.NEXT_RELEASE if release_next(ctx) else None
    if r['batch']:
        if r['batch']['cap']:
            return words.NEXT_CAP
        # Claude: the lead's turn ends; the console prints the parts, if any, and opens the dialog
        return words.next_answers(not ctx.codex, bool(r['batch'].get('notice')), words.batch_number(r['batch']['marker']))
    if r['step'] == 'check':
        check = r['check']
        if check.get('paused'):
            return words.NEXT_PAUSED
        if not ctx.codex:
            return None  # the pass sequence stays out of what Claude's model reads; the pane shows it (r34-q165)
        if check.get('challenge'):
            return words.next_challenge(check['challenge']['kind'], check['challenge']['ids'])
        if check['expect'] == 'challenge-rulings':
            return words.NEXT_CHALLENGE_LAST
        phase = (words.next_phase('path', rescope_ids(ctx) if check.get('pathScoped') else None) if check.get('pathNow') else
                 words.next_phase('options', options_ids(ctx, rescope_ids(ctx)) if check.get('optionsScoped') else None) if check.get('optionsNow') else
                 words.next_phase('refine', rescope_ids(ctx) if check.get('refineScoped') else None) if check.get('refineNow') else
                 words.NEXT_LEAN if check.get('focusing') else '')
        return words.next_check(check['expect'], phase, check['cycle'], check['cap'])
    if r['step'] == 'scoped' and r['pending']:
        return words.next_scoped(r['pending']['command'], r['pending']['args'])
    if r['step'] == 'collect':
        return words.next_classify(len(r['points']), len(r['items']))
    if r['step'] == 'ask' and ctx.away:
        return words.NEXT_ASK_AWAY
    return words.NEXT_STEPS.get(r['step'], r['step'])


def headline(ctx: Context) -> str:
    """The output's first line, which the console shows as the call's chat row: this call's events in the Log's
    words (words.log_text), then where the round goes next."""
    said, recorded = [], []
    for event in [*ctx.store.written, *ctx.store.pending]:
        if event['event'] == 'recorded':
            if not recorded:
                said.append(None)  # keeps the place of the merged "recorded q1, q2"
            recorded.append(event['question'])
        elif text := words.log_text(event):
            said.append(text)
    said = [f"recorded {', '.join(recorded)}" if word is None else word for word in said]
    r = ctx.round
    return words.headline(words.headline_label(r['id'], r['protocol'] == 'release', r['title'] if r['protocol'] == 'release' else None), said, next_words(ctx))


def instructions(ctx: Context) -> str:
    r = ctx.round
    text = PROTOCOLS[r['protocol']].steps[r['step']].text(ctx)
    return '\n'.join([headline(ctx), *ctx.messages, text])
