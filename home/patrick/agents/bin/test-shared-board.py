#!/usr/bin/env python3
"""Two-clone tests of shared boards through the real `board`, real bd and a local bare git remote.

    python3 -B bin/test-shared-board.py [--board <path>] [--only <name>,<name>] [--seconds <s>] [--soak <s>]

Needs bd and Dolt, which the validator's build sandbox lacks: bin/test-agent-configs.py holds the fake-bd checks, this holds
the ones only real clones can show. Everything lives in a temp folder, and every server it starts is stopped.
Rerun after a bd upgrade; the soak is the check that retires the write retry (board WRITE_RETRY_ERROR).
"""
from __future__ import annotations

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
parser.add_argument('--soak', type=float, default=40, help='seconds of parallel writing')
options = parser.parse_args()
BOARD = str(Path(options.board).resolve())
REGISTRY = str(Path(BOARD).parent / 'session-lead-mode')
ROOT = Path(tempfile.mkdtemp(prefix='shared-board.', dir='/tmp'))
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


def run(side: str, *args: str, role: str | None = 'lead', stdin: str | None = None, timeout: float = 200):
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


def bd(side: str, *args: str, **kwargs):
    return run(side, 'bd', *args, **kwargs)


def check(ok: bool, what: str, detail: object = '') -> None:
    print(('  ok   ' if ok else '  FAIL ') + what + (f': {detail}' if detail != '' and not ok else ''), flush=True)
    if not ok:
        failures.append(what)


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, env=base_env('a')).stdout


def items(side: str) -> dict[str, dict]:
    _, out, _, _ = bd(side, 'export')
    return {row['id']: row for row in map(json.loads, filter(str.strip, out.splitlines())) if row.get('_type', 'issue') == 'issue'}


def create(side: str, title: str, *flags: str, role: str | None = 'lead') -> str:
    rc, out, err, _ = bd(side, 'create', title, '-t', 'task', '--description', 'x', '--silent', *flags, role=role)
    if rc:
        raise RuntimeError(f'create {title}: {err}{out}')
    return out.strip().splitlines()[-1]


def settle(*sides: str, seconds: float | None = None) -> None:
    """Both clones hold each other's writes: manual syncs, the same a person would run."""
    for _ in range(2):
        for side in sides:
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
        for role in ROLES:
            if role == 'none':
                continue
            env = {**base_env(side), 'CLAUDE_CODE_SESSION_ID': session(side, role)}
            subprocess.run(['bash', REGISTRY, 'activate', role, *(['--pulls', 'implement,design,review,plan'] if role == 'agent' else [])],
                           cwd=ROOT / side, env=env, capture_output=True, check=True)
    rc, out, err, _ = bd('a', 'init', '--server', '--stealth', '--prefix', 'sb', '--skip-hooks', '--skip-agents', role=None)
    if rc:
        raise RuntimeError(f'init: {err}{out}')
    for key, value in (('status.custom', 'decided:wip,released:active,in_review:wip,needs_ratification:wip'), ('types.custom', 'design')):
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
    check(rc == 0 and 'board share' in err and len(err.strip().splitlines()) == 1, 'a hand-added remote: one line pointing at board share', err)
    rc, out, err, _ = run('a', 'health')
    check(rc == 0 and 'other queues' not in out and not (ROOT / 'a/.beads/board-sync').exists(), 'only board\'s mark shares: a remote alone does not', err)
    bd('a', 'dolt', 'remote', 'remove', 'origin', role=None)
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
    check(rc == 1 and 'board bd create' in err and not out.strip(), 'child ids: q --parent is refused, naming create', out + err)
    tracked = create('a', 'tracked')
    both = create('a', 'two link kinds', '--deps', f'tracks:{tracked}', '--parent', epic)
    kinds = {(dep['type'], dep['depends_on_id']) for dep in items('a')[both].get('dependencies', [])}
    check(kinds == {('tracks', tracked), ('parent-child', epic)}, "child ids: a revision's two links both land (real bd)", kinds)
    rc, out, err, _ = bd('a', 'create', 'no such parent', '-t', 'task', '--description', 'x', '--parent', 'sb-nope')
    check(rc != 0, 'child ids: an unknown parent fails', out)
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
    check(rc == 2 and "ben's queue" in err, 'update --claim on another queue: refused', err)
    rc, out, _, _ = run('a', 'claim', role='agent')
    check(rc == 0 and ben not in out and 'claimed' in out, 'bare claim: mine only', out)
    run('a', 'unclaim', out.split()[1], role='agent') if rc == 0 else None
    # A blocker in another queue, always listed.
    blocked = create('a', 'anna waits')
    bd('a', 'dep', 'add', blocked, ben)
    settle('a', 'b')
    _, out, _, _ = run('a', 'health')
    check('blocking yours' in out and ben in out, "other people's items blocking mine are listed", out)
    # Parents in different queues.
    mixed = create('a', 'two parents', '--parent', epic)
    bd('a', 'dep', 'add', mixed, ben, '--type', 'parent-child')
    settle('a', 'b')
    _, out, _, _ = run('b', 'health')
    check('unrouted' in out and mixed in out and 'queues anna,ben' in out, 'parents in different queues: unrouted and listed', out)
    _, out, _, _ = run('a', 'queue')
    check(mixed not in out.split('unrouted')[0], 'parents in different queues: nobody claims it by default', out)
    rc, _, err, _ = run('a', 'claim', mixed, role='agent')
    check(rc == 1 and 'unrouted' in err and f'board route <person> {mixed}' in err, 'claim by id on an unrouted item: refused until routed', err)
    rc, _, err, _ = run('a', 'take', mixed)
    check(rc == 1 and 'unrouted' in err, 'take on an unrouted item: refused', err)
    rc, _, err, _ = bd('a', 'update', mixed, '--claim', role='agent')
    check(rc == 2 and 'unrouted' in err, 'update --claim on an unrouted item: refused', err)
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
    run('a', 'unclaim', mixed, role='agent')
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
    item = create('a', 'to move')
    parent_b = create('b', 'ben parent')
    settle('a', 'b')
    child = create('a', 'to reparent', '--parent', item)
    for role in ('agent', 'none'):
        for args in (('label', 'add', item, 'queue:ben'), ('label', 'remove', item, 'queue:anna'),
                     ('update', item, '--add-label', 'queue:ben'), ('update', item, '--set-labels', 'x:y'),
                     ('update', child, '--parent', parent_b), ('dep', 'add', child, parent_b, '--type', 'parent-child'),
                     ('sql', f"delete from labels where issue_id='{item}'"),
                     ('create', 'for ben', '-t', 'task', '--description', 'x', '-l', 'queue:ben')):
            rc, _, err, _ = bd('a', *args, role=role)
            check(rc == 2 and 'only lead and solo' in err, f'{role} session refused: {" ".join(args[:2])}', err)
    env_rc = subprocess.run([sys.executable, '-B', BOARD, 'bd', 'label', 'add', item, 'queue:ben'], cwd=ROOT / 'a', capture_output=True, text=True,
                            env={**base_env('a'), 'BEADS_ACTOR': f"{session('a', 'lead')[-8:]}/worker01", 'CLAUDE_CODE_SESSION_ID': session('a', 'lead')})
    check(env_rc.returncode == 2 and 'only lead and solo' in env_rc.stderr, "a lead's worker is refused", env_rc.stderr)
    rc, _, err, _ = bd('a', 'update', item, '--add-label', 'topic:free', role='agent')
    check(rc == 0, 'agent: other label changes pass', err)
    rc, _, err, _ = bd('a', 'update', child, '--parent', '', role='lead')
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
    rc, _, err, took = bd('a', 'create', 'burst first', '-t', 'task', '--description', 'x', '--silent')
    check(took < 4, f'a write returns at once with the wait detached ({took:.1f} s)', took)
    made = [create('a', f'burst {n}') for n in range(5)]
    check(len(waits()) == 1, 'one wait for the board', waits())
    check(commits('a') == before, 'writes stay uncommitted during the window')
    if not wait_until(lambda: commits('a') > before and not waits(), options.seconds * 4):
        check(False, 'the wait synced and ended', commits('a'))
    elapsed = time.time() - started
    check(elapsed >= options.seconds - 1, f'sync waited for the window ({elapsed:.1f} s of {options.seconds} s)')
    check(commits('a') - before <= 2 and commits('a') - before >= 1, 'a burst goes out as one commit (a merge may add one)', commits('a') - before)
    bd('b', 'dolt', 'pull')
    check(all(item in items('b') for item in made), 'the burst reached the other clone')


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
    end = time.time() + options.soak
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
            rc, _, err, _ = bd(side, 'update', item, '--description', 'v1', role='lead')
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


def conflicted() -> str:
    """Delete against edit: b's next sync stops."""
    settle('a', 'b')
    wait_until(lambda: not waits(), options.seconds * 3)
    victim = create('a', 'victim')
    settle('a', 'b')
    bd('a', 'delete', victim, '--force')
    bd('a', 'sync')
    bd('b', 'update', victim, '--description', 'edited on b')
    return victim


def t_stopped() -> None:
    victim = conflicted()
    check(wait_until(lambda: sync_state('b').get('kind') == 'conflict', options.seconds * 4), 'the wait reports the conflict', sync_state('b'))
    rc, out, err, _ = run('b', 'health')
    check(rc == 0 and 'merge conflict' in err and 'bd conflicts resolve' in err, 'stopped sync: a read prints the problem and the fix', err)
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
    bd('b', 'create', 'same b', '-t', 'task', '--description', 'x', '--id', 'sb-collide', '--silent')
    check(wait_until(lambda: sync_state('b').get('kind') == 'conflict', options.seconds * 4), 'an id collision reports a conflict', sync_state('b'))
    rc, _, err, _ = run('b', 'position')
    check('CALL DOLT_MERGE' in err and 'bd rename' in err, 'the line carries the collision fix', err)
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
    rc, _, err, _ = bd('a', 'update', sorted(items('a'))[0], '--notes', 'still working')
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
    run('b', 'unclaim', item)
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
    rc, out, err, _ = run('a', 'create', '--for', 'ben', 'found for ben', '-t', 'bug', '--description', 'x', '--silent', role='agent')
    found = out.strip().splitlines()[-1] if rc == 0 else ''
    row = items('a').get(found, {})
    check(rc == 0 and {'for:ben', 'queue:anna'} <= set(row.get('labels', [])) and row.get('assignee') == 'user',
          'create --for: in my queue, held for my person, labelled for the other', err + out)
    rc, _, err, _ = run('a', 'create', '--for', 'ben', 'child find', '-t', 'bug', '--description', 'x', '--parent', found, role='agent')
    check(rc == 1 and '--parent' in err, 'create --for refuses --parent', err)
    rc, _, err, _ = run('a', 'claim', found, role='agent')
    check(rc == 1, 'a held find is not claimed', err)
    _, out, _, _ = run('a', 'health', '--json')
    check(found in [i['id'] for i in json.loads(out)['queues']['toSend']], 'health --json lists the finds held for my person', out[:300])
    rc, _, err, _ = run('a', 'send', 'ben', found, role='agent')
    check(rc == 1 and 'only lead' in err, 'send: an agent is refused', err)
    rc, out, err, _ = run('a', 'send', 'ben', found)
    row = items('a')[found]
    check(rc == 0 and 'for:ben' in row['labels'] and not any(label.startswith('queue:') for label in row['labels']) and not row.get('assignee'),
          'send: drops the queue label and the user hold, the item sits in the inbox', (err + out, row.get('labels'), row.get('assignee')))
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
    # route on a held find drops for: and the user hold; another user hold stays.
    rc, out, _, _ = run('a', 'create', '--for', 'ben', 'second find', '-t', 'bug', '--description', 'x', '--silent', role='agent')
    second = out.strip().splitlines()[-1]
    waiting = create('a', 'waits on anna')
    bd('a', 'update', waiting, '--assignee', 'user')
    rc, _, err, _ = run('a', 'route', 'ben', second, waiting)
    rows = items('a')
    check(rc == 0 and not rows[second].get('assignee') and 'for:ben' not in rows[second]['labels'] and 'queue:ben' in rows[second]['labels'],
          "route on a find: drops for: and the user hold", (err, rows[second]))
    check(rows[waiting].get('assignee') == 'user', 'route keeps other user holds', rows[waiting].get('assignee'))
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


def t_move() -> None:
    """board move (beads-setup.md#history) to a local fresh repository, a stale clone told, its rejoin, a new joiner."""
    settle('a', 'b')
    wait_until(lambda: not waits(), options.seconds * 3)
    item = create('a', 'survives the move')
    settle('a', 'b')
    wait_until(lambda: not waits(), options.seconds * 3)
    git('init', '-q', '--bare', 'fresh.git')
    git('push', '-q', str(ROOT / 'fresh.git'), 'main', cwd=ROOT / 'seed')
    fresh = f'git+file://{ROOT}/fresh.git'
    rc, _, err, _ = run('a', 'move', fresh, role='agent')
    check(rc == 1 and 'only lead' in err, 'move: an agent is refused', err)
    rc, _, err, _ = run('a', 'move', f'git+file://{ROOT}/empty.git')
    check(rc == 1 and 'empty' in err and 'not set' in bd('a', 'config', 'get', 'custom.board.moved')[1], 'move: an empty repository is refused before the note', err)
    before = commits('a')
    rc, out, err, _ = run('a', 'move', fresh)
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
    check(rc == 0 and stale in out and 'board bd import' in out, 'rejoin: lists the items the new board lacks, with bd import', err + out)
    check(not git('status', '--short', cwd=ROOT / 'b').strip(), 'rejoin: the kept copy stays out of project history', git('status', '--short', cwd=ROOT / 'b'))
    rows = items('b')
    check(item in rows and stale not in rows and not sync_state('b').get('moved'), 'rejoin: the new board, without the stale write')
    found = re.search(r'board bd import (\S+)', out)
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
            'status.custom': 'decided:wip,released:active,in_review:wip,needs_ratification:wip', 'types.custom': 'design', 'min_hash_length': '5'}


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
    check(setting('setupproj', 'validation.on-close') == 'error' and setting('setupproj', 'types.custom') == 'design', 'setup: the values are applied')
    check('already has a board' in out, 'setup: an existing board is never re-created', out)
    rc, out, err, _ = run('setupproj', 'setup', role=None)
    check(rc == 0 and ' -> ' not in out and 'up to date' in out, 'setup again: nothing to do', err + out)
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


def cleanup() -> None:
    for pid in waits():
        os.kill(pid, signal.SIGKILL)
    for side in ('a', 'b', 'c', 'unset', 'setupproj', 'setupsrv'):
        if (ROOT / side / '.beads').exists():
            subprocess.run([sys.executable, '-B', BOARD, 'bd', 'dolt', 'stop'], cwd=ROOT / side, env=base_env(side), capture_output=True, input='', text=True)
    shutil.rmtree(ROOT, ignore_errors=True)


ORDER = ('unshared', 'share_join', 'setup', 'child_ids', 'queues', 'moves', 'inbox', 'window', 'pull', 'manual_and_dead_wait', 'soak', 'stopped', 'held_elsewhere', 'store', 'move')
only = {name for name in options.only.split(',') if name}
try:
    setup()
    for name in ORDER:
        # share_join and unshared set up every later group.
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
