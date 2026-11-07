"""The check loop: pass sequence, cycles and cap, and the Check step's entry and report (its text: round.py)."""
from __future__ import annotations

import contextlib

from .base import (
    ALL_LENSES, CAP_CHOICES, CHECK_CAP, EXPLORED_VERDICTS, LEAN_LENSES, NO_RUN, OPTIONS_LENSES, PASSES, PATH_LENSES,
    REFINE_LENSES
)
from . import words
from .engine import Context, Step, by_id, fail, questions, unresolved
from .questions import apply_updates, describe, refuse_all
from .told import report_format
from .away import away_cap


# Check loop: step-back then ground per cycle until a cycle changes nothing; the cap hands over to the user.

def fresh_check(ctx: Context) -> None:
    ctx.round['checkRun'] = ctx.round.get('checkRun', 0) + 1  # a new check run lists its questions again
    ctx.round['check'] = {'cycle': 1, 'cap': CHECK_CAP, 'expect': 'step-back', 'changes': 0, 'last': {},
                          'converged': False, 'challenged': False, 'focused': False, 'focusing': False, 'pathNow': False,
                          'pathScoped': False, 'optionsNow': False, 'optionsScoped': False, 'refineNow': None, 'refineScoped': False, 'refineChanges': 0, 'askNow': False, 'paused': False}
    for q in questions(ctx, 'ready'):
        q['status'] = 'draft'
    start_base(ctx)


def rescope_ids(ctx: Context) -> list[str]:
    """The restarted questions still in the round: `protocol restart` queues scoped reruns of the path, options and refine
    passes on them (round['rescope']: ids, pending `path`, `options` and `refine` passes); the round's flags stay."""
    scope = ctx.round.get('rescope') or {}
    live = {q['id'] for q in ctx.round['questions']}
    return [qid for qid in scope.get('ids', []) if qid in live]


def named_words(ctx: Context, args: str) -> list[str]:
    """The lens names and question ids leading a pass's argument (`<lenses> on <ids>; <focus>`, `on` and `;` optional); the
    rest is the skill's focus (a Think more goal), whose words never count as lenses or ids. Names the lean pass's questions."""
    known = {lens for lenses in ALL_LENSES.values() for lens in lenses} | {q['id'] for q in ctx.round['questions']}
    named = []
    for word in str(args or '').split():
        name = word.removesuffix(';')
        if name == 'on' and name == word:
            continue
        if name not in known:
            break
        named.append(name)
        if name != word:
            break
    return named


def with_goal(ctx: Context, lenses: tuple[str, ...], ids: list[str]) -> str:
    """A pass argument: `<lenses> on <ids>`, then the Think more goal of those ids (r38-q213): the lean the person saw fell
    short (`protocol show <id>` keeps it as `thinkMore`), try to get a reasoned strong recommendation. One line without quotes,
    so a typed rerun matches it."""
    head = ' '.join([*lenses, *(['on', *ids] if ids else [])])
    rethink = [q['id'] for q in ctx.round['questions'] if q['id'] in ids and isinstance(q.get('thinkMore'), dict)]
    if not rethink:
        return head
    return words.think_more_goal(head, rethink)


def rescope_check(ctx: Context, ids: list[str]) -> None:
    """The restarted (or released held, or edited) ids get their own path pass, options pass and refine pair, accumulating over
    restarts before the loop settles, then a fresh check; the round's once-per-round flags stay."""
    r = ctx.round
    scope = r.get('rescope') or {'ids': []}
    r['rescope'] = {'ids': list(dict.fromkeys([*scope['ids'], *ids])), 'path': True, 'options': True, 'refine': list(REFINE_LENSES)}
    fresh_check(ctx)


def rescope_done(ctx: Context) -> None:
    scope = ctx.round.get('rescope')
    if scope and not scope['path'] and not scope.get('options') and not scope['refine']:
        del ctx.round['rescope']


def options_ids(ctx: Context, within: list[str] | None = None) -> list[str]:
    """The staged decisions the options pass covers (`within`: only these ids): a confirm-own-rulings question asks the person
    to confirm my rulings, so it has no other ways to explore (r30-q142)."""
    return [q['id'] for q in questions(ctx, 'draft', 'held', 'ready') if q['kind'] == 'decision' and (within is None or q['id'] in within)]


def start_base(ctx: Context) -> None:
    """The next step-back of the Base loop; the round's first one is the path pass (round-wide, once per round: r5 q21,
    flagged on the round so a rebuilt check does not repeat it), then the options pass (the same), and after a restart a
    path and an options pass on the restarted ids."""
    r, check = ctx.round, ctx.round['check']
    scope = r.get('rescope')
    check['pathNow'] = not r.get('pathRun')
    check['pathScoped'] = bool(not check['pathNow'] and scope and scope['path'] and rescope_ids(ctx))
    if scope and check['pathNow']:
        scope['path'] = False  # the round-wide path pass covers the restarted ids
    elif scope and scope['path'] and not check['pathScoped']:
        scope['path'] = False
    check['optionsNow'] = check['optionsScoped'] = False
    if check['pathScoped']:
        check['pathNow'] = True
        ctx.set_pending('step-back', with_goal(ctx, PATH_LENSES, rescope_ids(ctx)))
    elif check['pathNow']:
        ctx.set_pending('step-back', ' '.join(PATH_LENSES))
    else:
        check['optionsNow'] = not r.get('optionsRun') and bool(options_ids(ctx))
        scoped = options_ids(ctx, rescope_ids(ctx)) if scope and scope.get('options') else []
        check['optionsScoped'] = bool(not check['optionsNow'] and scoped)
        if scope and scope.get('options') and not check['optionsScoped']:
            scope['options'] = False  # the round-wide pass covers the restarted ids, or none of them has options to explore
        if check['optionsScoped']:
            check['optionsNow'] = True
            ctx.set_pending('step-back', with_goal(ctx, OPTIONS_LENSES, scoped))
        else:
            ctx.set_pending('step-back', ' '.join(OPTIONS_LENSES) if check['optionsNow'] else '')
    rescope_done(ctx)


def check_enter(ctx: Context) -> str | None:
    if not ctx.round['check'].get('expect'):
        fresh_check(ctx)
    return None


def needs_related(ctx: Context) -> bool:
    return bool(unresolved(ctx)) or any(q['board'] is None and not q['searched'] for q in questions(ctx, 'draft', 'held'))


def needs_challenge(ctx: Context) -> bool:
    """Every round carries own rulings (excluded options, accepted premises, bundling, entailed choices): challenge-rulings
    runs last before a batch, again whenever a pass changed questions since its last run (`challenged` is cleared by
    any pass with changes and set only by a challenge-rulings pass that changed nothing), so unsure rulings become
    questions in it. The cycle cap bounds the repeats."""
    check = ctx.round['check']
    return not check['challenged'] and not (check['askNow'] and check.get('challengeRan')) and bool(questions(ctx, 'draft', 'ready'))


def gate_ask(ctx: Context) -> str:
    """Before asking: every related hit has an outcome; challenge-rulings ran on the converged questions."""
    check = ctx.round['check']
    check['converged'] = True
    if needs_related(ctx):
        return 'related'  # a pass added or reworded drafts: search them first
    if not check['askNow']:
        # The refine pair, once per round after the Base loop converged (r5 q20, q26): step-back, then ground, round-wide
        # (no question ids).
        scope = ctx.round.get('rescope')
        for command, lenses in REFINE_LENSES.items():
            if command not in ctx.round.get('refineRun', []):
                if scope and command in scope['refine']:
                    scope['refine'].remove(command)  # the round-wide pass covers the restarted ids
                check.update(expect=command, refineNow=command, refineScoped=False)
                ctx.set_pending(command, ' '.join(lenses))
                return 'check'
            if scope and command in scope['refine']:
                if not rescope_ids(ctx):
                    scope['refine'].remove(command)
                    continue
                check.update(expect=command, refineNow=command, refineScoped=True)
                ctx.set_pending(command, with_goal(ctx, lenses, rescope_ids(ctx)))
                return 'check'
        rescope_done(ctx)
        if check.get('refineChanges'):  # the pair's changes rerun the Base loop (under the cap); the pair does not run again
            check['refineChanges'] = 0
            return next_cycle(ctx)
    leans = [q['id'] for q in questions(ctx, 'draft', 'ready') if q.get('strength') == 'lean']
    if leans and not check.get('focused') and not check['askNow']:
        # One targeted pass on every lean, evidence or preference, aiming it at strong (LEAN_JOB); a value lean asks its value question.
        check.update(expect='ground', focusing=True)
        ctx.set_pending('ground', with_goal(ctx, LEAN_LENSES, leans))
        return 'check'
    if needs_challenge(ctx):
        check['expect'] = 'challenge-rulings'
        ctx.set_pending('challenge-rulings')
        return 'check'
    ctx.round['pending'] = None
    return 'ask'


def cap_batch(ctx: Context) -> None:
    r = ctx.round
    r['pending'] = None
    r['batchSeq'] += 1
    r['batch'] = {'marker': f"round:{r['id']}:{r['batchSeq']}", 'cap': True, 'ids': [], 'questions': [{
        'question': words.cap_question(r['id'], r['check']['cycle']),
        'header': words.CAP_HEADER, 'multiSelect': False,
        'options': [{'label': choice, 'description': words.CAP_DESCRIPTIONS[choice]} for choice in CAP_CHOICES]}]}
    ctx.log('cap', cycle=r['check']['cycle'], marker=r['batch']['marker'])


def next_cycle(ctx: Context) -> str:
    check = ctx.round['check']
    if check['cycle'] >= check['cap']:
        if ctx.away:
            return away_cap(ctx)
        cap_batch(ctx)
        return 'check'
    check.update(cycle=check['cycle'] + 1, changes=0, expect='step-back', converged=False, refineNow=None)
    start_base(ctx)
    return 'check'


def pass_report_format(ctx: Context, command: str) -> str:
    return report_format(ctx, 'pass', words.pass_format(command))


def options_report_format(ctx: Context) -> str:
    return report_format(ctx, 'options', words.options_format())


def refused_formats(ctx: Context, step: Step, report: dict, before: dict) -> str:
    """The report formats a refused report repeats: the step's text rebuilt on the state before the refused call, which
    keeps every format it offers whether or not it printed them, and a pass report's own."""
    ctx.state, ctx.formats = before, {}
    with contextlib.suppress(Exception):
        step.text(ctx)
    if report.get('pass') in PASSES:
        ctx.formats.setdefault('pass', words.pass_format(report['pass']))
    return '\n'.join(ctx.formats.values())


def settles(ctx: Context, command: str) -> bool:
    """Whether a report of `command` settles the pending pass: the run it reports carried the pending pass's id (the console
    stamps a run whose command and arguments match it, `protocol pass`); Codex has no console to observe its runs, so its
    report of the pending command counts. Any other report is an extra pass."""
    pending = ctx.round['pending']
    if not pending or pending['command'] != command:
        return False
    return ctx.codex or (ctx.round['observed'].get(command) or {}).get('pending') == pending['id']


def options_due(ctx: Context, command: str) -> list[str] | None:
    """The question ids a step-back report must account for in `explored` when it is the options pass (the pending one, settled
    by its run), else None."""
    check = ctx.round['check']
    if command != 'step-back' or check.get('expect') != command or not check.get('optionsNow') or not settles(ctx, command):
        return None
    return options_ids(ctx, rescope_ids(ctx)) if check.get('optionsScoped') else options_ids(ctx)


def explored_of(raw, ids: list[str]) -> dict[str, list[dict] | str]:
    """The options pass's `explored` (r30-q142): per question a list of {idea, verdict kept|dropped, why}, or the reason there
    is no other way. Refused unless it accounts for exactly the questions the pass covers."""
    if not isinstance(raw, dict):
        fail('an options pass reports `explored`: per question a list of {"idea", "verdict": "kept" or "dropped", "why"}, or the reason there is no other way')
    errors = [f'explored: no entry for {qid}' for qid in ids if qid not in raw] + [f'explored: {qid} is not covered by this pass' for qid in raw if qid not in ids]
    found = {}
    for qid, value in raw.items():
        if qid not in ids:
            continue
        if isinstance(value, str) and value.strip():
            found[qid] = value.strip()
        elif isinstance(value, list) and value and all(isinstance(x, dict) and all(isinstance(x.get(k), str) and x[k].strip() for k in ('idea', 'why'))
                                                       and x.get('verdict') in EXPLORED_VERDICTS for x in value):
            found[qid] = [{'idea': x['idea'].strip(), 'verdict': x['verdict'], 'why': x['why'].strip()} for x in value]
        else:
            errors.append(f'explored.{qid}: a non-empty list of {{"idea", "verdict": {" or ".join(EXPLORED_VERDICTS)}, "why"}}, or the reason there is no other way')
    refuse_all(errors)
    return found


def record_pass(ctx: Context, report: dict) -> tuple[str, int, str]:
    command = report.get('pass')
    if command not in PASSES:
        fail(f"`pass` must be one of {', '.join(PASSES)}")
    observed = ctx.round['observed']
    if not ctx.codex and command not in observed:  # Codex has no console to observe its runs
        fail(NO_RUN.format(command=command))
    origin = (observed.get(command) or {}).get('origin', 'model')
    kind, scoped = pass_kind(ctx, command)
    describe(ctx, report.get('round'), 'pass report', required=False)
    checked = report.get('checked')
    if checked is not None and not (isinstance(checked, list) and all(isinstance(c, str) and c.strip() for c in checked)):
        fail('`checked` lists what the pass examined, as strings')
    due = options_due(ctx, command)
    raw = report.get('explored')
    explored = explored_of(raw, due if due is not None else [qid for qid in raw if any(q['id'] == qid for q in ctx.round['questions'])] if isinstance(raw, dict) else []) if due is not None or raw is not None else {}
    changes = apply_updates(ctx, report.get('updates') or [])
    if not changes and not checked:
        fail(f'a {command} pass that changes nothing names what it checked: `"checked": ["q2: the retry premise in '
             'task-queue.ts", …]`')
    for qid, found in explored.items():
        if any(q['id'] == qid for q in ctx.round['questions']):
            by_id(ctx, qid)['explored'] = found
    observed.pop(command, None)
    ctx.round['check']['last'][command] = {'changes': changes, 'origin': origin}
    ctx.round['lastPass'] = {'pass': command, 'questions': list(dict.fromkeys([*ctx.applied, *ctx.added]))}  # in or out of sequence
    ctx.log('pass', command=command, changes=changes, questions=list(dict.fromkeys(ctx.applied)), added=ctx.added,
            origin=origin, cycle=ctx.round['check']['cycle'], summary=report.get('summary'),
            checked=checked, kind=kind, scoped=scoped)
    return command, changes, origin


def start_challenge(ctx: Context, kind: str, ids: list[str]) -> None:
    """One challenge-rulings pass outside the Base loop: `answers` over the answered set after the last answer, `raised` on
    the questions an edit raised to strong. Its additions wait for their scoped check; nothing reruns the loop."""
    ctx.round['check'].update(expect='challenge-rulings', converged=True, pathNow=False, pathScoped=False, optionsNow=False,
                              optionsScoped=False, refineNow=None, refineScoped=False, focusing=False, challenge={'kind': kind, 'ids': ids})
    ctx.set_pending('challenge-rulings', ' '.join(ids))


def finish_challenge(ctx: Context, changes: int) -> str:
    """The pass of `start_challenge` reported: new questions it found wait for the scoped check (hand-over), then Ask.
    After the last answer a pass that changed nothing is done (`challenged`), else it runs again at the next hand-over."""
    check = ctx.round['check']
    spec = check.pop('challenge')
    for qid in ctx.added:
        if by_id(ctx, qid)['status'] == 'draft':
            by_id(ctx, qid)['unchecked'] = 'scoped'
    if spec['kind'] == 'answers':
        check.update(challenged=not changes, challengeRan=True)
    ctx.round['pending'] = None
    return 'ask'


def nothing_to_check(ctx: Context) -> bool:
    """No open question left, as after removing the only one under check: the pending pass has nothing to judge."""
    return not ctx.round['batch'] and not questions(ctx, 'draft', 'held', 'ready', 'asked')


def leave_check(ctx: Context) -> str:
    ctx.round['pending'] = None
    ctx.round.pop('rescope', None)
    return 'ask'


def check_accept(ctx: Context, report: dict) -> str:
    check = ctx.round['check']
    if ctx.round['batch']:
        fail(f"waiting on the user's answer to {ctx.round['batch']['marker']}")
    if check['paused']:
        fail('the check loop is paused: protocol resume continues it')
    expected = check['expect']
    settled = settles(ctx, report.get('pass'))
    command, changes, _ = record_pass(ctx, report)
    if changes and command != 'challenge-rulings':
        check['challenged'] = False  # a change after the last challenge-rulings run re-arms it
    if check.get('challenge') and command == expected == 'challenge-rulings' and settled:
        return finish_challenge(ctx, changes)
    if nothing_to_check(ctx):
        return leave_check(ctx)
    scope = ctx.round.get('rescope') or {}
    if command != expected or not settled:  # an extra pass between passes (pressed, typed, or asked for in chat)
        if changes:
            check.pop('challenge', None)
            check.update(changes=0, expect='step-back', converged=False, challenged=False, focused=False, focusing=False, refineNow=None)
            if not (check.get('pathNow') or check.get('optionsNow')):  # the pending path or options pass stays
                start_base(ctx)
        return 'check'
    if check.get('refineNow') == command:
        check.update(refineNow=None, refineChanges=check.get('refineChanges', 0) + changes)
        if check.get('refineScoped'):
            scope['refine'].remove(command)
        else:
            ctx.round['refineRun'] = list(dict.fromkeys([*ctx.round.get('refineRun', []), command]))
        check['refineScoped'] = False
        return gate_ask(ctx)
    if command == 'step-back' and check.get('pathNow'):
        # The path pass: its changes flow into the Base loop that runs next; new or reworded drafts are searched first.
        if check.get('pathScoped'):
            scope['path'] = False
        else:
            ctx.round['pathRun'] = True
        check.update(changes=0, expect='step-back')
        start_base(ctx)
        return 'related' if changes and needs_related(ctx) else 'check'
    if command == 'step-back' and check.get('optionsNow'):
        # The options pass: like the path pass, its changes flow into the Base loop that runs next.
        if check.get('optionsScoped'):
            scope['options'] = False
        else:
            ctx.round['optionsRun'] = True
        check.update(changes=0, expect='step-back')
        start_base(ctx)
        return 'related' if changes and needs_related(ctx) else 'check'
    if command == 'step-back':
        check.update(changes=changes, expect='ground')
        ctx.set_pending('ground')
        return 'check'
    if command == 'ground' and check.get('focusing'):
        check.update(focusing=False, focused=True)  # one pass: its changes do not restart the loop
        return gate_ask(ctx)
    if command == 'ground':
        if check['changes'] + changes == 0:
            return gate_ask(ctx)
        return next_cycle(ctx)
    check.update(challenged=not changes, challengeRan=True)  # challenge-rulings: a pass that changed nothing ends it
    if changes and not check['askNow']:
        return next_cycle(ctx)
    return gate_ask(ctx)


def pending_view(ctx: Context) -> dict | None:
    r = ctx.round
    if not r or r['step'] == 'closed' or not r['pending']:
        return None
    return dict(r['pending'])


def pass_kind(ctx: Context, command: str) -> tuple[str | None, list[str]]:
    """The kind of the pass about to be reported (path, options, refine, lean, challenge) and the ids it is scoped to; None for a
    Base-loop pass, 'extra' for one that does not settle the pending pass."""
    check = ctx.round['check']
    if check.get('expect') != command or not settles(ctx, command):
        return 'extra', []
    if command == 'step-back' and check.get('pathNow'):
        return 'path', rescope_ids(ctx) if check.get('pathScoped') else []
    if command == 'step-back' and check.get('optionsNow'):
        return 'options', options_ids(ctx, rescope_ids(ctx)) if check.get('optionsScoped') else []
    if check.get('refineNow') == command:
        return 'refine', rescope_ids(ctx) if check.get('refineScoped') else []
    if command == 'ground' and check.get('focusing'):
        return 'lean', [one for one in named_words(ctx, (ctx.round['pending'] or {}).get('args') or '') if one not in LEAN_LENSES]
    if command == 'challenge-rulings' and check.get('challenge'):
        spec = check['challenge']
        return ('after answers', []) if spec['kind'] == 'answers' else ('raised', spec['ids'])
    return None, []
