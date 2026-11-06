"""Read views: show, status, history, the log and the step output."""
from __future__ import annotations

import contextlib
import json
import re
from datetime import datetime, timezone

from .base import CHECK_CAP, VERSION, cut, plural
from .session import state_root
from .store import Store
from .engine import Context, PROTOCOLS, by_id, fail
from .record import release_next
from .check import options_ids, pending_view, rescope_ids
from .collect import candidates


# Views

def progress(ctx: Context) -> dict:
    """What the console says about the step: Collect's open items and points, Select's candidates, the selection."""
    r = ctx.round
    keys = [i['id'] for i in r['items']] + [p['id'] for p in r['points']]
    return {'items': len(r['items']), 'points': len(r['points']),
            'classified': sum(1 for key in keys if key in r['classes']),
            'candidates': len(candidates(ctx)) if r['step'] == 'select' else None,
            'selected': list(r['selected'])}


def batch_number(marker: str | None) -> str:
    """`round:r6:4` → `4`: the Log and the headline are per round."""
    return (marker or '?').rsplit(':', 1)[-1]


def pass_words(e: dict) -> str:
    """`q3, q5 changed`, `no change`."""
    ids, added, changes = e.get('questions'), e.get('added'), e.get('changes') or 0
    parts = [f"{', '.join(ids)} changed"] if ids else []
    parts += [f"{', '.join(added)} added"] if added else []
    return ', '.join(parts) if parts else f'{changes} changes' if changes else 'no change'


def classified_words(e: dict) -> str:
    tally = e.get('classes') or {}
    return f"classified {plural(sum(tally.values()), 'point')}" + (': ' + ', '.join(f'{n} {name}' for name, n in tally.items()) if tally else '')


NO_CHANGE = re.compile(r'^\s*no changes?\b[:.]?\s*', re.IGNORECASE)


def pass_label(e: dict) -> str:
    """`ground`, `step-back (path)`, `ground (lean q39 q40)`: the pass and, when it ran as one of the sequence's
    scoped or named kinds, which, with the question or record ids it was scoped to."""
    detail = ' '.join(filter(None, [e.get('kind'), *(e.get('scoped') or [])]))
    return f"{e.get('command')} ({detail})" if detail else str(e.get('command'))


def log_text(event: dict) -> str | None:
    """One history event in plain words for the console's log, or None for events it leaves out."""
    e, kind = event, event['event']
    ids = lambda key: ', '.join(e.get(key) or []) or 'none'
    said = NO_CHANGE.sub('', e['summary']) if e.get('summary') else ''  # the headline says whether anything changed
    summary = f': {cut(said, 90)}' if said else ''
    return {
        'start': 'release started' if e.get('protocol') == 'release' else 'round started',
        'rechecked': f"re-check: {e.get('unchanged')} unchanged" + (f", {ids('changed')} changed" if e.get('changed') else ''),
        'record-dropped': f"dropped {e.get('record')}: {(e.get('reason') or '')[:80]}",
        'record-revised': f"revised {e.get('record')}: {(e.get('reason') or '')[:80]}",
        'release-stopped': f"stopped: {(e.get('reason') or '')[:90]}",
        'board-checked': f"board check: {plural(e.get('supersedes') or 0, 'supersede')}, {plural(len(e.get('closes') or []), 'answered question')}",
        'own-rulings': f"own rulings: {e.get('rulings')}, {e.get('unsure')} unsure",
        'approval-asked': 'approval asked' + (f": {cut('; '.join(e['reasons']), 90)}" if isinstance(e.get('reasons'), list) and e['reasons'] else ''), 'approved': f"approved ({e.get('origin')}, {e.get('how')})",
        'stamped': f"/release-round ({e.get('origin')}): approves if the checks hold",
        'owners-checked': f"owners checked: {plural(e.get('written') or 0, 'written path')}",
        # a clean release without closes is "released <ids>" (release-done) alone
        'board-release': f"board release {ids('records')}" + (f" closing {ids('closes')}" if e.get('closes') else '') + (f": exit {e.get('exit')}" if e.get('exit') else '')
        if e.get('exit') or e.get('closes') else None,
        'superseded': f"superseded {e.get('old')} by {e.get('new')}", 'release-done': f"released {ids('records')}", 'selected': f"selected {ids('selected')}", 'staged': f"staged {ids('questions')}",
        'related': f"{e.get('question')}: {len(e.get('hits') or [])} related items",
        'pass': f"{pass_label(e)}: {pass_words(e)}{summary}", 'classified': classified_words(e),
        'asked': f"asked {ids('questions')}", 'answered': f"answered {ids('questions')} ({e.get('origin')})" + (f"; typed {ids('typed')}" if e.get('typed') else ''),
        'decline': f"batch {batch_number(e.get('marker'))} {e.get('reason')}", 'restart': f"restarted {ids('questions')}",
        'continued': f"released {ids('questions')} from held: checked again before the next batch",
        'cap': f"cycle cap at {e.get('cycle')}" + (': the questions park' if e.get('away') else ''), 'cap-decision': f"cap: {e.get('choice')}",
        'settled': f"away: acted {ids('acted')}, parked {ids('parked')}", 'parked': f"parked {e.get('question')} → {e.get('board')}",
        'batch-withdrawn': f"batch {batch_number(e.get('marker'))} withdrawn for updates", 'recorded': f"recorded {e.get('question')} → {e.get('board') or 'file'}",
        'deferred': f"deferred {e.get('question')}", 'released': f"released {ids('items')}",
        'refused': f"refused {e.get('verb')}: {(e.get('error') or '')[:90]}", 'removed': f"removed {e.get('question')}",
        'edited': f"edited {ids('questions')} (your words)",
        'checking': f"{ids('questions')}: " + ('challenge-rulings on the raised strong mark' if e.get('kind') == 'raised'
                                               else 'checked before they are asked (added or re-recommended)'),
        'closed': 'release closed' if e.get('protocol') == 'release' else 'round closed', 'abandoned': f"abandoned at {e.get('step')}",
    }.get(kind)


def recorded_line(events: list[dict]) -> str:
    """Consecutive `recorded` events as one line: `recorded q39, q40 → fx-1, fx-2`, or `→ files` when none reached the board."""
    targets = list(dict.fromkeys(e.get('board') or 'file' for e in events))
    return f"recorded {', '.join(e.get('question') for e in events)} → " + ('files' if targets == ['file'] else ', '.join(targets))


def round_log(ctx: Context) -> list[dict]:
    """The whole round's history in the Log's words (the console shows the last lines and folds the rest)."""
    lines, run = [], []
    path = ctx.store.dir / 'history.jsonl'

    def moment(event: dict) -> str:
        return datetime.strptime(event['at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).astimezone().strftime('%H:%M')

    def flush() -> None:
        if run:
            lines.append({'at': moment(run[0]), 'text': recorded_line(run)})
            run.clear()

    for raw in path.read_text(encoding='utf-8').splitlines() if path.is_file() else []:
        with contextlib.suppress(ValueError):
            event = json.loads(raw)
            if event.get('round') != ctx.round['id']:
                continue
            if event['event'] == 'recorded':
                run.append(event)
            elif text := log_text(event):
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
             **({'rounds': [one for one in proposal.get('rounds') or [] if isinstance(one, dict)]} if isinstance(proposal, dict) else {})}
    return found or None


def show_json(ctx: Context) -> dict:
    r = ctx.round
    base = {'version': VERSION, 'session': ctx.store.session, 'protocol': None, 'round': None, 'title': None,
            'summary': None, 'step': None,
            'check': None, 'pending': None, 'questions': [], 'batch': None, 'counts': ctx.state.get('counts'),
            'progress': None, 'log': [], 'records': [], 'stopped': stopped_view(r), 'next': None}
    if not r or r['step'] == 'closed':  # contract-rulings R-B3: no open round
        return {**base, 'next': next_run(ctx)}
    check = r['check']
    return {**base, 'protocol': r['protocol'], 'round': r['id'], 'title': r.get('title'), 'summary': r.get('summary'),
            'step': r['step'],
            'check': {'cycle': check.get('cycle', 0), 'cap': check.get('cap', CHECK_CAP), 'last': check.get('last', {})}
            if check.get('expect') else None,
            'pending': pending_view(ctx),
            'questions': [{'id': q['id'], 'board': q['board'], 'text': q['text'], 'title': q['title'], 'kind': q['kind'],
                           'status': q['status'], 'waitsOn': q['waitsOn'], 'settles': q.get('settles') or [], 'overlaps': q['overlaps'],
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
    if not r:
        return 'No round in this session.'
    check = r['check']
    noun = 'Release' if r['protocol'] == 'release' else 'Round'
    lines = [f"# {noun} {r['id']}{' · ' + r['title'] if r.get('title') else ''} · {r['step']}", '',
             *([r['summary'], ''] if r.get('summary') else [])]
    if r.get('set'):
        lines += ['| record | state | title |', '|---|---|---|',
                  *(f"| {rec['id']} | {rec['state']}{' (' + rec['reason'] + ')' if rec['reason'] else ''} | {rec['title']} |"
                    for rec in r['set']), '']
    if check.get('expect'):
        last = ', '.join(f"{k} {v['changes']} ({v['origin']})" for k, v in check.get('last', {}).items()) or 'none yet'
        lines.append(f"Check cycle {check['cycle']}/{check['cap']}; last passes: {last}.")
    if r['pending']:
        lines.append(f"Pending: /{r['pending']['command']} ({r['pending']['id']}).")
    if r['batch']:
        lines.append(f"Batch out: {r['batch']['marker']}.")
    lines += ['', '| id | board | status | kind | question | answer |', '|---|---|---|---|---|---|']
    for q in r['questions']:
        overlap = ''.join(f" (overlaps {h['id']}: {h['outcome'] or 'open'})" for h in q['overlaps'])
        lines.append(f"| {q['id']} | {q['board'] or 'draft'} | {q['status']}"
                     + (f" on {', '.join(q['waitsOn'])}" if q['status'] == 'held' else '')
                     + f" | {q['kind']} | {q['text']}{overlap} | {q['answer'] or ''} |")
    counts = ctx.state.get('counts')
    if counts:
        lines += ['', 'Board: ' + ', '.join(f'{k} {v}' for k, v in counts.items())]
    if r['step'] != 'closed':
        lines += ['', '## Next step', '', instructions(ctx)]  # recovery after compaction: the step's instructions
    return '\n'.join(lines)


def show_questions(ctx: Context, ids: list[str]) -> str:
    """The named questions whole (r23-q89): what `show` leaves out, for a model that lost them to a compaction."""
    if not ctx.round:
        fail('no round in this session')
    return '\n\n'.join(json.dumps({key: value for key, value in by_id(ctx, qid).items() if value not in (None, [], '') and key != 'printed'},
                                   indent=1, ensure_ascii=False) for qid in ids)


def status_line(ctx: Context) -> str:
    r = ctx.round
    if not r or r['step'] == 'closed':
        return 'protocol: no open round'
    tally = {}
    for q in r['questions']:
        tally[q['status']] = tally.get(q['status'], 0) + 1
    parts = [f"{'release' if r['protocol'] == 'release' else 'round'} {r['id']}", r['step']]
    if r['step'] == 'check' and r['check'].get('expect'):
        parts[-1] += f" {r['check']['cycle']}/{r['check']['cap']}"
    if r['pending']:
        parts.append(f"pending /{r['pending']['command']} ({r['pending']['id']})")
    if r['batch']:
        parts.append(f"batch {r['batch']['marker']} out")
    parts.append('questions ' + (', '.join(f'{n} {s}' for s, n in tally.items()) or 'none'))
    if r.get('set'):
        states = {}
        for rec in r['set']:
            states[rec['state']] = states.get(rec['state'], 0) + 1
        parts.append('records ' + ', '.join(f'{n} {state}' for state, n in states.items()))
    parts.append("`protocol show` repeats the step's instructions")
    return 'protocol: ' + ' · '.join(parts)


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
        return 'no protocol history'
    rows = []
    for (session, round_id), s in rounds.items():
        def counts(table):
            return ', '.join(f'{k} {v}' for k, v in sorted(table.items())) or 'none'
        rows.append(f"{session} {round_id}: passes {counts(s['passes'])}; changed something {counts(s['changed'])}; "
                    f"answers {counts(s['answers'])}; declines {s['declines']}; "
                    f"restarts {'; '.join(s['restarts']) or 'none'}; cap {', '.join(s['caps']) or 'not reached'}")
    return '\n'.join(rows)


def next_words(ctx: Context) -> str | None:
    """Where the round goes next, in the headline's words; None once it closed."""
    r = ctx.round
    if r['step'] == 'closed':
        if r['protocol'] == 'release':
            return f"a round on {', '.join(r['stopped']['ids'])}" if r.get('stopped') else None
        return 'release (/release-round or ask)' if release_next(ctx) else None
    if r['batch']:
        if r['batch']['cap']:
            return 'your call on the cycle cap'
        waits = not ctx.codex  # Claude: the lead's turn ends; the console prints the parts, if any, and opens the dialog
        return f"{('the console to print, then ' if r['batch'].get('notice') else 'the console to open the dialog, then ') if waits else ''}your answers (batch {batch_number(r['batch']['marker'])})"
    if r['step'] == 'check':
        check = r['check']
        if check.get('paused'):
            return 'check paused; `protocol resume` continues'
        if not ctx.codex:
            return None  # the pass sequence stays out of what Claude's model reads; the pane shows it (r34-q165)
        if check.get('challenge'):
            return 'challenge-rulings ' + ('after the last answer' if check['challenge']['kind'] == 'answers' else 'on the raised strong ' + ' '.join(check['challenge']['ids']))
        if check['expect'] == 'challenge-rulings':
            return 'challenge-rulings, last before asking'
        return f"{check['expect']}{', path pass' + (' ' + ' '.join(rescope_ids(ctx)) if check.get('pathScoped') else '') if check.get('pathNow') else ', options pass' + (' ' + ' '.join(options_ids(ctx, rescope_ids(ctx))) if check.get('optionsScoped') else '') if check.get('optionsNow') else ', refine pass' + (' ' + ' '.join(rescope_ids(ctx)) if check.get('refineScoped') else '') if check.get('refineNow') else ', lean pass' if check.get('focusing') else ''}, cycle {check['cycle']}/{check['cap']}"
    if r['step'] == 'scoped' and r['pending']:
        return f"{r['pending']['command']} pass on the revised {r['pending']['args']}"
    if r['step'] == 'collect':
        return 'classify ' + ' and '.join(plural(len(r[key]), key[:-1]) for key in ('points', 'items') if r[key])
    return {'select': 'select', 'stage': 'stage the questions', 'related': 'resolve related items',
            'ask': 'act or park per question' if ctx.away else 'the next batch', 'record': 'record the answers', 'recheck': 're-check the records',
            'board-check': 'the board check', 'own-rulings': 'your own rulings', 'owners': 'owner writes',
            'release': 'rerun the release'}.get(r['step'], r['step'])


def headline(ctx: Context) -> str:
    """The output's first line, which the console shows as the call's chat row: this call's events in the Log's
    words (log_text), then where the round goes next."""
    words, recorded = [], []
    for event in ctx.store.pending:
        if event['event'] == 'recorded':
            if not recorded:
                words.append(None)  # keeps the place of the merged "recorded q1, q2"
            recorded.append(event['question'])
        elif text := log_text(event):
            words.append(text)
    words = [f"recorded {', '.join(recorded)}" if word is None else word for word in words]
    upcoming = next_words(ctx)
    r = ctx.round
    label = f"{r['id']} release · {r['title']}" if r['protocol'] == 'release' else r['id']  # `r5 release · the session's records`
    return ' · '.join([label, *words, *([f'next: {upcoming}'] if upcoming else [])])


def instructions(ctx: Context) -> str:
    r = ctx.round
    text = PROTOCOLS[r['protocol']].steps[r['step']].text(ctx)
    return '\n'.join([headline(ctx), *ctx.messages, text])
