"""Ask: dialog batches and the Ask step."""
from __future__ import annotations

from .base import (
    BATCH, ProtocolError, THINK_MORE, THINK_MORE_LINE, TITLE_MAX, cut, json_block, lines, recommended_suffix
)
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
        because = q.get('leanBecause') or {}
        kind = 'Unverified' if because.get('cause') == 'evidence' else 'Your call'
        description = f"{kind}: {because.get('detail')}" + (f' — {description}' if description else '')
    dialog = lambda o: {k: v for k, v in o.items() if k not in ('for', 'against')}  # the engine prints them before the dialog
    options = [{**dialog(best), 'label': best['label'] + recommended_suffix(q), 'description': description},
               *(dialog(o) for o in q['options'] if o is not best)]
    if q['strength'] == 'lean' and len(options) < 4 and not q['multiSelect']:  # the dialog allows four
        options.append({'label': THINK_MORE, 'description': THINK_MORE_LINE})
    text = f"{q['text']} {replaced_words(q)}".rstrip()
    return {'question': f'{number}. {text}' if number else text, 'header': q['header'], 'options': options,
            'multiSelect': q['multiSelect']}


def replaced_words(q: dict) -> str:
    """The records the question replaces, by id and title, added to the dialog's question text (the engine's, outside TEXT_MAX
    like the numbering): the question is what the user answers whichever option they pick, and an option's description would
    name them only on that option. An answer recorded closes the decided ones; a deferred one closes nothing."""
    closes, revised = q.get('replaces') or [], q.get('revises')
    titles = {hit['id']: hit.get('title') or '' for hit in q['overlaps']}
    named = lambda rid: f"{rid} ({cut(titles[rid], TITLE_MAX)})" if titles.get(rid) else rid
    return '; '.join(filter(None, [f"Recording it closes {', '.join(map(named, closes))}" if closes else '',
                                   f"{named(revised)} is replaced at release" if revised else ''])) + ('.' if closes or revised else '')


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
    A question waits only within its round (r23-q91): nothing is held when the last answer is in."""
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
        ctx.messages.append('Not asked yet: ' + '; '.join(broken.values()) + f". Fix {', '.join(broken)} in a pass of its "
                            'own: call the ground skill on it (that Skill call counts as the observed run), then report the pass.')
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


EDIT_STDIN = '{"updates": [...], "quote": "<the user\'s exact words>"}'
CHAT_STDIN = '{"question": "<q id>", "answer": "<the answer>", "quote": "<the user\'s exact words>"}'
EDIT_WORDS = 'a question the edit adds or whose recommendation it changes is checked before it is asked.'


def away_ask_text(ctx: Context) -> str:
    """Ask while the role is autopilot: no batch, no dialog, no print (r28-q126, q128). The classes are unattended.md's."""
    ready = [q for q in questions(ctx, 'draft', 'ready') if not q.get('unchecked')]
    rows = [f"- {q['id']}: {q['text']} Recommendation: {q.get('recommendation')} ({q.get('strength')})" for q in ready]
    return lines(
        f"Round {ctx.round['id']} · Ask (away: the role is autopilot, so no dialog opens, nothing prints and the person is not asked). "
        'Settle each question by the Authority classes of unattended.md: `act` takes the recommendation as the answer (Record then asks '
        'its rationale, rule owner and reversal), `park` leaves it open and unassigned on the board for the person; a question waiting '
        'on a parked one parks with it. If the person is back, run `session-lead-mode activate solo` first.',
        *rows,
        report_hint(ctx, 'settle', {'settle': {q['id']: 'act' for q in ready[:1]} | {'<id>': 'park'}}),
    )


def ask_text(ctx: Context) -> str:
    if ctx.away:
        return away_ask_text(ctx)
    batch = ctx.round['batch']
    if not batch:
        if ctx.round.get('reading'):
            return (f"Round {ctx.round['id']} · Ask: the next batch waits for your reading of the user's reply: then `protocol step` "
                    'with {} (or a pass report) issues it.')
        return f"Round {ctx.round['id']} · Ask: no batch out. `protocol step` with {{}} issues the next one."
    tool_input = {'questions': batch['questions'], 'metadata': {'source': batch['marker']}}
    notice = batch.get('notice') or ''
    order = ', in this order' + (', numbered like the dialog' if len(batch['questions']) > 1 else '')
    console_opens = ('write one short line that questions are coming, nothing about their content, and end your turn; a message tells you when you have something to do. '
                     'After a reply the person typed instead of picking: answer it as the turn\'s last text and end the turn. '
                     'If a console message asks you to open the dialog: call AskUserQuestion with the input `protocol show` gives.')
    lead = f"Round {ctx.round['id']} · " + (f"Check cap reached: {'ask the user how to go on.' if ctx.codex else console_opens}" if batch['cap'] else
                                             f"Ask batch {batch['marker']}" + (f' (show the user the text below first, then ask{order}).' if ctx.codex else f': {console_opens}'))
    approval = approval_question(ctx) if ctx.round['protocol'] == 'release' else None
    if approval and approval['id'] in batch['ids'] and approval_reasons(ctx):
        lead += f" The dialog stays short; why it asks: {'; '.join(approval_reasons(ctx))}."
    once = first_time(ctx, 'ask')  # the dialog itself always prints; the instructions around it once
    if ctx.codex:
        answer_how = ('Then record the reply: `protocol answer --origin model-reported` with stdin '
                      + json_block({'marker': batch['marker'], 'answers': {batch['questions'][0]['question']: "<the user's own words, quoted verbatim>"}})
                      + ". Key each answer by the question's exact text and quote only what the user wrote; leave out questions "
                      'the user did not answer. If the user declines, run `protocol decline --origin model-reported` with stdin '
                      + json_block({'marker': batch['marker'], 'partial': None}) + '. To apply a change the user asked for to a question, '
                      f'run `protocol edit` (stdin {EDIT_STDIN}); ' + EDIT_WORDS)
        return lines(lead, *([f'Text to show first:\n{notice}'] if notice else []),
                     f'Ask the user exactly these questions: {json_block(batch["questions"])}',
                     answer_how if once else f"Record the reply as before: `protocol answer --origin model-reported` (or `decline`), marker {batch['marker']}.")
    return lines(lead, f'AskUserQuestion input{order}: {json_block(tool_input)}' if ctx.complete else '',
                 f'To apply a change the user asked for to a question before they answer, use `protocol edit` (stdin {EDIT_STDIN}); '
                 + EDIT_WORDS +
                 ' A pass report updates questions only for a pass.\n'
                 'Record an answer the user types in chat with the protocol tool\'s ["answer"] (through Bash, `protocol '
                 'answer --origin chat`) and stdin '
                 + json_block({'question': batch['ids'][0] if batch['ids'] else '<q id>', 'answer': '<the answer>',
                               'quote': "<the user's exact words>"}) + '.' if once else '')


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
            rescope_check(ctx, waiting) if waiting else fresh_check(ctx)
            return 'check'
    return 'ask'


def approval_reasons(ctx: Context) -> list[str]:
    """Why the approval is asked (unsure rulings, revised records, records that left the set): for the model and the Log."""
    return [f"unsure: {x['record']} {x['ruling']}" for x in ctx.round['rulings'] or [] if not x['sure']] + \
           [f"revised: {rec['id']} ({rec['change']})" for rec in ctx.round['set'] if rec['state'] == 'revised'] + \
           [f"left the set: {rec['id']} ({rec['reason']})" for rec in ctx.round['set'] if rec['state'] in ('dropped', 'changed')]


def approval_question(ctx: Context) -> dict | None:
    return next((q for q in ctx.round['questions'] if q['kind'] == 'confirm-own-rulings'), None)


def batch_back(ctx: Context) -> None:
    for qid in ctx.round['batch']['ids']:
        by_id(ctx, qid)['status'] = 'ready'
    ctx.round['batch'] = None
