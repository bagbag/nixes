"""Ask: dialog batches and the Ask step."""
from __future__ import annotations

from .base import BATCH, ProtocolError, THINK_MORE, TITLE_MAX, cut, lines, recommended_suffix
from . import words
from .engine import Context, PROTOCOLS, by_id, fail, premise_status, questions
from .questions import check_question
from .told import first_time, report_hint
from .render import render_batch
from .away import away_cap, away_guard, away_prepare, away_settle
from .check import fresh_check, record_pass, rescope_check, start_challenge


# Ask: machine-issued batches marked round:<id>:<n>.

def dialog_question(q: dict, number: int | None = None) -> dict:
    """The AskUserQuestion entry: the recommended option first, its label marked with the strength and, on a lean,
    its description opening with what the lean rests on; a batch of 2+ numbers its questions (`1. `)."""
    best = next(o for o in q['options'] if o['label'] == q['recommendation'])
    description = best['description']
    if q['strength'] == 'lean':
        description = words.lean_description(q.get('leanBecause') or {}, description)
    dialog = lambda o: {k: v for k, v in o.items() if k not in ('for', 'against')}  # the engine prints them before the dialog
    options = [{**dialog(best), 'label': best['label'] + recommended_suffix(q), 'description': description},
               *(dialog(o) for o in q['options'] if o is not best)]
    if q['strength'] == 'lean' and len(options) < 4 and not q['multiSelect']:  # the dialog allows four
        options.append({'label': THINK_MORE, 'description': words.THINK_MORE_LINE})
    return {'question': words.dialog_text(q['text'], replaced_words(q), number), 'header': q['header'], 'options': options,
            'multiSelect': q['multiSelect']}


def replaced_words(q: dict) -> str:
    """The records the question replaces, by id and title, added to the dialog's question text (the engine's, outside TEXT_MAX
    like the numbering): the question is what the user answers whichever option they pick, and an option's description would
    name them only on that option. An answer recorded closes the decided ones; a deferred one closes nothing."""
    closes, revised = q.get('replaces') or [], q.get('revises')
    titles = {hit['id']: hit.get('title') or '' for hit in q['overlaps']}
    named = lambda rid: f"{rid} ({cut(titles[rid], TITLE_MAX)})" if titles.get(rid) else rid
    return words.replaced_text(closes, revised, named)


def released_held(ctx: Context) -> list[str]:
    """Held questions whose every `waitsOn` is answered now."""
    return [q['id'] for q in questions(ctx, 'held') if premise_status(ctx, q) == 'draft']


def unchecked(ctx: Context, kind: str | None = None) -> list[str]:
    """The questions an edit added or whose recommendation it changed (`scoped`), or raised to strong (`raised`): they wait
    out of the batches for their check at the hand-over."""
    return [q['id'] for q in questions(ctx, 'draft') if q.get('unchecked') and kind in (None, q['unchecked'])]


def take_unchecked(ctx: Context) -> list[str]:
    ids = unchecked(ctx)
    for qid in ids:
        del by_id(ctx, qid)['unchecked']
    return ids


def hand_over(ctx: Context) -> str:
    """Nothing is left to ask. A round continues with the questions that await a check, then ends (Record runs once, when
    nothing is left to ask):
    - held questions the answers released (r11 q42) and questions an edit added or re-recommended (r13 q47) get the scoped
      rerun (path pass and refine pair on their ids, a fresh Base loop, lean pass and challenge-rulings), then the next batch;
    - questions an edit raised to strong alone get one challenge-rulings pass on them (r13 q48);
    - once the last answer is in, one challenge-rulings over the answered set (r13 q49): a finding is a new question that
      takes the first path, and the pass runs again after its answer; a pass that changed nothing goes to Record.
    A question waits only within its round (r23-q91): one still held on an outside result (`waitsFor`, r8-q31) when the last
    answer is in is deferred at Record, with the questions that wait on it."""
    r = ctx.round
    if r['protocol'] != 'round':
        return PROTOCOLS[r['protocol']].after_ask
    released, scoped, raised = released_held(ctx), unchecked(ctx, 'scoped'), unchecked(ctx, 'raised')
    if released or scoped:
        for q in questions(ctx, 'draft', 'held', 'ready'):
            q['status'] = premise_status(ctx, q)
        if released:
            ctx.log('continued', questions=released)
        if scoped:
            ctx.log('checking', questions=scoped)
        rescope_check(ctx, [*released, *take_unchecked(ctx)])
        return 'check'
    if raised:
        take_unchecked(ctx)
        ctx.log('checking', questions=raised, kind='raised')
        start_challenge(ctx, 'raised', raised)
        return 'check'
    heard = [q['id'] for q in questions(ctx, 'answered') if not q.get('recorded')]
    if heard and not r['check'].get('challenged'):
        start_challenge(ctx, 'answers', heard)
        return 'check'
    return PROTOCOLS[r['protocol']].after_ask


def withdraw_away(ctx: Context) -> str:
    """A batch still out when the role became autopilot: nobody can answer it, so it is withdrawn and its questions settle as away."""
    away_guard(ctx)
    batch = ctx.round['batch']
    ctx.log('batch-withdrawn', marker=batch['marker'], reason='away')
    if batch['cap']:
        ctx.round['batch'] = None
        return away_cap(ctx)
    batch_back(ctx)
    return 'ask'


def ask_enter(ctx: Context) -> str | None:
    r = ctx.round
    if r['batch'] or r.get('reading'):
        return None  # a reply the model reads first holds every next batch: its reading may change or restart questions
    for q in questions(ctx, 'draft'):
        if q.get('unchecked'):
            continue  # an edit added it or changed its recommendation: it waits for its check (hand_over)
        q['status'] = 'ready'
        q.setdefault('messagesBefore', len(r['messages']))  # chat answers quote only messages sent after this
    if ctx.away:
        away_prepare(ctx)
    ready = [q for q in questions(ctx, 'ready') if not q.get('typed')]  # typed answers wait for the model's reading
    if not ready:
        if questions(ctx, 'asked') or any(q.get('typed') for q in questions(ctx, 'ready')):
            return None
        return hand_over(ctx)
    if ctx.away:
        return None  # no batch: the step text asks the model to settle them (away_settle)
    # Only valid questions go out (an answer being recorded must not fail here). Only a question staged before a rule
    # can be invalid here (staging, pass and edit updates check them): it names its error and the model fixes it in a
    # pass of its own (no automatic pass).
    valid, broken = [], {}
    for q in ready:
        try:
            check_question(q, q['id'], marks=bool(q.get('strength')))  # a release approval has no mark and no parts
            valid.append(q)
        except ProtocolError as error:
            broken[q['id']] = str(error)
    if broken:
        ctx.messages.append(words.not_asked(broken))
    if not valid:
        return None
    chosen = valid[:BATCH]
    r['batchSeq'] += 1
    r['batch'] = {'marker': f"round:{r['id']}:{r['batchSeq']}", 'cap': False, 'ids': [q['id'] for q in chosen],
                  'questions': [dialog_question(q, i + 1 if len(chosen) > 1 else None) for i, q in enumerate(chosen)],
                  'notice': render_batch(ctx, chosen)}
    for q in chosen:
        q['status'] = 'asked'
        q.pop('thinkMore', None)  # asked again: a Think more goal is spent
    ctx.log('asked', marker=r['batch']['marker'], questions=r['batch']['ids'])
    return None


def away_ask_text(ctx: Context) -> str:
    """Ask while the role is autopilot: no batch, no dialog, no print (r28-q126, q128). The classes are unattended.md's."""
    ready = [q for q in questions(ctx, 'draft', 'ready') if not q.get('unchecked')]
    return lines(
        words.away_ask_intro(ctx.round['id']),
        *map(words.away_ask_row, ready),
        report_hint(ctx, 'settle', words.settle_example([q['id'] for q in ready[:1]])),
    )


def ask_text(ctx: Context) -> str:
    if ctx.away:
        return away_ask_text(ctx)
    batch = ctx.round['batch']
    if not batch:
        if ctx.round.get('reading'):
            return words.ask_reading(ctx.round['id'])
        return words.ask_no_batch(ctx.round['id'])
    tool_input = {'questions': batch['questions'], 'metadata': {'source': batch['marker']}}
    notice = batch.get('notice') or ''
    numbered = len(batch['questions']) > 1
    lead = words.ask_lead(ctx.round['id'], batch['marker'], batch['cap'], ctx.codex, numbered)
    approval = approval_question(ctx) if ctx.round['protocol'] == 'release' else None
    if approval and approval['id'] in batch['ids'] and approval_reasons(ctx):
        lead += words.approval_why(approval_reasons(ctx))
    once = first_time(ctx, 'ask')  # the dialog itself always prints; the instructions around it once
    if ctx.codex:
        return lines(lead, *([words.text_to_show(notice)] if notice else []),
                     words.ask_exactly(batch['questions']),
                     words.codex_answer_how(batch['marker'], batch['questions'][0]['question']) if once
                     else words.codex_answer_again(batch['marker']))
    return lines(lead, words.dialog_input(words.ask_order(numbered), tool_input) if ctx.complete else '',
                 words.claude_answer_how(batch['ids'][0] if batch['ids'] else None) if once else '')


def ask_accept(ctx: Context, report: dict) -> str:
    """A pass report in Ask (after a decline, or an extra pass before the user answers) updates the questions: a batch
    still out comes back and is issued again, and a change reruns the check loop (asking.md Check). Away: the `settle` report."""
    if ctx.away and 'settle' in report:
        return away_settle(ctx, report)
    if ctx.round['batch'] and not report.get('pass'):
        fail(f"waiting on the user's answer to {ctx.round['batch']['marker']}; a pass report updates its questions")
    for q in questions(ctx):
        q.pop('typed', None)  # read: the step or pass report sends them out again
    ctx.round.pop('reading', None)
    if report.get('pass'):
        if ctx.round['batch']:
            ctx.log('batch-withdrawn', marker=ctx.round['batch']['marker'], reason='pass report')
            batch_back(ctx)
        _, changes, _ = record_pass(ctx, report)
        if changes:
            waiting = take_unchecked(ctx)
            if waiting:
                rescope_check(ctx, waiting)
            else:
                fresh_check(ctx)
            return 'check'
    return 'ask'


def approval_reasons(ctx: Context) -> list[str]:
    return words.approval_reasons(ctx.round['rulings'], ctx.round['set'])


def approval_question(ctx: Context) -> dict | None:
    return next((q for q in ctx.round['questions'] if q['kind'] == 'confirm-own-rulings'), None)


def batch_back(ctx: Context) -> None:
    for qid in ctx.round['batch']['ids']:
        by_id(ctx, qid)['status'] = 'ready'
    ctx.round['batch'] = None
