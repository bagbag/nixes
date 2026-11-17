"""protocol: the protocol engine for deciding sessions.

Owns each session's protocol state in <state dir>/<session>.protocol/ and tells the model the next step, one call
per step. Protocols: `round`, the decide protocol's Round from Collect to Record
(skills/role/protocols/decide.md#round, skills/shared/asking.md), and `release`, its Release
(decide.md#release), in the same run slot. `next` lists the seed questions of the next round and the model's stored
proposal (`next --set`), and what waits on the user. What a session was told (report formats, the question rows last printed, the open-item list, Durable owners)
is `state['told']`, cleared by `compacted` (docs/protocol-engine.md). The console mod reads `show --json`, `pending` and `scope`; the state file stays internal. Contract: console-spec 1a plus the lead's contract rulings (version 1).

Approvals (answers, the check cap's "ask now") count only from the person: `answer` takes origin `dialog` (the
console relays the dialog result of the batch out), `chat` (the model maps an answer the user typed, accepted only
when its quote appears in a message the console relayed with `say`), or `model-reported` in a Codex session (no
console: the model records the user's quoted words). A release's approval is an engine-issued question answered the
same ways, or a /release-round the person typed or pressed (`pass --origin composer|bridge|press`). Board writes run through `board`
with the session's actor. While the session's registered role is autopilot (away, in Claude and Codex alike) Ask opens no batch:
the model reports `act` or `park` per question (docs/protocol-engine.md, Away rounds).
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from .base import BIN, CHECK_CAP, Call, ProtocolError, VERBS, VERB_ORIGINS, Verb, _call, lines, utcnow
from .session import resolve_session
from .store import Store, new_round, next_id, next_records_round
from .boards import Board, board_root
from .engine import Context, PROTOCOLS, fail
from .record import abandon_note, refresh_board, release_claims
from .away import SWITCH_TO_SOLO
from .check import next_cycle, pending_view, refused_formats, start_scope
from .ask import batch_back, withdraw_away
from . import schema, words
from .release_set import start_release
from .release_files import start_files
from .release import stamp_release
from .seeds import next_text, proposal_row, set_proposal
from .views import (
    headline, instructions, show_json, show_markdown, show_questions, status_line
)
from .verbs import answer, answered_line, decline, defer_round, drop_report, edit_round, nudge_report, prune, require_origin, restart


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


def default_records() -> Path:
    """The private folder of a repository's board-less decision records, named as bin/scratch names the repository (r15-q71)."""
    call = _call.get()
    result = subprocess.run([sys.executable, str(BIN / 'scratch'), '__repo'], capture_output=True, text=True, env=call.env, cwd=call.cwd,
                            stdin=subprocess.DEVNULL)
    if result.returncode != 0 or not result.stdout.strip():
        fail(f"--no-board needs the repository's name from `scratch __repo`: {result.stderr.strip() or 'it printed nothing'}")
    data = call.env.get('XDG_DATA_HOME', '')
    if not data.startswith('/'):  # the XDG spec: a relative value is invalid and ignored
        data = str(Path(call.env.get('HOME') or Path.home()) / '.local' / 'share')
    return Path(data) / 'agents' / 'decisions' / result.stdout.strip()


def start(ctx: Context, name: str, report: dict, scope: str = 'board', records: Path | None = None,
          ids: list[str] | None = None, topic: str | None = None, proposal: int | None = None,
          subject: str | None = None) -> None:
    """`proposal`: the number of the stored proposal row the round starts from (its topic, ids, title and summary).
    `subject`: the artifact the round judges; the pre-pass presents and grounds it and its findings become the points."""
    if ctx.round and ctx.round['step'] != 'closed':
        fail(f"{ctx.round['protocol']} {ctx.round['id']} is open at {ctx.round['step']}: finish it, or `protocol abandon`"
             + (' (for a question to the user, abandon it: nothing is released, and `protocol start release` takes the same '
                'records again)' if ctx.round['protocol'] == 'release' else ''))
    if ctx.away and records is not None:
        fail(f'--no-board is refused on autopilot: nothing would track its records for ratification; {SWITCH_TO_SOLO}')
    schema.require(schema.Start, report)
    if name == 'release':
        if scope != 'board' or report or topic or proposal is not None or subject is not None:
            fail('start release takes record ids only (no --discussion, --topic, --proposal, --subject or stdin)'
                 ' and --no-board for the record files of a round without a board')
        if records is not None:
            start_files(ctx, records, ids or [])
        else:
            start_release(ctx, ids or [])
        return
    if subject is not None and not subject.strip():
        fail('--subject names the artifact the round judges: an id or a few words')
    if subject is not None and proposal is not None:
        fail("--subject is not for --proposal: a proposal row brings its own topic and items, while a subject's findings become the points")
    row = proposal_row(ctx, proposal, topic, ids or []) if proposal is not None else None
    if row:
        ids, topic = row.get('ids') or [], words.proposal_topic(row)
    if ids and (scope != 'board' or ctx.board is None):
        fail('start round <ids> names open board items: not with --discussion or --no-board')
    if ctx.board is None and records is None:
        fail('no board here: `start round --no-board` records the round as files in the records folder (`protocol records`)')
    ctx.state.pop('proposal', None)  # a round starts from its proposal or without one: the next proposal is made after it
    ctx.state['round'] = new_round(id=next_records_round(records, ctx.state) if records else next_id(ctx.state, 'round', 'r'), protocol=name,
                                   step='prepass', subject=(subject or '').strip() or None, first=[],
                                   repo=ctx.board.repo if ctx.board else None, scope=scope, records=str(records.resolve()) if records else None,
                                   named=list(dict.fromkeys(ids or [])), topic=(topic or '').strip() or None)
    if row:
        ctx.round.update(title=row['title'], summary=row['summary'])
    ctx.log('start', protocol=name, repo=ctx.state['round']['repo'], scope=scope, named=ctx.round['named'] or None,
            topic=ctx.round['topic'], subject=ctx.round['subject'])
    for point in report.get('points') or []:
        ctx.round['points'].append({'id': next_id(ctx.state, 'point', 'pt'), 'text': str(point['text'] if isinstance(point, dict) and 'text' in point else point)})
    ctx.go('prepass')


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


ORIGIN_MARK = ' *'


def detail(verb: Verb) -> str:
    """A verb's help epilog: example, origins and the stdin forms from the schema."""
    forms = [line for name in verb.stdin for line in ('', *(f'  {row}' if row else row for row in schema.render(schema.FORMS[name])))]
    return '\n'.join([f'example: {verb.example}',
                       *([f"--origin: {', '.join(verb.origins)}"] if verb.origins else []),
                       'stdin: ' + ('JSON on stdin; each form below is one case' + (' (each step\'s text prints its own example)' if verb.name == 'step' else '')
                                    if verb.stdin else 'none'), *forms])


def help_text() -> str:
    """Every verb with one example: the verbs sessions run first (`*`: the accepted --origin depends on the caller), then the
    console's. The sections are the Verb records' audiences."""
    def section(audiences: tuple[str, ...]) -> list[str]:
        return [f"  {verb.example}{ORIGIN_MARK if verb.audience == 'origin' else ''}\n      {verb.summary}" for verb in VERBS if verb.audience in audiences]
    return '\n'.join(['usage: protocol <verb> [args]; reports are JSON on stdin (`<` below); protocol help <verb> prints one verb in full', '',
                      *section(('session', 'origin')), '', '* origin-dependent: the accepted --origin differs by caller (protocol help <verb>)', '',
                      'console only:', *section(('console',))])


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
    origin.add_argument('--origin', help='who caused the call: ' + '; '.join(f"{v.name} {'|'.join(v.origins)}" for v in VERBS if v.origins)
                                         + '; other verbs model')
    commands = parser.add_subparsers(dest='command', required=True)
    subs = {v.name: commands.add_parser(v.name, help=v.summary, description=v.summary, epilog=detail(v), parents=[origin], allow_abbrev=False,
                                        formatter_class=argparse.RawDescriptionHelpFormatter) for v in VERBS}

    def verb(name: str):
        return subs[name]

    sub = verb('start')
    sub.add_argument('name', choices=sorted(PROTOCOLS))
    sub.add_argument('ids', nargs='*', help="release: the decided records (default: the decided records this session holds, "
                                            "minus dropped ones; with --no-board: record ids in the records folder, default the newest round's "
                                            "unreleased records); round: the open items to look at first (default: the whole list)")
    sub.add_argument('--topic', metavar='TEXT', help="round: the topic, '<title>: <summary>'")
    sub.add_argument('--proposal', metavar='N', type=int, help="round: start row N of the stored proposal; not with --topic or ids")
    sub.add_argument('--subject', metavar='ID|TEXT', help="round: the artifact the round judges (a design's CR id, a result, a proposal); "
                                                          "its pre-pass presents it with a verdict and findings, which become the points; not with --proposal")
    sub.add_argument('--discussion', action='store_true',
                     help="the pasted points alone (question-me): no board list at Collect; board items join through Related")
    sub.add_argument('--no-board', action='store_true',
                     help="a topic outside this repository's board: no board reads or writes; records are files in the repo's records folder "
                          "(`protocol records`), which a release takes the ids from")
    verb('records')
    sub = verb('restart')
    sub.add_argument('ids', nargs='+')
    sub.add_argument('--reason')
    sub = verb('next')
    sub.add_argument('--set', action='store_true', help='store the proposal (stdin)')
    sub = verb('show')
    sub.add_argument('ids', nargs='*', help='question ids: their options, examples, premises and marks')
    sub.add_argument('--json', action='store_true')
    sub = verb('status')
    sub.add_argument('--line', action='store_true', required=True)
    verb('help').add_argument('verb', nargs='?', choices=list(subs), metavar='verb', help='the verb to print in full: arguments, example and stdin forms')
    args = parser.parse_args(argv or ['help'])
    if args.command == 'help':
        _call.get().stdout.append((subs[args.verb].format_help() if args.verb else help_text() + '\n'))
        return 0
    if args.command == 'records':
        try:
            folder = default_records()
            _call.get().stdout.append(f'{folder}\n')
            return 0
        except ProtocolError as error:
            _call.get().stderr.append(f'protocol: {error}\n')
            return 1
    args.origin = args.origin or args.global_origin
    if args.command in VERB_ORIGINS and not args.origin:
        parser.error(f'{args.command} needs --origin')

    try:
        session, entry = resolve_session(args.session)
        store = Store(session)
        write = args.command not in ('show', 'pending', 'status', 'scope')  # `next` saves the board's release count
        with store.locked(write):
            state = store.load()
            open_round = state.get('round') if (state.get('round') or {}).get('step') not in (None, 'closed') else None
            if open_round:
                repo = open_round.get('repo')  # the round keeps the board it started on, or none (--no-board)
            elif args.command == 'start' and args.no_board:
                repo = None
            else:
                repo = str(board_root(_call.get().cwd)) if board_root(_call.get().cwd) else None
            board = Board(repo, entry.get('actor') or session[-8:]) if repo else None
            ctx = Context(store, state, entry, board)
            if args.command == 'start':
                args.no_board = default_records() if args.no_board else None
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
        ctx.state.pop('rows', None)
        ctx.store.log({'round': (ctx.round or {}).get('id'), 'event': 'compacted'})
        return words.COMPACTED
    if command == 'status':
        return status_line(ctx)
    if command == 'next' and not args.set:
        if ctx.board:
            refresh_board(ctx)
        return '\n'.join([*ctx.messages, next_text(ctx)])
    schema.CALLER.set(command)
    open_step = f"{ctx.round['protocol']} {ctx.round['step']}" if command == 'step' and ctx.round else ''
    report = schema.without_nulls(read_stdin(), schema.verb_forms(command, open_step))
    if command == 'next':
        return set_proposal(ctx, report)
    if command == 'start':
        start(ctx, args.name, report, 'discussion' if args.discussion else 'board', args.no_board, args.ids, args.topic, args.proposal, args.subject)
        prune(ctx.store)
        return instructions(ctx)
    if command == 'pass':
        schema.require(schema.PassRun, report)
    if command == 'pass' and report['command'] == 'release-round':
        note = stamp_release(ctx, args.origin, report.get('args') or '')
        ctx.messages.insert(0, note)
        ctx.complete = True  # the console does not forward this note: nothing here counts as told
        return json.dumps({**show_json(ctx), 'note': instructions(ctx)}, indent=1, ensure_ascii=False)
    if command == 'dropped':  # a late drop may follow the round's close
        drop_report(ctx, report)
        return ''
    if command == 'nudged':  # also with no round open: the press said so, and that use counts too
        nudge_report(ctx, report)
        return ''
    if command == 'scope':  # no round open: nothing to name
        return json.dumps(start_scope(ctx, report), ensure_ascii=False)
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
            unknown, accepted = schema.unknown_keys(open_step, report)
            if unknown:
                fail(words.step_unknown_keys(open_step, unknown, accepted))
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
    if command == 'defer':
        try:
            ctx.go(defer_round(ctx, report))
        except ProtocolError as error:
            raise ProtocolError(str(error), formats=words.DEFER_FORMAT) from None
        return instructions(ctx)
    if command == 'say':
        schema.require_needs(schema.Say, report)
        r['messages'].append({'text': report['text'], 'origin': args.origin, 'at': utcnow()})
        return json.dumps({**show_json(ctx), 'note': None}, indent=1, ensure_ascii=False)
    if command in ('answer', 'decline'):
        batch = r['batch'] if command == 'answer' else None
        try:
            note = answer(ctx, report, args.origin) if command == 'answer' else decline(ctx, report, args.origin)
        except ProtocolError as error:
            raise ProtocolError(str(error), formats=words.CHAT_FORMAT if args.origin == 'chat' else '') from None
        ctx.messages.insert(0, note)
        if args.origin != 'dialog':  # the model reads this result: the note alone (the console's dialog path reads the state)
            return instructions(ctx)
        return json.dumps({**show_json(ctx), 'note': instructions(ctx), **({'echo': answered_line(ctx, batch, report)} if batch else {})},
                          indent=1, ensure_ascii=False)
    if command == 'pass':
        pass_command = report['command']
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
            r['step'] = 'closed'
            return words.release_abandoned(headline(ctx), ctx.messages, r['id'], ctx.board is not None)
        release_claims(ctx)
        r['step'] = 'closed'
        if ctx.board and any(q.get('recorded') not in (None, 'deferred', 'file') for q in r['questions']):
            refresh_board(ctx)  # records written before the abandon are decided and held
        return words.round_abandoned(headline(ctx), ctx.messages, r['id'], abandon_note(r['questions']))
    fail(f'unknown command {command}')
