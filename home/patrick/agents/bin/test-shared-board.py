#!/usr/bin/env python3
"""The board through real bd, real Dolt servers and real git: what the fake-bd checks in bin/test-agent-configs.py cannot show.

    python3 -B bin/test-shared-board.py [--board <path>] [--shared] [--migrate] [--only <name>,<name>] [--serial] [--seconds <s>] [--soak <s>]

The default run (every change request's full check, board-checks.sh) runs the groups any board needs: a board on one clone, setup,
one change request end to end and the suite's own cleanup. Two sets run on request:
- `--shared`, the shared-board groups (two clones syncing through a local bare git remote; SHARING): before a board is first shared,
  after a bd upgrade, and when a change touches sharing or sync;
- `--migrate`, board-migrate's conversion and rehearsal on a board of every earlier stored form (MIGRATION): when a change touches
  board-migrate or the model's stored forms.
`--only` runs the named groups, of any set.

A run starts each group as its own `--only` run at once (each with its own folder and servers) and prints their results in order;
`--serial` runs them one after another in this process, building the two clones once.

Every run has a watcher process: however the run ends (a signal, a crash, SIGKILL), its Dolt servers and sync waits stop and its
folder goes; a parallel run's groups end with it. A start also clears earlier runs whose process is gone (shared-board.* folders in
/tmp, marked by their `runner.pid`).

Needs bd and Dolt, which the validator's build sandbox lacks. After a bd upgrade, run the soak too (`--soak 40`, or
`--only soak`): it is the check that retires the write retry (board WRITE_RETRY_ERROR), so ordinary runs skip it.
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
parser.add_argument('--shared', action='store_true', help='also run the shared-board groups (SHARING)')
parser.add_argument('--migrate', action='store_true', help='also run board-migrate\'s groups (MIGRATION)')
parser.add_argument('--idle', action='store_true', help='internal (the cleanup test): start up, then wait for a signal')
parser.add_argument('--watch', action='store_true', help='internal: the watcher of the run whose folder SB_WATCH_ROOT names')
parser.add_argument('--linked', action='store_true', help='internal: a parallel run\'s group; its stdin closing means the run is gone')
options = parser.parse_args()
if shutil.which('bd') is None:  # the gate's contract (board-checks.sh): a suite that cannot start exits 127, "cannot run", not a failed check
    print('test-shared-board: bd is not installed; the suite needs real bd, Dolt and git clones', file=sys.stderr)
    sys.exit(127)
BOARD = str(Path(options.board).resolve())
REGISTRY = str(Path(BOARD).parent / 'session')
ROOT = Path(os.environ['SB_WATCH_ROOT']) if options.watch else Path(tempfile.mkdtemp(prefix='shared-board.', dir='/tmp'))
RUNNER_PID = 'runner.pid'  # in the run's folder: tells a later run whether this one is still alive
if not options.watch:
    (ROOT / RUNNER_PID).write_text(str(os.getpid()))
ROLES = {'lead': 1, 'solo': 2, 'agent': 3, 'none': 4, 'autopilot': 5}  # 'none' registers no role


def session(side: str, role: str) -> str:
    return f'c0000000-0000-4000-8000-00000000{ord(side[0]):02x}{ROLES[role]:02x}'  # each clone its own: another machine's sessions are unknown here


failures: list[str] = []
retries = collections.Counter()


def base_env(side: str, window: float | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CODEX_', 'CLAUDE_CODE_SESSION')) and k not in ('BEADS_ACTOR', 'BD_ACTOR')}
    env.update(AGENT_SESSION_STATE_DIR=str(ROOT / f'state-{side}'), AGENT_BOARD_SYNC_SECONDS=str(options.seconds if window is None else window),
               GIT_CONFIG_GLOBAL=str(ROOT / 'gitconfig'))
    return env


def raw(side: str, *args: str, timeout: float = 200, window: float | None = None):
    """bd without --readonly, through `board bd --raw --yes`: setup and maintenance no board verb offers (an explicit id, dolt, sync, sql, delete)."""
    result = subprocess.run([sys.executable, '-B', BOARD, 'bd', '--raw', '--yes', *args], cwd=ROOT / side, capture_output=True, text=True, timeout=timeout,
                            env={**base_env(side, window), 'BD_NO_REMOTE_ADOPT': '1'}, input='')
    return result.returncode, result.stdout, result.stderr, 0.0


def run(side: str, *args: str, role: str | None = 'lead', stdin: str | None = None, timeout: float = 200, window: float | None = None):
    """One board call with exactly these arguments, as the session of `role` (None: a person's terminal, no session);
    `window` replaces the sync window the call (and the wait it starts) runs with."""
    env = base_env(side, window)
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
    _, out, _, _ = run(side, 'bd', '--raw', '--yes', 'export')
    return {row['id']: row for row in map(json.loads, filter(str.strip, out.splitlines())) if row.get('_type', 'issue') == 'issue'}


def create(side: str, title: str, *flags: str, role: str | None = 'lead', kind: str = 'change-request', window: float | None = None) -> str:
    """The fixture creator: a valid board create with the defaults the scenarios do not state (description 'x', a work task filed without a
    commit unless it has a parent, a question holding nothing). A scenario about the arguments themselves calls `run(side, 'create', ...)`."""
    if kind in ('bug', 'design', 'spike', 'feature', 'cleanup'):  # a kind is a label on a task: no rule reads it
        flags, kind = (*flags, '--label', f'kind:{kind}'), 'task'
    if '--status' in flags or kind == 'epic':  # a state no verb writes (create sets no status), and the epic scope root autopilot's --root reads
        queue = [] if '--parent' in flags else ['--labels', 'queue:' + git('config', 'agents.person', cwd=ROOT / side).strip()]  # what board create gives a top-level item
        rc, out, err, _ = raw(side, 'create', title, '--type', kind, '--description', 'x', '--silent', *queue, *flags)
        if rc:
            raise RuntimeError(f'create {title}: {err}{out}')
        return out.strip().splitlines()[-1]
    holds = ['--holds', 'none'] if kind == 'decision' else []
    filed = ['--no-commit'] if kind == 'task' and not {'--parent', '--no-commit'} & {arg.split('=')[0] for arg in flags} else []
    rc, out, err, _ = run(side, 'create', title, '-t', kind, *flags, *holds, '--description-file', '-', *filed, stdin='x', role=role, window=window)
    if rc:
        raise RuntimeError(f'create {title}: {err}{out}')
    return out.strip().splitlines()[-1]


def settle(*sides: str) -> None:
    """Every clone holds every other's writes: manual syncs, the same a person would run. Each sync pushes what its clone
    holds by then, so one pass forward and one back over all but the last reach everyone (a, b, a)."""
    for side in (*sides, *sides[-2::-1]):
        run(side, 'bd', '--raw', '--yes', 'sync')


def commits(side: str) -> int:
    _, out, _, _ = run(side, 'bd', 'sql', '--json', 'select count(*) c from dolt_log')
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
    rc, out, err, _ = raw('a', 'init', '--server', '--stealth', '--prefix', 'sb', '--skip-hooks', '--skip-agents')
    if rc:
        raise RuntimeError(f'init: {err}{out}')
    for key, value in (('status.custom', 'decided:wip,in_force:active,in_review:wip,passed:wip'), ('types.custom', 'change-request')):
        raw('a', 'config', 'set', key, value)
    for key, value in (('custom.board.target', git('symbolic-ref', '--short', 'HEAD', cwd=ROOT / 'a').strip()), ('custom.board.setup', 'true'), ('custom.board.checks', 'true'), ('custom.board.look', 'before'), ('custom.board.view', 'code'), ('custom.board.model', '1')):
        raw('a', 'config', 'set', key, value)
    raw('a', 'dolt', 'commit', '-m', 'config')


def beads_files(side: str) -> list[str]:
    """What of a board sits in a clone's folder: a failed join leaves none of it."""
    return sorted(path.name for path in (ROOT / side).iterdir() if path.name.startswith('.beads'))


def servers(side: str) -> list[str]:
    out = subprocess.run(['pgrep', '-f', f'{ROOT.name}/{side}/.beads/'], capture_output=True, text=True).stdout
    return out.split()


def remotes(side: str) -> str:
    out = run(side, 'bd', 'dolt', 'remote', 'list', role=None)[1].strip()
    return '' if out.startswith('No remotes') else out


def mark(side: str) -> dict:
    try:
        return json.loads((ROOT / side / '.beads' / 'board-shared.json').read_text())
    except OSError:
        return {}


CLOSED: list[str] = []


def t_unshared() -> None:
    parent = create('a', 'unshared parent')
    child = create('a', 'unshared child', '--parent', parent, kind='task')
    check('.' not in child, 'unshared board: a child has a plain id', child)
    CLOSED.append(create('a', 'closed top-level'))
    run('a', 'close', CLOSED[0], '--reason', 'closed before the share, which labels it too', '--force')
    rc, out, err, took = run('a', 'health')
    check(rc == 0 and not (ROOT / 'a/.beads/board-sync').exists(), 'unshared board: no sync state, no queue filter', err)
    check('other queues' not in out and 'set your person' not in err, 'unshared board: output as before', err)
    rc, _, err, _ = run('a', 'health', '--queue', 'ben')
    check(rc == 1 and 'not shared' in err, 'unshared board: --queue says there are no queues', err)
    rc, _, err, _ = raw('a', 'dolt', 'remote', 'add', 'origin', f'git+file://{ROOT}/remote.git', '--allow-git-origin')
    check(rc == 0, 'a hand-added remote is added (board no longer comments on it)', err)
    rc, out, err, _ = run('a', 'health')
    check(rc == 0 and 'other queues' not in out and not (ROOT / 'a/.beads/board-sync').exists(), 'only board\'s mark shares: a remote alone does not', err)
    raw('a', 'dolt', 'remote', 'remove', 'origin')
    # Field size guard (r13-q74) through real bd: stdin is judged and still reaches bd.
    long = 'x' * 2001
    rc, _, err, _ = run('a', 'create', 'long', '-t', 'task', '--description-file', '-', '--no-commit', stdin=long)
    check(rc == 2 and 'description is 2001 characters' in err, 'a work item over 2000 characters is refused', err)
    rc, out, err, _ = run('a', 'create', 'long stdin', '-t', 'task', '--description-file', '-', '--no-commit', stdin=long)
    check(rc == 2 and 'description is 2001 characters' in err and not out.strip(), 'the same through stdin', err)
    rc, out, err, _ = run('a', 'create', 'short stdin', '-t', 'task', '--parent', parent, '--description-file', '-', stdin='short text')
    made = out.strip().splitlines()[-1] if rc == 0 and out.strip() else ''
    check(made != '' and items('a').get(made, {}).get('description') == 'short text', 'a short description through stdin reaches bd', err or out)
    rc, out, err, _ = run('a', 'create', 'record', '-t', 'decision', '--holds', 'none', '--description-file', '-', stdin=long)  # a decision has no parent (nixes-7oqkc)
    check(rc == 0, 'a decision is not limited', err)
    run('a', 'bd', '--raw', '--yes', 'dolt', 'commit', '-m', 'unshared items')


def t_share_join() -> None:
    before = commits('a')
    rc, out, err, _ = run('a', 'share', f'git+file://{ROOT}/empty.git', '--yes', role=None)
    check(rc == 1 and 'empty repository' in err and not remotes('a'), 'share: a completely empty repository is refused before any change', err + out)
    rc, out, err, _ = run('a', 'share', role=None)
    check(rc == 1 and 'git emails' in out and 'remote.git' in out and '--yes' in out, 'share without --yes: says what goes out and where, then stops', err + out)
    check(not remotes('a') and commits('a') == before and not mark('a') and 'auto-commit: batch' not in (ROOT / 'a/.beads/config.yaml').read_text(),
          'share without --yes: no remote, no config, no commit, no mark', remotes('a'))
    env = {**base_env('a'), 'CLAUDE_CODE_SESSION_ID': 'garbage'}  # a session whose actor cannot be derived: its label write is refused, so share refuses before its push
    refused = subprocess.run([sys.executable, '-B', BOARD, 'share', '--yes'], cwd=ROOT / 'a', capture_output=True, text=True, env=env, input='')
    check(refused.returncode == 1 and 'cannot be derived' in refused.stderr and not remotes('a') and commits('a') == before and not mark('a'),
          'share: a refused label write refuses before any push, remote or mark', refused.stderr)
    held = next(i for i, issue in items('a').items() if issue.get('title') == 'unshared parent')
    run('a', 'claim', held, role='solo')
    rc, out, err, _ = run('a', 'share', '--yes', role='lead')  # another live session holds a top-level record: share's first label passes the hold rule (nixes-3se1p)
    check(rc == 0 and 'queue:anna' in items('a')[held].get('labels', []) and '3 top-level' in out, "share: another session's held top-level record is labelled", err + out)
    run('a', 'unclaim', held, '--resume', 'held across the share', role='solo')
    rc, out, err, _ = run('a', 'share', '--yes', role=None)
    check(rc == 0 and mark('a').get('remote') == 'origin', 'share --yes: default remote is the project repository, marked shared after the push', err + out)
    check('queue:anna' in items('a')[held].get('labels', []) and '0 top-level' in out, 'share: existing top-level unlabelled items go to the sharer (the parent, the closed item and the decision record, which has no parent: 3, in the lead\'s share above)', out)
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
    _, out, _, _ = run('b', 'bd', '--raw', '--yes', 'config', 'get', 'status.custom')
    check('in_review' in out, 'join: the custom statuses travel', out)
    _, out, _, _ = run('b', 'bd', '--raw', '--yes', 'config', 'get', 'min_hash_length')
    check('5' in out, 'join: min_hash_length travels', out)
    rc, out, err, _ = run('b', 'share', role=None)
    check(rc == 0 and '0 top-level' in out, "a second person's share takes nothing", err + out)
    git('clone', '-q', 'remote.git', 'unset')
    rc, out, err, _ = run('unset', 'join', role=None)
    check(rc == 1 and 'agents.person' in err and not (ROOT / 'unset/.beads').exists(), 'join with no person at no terminal: says how to set it, changes nothing', err)
    rc, out, err, _ = run('a', 'setup', role=None)
    check(rc == 0 and 'up to date' in out and ' -> ' not in out, 'setup on a shared board: share applied the same lists, the shared ones included', err + out)


def t_child_ids() -> None:
    epic = create('a', 'ids epic', '--label', 'topic:x')
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
    made = [create('a', 'a child', '--parent', epic, kind='task'), create('b', 'b child', f'--parent={epic}', kind='task')]
    check(all('.' not in item for item in made), 'child ids: --parent on both sides makes plain ids', made)
    settle('a', 'b')
    rows = items('a')
    check(all(i in rows for i in made), 'child ids: both sides under one parent sync', made)
    child = rows[made[0]]
    check('topic:x' in child.get('labels', []) and not any(label.startswith('queue:') for label in child.get('labels', [])),
          'child ids: other labels copied, the queue label not', child.get('labels'))
    check(any(dep['type'] == 'parent-child' and dep['depends_on_id'] == epic for dep in child.get('dependencies', [])), 'child ids: linked to the parent')
    _, out2, _, _ = run('a', 'bd', 'sql', '--json', f'select count(*) c from child_counters where parent_id = "{epic}"')
    check(json.loads(out2)[0]['c'] == 0, 'child ids: child_counters untouched', out2)
    rc, out, err, _ = run('a', 'bd', 'q', 'quick child', '--parent', epic)
    check(rc != 0 and 'board create' in err and not out.strip(), 'q is refused read-only, naming board create', out + err)
    tracked = create('a', 'tracked')
    both = create('a', 'two link kinds', '--deps', f'relates-to:{tracked}', '--parent', epic, kind='task')
    kinds = {(dep['type'], dep['depends_on_id']) for dep in items('a')[both].get('dependencies', [])}
    check(kinds == {('relates-to', tracked), ('parent-child', epic)}, "child ids: a node's dep and its parent link both land (real bd; a revision's tracks link and its parent do alike)", kinds)
    rc, out, err, _ = run('a', 'create', 'no such parent', '-t', 'task', '--parent', 'sb-nope', '--description-file', '-', stdin='x')
    check(rc != 0, 'child ids: an unknown parent fails', out)
    # Links (real bd): a blocking edge between two new work items is bd's own write; a pair with another link kind refuses before record writes.
    plan = ROOT / 'links-plan.json'
    plan.write_text(json.dumps({'nodes': [{'key': 'one', 'title': 'first new task', 'type': 'task', 'description': 'x', 'no_commit': True},
                                          {'key': 'two', 'title': 'second new task', 'type': 'task', 'description': 'x', 'no_commit': True, 'waits_on': [{'on': 'one', 'for': 'the first task'}]}],
                                'edges': []}))
    rc, out, err, _ = run('a', 'create', '--graph', str(plan))
    made = dict(line.split() for line in out.splitlines() if len(line.split()) == 2)
    check(rc == 0 and not err.strip() and any(dep['type'] == 'blocks' and dep['depends_on_id'] == made.get('one') for dep in items('a').get(made.get('two'), {}).get('dependencies', [])),
          'links: a plan edge between two new work items is written by bd, no refusal', (rc, out, err))
    draft = ROOT / 'record.md'
    draft.write_text('## Question\nq\n## Alternatives Considered\na\n## Decision\nd\n## Rationale\nr\n## Rule owner\no\n')

    def decision(title: str) -> str:
        item = create('a', title, kind='decision')
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
    run('a', 'bd', '--raw', '--yes', 'sync')


def t_queues() -> None:
    epic = create('a', 'anna epic', kind='milestone')  # a change request is part of a milestone (nixes-s378b): parents route their parts
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
    rc, _, err, _ = run('a', 'bd', 'update', ben, '--claim', role='agent')
    check(rc != 0 and 'board claim' in err, 'bd update --claim is refused read-only, naming board claim', err)
    rc, out, _, _ = run('a', 'claim', role='agent')
    check(rc == 0 and ben not in out and 'claimed' in out, 'bare claim: mine only', out)
    run('a', 'unclaim', re.search(r'claimed (\S+)', out)[1], '--resume', 'claim it again', role='agent') if rc == 0 else None  # a CR claim prints its worktree first
    # A blocker in another queue, always listed.
    blocked = create('a', 'anna waits')
    run('a', 'wait', blocked, '--on', ben, '--for', 'test setup')
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
    rc, _, err, _ = raw('a', 'update', epic, '--remove-label', 'queue:anna', '--add-label', 'queue:ben')
    check(rc == 0, 'lead moves an epic', err)
    settle('a', 'b')
    _, out, _, _ = run('b', 'queue')
    check(child in out, 'a moved epic takes its children along', out)
    _, out, _, _ = run('a', 'queue')
    check(child not in out, 'a moved child leaves the old queue', out)
    raw('a', 'update', epic, '--remove-label', 'queue:ben', '--add-label', 'queue:anna')
    settle('a', 'b')
    # A closed parent's label still routes.
    closing = create('a', 'closed parent', kind='milestone')
    kid = create('a', 'kid of closed', '--parent', closing)
    settle('a', 'b')
    run('a', 'close', closing, '--reason', 'closed to test a closed parent still routes its child', '--force')
    settle('a', 'b')
    _, out, _, _ = run('a', 'queue')
    check(kid in out, "a closed parent's queue still routes its child", out)
    # Moves (parents and queues): a lead reparents, a person's terminal moves queue labels, a lead's worker is refused.
    item = create('a', 'to move')  # an item moves between change requests: the queue rule is about the parent it takes
    parent_b = create('b', 'ben parent')
    settle('a', 'b')
    moved = create('a', 'to reparent', '--parent', item, kind='task')
    worker = subprocess.run([sys.executable, '-B', BOARD, 'move', moved, '--to', parent_b], cwd=ROOT / 'a', capture_output=True, text=True,
                            env={**base_env('a'), 'BEADS_ACTOR': f"{session('a', 'lead')[-8:]}/worker01", 'CLAUDE_CODE_SESSION_ID': session('a', 'lead')})
    check(worker.returncode == 2 and 'only lead and solo' in worker.stderr, "a lead's worker is refused", worker.stderr)
    rc, _, err, _ = run('a', 'move', moved, '--to', parent_b)
    check(rc == 0, 'lead: reparent passes', err)
    added, removed = raw('a', 'label', 'add', item, 'queue:ben'), raw('a', 'label', 'remove', item, 'queue:anna')
    check(added[0] == 0 and removed[0] == 0, "a person's terminal moves queue labels", added[2] + removed[2])
    rows = items('a')
    check('queue:ben' in rows[item].get('labels', []) and 'queue:anna' not in rows[item].get('labels', []), 'moves took effect')
    settle('a', 'b')
    # Unset person.
    git('config', '--unset', 'agents.person', cwd=ROOT / 'a')
    rc, _, err, _ = run('a', 'health')
    check('agents.person' in err, 'person unset: every command says how to set it', err)
    rc, _, err, _ = run('a', 'claim', role='agent')
    check(rc == 1 and 'agents.person' in err, 'person unset: a bare claim says how', err)
    git('config', 'agents.person', 'anna', cwd=ROOT / 'a')


def close_window(side: str = 'a') -> float:
    """Ends an open send window now: stops its wait and starts the window again from this moment, with the length under test. Returns when it started."""
    unsent = ROOT / side / '.beads' / 'board-sync' / 'unsent'  # the wait marks the first unsent write: it opens the window
    wait_until(unsent.exists, 30)
    for pid in waits():
        os.kill(pid, signal.SIGKILL)
    wait_until(lambda: not waits(), 10)
    started = time.time()
    os.utime(unsent)
    run(side, 'health')  # a command restarts a dead wait
    return started


def t_window() -> None:
    settle('a', 'b')
    check(wait_until(lambda: not waits(), options.seconds * 3), 'no wait left running before the burst', waits())
    before = commits('a')
    # A burst is judged against an open window, so it runs under one no machine load can outlast (a window of options.seconds closes before six
    # bd calls return on a loaded machine); close_window then starts the window under test.
    open_window = 600
    rc, _, err, took = raw('a', 'create', 'burst first', '-t', 'task', '--description', 'x', '--silent', window=open_window)
    check(took < open_window / 2, f'a write returns at once with the wait detached ({took:.1f} s)', took)  # an attached wait would hold the call for the whole window
    made = [raw('a', 'create', f'burst {n}', '-t', 'task', '--description', 'x', '--silent', window=open_window)[1].strip() for n in range(5)]  # board create commits per call; the window is about bd's own writes
    check(len(waits()) == 1, 'one wait for the board', waits())
    check(commits('a') == before, 'writes stay uncommitted during the window')
    started = close_window()
    if not wait_until(lambda: commits('a') > before and not waits(), options.seconds * 4):
        check(False, 'the wait synced and ended', commits('a'))
    elapsed = time.time() - started
    check(elapsed >= options.seconds - 1, f'sync waited for the window ({elapsed:.1f} s of {options.seconds} s)')
    check(commits('a') - before <= 2 and commits('a') - before >= 1, 'a burst goes out as one commit (a merge may add one)', commits('a') - before)
    run('b', 'bd', '--raw', '--yes', 'dolt', 'pull')
    check(all(item in items('b') for item in made), 'the burst reached the other clone')
    # The product path: board create commits once per call (bd's create --graph ignores dolt.auto-commit=batch, accepted), so the count is not
    # pinned. What must hold: one wait for the burst, every item reaches the other clone, nothing is left unsent.
    settle('a', 'b')
    check(wait_until(lambda: not waits(), options.seconds * 3), 'no wait left running before the board create burst', waits())
    made = [create('a', f'board burst {n}', kind='task', window=open_window) for n in range(5)]
    check(len(waits()) == 1, 'one wait for a burst of board create calls', waits())
    close_window()
    check(wait_until(lambda: not waits(), options.seconds * 4), 'the wait ended after the board create burst')
    check(not (ROOT / 'a' / '.beads' / 'board-sync' / 'unsent').exists(), 'nothing left unsent after the board create burst')
    run('b', 'bd', '--raw', '--yes', 'dolt', 'pull')
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
    run('b', 'bd', '--raw', '--yes', 'sync')


def t_manual_and_dead_wait() -> None:
    settle('a', 'b')
    check(wait_until(lambda: not waits(), options.seconds * 3), 'idle')
    item = create('a', 'manual sync')
    rc, out, err, _ = run('a', 'bd', '--raw', '--yes', 'sync')
    check(rc == 0, 'a manual sync works, also mid-window', err + out)
    run('b', 'bd', '--raw', '--yes', 'dolt', 'pull')
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
    run('b', 'bd', '--raw', '--yes', 'dolt', 'pull')
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
            rc, out, err, _ = run(side, 'create', f'{side}{number}-{n}', '-t', 'task', '--description-file', '-', '--no-commit', stdin='v0')
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
    run('a', 'bd', '--raw', '--yes', 'delete', victim, '--force')
    run('a', 'bd', '--raw', '--yes', 'sync')
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
    rc, _, err, _ = run('b', 'create', 'refused', '-t', 'task', '--description-file', '-', '--no-commit', stdin='x')
    check(rc != 0 and 'Merge conflict detected' in err and 'retry' not in err, 'stopped sync: beads refuses writes, no retry', err)
    rc, out, err, _ = run('b', 'bd', '--raw', '--yes', 'conflicts', 'resolve', victim, '--theirs')
    if rc:
        rc, out, err, _ = run('b', 'bd', '--raw', '--yes', 'conflicts', 'resolve', '--all', '--table', 'issues', '--theirs')
    check(rc == 0, 'stopped sync: bd conflicts resolve clears it', err + out)
    _, _, err, _ = run('b', 'health')
    check('merge conflict' not in err, 'stopped sync: the line goes with the conflict', err)
    check(wait_until(lambda: not waits() and not sync_state('b').get('kind'), options.seconds * 4), 'stopped sync: the wait finishes the send', sync_state('b'))
    run('b', 'health')
    settle('a', 'b')
    check(items('a').keys() == items('b').keys(), 'after the conflict: same items')
    # An id collision.
    wait_until(lambda: not waits(), options.seconds * 3)
    raw('a', 'create', 'same a', '-t', 'task', '--description', 'x', '--id', 'sb-collide', '--silent')
    run('a', 'bd', '--raw', '--yes', 'sync')
    pulled_just_now('b')
    raw('b', 'create', 'same b', '-t', 'task', '--description', 'x', '--id', 'sb-collide', '--silent')
    check(wait_until(lambda: sync_state('b').get('kind') == 'conflict', options.seconds * 4), 'an id collision reports a conflict', sync_state('b'))
    rc, _, err, _ = run('b', 'position')
    check('CALL DOLT_MERGE' in err and 'board bd --raw --yes rename' in err, 'the line carries the collision fix', err)
    rc, out, err, _ = run('b', 'bd', '--raw', '--yes', 'sql', "CALL DOLT_MERGE('--abort')")
    check(rc == 0, 'collision fix: abort', err + out)
    rc, out, err, _ = run('b', 'bd', '--raw', '--yes', 'rename', 'sb-collide', 'sb-other')
    check(rc == 0, 'collision fix: rename', err + out)
    rc, out, err, _ = run('b', 'bd', '--raw', '--yes', 'sync')
    check(rc == 0, 'collision fix: sync', err + out)
    run('a', 'bd', '--raw', '--yes', 'sync')
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
    rc, _, err, _ = run('a', 'update', sorted(items('a'))[0], '--title', 'still working')
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
    raw('b', 'update', item, '--remove-label', 'queue:ben', '--add-label', 'queue:anna')
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
    raw('a', 'update', stray, '--remove-label', 'queue:anna')
    time.sleep(1.1)
    rc, out, err, _ = run('a', 'create', '--for', 'ben', 'found for ben', '-t', 'change-request', '--description-file', '-', stdin='x', role='agent')
    found = out.strip().splitlines()[-1] if rc == 0 else ''
    row = items('a').get(found, {})
    check(rc == 0 and {'for:ben', 'queue:anna'} <= set(row.get('labels', [])) and not row.get('assignee'),
          'create --for: in my queue, labelled for the other, held by nobody', err + out)
    rc, _, err, _ = run('a', 'create', '--for', 'ben', 'child find', '-t', 'change-request', '--parent', found, '--description-file', '-', stdin='x', role='agent')
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
    run('b', 'unclaim', found, '--resume', 'pass it on', role='agent')  # a held record is its holder's to send (nixes-7mt77)
    # route on a find drops for:.
    rc, out, _, _ = run('a', 'create', '--for', 'ben', 'second find', '-t', 'change-request', '--description-file', '-', stdin='x', role='agent')
    second = out.strip().splitlines()[-1]
    rc, _, err, _ = run('a', 'route', 'ben', second)
    rows = items('a')
    check(rc == 0 and not rows[second].get('assignee') and 'for:ben' not in rows[second]['labels'] and 'queue:ben' in rows[second]['labels'],
          "route on a find: drops for:", (err, rows[second]))
    parent = create('a', 'a parent')
    kid = create('a', 'a kid', '--parent', parent, kind='task')
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
    """One change request end to end on clone a's board, through real bd and real git: claim (worktree, branch, recorded
    base), a worker's item closed with its pass commit, hand-over (checks, stored pair), another session's review, and the Accept that
    lands it. The rules on each step are the fake-bd suite's (test-agent-configs.py test_board crs parts)."""
    side = ROOT / 'a'
    target = git('symbolic-ref', '--short', 'HEAD', cwd=side).strip()
    worktree = side / '.worktrees'

    def meta_of(cr: str) -> dict:
        return items('a')[cr].get('metadata') or {}

    cr = create('a', 'change request A')
    item = run('a', 'create', 'A item', '-t', 'task', '--parent', cr, '--description-file', '-', stdin='x')[1].strip().splitlines()[-1]
    main_tip = git('rev-parse', target, cwd=side).strip()
    rc, out, err, _ = run('a', 'claim', cr, role='agent')
    check(rc == 0 and (worktree / cr).is_dir() and git('branch', '--list', f'cr/{cr}', cwd=side).strip()
          and meta_of(cr).get('base') == target and meta_of(cr).get('base_sha') == main_tip,
          'cr: a claim creates the worktree and branch and records the base', err + out + str(meta_of(cr)))
    (worktree / cr / 'a.txt').write_text('a\n')
    git('add', 'a.txt', cwd=worktree / cr)
    git('commit', '-q', '-m', f'{item}: a.txt', cwd=worktree / cr)
    sha = git('rev-parse', '--short', 'HEAD', cwd=worktree / cr).strip()
    rc, out, err, _ = run('a', 'close', item, '--reason', f'{sha}: a.txt written in the pass commit', role='agent')
    check(rc == 0, 'cr: the item closes with its pass commit', err + out)
    tip = git('rev-parse', 'HEAD', cwd=worktree / cr).strip()
    rc, out, err, _ = run('a', 'handover', cr, 'tests: exit 0', role='agent')
    check(rc == 0 and items('a')[cr]['status'] == 'in_review' and meta_of(cr).get('check_result') == 'pass' and meta_of(cr).get('check_tip') == tip,
          'cr: hand-over runs the checks and stores the pair', err + out + str(meta_of(cr)))
    rc, out, err, _ = run('a', 'claim', cr, role='solo')
    check(rc == 0, 'cr: another session claims the review', err + out)
    rc, out, err, _ = run('a', 'handover', cr, 'reviewed: fine', role='solo')
    check(rc == 0 and items('a')[cr]['status'] == 'passed', 'cr: the review passes it to the Accept (look before)', err + out)
    rc, out, err, _ = run('a', 'cr', 'land', cr, '--tip', tip, '--base', main_tip)
    check(rc == 0 and items('a')[cr]['status'] == 'closed' and git('rev-parse', target, cwd=side).strip() == tip
          and not (worktree / cr).exists() and not git('branch', '--list', f'cr/{cr}', cwd=side).strip(),
          'cr: the Accept lands it and removes its worktree and branch', err + out)


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
    check(rc == 1 and 'empty' in err and 'not set' in run('a', 'bd', '--raw', '--yes', 'config', 'get', 'custom.board.moved')[1], 'move: an empty repository is refused before the note', err)
    before = commits('a')
    rc, out, err, _ = run('a', 'relocate', fresh)
    check(rc == 0 and commits('a') < before, 'move: flattened and pushed', err + out)
    check('refs/dolt/data' in git('for-each-ref', cwd=ROOT / 'remote.git') and 'refs/dolt/data' in git('for-each-ref', cwd=ROOT / 'fresh.git'),
          'move: the old data stays, the new repository holds the board')
    check('not set' in run('a', 'bd', '--raw', '--yes', 'config', 'get', 'custom.board.moved')[1] and 'fresh.git' in remotes('a') and 'remote.git' not in remotes('a'),
          "move: the mover's board carries no note and syncs with the new repository", remotes('a'))
    rc, _, err, _ = run('a', 'health')
    check(rc == 0 and 'moved' not in err, 'move: the mover works on', err)
    # A write between pulls lands on the old board; the stale clone learns at its next sync, and refuses writes.
    (ROOT / 'b/.beads/board-sync/pulled').touch()
    stale = create('b', 'written before b knows')
    check(wait_until(lambda: sync_state('b').get('moved') == fresh, options.seconds * 5), 'a stale clone learns of the move at its next sync', sync_state('b'))
    rc, _, err, _ = run('b', 'create', 'refused after the move', '-t', 'task', '--description-file', '-', '--no-commit', stdin='x')
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
    rc, _, err, _ = run('b', 'bd', '--raw', '--yes', 'import', found.group(1) if found else 'missing')
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
            'status.custom': 'decided:wip,in_force:active,in_review:wip,passed:wip', 'types.custom': 'change-request', 'min_hash_length': '5', 'custom.board.model': '1'}


def setting(side: str, key: str) -> str:
    return json.loads(raw(side, 'config', 'get', '--json', key)[1] or '{}').get('value', '')


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
    raw('setupproj', 'config', 'set', 'validation.on-close', 'warn')
    raw('setupproj', 'config', 'unset', 'types.custom')
    raw('setupproj', 'dolt', 'commit', '-m', 'drift')
    rc, out, err, _ = run('setupproj', 'setup', role=None)
    check(rc == 0 and 'validation.on-close: warn -> error' in out and 'types.custom: (unset) -> change-request' in out,
          'setup on an existing board: sets the missing setting, resets the differing one, printing old and new', err + out)
    check(setting('setupproj', 'validation.on-close') == 'error' and setting('setupproj', 'types.custom') == 'change-request', 'setup: the values are applied')
    check('already has a board' in out, 'setup: an existing board is never re-created', out)
    rc, out, err, _ = run('setupproj', 'setup', role=None)
    check(rc == 0 and ' -> ' not in out and 'up to date' in out, 'setup again: nothing to do', err + out)
    raw('setupproj', 'config', 'unset', 'custom.board.model')
    raw('setupproj', 'dolt', 'commit', '-m', 'an older board')
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
    made = [run('setupproj', 'create', title, '--description-file', '-', '--no-commit', stdin=f'{title}, an item the conversion keeps', role=None)[1].strip()
            for title in ('first kept', 'second kept')]
    rc, out, err, _ = run('setupproj', 'setup', '--server', role=None)
    meta = json.loads((ROOT / 'setupproj/.beads/metadata.json').read_text()) if (ROOT / 'setupproj/.beads/metadata.json').is_file() else {}
    kept = sorted((ROOT / 'setupproj').glob('.beads.before-server-*'))
    rc_list, listed, _, _ = run('setupproj', 'bd', 'list', '--all', '--json', role=None)
    present = {item['id'] for item in json.loads(listed or '[]')} if rc_list == 0 else set()
    check(rc == 0 and meta.get('dolt_mode') == 'server' and meta.get('dolt_database') == 'setupproj' and set(made) <= present and len(kept) == 1,
          'setup --server on an embedded board: converts it in place, every item kept, the old folder beside it', (err + out, meta, made, present, kept))
    check(setting('setupproj', 'dolt.auto-start') == 'false' and setting('setupproj', 'validation.on-close') == 'error',
          'setup --server: the converted board has the server settings and the rest', (setting('setupproj', 'dolt.auto-start'), err + out))
    status = raw('setupproj', 'backup', 'status')[1]
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


MIGRATE_SCRIPT = HERE.parent / 'skills' / 'board-migrate' / 'scripts' / 'convert-stored-forms.py'


def old_form_board(side: str) -> dict[str, str]:
    """A board holding every stored form of the earlier model: fixtures/migrate-old-forms.jsonl, a `bd export` of one built through the
    earlier commands (the forms are history, so the export stays as it is), imported under the earlier status list, plus the worktree each
    of its change requests had. Returns the record ids by name (mg-<name>)."""
    git('init', '-q', '-b', 'main', side)
    git('commit', '-q', '--allow-empty', '-m', 'init', cwd=ROOT / side)
    rc, out, err, _ = run(side, 'setup', '--prefix', 'mg', '--target', 'main', '--setup', 'true', '--checks', 'true', '--look', 'before', '--view', 'code', role=None)
    check(rc == 0, f'{side}: the board is set up', err + out)
    raw(side, 'config', 'set', 'status.custom', 'decided:wip,released:active,in_review:wip,needs_ratification:wip,needs_acceptance:wip,in_force:active,passed:wip')
    raw(side, 'config', 'set', 'types.custom', 'design,change-request')  # the earlier model registered the design type; `setup` below puts the current list back
    rc, out, err, _ = raw(side, 'import', str(HERE / 'fixtures' / 'migrate-old-forms.jsonl'))
    if rc:
        raise RuntimeError(f'import the old forms: {err}{out}')
    ids = {name.removeprefix('mg-').replace('-', '_'): name for name in items(side)}
    for name in ('cr2', 'cr3', 'cr4', 'cr5', 'cr6', 'ck1', 'ck2'):
        git('worktree', 'add', '-q', f'.worktrees/{ids[name]}', '-b', f'cr/{ids[name]}', cwd=ROOT / side)
    run(side, 'setup', role=None)  # status.custom to the current list; the records keep their old statuses
    raw(side, 'config', 'unset', 'custom.board.model')
    raw(side, 'dolt', 'commit', '-m', 'old forms')
    return ids


def t_rehearse() -> None:
    """board-migrate --rehearse on a board holding every old form: the whole conversion on a copy in a temporary board, nothing written here."""
    side = 'rehproj'
    ids = old_form_board(side)
    scratch = ROOT / 'rehearsals'  # the rehearsal's TMPDIR: its folder and its server's command line sit under this run's own root, so another session's never match
    scratch.mkdir()

    def leftovers() -> list[str]:
        """What a rehearsal of this run leaves: its folder, or a process running in it (its dolt server)."""
        running = subprocess.run(['pgrep', '-f', str(scratch)], capture_output=True, text=True).stdout.split()
        return [str(p) for p in scratch.glob('board-rehearsal-*')] + running

    def migrate(*flags: str):
        result = subprocess.run([sys.executable, '-B', str(MIGRATE_SCRIPT), *flags], cwd=ROOT / side, capture_output=True, text=True, env={**base_env(side), 'TMPDIR': str(scratch)}, input='')
        return result.returncode, result.stdout, result.stderr

    before = items(side)
    rc, out, err = migrate('--rehearse')
    check(rc == 0 and 'rehearsal on a copy' in out and out.index('--- summary') < out.index('--- conversion (exit 0)') and 'conversion(s) applied' in out and 'mark: blocked' in out
          and f"{ids['ratify']}" in out.split('--- conversion')[0] and items(side) == before and not leftovers(),
          'migrate: --rehearse converts a copy in a temporary board, shows the open ratification that blocks its mark, and writes nothing here', (leftovers(), items(side) == before, err + out[-300:]))


def t_migrate() -> None:
    """board-migrate's conversion on a board holding every old form: refused writes and open reads before, a dry run that writes nothing,
    the conversions, a rerun that finds nothing, `check` clean, and the marker last."""
    side = 'migproj'
    ids = old_form_board(side)

    def migrate(*flags: str):
        result = subprocess.run([sys.executable, '-B', str(MIGRATE_SCRIPT), *flags], cwd=ROOT / side, capture_output=True, text=True, env=base_env(side), input='')
        return result.returncode, result.stdout, result.stderr

    rc, out, err, _ = run(side, 'update', ids['bug'], '--title', 'a bug item, retitled', role=None)
    check(rc != 0 and '/board-migrate' in err, 'migrate: a write verb on the old board is refused, naming /board-migrate', err + out)
    rc, out, err, _ = run(side, 'show', ids['bug'])
    check(rc == 0 and 'a bug item' in out and 'retitled' not in out, 'migrate: reads work on the old board', err + out)
    before = items(side)
    rc, out, err = migrate()
    check(rc == 0 and out.count('would: ') >= 20 and items(side) == before, 'migrate: the dry run lists the conversions and writes nothing', err + out)
    rc, out, err = migrate('--mark')
    check(rc == 1 and setting(side, 'custom.board.model') == '', 'migrate: the marker waits for the conversions', err + out)
    rc, out, err = migrate('--apply')
    first_apply = out
    check(rc == 0 and 'conversion(s) applied' in out and 'no recorded author' in out and 'timer gate' in out and f"{ids['ratify']}: an open landing ratification" in out, 'migrate: --apply converts and lists what is left for the user', err + out)
    nocode_line = f"{ids['nocode']}: a no-commit task inside change request {ids['cr1']}"
    check(nocode_line in first_apply and 'no_commit' not in (items(side)[ids['nocode']].get('metadata') or {}), 'migrate: a no-code task inside a change request is listed to settle, never no_commit', first_apply)
    rc, out, err = migrate('--apply')
    check(nocode_line in out, 'migrate: the no-code member is listed again until it is settled', out)
    check(raw(side, 'update', ids['nocode'], '--unset-metadata', 'no_code')[0] == 0, 'migrate: the agent settles the no-code member (drops the mark)')
    rc, out, err = migrate('--apply')
    check(rc == 0 and out.startswith('0 conversion(s) applied') and all(ids[name] in next((l for l in out.splitlines() if 'in-force ruling(s)' in l), '') for name in ('ruling_wait', 'ruling_cr')), 'migrate: a rerun finds nothing to convert and lists the rulings to plan again, a wait on a change request included', err + out)

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
    own = next((target for target, kind in deps('def_item') if kind == 'parent-child'), None)
    check(own and own != ids['cr1'] and now[own]['issue_type'] == 'change-request' and now[own]['status'] == 'deferred' and row('def_item')['status'] == 'open'
          and (ids['cr1'], 'relates-to') in {(d['depends_on_id'], d['type']) for d in now[own].get('dependencies') or []} and 'found_in' not in meta_of('def_item')
          and [i['id'] for i in now.values() if (own, 'parent-child') in {(d['depends_on_id'], d['type']) for d in i.get('dependencies') or []}] == [ids['def_item']],
          'migrate: a deferred item of a live change request leaves it as the only item of a deferred change request of its own, related to the old one', (own, row('def_item')['status'], meta_of('def_item'), deps('def_item')))
    check((ids['resumed_cr'], 'parent-child') in deps('def_resumed') and row('def_resumed')['status'] == 'open' and row('resumed_cr')['status'] == 'deferred'
          and not any((ids['stray_cr'], 'parent-child') in {(d['depends_on_id'], d['type']) for d in i.get('dependencies') or []} for i in now.values()) and row('stray_cr')['status'] == 'deferred',
          'migrate: a rerun after an interruption reuses the childless deferred change request related to the old one, and leaves an unrelated one alone', (deps('def_resumed'), row('stray_cr')['status']))
    check(row('def_under')['status'] == 'open' and (ids['cr7'], 'parent-child') in deps('def_under') and row('cr7')['status'] == 'deferred',
          'migrate: an item of a deferred change request is open, the deferral of its change request holds it', (row('def_under')['status'], deps('def_under')))
    check(row('cond_loose')['status'] == 'open' and (ids['target'], 'blocks') in deps('cond_loose') and any(kind == 'parent-child' for _, kind in deps('cond_loose')),
          'migrate: a work item reopened by its deferral condition is filed in the same apply', (row('cond_loose')['status'], deps('cond_loose')))
    filed = [now[target] for target, kind in deps('loose') if kind == 'parent-child']
    check(len(filed) == 1 and filed[0]['issue_type'] == 'change-request' and not filed[0].get('external_ref') and (filed[0].get('metadata') or {}).get('plan_first') and 'topic:loose' in filed[0].get('labels', [])
          and not any(kind == 'parent-child' for _, kind in deps('spike')) and row('loose_def')['status'] == 'deferred' and not any(kind == 'parent-child' for _, kind in deps('loose_def')),
          'migrate: a work item outside any change request becomes the only item of one, marked plan_first and carrying no marker of the migration; a no-commit task and a deferred one stay tasks', (filed, deps('loose')))
    check(meta_of('replanned').get('plan_first') == 'the ruling changed it' and 'replan' not in meta_of('replanned'), 'migrate: the earlier replan mark becomes plan_first with its reason', meta_of('replanned'))
    check('outcome' not in meta_of('reopened'), 'migrate: an open record carries no outcome', meta_of('reopened'))
    check((ids['target'], 'blocks') in deps('waits') and (ids['target'], 'blocks') in deps('cond') and not {'waits-for', 'conditional-blocks'} & {kind for _, kind in deps('waits') | deps('cond')},
          'migrate: waits-for and conditional-blocks become waits', (deps('waits'), deps('cond')))
    check(meta_of('found').get('found_in') == ids['target'] and not any(kind == 'discovered-from' for _, kind in deps('found')), 'migrate: discovered-from becomes found_in', (meta_of('found'), deps('found')))
    check((ids['target'], 'relates-to') in deps('related') and (ids['target'], 'relates-to') in deps('dup'), 'migrate: related and duplicates become relates-to', (deps('related'), deps('dup')))
    check((ids['milestone'], 'parent-child') in deps('cr4') and not deps('milestone') and row('cr4')['status'] == 'passed',
          'migrate: a milestone waiting on a change request holds it as a part; needs_acceptance is passed', (deps('cr4'), deps('milestone')))
    check(row('cr5')['status'] == 'passed' and meta_of('cr5').get('look') == 'before' and 'look' not in meta_of('cr4'),
          'migrate: a change request that awaited acceptance waits for it as passed, whatever look it carried', (meta_of('cr4'), meta_of('cr5')))
    check(row('cr6')['status'] == 'open' and row('cr6')['assignee'] == 'abcd1234' and meta_of('cr6').get('hold') == 'work',
          'migrate: an in-progress change request stays held, its hold is work', (row('cr6')['status'], row('cr6').get('assignee'), meta_of('cr6')))
    check((ids['target'], 'blocks') not in deps('ruling_wait') and (ids['target'], 'relates-to') in deps('ruling_wait') and (ids['plan_question'], 'blocks') in deps('ruling_wait')
          and all(ids[name] in next((l for l in first_apply.splitlines() if 'in-force ruling(s)' in l), '') for name in ('ruling_wait', 'ruling_cr')),
          'migrate: an in-force ruling keeps its wait on work as a relates-to link and is listed for planning, its wait on a question stays', (deps('ruling_wait'), first_apply[-600:]))
    check(row('released')['status'] == 'in_force' and row('unratified')['status'] == 'in_force', 'migrate: released and an unratified ruling are in_force', (row('released')['status'], row('unratified')['status']))
    def confirmations(name: str) -> list[dict]:
        return [i for i in now.values() if i['issue_type'] == 'decision' and f"Confirm ruling {ids[name]} or revise it" in str(i.get('description')) and (ids[name], 'relates-to') in {(d['depends_on_id'], d['type']) for d in i.get('dependencies') or []}]

    confirm = confirmations('unratified')
    check(len(confirm) == 1 and confirm[0]['status'] == 'open' and (ids['unratified'], 'relates-to') in {(d['depends_on_id'], d['type']) for d in confirm[0].get('dependencies') or []}
          and 'Undo this by hand' in confirm[0]['description'], 'migrate: an unratified ruling stays in force with a question to confirm or revise it', confirm)
    names = ('old_ruling', 'planned', 'dropped', 'closed_gate', 'ms_closed', 'planned_carried', 'planned_lower', 'answered', 'dropped_word', 'unmapped')
    check([meta_of(name).get('outcome') for name in names] == ['superseded', 'planned', 'dropped', 'resolved', 'accepted', 'planned', 'planned', 'superseded', 'dropped', None],
          'migrate: closed decisions, gates and milestones get their outcome from what their close says; one that says nothing is left for the agent, not guessed', [meta_of(name).get('outcome') for name in names])
    check(row('user_held')['assignee'] == 'user' and f"{ids['user_held']}: an item of {ids['cr1']} is held by you" in first_apply and f"{ids['unmapped']}: a closed ruling" in first_apply,
          'migrate: a user-held item of a change request keeps its hold until the agent made its gate, and both it and an unmapped closed ruling are listed', first_apply[-900:])
    check(raw(side, 'update', ids['user_held'], '--assignee', '')[0] == 0, 'migrate: the agent makes the gate and clears the hold (the check flags a user holder)')
    check(migrate('--apply')[0] == 0, 'migrate: a rerun clears the hold mark that the cleared holder left')
    now = items(side)
    check(meta_of('dated').get('revisit') == '2027-03-04' and row('dated')['status'] == 'deferred' and not row('dated').get('defer_until'),
          'migrate: defer_until becomes the revisit field and leaves bd', (meta_of('dated'), row('dated').get('defer_until')))
    check(row('conditional')['status'] == 'open' and (ids['target'], 'blocks') in deps('conditional'), 'migrate: a deferral that already waits on an open record reopens, its wait kept', (row('conditional')['status'], deps('conditional')))
    check(all(row(name)['status'] == 'deferred' and not any(kind == 'blocks' for _, kind in deps(name)) and any(f"{ids[name]}:" in line for line in first_apply.splitlines())
              for name in ('cond_rel', 'cond_none')) and (ids['target'], 'relates-to') in deps('cond_rel'),
          'migrate: a condition-worded deferral with no wait stays deferred, gets no wait from its note, and is listed', [(row(n)['status'], deps(n)) for n in ('cond_rel', 'cond_none')])
    check(row('cond_mixed')['status'] == 'deferred' and {(ids['target'], 'blocks'), (ids['someday'], 'blocks')} <= deps('cond_mixed')
          and any(f"{ids['cond_mixed']}:" in line and ids['someday'] in line for line in first_apply.splitlines()),
          'migrate: a condition-worded deferral that also waits on a deferred record stays deferred, both waits kept, and is listed (N8)',
          (row('cond_mixed')['status'], deps('cond_mixed'), first_apply[-600:]))
    check(row('cond_q')['status'] == 'deferred' and {(ids['target'], 'blocks'), (ids['cond_qd'], 'blocks')} <= deps('cond_q')
          and any(f"{ids['cond_q']}:" in line and ids['cond_qd'] in line for line in first_apply.splitlines()),
          'migrate: a condition-worded deferral that also waits on a deferred question stays deferred, both waits kept, and is listed (undefer refuses it, P6)',
          (row('cond_q')['status'], deps('cond_q'), first_apply[-600:]))
    check((ids['rule_b'], 'blocks') in deps('rule_a') and (ids['rule_b'], 'relates-to') not in deps('rule_a'), 'migrate: an in-force ruling keeps its wait on an in-force ruling', deps('rule_a'))
    gates = [i for i in now.values() if i['issue_type'] == 'gate' and i['status'] == 'open' and i.get('await_type') == 'human']
    gates = [g for g in gates if any((g['id'], 'supersedes') in {(d['depends_on_id'], d['type']) for d in i.get('dependencies') or []} for i in now.values() if i['status'] == 'closed')]  # the old record is superseded by the gate
    check(len(gates) == 3 and all(any((g['id'], 'supersedes') in deps(name) for g in gates) for name in ('user_gate', 'user_item', 'user_item2'))
          and any((g['id'], 'blocks') in deps('waiter') for g in gates) and row('user_gate')['status'] == 'closed' and row('user_item')['status'] == 'closed',
          'migrate: a gate and a user item become human gates that supersede them, the waiter moved to the new gate', (gates, deps('waiter')))
    check(row('dated_live')['status'] == 'open' and 'revisit' not in meta_of('dated_live'), 'migrate: a live record with a stale defer_until is not parked by it', (row('dated_live')['status'], meta_of('dated_live')))
    confirm2 = confirmations('unratified2')
    check(len(confirm2) == 1 and confirm2[0]['id'] == ids['confirm_q'] and not any(i.get('external_ref') for i in confirm + confirm2),
          'migrate: a confirm question an earlier stop made is found by its link and text, not made again, and no question carries a marker', confirm2)
    check(row('user_item2')['status'] == 'closed' and any(i.get('title') == 'check the logs' and i['status'] == 'open' for i in now.values())
          and any(i.get('title') == 'Existing human gate' and i['status'] == 'open' for i in now.values()),
          'migrate: a user item that waits on an existing human gate gets a gate of its own, the existing one stays', [(i.get('title'), i['status']) for i in now.values() if i['issue_type'] == 'gate'])
    check(row('ratify')['status'] == 'needs_ratification' and not [i for i in now.values() if str(i.get('external_ref') or '').startswith('migrated')],
          'migrate: an open ratification is listed, not converted, and no interim question is written', row('ratify'))
    rc, _, err, _ = raw(side, 'close', ids['ratify'], '--reason', 'the agent resolved the ratification with the user before the mark')  # the agent's resolution, a raw write: the board refuses its verbs until the marker
    check(rc == 0, 'migrate: the agent resolves the listed ratification', err)
    now = items(side)
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
    timer = next(i['id'] for i in items(side).values() if i['issue_type'] == 'gate' and i.get('await_type') == 'timer' and i['status'] != 'closed')
    check(rc == 1 and setting(side, 'custom.board.model') == '' and all(one in err for one in (ids['unmapped'], timer)),
          'migrate: --mark refuses while forms listed for the agent remain, naming them', err + out)
    for one, flags in ((ids['unmapped'], ('--set-metadata', 'outcome=dropped')),):  # the agent's resolutions, raw writes
        check(raw(side, 'update', one, *flags)[0] == 0, f'migrate: the agent settles {one}')
    check(raw(side, 'close', timer, '--force', '--reason', 'the agent resolved the timer gate with the user')[0] == 0, 'migrate: the agent resolves the timer gate')
    check(migrate('--apply')[0] == 0, 'migrate: a rerun writes the outcome of the gate the agent closed')
    rc, out, err = migrate('--mark')
    check(rc == 0 and setting(side, 'custom.board.model') == '1', 'migrate: --mark writes the marker last', err + out)
    rc, out, err, _ = run(side, 'update', ids['bug'], '--title', 'a bug item, retitled', role=None)
    check(rc == 0, 'migrate: a write verb works once the marker is set', err + out)


def cleanup() -> None:
    """Ends this run's sync waits and every process with its folder on the command line (its Dolt servers, a rehearsal's), then
    removes the folder. The watcher calls it too, however the run ended."""
    for pid in waits():
        with contextlib.suppress(ProcessLookupError):  # a wait that ended since it was listed
            os.kill(pid, signal.SIGKILL)
    stop_processes(ROOT.name)
    shutil.rmtree(ROOT, ignore_errors=True)


def stop_processes(folder: str) -> None:
    """SIGTERM, then SIGKILL, to every process whose command line names /tmp/<folder>/."""
    pids = [int(pid) for pid in subprocess.run(['pgrep', '-f', f'/{folder}/'], capture_output=True, text=True).stdout.split() if int(pid) != os.getpid()]
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in pids:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, sig)
        if wait_until(lambda: not any(alive(pid) for pid in pids), 5, 0.2):
            break


def alive(pid: int) -> bool:
    """A process that runs (a zombie, which only its parent has yet to reap, does not)."""
    state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith('Z')


def clear_dead_runs() -> None:
    """Stops the processes and removes the folder of every earlier run whose process is gone: its folder's runner.pid names no live
    process. A folder without one (or a server whose folder is gone) belongs to a run of an older script, cleared only when no other
    test-shared-board.py runs. Another live run's stay."""
    ps = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True).stdout
    runners = any('test-shared-board.py' in row and '--watch' not in row and row.split(maxsplit=1)[0] != str(os.getpid()) for row in ps.splitlines())
    names = {path.name for path in Path('/tmp').glob('shared-board.*')} | set(re.findall(r'/tmp/(shared-board\.[^/\s]+)/', ps))
    for name in sorted(names - {ROOT.name}):
        try:
            owner = int((Path('/tmp') / name / RUNNER_PID).read_text().strip())
        except (OSError, ValueError):
            owner = None
        if alive(owner) if owner else runners:
            continue
        stop_processes(name)
        shutil.rmtree(Path('/tmp') / name, ignore_errors=True)


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
        CHILDREN.append(subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--only', name, '--linked', *args],
                                         stdin=subprocess.PIPE, stdout=out, stderr=subprocess.STDOUT, text=True))
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


ORDER = ('unshared', 'share_join', 'setup', 'child_ids', 'queues', 'inbox', 'cr', 'window', 'pull', 'manual_and_dead_wait', 'soak', 'stopped', 'held_elsewhere', 'store', 'move', 'rehearse', 'migrate', 'cleanup')
SHARING = ('share_join', 'child_ids', 'queues', 'inbox', 'window', 'pull', 'manual_and_dead_wait', 'soak', 'stopped', 'held_elsewhere', 'store', 'move')
MIGRATION = ('rehearse', 'migrate')
PREFIX = ('unshared', 'share_join')  # a shared-board group starts on the board these leave: shared by a, joined by b
if options.watch:
    sys.stdin.read()  # end of file: the run is gone, however it ended
    cleanup()
    sys.exit(0)
WATCHER = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--watch', '--board', BOARD], stdin=subprocess.PIPE,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, 'SB_WATCH_ROOT': str(ROOT)}, start_new_session=True)
if options.linked:  # the parallel run that started this group is gone: end like on its SIGTERM
    threading.Thread(target=lambda: (sys.stdin.read(), os.kill(os.getpid(), signal.SIGTERM)), daemon=True).start()
only = [name for name in options.only.split(',') if name]
unknown = set(only) - set(ORDER)
if unknown:
    sys.exit(f"unknown group(s): {', '.join(sorted(unknown))}")
# soak is an upgrade check: --soak <s> or --only soak runs it.
selected = only or [name for name in ORDER if (options.soak if name == 'soak' else options.shared if name in SHARING else options.migrate if name in MIGRATION else True)]
shared = any(name in SHARING for name in selected)
clear_dead_runs()
for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(signum, on_signal)
if options.idle:
    print('idle', ROOT, flush=True)
    time.sleep(600)
    sys.exit(0)
if not options.only and not options.serial:
    started = time.time()
    code = run_parallel([name for name in selected if not (shared and name == 'share_join')])  # each shared group runs PREFIX itself
    print(f'   (parallel run {time.time() - started:.0f} s)', flush=True)
    cleanup()
    sys.exit(code)
try:
    setup()
    for name in ORDER:
        if name in selected or (shared and name in PREFIX):
            print(f'## {name}', flush=True)
            started = time.time()
            globals()[f't_{name}']()
            print(f'   ({time.time() - started:.0f} s)', flush=True)
finally:
    print(f'foreign key retries seen: {retries["retried"]}', flush=True)
    cleanup()
print('FAILED: ' + '; '.join(failures) if failures else 'all passed', flush=True)
sys.exit(1 if failures else 0)
