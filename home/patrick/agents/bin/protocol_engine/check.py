"""The check loop: pass sequence, cycles and cap, and the Check step's entry and report (its text: round.py)."""
from __future__ import annotations

import contextlib

from .base import CHECKED_LIMIT, CHECKED_MAX, CAP_CHOICES, CHECK_CAP, PASSES, ProtocolError, band_warning
from . import schema, words
from .engine import Context, Step, by_id, fail, questions, touch, unresolved
from .questions import apply_updates, describe, disclosure_error, refuse_all, strong_errors
from .told import report_format
from .away import away_cap


# Check loop: step-back and a confirming step-back converge before challenge-rulings; the cap hands over to the user.

def fresh_check(ctx: Context) -> None:
    focus_ids = list((ctx.round.get('check') or {}).get('focusIds') or [])
    ctx.round['check'] = {'cycle': 1, 'cap': CHECK_CAP, 'expect': 'step-back', 'changes': 0, 'last': {},
                          'converged': False, 'challenged': False, 'confirming': False, 'focusIds': focus_ids, 'askNow': False, 'paused': False}
    for q in questions(ctx, 'ready'):
        q['status'] = 'draft'
    start_base(ctx)


def queue_rescope(ctx: Context, ids: list[str]) -> None:
    """Questions changed by restart or edit receive a focused step-back before confirmation."""
    if ids:
        scope = ctx.round['check'].setdefault('focusIds', [])
        ctx.round['check']['focusIds'] = list(dict.fromkeys([*scope, *ids]))


def rescope_ids(ctx: Context) -> list[str]:
    """The focused questions still in the round."""
    live = {q['id'] for q in ctx.round['questions']}
    return [qid for qid in ctx.round['check'].get('focusIds', []) if qid in live]


def with_goal(ctx: Context, ids: list[str]) -> str:
    """A focused pass includes the user's Think More goal, so the run keeps its reason and scope."""
    head = ' '.join(['on', *ids]) if ids else ''
    rethink = [q for q in ctx.round['questions'] if q['id'] in ids and isinstance(q.get('thinkMore'), dict)]
    if not rethink:
        return head
    return words.think_more_goal(head, [q['id'] for q in rethink], [str(q['thinkMore'].get('quote') or '') for q in rethink])


def rescope_check(ctx: Context, ids: list[str]) -> None:
    """Restarted, released or edited questions get a focused step-back and a fresh confirmation."""
    queue_rescope(ctx, ids)
    touch(ctx, ids)  # a restart, a release from held and an edit's re-check enter every pass kind's next scope
    fresh_check(ctx)


def start_base(ctx: Context) -> None:
    """Queue a full or focused step-back pass, then a fresh-turn confirmation."""
    check = ctx.round['check']
    ids = rescope_ids(ctx)
    check['confirming'] = False
    ctx.set_pending('step-back', with_goal(ctx, ids))


def migrate_legacy_check(ctx: Context) -> bool:
    """Map an old path/options/refine/ground run to a confirming step-back, preserving its pending id."""
    r = ctx.round
    if not r or r.get('protocol') != 'round' or r.get('step') != 'check':
        return False
    check = r.get('check') or {}
    pending = r.get('pending') or {}
    legacy = any(key in check for key in ('pathNow', 'pathScoped', 'optionsNow', 'optionsScoped', 'refineNow', 'refineScoped', 'focusing'))
    if not legacy or pending.get('command') not in ('step-back', 'ground'):
        return False
    ids = list((r.get('rescope') or {}).get('ids', [])) or list(check.get('focusIds', []))
    check.clear()
    check.update(cycle=1, cap=CHECK_CAP, expect='step-back', changes=0, last={}, converged=False,
                 challenged=False, confirming=True, focusIds=ids, askNow=False, paused=False)
    r['check'] = check
    r.pop('rescope', None)
    live = [qid for qid in ids if any(q['id'] == qid for q in r['questions'])]
    ctx.set_pending('step-back', with_goal(ctx, live))
    return True


def check_enter(ctx: Context) -> str | None:
    if not ctx.round['check'].get('expect'):
        fresh_check(ctx)
    migrate_legacy_check(ctx)
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
    """Before asking: check new drafts for related hits, then challenge-rulings on converged questions."""
    check = ctx.round['check']
    check['converged'] = True
    if needs_related(ctx):
        return 'related'
    if needs_challenge(ctx):
        check['expect'] = 'challenge-rulings'
        ctx.set_pending('challenge-rulings')
        return 'check'
    check['focusIds'] = []
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
    check.update(cycle=check['cycle'] + 1, changes=0, expect='step-back', converged=False, confirming=True)
    ctx.set_pending('step-back', with_goal(ctx, rescope_ids(ctx)))
    return 'check'


def pass_report_format(ctx: Context, command: str) -> str:
    return report_format(ctx, 'pass', words.pass_format(command))




def challenge_report_format(ctx: Context) -> str:
    return report_format(ctx, 'challenge', words.challenge_format())


def refused_formats(ctx: Context, step: Step, report: dict, before: dict) -> str:
    """The report formats a refused report repeats that the session was not told since its last compaction: the step's text
    rebuilt on the state before the refused call, which keeps every format it offers whether or not it printed them, and a
    pass report's own. One line points at `protocol show` when a told format is left out."""
    told = set(before.get('told') or [])  # before the rebuild: step.text records its keys into `before`
    ctx.state, ctx.formats = before, {}
    with contextlib.suppress(Exception):
        step.text(ctx)
    if report.get('pass') in PASSES:
        ctx.formats.setdefault('pass', words.pass_format(report['pass']))
    if report.get('pass') == 'challenge-rulings':
        ctx.formats.setdefault('challenge', words.challenge_format())
    new = [text for kind, text in ctx.formats.items() if f'format:{kind}' not in told]
    return '\n'.join([*new, *([words.FORMAT_AGAIN] if len(new) < len(ctx.formats) else [])])


def settles(ctx: Context, command: str) -> bool:
    """Whether a report of `command` settles the pending pass: the run it reports carried the pending pass's id (the console
    stamps a run whose command and arguments match it, `protocol pass`); Codex has no console to observe its runs, so its
    report of the pending command counts. Any other report is an extra pass."""
    return stamp_settles(ctx, command, (ctx.round['observed'].get(command) or {}).get('pending'))


def stamp_settles(ctx: Context, command: str, stamp: str | None) -> bool:
    """`settles` only when the console stamped this pending run; a Skill expansion alone is not a run."""
    pending = ctx.round['pending']
    if not pending or pending['command'] != command:
        return False
    return ctx.codex or stamp == pending['id']


# Scoped coverage (r4-q15, q16): each pass report keys `checked` by question for its scope; a change stamps the question
# (engine.touch: round['coverage']['at'][id] = the round's change sequence), and a pass marks what it covered under its
# coverage key (round['coverage']['seen'][key][id]) after applying its own updates, so they stay out of its next scope.

SCOPE_STATUSES = ('draft', 'ready')


def pass_scope(ctx: Context, command: str, kind: str | None, scoped: list[str]) -> tuple[str | None, list[str]]:
    """The question ids a pass report must cover and the coverage key whose marks it advances."""
    if kind == 'focused':
        return 'focused', scoped
    if kind == 'confirming':
        return 'confirming', [q['id'] for q in questions(ctx, *SCOPE_STATUSES)]
    if kind in ('after answers', 'raised'):
        live = {q['id'] for q in ctx.round['questions']}
        return 'challenge-rulings', [qid for qid in ctx.round['check']['challenge']['ids'] if qid in live]
    key = f'extra {command}' if kind == 'extra' else kind or command
    coverage = ctx.round.get('coverage') or {}
    seen, at = (coverage.get('seen') or {}).get(key, {}), coverage.get('at') or {}
    return key, [q['id'] for q in questions(ctx, *SCOPE_STATUSES) if q['id'] not in seen or at.get(q['id'], 0) > seen[q['id']]]


def mark_covered(ctx: Context, key: str, ids: list[str]) -> None:
    coverage = ctx.round.setdefault('coverage', {'seq': 0, 'at': {}, 'seen': {}})
    seen = coverage['seen'].setdefault(key, {})
    for qid in ids:
        seen[qid] = coverage['seq']


def strong_ids(ctx: Context, ids: list[str]) -> list[str]:
    """The strong questions among `ids` whose mark the pass re-derives: after the last answer (r21-q143) the answered ones
    keep their mark, only the rulings and a checked entry per question are due."""
    after_answers = ((ctx.round['check'].get('challenge') or {}).get('kind')) == 'answers'
    return [q['id'] for q in ctx.round['questions']
            if q['id'] in ids and q.get('strength') == 'strong' and not (after_answers and q['status'] == 'answered')]


def scope_ids(ctx: Context, command: str, settled: bool | None) -> tuple[list[str], list[str] | None]:
    """The ids a report of `command` covers (`settled` as in pass_kind) and, for challenge-rulings, the strong ones among them."""
    kind, scoped = pass_kind(ctx, command, settled)
    _, ids = pass_scope(ctx, command, kind, scoped)
    return ids, strong_ids(ctx, ids) if command == 'challenge-rulings' else None


def scope_text(ctx: Context, command: str) -> str:
    """The pending pass's scope as the step names it: the ids to cover and, for challenge-rulings, the strong ones."""
    return words.pass_scope(*scope_ids(ctx, command, settled=True), command, pass_kind(ctx, command, True)[0] == 'after answers')


SCOPE_STEPS = ('check', 'ask')  # the steps that take a pass report (check_accept, ask_accept)


def start_scope(ctx: Context, report: dict) -> dict:
    """`protocol scope`: what a report of the pass starting now must cover, without a change."""
    schema.require(schema.Scope, report)
    command, stamp = report['command'], report.get('pending')
    r = ctx.round
    if not r or r['step'] not in SCOPE_STEPS or r['protocol'] != 'round':
        return {'covers': [], 'text': ''}
    settled = stamp_settles(ctx, command, stamp) if 'pending' in report else None
    ids, strong = scope_ids(ctx, command, settled)
    text = words.start_scope(ids, strong, command, pass_kind(ctx, command, settled)[0] == 'after answers') if ids else ''
    return {'covers': ids, 'text': text}


def checked_of(raw, known: set[str]) -> tuple[dict[str, str], list[str]]:
    errors = [f'checked.{key}: no question of this round (keys: question ids, and `round` for a round-wide note)'
              for key in raw if key != 'round' and key not in known]
    errors += [f'checked.{key}: what you examined, a non-empty string' for key, value in raw.items() if not (isinstance(value, str) and value.strip())]
    errors += [f'checked.{key}: {len(value.strip())} characters; one line of about {CHECKED_MAX} (the finding itself goes in an update or `summary`)'
               for key, value in raw.items() if isinstance(value, str) and len(value.strip()) > CHECKED_LIMIT]
    return {key: value.strip() for key, value in raw.items() if isinstance(value, str) and value.strip()}, errors


def challenge_errors(ctx: Context, report: dict, scope: list[str], updates: list) -> list[str]:
    """challenge-rulings re-derives each strong question in its scope, an answered one after the last answer excepted (`verdicts`: its strongBecause, or an update lowering it
    to lean or re-sending it) and lists its own rulings in the disclosure shape, keyed by question (`rulings`)."""
    current = {q['id']: q for q in ctx.round['questions']}
    resent = {u['id'] for u in updates if isinstance(u, dict) and 'strongBecause' in u and isinstance(u.get('id'), str)}
    errors, verdicts = schema.problems(schema.PassReport, report, 'verdicts'), report.get('verdicts', {})
    if errors:
        verdicts = {}
    for qid, verdict in verdicts.items():
        if (current.get(qid) or {}).get('strength') != 'strong':
            errors.append(f'verdicts.{qid}: not a strong question of this round')
        elif not isinstance(verdict, dict):
            errors.append(f'verdicts.{qid}: {{"strongBecause": {{…}}}}')
        else:
            errors += strong_errors(verdict.get('strongBecause'), f'verdicts.{qid}')
    errors += [f'verdicts.{qid}: re-send the strongBecause of {qid} as re-derived this run, or lower it to lean by an update'
               for qid in strong_ids(ctx, scope) if qid not in verdicts and qid not in resent]
    shape = schema.problems(schema.PassReport, report, 'rulings', due=('rulings',))
    if shape:
        return errors + shape
    rulings = report['rulings']
    for index, ruling in enumerate(rulings):
        if not isinstance(ruling, dict) or ruling.get('question') not in current:
            errors.append(f'rulings[{index}]: `question` names a question of this round')
        elif error := disclosure_error(ruling, f'rulings[{index}]', schema.ChallengeRuling):
            errors.append(error)
    return errors


def record_pass(ctx: Context, report: dict) -> tuple[str, int, str]:
    schema.require(schema.PassReport, report, 'pass', due=('pass',))
    command = report['pass']
    observed = ctx.round['observed']
    if not ctx.codex and command not in observed:  # Codex has no console to observe its runs
        fail(words.no_run(command, ctx.round['pending']))
    origin = (observed.get(command) or {}).get('origin', 'model')
    kind, scoped = pass_kind(ctx, command)
    key, scope = pass_scope(ctx, command, kind, scoped)
    describe(ctx, report.get('round'), 'pass report', required=False)
    shape = schema.problems(schema.PassReport, report, 'checked', due=('checked',))
    checked, errors = ({}, shape) if shape else checked_of(report['checked'], {q['id'] for q in ctx.round['questions']})
    updates = report.get('updates') or []
    try:
        changes = apply_updates(ctx, updates, answered_rulings=kind == 'after answers')
    except ProtocolError as error:
        refuse_all([*errors, str(error)])
    covered = {*checked, *(u['id'] for u in updates if isinstance(u, dict) and isinstance(u.get('id'), str))}
    missing = [qid for qid in scope if qid not in covered]
    if missing:
        errors.append(f"a {command} pass covers {' '.join(scope)}: no `checked` entry or update for {' '.join(missing)}; add "
                      f'`"checked": {{"{missing[0]}": "<what you examined in it this run>"}}`')
    elif not (changes or checked or ctx.applied or ctx.added):
        errors.append(f'a {command} pass that changes nothing names what it checked: `"checked": {{"round": "<what you examined>"}}`')
    if command == 'challenge-rulings':
        errors += challenge_errors(ctx, report, scope, updates)
    refuse_all(errors)
    ctx.messages += [w for name, value in checked.items() for w in band_warning(f'checked.{name}', len(value), CHECKED_MAX, CHECKED_LIMIT)]
    if key:
        mark_covered(ctx, key, [*scope, *ctx.applied, *ctx.added])
    observed.pop(command, None)
    ctx.round['check']['last'][command] = {'changes': changes, 'origin': origin}
    ctx.round['lastPass'] = {'pass': command, 'questions': list(dict.fromkeys([*ctx.applied, *ctx.added]))}  # in or out of sequence
    ctx.log('pass', command=command, changes=changes, questions=list(dict.fromkeys(ctx.applied)), added=ctx.added,
            origin=origin, cycle=ctx.round['check']['cycle'], summary=report.get('summary'),
            checked=checked, kind=kind, scoped=scoped, covers=scope,
            **({'verdicts': report.get('verdicts') or {}, 'rulings': report['rulings']} if command == 'challenge-rulings' else {}))
    return command, changes, origin


def start_challenge(ctx: Context, kind: str, ids: list[str]) -> None:
    """One challenge-rulings pass outside the loop, after answers or a raise to strong."""
    ctx.round['check'].update(expect='challenge-rulings', converged=True, challenge={'kind': kind, 'ids': ids})
    ctx.set_pending('challenge-rulings', words.answers_args(ids) if kind == 'answers' else ' '.join(ids))


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
        check['challenged'] = False
    if check.get('challenge') and command == expected == 'challenge-rulings' and settled:
        return finish_challenge(ctx, changes)
    if nothing_to_check(ctx):
        return leave_check(ctx)
    if command != expected or not settled:
        if changes:
            check.pop('challenge', None)
            check.update(changes=0, expect='step-back', converged=False, challenged=False, confirming=True)
            ctx.set_pending('step-back', with_goal(ctx, rescope_ids(ctx)))
        return 'check'
    if command == 'step-back':
        if needs_related(ctx):
            check.update(changes=changes, confirming=True)
            ctx.set_pending('step-back', with_goal(ctx, rescope_ids(ctx)))
            return 'related'
        if not check.get('confirming'):
            check.update(changes=changes, confirming=True)
            ctx.set_pending('step-back', with_goal(ctx, rescope_ids(ctx)))
            return 'check'
        if changes:
            check['changes'] += changes
            return next_cycle(ctx)
        check.update(changes=0, confirming=False)
        return gate_ask(ctx)
    check.update(challenged=not changes, challengeRan=True)
    if changes and not check['askNow']:
        check.update(expect='step-back', confirming=True, changes=0, focusIds=[])
        ctx.set_pending('step-back', with_goal(ctx, rescope_ids(ctx)))
        return 'check'
    return gate_ask(ctx)


def pending_view(ctx: Context) -> dict | None:
    r = ctx.round
    if not r or r['step'] == 'closed' or not r['pending']:
        return None
    return dict(r['pending'])


def pass_kind(ctx: Context, command: str, settled: bool | None = None) -> tuple[str | None, list[str]]:
    """The pass kind and any intentionally focused question ids."""
    check = ctx.round['check']
    if check.get('expect') != command or not (settles(ctx, command) if settled is None else settled):
        return 'extra', []
    if command == 'step-back' and check.get('focusIds'):
        return 'focused', rescope_ids(ctx)
    if command == 'step-back' and check.get('confirming'):
        return 'confirming', []
    if command == 'challenge-rulings' and check.get('challenge'):
        spec = check['challenge']
        return ('after answers', []) if spec['kind'] == 'answers' else ('raised', spec['ids'])
    return None, []
