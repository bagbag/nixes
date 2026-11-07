"""protocol: the protocol engine for deciding sessions.

Owns each session's protocol state in <state dir>/<session>.protocol/ and tells the model the next step, one call
per step. Protocols: `round`, the decide protocol's Round from Collect to Record
(skills/role/protocols/decide.md#round, skills/shared/asking.md), and `release`, its Release
(decide.md#release), in the same run slot. `next` lists the seed questions of the next round and the model's stored
proposal (`next --set`), and what waits on the user. What a session was told (report formats, the question list per check cycle, the open-item list, Durable owners)
is `state['told']`, cleared by `compacted` (README). The console mod reads `show --json` and `pending`; the state file stays internal. Contract: console-spec 1a plus the lead's contract rulings (version 1).

Approvals (answers, the check cap's "ask now") count only from the person: `answer` takes origin `dialog` (the
console relays the dialog result of the batch out), `chat` (the model maps an answer the user typed, accepted only
when its quote appears in a message the console relayed with `say`), or `model-reported` in a Codex session (no
console: the model records the user's quoted words). A release's approval is an engine-issued question answered the
same ways, or a /release-round the person typed or pressed (`pass --origin composer|bridge|press`). Board writes run through `board`
with the session's actor. While the session's registered role is autopilot (away, in Claude and Codex alike) Ask opens no batch:
the model reports `act` or `park` per question (README, Away rounds).
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from .base import CHECK_CAP, Call, PASSES, ProtocolError, VERB_ORIGINS, _call, lines, utcnow
from .session import resolve_session
from .store import Store, next_id
from .boards import Board, board_root
from .engine import Context, PROTOCOLS, fail
from .told import forget_runs
from .record import abandon_note, refresh_board, release_claims
from .away import SWITCH_TO_SOLO
from .check import next_cycle, pending_view, refused_formats
from .ask import batch_back, withdraw_away
from . import words
from .release_set import start_release
from .release import stamp_release
from .seeds import next_text, proposal_row, set_proposal
from .views import (
    headline, history_events, history_text, instructions, show_json, show_markdown, show_questions, status_line
)
from .verbs import answer, answered_line, decline, drop_report, edit_round, prune, require_origin, restart


# CLI

def read_stdin() -> dict:
    source = _call.get().stdin
    text = source if isinstance(source, str) else '' if source is None or source.isatty() else source.read()
    if not text.strip():
        return {}
    try:
        value = json.loads(text)
    except ValueError as error:
        fail(f'stdin is not JSON: {error}')
    if not isinstance(value, dict):
        fail('stdin must be a JSON object')
    return value


def start(ctx: Context, name: str, report: dict, scope: str = 'board', records: Path | None = None,
          ids: list[str] | None = None, topic: str | None = None, proposal: int | None = None) -> None:
    """`proposal`: the number of the stored proposal row the round starts from (its topic, ids, title and summary)."""
    if ctx.round and ctx.round['step'] != 'closed':
        fail(f"{ctx.round['protocol']} {ctx.round['id']} is open at {ctx.round['step']}: finish it, or `protocol abandon`"
             + (' (for a question to the user, abandon it: nothing is released, and `protocol start release` takes the same '
                'records again)' if ctx.round['protocol'] == 'release' else ''))
    if ctx.away and records is not None:
        fail(f'--no-board is refused on autopilot: nothing would track its records for ratification; {SWITCH_TO_SOLO}')
    if name == 'release':
        if scope != 'board' or records is not None or report or topic or proposal is not None:
            fail('start release takes record ids only (no --discussion, --no-board, --topic, --proposal or stdin)')
        start_release(ctx, ids or [])
        return
    row = proposal_row(ctx, proposal, topic, ids or []) if proposal is not None else None
    if row:
        ids, topic = row.get('ids') or [], words.proposal_topic(row)
    if ids and (scope != 'board' or ctx.board is None):
        fail('start round <ids> names open board items: not with --discussion or --no-board')
    if ctx.board is None and records is None:
        fail('no board here: name the records folder with `start round --no-board <dir>`')
    ctx.state.pop('proposal', None)  # a round starts from its proposal or without one: the next proposal is made after it
    forget_runs(ctx)
    ctx.state['round'] = {'id': next_id(ctx.state, 'round', 'r'), 'protocol': name, 'step': 'collect',
                          'repo': ctx.board.repo if ctx.board else None, 'scope': scope,
                          'records': str(records.resolve()) if records else None, 'items': [],
                          'named': list(dict.fromkeys(ids or [])), 'topic': (topic or '').strip() or None,
                          'points': [], 'classes': {}, 'selected': [], 'questions': [], 'check': {}, 'pending': None,
                          'observed': {}, 'batch': None, 'batchSeq': 0, 'messages': []}
    if row:
        ctx.round.update(title=row['title'].strip(), **({'summary': row['summary'].strip()} if row.get('summary') else {}))
    ctx.log('start', protocol=name, repo=ctx.state['round']['repo'], scope=scope, named=ctx.round['named'] or None,
            topic=ctx.round['topic'])
    for point in report.get('points') or []:
        ctx.round['points'].append({'id': next_id(ctx.state, 'point', 'pt'), 'text': str(point['text'] if isinstance(point, dict) and 'text' in point else point)})
    ctx.go('collect')


class Exit(Exception):
    def __init__(self, status: int, stderr: str = ''):
        self.status, self.stderr = status, stderr


class Parser(argparse.ArgumentParser):
    """argparse that reports into the current call (stdout/stderr buffers, `Exit`) instead of the process."""

    def __init__(self, **kwargs):
        if sys.version_info >= (3, 14):
            kwargs.setdefault('color', False)  # usage text must not depend on the terminal
        super().__init__(**kwargs)

    def print_help(self, file=None):
        _call.get().stdout.append(self.format_help())

    def print_usage(self, file=None):
        _call.get().stdout.append(self.format_usage())

    def exit(self, status=0, message=None):
        raise Exit(status, message or '')

    def error(self, message):
        raise Exit(2, self.format_usage() + f'{self.prog}: error: {message}\n')


def main(argv: list[str] | None = None) -> int:
    code, out, err = run_cli(sys.argv[1:] if argv is None else argv, os.environ, Path.cwd(), sys.stdin)
    sys.stdout.write(out)
    sys.stderr.write(err)
    return code


def run_cli(argv: list[str], env: Mapping[str, str], cwd: Path, stdin) -> tuple[int, str, str]:
    """The CLI as a function: (exit code, stdout, stderr). stdin is the JSON text or a file object."""
    call = Call(env, Path(cwd), stdin)
    token = _call.set(call)
    try:
        code = cli(argv)
    except Exit as stop:
        call.stderr.append(stop.stderr)
        code = stop.status
    finally:
        _call.reset(token)
    return code, ''.join(call.stdout), ''.join(call.stderr)


def cli(argv: list[str]) -> int:
    # No abbreviations: `--orig dialog` must not pass as --origin (person origins are refused by exact name).
    parser = Parser(prog='protocol', description=__doc__.split('\n\n')[0], allow_abbrev=False)
    parser.add_argument('--session', help='session id (the console passes it); default: CODEX_THREAD_ID, else the '
                                          'registered session of this environment')
    parser.add_argument('--origin', dest='global_origin', help='who caused the call (also accepted after the verb)')
    origin = Parser(add_help=False, allow_abbrev=False)
    origin.add_argument('--origin', help='who caused the call: answer dialog|chat|model-reported, decline '
                                         'dialog|model-reported, pass composer|bridge|press|plugin|model, say '
                                         'composer|bridge, dropped plugin; other verbs model')
    commands = parser.add_subparsers(dest='command', required=True)

    def verb(name: str, text: str):
        return commands.add_parser(name, help=text, parents=[origin], allow_abbrev=False)

    sub = verb('start', 'open a protocol run; stdin {"points": [...]} adds pasted points')
    sub.add_argument('name', choices=sorted(PROTOCOLS))
    sub.add_argument('ids', nargs='*', help="release: the decided records (default: the decided records this session holds, "
                                            "minus dropped ones); round: the open items to look at first (default: the whole list)")
    sub.add_argument('--topic', metavar='TEXT', help="round: the topic, '<title>: <summary>'")
    sub.add_argument('--proposal', metavar='N', type=int, help="round: start row N of the stored proposal; not with --topic or ids")
    sub.add_argument('--discussion', action='store_true',
                     help="the pasted points alone (question-me): no board list at Collect; board items join through Related")
    sub.add_argument('--no-board', metavar='DIR', type=Path,
                     help="a topic outside this repository's board: no board reads or writes; records go to DIR")
    verb('step', "submit the current step's report (stdin JSON); prints the next step")
    verb('answer', 'record answers (stdin JSON); prints show --json with a note')
    verb('decline', 'a declined batch returns to ready (stdin JSON); prints show --json')
    verb('pass', 'a pass started, or the person typed or pressed /release-round (stdin {"command","args","pending"}); prints '
                 'show --json')
    verb('edit', "apply the user's requested change to the questions (stdin {\"updates\", \"quote\"}); no pass for wording, options "
                 "or a mark lowered to lean; a new question or changed recommendation gets the scoped check, a raise to strong one challenge")
    verb('say', "store the person's message for the chat quote check (stdin {\"text\"})")
    verb('dropped', 'the console dropped a stale action (stdin {"kind": "pass", "id"} or {"kind": "batch", "marker"})')
    sub = verb('restart', 'questions back to draft after a criterion answer; the check loop reruns')
    sub.add_argument('ids', nargs='+')
    sub.add_argument('--reason')
    sub = verb('next', 'the seed questions, the open questions by topic and the stored proposal; --set stores the proposal (stdin)')
    sub.add_argument('--set', action='store_true', help='store the proposal: stdin {"rounds": [{"title", "summary", "estimate": '
                                                        '{"questions", "unblocks"}, "why", "fresh", "ids"?}]}')
    verb('compacted', "the session's context was compacted: what it was told prints in full again")
    verb('resume', 'continue a paused check loop')
    verb('abandon', 'close the open round without records')
    sub = verb('show', 'the round as markdown, --json (the console contract), or <ids>: those questions whole')
    sub.add_argument('ids', nargs='*', help='question ids: their options, previews, premises and marks')
    sub.add_argument('--json', action='store_true')
    verb('pending', 'the pending pass as JSON, or null')
    sub = verb('status', 'one recovery line')
    sub.add_argument('--line', action='store_true', required=True)
    sub = verb('history', 'passes by origin, answers, declines, restarts per round')
    sub.add_argument('--all', action='store_true', help='every session in the state dir')
    sub.add_argument('--json', action='store_true', help='the raw events')
    args = parser.parse_args(argv)
    args.origin = args.origin or args.global_origin
    if args.command in VERB_ORIGINS and not args.origin:
        parser.error(f'{args.command} needs --origin')

    try:
        session, entry = resolve_session(args.session)
        store = Store(session)
        write = args.command not in ('show', 'pending', 'status', 'history')  # `next` saves the board's release count
        with store.locked(write):
            state = store.load()
            open_round = state.get('round') if (state.get('round') or {}).get('step') not in (None, 'closed') else None
            if open_round:
                repo = open_round.get('repo')  # the round keeps the board it started on, or none (--no-board)
            elif args.command == 'start' and args.no_board is not None:
                repo = None
            else:
                repo = str(board_root(_call.get().cwd)) if board_root(_call.get().cwd) else None
            board = Board(repo, entry.get('actor') or session[-8:]) if repo else None
            ctx = Context(store, state, entry, board)
            require_origin(ctx, args.command, args.origin)
            output = run(ctx, args)
            if write:
                store.save(state)
                store.flush()
        _call.get().stdout.append(output + '\n')
        return 0
    except ProtocolError as error:
        _call.get().stderr.append(lines(f'protocol: {error}', error.formats) + '\n')
        log_refusal(args, error)
        return 1
    except Exit:
        raise
    except Exception as error:  # a defect: nothing was saved; say so instead of a stack trace
        message = f'internal error ({type(error).__name__}: {error}); nothing was saved'
        _call.get().stderr.append(f'protocol: {message}\n')
        log_refusal(args, ProtocolError(message))
        return 1


def log_refusal(args, error: ProtocolError) -> None:
    """Refused calls go to the history (the state stays unchanged): friction /retro and the pane's log can see."""
    with contextlib.suppress(ProtocolError, OSError, ValueError):
        session, _ = resolve_session(args.session)
        store = Store(session)
        if (store.dir / 'state.json').is_file():
            round_id = (json.loads((store.dir / 'state.json').read_text(encoding='utf-8')).get('round') or {}).get('id')
            store.log({'round': round_id, 'event': 'refused', 'verb': args.command, 'error': str(error)[:300]})
            store.flush()


def run(ctx: Context, args) -> str:
    command = args.command
    if command == 'show':
        ctx.complete = True  # the model asked: everything, whatever it was told
        if args.ids:
            return show_questions(ctx, args.ids)
        return json.dumps(show_json(ctx), indent=1, ensure_ascii=False) if args.json else show_markdown(ctx)
    if command == 'pending':
        return json.dumps(pending_view(ctx))
    if command == 'compacted':
        ctx.state['told'] = []
        ctx.store.log({'round': (ctx.round or {}).get('id'), 'event': 'compacted'})
        return words.COMPACTED
    if command == 'status':
        return status_line(ctx)
    if command == 'history':
        events = history_events(ctx.store, args.all)
        return '\n'.join(json.dumps(e, ensure_ascii=False) for e in events) if args.json else history_text(events)
    if command == 'next' and not args.set:
        if ctx.board:
            refresh_board(ctx)
        return '\n'.join([*ctx.messages, next_text(ctx)])
    report = read_stdin()
    if command == 'next':
        return set_proposal(ctx, report)
    if command == 'start':
        start(ctx, args.name, report, 'discussion' if args.discussion else 'board', args.no_board, args.ids, args.topic, args.proposal)
        prune(ctx.store)
        return instructions(ctx)
    if command == 'pass' and report.get('command') == 'release-round':
        note = stamp_release(ctx, args.origin, report.get('args') or '')
        ctx.messages.insert(0, note)
        ctx.complete = True  # the console does not forward this note: nothing here counts as told
        return json.dumps({**show_json(ctx), 'note': instructions(ctx)}, indent=1, ensure_ascii=False)
    if command == 'dropped':  # a late drop may follow the round's close
        drop_report(ctx, report)
        return ''
    r = ctx.round
    if not r or r['step'] == 'closed':
        fail('no open round: protocol start round')
    if command == 'step' and ctx.away and r['batch']:
        ctx.go(withdraw_away(ctx))  # its questions settle as away at this step: the report waits for the new step text
        return instructions(ctx)
    if command == 'step':
        step = PROTOCOLS[r['protocol']].steps[r['step']]
        before = copy.deepcopy(ctx.state)
        try:
            ctx.go(step.accept(ctx, report))
        except ProtocolError as error:
            raise ProtocolError(str(error), formats=refused_formats(ctx, step, report, before)) from None
        return instructions(ctx)
    if command == 'edit':
        try:
            ctx.go(edit_round(ctx, report))
        except ProtocolError as error:
            raise ProtocolError(str(error), formats=words.EDIT_FORMAT) from None
        return instructions(ctx)
    if command == 'say':
        if not isinstance(report.get('text'), str) or not report['text'].strip():
            fail('say: stdin needs {"text"}')
        r['messages'].append({'text': report['text'], 'origin': args.origin, 'at': utcnow()})
        return json.dumps({**show_json(ctx), 'note': None}, indent=1, ensure_ascii=False)
    if command in ('answer', 'decline'):
        batch = r['batch'] if command == 'answer' and not report.get('afkTimeoutMs') else None
        try:
            note = answer(ctx, report, args.origin) if command == 'answer' else decline(ctx, report, args.origin, 'declined')
        except ProtocolError as error:
            raise ProtocolError(str(error), formats=words.CHAT_FORMAT if args.origin == 'chat' else '') from None
        ctx.messages.insert(0, note)
        if args.origin != 'dialog':  # the model reads this result: the note alone (the console's dialog path reads the state)
            return instructions(ctx)
        return json.dumps({**show_json(ctx), 'note': instructions(ctx), **({'echo': answered_line(ctx, batch, report)} if batch else {})},
                          indent=1, ensure_ascii=False)
    if command == 'pass':
        pass_command = report.get('command')
        if pass_command not in PASSES:
            fail(f"`command` must be one of {', '.join(PASSES)}")
        # Observation only: the pending pass stays until its report (`step`), so the console can tell a pass turn
        # that ended without one.
        stamp = report.get('pending')
        r['observed'][pass_command] = {'origin': args.origin, 'pending': stamp if isinstance(stamp, str) else None}
        ctx.log('pass-start', command=pass_command, args=report.get('args') or '', origin=args.origin,
                pending=report.get('pending'))
        return json.dumps({**show_json(ctx), 'note': None}, indent=1, ensure_ascii=False)
    if command == 'restart':
        restart(ctx, args.ids, args.reason)
        return instructions(ctx)
    if command == 'resume':
        check = r['check']
        if r['step'] != 'check' or not check.get('paused'):
            fail('the check loop is not paused')
        check.update(paused=False, cap=check['cycle'] + CHECK_CAP)
        if r['batch'] and r['batch']['cap']:
            r['batch'] = None
        next_cycle(ctx)
        return instructions(ctx)
    if command == 'abandon':
        if r['batch']:
            batch_back(ctx)
        r['pending'] = None
        ctx.log('abandoned', step=r['step'])
        if r['protocol'] == 'release':  # the records stay decided and held
            r['step'], r['closedAt'] = 'closed', utcnow()
            return words.release_abandoned(headline(ctx), ctx.messages, r['id'])
        release_claims(ctx)
        r['step'] = 'closed'
        r['closedAt'] = utcnow()
        if ctx.board and any(q.get('recorded') not in (None, 'deferred', 'file') for q in r['questions']):
            refresh_board(ctx)  # records written before the abandon are decided and held
        return words.round_abandoned(headline(ctx), ctx.messages, r['id'], abandon_note(r['questions']))
    fail(f'unknown command {command}')
