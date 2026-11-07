"""Write verbs relayed by the console (and the Codex model-reported path)."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone

from .base import CAP_CHOICES, CHECK_CAP, DROP_KINDS, PRUNE_DAYS, THINK_MORE, VERB_ORIGINS, recommended_suffix, utcnow
from . import words
from .session import state_root
from .store import Store
from .engine import Context, by_id, fail, premise_status, questions, touch
from .questions import apply_updates
from .render import batch_seen
from .check import gate_ask, leave_check, next_cycle, nothing_to_check, rescope_check
from .ask import batch_back, hand_over, take_unchecked, unchecked


def require_origin(ctx: Context, verb: str, origin: str | None) -> None:
    allowed = VERB_ORIGINS.get(verb, ('model',))
    if origin is None and verb not in VERB_ORIGINS:
        return
    if origin not in allowed:
        fail(f"{verb}: origin {origin!r} is not accepted here (accepted: {', '.join(allowed)})")
    if origin == 'model-reported' and not ctx.codex:
        fail(f'{verb}: origin model-reported is the Codex path only; in Claude the console records the dialog, and '
             'an answer typed in chat goes through answer --origin chat with its quote')


def drop_report(ctx: Context, report: dict) -> None:
    """The console dropped a stale pass run or batch dialog: logged, and the pass's observed run goes, but only a run of that
    pass (a newer run of the same command stays)."""
    kind = report.get('kind')
    if kind not in DROP_KINDS:
        fail(f"dropped: `kind` must be one of {', '.join(DROP_KINDS)}")
    key = 'id' if kind == 'pass' else 'marker'
    ref = report.get(key)
    if not isinstance(ref, str) or not ref:
        fail(f'dropped: kind {kind} needs `{key}` in stdin')
    if ctx.round and kind == 'pass':
        observed = ctx.round['observed']
        for command in [c for c, run in observed.items() if run.get('pending') == ref]:
            del observed[command]
    ctx.log('dropped', kind=kind, **{key: ref})


def normalized(text: str) -> str:
    return ' '.join(str(text).split())


def chat_answer(ctx: Context, report: dict) -> str:
    """An answer the user typed in chat, mapped by the model: accepted only when its quote appears in a message the
    console relayed from the person after the question went out (a short "yes" from earlier must not count)."""
    qid, text, quote = report.get('question'), report.get('answer'), report.get('quote')
    if not all(isinstance(v, str) and v.strip() for v in (qid, text, quote)):
        fail('answer --origin chat: stdin needs "question" (an id), "answer" and "quote" (the user\'s exact words)')
    q = by_id(ctx, qid)
    if q['status'] not in ('ready', 'asked'):
        fail(f"answer --origin chat: {qid} is {q['status']}, not ready or asked")
    after = ctx.round['messages'][q.get('messagesBefore', 0):]
    if not any(normalized(quote) in normalized(message['text']) for message in after):
        fail('answer --origin chat: quote check failed: the quote appears in no message the user sent since the question '
             'went out')
    batch = ctx.round['batch']
    if batch and qid in batch['ids']:
        index = batch['ids'].index(qid)
        del batch['ids'][index], batch['questions'][index]
        if not batch['ids']:
            ctx.round['batch'] = None
    q.pop('typed', None)
    ctx.round.pop('reading', None)  # a chat answer is the model's reading
    q.update(status='answered', answer=text, origin='chat', quote=quote, answeredAt=utcnow())
    ctx.state['answers'][qid] = text
    touch(ctx, [qid])
    if ctx.round['protocol'] == 'round':
        ctx.round['check']['challenged'] = False  # the answer is news to the last challenge-rulings run
    ctx.log('answered', origin='chat', questions=[qid], quote=quote)
    if ctx.round['step'] == 'ask':
        ctx.go('ask')
    return words.chat_recorded(qid)


def recommended_index(q: dict) -> int | None:
    """Which option is recommended, by position: renaming its label (with `recommendation` following) is wording."""
    return next((i for i, o in enumerate(q['options']) if o['label'] == q.get('recommendation')), None)


def mark_unchecked(ctx: Context, before: dict[str, tuple]) -> None:
    """What an edit made unchecked (r13 q47, q48), kept out of the batches until hand_over checks it: a new question and a
    changed recommendation (the scoped check), a recommendation raised to strong (one challenge-rulings pass). Wording,
    options, premises, previews and a mark lowered to lean stay free: decide.md says edit applies the user's own words."""
    for qid in ctx.added:
        if by_id(ctx, qid)['status'] == 'draft':
            by_id(ctx, qid)['unchecked'] = 'scoped'
    for qid in ctx.applied:
        q = next((one for one in questions(ctx, 'draft', 'ready') if one['id'] == qid), None)
        if q is None or qid not in before:
            continue
        if recommended_index(q) != before[qid][0]:
            kind = 'scoped'
        elif q.get('strength') == 'strong' and before[qid][1] != 'strong' and q.get('unchecked') != 'scoped':
            kind = 'raised'
        else:
            continue
        q.update(status='draft', unchecked=kind)


def edit_round(ctx: Context, report: dict) -> str:
    """The user's requested change to the questions: the quote must appear in a message the console relayed (or a typed
    dialog text) in this round, also one sent before the questions went out (Codex has no relay: its quote is not checked).
    Changes apply without a pass and a batch that is out comes back and goes out again, except an edit that only adds
    questions, which leaves it out. A new question or a changed recommendation then gets the scoped check, a raise to strong one
    challenge-rulings pass, before it is asked (`mark_unchecked`): at the hand-over, or at once when nothing else waits.
    While recording, an edit that leaves a question unchecked hands the round back through the hand-over, and the challenge
    after the answers runs again once it is answered."""
    r = ctx.round
    if r['protocol'] != 'round' or r['step'] not in ('related', 'check', 'ask', 'record'):
        fail('edit applies to a round between Related and Record')
    if r['batch'] and r['batch']['cap']:
        fail('answer the cap question first')
    updates, quote = report.get('updates'), report.get('quote')
    if not isinstance(updates, list) or not updates or not isinstance(quote, str) or not quote.strip():
        fail('edit: stdin needs "updates" (per-question updates as in a pass report) and "quote" (the user\'s exact words asking for it)')
    if not ctx.codex and not any(normalized(quote) in normalized(message['text']) for message in r['messages']):
        fail('edit: quote check failed: the quote appears in no message the user sent in this round')
    if r['batch'] and not all(isinstance(u, dict) and 'id' not in u for u in updates):
        ctx.log('batch-withdrawn', marker=r['batch']['marker'], reason='edit')
        batch_back(ctx)
    for q in questions(ctx):
        q.pop('typed', None)
    r.pop('reading', None)
    before = {q['id']: (recommended_index(q), q.get('strength')) for q in questions(ctx)}
    apply_updates(ctx, updates)
    mark_unchecked(ctx, before)
    touched = list(dict.fromkeys([*ctx.applied, *ctx.added]))
    r['lastPass'] = {'pass': 'edit', 'questions': touched}  # rows read "↻ edit"
    ctx.log('edited', questions=touched, quote=quote)
    if r['step'] not in ('ask', 'record'):
        # Before Ask the check takes them: not started yet, it covers them; under way, a scoped check restarts it and a raise
        # re-arms the round's challenge-rulings.
        scoped, waiting = bool(unchecked(ctx, 'scoped')), take_unchecked(ctx)
        if waiting and r['check'].get('expect'):
            if scoped:
                rescope_check(ctx, waiting)
            else:
                r['check']['challenged'] = False
    if r['step'] == 'record' and unchecked(ctx):
        r['check']['challenged'] = False
        return hand_over(ctx)
    if r['step'] == 'check' and nothing_to_check(ctx):
        return leave_check(ctx)
    return r['step']


def open_batch(ctx: Context, marker) -> dict:
    r = ctx.round
    if not r or r['step'] == 'closed':
        fail('no open round')
    if not r['batch']:
        fail('no batch is out')
    if marker != r['batch']['marker']:
        fail(f"marker {marker!r} is not the issued batch {r['batch']['marker']}")
    return r['batch']


def decline(ctx: Context, report: dict, origin: str, reason: str) -> str:
    batch = open_batch(ctx, report.get('marker'))
    partial = report.get('partial') or {}
    if not isinstance(partial, dict):
        fail('`partial` must map question texts to answers, or be null')
    batch_seen(ctx, batch)
    batch_back(ctx)
    ctx.log('decline', marker=batch['marker'], origin=origin, reason=reason, partial=partial or None)
    if batch['cap']:
        ctx.round['check']['paused'] = True  # nothing decided: the loop waits for the user
    return words.declined_note(batch['marker'], reason, partial, batch['cap'])


def cap_decision(ctx: Context, answer: str, origin: str) -> str:
    choice = next((c for c in CAP_CHOICES if answer.strip().lower().startswith(c.lower())), None)
    ctx.round['batch'] = None
    check = ctx.round['check']
    ctx.log('cap-decision', choice=choice or answer, origin=origin)
    if choice is None:
        check['paused'] = True
        return words.cap_own_words(answer)
    if choice == 'Continue':
        check['cap'] = check['cycle'] + CHECK_CAP
        next_cycle(ctx)
        return words.CAP_CONTINUED
    if choice == 'Pause':
        check['paused'] = True
        return words.CAP_PAUSED
    check['askNow'] = True
    ctx.go(gate_ask(ctx))
    return words.CAP_ASK_NOW


def option_pick(q: dict, value: str) -> str | None:
    """The answer as the option label(s) it picks, the dialog's recommended mark removed; None for typed text."""
    labels = {o['label'] for o in q['options']}
    parts = [part.strip().removesuffix(recommended_suffix(q)) for part in (value.split(', ') if q['multiSelect'] else [value])]
    return ', '.join(parts) if value and all(part in labels for part in parts) else None


def typed_reply(report: dict, text: str, value: str) -> str:
    """What the person wrote instead of a pick: the typed text and a note on the question; a note alone counts as the reply
    (the console sends a note written with no pick as no answer plus the note)."""
    annotation = (report.get('annotations') or {}).get(text)
    note = str(annotation.get('notes') or '').strip() if isinstance(annotation, dict) else ''
    return '; '.join(part for part in (value, note) if part)


def answered_line(ctx: Context, batch: dict, report: dict) -> str:
    """What the person reads after a dialog (r36-q197): one row per question, numbered like the dialog, with its title and
    what became of it. Every dialog comes through here; a cap question has no record, so its text stands in for the title."""
    rows = []
    for index, shown in enumerate(batch['questions']):
        q = None if batch['cap'] else by_id(ctx, batch['ids'][index])
        value = ((report.get('answers') or {}).get(shown['question']) or '').strip()
        pick = option_pick(q, value) if q else value
        reply = typed_reply(report, shown['question'], value) if pick is None else ''
        if q and value == THINK_MORE and pick is None:
            outcome = words.ANSWER_THINK_MORE
        elif reply:
            outcome = words.answer_typed(reply)
        elif not value:
            outcome = words.ANSWER_NONE
        elif q and q.get('strength'):
            outcome = words.answer_pick(pick, pick == q['recommendation'])
        else:
            outcome = pick
        title = q['title'] if q else shown['question']
        rows.append(words.answered_row(index, len(batch['questions']), title, outcome))
    return words.answered_rows(rows)


def answer(ctx: Context, report: dict, origin: str) -> str:
    if origin == 'chat':
        return chat_answer(ctx, report)
    if report.get('afkTimeoutMs'):
        return decline(ctx, {'marker': report.get('marker'), 'partial': None}, origin, 'resolved itself (timeout)')
    batch = open_batch(ctx, report.get('marker'))
    answers = report.get('answers') or {}
    if not isinstance(answers, dict) or not all(isinstance(v, str) for v in answers.values()):
        fail('`answers` must map question texts to answer strings')
    texts = {q['question']: (batch['ids'][i] if not batch['cap'] else None) for i, q in enumerate(batch['questions'])}
    unknown = [text for text in answers if text not in texts]
    if unknown:
        fail(f'not a question of {batch["marker"]}: {unknown[0]!r}')
    if batch['cap']:
        if not answers:
            fail('the cap question has no answer')
        return cap_decision(ctx, next(iter(answers.values())), origin)
    batch_seen(ctx, batch)
    now = utcnow()
    done, typed, noted, rethink = [], [], [], []
    for text, qid in texts.items():
        q = by_id(ctx, qid)
        value = (answers.get(text) or '').strip()
        if value == THINK_MORE and not any(o['label'] == THINK_MORE for o in q['options']):
            rethink.append(qid)
            q['thinkMore'] = dict(q.get('leanBecause') or {})  # the lean the person saw: its reruns name it as what fell short
            continue
        pick = option_pick(q, value)
        if pick is None and value and origin != 'dialog':
            pick = value  # model-reported (Codex): the user's quoted words, read at Record
        if pick is not None:
            annotation = (report.get('annotations') or {}).get(text)
            q.update(status='answered', answer=pick, origin=origin, answeredAt=now, annotations=annotation)
            ctx.state['answers'][qid] = pick
            done.append(qid)
            if isinstance(annotation, dict) and str(annotation.get('notes') or '').strip():
                noted.append(words.answer_noted(qid, pick, annotation["notes"].strip()))
                ctx.round['messages'].append({'text': annotation['notes'], 'origin': origin, 'at': now})  # the quote check reads these
        else:
            q['status'] = 'ready'
            reply = typed_reply(report, text, value)
            if reply:  # typed instead of a pick: the model reads it before the question goes out again
                q['typed'] = reply
                ctx.round['messages'].append({'text': reply, 'origin': origin, 'at': now})
                typed.append(qid)
    ctx.round['batch'] = None
    if done and ctx.round['protocol'] == 'round':
        ctx.round['check']['challenged'] = False  # the answers are news to the last challenge-rulings run
    if done:
        touch(ctx, done)
    response = report.get('response')
    ctx.log('answered', marker=batch['marker'], origin=origin, questions=done, typed=typed, response=response, **({'thinkMore': rethink} if rethink else {}))
    notes = [words.answers_recorded(done, origin)] if done else []
    notes += noted
    for qid in typed:
        notes.append(words.answer_typed_note(qid, by_id(ctx, qid)["typed"]))
    if response:
        notes.append(words.answer_response(response))
    if typed or noted or response:
        notes.append(words.ANSWER_ROUTES)
    if noted:
        notes.append(words.NOTE_RECORD)
    if typed or noted:
        notes.append(words.PICK_DETAIL)
    unanswered = [qid for qid in batch['ids'] if qid not in done and qid not in typed and qid not in rethink]
    if unanswered:
        notes.append(words.answers_unanswered(unanswered))
    if report.get('followUp'):
        notes.append(words.FOLLOW_UP)
    reading = origin == 'dialog' and bool(typed or noted or response or report.get('followUp'))
    if reading:
        notes.append(words.answer_reading(typed))
    if rethink:
        restart(ctx, rethink, THINK_MORE)
        if reading:
            ctx.round['reading'] = True  # set after the restart, which counts as the model's reading
        return ' '.join([*notes, words.answer_rethink(rethink)])
    if reading:
        ctx.round['reading'] = True
    ctx.go('ask')
    return ' '.join(notes)


def restart(ctx: Context, ids: list[str], reason: str | None) -> None:
    r = ctx.round
    if r and r['protocol'] == 'release' and r['step'] != 'closed':
        fail('restart is a round verb: in a release, a criterion holds the set (answer Hold, or `protocol abandon`) '
             'and the next round restarts it')
    if not r or r['step'] in ('collect', 'select', 'stage', 'closed'):
        fail('restart needs an open round past Stage')
    targets = [by_id(ctx, qid) for qid in ids]
    # Answers resting on a restarted premise go with it, through chains (r23-q92): their options assumed the old answer.
    resting = []
    for q in targets:
        for other in r['questions']:
            if q['id'] in other.get('waitsOn', []) and other not in targets and other['answer'] is not None:
                targets.append(other)  # the loop reaches its own dependents too
                resting.append(other['id'])
    ids = [q['id'] for q in targets]
    if r['batch'] and not r['batch']['cap']:
        batch_back(ctx)
    for q in targets:
        if q.get('recorded'):
            fail(f"{q['id']} is recorded; a later change is a new question (board revise)")
        if q['answer'] is not None:
            ctx.state['answers'].pop(q['id'], None)
        q.pop('typed', None)
        q.pop('parked', None)
        q.pop('quote', None)  # the answer's own words go with it: a later answer's record must not quote them
        q.pop('annotations', None)
        q.update(answer=None, status='draft')
    for q in questions(ctx, 'draft', 'held', 'ready'):
        q['status'] = premise_status(ctx, q)
    ctx.log('restart', questions=ids, reason=reason)
    r['batch'] = None
    r.pop('reading', None)
    rescope_check(ctx, [*ids, *take_unchecked(ctx)])
    if resting:
        ctx.messages.append(words.restart_resting(resting))
    ctx.messages.append(words.restart_widens())
    ctx.go('check')


def prune(current: Store) -> None:
    """Deletes other sessions' protocol folders without an open round once nothing in them changed for PRUNE_DAYS
    (records live with the board or in the round's named folder, never here)."""
    cutoff = datetime.now(timezone.utc).timestamp() - timedelta(days=PRUNE_DAYS).total_seconds()
    for folder in state_root().glob('*.protocol'):
        if folder == current.dir or not folder.is_dir():
            continue
        try:
            if max((f.stat().st_mtime for f in folder.rglob('*')), default=folder.stat().st_mtime) > cutoff:
                continue
            state = json.loads((folder / 'state.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue  # unreadable: leave it for a person to look at
        if (state.get('round') or {}).get('step') in (None, 'closed'):
            shutil.rmtree(folder, ignore_errors=True)
