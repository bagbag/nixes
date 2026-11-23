#!/usr/bin/env python3
"""Two-clone tests of shared boards through the real `board`, real bd and a local bare git remote.

    python3 -B bin/test-shared-board.py [--board <path>] [--only <name>,<name>] [--serial] [--seconds <s>] [--soak <s>]

A full run starts every group as its own `--only` run at once (each with its own folder and servers) and prints their
results in order; `--serial` runs them one after another in this process.

A run removes its folder and stops its servers on SIGTERM, SIGINT and SIGHUP too, and at start stops the Dolt servers of
earlier runs whose process is gone (shared-board.* folders in /tmp, marked by their `runner.pid`).

Needs bd and Dolt, which the validator's build sandbox lacks: bin/test-agent-configs.py holds the fake-bd checks, this holds
the ones only real clones can show. Everything lives in a temp folder, and every server it starts is stopped.
After a bd upgrade, run the soak too (`--soak 40`, or `--only soak`): it is the check that retires the write retry
(board WRITE_RETRY_ERROR), so ordinary runs skip it.
"""
from __future__ import annotations

import contextlib
import argparse
import collections
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--board', default=str(HERE / 'board'))
parser.add_argument('--only', default='')
parser.add_argument('--seconds', type=float, default=6, help='the sync window and pull interval to test with')
parser.add_argument('--soak', type=float, default=0, help='seconds of parallel writing; 0 skips the soak unless --only names it')
parser.add_argument('--serial', action='store_true', help='run the groups one after another instead of as parallel --only runs')
parser.add_argument('--idle', action='store_true', help='internal (the cleanup test): start up, then wait for a signal')
options = parser.parse_args()
if shutil.which('bd') is None:  # the gate's contract (board-checks.sh): a suite that cannot start exits 127, "cannot run", not a failed check
    print('test-shared-board: bd is not installed; the suite needs real bd, Dolt and git clones', file=sys.stderr)
    sys.exit(127)
BOARD = str(Path(options.board).resolve())
REGISTRY = str(Path(BOARD).parent / 'session')
ROOT = Path(tempfile.mkdtemp(prefix='shared-board.', dir='/tmp'))
RUNNER_PID = 'runner.pid'  # in the run's folder: tells a later run whether this one is still alive
(ROOT / RUNNER_PID).write_text(str(os.getpid()))
ROLES = {'lead': 1, 'solo': 2, 'agent': 3, 'none': 4, 'autopilot': 5}  # 'none' registers no role


def session(side: str, role: str) -> str:
    return f'c0000000-0000-4000-8000-00000000{ord(side[0]):02x}{ROLES[role]:02x}'  # each clone its own: another machine's sessions are unknown here


failures: list[str] = []
retries = collections.Counter()


def base_env(side: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CODEX_', 'CLAUDE_CODE_SESSION')) and k not in ('BEADS_ACTOR', 'BD_ACTOR')}
    env.update(AGENT_SESSION_STATE_DIR=str(ROOT / f'state-{side}'), AGENT_BOARD_SYNC_SECONDS=str(options.seconds),
               GIT_CONFIG_GLOBAL=str(ROOT / 'gitconfig'))
    return env


def raw(side: str, *args: str, timeout: float = 200):
    """bd without --readonly, through `board bd --raw --yes`: setup and maintenance no board verb offers (an explicit id, dolt, sync, sql, delete)."""
    result = subprocess.run([sys.executable, '-B', BOARD, 'bd', '--raw', '--yes', *args], cwd=ROOT / side, capture_output=True, text=True, timeout=timeout,
                            env={**base_env(side), 'BD_NO_REMOTE_ADOPT': '1'}, input='')
    return result.returncode, result.stdout, result.stderr, 0.0


def board_create_args(args: tuple[str, ...], stdin: str | None) -> tuple[list[str], str | None]:
    """A bd-create-style call as board create takes it: the description by stdin, labels as --label, ids printed without --silent."""
    out, text, at = [], None, 0
    while at < len(args):
        arg = args[at]
        if arg == '--silent':
            at += 1
        elif arg == '--description':
            text, at = args[at + 1], at + 2
        elif arg == '--stdin':
            text, at = stdin or '', at + 1
        elif arg in ('-l', '--labels'):
            out += ['--label', args[at + 1]]
            at += 2
        else:
            out.append(arg)
            at += 1
    return (out + ['--description-file', '-'], text) if text is not None else (out, stdin)


def run(side: str, *args: str, role: str | None = 'lead', stdin: str | None = None, timeout: float = 200):
    if args[:1] == ('create',) and '--id' in args:
        return raw(side, *args)
    if args[:1] == ('create',):
        converted, stdin = board_create_args(args[1:], stdin)
        args = ('create', *converted)
    env = base_env(side)
    if role:
        env['CLAUDE_CODE_SESSION_ID'] = session(side, role)
    started = time.time()
    try:
        result = subprocess.run([sys.executable, '-B', BOARD, *args], cwd=ROOT / side, capture_output=True, text=True, timeout=timeout,
                                env=env, input=stdin if stdin is not None else '')
    except subprocess.TimeoutExpired:
        return 124, '', 'timeout', time.time() - started
    retries['retried'] += result.stderr.count('foreign key conflicts')
    return result.returncode, result.stdout, result.stderr, time.time() - started


def run_piped(side: str, *args: str, role: str = 'lead', timeout: float = 200) -> tuple[int, str]:
    """A board call whose stdout and stderr share one pipe, as `2>&1 | tail` gives a session: what it reads last is what it acts on."""
    env = base_env(side)
    env['CLAUDE_CODE_SESSION_ID'] = session(side, role)
    result = subprocess.run([sys.executable, '-B', BOARD, *args], cwd=ROOT / side, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    return result.returncode, result.stdout


def bd(side: str, *args: str, **kwargs):
    """A bd call as the board offers it: the writes go through their board verbs (create, close --force, block, link, update, label); setup
    and maintenance no verb offers (dolt, sync, sql, delete, conflicts) run `board bd --raw --yes`."""
    if args[:1] == ('create',):
        return run(side, 'create', *args[1:], **kwargs)
    if args[:1] == ('q',):
        return run(side, 'bd', *args, **kwargs)  # refused by --readonly, not run raw
    if args[:1] == ('move',):
        return run(side, *args, **kwargs)
    if args[:1] == ('close',):
        reason = args[args.index('--reason') + 1]
        return run(side, 'close', args[1], '--reason', reason, *(['--force'] if '--force' in args else []), **kwargs)
    if args[:2] == ('dep', 'add') and '--type' not in args:
        return run(side, 'wait', args[2], '--on', args[3], '--for', 'test setup', **kwargs)
    if args[:2] == ('dep', 'add'):
        return run(side, 'link', args[2], args[3], '--type', args[args.index('--type') + 1], **kwargs)
    if any(arg.startswith(('queue:', 'for:')) for arg in args) and kwargs.get('role', 'lead') not in ('agent', 'none'):
        return raw(side, *args)  # moves belong to send/route; the setup here changes the labels directly
    if args[:1] == ('update',) and '--claim' in args:
        return run(side, 'bd', *args, **kwargs)  # refused read-only
    if args[:1] == ('update',) and '--claim' not in args and '--assignee' not in args:  # the user hold is set by hand here: no board verb does it
        words = []
        flags = {'--add-label': '--label', '--remove-label': '--unlabel'}
        for arg in args:
            words.append(flags.get(arg, arg))
        return run(side, *words, **kwargs)
    if args[:2] in (('label', 'add'), ('label', 'remove')):
        return run(side, 'update', args[2], '--label' if args[1] == 'add' else '--unlabel', args[3], **kwargs)
    if args[:1] in (('list',), ('ready',)) or args[:2] == ('dolt', 'remote') and args[2:3] == ('list',) or args[:1] == ('sql',) and args[-1].lstrip().lower().startswith('select'):
        return run(side, 'bd', *args, **kwargs)
    if kwargs.get('role', 'lead') is None:
        return raw(side, *args)
    return run(side, 'bd', '--raw', '--yes', *args, **kwargs)


def set_field(side: str, item: str, field: str, text: str, role: str | None = 'lead'):
    """board field export, edit the file, board field apply."""
    rc, out, err, took = run(side, 'field', 'export', item, '--field', field, role=role)
    if rc:
        return rc, out, err, took
    Path(out.strip().splitlines()[0]).write_text(text, encoding='utf-8')
    return run(side, 'field', 'apply', item, '--field', field, role=role)


def check(ok: bool, what: str, detail: object = '') -> None:
    print(('  ok   ' if ok else '  FAIL ') + what + (f': {detail}' if detail != '' and not ok else ''), flush=True)
    if not ok:
        failures.append(what)


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, env=base_env('a')).stdout


def items(side: str) -> dict[str, dict]:
    _, out, _, _ = bd(side, 'export')
    return {row['id']: row for row in map(json.loads, filter(str.strip, out.splitlines())) if row.get('_type', 'issue') == 'issue'}


def create(side: str, title: str, *flags: str, role: str | None = 'lead', kind: str = 'change-request') -> str:
    if kind in ('bug', 'design', 'spike', 'feature', 'cleanup'):  # a kind is a label on a task: no rule reads it
        flags, kind = (*flags, '--label', f'kind:{kind}'), 'task'
    if '--status' in flags or kind == 'epic':  # a state no verb writes (create sets no status), and the epic scope root autopilot's --root reads
        queue = [] if '--parent' in flags else ['--labels', 'queue:' + git('config', 'agents.person', cwd=ROOT / side).strip()]  # what board create gives a top-level item
        rc, out, err, _ = raw(side, 'create', title, '--type', kind, '--description', 'x', '--silent', *queue, *flags)
        if rc:
            raise RuntimeError(f'create {title}: {err}{out}')
        return out.strip().splitlines()[-1]
    holds = ['--holds', 'none'] if '-t' in flags and flags[flags.index('-t') + 1] == 'decision' else []
    rc, out, err, _ = bd(side, 'create', title, '-t', kind, '--description', 'x', '--silent', *flags, *holds, role=role)
    if rc:
        raise RuntimeError(f'create {title}: {err}{out}')
    return out.strip().splitlines()[-1]


def settle(*sides: str) -> None:
    """Every clone holds every other's writes: manual syncs, the same a person would run. Each sync pushes what its clone
    holds by then, so one pass forward and one back over all but the last reach everyone (a, b, a)."""
    for side in (*sides, *sides[-2::-1]):
        bd(side, 'sync')


def commits(side: str) -> int:
    _, out, _, _ = bd(side, 'sql', '--json', 'select count(*) c from dolt_log')
    return int(json.loads(out)[0]['c'])


def sync_state(side: str) -> dict:
    try:
        return json.loads((ROOT / side / '.beads' / 'board-sync' / 'state.json').read_text())
    except OSError:
        return {}


def wait_until(test, seconds: float, step: float = 0.5) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if test():
            return True
        time.sleep(step)
    return test()


def waits() -> list[int]:
    out = subprocess.run(['pgrep', '-f', '_sync-wait'], capture_output=True, text=True).stdout.split()
    found = []
    for pid in out:
        cwd = subprocess.run(['lsof', '-a', '-p', pid, '-d', 'cwd', '-Fn'], capture_output=True, text=True).stdout
        if str(ROOT) in cwd or f'/private{ROOT}' in cwd:
            found.append(int(pid))
    return found


def setup() -> None:
    (ROOT / 'gitconfig').write_text('[user]\n\tname = t\n\temail = t@example.invalid\n')
    git('init', '-q', '--bare', 'remote.git')
    git('init', '-q', '--bare', 'empty.git')
    git('init', '-q', '-b', 'main', 'seed')
    git('commit', '-q', '--allow-empty', '-m', 'init', cwd=ROOT / 'seed')
    git('push', '-q', str(ROOT / 'remote.git'), 'main', cwd=ROOT / 'seed')
    for side, name in (('a', 'anna'), ('b', 'ben')):
        git('clone', '-q', 'remote.git', side)
        git('config', 'agents.person', name, cwd=ROOT / side)
        git('commit', '-q', '--allow-empty', '-m', 'init', cwd=ROOT / side)  # a clone parks edits against HEAD
        for role in ROLES:
            if role == 'none':
                continue
            env = {**base_env(side), 'CLAUDE_CODE_SESSION_ID': session(side, role)}
            subprocess.run(['bash', REGISTRY, 'activate', role, *(['--pulls', 'implement,review,plan'] if role == 'agent' else [])],
                           cwd=ROOT / side, env=env, capture_output=True, check=True)
    rc, out, err, _ = bd('a', 'init', '--server', '--stealth', '--prefix', 'sb', '--skip-hooks', '--skip-agents', role=None)
    if rc:
        raise RuntimeError(f'init: {err}{out}')
    for key, value in (('status.custom', 'decided:wip,in_force:active,in_review:wip,passed:wip'), ('types.custom', 'design,change-request')):
        bd('a', 'config', 'set', key, value, role=None)
    for key, value in (('custom.board.target', git('symbolic-ref', '--short', 'HEAD', cwd=ROOT / 'a').strip()), ('custom.board.setup', 'true'), ('custom.board.checks', 'true'), ('custom.board.look', 'before'), ('custom.board.view', 'code'), ('custom.board.model', '1')):
        bd('a', 'config', 'set', key, value, role=None)
    bd('a', 'dolt', 'commit', '-m', 'config', role=None)


def beads_files(side: str) -> list[str]:
    """What of a board sits in a clone's folder: a failed join leaves none of it."""
    return sorted(path.name for path in (ROOT / side).iterdir() if path.name.startswith('.beads'))


def servers(side: str) -> list[str]:
    out = subprocess.run(['pgrep', '-f', f'{ROOT.name}/{side}/.beads/'], capture_output=True, text=True).stdout
    return out.split()


def remotes(side: str) -> str:
    out = bd(side, 'dolt', 'remote', 'list', role=None)[1].strip()
    return '' if out.startswith('No remotes') else out


def mark(side: str) -> dict:
    try:
        return json.loads((ROOT / side / '.beads' / 'board-shared.json').read_text())
    except OSError:
        return {}


CLOSED: list[str] = []


def t_unshared() -> None:
    parent = create('a', 'unshared parent')
    child = create('a', 'unshared child', '--parent', parent)
    check('.' not in child, 'unshared board: a child has a plain id', child)
    CLOSED.append(create('a', 'closed top-level'))
    bd('a', 'close', CLOSED[0], '--force', '--reason', 'closed before the share, which labels it too')
    rc, out, err, took = run('a', 'health')
    check(rc == 0 and not (ROOT / 'a/.beads/board-sync').exists(), 'unshared board: no sync state, no queue filter', err)
    check('other queues' not in out and 'set your person' not in err, 'unshared board: output as before', err)
    rc, _, err, _ = run('a', 'health', '--queue', 'ben')
    check(rc == 1 and 'not shared' in err, 'unshared board: --queue says there are no queues', err)
    rc, _, err, _ = bd('a', 'dolt', 'remote', 'add', 'origin', f'git+file://{ROOT}/remote.git', '--allow-git-origin', role=None)
    check(rc == 0, 'a hand-added remote is added (board no longer comments on it)', err)
    rc, out, err, _ = run('a', 'health')
    check(rc == 0 and 'other queues' not in out and not (ROOT / 'a/.beads/board-sync').exists(), 'only board\'s mark shares: a remote alone does not', err)
    bd('a', 'dolt', 'remote', 'remove', 'origin', role=None)
    # Field size guard (r13-q74) through real bd: stdin is judged and still reaches bd.
    long = 'x' * 2001
    rc, _, err, _ = bd('a', 'create', 'long', '-t', 'task', '--description', long, '--silent')
    check(rc == 2 and 'description is 2001 characters' in err, 'a work item over 2000 characters is refused', err)
    rc, out, err, _ = bd('a', 'create', 'long stdin', '-t', 'task', '--stdin', '--silent', stdin=long)
    check(rc == 2 and 'description is 2001 characters' in err and not out.strip(), 'the same through stdin', err)
    rc, out, err, _ = bd('a', 'create', 'short stdin', '-t', 'task', '--stdin', '--parent', parent, '--silent', stdin='short text')
    made = out.strip().splitlines()[-1] if rc == 0 and out.strip() else ''
    check(made != '' and items('a').get(made, {}).get('description') == 'short text', 'a short description through stdin reaches bd', err or out)
    rc, out, err, _ = bd('a', 'create', 'record', '-t', 'decision', '--description', long, '--parent', parent, '--holds', 'none', '--silent')
    check(rc == 0, 'a decision is not limited', err)
    bd('a', 'dolt', 'commit', '-m', 'unshared items')


def t_share_join() -> None:
    before = commits('a')
    rc, out, err, _ = run('a', 'share', f'git+file://{ROOT}/empty.git', '--yes', role=None)
    check(rc == 1 and 'empty repository' in err and not remotes('a'), 'share: a completely empty repository is refused before any change', err + out)
    rc, out, err, _ = run('a', 'share', role=None)
    check(rc == 1 and 'git emails' in out and 'remote.git' in out and '--yes' in out, 'share without --yes: says what goes out and where, then stops', err + out)
    check(not remotes('a') and commits('a') == before and not mark('a') and 'auto-commit: batch' not in (ROOT / 'a/.beads/config.yaml').read_text(),
          'share without --yes: no remote, no config, no commit, no mark', remotes('a'))
    rc, out, err, _ = run('a', 'share', '--yes', role=None)
    check(rc == 0 and mark('a').get('remote') == 'origin', 'share --yes: default remote is the project repository, marked shared after the push', err + out)
    check('2 top-level items labelled queue:anna' in out, 'share: existing top-level unlabelled items go to the sharer', out)
    check('queue:anna' in items('a')[CLOSED[0]].get('labels', []), 'share: closed top-level items are labelled too')
    rc, out, err, _ = run('a', 'share', role=None)
    check(rc == 0 and '0 top-level' in out and 'git emails' not in out, 'share again: quiet, nothing relabelled', err + out)
    rc, out, err, _ = run('a', 'share', f'git+file://{ROOT}/empty.git', role=None)
    check(rc == 1 and 'already syncs' in err, 'share with another url: refused, the existing remote stays', err + out)
    exclude = (ROOT / 'b/.git/info/exclude').read_text()
    rc, out, err, _ = run('b', 'join', f'git+file://{ROOT}/missing.git', role=None)
    check(rc == 1 and not beads_files('b') and not servers('b'), 'a failed join removes what it made and stops its server', (err, beads_files('b')))
    check((ROOT / 'b/.git/info/exclude').read_text() == exclude and not git('config', '--get', 'beads.role', cwd=ROOT / 'b').strip(),
          'a failed join leaves the git config as it was')
    git('init', '-q', '--bare', 'nodata.git')
    git('push', '-q', str(ROOT / 'nodata.git'), 'main', cwd=ROOT / 'seed')
    rc, out, err, _ = run('b', 'join', f'git+file://{ROOT}/nodata.git', role=None)
    check(rc == 1 and 'no board data' in err and 'board join <' in err and not beads_files('b') and not servers('b'),
          'join where no board is: says so, asks for the address, leaves nothing', (err, beads_files('b')))
    rc, out, err, _ = run('b', 'join', role=None)
    check(rc == 0 and 'joined' in out and mark('b').get('remote') == 'origin', 'join: from the project repository, after the failed ones', err + out)
    check(run('b', 'health')[0] == 0, 'join: the board works after a failed join')
    rc, out, err, _ = run('b', 'join', role=None)
    check(rc == 0 and 'nothing to do' in out, 'join again: does nothing', err + out)
    check(not git('status', '--short', cwd=ROOT / 'b').strip(), 'join: .beads stays out of project history', git('status', '--short', cwd=ROOT / 'b'))
    check(not git('config', '--get', 'core.hooksPath', cwd=ROOT / 'b').strip(), 'join: no beads git hooks')
    check(not (ROOT / 'b/AGENTS.md').exists(), 'join: no agent files')
    check(git('config', '--get', 'beads.role', cwd=ROOT / 'b').strip() == 'maintainer', 'join: beads.role set')
    config = (ROOT / 'b/.beads/config.yaml').read_text()
    for needle in ('auto-commit: batch', 'auto-start: false', 'on-close: error', 'decision: Question,Decision,Rule owner', 'events-journal: true', 'require-description: true'):
        check(needle in config, f'join: config.yaml has {needle}')
    _, out, _, _ = bd('b', 'config', 'get', 'status.custom')
    check('in_review' in out, 'join: the custom statuses travel', out)
    _, out, _, _ = bd('b', 'config', 'get', 'min_hash_length')
    check('5' in out, 'join: min_hash_length travels', out)
    rc, out, err, _ = run('b', 'share', role=None)
    check(rc == 0 and '0 top-level' in out, "a second person's share takes nothing", err + out)
    git('clone', '-q', 'remote.git', 'unset')
    rc, out, err, _ = run('unset', 'join', role=None)
    check(rc == 1 and 'agents.person' in err and not (ROOT / 'unset/.beads').exists(), 'join with no person at no terminal: says how to set it, changes nothing', err)


def t_child_ids() -> None:
    epic = create('a', 'ids epic', '-l', 'topic:x')
    settle('a', 'b')
    rc, out, err, _ = raw('a', 'create', 'atomic status child', '--type', 'task', '--status', 'passed',
                          '--description', 'x', '--metadata', '{"hold":"plan"}', '--deps', f'parent-child:{epic}',
                          '--no-inherit-labels', '--labels', 'topic:x', '--silent')
    atomic_id = out.strip()
    atomic = items('a').get(atomic_id, {})
    check(rc == 0 and atomic_id and '.' not in atomic_id and atomic.get('status') == 'passed'
          and (atomic.get('metadata') or {}).get('hold') == 'plan'
          and any(dep.get('type') == 'parent-child' and dep.get('depends_on_id') == epic for dep in atomic.get('dependencies', [])),
          'child ids: native --deps creates a plain id with parent edge, kind and status in one write', {"id": atomic_id, "row": atomic, "error": err})
    check('topic:x' in atomic.get('labels', []) and not any(label.startswith('queue:') for label in atomic.get('labels', [])),
          'child ids: atomic linked child keeps non-queue parent labels and inherits queue through ancestry', atomic.get('labels'))
    settle('a', 'b')
    synced_atomic = items('b').get(atomic_id, {})
    check(bool(synced_atomic) and synced_atomic.get('status') == 'passed'
          and any(dep.get('type') == 'parent-child' and dep.get('depends_on_id') == epic for dep in synced_atomic.get('dependencies', [])),
          'child ids: atomic plain-id child syncs to the other clone', synced_atomic)
    rc, out, err, _ = raw('a', 'close', atomic_id, '--reason', 'close test-only active status row', '--json')  # a passed task is no board shape: no verb closes it
    check(rc == 0 and items('a')[atomic_id].get('status') == 'closed',
          'child ids: close the temporary passed row after checking its status and sync', err + out)
    settle('a', 'b')
    made = [create('a', 'a child', '--parent', epic), create('b', 'b child', f'--parent={epic}')]
    check(all('.' not in item for item in made), 'child ids: --parent on both sides makes plain ids', made)
    settle('a', 'b')
    rows = items('a')
    check(all(i in rows for i in made), 'child ids: both sides under one parent sync', made)
    child = rows[made[0]]
    check('topic:x' in child.get('labels', []) and not any(label.startswith('queue:') for label in child.get('labels', [])),
          'child ids: other labels copied, the queue label not', child.get('labels'))
    check(any(dep['type'] == 'parent-child' and dep['depends_on_id'] == epic for dep in child.get('dependencies', [])), 'child ids: linked to the parent')
    _, out2, _, _ = bd('a', 'sql', '--json', f'select count(*) c from child_counters where parent_id = "{epic}"')
    check(json.loads(out2)[0]['c'] == 0, 'child ids: child_counters untouched', out2)
    rc, out, err, _ = bd('a', 'q', 'quick child', '--parent', epic)
    check(rc != 0 and 'board create' in err and not out.strip(), 'q is refused read-only, naming board create', out + err)
    tracked = create('a', 'tracked')
    both = create('a', 'two link kinds', '--deps', f'relates-to:{tracked}', '--parent', epic)
    kinds = {(dep['type'], dep['depends_on_id']) for dep in items('a')[both].get('dependencies', [])}
    check(kinds == {('relates-to', tracked), ('parent-child', epic)}, "child ids: a node's dep and its parent link both land (real bd; a revision's tracks link and its parent do alike)", kinds)
    rc, out, err, _ = bd('a', 'create', 'no such parent', '-t', 'task', '--description', 'x', '--parent', 'sb-nope')
    check(rc != 0, 'child ids: an unknown parent fails', out)
    # Links (real bd): a blocking edge between two new work items is bd's own write; a pair with another link kind refuses before record writes.
    plan = ROOT / 'links-plan.json'
    plan.write_text(json.dumps({'nodes': [{'key': 'one', 'title': 'first new task', 'type': 'task', 'description': 'x'},
                                          {'key': 'two', 'title': 'second new task', 'type': 'task', 'description': 'x', 'waits_on': [{'on': 'one', 'for': 'the first task'}]}],
                                'edges': []}))
    rc, out, err, _ = run('a', 'create', '--graph', str(plan))
    made = dict(line.split() for line in out.splitlines() if len(line.split()) == 2)
    check(rc == 0 and not err.strip() and any(dep['type'] == 'blocks' and dep['depends_on_id'] == made.get('one') for dep in items('a').get(made.get('two'), {}).get('dependencies', [])),
          'links: a plan edge between two new work items is written by bd, no refusal', (rc, out, err))
    draft = ROOT / 'record.md'
    draft.write_text('## Question\nq\n## Alternatives Considered\na\n## Decision\nd\n## Rationale\nr\n## Rule owner\no\n')

    def decision(title: str) -> str:
        item = create('a', title, '-t', 'decision', kind='decision')
        run('a', 'claim', item)
        return item

    def status_of(item: str) -> str:
        return items('a')[item]['status']

    def linked(source: str, target: str, kind: str) -> bool:
        return any(dep['type'] == kind and dep['depends_on_id'] == target for dep in items('a')[source].get('dependencies', []))

    # Record replaces the pair's previous link. Release brings the new ruling into force and supersedes the old one.
    released = decision('released ruling')
    check(run('a', 'ruling', 'record', released, str(draft))[0] == 0 and run('a', 'ruling', 'release', released)[0] == 0 and status_of(released) == 'in_force',
          'links: the released ruling is set up')
    newer = decision('newer ruling')
    run('a', 'link', newer, released, '--type', 'relates-to')
    rc, out, err, _ = run('a', 'ruling', 'record', newer, str(draft), '--replaces', released)
    check(rc == 0 and status_of(newer) == 'decided' and status_of(released) == 'in_force'
          and linked(newer, released, 'tracks') and not linked(newer, released, 'relates-to'),
          'record --replaces: recording replaces a related link with a pending revision and keeps the old ruling in force', (rc, err, out))
    rc, out, err, _ = run('a', 'ruling', 'release', newer)
    check(rc == 0 and status_of(newer) == 'in_force' and status_of(released) == 'closed' and linked(released, newer, 'supersedes'),
          'record --replaces: release supersedes the old ruling', (rc, err, out))

    # Decided records stay pending through Record retries. Release supersedes them without releasing them first.
    newer = decision('replacement for two drafts')
    first, second = decision('first old ruling'), decision('second old ruling')
    for old in (first, second):
        check(run('a', 'ruling', 'record', old, str(draft))[0] == 0, 'links: an old ruling records')
    run('a', 'link', newer, first, '--type', 'relates-to')
    rc, out, err, _ = run('a', 'ruling', 'record', newer, str(draft), '--replaces', f'{first},{second}')
    check(rc == 0 and status_of(newer) == 'decided' and all(status_of(old) == 'decided' and linked(newer, old, 'tracks') for old in (first, second)),
          'record --replaces: both decided drafts remain pending until release', (rc, err, out))
    rc, out, err, _ = run('a', 'ruling', 'record', newer, str(draft), '--replaces', f'{first},{second}')
    check(rc == 0 and all(status_of(old) == 'decided' and linked(newer, old, 'tracks') for old in (first, second)),
          'record --replaces: a Record retry keeps the same pending revisions', (rc, err, out))
    rc, out, err, _ = run('a', 'ruling', 'release', first, second, newer)
    check(rc == 0 and status_of(newer) == 'in_force' and all(status_of(old) == 'closed' and linked(old, newer, 'supersedes') for old in (first, second)),
          'record --replaces: releasing the set supersedes both drafts', (rc, err, out))

    # Resume a release stopped after its status write and one of its supersedes.
    first, second, third = decision('first old ruling b'), decision('second old ruling b'), decision('third old ruling b')
    for old in (first, second, third):
        run('a', 'ruling', 'record', old, str(draft))
    newer = decision('newer ruling b')
    rc, out, err, _ = run('a', 'ruling', 'record', newer, str(draft), '--replaces', f'{first},{second},{third}')
    check(rc == 0, 'record --replaces: the release retry fixture records all revisions', (rc, err, out))
    rc, _, err, _ = run('a', 'ruling', 'release', first)
    check(rc != 0 and newer in err and status_of(first) == 'decided',
          'record --replaces: a pending draft cannot be released separately from its replacement', err)
    rc, out, err, _ = raw('a', 'update', newer, '--status', 'in_force', '--assignee', '')
    check(rc == 0 and status_of(newer) == 'in_force', 'record --replaces: the interrupted release has written its status', (rc, err, out))
    check(run('a', 'ruling', 'supersede', first, '--with', newer)[0] == 0 and status_of(first) == 'closed', 'record --replaces: the first old is superseded by hand (a stop mid-way)')
    rc, out, err, _ = run('a', 'ruling', 'release', newer)
    check(rc == 0 and all(status_of(old) == 'closed' and linked(old, newer, 'supersedes') for old in (first, second, third)),
          'record --replaces: a Release retry finishes pending supersedes', (rc, err, out))
    # A hold on the old ruling only blocks the operation that supersedes it.
    held, newest = decision('held old ruling'), decision('newest ruling')
    run('a', 'ruling', 'record', held, str(draft))
    run('a', 'unclaim', held)
    rc, out, err, _ = run('a', 'claim', held, role='solo')
    solo = session('a', 'solo')[-8:]
    check(rc == 0 and items('a')[held].get('assignee') == solo,
          'record --replaces: the old ruling is held by another session', (rc, err, out))
    rc, out, err, _ = run('a', 'ruling', 'record', newest, str(draft), '--replaces', held)
    check(rc == 0 and status_of(newest) == 'decided' and status_of(held) == 'decided' and linked(newest, held, 'tracks'),
          'record --replaces: recording can stage a revision of a held draft', (rc, err, out))
    rc, out, err, _ = run('a', 'ruling', 'release', newest)
    check(rc != 0 and solo in err and status_of(newest) == 'decided' and status_of(held) == 'decided'
          and items('a')[held].get('assignee') == solo and linked(newest, held, 'tracks'),
          'record --replaces: release refuses before writing while another session holds the old ruling', (rc, err, out))
    bd('a', 'sync')


def t_queues() -> None:
    epic = create('a', 'anna epic')
    child = create('a', 'anna child', '--parent', epic)
    ben = create('b', 'ben top')
    settle('a', 'b')
    rows = items('a')
    check('queue:anna' in rows[epic].get('labels', []), 'queues: a top-level item takes its creator')
    check(not any(label.startswith('queue:') for label in rows[child].get('labels', [])), 'queues: a child carries no label of its own')
    _, out, _, _ = run('a', 'queue')
    check(child in out and ben not in out, "default list: mine only", out)
    _, out, _, _ = run('a', 'health', '--items', 'ready')
    check(child in out and ben not in out and 'other queues: ben ' in out, 'health: other queues as counts', out)
    _, out, _, _ = run('a', 'health', '--items', 'ready', '--queue', 'ben')
    check(ben in out and child not in out, 'health --queue expands a person')
    _, out, _, _ = run('a', 'console')
    check('other queues: ben' in (json.loads(out).get('queueLine') or ''), 'console: other queues as counts', out[:300])
    _, out, _, _ = run('a', 'health', '--items', 'ready', '--queue', 'all')
    check(ben in out and child in out, 'health --queue all expands everyone')
    _, out, _, _ = run('a', 'related', 'ben', 'top')
    check(ben in out and 'queue ben' in out, 'related: every queue, naming the queue on hits from others', out)
    _, out, _, _ = run('a', 'related', 'ben', 'top', '--json')
    check(next(row for row in json.loads(out)['items'] if row['id'] == ben).get('queue') == 'ben', 'related --json names the queue')
    rc, out, _, _ = run('a', 'show', ben)
    check(rc == 0 and 'queue ben' in out, 'show: any item, with its queue', out)
    rc, _, err, _ = run('a', 'claim', ben, role='agent')
    check(rc == 1 and "ben's queue" in err and f'board route anna {ben}' in err, 'claim by id on another queue: refused, says how to move', err)
    rc, _, err, _ = run('a', 'take', ben)
    check(rc == 1 and "ben's queue" in err, 'take on another queue: refused', err)
    question = create('b', 'ben question', '-t', 'decision')
    settle('a', 'b')
    rc, _, err, _ = run('a', 'claim', question)
    check(rc == 1 and "ben's queue" in err, 'claim by id: questions refused alike', err)
    rc, _, err, _ = bd('a', 'update', ben, '--claim', role='agent')
    check(rc != 0 and 'board claim' in err, 'bd update --claim is refused read-only, naming board claim', err)
    rc, out, _, _ = run('a', 'claim', role='agent')
    check(rc == 0 and ben not in out and 'claimed' in out, 'bare claim: mine only', out)
    run('a', 'unclaim', out.split()[1], '--resume', 'claim it again', role='agent') if rc == 0 else None
    # A blocker in another queue, always listed.
    blocked = create('a', 'anna waits')
    bd('a', 'dep', 'add', blocked, ben)
    settle('a', 'b')
    _, out, _, _ = run('a', 'health')
    check('blocking yours' in out and ben in out, "other people's items blocking mine are listed", out)
    # Parents in different queues.
    mixed = create('a', 'two parents', '--parent', epic)
    raw('a', 'dep', 'add', mixed, ben, '--type', 'parent-child')
    settle('a', 'b')
    _, out, _, _ = run('b', 'health')
    check('unrouted' in out and mixed in out and 'queues anna,ben' in out, 'parents in different queues: unrouted and listed', out)
    _, out, _, _ = run('a', 'queue')
    check(mixed not in out.split('unrouted')[0], 'parents in different queues: nobody claims it by default', out)
    rc, _, err, _ = run('a', 'claim', mixed, role='agent')
    check(rc == 1 and 'unrouted' in err and f'board route <person> {mixed}' in err, 'claim by id on an unrouted item: refused until routed', err)
    rc, _, err, _ = run('a', 'take', mixed)
    check(rc == 1 and 'unrouted' in err, 'take on an unrouted item: refused', err)
    rc, _, err, _ = run('a', 'route', 'anna', mixed, role='agent')
    check(rc == 1 and 'only lead' in err, 'route: an agent is refused', err)
    rc, _, err, _ = run('a', 'route', 'anna', mixed, role='autopilot')
    check(rc == 1 and 'only lead' in err, 'route: autopilot is refused', err)
    rc, out, err, _ = run('a', 'route', 'anna', mixed, ben)
    rows = items('a')
    check(rc == 0 and 'queue:anna' in rows[mixed]['labels'] and 'queue:anna' in rows[ben]['labels'] and 'queue:ben' not in rows[ben]['labels'],
          'route: several items in one command, replacing their queue label', err + out)
    rc, out, err, _ = run('a', 'claim', mixed, role='agent')
    check(rc == 0, 'a routed item claims', err)
    run('a', 'unclaim', mixed, '--resume', 'claim it again', role='agent')
    rc, _, err, _ = run('a', 'route', 'ben', ben, role='solo')
    check(rc == 0 and 'queue:ben' in items('a')[ben]['labels'], 'route: solo moves', err)
    # Moving an epic moves its children.
    rc, _, err, _ = bd('a', 'update', epic, '--remove-label', 'queue:anna', '--add-label', 'queue:ben')
    check(rc == 0, 'lead moves an epic', err)
    settle('a', 'b')
    _, out, _, _ = run('b', 'queue')
    check(child in out, 'a moved epic takes its children along', out)
    _, out, _, _ = run('a', 'queue')
    check(child not in out, 'a moved child leaves the old queue', out)
    bd('a', 'update', epic, '--remove-label', 'queue:ben', '--add-label', 'queue:anna')
    settle('a', 'b')
    # A closed parent's label still routes.
    closing = create('a', 'closed parent')
    kid = create('a', 'kid of closed', '--parent', closing)
    settle('a', 'b')
    bd('a', 'close', closing, '--force', '--reason', 'closed to test a closed parent still routes its child')
    settle('a', 'b')
    _, out, _, _ = run('a', 'queue')
    check(kid in out, "a closed parent's queue still routes its child", out)
    # Unset person.
    git('config', '--unset', 'agents.person', cwd=ROOT / 'a')
    rc, _, err, _ = run('a', 'health')
    check('agents.person' in err, 'person unset: every command says how to set it', err)
    rc, _, err, _ = run('a', 'claim', role='agent')
    check(rc == 1 and 'agents.person' in err, 'person unset: a bare claim says how', err)
    git('config', 'agents.person', 'anna', cwd=ROOT / 'a')


def t_moves() -> None:
    item = create('a', 'to move')  # an item moves between change requests: the queue rule is about the parent it takes
    parent_b = create('b', 'ben parent')
    settle('a', 'b')
    child = create('a', 'to reparent', '--parent', item, kind='task')
    for role in ('agent', 'none'):
        for args in (('update', item, '--label', 'queue:ben'), ('update', item, '--unlabel', 'queue:anna'), ('move', child, '--to', parent_b),
                     ('create', 'for ben', '-t', 'task', '--description', 'x', '-l', 'queue:ben')):
            rc, _, err, _ = bd('a', *args, role=role)
            check(rc in (1, 2) and ('only lead and solo' in err or 'board send' in err or 'board route' in err), f'{role} session refused: {" ".join(args[:2])}', err)
    for args in (('label', 'add', item, 'queue:ben'), ('sql', f"delete from labels where issue_id='{item}'")):
        rc, _, err, _ = run('a', 'bd', *args, role='agent')
        check(rc != 0 and 'read-only' in err, f'board bd refuses a write read-only: {" ".join(args[:2])}', err)
    env_rc = subprocess.run([sys.executable, '-B', BOARD, 'move', child, '--to', parent_b], cwd=ROOT / 'a', capture_output=True, text=True,
                            env={**base_env('a'), 'BEADS_ACTOR': f"{session('a', 'lead')[-8:]}/worker01", 'CLAUDE_CODE_SESSION_ID': session('a', 'lead')})
    check(env_rc.returncode == 2 and 'only lead and solo' in env_rc.stderr, "a lead's worker is refused", env_rc.stderr)
    rc, _, err, _ = bd('a', 'update', item, '--add-label', 'topic:free', role='agent')
    check(rc == 0, 'agent: other label changes pass', err)
    plan = ROOT / 'label-plan.json'
    plan.write_text(json.dumps({'nodes': [{'key': 'n', 'title': 'loose label', 'description': 'x', 'type': 'task', 'labels': ['loose']}]}))
    for what, args in (('create --label', ('create', 'loose label', '-t', 'task', '--description', 'x', '--label', 'loose')),
                       ('create --graph', ('create', '--graph', str(plan))), ('update --label', ('update', item, '--label', 'human')),
                       ('update --label', ('update', item, '--label', 'loose'))):
        rc, _, err, _ = run('a', *args, role='agent')
        check(rc != 0 and 'a label starts with' in err, f'a label outside the shapes check reports is refused: {what}', err)
    rc, _, err, _ = run('a', 'update', item, '--unlabel', 'loose', role='agent')
    check(rc == 0, 'a label of any shape can still be removed', err)
    rc, _, err, _ = bd('a', 'move', child, '--to', parent_b, role='lead')
    check(rc == 0, 'lead: reparent passes', err)
    rc, _, err, _ = bd('a', 'label', 'add', item, 'queue:ben', role='solo')
    check(rc == 0, 'solo: moves pass', err)
    rc, _, err, _ = bd('a', 'label', 'remove', item, 'queue:anna', role=None)
    check(rc == 0, "a person's terminal is not limited", err)
    rows = items('a')
    check('queue:ben' in rows[item].get('labels', []) and 'queue:anna' not in rows[item].get('labels', []), 'moves took effect')
    settle('a', 'b')


def t_window() -> None:
    settle('a', 'b')
    check(wait_until(lambda: not waits(), options.seconds * 3), 'no wait left running before the burst', waits())
    before = commits('a')
    started = time.time()
    rc, _, err, took = raw('a', 'create', 'burst first', '-t', 'task', '--description', 'x', '--silent')
    check(took < 4, f'a write returns at once with the wait detached ({took:.1f} s)', took)
    made = [raw('a', 'create', f'burst {n}', '-t', 'task', '--description', 'x', '--silent')[1].strip() for n in range(5)]  # board create commits per call; the window is about bd's own writes
    check(len(waits()) == 1, 'one wait for the board', waits())
    check(commits('a') == before, 'writes stay uncommitted during the window')
    if not wait_until(lambda: commits('a') > before and not waits(), options.seconds * 4):
        check(False, 'the wait synced and ended', commits('a'))
    elapsed = time.time() - started
    check(elapsed >= options.seconds - 1, f'sync waited for the window ({elapsed:.1f} s of {options.seconds} s)')
    check(commits('a') - before <= 2 and commits('a') - before >= 1, 'a burst goes out as one commit (a merge may add one)', commits('a') - before)
    bd('b', 'dolt', 'pull')
    check(all(item in items('b') for item in made), 'the burst reached the other clone')
    # The product path: board create commits once per call (bd's create --graph ignores dolt.auto-commit=batch, accepted), so the count is not
    # pinned. What must hold: one wait for the burst, every item reaches the other clone, nothing is left unsent.
    settle('a', 'b')
    check(wait_until(lambda: not waits(), options.seconds * 3), 'no wait left running before the board create burst', waits())
    made = [create('a', f'board burst {n}', kind='task') for n in range(5)]
    check(len(waits()) == 1, 'one wait for a burst of board create calls', waits())
    check(wait_until(lambda: not waits(), options.seconds * 4), 'the wait ended after the board create burst')
    check(not (ROOT / 'a' / '.beads' / 'board-sync' / 'unsent').exists(), 'nothing left unsent after the board create burst')
    bd('b', 'dolt', 'pull')
    check(all(item in items('b') for item in made), 'a board create burst reached the other clone')


def t_pull() -> None:
    settle('a', 'b')
    item = create('a', 'to arrive')
    check(wait_until(lambda: not waits(), options.seconds * 4), 'sent by the wait')
    time.sleep(options.seconds + 0.5)
    run('b', 'queue', '--queue', 'all')  # the command itself pulled before reading
    rc, out, _, _ = run('b', 'show', item)
    check(rc == 0 and 'to arrive' in out, 'pull before command: a read sees the other side after the interval', out)
    # Nothing is pulled while a write waits: the pull would commit it and undo the grouping.
    create('a', 'second arrival')
    check(wait_until(lambda: not waits(), options.seconds * 4), 'sent by the wait')
    create('b', 'unsent here')
    before = commits('b')
    (ROOT / 'b/.beads/board-sync/pulled').unlink()  # a pull is due
    run('b', 'health')
    check(commits('b') == before, 'no pull while a write waits to be sent', commits('b') - before)
    check(wait_until(lambda: not waits(), options.seconds * 4), 'b sent')
    # One session pulls; others carry on.
    time.sleep(options.seconds + 0.5)
    results = []
    threads = [threading.Thread(target=lambda: results.append(run('b', 'health')[0])) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    check(results == [0, 0, 0, 0], 'parallel commands with a pull due all finish', results)
    # board watch pulls again on each poll, not only at its start.
    time.sleep(options.seconds + 0.5)
    gap = options.seconds + 0.5
    pulled, started = ROOT / 'b/.beads/board-sync/pulled', time.time()
    rc, out, err, _ = run('b', 'watch', '--queue', 'all', '--root', item, '--interval', str(gap), '--timeout', str(gap + 1))
    check(rc == 3 and pulled.stat().st_mtime >= started + gap - 0.3, 'wait: a poll pulls when one is due', (rc, out, err, pulled.stat().st_mtime - started))
    # A dead remote: the command gives up on time.
    time.sleep(options.seconds + 0.5)
    hidden = ROOT / 'remote.git.hidden'
    (ROOT / 'remote.git').rename(hidden)
    rc, _, err, took = run('b', 'health')
    check(rc == 0 and took < 9, f'a failed pull does not stop the command ({took:.1f} s)', err)
    hidden.rename(ROOT / 'remote.git')
    bd('b', 'sync')


def t_manual_and_dead_wait() -> None:
    settle('a', 'b')
    check(wait_until(lambda: not waits(), options.seconds * 3), 'idle')
    item = create('a', 'manual sync')
    rc, out, err, _ = bd('a', 'sync')
    check(rc == 0, 'a manual sync works, also mid-window', err + out)
    bd('b', 'dolt', 'pull')
    check(item in items('b'), 'a manual sync sent the write')
    check(wait_until(lambda: not waits(), options.seconds * 3), 'the wait ends with nothing left')
    # A dead wait restarts at the next command.
    item = create('a', 'orphan')
    pids = waits()
    check(len(pids) == 1, 'a wait is running', pids)
    for pid in pids:
        os.kill(pid, signal.SIGKILL)
    time.sleep(0.3)
    check(not waits(), 'the wait is dead')
    run('a', 'health')
    check(len(waits()) == 1, 'the next command restarts it', waits())
    check(wait_until(lambda: not waits(), options.seconds * 3), 'the new wait finishes')
    bd('b', 'dolt', 'pull')
    check(item in items('b'), 'the write went out despite the dead wait')


def t_soak() -> None:
    settle('a', 'b')
    expected: dict[str, str] = {}
    errors = collections.Counter()
    lock = threading.Lock()
    end = time.time() + (options.soak or 40)
    count = [0]

    def writer(side: str, number: int) -> None:
        n = 0
        while time.time() < end:
            n += 1
            rc, out, err, _ = bd(side, 'create', f'{side}{number}-{n}', '-t', 'task', '--description', 'v0', '--silent', role='lead')
            with lock:
                count[0] += 1
                if rc:
                    errors[(err.strip().splitlines() or ['?'])[-1][:90]] += 1
            if rc:
                continue
            item = out.strip().splitlines()[-1]
            expected[item] = 'v0'
            rc, _, err, _ = set_field(side, item, 'description', 'v1')
            if rc:
                with lock:
                    errors[(err.strip().splitlines() or ['?'])[-1][:90]] += 1
            else:
                expected[item] = 'v1'
            time.sleep(0.5)

    threads = [threading.Thread(target=writer, args=(side, k)) for side in 'ab' for k in (1, 2, 3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    check(not errors, f'parallel writers: {count[0]} creates without an error', dict(errors))
    print(f'  note: {retries["retried"]} foreign key retries so far', flush=True)
    wait_until(lambda: not waits(), options.seconds * 4)
    settle('a', 'b')
    a_items, b_items = items('a'), items('b')
    lost = [item for item, value in expected.items() if a_items.get(item, {}).get('description') != value]
    check(not lost, f'parallel writers: nothing lost of {len(expected)}', lost[:5])
    check(a_items.keys() == b_items.keys(), 'parallel writers: same items on both sides')
    check(not sync_state('a').get('kind') and not sync_state('b').get('kind'), 'parallel writers: no problem reported', (sync_state('a'), sync_state('b')))


def pulled_just_now(side: str) -> None:
    """The side's commands skip their due pull for a window: its next write stays ahead of what the other side just sent,
    however long the setup took (a slow parallel run would otherwise pull it first)."""
    (ROOT / side / '.beads' / 'board-sync' / 'pulled').touch()


def conflicted() -> str:
    """Delete against edit: b's next sync stops."""
    settle('a', 'b')
    wait_until(lambda: not waits(), options.seconds * 3)
    victim = create('a', 'victim')
    settle('a', 'b')
    bd('a', 'delete', victim, '--force')
    bd('a', 'sync')
    pulled_just_now('b')
    rc, out, err, _ = run('b', 'field', 'export', victim, '--field', 'description')
    if rc == 0:
        Path(out.strip().splitlines()[0]).write_text('edited on b', encoding='utf-8')
        pulled_just_now('b')
        rc, _, err, _ = run('b', 'field', 'apply', victim, '--field', 'description')
    check(rc == 0, 'conflict setup: b edits the item a deleted', err)
    return victim


def t_stopped() -> None:
    victim = conflicted()
    check(wait_until(lambda: sync_state('b').get('kind') == 'conflict', options.seconds * 4), 'the wait reports the conflict', sync_state('b'))
    rc, out, err, _ = run('b', 'health')
    check(rc == 0 and 'merge conflict' in err and 'board bd --raw --yes conflicts resolve' in err, 'stopped sync: a read prints the problem and the fix', err)
    check(sum('merge conflict' in row for row in err.splitlines()) == 1, 'stopped sync: one line', err)
    rc, out, err, _ = run('b', 'console')
    check(rc == 0 and 'merge conflict' in (json.loads(out).get('sync') or ''), 'stopped sync: the console field names it', out[:200])
    check('other queues' in (json.loads(out).get('queueLine') or '') or json.loads(out).get('queueLine') is None, 'console: the queue line', out[:200])
    rc, _, err, _ = bd('b', 'create', 'refused', '-t', 'task', '--description', 'x')
    check(rc != 0 and 'Merge conflict detected' in err and 'retry' not in err, 'stopped sync: beads refuses writes, no retry', err)
    rc, out, err, _ = bd('b', 'conflicts', 'resolve', victim, '--theirs')
    if rc:
        rc, out, err, _ = bd('b', 'conflicts', 'resolve', '--all', '--table', 'issues', '--theirs')
    check(rc == 0, 'stopped sync: bd conflicts resolve clears it', err + out)
    _, _, err, _ = run('b', 'health')
    check('merge conflict' not in err, 'stopped sync: the line goes with the conflict', err)
    check(wait_until(lambda: not waits() and not sync_state('b').get('kind'), options.seconds * 4), 'stopped sync: the wait finishes the send', sync_state('b'))
    run('b', 'health')
    settle('a', 'b')
    check(items('a').keys() == items('b').keys(), 'after the conflict: same items')
    # An id collision.
    wait_until(lambda: not waits(), options.seconds * 3)
    bd('a', 'create', 'same a', '-t', 'task', '--description', 'x', '--id', 'sb-collide', '--silent')
    bd('a', 'sync')
    pulled_just_now('b')
    bd('b', 'create', 'same b', '-t', 'task', '--description', 'x', '--id', 'sb-collide', '--silent')
    check(wait_until(lambda: sync_state('b').get('kind') == 'conflict', options.seconds * 4), 'an id collision reports a conflict', sync_state('b'))
    rc, _, err, _ = run('b', 'position')
    check('CALL DOLT_MERGE' in err and 'board bd --raw --yes rename' in err, 'the line carries the collision fix', err)
    rc, out, err, _ = bd('b', 'sql', "CALL DOLT_MERGE('--abort')")
    check(rc == 0, 'collision fix: abort', err + out)
    rc, out, err, _ = bd('b', 'rename', 'sb-collide', 'sb-other')
    check(rc == 0, 'collision fix: rename', err + out)
    rc, out, err, _ = bd('b', 'sync')
    check(rc == 0, 'collision fix: sync', err + out)
    bd('a', 'sync')
    rows = items('a')
    check('sb-collide' in rows and 'sb-other' in rows, 'collision fix: both items survive')
    _, _, err, _ = run('b', 'health')
    check('merge conflict' not in err, 'collision fix: the line is gone', err)
    # A dead remote: quiet at first, reported when repeated.
    wait_until(lambda: not waits(), options.seconds * 3)
    hidden = ROOT / 'remote.git.hidden'
    (ROOT / 'remote.git').rename(hidden)
    create('a', 'no remote')
    check(wait_until(lambda: int(sync_state('a').get('failures') or 0) >= 1, options.seconds * 4), 'a failed sync is counted')
    _, _, err, _ = run('a', 'bd', 'version')
    quiet = 'sync failing' not in err or int(sync_state('a').get('failures') or 0) >= 3
    check(quiet, 'a single failed sync stays quiet', err)
    check(wait_until(lambda: int(sync_state('a').get('failures') or 0) >= 3, 30), 'failures go on being counted', sync_state('a'))
    _, _, err, _ = run('a', 'health')
    check('sync failing' in err and 'Fix:' in err, 'repeated failures print the problem and the fix', err)
    rc, _, err, _ = bd('a', 'update', sorted(items('a'))[0], '--title', 'still working')
    check(rc == 0, 'work continues while sync fails', err)
    hidden.rename(ROOT / 'remote.git')
    wait_until(lambda: not waits(), 30)
    time.sleep(options.seconds)
    run('a', 'health')
    check(wait_until(lambda: not sync_state('a').get('kind'), options.seconds * 5 + 30), 'recovers once the remote is back', sync_state('a'))
    _, _, err, _ = run('a', 'health')
    check('sync failing' not in err, 'the failing line goes with the failure', err)
    settle('a', 'b')


def t_held_elsewhere() -> None:
    item = create('b', 'ben holds')
    run('b', 'claim', item)
    settle('a', 'b')
    rc, out, err, _ = run('a', 'position', '--queue', 'all')
    row = next((row for row in out.splitlines() if item in row and 'held' in row), '')
    check('held elsewhere' in row and 'updated' in row and 'IDLE' not in row, 'held elsewhere: row with its update time, no idle mark', out)
    check('board take' not in out.split('held items')[1].split('open questions')[0], 'held elsewhere: no take hint', out)
    rc, out, _, _ = run('a', 'position', '--queue', 'all', '--json')
    check(next(h for h in json.loads(out)['held'] if h['id'] == item)['mark'] == 'elsewhere', 'held elsewhere: the JSON mark')
    rc, _, err, _ = run('a', 'claim', item)
    check(rc == 1 and ("ben's queue" in err), 'held elsewhere: a claim across queues is still refused', err)
    bd('b', 'update', item, '--remove-label', 'queue:ben', '--add-label', 'queue:anna')
    settle('a', 'b')
    rc, _, err, _ = run('a', 'claim', item)
    check(rc == 1 and 'held elsewhere' in err and 'board take' not in err, 'held elsewhere: a claim in my own queue says so, offering no take', err)
    run('b', 'unclaim', item, '--resume', 'claim it again')
    settle('a', 'b')


def t_store() -> None:
    state_file = ROOT / 'a/.beads/board-sync/state.json'
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    state_file.write_text(json.dumps({**state, 'store_bytes': 2 << 30, 'store_warned': False}))
    _, out, err, _ = run('a', 'health')
    check('2.0 GB' in err and 'flatten' in err, 'the store warning prints', err)
    _, out, err, _ = run('a', 'health')
    check('flatten' not in err, 'the store warning prints once per check', err)
    _, out, _, _ = run('a', 'console')
    check('flatten' in (json.loads(out).get('sync') or ''), 'the console keeps showing it', out[:200])
    state = json.loads(state_file.read_text())
    state_file.write_text(json.dumps({**state, 'store_bytes': 0}))


def t_inbox() -> None:
    settle('a', 'b')
    stray = create('a', 'stray, older', role=None)
    bd('a', 'update', stray, '--remove-label', 'queue:anna', role=None)
    time.sleep(1.1)
    rc, out, err, _ = run('a', 'create', '--for', 'ben', 'found for ben', '-t', 'change-request', '--description', 'x', '--silent', role='agent')
    found = out.strip().splitlines()[-1] if rc == 0 else ''
    row = items('a').get(found, {})
    check(rc == 0 and {'for:ben', 'queue:anna'} <= set(row.get('labels', [])) and not row.get('assignee'),
          'create --for: in my queue, labelled for the other, held by nobody', err + out)
    rc, _, err, _ = run('a', 'create', '--for', 'ben', 'child find', '-t', 'change-request', '--description', 'x', '--parent', found, role='agent')
    check(rc == 2 and '--parent' in err, 'create --for refuses --parent', err)
    rc, _, err, _ = run('a', 'claim', found, role='agent')
    check(rc == 1, 'a held find is not claimed', err)
    _, out, _, _ = run('a', 'health', '--json')
    check(found in [i['id'] for i in json.loads(out)['queues']['toSend']], 'health --json lists the finds held for my person', out[:300])
    rc, _, err, _ = run('a', 'send', 'ben', found, role='agent')
    check(rc == 1 and 'only lead' in err, 'send: an agent is refused', err)
    rc, out, err, _ = run('a', 'send', 'ben', found)
    row = items('a')[found]
    check(rc == 0 and 'for:ben' in row['labels'] and not any(label.startswith('queue:') for label in row['labels']) and not row.get('assignee'),
          'send: drops the queue label, the item sits in the inbox', (err + out, row.get('labels'), row.get('assignee')))
    settle('a', 'b')
    _, out, _, _ = run('b', 'health')
    unrouted = out.split('unrouted:')[1] if 'unrouted:' in out else ''
    rows = [row for row in unrouted.splitlines() if row.startswith('  ')]
    mine = next((n for n, row in enumerate(rows) if found in row), None)
    check(mine == 0 and 'for:ben' in rows[0] and 'sent ' in rows[0] and ' ago' in rows[0], 'unrouted rows: time since sent and for:, items for me on top', out)
    check(any(stray in row and ' old' in row and 'sent ' not in row for row in rows), 'unrouted rows: an item sent to nobody shows its age', out)
    sent_at = (items('b')[found].get('metadata') or {}).get('sent_at', '')
    check(sent_at != '' and sent_at >= items('b')[found]['created_at'][:19] + 'Z', 'send stamps sent_at', items('b')[found].get('metadata'))
    check(any(stray in row for row in rows[1:]), 'unrouted rows: the rest follow', out)
    _, out, _, _ = run('a', 'health')
    rows = [row for row in out.split('unrouted:')[1].splitlines() if row.startswith('  ')]
    check([n for n, row in enumerate(rows) if stray in row] < [n for n, row in enumerate(rows) if found in row], 'unrouted rows: oldest first', out)
    _, out, _, _ = run('b', 'console')
    check('1 for you' in (json.loads(out).get('queueLine') or ''), 'console: counts the items for you', out[:400])
    _, out, _, _ = run('b', 'health', '--json')
    check(found in [i['id'] for i in json.loads(out)['queues']['inbox']], 'health --json lists my inbox', out[:300])
    inbox = {i['id']: i for i in json.loads(out)['queues']['inbox']}
    unrouted = {i['id']: i for i in json.loads(out)['queues']['unrouted']}
    check(inbox[found].get('waitingSince') == sent_at and unrouted[found].get('waitingSince') == sent_at,
          'health --json: an inbox item waits since it was sent', (inbox[found], sent_at))
    check(unrouted[stray].get('waitingSince') == items('b')[stray]['created_at'], 'health --json: another unrouted item waits since created', unrouted.get(stray))
    rc, _, err, _ = run('b', 'claim', found, role='agent')
    check(rc == 1 and 'unrouted' in err, 'an inbox item is not claimed until routed', err)
    rc, out, err, _ = run('b', 'route', 'ben', found)
    row = items('b')[found]
    check(rc == 0 and 'queue:ben' in row['labels'] and 'for:ben' not in row['labels'], 'route takes an inbox item into the queue, dropping for:', err + out)
    rc, out, err, _ = run('b', 'claim', found, role='agent')
    check(rc == 0, 'then it claims', err)
    run('b', 'unclaim', found, role='agent')
    # route on a find drops for:.
    rc, out, _, _ = run('a', 'create', '--for', 'ben', 'second find', '-t', 'change-request', '--description', 'x', '--silent', role='agent')
    second = out.strip().splitlines()[-1]
    rc, _, err, _ = run('a', 'route', 'ben', second)
    rows = items('a')
    check(rc == 0 and not rows[second].get('assignee') and 'for:ben' not in rows[second]['labels'] and 'queue:ben' in rows[second]['labels'],
          "route on a find: drops for:", (err, rows[second]))
    parent = create('a', 'a parent')
    kid = create('a', 'a kid', '--parent', parent)
    rc, _, err, _ = run('a', 'send', 'ben', kid)
    check(rc == 1 and 'parent' in err, 'send refuses an item that inherits a queue', err)
    time.sleep(1.1)
    rc, _, err, _ = run('b', 'send', 'anna', found)
    check(rc == 0 and 'for:anna' in items('b')[found]['labels'] and 'for:ben' not in items('b')[found]['labels'], 'passing an item on uses send', err)
    check((items('b')[found].get('metadata') or {}).get('sent_at', '') > sent_at, 'a pass-on stamps sent_at again', items('b')[found].get('metadata'))
    rc, _, err, _ = run('b', 'send', 'anna', found)
    check(rc == 0 and (items('b')[found].get('metadata') or {}).get('sent_at', '') > sent_at, 'a repeated send stamps too', err)
    settle('a', 'b')


def t_cr() -> None:
    """The change-request flow against real bd and real git in clone a: claim (worktree, setup), a worker's item, hand-over
    (rebase, checks, stored pair), agent review, the Accept (look before), a look-after pass that lands and opens its
    ratification, a CR stacked on one in review that lands only after its base, and a landing finished by the next read."""
    settle('a', 'b')
    side = ROOT / 'a'
    target = git('symbolic-ref', '--short', 'HEAD', cwd=side).strip()

    def wt(cr: str) -> Path:
        return side / '.worktrees' / cr

    def meta_of(cr: str) -> dict:
        return items('a')[cr].get('metadata') or {}

    def task(cr: str, title: str) -> str:
        return bd('a', 'create', title, '-t', 'task', '--description', 'x', '--silent', '--parent', cr)[1].strip().splitlines()[-1]

    def worker_pass(cr: str, item: str, name: str, contents: str | None = None) -> None:
        (wt(cr) / name).write_text(name + '\n' if contents is None else contents)
        git('add', name, cwd=wt(cr))
        git('commit', '-q', '-m', f'{item}: {name}', cwd=wt(cr))
        sha = git('rev-parse', '--short', 'HEAD', cwd=wt(cr)).strip()
        rc, out, err, _ = bd('a', 'close', item, '--reason', f'{sha}: {name} written in the pass commit', role='agent')
        check(rc == 0, f'{cr}: the item {item} closes with its pass commit', err + out)

    def close_open_items(cr: str, role: str = 'agent') -> None:
        """The worker's part after a Return: its findings are items, and a hand-over or a reject needs them closed. The worker holds the request;
        a request nobody holds has its items closed by a deciding session."""
        for item in items('a').values():
            if item['status'] != 'closed' and any(dep.get('type') == 'parent-child' and dep.get('depends_on_id') == cr for dep in item.get('dependencies') or []):
                rc, _, err, _ = run('a', 'close', item['id'], '--reason', 'fixture: the finding is addressed', role=role)
                check(rc == 0, f'{cr}: item {item["id"]} closes', err)

    def to_review(cr: str, role: str = 'agent') -> None:
        close_open_items(cr)
        rc, _, err, _ = run('a', 'handover', cr, 'tests: exit 0', role=role)
        check(rc == 0 and items('a')[cr]['status'] == 'in_review', f'{cr}: handed over', err)

    def review_pass(cr: str) -> tuple[int, str, str]:
        rc, _, err, _ = run('a', 'claim', cr, role='solo')
        check(rc == 0, f'{cr}: another session claims the review by id', err)
        rc, out, err, _ = run('a', 'handover', cr, 'reviewed: fine', role='solo')
        return rc, out, err

    (side / 'overlap.txt').write_text('base line one\n' + ''.join(f'base line {n}\n' for n in range(2, 10)))
    git('add', 'overlap.txt', cwd=side)
    git('commit', '-q', '-m', 'seed overlap fixture', cwd=side)
    a = create('a', 'change request A')
    a1 = task(a, 'A item')
    main_tip = git('rev-parse', target, cwd=side).strip()
    rc, out, err, _ = run('a', 'claim', a, role='agent')
    check(rc == 0 and wt(a).is_dir() and git('branch', '--list', f'cr/{a}', cwd=side).strip(), 'cr: a claim creates the worktree and branch', err + out)
    check(meta_of(a).get('base') == target and meta_of(a).get('base_sha') == main_tip and meta_of(a).get('setup_sha') == main_tip,
          'cr: the claim records the base, the fork point and the setup run', meta_of(a))
    exclude = Path(git('rev-parse', '--path-format=absolute', '--git-path', 'info/exclude', cwd=side).strip())
    check(wt(a).parent == side / '.worktrees' and '/.worktrees/' in exclude.read_text().splitlines()
          and '.worktrees' not in git('status', '--porcelain', '--untracked-files=all', cwd=side),
          'cr: the worktree lives in <main>/.worktrees, hidden from git status by the local exclude file', exclude.read_text())
    loose = bd('a', 'create', 'loose task', '-t', 'task', '--description', 'x', '--silent')[1].strip().splitlines()[-1]
    rc, _, err, _ = run('a', 'claim', loose, role='agent')
    check(rc == 1 and 'move' in err and not items('a')[loose].get('assignee'), 'cr: a work item outside any change request is refused with the fix', err)
    rc, _, err, _ = run('a', 'handover', a, 'too early', role='agent')
    check(rc == 1 and 'items still open' in err, 'cr: hand-over refuses open items', err)
    worker_pass(a, a1, 'a.txt')
    overlap = wt(a) / 'overlap.txt'
    overlap.write_text('CR line one\n' + ''.join(f'base line {n}\n' for n in range(2, 10)))
    git('add', 'overlap.txt', cwd=wt(a))
    git('commit', '-q', '-m', 'edit first overlap line', cwd=wt(a))
    (wt(a) / 'dirty.txt').write_text('x\n')
    rc, _, err, _ = run('a', 'handover', a, 'dirty', role='agent')
    check(rc == 1 and 'uncommitted changes' in err, 'cr: hand-over refuses a dirty worktree', err)
    (wt(a) / 'dirty.txt').unlink()
    to_review(a)
    check(items('a')[a]['status'] == 'in_review' and meta_of(a).get('check_result') == 'pass' and meta_of(a).get('check_tip') == git('rev-parse', 'HEAD', cwd=wt(a)).strip(),
          'cr: hand-over stores the (tip, base tip) check and the review stage', meta_of(a))
    rc, out, err = review_pass(a)
    check(rc == 0 and items('a')[a]['status'] == 'passed', 'cr: look before stays at accept after the agent review', err + out)
    rc, _, err, _ = run('a', 'cr', 'land', a, role='agent')
    check(rc == 1 and 'only a lead or solo' in err, 'cr: an agent session cannot land', err)
    tip = git('rev-parse', 'HEAD', cwd=wt(a)).strip()
    rc, _, err, _ = run('a', 'cr', 'land', a, '--tip', main_tip, '--base', main_tip)
    check(rc == 1 and 'branch moved' in err and git('rev-parse', target, cwd=side).strip() == main_tip, 'cr: land --tip refuses a moved branch', err)
    rc, out, err, _ = run('a', 'review', 'open', a, role='solo')
    check(rc == 0 and meta_of(a).get('opened_tip') == tip, 'cr: the user opens the reviewed branch at its seen tip', err + out)
    (side / 'land-base.txt').write_text('base moved after Accept\n')
    (side / 'overlap.txt').write_text('base line one\n' + ''.join(f'base line {n}\n' for n in range(2, 9)) + 'main line nine\n')
    git('add', 'land-base.txt', cwd=side)
    git('add', 'overlap.txt', cwd=side)
    git('commit', '-q', '-m', 'advance target after Accept', cwd=side)
    moved_base = git('rev-parse', target, cwd=side).strip()
    rc, out, err, _ = run('a', 'cr', 'land', a, '--tip', tip, '--base', main_tip)
    check(rc == 1 and items('a')[a]['status'] == 'passed'
          and git('rev-parse', target, cwd=side).strip() == moved_base
          and 'advance target after Accept' in (err + out),
          'cr: a moved base refuses the seen pair and shows incoming commits without changing coverage', err + out)
    rc, console, err, _ = run('a', 'console')
    row = next(one for one in json.loads(console)['crs'] if one['id'] == a)
    incoming = row['acceptance']['incomingCommits']
    moved = next(one for one in incoming if one['subject'] == 'advance target after Accept')
    check(rc == 0 and row['acceptance']['incomingBaseTip'] == main_tip
          and 'land-base.txt' in moved['files'] and moved['crFiles'] == ['overlap.txt'],
          'cr: the Accept JSON lists incoming commits and marks paths overlapping CR files', err + str(row['acceptance']))
    rc, out, err, _ = run('a', 'cr', 'land', a, '--tip', tip, '--base', moved_base)
    landed = meta_of(a)
    rebased_tip = git('rev-parse', target, cwd=side).strip()
    check(rc == 0 and landed.get('check_result') == 'pass',
          'cr: one Accept call rebases and checks the exact current row pair', err + out)
    check(rc == 0 and items('a')[a]['status'] == 'closed' and landed.get('review_tip') == tip
          and landed.get('review_base_tip') == main_tip and landed.get('check_result') == 'pass'
          and landed.get('check_tip') == rebased_tip and landed.get('check_base_tip') == moved_base,
          'cr: one exact current pair lands with its passing check and clean replay', err + out + str(landed))
    check(not meta_of(a).get('opened_tip') and not wt(a).exists()
          and not git('branch', '--list', f'cr/{a}', cwd=side).strip(), 'cr: land removes the CR worktree and branch')

    a_stale = create('a', 'stale seen pair')
    stale_item = task(a_stale, 'stale pair item')
    run('a', 'claim', a_stale, role='agent')
    worker_pass(a_stale, stale_item, 'stale.txt')
    to_review(a_stale)
    review_pass(a_stale)
    stale_seen = git('rev-parse', f'refs/heads/cr/{a_stale}', cwd=side).strip()
    stale_base = git('rev-parse', target, cwd=side).strip()
    (side / 'stale-base-one.txt').write_text('first incoming base move\n')
    git('add', 'stale-base-one.txt', cwd=side)
    git('commit', '-q', '-m', 'move base for stale pair', cwd=side)
    moved_again = git('rev-parse', target, cwd=side).strip()
    rc, out, err, _ = run('a', 'cr', 'land', a_stale, '--tip', stale_seen, '--base', stale_base)
    check(rc == 1 and 'base moved since the pair you saw' in err and 'move base for stale pair' in out
          and git('rev-parse', target, cwd=side).strip() == moved_again
          and meta_of(a_stale).get('review_tip') == stale_seen,
          'cr: a stale base pin refuses without advancing review coverage', err + out)
    (side / 'stale-base-two.txt').write_text('second incoming base move\n')
    git('add', 'stale-base-two.txt', cwd=side)
    git('commit', '-q', '-m', 'move base after refresh', cwd=side)
    newest_base = git('rev-parse', target, cwd=side).strip()
    rc, out, err, _ = run('a', 'cr', 'land', a_stale, '--tip', stale_seen, '--base', moved_again)
    check(rc == 1 and 'base moved since the pair you saw' in err and 'move base after refresh' in out
          and items('a')[a_stale]['status'] == 'passed',
          'cr: concurrent target movement invalidates the exact refreshed pins', err + out)
    rc, piped = run_piped('a', 'cr', 'land', a_stale, '--tip', stale_seen, '--base', moved_again)
    lines = piped.strip().splitlines()
    step = lines[-1] if lines else ''
    command = step.split('then ', 1)[1].split() if 'then agents board cr land ' in step else []
    check(rc == 1 and step.startswith('next: ask the user to Accept the incoming commits')
          and piped.index('move base after refresh') < piped.index('base moved since the pair you saw')
          and command[:5] == ['agents', 'board', 'cr', 'land', a_stale] and command[-1] == newest_base,
          'cr: a piped stale-base refusal ends with the reason, then the next step naming the current pair', piped)
    rc, out, err, _ = run('a', *command[2:])
    next_tip = meta_of(a_stale).get('check_tip')
    check(rc == 0 and items('a')[a_stale]['status'] == 'closed'
          and git('rev-parse', target, cwd=side).strip() == next_tip,
          'cr: the latest exact pair lands after a fresh passing check', err + out)

    direct_land = create('a', 'direct route moved-base landing')
    direct_land_item = task(direct_land, 'direct route landing item')
    run('a', 'claim', direct_land, role='agent')
    worker_pass(direct_land, direct_land_item, 'direct-land.txt')
    rc, out, err, _ = run('a', 'handover', direct_land, 'documentation only', '--no-agent-review', 'documentation only', role='agent')
    direct_seen = git('rev-parse', f'refs/heads/cr/{direct_land}', cwd=side).strip()
    direct_seen_base = git('rev-parse', target, cwd=side).strip()
    (side / 'direct-land-base.txt').write_text('unrelated incoming change for direct route\n')
    git('add', 'direct-land-base.txt', cwd=side)
    git('commit', '-q', '-m', 'move base for direct route land', cwd=side)
    direct_moved_base = git('rev-parse', target, cwd=side).strip()
    rc, out, err, _ = run('a', 'cr', 'land', direct_land, '--tip', direct_seen, '--base', direct_seen_base)
    check(rc == 1 and 'move base for direct route land' in out and 'base moved since the pair you saw' in err
          and meta_of(direct_land).get('no_agent_review_reason') == 'documentation only',
          'cr: direct user coverage also refuses a moved seen pair', err + out)
    (side / 'direct-land.txt').write_text('overlapping user edit\n')
    rc, out, err, _ = run('a', 'cr', 'land', direct_land, '--tip', direct_seen, '--base', direct_moved_base)
    direct_rebased_tip = git('rev-parse', f'refs/heads/cr/{direct_land}', cwd=side).strip()
    direct_check_at = meta_of(direct_land).get('check_at')
    blocked_pending = meta_of(direct_land)
    check(rc == 1 and 'land blocked' in err and blocked_pending.get('landing') is None
          and blocked_pending.get('review_tip') is None and blocked_pending.get('no_agent_review_reason') == 'documentation only'
          and git('rev-parse', target, cwd=side).strip() == direct_moved_base,
          'cr: a failed land preflight leaves direct-route coverage unchanged', err + out + str(blocked_pending))
    (side / 'direct-land.txt').unlink()
    rc, out, err, _ = run('a', 'cr', 'land', direct_land, '--tip', direct_rebased_tip, '--base', direct_moved_base)
    direct_landed = meta_of(direct_land)
    check(rc == 0 and items('a')[direct_land]['status'] == 'closed'
          and direct_landed.get('review_tip') is None
          and direct_landed.get('no_agent_review_reason') == 'documentation only' and direct_landed.get('check_at') == direct_check_at,
          'cr: successful direct-route landing keeps only its reason and reuses its check', err + out + str(direct_landed))

    b = create('a', 'change request B', '--look', 'after')
    b1 = task(b, 'B item')
    run('a', 'claim', b, role='agent')
    worker_pass(b, b1, 'b.txt')
    to_review(b)
    before = git('rev-parse', target, cwd=side).strip()
    rc, out, err = review_pass(b)
    check(rc == 0 and git('rev-parse', target, cwd=side).strip() != before and items('a')[b]['status'] == 'closed'
          and (items('a')[b].get('metadata') or {}).get('outcome') == 'landed',
          'cr: a look-after pass lands the request, closed as landed', err + out)

    design = create('a', 'design CR C', '--look', 'after')
    design_item = create('a', 'C design', '--parent', design, kind='design')
    run('a', 'claim', design, role='agent')
    worker_pass(design, design_item, 'design.txt')
    to_review(design)
    affected_design = create('a', 'affected design', '--parent', design, kind='design')  # work the review opens while the CR waits in review
    ruling = create('a', 'change the design', '-t', 'decision', kind='decision')
    record = ROOT / 'planner-return-record.md'
    record.write_text('## Question\nq\n## Alternatives Considered\na\n## Decision\nd\n## Rationale\nr\n## Rule owner\no\n')
    rc, out, err, _ = run('a', 'wait', affected_design, '--on', ruling)
    check(rc == 0 and items('a')[design]['status'] == 'in_review', 'cr: a question hold alone keeps the review phase', err + out)
    rc, out, err, _ = run('a', 'claim', ruling)
    check(rc == 0, 'cr: the lead takes the question to record the ruling', err + out)
    rc, out, err, _ = run('a', 'ruling', 'record', ruling, str(record))
    check(rc == 0, 'cr: record the ruling that changes the design', err + out)
    rc, out, err, _ = run('a', 'ruling', 'release', ruling)
    check(rc == 0 and items('a')[design]['status'] == 'in_review', 'cr: release alone keeps the review phase', err + out)
    rc, out, err, _ = run('a', 'claim', ruling, role='solo')
    check(rc == 0, 'cr: planner takes the released ruling', err + out)
    review_tip = git('rev-parse', 'HEAD', cwd=wt(design)).strip()
    rc, out, err, _ = run('a', 'return', design, 'Rework the design under this ruling', '--ruling', ruling, role='solo')
    returned = items('a')
    check(rc == 0 and returned[design]['status'] == 'open' and not returned[design].get('assignee')
          and returned[affected_design]['status'] == 'open' and git('rev-parse', 'HEAD', cwd=wt(design)).strip() == review_tip,
          'cr: explicit planner return reopens the review without rewriting the branch', err + out)
    rc, out, err, _ = run('a', 'close', ruling, '--reason', 'planned the design rework', role='solo')
    check(rc == 0, 'cr: the planner closes the applied ruling', err + out)
    run('a', 'claim', design, role='agent')
    worker_pass(design, affected_design, 'design-rework.txt')
    to_review(design)
    rc, out, err = review_pass(design)
    check(rc == 0 and items('a')[design]['status'] == 'closed' and (items('a')[design].get('metadata') or {}).get('outcome') == 'landed',
          'cr: a look-after design CR lands on the reviewer pass like any other', err + out)

    finished = create('a', 'autopilot finished CR', '--status', 'passed')
    rc, _, err, _ = run('a', 'cr', 'land', finished, role='autopilot')
    check(rc != 0 and 'only a lead or solo' in err and items('a')[finished]['status'] == 'passed',
          f'{finished}: autopilot is refused a land', err)
    waiting_finished = create('a', 'autopilot finished CR that waits', '--status', 'passed')
    bd('a', 'dep', 'add', waiting_finished, create('a', 'autopilot finished CR blocker', kind='task'))
    for named in (finished, waiting_finished):  # the waiting one took the named Accept override before
        rc, _, err, _ = run('a', 'claim', named, role='autopilot')
        check(rc != 0 and "user's Accept" in err and not items('a')[named].get('assignee'),
              f'{named}: autopilot is refused a named claim of a finished CR', err)
    design_accept = create('a', 'design-only CR at Accept', '--status', 'passed')
    create('a', f'{design_accept} design', '--parent', design_accept, kind='design')
    rc, _, err, _ = run('a', 'claim', design_accept, role='autopilot')
    check(rc != 0 and "user's Accept" in err and not items('a')[design_accept].get('assignee'),
          f'{design_accept}: autopilot has no Accept authority over a design-only CR', err)
    rc, _, err, _ = run('a', 'return', design_accept, 'rework the design', role='autopilot')
    check(rc != 0 and items('a')[design_accept]['status'] == 'passed',
          f'{design_accept}: autopilot is refused the return of a design-only CR', err)
    accept_queue = create('a', 'autopilot bare Accept queue', kind='epic')
    finished_in_queue = create('a', 'finished CR in autopilot queue', '--status', 'passed', '--parent', accept_queue)
    design_in_queue = create('a', 'design-only CR in autopilot queue', '--status', 'passed', '--parent', accept_queue)
    create('a', f'{design_in_queue} design', '--parent', design_in_queue, kind='design')
    rc, output, err, _ = run('a', 'claim', '--root', accept_queue, role='autopilot')
    accepted_queue_items = items('a')
    check(accepted_queue_items[design_in_queue].get('assignee') is None and accepted_queue_items[finished_in_queue].get('assignee') is None,
          'autopilot bare claim takes no CR waiting for the user, a design-only one included', err + output)
    for unused_accept in (finished, waiting_finished, design_accept, finished_in_queue, design_in_queue):
        close_open_items(unused_accept, role='solo')
        rc, out, err, _ = run('a', 'cr', 'reject', unused_accept, 'test fixture cleanup', role='solo')
        check(rc == 0 and items('a')[unused_accept]['status'] == 'closed',
              f'{unused_accept}: the negative Accept fixture leaves the queue', err + out)
    rc, out, err, _ = raw('a', 'create', 'legacy checkpoint CR', '--type', 'change-request', '--description', 'x', '--metadata', '{"checkpoint":"user"}', '--silent')
    legacy_cr = out.strip().splitlines()[-1] if out.strip() else ''
    rc, report, err, _ = run('a', 'check')
    check(any(legacy_cr in row and 'cr-checkpoint' in row and 'board-migrate' in row for row in report.splitlines())
          and not any(legacy_cr in row and 'unknown-metadata' in row for row in report.splitlines()),
          'board check lists a live CR still carrying checkpoint metadata, naming board-migrate', err + report)  # check exits non-zero while a deviation stands
    bd('a', 'close', legacy_cr, '--reason', 'test fixture cleanup', '--force')

    base_cr, child_cr = create('a', 'stack base P'), create('a', 'stack child C')
    p1, c1 = task(base_cr, 'P item'), task(child_cr, 'C item')
    bd('a', 'dep', 'add', child_cr, base_cr)
    rc, _, err, _ = run('a', 'claim', child_cr, role='agent')
    check(rc == 1 and 'waits on' in err, 'cr: a CR waits while the CR it depends on is in work', err)
    run('a', 'claim', base_cr, role='agent')
    worker_pass(base_cr, p1, 'p.txt')
    to_review(base_cr)
    rc, _, err, _ = run('a', 'claim', child_cr, role='agent')
    check(rc == 1 and 'waits on' in err, 'cr: a CR does not build on a parent still in agent review', err)
    review_pass(base_cr)
    rc, out, err, _ = run('a', 'claim', child_cr, role='agent')
    check(rc == 0 and meta_of(child_cr).get('base') == base_cr, 'cr: a CR builds on the parent waiting for the user, which becomes its base', err + out)
    worker_pass(child_cr, c1, 'c.txt')
    to_review(child_cr)
    review_pass(child_cr)
    rc, _, err, _ = run('a', 'cr', 'land', child_cr)
    check(rc == 1 and 'has not landed' in err, 'cr: a CR with a CR base never lands before its base', err)
    base_tip = git('rev-parse', 'HEAD', cwd=wt(base_cr)).strip()
    base_pair_tip = git('rev-parse', f'refs/heads/cr/{base_cr}', cwd=side).strip()
    base_pair_base = git('rev-parse', target, cwd=side).strip()
    rc, out, err, _ = run('a', 'cr', 'land', base_cr, '--tip', base_pair_tip, '--base', base_pair_base)
    check(rc == 0 and meta_of(child_cr).get('base') == target and items('a')[base_cr]['status'] == 'closed',
          'cr: landing the base resets the CRs stacked on it to the target', err + out)
    child_tip = git('rev-parse', 'HEAD', cwd=wt(child_cr)).strip()
    child_base = git('rev-parse', target, cwd=side).strip()
    rc, out, err, _ = run('a', 'cr', 'land', child_cr, '--tip', child_tip, '--base', child_base)
    check(rc == 0 and git('rev-parse', target, cwd=side).strip() == child_tip and subprocess.run(['git', 'merge-base', '--is-ancestor', base_tip, target], cwd=side).returncode == 0,
          'cr: the child lands once its base has', err + out)

    d = create('a', 'derived landing')
    d1 = task(d, 'D item')
    run('a', 'claim', d, role='agent')
    worker_pass(d, d1, 'd.txt')
    to_review(d)
    review_pass(d)
    git('merge', '-q', '--ff-only', f'cr/{d}', cwd=side)  # the fast-forward done, the close not
    rc, _, err, _ = run('a', 'queue')
    check(rc == 0 and items('a')[d]['status'] == 'closed' and not wt(d).exists(), 'cr: a tip the target holds closes its CR on the next read', err)

    e = create('a', 'returned CR')
    e1 = task(e, 'E item')
    run('a', 'claim', e, role='agent')
    worker_pass(e, e1, 'e.txt')
    to_review(e)
    review_pass(e)
    covered = meta_of(e).get('review_tip')
    rc, _, err, _ = run('a', 'return', e, 'rename the file', role='solo')
    row = items('a')[e]
    check(rc == 0 and row['status'] == 'open' and not row.get('assignee') and wt(e).is_dir() and git('branch', '--list', f'cr/{e}', cwd=side).strip()
          and meta_of(e).get('review_tip') == covered, 'cr: Return keeps the prior reviewed range and leaves the worktree and branch', err)
    rc, _, err, _ = run('a', 'cr', 'reject', e, 'the approach fails')
    check(rc == 1 and items('a')[e]['status'] == 'open' and 'items still open' in err, 'cr: reject refuses while items are open, naming the way out', err)
    close_open_items(e, role='solo')  # the Return left the request unheld: a deciding session closes its items
    rc, out, err, _ = run('a', 'cr', 'reject', e, 'the approach fails')
    check(rc == 0 and items('a')[e]['status'] == 'closed' and git('branch', '--list', f'cr/{e}', cwd=side).strip() and wt(e).is_dir(),
          'cr: reject closes it unlanded, the branch and worktree stay until confirmed', err + out)

    f = create('a', 'direct user review')
    f1 = task(f, 'F item')
    run('a', 'claim', f, role='agent')
    worker_pass(f, f1, 'f.txt')
    rc, out, err, _ = run('a', 'handover', f, 'changelog only', '--no-agent-review', 'merged changelog bullet', role='agent')
    direct_tip = git('rev-parse', 'HEAD', cwd=wt(f)).strip()
    direct_base_tip = git('rev-parse', target, cwd=side).strip()
    direct_meta = meta_of(f)
    check(rc == 0 and items('a')[f]['status'] == 'passed' and direct_meta.get('no_agent_review_reason') == 'merged changelog bullet',
          'cr: eligible no-agent handover reaches Accept with its reason', err + out)
    (side / 'f.txt').write_text('uncommitted edit that overlaps the landing\n')
    rc, out, err, _ = run('a', 'cr', 'land', f, '--tip', direct_tip, '--base', direct_base_tip)
    failed_meta = meta_of(f)
    check(rc == 1 and 'land blocked' in err and failed_meta.get('review_tip') is None
          and failed_meta.get('no_agent_review_reason') == 'merged changelog bullet',
          'cr: a refused direct Accept does not record operative user review coverage', err + str(failed_meta))
    (side / 'f.txt').unlink()
    rc, out, err, _ = run('a', 'cr', 'land', f, '--tip', direct_tip, '--base', direct_base_tip)
    final_meta = meta_of(f)
    check(rc == 0 and items('a')[f]['status'] == 'closed' and final_meta.get('review_tip') is None and final_meta.get('no_agent_review_reason') == 'merged changelog bullet',
          'cr: direct Accept lands with its route reason', err + out)

    h = create('a', 'direct review with a moved base')
    h1 = task(h, 'H item')
    run('a', 'claim', h, role='agent')
    worker_pass(h, h1, 'h.txt')
    rc, out, err, _ = run('a', 'handover', h, 'changelog only', '--no-agent-review', 'merged changelog bullet', role='agent')
    h_tip = git('rev-parse', 'HEAD', cwd=wt(h)).strip()
    h_base = git('rev-parse', target, cwd=side).strip()
    (side / 'direct-base.txt').write_text('incoming unrelated change\n')
    git('add', 'direct-base.txt', cwd=side)
    git('commit', '-q', '-m', 'move base for direct review', cwd=side)
    direct_base = git('rev-parse', target, cwd=side).strip()
    rc, out, err, _ = run('a', 'cr', 'land', h, '--tip', h_tip, '--base', h_base)
    check(rc == 1 and 'move base for direct review' in out and 'base moved since the pair you saw' in err,
          'cr: a direct user route refuses a moved seen pair and shows incoming commits', err + out)
    rc, _, err, _ = run('a', 'cr', 'request-review', h, 'incoming change affects this CR', role='autopilot')
    check(rc == 1 and 'only a lead or solo' in err,
          'cr: an unheld non-deciding session cannot request review', err)
    rc, out, err, _ = run('a', 'claim', h, role='agent')
    check(rc == 0, 'cr: a current CR holder can take the request', err + out)
    rc, out, err, _ = run('a', 'cr', 'request-review', h, 'incoming change affects this CR', role='agent')
    check(rc == 0 and items('a')[h]['status'] == 'in_review' and 'requested agent review' in out,
          'cr: the current holder can route relevant changes without a lead detour', err + out)
    rc, out, err = review_pass(h)
    check(rc == 1 and 'tip moved' in err + out,
          'cr: the first review gate reports its moved tip before recording a verdict', err + out)
    rc, out, err = review_pass(h)
    after_review_tip = git('rev-parse', 'HEAD', cwd=wt(h)).strip()
    after_review_base = git('rev-parse', target, cwd=side).strip()
    check(rc == 0 and items('a')[h]['status'] == 'passed',
          'cr: review passes after a moved-base Accept requests review', err + out)
    rc, out, err, _ = run('a', 'cr', 'land', h, '--tip', after_review_tip, '--base', after_review_base, role='solo')
    check(rc == 0 and items('a')[h]['status'] == 'closed' and git('rev-parse', target, cwd=side).strip() == after_review_tip,
          'cr: exact current pair lands after the requested review passes', err + out)

    i = create('a', 'prior agent coverage with a direct route')
    i1 = task(i, 'I item')
    run('a', 'claim', i, role='agent')
    worker_pass(i, i1, 'i.txt')
    to_review(i)
    rc, out, err = review_pass(i)
    prior_agent_tip = meta_of(i).get('review_tip')
    prior_agent_base = meta_of(i).get('review_base_tip')
    check(rc == 0 and items('a')[i]['status'] == 'passed' and prior_agent_tip,
          'cr: the prior coverage route starts with a real agent review', err + out)
    rc, out, err, _ = run('a', 'return', i, 'the remaining note is documentation only', role='solo')
    check(rc == 0 and items('a')[i]['status'] == 'open', 'cr: the direct route can follow a user Return', err + out)
    run('a', 'claim', i, role='agent')
    (wt(i) / 'i-doc.txt').write_text('documentation-only follow-up\n')
    git('add', 'i-doc.txt', cwd=wt(i))
    git('commit', '-q', '-m', 'documentation-only follow-up', cwd=wt(i))
    close_open_items(i)
    rc, out, err, _ = run('a', 'handover', i, 'documentation-only follow-up', '--no-agent-review', 'documentation only', role='agent')
    check(rc == 0 and meta_of(i).get('review_tip') == prior_agent_tip
          and meta_of(i).get('review_base_tip') == prior_agent_base and items('a')[i]['status'] == 'passed',
          'cr: direct routing preserves the historical agent review pair', err + out)
    (side / 'i-base.txt').write_text('unrelated incoming base change\n')
    git('add', 'i-base.txt', cwd=side)
    git('commit', '-q', '-m', 'move base for prior direct route', cwd=side)
    direct_i_base = git('rev-parse', target, cwd=side).strip()
    rc, out, err, _ = run('a', 'cr', 'refresh', i, role='agent')
    direct_i_tip = git('rev-parse', 'HEAD', cwd=wt(i)).strip()
    check(rc == 0 and items('a')[i]['status'] == 'passed' and out.count('move base for prior direct route') == 1,
          'cr: refresh rebases and checks without advancing coverage', err + out)
    refreshed_i = meta_of(i)
    check(refreshed_i.get('no_agent_review_reason') == 'documentation only'
          and refreshed_i.get('review_tip') == prior_agent_tip and refreshed_i.get('review_base_tip') == prior_agent_base,
          'cr: refresh preserves existing agent coverage', err + out + str(refreshed_i))
    rc, out, err, _ = run('a', 'review', 'open', i, role='solo')
    check(rc == 0, 'cr: the user sees the no-agent series before a conflict', err + out)
    run('a', 'cr', 'edits', i, '--tip', direct_i_tip, '--commit', role='solo')
    (side / 'i-doc.txt').write_text('main added this file too\n')
    git('add', 'i-doc.txt', cwd=side)
    git('commit', '-q', '-m', 'conflict with no-agent series', cwd=side)
    rc, out, err, _ = run('a', 'cr', 'refresh', i, role='agent')
    check(rc == 1 and 'stopped on a conflict' in err, 'cr: refresh stops at the no-agent conflict', err + out)
    (wt(i) / 'i-doc.txt').write_text('resolved documentation change\n')
    git('add', 'i-doc.txt', cwd=wt(i))
    rc, out, err, _ = run('a', 'cr', 'refresh', i, role='agent')
    direct_i_tip = git('rev-parse', 'HEAD', cwd=wt(i)).strip()
    _, console, _, _ = run('a', 'console')
    row_i = next(one for one in json.loads(console)['crs'] if one['id'] == i)
    delta_i = row_i['acceptance']['delta'] or ''
    check(rc == 0 and row_i['status'] == 'passed' and not row_i['acceptance']['fullChange']
          and row_i['acceptance']['seenTip'] != direct_i_tip and 'documentation-only follow-up' in delta_i
          and any(line.split()[2:3] in (['!'], ['>']) for line in delta_i.splitlines()),
          'cr: a resolved no-agent series stays at Accept with its changed delta', err + out + str(row_i['acceptance']))
    rc, out, err, _ = run('a', 'cr', 'request-review', i, 'the incoming change affects this documentation', role='solo')
    check(rc == 0 and items('a')[i]['status'] == 'in_review' and meta_of(i).get('review_tip') == prior_agent_tip,
          'cr: a lead can route relevant incoming changes while preserving old agent coverage', err + out)
    rc, out, err, _ = run('a', 'claim', i, role='solo')  # the author's own session never reviews it
    check(rc == 0 and 'range-diff since the last covered series' in out and 'documentation-only follow-up' in out,
          'cr: the re-review sees the uncovered author follow-up', err + out)
    rc, out, err, _ = run('a', 'handover', i, 'reviewed the uncovered documentation change', role='solo')
    check(rc == 0 and items('a')[i]['status'] == 'passed'
          and meta_of(i).get('review_tip') == direct_i_tip,
          'cr: the agent can pass the request for review after reading the uncovered range', err + out)

    j = create('a', 'recorded user edit after a base move')
    j1 = task(j, 'J item')
    run('a', 'claim', j, role='agent')
    worker_pass(j, j1, 'j.txt')
    to_review(j)
    rc, out, err = review_pass(j)
    j_covered_tip, j_covered_base = meta_of(j).get('review_tip'), meta_of(j).get('review_base_tip')
    check(rc == 0 and items('a')[j]['status'] == 'passed' and j_covered_tip and j_covered_base,
          'cr: recorded-user-edit case starts from current agent coverage', err + out)
    git('config', 'user.name', 'Test User', cwd=side)
    git('config', 'user.email', 'test@example.test', cwd=side)
    rc, out, err, _ = run('a', 'review', 'open', j, role='solo')
    j_seen_tip = meta_of(j).get('user_seen_tip')
    check(rc == 0 and j_seen_tip == j_covered_tip, 'cr: the user opened the covered series before editing', err + out)
    (wt(j) / 'j.txt').write_text('user edit after agent review\n')
    (side / 'j-base.txt').write_text('incoming base change during user edits\n')
    git('add', 'j-base.txt', cwd=side)
    git('commit', '-q', '-m', 'move base during user edits', cwd=side)
    j_moved_base = git('rev-parse', target, cwd=side).strip()
    rc, out, err, _ = run('a', 'cr', 'edits', j, '--tip', j_seen_tip, '--commit', '-m', 'record user edit', role='solo')
    j_after_edit = meta_of(j)
    check(rc == 0 and items('a')[j]['status'] == 'passed'
          and j_after_edit.get('review_tip') == j_covered_tip and j_after_edit.get('review_base_tip') == j_covered_base
          and j_after_edit.get('user_seen_base_tip') == j_covered_base
          and j_after_edit.get('base_sha') == j_moved_base,
          'cr: recorded user edits after a base move keep prior coverage and remain at Accept', err + out + str(j_after_edit))
    j_current_tip = git('rev-parse', f'refs/heads/cr/{j}', cwd=side).strip()
    rc, out, err, _ = run('a', 'cr', 'land', j, '--tip', j_current_tip, '--base', j_moved_base)
    check(rc == 0 and items('a')[j]['status'] == 'closed' and meta_of(j).get('review_tip') == j_covered_tip
          and meta_of(j).get('review_base_tip') == j_covered_base,
          'cr: a user edit cleanly replayed on the moved base lands on the exact current pair', err + out)

    k = create('a', 'first Accept look after a base move')
    k1 = task(k, 'K item')
    run('a', 'claim', k, role='agent')
    worker_pass(k, k1, 'k.txt')
    k_fork = meta_of(k).get('base_sha')
    rc, out, err, _ = run('a', 'handover', k, 'documentation-only change', '--no-agent-review', 'documentation only', role='agent')
    check(rc == 0 and items('a')[k]['status'] == 'passed' and k_fork,
          'cr: first-look moved-base case begins with a user-only coverage route', err + out)
    (side / 'k-base.txt').write_text('unrelated incoming base change before first Accept look\n')
    git('add', 'k-base.txt', cwd=side)
    git('commit', '-q', '-m', 'move base before first Accept look', cwd=side)
    k_tip = git('rev-parse', f'refs/heads/cr/{k}', cwd=side).strip()
    k_seen_base = git('rev-parse', target, cwd=side).strip()
    rc, out, err, _ = run('a', 'cr', 'land', k, '--tip', k_tip, '--base', k_seen_base)
    k_after_look = meta_of(k)
    k_landed_tip = git('rev-parse', target, cwd=side).strip()
    check(rc == 0 and items('a')[k]['status'] == 'closed' and k_after_look.get('user_seen_tip') == k_tip
          and k_after_look.get('user_seen_base_tip') == k_seen_base and k_after_look.get('base_sha') == k_seen_base
          and k_landed_tip == k_after_look.get('check_tip'),
          'cr: first Accept on the exact current pair rebases, checks and lands in one call', err + out + str(k_after_look))

    g = create('a', 'request a delta review')
    g1 = task(g, 'G item')
    run('a', 'claim', g, role='agent')
    worker_pass(g, g1, 'g.txt')
    to_review(g)
    review_pass(g)
    prior = meta_of(g).get('review_tip')
    rc, out, err, _ = run('a', 'cr', 'request-review', g, 'please recheck this delta', role='solo')
    after_request = meta_of(g)
    check(rc == 0 and items('a')[g]['status'] == 'in_review' and after_request.get('review_tip') == prior
          and 'requested agent review' in out, 'cr: Review requests agent delta review without erasing prior coverage', err + out)
    rc, out, err = review_pass(g)
    g_tip = git('rev-parse', 'HEAD', cwd=wt(g)).strip()
    g_base = git('rev-parse', target, cwd=side).strip()
    rc_land, land_out, land_err, _ = run('a', 'cr', 'land', g, '--tip', g_tip, '--base', g_base)
    check(rc == 0 and rc_land == 0 and items('a')[g]['status'] == 'closed' and meta_of(g).get('review_tip') == prior,
          'cr: re-review passes and lands the unchanged already-covered series', err + out + land_err + land_out)


    design_cr = create('a', 'design with independent dependent')
    design = create('a', 'independent design', '--parent', design_cr, kind='design')
    dependent = create('a', 'waits for design text')
    dependent_item = task(dependent, 'consumer item')
    rc, _, err, _ = run('a', 'wait', dependent_item, '--on', design, '--for', 'read accepted design')
    check(rc == 0 and any(edge['depends_on_id'] == design for edge in items('a')[dependent_item].get('dependencies') or []),
          'cr: an item may wait on an item of another request', err)
    rc, _, err, _ = run('a', 'unlink', dependent_item, design)
    check(rc == 0, 'cr: the item wait is unlinked again', err)
    rc, _, err, _ = run('a', 'wait', dependent, '--on', design, '--for', 'read accepted design')
    check(rc == 0, 'cr: declare a design wait on its dependent request', err)
    rc, _, err, _ = run('a', 'claim', dependent, role='agent')
    check(rc == 1 and not wt(dependent).exists(), 'cr: an open design still holds its dependent request', err)
    rc, _, err, _ = run('a', 'claim', design_cr, role='agent')
    check(rc == 0, 'cr: the design-only CR is claimed like any CR', err)
    worker_pass(design_cr, design, 'design-doc.txt')
    rc, _, err, _ = run('a', 'claim', dependent, role='agent')
    check(rc == 1 and design_cr in err and not wt(dependent).exists(), 'cr: the closed design item does not release its dependent before the CR lands', err)
    to_review(design_cr)
    rc, _, err, _ = run('a', 'claim', dependent, role='agent')
    check(rc == 1 and design_cr in err and not wt(dependent).exists(), 'cr: the dependent waits while the design-only CR is in review', err)
    rc, out, err = review_pass(design_cr)
    check(rc == 0 and items('a')[design_cr]['status'] == 'passed' and not [r for r in items('a').values() if r['status'] == 'needs_ratification'
                                                                                       and any(e.get('depends_on_id') == design_cr for e in r.get('dependencies') or [])],
          'cr: a look-before design-only CR waits for the user\'s Accept after the reviewer pass', err + out)
    rc, _, err, _ = run('a', 'claim', dependent, role='agent')
    check(rc == 0 and meta_of(dependent).get('base') == design_cr, 'cr: a design-only CR at Accept is an ordinary stack base: the dependent stacks on it', err)
    design_tip = git('rev-parse', f'refs/heads/cr/{design_cr}', cwd=side).strip()
    design_base = git('rev-parse', target, cwd=side).strip()
    rc, out, err, _ = run('a', 'cr', 'land', design_cr, '--tip', design_tip, '--base', design_base)
    check(rc == 0 and items('a')[design_cr]['status'] == 'closed' and items('a')[design]['status'] == 'closed'
          and git('rev-parse', target, cwd=side).strip() == design_tip, 'cr: the design-only CR lands the doc commit on Accept', err + out)
    rc, _, err, _ = run('a', 'claim', dependent, role='agent')
    check(rc == 0 and meta_of(dependent).get('base') == target, 'cr: after the design lands the dependent starts on the target', err)

    first = create('a', 'first standalone item', kind='task')
    second = create('a', 'second standalone item', kind='task')
    rc, _, err, _ = run('a', 'wait', second, '--on', first, '--for', 'do the first item before the second')
    check(rc == 0, 'cr: standalone items can already have a blocking edge', err)
    plan = ROOT / 'group-linked-items.json'
    plan.write_text(json.dumps({
        'nodes': [{'key': 'request', 'title': 'group linked items', 'type': 'change-request', 'description': 'x'}],
        'edges': [{'from_id': item, 'to_key': 'request', 'type': 'parent-child'} for item in (first, second)],
    }))
    rc, out, err, _ = run('a', 'create', '--graph', str(plan))
    request = next((line.split()[1] for line in out.splitlines() if line.startswith('request ')), None)
    graph_rows = items('a')
    check(rc == 0 and request in graph_rows and all(
        any(dep['type'] == 'parent-child' and dep['depends_on_id'] == request for dep in graph_rows[item]['dependencies'])
        for item in (first, second)) and any(
        dep['type'] == 'blocks' and dep['depends_on_id'] == first for dep in graph_rows[second]['dependencies']),
        'cr: one graph can group linked items while keeping their newly internal wait', err + out)

    awaiting = create('a', 'request waiting on a question')
    affected = task(awaiting, 'item affected by the answer')
    rc, out, err, _ = run('a', 'console')
    before = json.loads(out)['waitingOnYou'] if rc == 0 else None
    rc, out, err, _ = run('a', 'create', 'question about one item', '-t', 'decision', '--description', 'x', '--holds', affected)
    question = out.strip().splitlines()[-1] if rc == 0 else None
    held = items('a')[affected]
    check(rc == 0 and any(dep['type'] == 'blocks' and dep['depends_on_id'] == question for dep in held.get('dependencies', [])),
          'cr: a question can hold an affected item', err + out)
    rc, out, err, _ = run('a', 'console')
    check(rc == 0 and before is not None and json.loads(out)['waitingOnYou'] == before + 1,
          'cr: an item-scoped question adds its request to waits on your answers', err + out)
    rc, _, err, _ = run('a', 'claim', awaiting, role='agent')
    check(rc == 1 and not wt(awaiting).exists(), 'cr: a pending item question blocks claiming the request', err)


def t_scenarios() -> None:
    """The board model's Verified scenarios that board code owns, through the real verbs (docs: the model's Verified scenarios).
    1 and 15 are t_cr's (a look-after pass lands; hand-over refuses open items); 5 is t_cr's stacking and the fake suite's landing of a
    look-after child; 6 (ratify) and 11 (filing a find) belong to nixes-cop95 and nixes-5smx7; 9 is the fake suite's milestones;
    12 is the fake suite's gone-holder takeover; 14 has no verb; 16 is judgment. Here: 2, 3, 4, 7, 8, 10 and 13."""
    settle('a', 'b')
    side = ROOT / 'a'
    target = git('symbolic-ref', '--short', 'HEAD', cwd=side).strip()

    def wt(cr: str) -> Path:
        return side / '.worktrees' / cr

    def task(cr: str, title: str) -> str:
        return bd('a', 'create', title, '-t', 'task', '--description', 'x', '--silent', '--parent', cr)[1].strip().splitlines()[-1]

    def row(item: str) -> dict:
        return items('a')[item]

    def open_items(cr: str) -> list[str]:
        return [one['id'] for one in items('a').values() if one['status'] != 'closed'
                and any(dep.get('type') == 'parent-child' and dep.get('depends_on_id') == cr for dep in one.get('dependencies') or [])]

    def work(cr: str, item: str, name: str) -> None:
        (wt(cr) / name).write_text(name + '\n')
        git('add', name, cwd=wt(cr))
        git('commit', '-q', '-m', f'{item}: {name}', cwd=wt(cr))
        rc, _, err, _ = run('a', 'close', item, '--reason', f'{item}: {name} written in a commit', role='agent')
        check(rc == 0, f'{cr}: {item} closes', err)

    def to_passed(cr: str) -> None:
        check(run('a', 'handover', cr, 'tests: exit 0', role='agent')[0] == 0, f'{cr}: handed over')
        check(run('a', 'claim', cr, role='solo')[0] == 0, f'{cr}: another session reviews it')
        rc, _, err, _ = run('a', 'handover', cr, 'reviewed: fine', role='solo')
        check(rc == 0 and row(cr)['status'] == 'passed', f'{cr}: the review passes it to Accept', err)

    # 2. Look before; the user returns it with two findings: two items, fixed and closed, re-reviewed, Accepted, landed.
    two = create('a', 'scenario 2: look before, two findings')
    first = task(two, 'the change')
    check(run('a', 'claim', two, role='agent')[0] == 0, 'scenario 2: claimed')
    work(two, first, 's2.txt')
    to_passed(two)
    rc, out, err, _ = run('a', 'return', two, 'first finding of the Accept', 'second finding of the Accept', role='lead')
    check(rc == 0 and row(two)['status'] == 'open' and len(open_items(two)) == 2, 'scenario 2: a Return makes one open item per finding', err + out)
    check(run('a', 'claim', two, role='agent')[0] == 0, 'scenario 2: the worker claims it again')
    for finding in open_items(two):
        work(two, finding, f's2-{finding}.txt')
    to_passed(two)
    tip, base = git('rev-parse', f'refs/heads/cr/{two}', cwd=side).strip(), git('rev-parse', target, cwd=side).strip()
    rc, out, err, _ = run('a', 'cr', 'land', two, '--tip', tip, '--base', base, role='lead')
    check(rc == 0 and row(two)['status'] == 'closed' and (row(two).get('metadata') or {}).get('outcome') == 'landed'
          and git('rev-parse', target, cwd=side).strip() == tip, 'scenario 2: the Accept lands it, closed as landed', err + out)

    # 3. Item B waits on a question while A is ready: A is done, hand-over refuses on B, the worker hands the CR back, and it is ready again
    # once the ruling is planned (closed): in force still holds the waiter.
    draft = ROOT / 'scenario-record.md'
    draft.write_text('## Question\nq\n## Alternatives Considered\na\n## Decision\nd\n## Rationale\nr\n## Rule owner\no\n')
    question = create('a', 'scenario 3: which way', '-t', 'decision', kind='decision')
    three = create('a', 'scenario 3: item waits on a question')
    a_item, b_item = task(three, 'A, ready'), task(three, 'B, waits on the question')
    check(run('a', 'wait', b_item, '--on', question, '--for', 'the way it goes')[0] == 0, 'scenario 3: B waits on the question')
    check(run('a', 'claim', three, role='agent')[0] == 0, 'scenario 3: the CR is ready through A')
    work(three, a_item, 's3.txt')
    rc, _, err, _ = run('a', 'handover', three, 'A is done', role='agent')
    check(rc == 1 and b_item in err and row(three)['status'] == 'open', 'scenario 3: hand-over refuses while B is open, naming it', err)
    rc, _, err, _ = run('a', 'unclaim', three, '--resume', 'B waits for the ruling', role='agent')
    check(rc == 0 and not row(three).get('assignee'), 'scenario 3: the worker hands the CR back', err)
    rc, _, err, _ = run('a', 'claim', three, role='agent')
    check(rc == 1 and not row(three).get('assignee'), 'scenario 3: with only B open the CR is not ready', err)
    check(run('a', 'claim', question)[0] == 0 and run('a', 'ruling', 'record', question, str(draft))[0] == 0
          and run('a', 'ruling', 'release', question)[0] == 0 and row(question)['status'] == 'in_force', 'scenario 3: the ruling is in force')
    rc, _, err, _ = run('a', 'claim', three, role='agent')
    check(rc == 1 and not row(three).get('assignee'), 'scenario 3: a ruling in force does not release the waiter', err)
    check(run('a', 'close', question, '--reason', 'planned: the way it goes is carried into B', role='solo')[0] == 0
          and (row(question).get('metadata') or {}).get('outcome') == 'planned', 'scenario 3: planning closes the ruling as planned')
    rc, _, err, _ = run('a', 'claim', three, role='agent')
    check(rc == 0 and row(three).get('assignee'), 'scenario 3: ready again once the ruling is planned', err)

    # 4. A no-commit probe is a task; the question waits on it; a CR whose only item waits on the question is not ready; the probe runs on its own.
    probe = create('a', 'scenario 4: probe', '--no-commit', kind='task')
    stalled_q = create('a', 'scenario 4: question', '-t', 'decision', kind='decision')
    four = create('a', 'scenario 4: only item waits on the question')
    four_item = task(four, 'the waiting item')
    check(run('a', 'wait', stalled_q, '--on', probe, '--for', 'the probe result')[0] == 0
          and run('a', 'wait', four_item, '--on', stalled_q, '--for', 'the answer')[0] == 0, 'scenario 4: question waits on the probe, the item on the question')
    rc, _, err, _ = run('a', 'claim', four, role='agent')
    check(rc == 1 and not row(four).get('assignee'), 'scenario 4: the CR with only the waiting item is not ready', err)
    rc, _, err, _ = run('a', 'claim', stalled_q)
    check(rc == 1 and probe in err and not row(stalled_q).get('assignee'), 'scenario 4: the question is not claimable while it waits on the probe, naming it', err)
    check(run('a', 'claim', probe, role='agent')[0] == 0 and row(probe).get('assignee'), 'scenario 4: the probe runs on its own')
    check(run('a', 'close', probe, '--reason', 'the probe found what it was after', role='agent')[0] == 0, 'scenario 4: the probe closes')
    rc, _, err, _ = run('a', 'claim', four, role='agent')
    check(rc == 1 and not row(four).get('assignee'), 'scenario 4: its CR still waits for the ruling', err)
    rc, _, err, _ = run('a', 'claim', stalled_q)
    check(rc == 0 and row(stalled_q).get('assignee'), 'scenario 4: the question is ready once the probe closed', err)

    # An item follows its change request's hold: only the holder's session, the user or (once the holder is gone) a deciding session write it.
    held = create('a', 'items follow the hold')
    mine, other_cr = task(held, 'an item of the held request'), create('a', 'another request')
    check(run('a', 'claim', held, role='agent')[0] == 0, 'item writes: the agent holds the request')
    for what, args in (('close', ('close', mine, '--reason', 'closed by a session that does not hold its request')),
                       ('update', ('update', mine, '--title', 'renamed by a stranger')),
                       ('move', ('move', mine, '--to', other_cr))):
        rc, _, err, _ = run('a', *args, role='solo')
        check(rc != 0 and held in err and row(mine)['status'] == 'open' and row(mine)['title'] == 'an item of the held request',
              f'item writes: a session that does not hold the request cannot {what} its item', err)
    # A wait is written by the user or a deciding session whoever holds the request; a session that does not hold it, or any unheld request, refuses it.
    solo_cr, solo_item = create('a', 'held by solo'), None
    solo_item = task(solo_cr, 'an item of the request solo holds')
    check(run('a', 'claim', solo_cr, role='solo')[0] == 0, 'item waits: solo holds a request')
    rc, _, err, _ = run('a', 'wait', solo_item, '--on', other_cr, '--for', 'another session waits it', role='agent')
    check(rc != 0 and solo_cr in err and not any(dep.get('type') == 'blocks' for dep in row(solo_item).get('dependencies') or []), 'item waits: a session that does not hold the request cannot wait its item', err)
    unheld_item = task(create('a', 'nobody holds this'), 'an item of an unheld request')
    rc, _, err, _ = run('a', 'wait', unheld_item, '--on', other_cr, '--for', 'an agent waits it', role='agent')
    check(rc != 0 and 'claim it first' in err, 'item waits: an unheld request is claimed first', err)
    check(run('a', 'wait', mine, '--on', other_cr, '--for', 'a deciding session waits it', role='solo')[0] == 0
          and run('a', 'wait', unheld_item, '--on', other_cr, '--for', 'a deciding session waits it', role='autopilot')[0] == 0,
          'item waits: a deciding session writes a wait whoever holds the request')
    check(run('a', 'update', mine, '--title', 'renamed by the holder', role='agent')[0] == 0 and row(mine)['title'] == 'renamed by the holder',
          'item writes: the holder writes it')
    check(run('a', 'update', mine, '--title', 'renamed by the user', role=None)[0] == 0 and row(mine)['title'] == 'renamed by the user',
          'item writes: the user writes it')

    # Deciding sessions are lead, solo and autopilot: the away path's supersede and close of settled questions pass for autopilot. The holder of an
    # in-force ruling that claimed it with the plan pull closes it as planned; a session that does not hold it does not.
    def outcome(item: str) -> str | None:
        return (row(item).get('metadata') or {}).get('outcome')

    def in_force(title: str) -> str:
        ruling = create('a', title, '-t', 'decision', kind='decision')
        check(run('a', 'claim', ruling)[0] == 0 and run('a', 'ruling', 'record', ruling, str(draft))[0] == 0
              and run('a', 'ruling', 'release', ruling)[0] == 0 and row(ruling)['status'] == 'in_force', f'{title}: in force')
        return ruling
    planned = in_force('planner closes: the ruling')
    rc, _, err, _ = run('a', 'close', planned, '--reason', 'planned in the change requests it made', role='agent')
    check(rc != 0 and row(planned)['status'] == 'in_force', 'planner close: a session that does not hold the ruling cannot close it', err)
    check(run('a', 'claim', planned, role='agent')[0] == 0, 'planner close: the plan pull claims the ruling')
    rc, _, err, _ = run('a', 'close', planned, '--reason', 'planned in the change requests it made', role='agent')
    check(rc == 0 and row(planned)['status'] == 'closed' and outcome(planned) == 'planned', 'planner close: its holder closes it as planned', err)
    old, new = in_force('away: the ruling replaced'), create('a', 'away: the replacing ruling', '-t', 'decision', kind='decision')
    away_draft = ROOT / 'away-record.md'
    away_draft.write_text(draft.read_text() + '## Reversal\nrevert\n')
    check(run('a', 'claim', new, role='autopilot')[0] == 0, 'away: autopilot claims the question')
    rc, _, err, _ = run('a', 'ruling', 'record', new, str(away_draft), '--unratified', '--replaces', old, role='autopilot')
    check(rc == 0 and row(new)['status'] == 'in_force' and row(old)['status'] == 'closed' and outcome(old) == 'superseded',
          'away: autopilot records an unratified ruling, which supersedes the old one', err)
    settled = create('a', 'away: a question settled in the chat', '-t', 'decision', kind='decision')
    rc, _, err, _ = run('a', 'close', settled, '--reason', 'settled by the chat answer, recorded elsewhere', role='autopilot')
    check(rc == 0 and row(settled)['status'] == 'closed' and outcome(settled) == 'dropped', 'away: autopilot closes a settled question', err)
    # A question another ruling answers closes superseded.
    answered, answering = create('a', 'answered question', '-t', 'decision', kind='decision'), create('a', 'answering ruling', '-t', 'decision', kind='decision')
    check(run('a', 'claim', answering)[0] == 0 and run('a', 'ruling', 'record', answering, str(draft))[0] == 0, 'answered: the ruling is recorded')
    rc, _, err, _ = run('a', 'ruling', 'release', answering, '--closes', f'{answered}={answering}')
    check(rc == 0 and row(answered)['status'] == 'closed' and outcome(answered) == 'superseded', 'answered: the question closes as superseded', err)

    # 7 and 8. Someday and "remind me on a day" are deferred, not started by themselves; a question put off is deferred too; the user's
    # deferral is undone only by the user (through a deciding session).
    someday = create('a', 'scenario 7: someday dark mode', '--no-commit', kind='task')
    remind = create('a', 'scenario 7: remind me', '--no-commit', kind='task')
    parked = create('a', 'scenario 8: a question put off', '-t', 'decision', kind='decision')
    check(run('a', 'defer', someday, '--reason', 'someday: nobody needs dark mode yet')[0] == 0
          and run('a', 'defer', remind, '--reason', 'remind me', '--until', '2020-01-06')[0] == 0
          and run('a', 'defer', parked, '--reason', 'put off without a date')[0] == 0, 'scenario 7, 8: set aside')
    run('a', 'queue')  # a read: nothing reopens by itself
    check(all(row(one)['status'] == 'deferred' for one in (someday, remind, parked))
          and (row(remind).get('metadata') or {}).get('revisit') == '2020-01-06' and not (row(someday).get('metadata') or {}).get('revisit'),
          'scenario 7, 8: they stay deferred after a read, the date only a revisit day')
    rc, _, err, _ = run('a', 'claim', someday, role='agent')
    check(rc == 1 and not row(someday).get('assignee'), 'scenario 7: a deferred task is not claimable', err)
    rc, _, err, _ = run('a', 'undefer', someday, role='agent')
    check(rc != 0 and row(someday)['status'] == 'deferred', "scenario 7: an agent session does not undo the user's deferral", err)
    check(run('a', 'undefer', someday, remind, parked)[0] == 0 and all(row(one)['status'] == 'open' for one in (someday, remind, parked)),
          'scenario 7, 8: a deciding session undefers for the user')

    # 10. A step only the user takes is a human gate: the CR waits on it; resolving the gate frees the CR.
    ten = create('a', 'scenario 10: deploy waits for the key rotation')
    task(ten, 'deploy')
    rc, out, err, _ = run('a', 'gate', 'create', '--blocks', ten, '--reason', 'rotate the API key before deploy')
    gate = next((one['id'] for one in items('a').values() if one.get('issue_type') == 'gate' and one['status'] != 'closed'), None)
    check(rc == 0 and gate, 'scenario 10: the gate is filed', err + out)
    rc, _, err, _ = run('a', 'claim', ten, role='agent')
    check(rc == 1 and not row(ten).get('assignee'), 'scenario 10: the CR waits on the gate', err)
    rc, _, err, _ = run('a', 'gate', 'resolve', gate, role='agent')
    check(rc != 0 and row(gate)['status'] != 'closed', 'scenario 10: a worker does not resolve the user\'s step', err)
    check(run('a', 'gate', 'resolve', gate, '--reason', 'the key is rotated')[0] == 0 and run('a', 'claim', ten, role='agent')[0] == 0,
          'scenario 10: resolving the gate frees the CR')

    # 9. A milestone waits on nothing: its change requests are part of it, and it is accepted once their work is done.
    milestone = create('a', 'scenario 9: the milestone', kind='milestone')
    member = create('a', 'scenario 9: a member')
    member_item = task(member, 'the member\'s work')
    check(run('a', 'move', member, '--to', milestone)[0] == 0, 'scenario 9: a change request joins a milestone')
    rc, _, err, _ = run('a', 'wait', milestone, '--on', member, '--for', 'its members')
    check(rc != 0 and 'waits on nothing' in err, 'scenario 9: a milestone does not wait', err)
    rc, _, err, _ = run('a', 'claim', milestone)
    check(rc != 0 and not row(milestone).get('assignee') and member_item in err, 'scenario 9: the milestone is not ready while its work is open, naming it', err)
    check(run('a', 'close', member_item, '--reason', 'scenario 9: the work is moot', '--outcome', 'dropped')[0] == 0
          and run('a', 'cr', 'reject', member, 'scenario 9: the member is dropped')[0] == 0, 'scenario 9: the member is done')
    check(run('a', 'claim', milestone)[0] == 0 and run('a', 'close', milestone, '--reason', 'the user accepted the milestone')[0] == 0
          and row(milestone)['status'] == 'closed' and (row(milestone).get('metadata') or {}).get('outcome') == 'accepted',
          'scenario 9: ready once its work is done, and accepted')
    rc, _, err, _ = bd('a', 'create', 'a timer gate', '-t', 'gate', '--description', 'x', '--silent')
    check(rc != 0 and 'agents board gate create' in err, 'a gate is made by the human gate verb only', err)

    # 13. Two sessions claim at once: the compare-and-set lets exactly one win.
    race = create('a', 'scenario 13: two claims at once')
    task(race, 'the item')
    results: dict[str, int] = {}
    threads = [threading.Thread(target=lambda role=role: results.__setitem__(role, run('a', 'claim', race, role=role)[0])) for role in ('agent', 'solo')]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    holder = row(race).get('assignee')
    check(sorted(results.values()) == [0, 1] and holder and holder.startswith(session('a', next(role for role, code in results.items() if code == 0))[-8:]),
          'scenario 13: exactly one claim wins, and holds', (results, holder))
    check(wt(race).is_dir() and git('branch', '--list', f'cr/{race}', cwd=side).strip(), 'scenario 13: the winner\'s worktree and branch survive the loser\'s claim')


def t_move() -> None:
    """board relocate (beads-setup.md#history) to a local fresh repository, a stale clone told, its rejoin, a new joiner."""
    settle('a', 'b')
    wait_until(lambda: not waits(), options.seconds * 3)
    item = create('a', 'survives the move')
    settle('a', 'b')
    wait_until(lambda: not waits(), options.seconds * 3)
    git('init', '-q', '--bare', 'fresh.git')
    git('push', '-q', str(ROOT / 'fresh.git'), 'main', cwd=ROOT / 'seed')
    fresh = f'git+file://{ROOT}/fresh.git'
    rc, _, err, _ = run('a', 'relocate', fresh, role='agent')
    check(rc == 1 and 'only lead' in err, 'move: an agent is refused', err)
    rc, _, err, _ = run('a', 'relocate', f'git+file://{ROOT}/empty.git')
    check(rc == 1 and 'empty' in err and 'not set' in bd('a', 'config', 'get', 'custom.board.moved')[1], 'move: an empty repository is refused before the note', err)
    before = commits('a')
    rc, out, err, _ = run('a', 'relocate', fresh)
    check(rc == 0 and commits('a') < before, 'move: flattened and pushed', err + out)
    check('refs/dolt/data' in git('for-each-ref', cwd=ROOT / 'remote.git') and 'refs/dolt/data' in git('for-each-ref', cwd=ROOT / 'fresh.git'),
          'move: the old data stays, the new repository holds the board')
    check('not set' in bd('a', 'config', 'get', 'custom.board.moved')[1] and 'fresh.git' in remotes('a') and 'remote.git' not in remotes('a'),
          "move: the mover's board carries no note and syncs with the new repository", remotes('a'))
    rc, _, err, _ = run('a', 'health')
    check(rc == 0 and 'moved' not in err, 'move: the mover works on', err)
    # A write between pulls lands on the old board; the stale clone learns at its next sync, and refuses writes.
    (ROOT / 'b/.beads/board-sync/pulled').touch()
    stale = create('b', 'written before b knows')
    check(wait_until(lambda: sync_state('b').get('moved') == fresh, options.seconds * 5), 'a stale clone learns of the move at its next sync', sync_state('b'))
    rc, _, err, _ = bd('b', 'create', 'refused after the move', '-t', 'task', '--description', 'x')
    check(rc != 0 and f'board join {fresh}' in err, 'a moved board refuses writes, naming the join', err)
    rc, _, err, _ = run('b', 'claim', role='agent')
    check(rc != 0 and 'board join' in err, 'a moved board refuses claims', err)
    rc, out, err, _ = run('b', 'show', item)
    check(rc == 0 and 'moved' in err, 'a moved board still reads, and says it moved', err)
    rc, _, err, _ = run('b', 'join', f'git+file://{ROOT}/missing.git', role=None)
    check(rc == 1 and mark('b') and sync_state('b').get('moved') == fresh and stale in items('b'), 'a failed rejoin puts the old board back', err)
    rc, out, err, _ = run('b', 'join', fresh, role=None)
    check(rc == 0 and stale in out and 'board bd --raw --yes import' in out, 'rejoin: lists the items the new board lacks, with the raw import', err + out)
    check(not git('status', '--short', cwd=ROOT / 'b').strip(), 'rejoin: the kept copy stays out of project history', git('status', '--short', cwd=ROOT / 'b'))
    rows = items('b')
    check(item in rows and stale not in rows and not sync_state('b').get('moved'), 'rejoin: the new board, without the stale write')
    found = re.search(r'board bd --raw --yes import (\S+)', out)
    rc, _, err, _ = bd('b', 'import', found.group(1) if found else 'missing')
    check(rc == 0 and stale in items('b'), 'bd import brings the stale write over', err)
    mine = create('b', 'after the move')
    settle('a', 'b')
    check(mine in items('a') and stale in items('a'), 'both sides sync on the new repository')
    # New joiners: pointed at the new repository while the old data stays; told there is none once it is deleted.
    git('clone', '-q', 'remote.git', 'c')
    git('config', 'agents.person', 'cara', cwd=ROOT / 'c')
    rc, _, err, _ = run('c', 'join', role=None)
    check(rc == 1 and f'board join {fresh}' in err and not beads_files('c') and not servers('c'), 'a new joiner of the old repository is pointed at the new one', err)
    git('push', '-q', str(ROOT / 'remote.git'), '--delete', 'refs/dolt/data', 'refs/heads/__dolt_remote_info__', cwd=ROOT / 'seed')
    rc, _, err, _ = run('c', 'join', role=None)
    check(rc == 1 and 'no board data' in err and not beads_files('c'), 'once the old data is deleted, join says there is none and asks for the address', err)
    rc, out, err, _ = run('c', 'join', fresh, role=None)
    check(rc == 0 and item in items('c') and stale in items('c'), 'a new joiner joins the new repository', err + out)


SETTINGS = {'create.require-description': 'true', 'validation.on-close': 'error', 'lint.sections.decision': 'Question,Decision,Rule owner',
            'events-journal': 'true', 'events-journal-retain-days': '30', 'no-git-ops': 'true',
            'status.custom': 'decided:wip,in_force:active,in_review:wip,passed:wip', 'types.custom': 'design,change-request', 'min_hash_length': '5', 'custom.board.model': '1'}


def setting(side: str, key: str) -> str:
    return json.loads(bd(side, 'config', 'get', '--json', key, role=None)[1] or '{}').get('value', '')


def t_setup() -> None:
    """board setup (r38-q218): creates a board or brings an existing one to the current settings, safe to rerun."""
    for side in ('setupproj', 'setupsrv'):
        git('init', '-q', '-b', 'main', side)
    (ROOT / 'setupproj' / 'kept.db').write_text('project data')
    git('add', 'kept.db', cwd=ROOT / 'setupproj')
    git('commit', '-q', '-m', 'a tracked db file', cwd=ROOT / 'setupproj')
    rc, out, err, _ = run('setupproj', 'setup', '--embedded', role=None)
    meta = json.loads((ROOT / 'setupproj/.beads/metadata.json').read_text()) if (ROOT / 'setupproj/.beads/metadata.json').is_file() else {}
    check(rc == 0 and meta.get('dolt_mode') == 'embedded' and meta.get('dolt_database') == 'setupproj', 'setup --embedded: a new embedded board, named after the project', (err + out, meta))
    wrong = {key: setting('setupproj', key) for key in SETTINGS if setting('setupproj', key) != SETTINGS[key]}
    check(not wrong, 'setup: a new board gets every setting', wrong)
    check('*.db' in out and 'kept.db' in out, 'setup: reports the exclude line hiding a tracked project file', out)
    check(not git('status', '--short', cwd=ROOT / 'setupproj').strip() and not (ROOT / 'setupproj/AGENTS.md').exists()
          and not git('config', '--get', 'core.hooksPath', cwd=ROOT / 'setupproj').strip(), 'setup: no project files, agent files or hooks',
          git('status', '--short', cwd=ROOT / 'setupproj'))
    bd('setupproj', 'config', 'set', 'validation.on-close', 'warn', role=None)
    bd('setupproj', 'config', 'unset', 'types.custom', role=None)
    bd('setupproj', 'dolt', 'commit', '-m', 'drift', role=None)
    rc, out, err, _ = run('setupproj', 'setup', role=None)
    check(rc == 0 and 'validation.on-close: warn -> error' in out and 'types.custom: (unset) -> design' in out,
          'setup on an existing board: sets the missing setting, resets the differing one, printing old and new', err + out)
    check(setting('setupproj', 'validation.on-close') == 'error' and setting('setupproj', 'types.custom') == 'design,change-request', 'setup: the values are applied')
    check('already has a board' in out, 'setup: an existing board is never re-created', out)
    rc, out, err, _ = run('setupproj', 'setup', role=None)
    check(rc == 0 and ' -> ' not in out and 'up to date' in out, 'setup again: nothing to do', err + out)
    bd('setupproj', 'config', 'unset', 'custom.board.model', role=None)
    bd('setupproj', 'dolt', 'commit', '-m', 'an older board', role=None)
    rc, out, err, _ = run('setupproj', 'setup', role=None)
    check(rc == 0 and setting('setupproj', 'custom.board.model') == '', 'setup on an existing board without the marker leaves it unset: only board-migrate writes it', err + out)
    rc, out, err, _ = run('setupproj', 'comment', 'nothing-here', '-m', 'a write on a board without the marker', role=None)
    check(rc != 0 and '/board-migrate' in err and 'nothing-here' not in out, 'a write verb on a board without the marker is refused, naming /board-migrate', err + out)
    rc, out, err, _ = run('setupproj', 'check', role=None)
    check(rc == 0, 'a read (check) works on a board without the marker', err + out)
    rc, out, err, _ = run('setupproj', 'bd', '--raw', '--yes', 'config', 'set', 'custom.board.model', '1', role=None)
    check(rc == 0 and setting('setupproj', 'custom.board.model') == '1', 'raw bd, board-migrate\'s way in, writes the marker on a board without it', err + out)
    rc, out, err, _ = run('setupproj', 'comment', 'nothing-here', '-m', 'a write on a board with the marker', role=None)
    check('/board-migrate' not in err, 'a write verb on a board with the marker is not refused for it', err + out)
    rc, out, err, _ = run('setupproj', 'setup', '--target', 'main', '--setup', 'true', '--checks', 'true', '--look', 'after', '--view', 'result', role=None)
    got = {key: setting('setupproj', f'custom.board.{key}') for key in ('target', 'setup', 'checks', 'look', 'view')}
    check(rc == 0 and got == {'target': 'main', 'setup': 'true', 'checks': 'true', 'look': 'after', 'view': 'result'}, 'setup: the project setting flags are applied', (err + out, got))
    rc, out, err, _ = run('setupproj', 'setup', '--look', 'sometimes', role=None)
    check(rc == 1 and 'not one of' in err and setting('setupproj', 'custom.board.look') == 'after', 'setup: an invalid setting is refused and changes nothing', err + out)
    rc, out, err, _ = run('setupproj', 'share', role=None)
    check(rc == 1 and 'board setup --server' in err, 'share on an embedded board: refused, naming the conversion', err + out)
    made = [bd('setupproj', 'create', title, '--description', f'{title}, an item the conversion keeps', '--silent', role=None)[1].strip()
            for title in ('first kept', 'second kept')]
    rc, out, err, _ = run('setupproj', 'setup', '--server', role=None)
    meta = json.loads((ROOT / 'setupproj/.beads/metadata.json').read_text()) if (ROOT / 'setupproj/.beads/metadata.json').is_file() else {}
    kept = sorted((ROOT / 'setupproj').glob('.beads.before-server-*'))
    rc_list, listed, _, _ = bd('setupproj', 'list', '--all', '--json', role=None)
    present = {item['id'] for item in json.loads(listed or '[]')} if rc_list == 0 else set()
    check(rc == 0 and meta.get('dolt_mode') == 'server' and meta.get('dolt_database') == 'setupproj' and set(made) <= present and len(kept) == 1,
          'setup --server on an embedded board: converts it in place, every item kept, the old folder beside it', (err + out, meta, made, present, kept))
    check(setting('setupproj', 'dolt.auto-start') == 'false' and setting('setupproj', 'validation.on-close') == 'error',
          'setup --server: the converted board has the server settings and the rest', (setting('setupproj', 'dolt.auto-start'), err + out))
    status = bd('setupproj', 'backup', 'status', role=None)[1]
    check('Destination' not in status, "setup --server: the conversion's backup is not left registered", status)
    check(not git('status', '--short', cwd=ROOT / 'setupproj').strip(), 'setup --server: the kept folder stays out of git status',
          git('status', '--short', cwd=ROOT / 'setupproj'))
    rc, out, err, _ = run('setupproj', 'setup', '--embedded', role=None)
    check(rc == 1 and 'server' in err, 'setup --embedded on a server board: refused, a board is never converted back', err + out)
    rc, out, err, _ = run('setupsrv', 'setup', '--prefix', 'srv', role=None)
    meta = json.loads((ROOT / 'setupsrv/.beads/metadata.json').read_text()) if (ROOT / 'setupsrv/.beads/metadata.json').is_file() else {}
    check(rc == 0 and meta.get('dolt_mode') == 'server' and meta.get('dolt_database') == 'srv' and setting('setupsrv', 'dolt.auto-start') == 'false',
          'setup: a new board is a server board that board starts itself', (err + out, meta))
    check(setting('setupsrv', 'dolt.auto-commit') != 'batch', 'setup: an unshared board keeps per-write commits', setting('setupsrv', 'dolt.auto-commit'))
    rc, out, err, _ = run('a', 'setup', role=None)
    check(rc == 0 and 'up to date' in out and ' -> ' not in out, 'setup on a shared board: share applied the same lists, the shared ones included', err + out)


def t_migrate() -> None:
    """board-migrate's conversion on a board holding every old form: refused writes and open reads before, a dry run that writes nothing,
    the conversions, a rerun that finds nothing, `check` clean, and the marker last."""
    side = 'migproj'
    git('init', '-q', '-b', 'main', side)
    git('commit', '-q', '--allow-empty', '-m', 'init', cwd=ROOT / side)
    rc, out, err, _ = run(side, 'setup', '--embedded', '--prefix', 'mg', '--target', 'main', '--setup', 'true', '--checks', 'true', '--look', 'before', '--view', 'code', role=None)
    check(rc == 0, 'migrate: the board is set up', err + out)
    raw(side, 'config', 'set', 'status.custom', 'decided:wip,released:active,in_review:wip,needs_ratification:wip,needs_acceptance:wip,in_force:active,passed:wip')
    raw(side, 'config', 'unset', 'custom.board.model')
    ids: dict[str, str] = {}

    def make(name: str, title: str, *flags: str, kind: str = 'task') -> None:
        rc, out, err, _ = raw(side, 'create', title, '-t', kind, '-d', f'{title} text', '--silent', *flags)
        if rc:
            raise RuntimeError(f'create {title}: {err}{out}')
        ids[name] = out.strip().splitlines()[-1]

    def update(name: str, *flags: str) -> None:
        rc, out, err, _ = raw(side, 'update', ids[name], *flags)
        if rc:
            raise RuntimeError(f'update {name}: {err}{out}')

    def link(name: str, target: str, kind: str) -> None:
        result = subprocess.run([sys.executable, '-B', BOARD, 'bd', '--raw', '--yes', 'batch', '-m', 'fixture', '--json'], cwd=ROOT / side, capture_output=True, text=True,
                                env=base_env(side), input=f'dep add {ids[name]} {ids[target]} {kind}\n')
        if result.returncode:
            raise RuntimeError(f'link {name}: {result.stderr}{result.stdout}')

    no_commit = ['--metadata', '{"no_commit":true}']
    for name, title in (('cr1', 'CR one'), ('cr2', 'CR in review, claimed'), ('cr3', 'CR in review, unknown hand-over'), ('cr4', 'CR awaiting acceptance'), ('cr5', 'CR awaiting acceptance with its own look'), ('cr6', 'CR in progress')):
        make(name, title, kind='change-request')
    make('dsg_review', 'design item in review, held', '--parent', ids['cr1'], kind='design')
    update('dsg_review', '--status', 'in_review', '--assignee', 'abcd1234')
    make('def_item', 'deferred item of a live change request', '--parent', ids['cr1'])
    raw(side, 'defer', ids['def_item'])
    make('cr7', 'a deferred change request', kind='change-request')
    make('def_under', 'item of the deferred change request', '--parent', ids['cr7'])
    raw(side, 'defer', ids['def_under'])
    raw(side, 'defer', ids['cr7'])
    make('loose', 'loose work item', '--labels', 'topic:loose')
    make('loose_def', 'loose deferred work item')
    raw(side, 'defer', ids['loose_def'])
    make('held', 'held item', '--parent', ids['cr1'])
    update('held', '--assignee', 'abcd1234', '--set-metadata', 'hold=work', '--status', 'in_progress')
    make('bug', 'a bug item', '--parent', ids['cr1'], kind='bug')
    make('design', 'a design item', '--parent', ids['cr1'], kind='design')
    make('spike', 'a spike', *no_commit, kind='spike')
    make('reopened', 'reopened item', '--parent', ids['cr1'])
    update('reopened', '--set-metadata', 'outcome=done')
    make('target', 'link target', *no_commit)
    for name, kind in (('waits', 'waits-for'), ('cond', 'conditional-blocks'), ('found', 'discovered-from'), ('related', 'related')):
        make(name, f'item with {kind}', '--parent', ids['cr1'])
        link(name, 'target', kind)
    make('milestone', 'a milestone', kind='milestone')
    link('milestone', 'cr4', 'blocks')
    make('ms_closed', 'a closed milestone', kind='milestone')
    make('released', 'released ruling', kind='decision')
    update('released', '--status', 'released')
    make('unratified', 'unratified ruling', kind='decision')
    update('unratified', '--status', 'needs_ratification', '--description', '## Question\nWhich?\n## Decision\nThis.\n## Reversal\nUndo this by hand.\n')
    make('old_ruling', 'superseded ruling', kind='decision')
    make('new_ruling', 'newer ruling', kind='decision')
    link('old_ruling', 'new_ruling', 'supersedes')
    make('planned', 'planned ruling', kind='decision')
    make('dropped', 'dropped ruling', kind='decision')
    make('user_gate', 'user rotate the key', kind='gate')
    make('waiter', 'item waiting on the gate', '--parent', ids['cr1'])
    link('waiter', 'user_gate', 'blocks')
    make('closed_gate', 'an old gate', kind='gate')
    rc, out, err, _ = raw(side, 'gate', 'create', '--type=timer', '--blocks', ids['target'], '--timeout', '2h', '--title', 'Timer gate')
    make('dated', 'dated deferral', *no_commit, '--defer', '2027-03-04')
    make('conditional', 'conditional deferral', *no_commit)
    update('conditional', '--notes', f"revisit after {ids['target']} lands")
    raw(side, 'defer', ids['conditional'])
    make('user_item', 'user step item', *no_commit)
    update('user_item', '--assignee', 'user')
    make('ratify', 'Ratify the landing', '--parent', ids['cr1'])
    update('ratify', '--status', 'needs_ratification', '--set-metadata', 'ratification=landing')
    make('epic', 'Big topic epic', kind='epic')
    make('child', 'epic child', '--parent', ids['epic'], *no_commit)
    update('cr2', '--status', 'in_review', '--assignee', 'abcd1234')
    update('cr3', '--status', 'in_review')
    update('cr4', '--status', 'needs_acceptance')
    for name, title, status in (('ck1', 'checkpoint CR, open', None), ('ck2', 'checkpoint CR, awaiting acceptance', 'needs_acceptance')):
        make(name, title, kind='change-request')
        update(name, '--set-metadata', 'checkpoint=design', *(['--status', status, '--set-metadata', 'review_tip=abc123'] if status else []))
        make(f'{name}_design', f'{title}: design', '--parent', ids[name], kind='design')
        if status:
            update(f'{name}_design', '--status', 'in_review')
    make('ck_waiter', 'waits on a design item', *no_commit)
    link('ck_waiter', 'ck1_design', 'blocks')
    update('cr5', '--status', 'needs_acceptance', '--set-metadata', 'look=after')
    update('cr6', '--status', 'in_progress', '--assignee', 'abcd1234')
    for name in ('cr2', 'cr3', 'cr4', 'cr5', 'cr6', 'ck1', 'ck2'):
        git('worktree', 'add', '-q', f'.worktrees/{ids[name]}', '-b', f'cr/{ids[name]}', cwd=ROOT / side)
    for name, reason in (('ms_closed', 'closed in the earlier model'), ('closed_gate', 'closed in the earlier model'), ('old_ruling', 'superseded by the newer ruling'),
                         ('planned', 'planned in nixes-abc and done'), ('dropped', 'no longer wanted at all')):
        raw(side, 'close', ids[name], '--reason', reason)
    run(side, 'setup', role=None)  # status.custom to the current list; the records keep their old statuses
    raw(side, 'config', 'unset', 'custom.board.model')
    raw(side, 'dolt', 'commit', '-m', 'old forms')

    script = HERE.parent / 'skills' / 'board-migrate' / 'scripts' / 'convert-stored-forms.py'

    def migrate(*flags: str):
        result = subprocess.run([sys.executable, '-B', str(script), *flags], cwd=ROOT / side, capture_output=True, text=True, env=base_env(side), input='')
        return result.returncode, result.stdout, result.stderr

    rc, out, err, _ = run(side, 'update', ids['bug'], '--title', 'a bug item, retitled', role=None)
    check(rc != 0 and '/board-migrate' in err, 'migrate: a write verb on the old board is refused, naming /board-migrate', err + out)
    rc, out, err, _ = run(side, 'show', ids['bug'])
    check(rc == 0 and 'a bug item' in out and 'retitled' not in out, 'migrate: reads work on the old board', err + out)
    before = items(side)
    rc, out, err = migrate()
    check(rc == 0 and out.count('would: ') >= 20 and items(side) == before, 'migrate: the dry run lists the conversions and writes nothing', err + out)
    rc, out, err = migrate('--rehearse')
    check(rc == 0 and 'rehearsal on a copy' in out and out.index('--- summary') < out.index('--- conversion (exit 0)') and 'conversion(s) applied' in out and 'blocked' in out and items(side) == before and not list(Path('/tmp').glob('board-rehearsal-*')),
          'migrate: --rehearse converts a copy in a temporary board and writes nothing here', err + out)
    rc, out, err = migrate('--mark')
    check(rc == 1 and setting(side, 'custom.board.model') == '', 'migrate: the marker waits for the conversions', err + out)
    rc, out, err = migrate('--apply')
    check(rc == 0 and 'conversion(s) applied' in out and 'no recorded author' in out and 'timer gate' in out, 'migrate: --apply converts and lists what is left for the user', err + out)
    rc, out, err = migrate('--apply')
    check(rc == 0 and out.startswith('0 conversion(s) applied'), 'migrate: a rerun finds nothing to convert', err + out)

    now = items(side)

    def row(name: str) -> dict:
        return now[ids[name]]

    def deps(name: str) -> set[tuple[str, str]]:
        return {(d['depends_on_id'], d['type']) for d in row(name).get('dependencies') or [] if d['issue_id'] == ids[name]}

    def meta_of(name: str) -> dict:
        return row(name).get('metadata') or {}

    check(not row('held').get('assignee') and 'hold' not in meta_of('held') and row('held')['status'] == 'open', 'migrate: the hold on an item is cleared and in_progress is open', row('held'))
    check(row('bug')['issue_type'] == 'task' and 'kind:bug' in row('bug')['labels'] and 'kind:design' in row('design')['labels'] and row('spike')['issue_type'] == 'task',
          'migrate: bug, design and spike types become tasks, with kind labels where there is one', (row('bug'), row('design'), row('spike')))
    check(row('dsg_review')['issue_type'] == 'task' and row('dsg_review')['status'] == 'open' and not row('dsg_review').get('assignee') and 'kind:design' in row('dsg_review')['labels'],
          'migrate: a design-typed item in review, held, converges in one apply', row('dsg_review'))
    check(row('def_item')['status'] == 'deferred' and meta_of('def_item').get('found_in') == ids['cr1'] and not any(kind == 'parent-child' for _, kind in deps('def_item')),
          'migrate: a deferred item of a live change request leaves it as a deferred task found in it', (row('def_item')['status'], meta_of('def_item'), deps('def_item')))
    check(row('def_under')['status'] == 'open' and (ids['cr7'], 'parent-child') in deps('def_under') and row('cr7')['status'] == 'deferred',
          'migrate: an item of a deferred change request is open, the deferral of its change request holds it', (row('def_under')['status'], deps('def_under')))
    filed = [i for i in now.values() if i.get('external_ref') == f"migrated-cr:{ids['loose']}"]
    check(len(filed) == 1 and filed[0]['issue_type'] == 'change-request' and (filed[0]['id'], 'parent-child') in deps('loose') and 'topic:loose' in filed[0].get('labels', [])
          and not any(kind == 'parent-child' for _, kind in deps('spike')) and row('loose_def')['status'] == 'deferred' and not any(kind == 'parent-child' for _, kind in deps('loose_def')),
          'migrate: a work item outside any change request becomes the only item of one; a no-commit task and a deferred one stay tasks', (filed, deps('loose')))
    check('outcome' not in meta_of('reopened'), 'migrate: an open record carries no outcome', meta_of('reopened'))
    check((ids['target'], 'blocks') in deps('waits') and (ids['target'], 'blocks') in deps('cond') and not {'waits-for', 'conditional-blocks'} & {kind for _, kind in deps('waits') | deps('cond')},
          'migrate: waits-for and conditional-blocks become waits', (deps('waits'), deps('cond')))
    check(meta_of('found').get('found_in') == ids['target'] and not any(kind == 'discovered-from' for _, kind in deps('found')), 'migrate: discovered-from becomes found_in', (meta_of('found'), deps('found')))
    check((ids['target'], 'relates-to') in deps('related'), 'migrate: related becomes relates-to', deps('related'))
    check((ids['milestone'], 'parent-child') in deps('cr4') and not deps('milestone') and row('cr4')['status'] == 'passed',
          'migrate: a milestone waiting on a change request holds it as a part; needs_acceptance is passed', (deps('cr4'), deps('milestone')))
    check(row('cr5')['status'] == 'passed' and meta_of('cr5').get('look') == 'before' and 'look' not in meta_of('cr4'),
          'migrate: a change request that awaited acceptance waits for it as passed, whatever look it carried', (meta_of('cr4'), meta_of('cr5')))
    check(row('cr6')['status'] == 'open' and row('cr6')['assignee'] == 'abcd1234' and meta_of('cr6').get('hold') == 'work',
          'migrate: an in-progress change request stays held, its hold is work', (row('cr6')['status'], row('cr6').get('assignee'), meta_of('cr6')))
    check(row('released')['status'] == 'in_force' and row('unratified')['status'] == 'in_force', 'migrate: released and an unratified ruling are in_force', (row('released')['status'], row('unratified')['status']))
    confirm = [i for i in now.values() if i.get('external_ref') == f"confirm:{ids['unratified']}"]
    check(len(confirm) == 1 and confirm[0]['status'] == 'open' and (ids['unratified'], 'relates-to') in {(d['depends_on_id'], d['type']) for d in confirm[0].get('dependencies') or []}
          and 'Undo this by hand' in confirm[0]['description'], 'migrate: an unratified ruling stays in force with a question to confirm or revise it', confirm)
    check([meta_of(name).get('outcome') for name in ('old_ruling', 'planned', 'dropped', 'closed_gate', 'ms_closed')] == ['superseded', 'planned', 'dropped', 'resolved', 'accepted'],
          'migrate: closed decisions, gates and milestones get their outcome', [meta_of(name).get('outcome') for name in ('old_ruling', 'planned', 'dropped', 'closed_gate', 'ms_closed')])
    check(meta_of('dated').get('revisit') == '2027-03-04' and row('dated')['status'] == 'deferred' and not row('dated').get('defer_until'),
          'migrate: defer_until becomes the revisit field and leaves bd', (meta_of('dated'), row('dated').get('defer_until')))
    check(row('conditional')['status'] == 'open' and (ids['target'], 'blocks') in deps('conditional'), 'migrate: a deferral on a condition becomes a wait', (row('conditional')['status'], deps('conditional')))
    gates = [i for i in now.values() if i['issue_type'] == 'gate' and i['status'] == 'open' and i.get('await_type') == 'human']
    check(len(gates) == 2 and all(any(kind == 'supersedes' for _, kind in {(d['depends_on_id'], d['type']) for d in g.get('dependencies') or []}) for g in gates)
          and any((g['id'], 'blocks') in deps('waiter') for g in gates) and row('user_gate')['status'] == 'closed' and row('user_item')['status'] == 'closed',
          'migrate: a gate and a user item become human gates that supersede them, the waiter moved to the new gate', (gates, deps('waiter')))
    questions = [i for i in now.values() if i['issue_type'] == 'decision' and i['status'] == 'open' and i.get('external_ref') == f"migrated:{ids['ratify']}"]
    check(len(questions) == 1 and row('ratify')['status'] == 'closed', 'migrate: an open landing ratification becomes an open question', questions)
    check('topic:big-topic-epic' in row('child')['labels'] and row('epic')['status'] == 'closed', 'migrate: an epic gives its children a topic label and closes', row('child'))
    check(meta_of('cr2').get('author') == 'abcd1234' and 'author' not in meta_of('cr3'), 'migrate: the author is the holder of record, and none is invented', (meta_of('cr2'), meta_of('cr3')))
    rc, out, err, _ = run(side, 'check', '--limit', '0')
    check(rc == 1 and 'cr-checkpoint' in out and 'convention deviations: 2' in out, 'migrate: check names the live checkpoints, which only the checkpoint conversion settles', err + out)
    subprocess.run(['bash', REGISTRY, 'activate', 'lead'], cwd=ROOT / side, env={**base_env(side), 'CLAUDE_CODE_SESSION_ID': session(side, 'lead')}, capture_output=True, check=True)
    checkpoints = HERE.parent / 'skills' / 'board-migrate' / 'scripts' / 'convert-design-checkpoints.py'
    mapping = ROOT / 'checkpoint-mapping.json'

    def convert_checkpoints(*args: str):
        result = subprocess.run([sys.executable, '-B', str(checkpoints), *args], cwd=ROOT / side, capture_output=True, text=True, input='',
                                env={**base_env(side), 'CLAUDE_CODE_SESSION_ID': session(side, 'lead')})
        return result.returncode, result.stdout, result.stderr

    rc, out, err = convert_checkpoints('inventory', '--mapping', str(mapping))
    check(rc == 0 and 'authoring-clear' in mapping.read_text() and 'authoring-return' in mapping.read_text(), 'migrate: the checkpoint inventory sees both live checkpoints', err + out)
    approved = json.loads(mapping.read_text())
    approved['approved_by'] = 'the test'
    mapping.write_text(json.dumps(approved))
    rc, out, err = convert_checkpoints('apply', str(mapping), '--apply')
    check(rc == 0, 'migrate: the checkpoint conversion applies', err + out)
    rc, out, err = convert_checkpoints('apply', str(mapping), '--apply')
    check(rc == 0 and 'converted already' in out, 'migrate: the checkpoint conversion reruns cleanly', err + out)
    rc, out, err = convert_checkpoints('verify')
    check(rc == 0, 'migrate: no checkpoint is left', err + out)
    now = items(side)
    check(row('ck2')['status'] == 'open' and 'checkpoint' not in meta_of('ck1') and 'checkpoint' not in meta_of('ck2')
          and (ids['ck1'], 'blocks') in deps('ck_waiter'), 'migrate: a checkpoint change request is an ordinary open one, its waiter waits on it', (row('ck2')['status'], deps('ck_waiter')))
    rc, out, err, _ = run(side, 'check', '--limit', '0')
    check(rc == 0 and 'convention deviations: 0' in out, 'migrate: check is clean after the conversions', err + out)
    rc, out, err = migrate('--mark')
    check(rc == 0 and setting(side, 'custom.board.model') == '1', 'migrate: --mark writes the marker last', err + out)
    rc, out, err, _ = run(side, 'update', ids['bug'], '--title', 'a bug item, retitled', role=None)
    check(rc == 0, 'migrate: a write verb works once the marker is set', err + out)


def cleanup() -> None:
    for pid in waits():
        with contextlib.suppress(ProcessLookupError):  # a wait that ended since it was listed
            os.kill(pid, signal.SIGKILL)
    for side in ('a', 'b', 'c', 'unset', 'setupproj', 'setupsrv'):
        if (ROOT / side / '.beads').exists():
            subprocess.run([sys.executable, '-B', BOARD, 'bd', 'dolt', 'stop'], cwd=ROOT / side, env=base_env(side), capture_output=True, input='', text=True)
    shutil.rmtree(ROOT, ignore_errors=True)


def alive(pid: int) -> bool:
    """A process that runs (a zombie, which only its parent has yet to reap, does not)."""
    state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith('Z')


def stop_dead_servers() -> list[int]:
    """Stops the Dolt servers under /tmp/shared-board.* (/private/tmp on macOS) whose run is gone: its folder's runner.pid
    names no live process. A folder without one belongs to a run of an older script, gone only when no test-shared-board.py
    runs at all. Another live run's servers stay."""
    ps = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True).stdout
    runners = any('test-shared-board.py' in row and not row.split(maxsplit=1)[0] == str(os.getpid()) for row in ps.splitlines())
    stopped = []
    for row in ps.splitlines():
        pid, _, command = row.strip().partition(' ')
        found = re.search(r'/tmp/(shared-board\.[^/\s]+)/', command)
        if not found or 'dolt' not in command or not pid.isdigit() or int(pid) == os.getpid() or found.group(1) == ROOT.name:
            continue
        try:
            owner = int((Path('/tmp') / found.group(1) / RUNNER_PID).read_text().strip())
        except (OSError, ValueError):
            owner = None
        if (alive(owner) if owner else runners):
            continue
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(int(pid), sig)
            except ProcessLookupError:
                break
            if wait_until(lambda: not alive(int(pid)), 3):
                break
        stopped.append(int(pid))
    return stopped


CHILDREN: list[subprocess.Popen] = []  # a parallel run's group runs


def on_signal(signum, frame) -> None:
    for child in CHILDREN:
        if child.poll() is None:
            child.send_signal(signal.SIGTERM)  # each child stops its servers and removes its folder
    for child in CHILDREN:
        try:
            child.wait(30)
        except subprocess.TimeoutExpired:
            child.kill()
    cleanup()
    sys.exit(128 + signum)


def run_parallel(groups: list[str]) -> int:
    """Each group as its own --only run (unshared and share_join run inside each); output in ORDER, then one verdict."""
    args = ['--board', BOARD, '--seconds', str(options.seconds), '--soak', str(options.soak)]
    outputs = {}
    for name in groups:
        out = tempfile.TemporaryFile('w+', encoding='utf-8')
        CHILDREN.append(subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--only', name, *args],
                                         stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, text=True))
        outputs[name] = out
    failed = []
    for name, child in zip(groups, CHILDREN):
        code = child.wait()
        out = outputs[name]
        out.seek(0)
        text = out.read()
        out.close()
        marker = f'## {name}\n'
        print(text[text.index(marker):] if marker in text and code == 0 else text, end='' if text.endswith('\n') else '\n', flush=True)
        if code != 0:
            failed.append(name)
    print(f"FAILED groups: {', '.join(failed)}" if failed else 'all groups passed', flush=True)
    return 1 if failed else 0


def t_cleanup() -> None:
    """A signalled run removes its folder; a start stops the servers of dead runs and leaves a live run's."""
    def fake_server(folder: Path):
        return subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)', 'dolt', 'sql-server', f'{folder}/a/.beads/dolt'])

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        child = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--idle', '--board', BOARD], stdout=subprocess.PIPE, text=True)
        folder = Path((child.stdout.readline().split(maxsplit=1) or ['', ''])[1].strip() or '/nonexistent')
        check(folder.is_dir() and (folder / RUNNER_PID).read_text() == str(child.pid), f'{sig.name}: the run has its folder', folder)
        child.send_signal(sig)
        try:
            code = child.wait(30)
        except subprocess.TimeoutExpired:
            child.kill()
            code = None
        check(code == 128 + sig and not folder.exists(), f'{sig.name}: the run exits and removes its folder', (code, folder.exists()))
    dead, live, bare = (Path('/tmp') / f'shared-board.cleanuptest-{name}' for name in ('dead', 'live', 'bare'))
    for folder in (dead, live, bare):
        folder.mkdir(exist_ok=True)
    (live / RUNNER_PID).write_text(str(os.getpid()))
    (dead / RUNNER_PID).write_text('999999')  # no such process
    servers_of = {'dead': fake_server(dead), 'live': fake_server(live), 'bare': fake_server(bare)}
    try:
        time.sleep(0.5)  # the interpreters are up with their arguments
        child = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--idle', '--board', BOARD], stdout=subprocess.PIPE, text=True)
        child.stdout.readline()
        child.send_signal(signal.SIGTERM)
        child.wait(30)
        check(wait_until(lambda: servers_of['dead'].poll() is not None, 5), 'start: a dead run\'s server is stopped')
        check(servers_of['live'].poll() is None, 'start: a live run\'s server is left')
        check(servers_of['bare'].poll() is None, 'start: a folder without runner.pid is left while another run (this one) is going')
    finally:
        for server in servers_of.values():
            server.kill()
            server.wait()
        for folder in (dead, live, bare):
            shutil.rmtree(folder, ignore_errors=True)


ORDER = ('unshared', 'share_join', 'setup', 'child_ids', 'queues', 'moves', 'inbox', 'cr', 'scenarios', 'window', 'pull', 'manual_and_dead_wait', 'soak', 'stopped', 'held_elsewhere', 'store', 'move', 'migrate', 'cleanup')
only = {name for name in options.only.split(',') if name}
stop_dead_servers()
for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(signum, on_signal)
if options.idle:
    print('idle', ROOT, flush=True)
    time.sleep(600)
    sys.exit(0)
if not options.only and not options.serial:
    started = time.time()
    code = run_parallel([name for name in ORDER if name not in ('unshared', 'share_join') and (name != 'soak' or options.soak)])
    print(f'   (parallel run {time.time() - started:.0f} s)', flush=True)
    cleanup()
    sys.exit(code)
try:
    setup()
    for name in ORDER:
        # share_join and unshared set up every later group.
        if name == 'soak' and not options.soak and name not in only:
            continue  # an upgrade check: --soak <s> or --only soak runs it
        if not only or name in only or name in ('unshared', 'share_join'):
            print(f'## {name}', flush=True)
            started = time.time()
            globals()[f't_{name}']()
            print(f'   ({time.time() - started:.0f} s)', flush=True)
finally:
    print(f'foreign key retries seen: {retries["retried"]}', flush=True)
    cleanup()
print('FAILED: ' + '; '.join(failures) if failures else 'all passed', flush=True)
sys.exit(1 if failures else 0)
