#!/usr/bin/env python3
"""Behaviour tests of bin/scratch.

    python3 -B bin/test-scratch.py </dev/null [--only a,b] [--scratch <path to a copy of scratch>]

Everything runs in temp folders (HOME, XDG_STATE_HOME, the session registry and a fake board are all temp); the
session variables of the running agent are removed from every child. --scratch runs the suite against a mutated
copy (the break checks).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--only', default='')
parser.add_argument('--scratch', default=str(HERE / 'scratch'))
OPTIONS = parser.parse_args()
SCRATCH = OPTIONS.scratch
SESSION = HERE / 'session'
SESSION_ID = 'sess-0001-abcd1234'
ACTOR = 'abcd1234'
DAY = 86400

FAKE_BOARD = '''#!{python}
import json, os, sys
items = dict(line.split() for line in open(os.environ['FAKE_BOARD_ITEMS']).read().splitlines() if line.strip())
args = sys.argv[1:]
if os.environ.get('FAKE_BOARD_FAIL'):
    sys.exit(1)
if args[:1] == ['show']:
    full = next((i for i in (args[1], 't-' + args[1]) if i in items), None)
    if full is None:
        print('board: unknown ' + args[1], file=sys.stderr)
        sys.exit(1)
    print(json.dumps({{full: {{'status': items[full]}}}}))
elif args[:2] == ['bd', 'list']:
    print(json.dumps([{{'id': i}} for i, s in items.items() if s == 'closed']))
else:
    sys.exit(2)
'''


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def backdate(path, days: float, clock: float | None = None) -> None:
    """Make the path and everything below it (symlinks as links) last written `days` before `clock` (default: now).
    ctime cannot be set: tests that need idle data run scratch on a clock `skew` days ahead (SCRATCH_NOW)."""
    moment = (time.time() if clock is None else clock) - days * DAY
    for top, dirs, files in os.walk(path, followlinks=False):
        for name in (*dirs, *files):
            os.utime(os.path.join(top, name), (moment, moment), follow_symlinks=False)
    os.utime(path, (moment, moment), follow_symlinks=False)


def age_entry(entry: str, days: float) -> str:
    """Make a trash entry look trashed `days` ago (the time stored in it); the same path."""
    Path(f'{entry}/trashed').write_text(f'{int(time.time() - days * DAY)}\n')
    return entry


class Env:
    def __init__(self, tmp: str):
        self.tmp = os.path.realpath(tmp)
        self.home = f'{self.tmp}/home'
        self.state = f'{self.tmp}/state'
        self.sessions = f'{self.tmp}/sessions'
        self.work = f'{self.tmp}/work'
        self.items = f'{self.tmp}/items.txt'
        self.board = f'{self.tmp}/board'
        for d in (self.home, self.state, self.sessions, self.work):
            os.makedirs(d)
        Path(self.items).write_text('')
        Path(self.board).write_text(FAKE_BOARD.format(python=sys.executable))
        os.chmod(self.board, 0o755)
        self.root = f'{self.state}/agents/scratch'
        self.background = False
        self.skew = 0  # days the scratch clock runs ahead of the real one

    def environ(self, session: bool = True, **extra) -> dict:
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('CODEX_', 'CLAUDE', 'BEADS_', 'XDG_', 'AGENT_', 'SCRATCH_', 'GIT_'))}
        env.update(HOME=self.home, XDG_STATE_HOME=self.state, AGENT_SESSION_STATE_DIR=self.sessions,
                   AGENT_SESSION_COMMAND=str(SESSION), AGENT_BOARD_COMMAND=self.board, FAKE_BOARD_ITEMS=self.items,
                   GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1')
        if not self.background:
            env['SCRATCH_NO_BACKGROUND'] = '1'
        if self.skew:
            env['SCRATCH_NOW'] = str(self.clock())
        if session:
            env['CLAUDE_CODE_SESSION_ID'] = SESSION_ID
        env.update(extra)
        return env

    def clock(self) -> float:
        return time.time() + self.skew * DAY

    def scratch(self, *args: str, cwd: str, session: bool = True, **extra) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, '-B', SCRATCH, *args], cwd=cwd, env=self.environ(session, **extra),
                              capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)

    def repo(self, *parts: str, board: bool = False, git: bool = True) -> str:
        path = os.path.join(self.work, *parts)
        os.makedirs(path)
        if git:
            subprocess.run(['git', 'init', '-q', path], check=True, env=self.environ(False))
        if board:
            os.makedirs(f'{path}/.beads')
            Path(f'{path}/.beads/metadata.json').write_text('{}')
        return path

    def folder(self, repo: str) -> str:
        return f"{self.root}/{os.path.realpath(repo).replace('/', '-')}"

    def session_dir(self, repo: str) -> str:
        out = self.scratch('dir', cwd=repo)
        check(out.returncode == 0, f'dir failed: {out.stderr}')
        return out.stdout.strip()

    def register(self, session: str, **fields) -> None:
        entry = {'session': session, 'actor': session[-8:], 'role': 'lead', 'tool': 'claude', 'pulls': [],
                 'registered_at': '2026-01-01T00:00:00Z', **fields}
        Path(f'{self.sessions}/{session}.json').write_text(json.dumps(entry))

    def make(self, base: str, name: str, days: float = 0, body: str = 'x') -> str:
        path = os.path.join(base, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_text(body)
        if days or self.skew:
            backdate(os.path.join(base, name.split('/')[0]), days, self.clock())  # the entry's own mtime counts too
        return path


TESTS: dict = {}


def test(function):
    TESTS[function.__name__] = function
    return function


def lines(out: subprocess.CompletedProcess) -> list[str]:
    return out.stdout.splitlines()


# Interface

@test
def help_lists_every_verb(e: Env):
    for args in ((), ('help',)):
        out = e.scratch(*args, cwd=e.work)
        check(out.returncode == 0, f'{args}: exit {out.returncode}')
        for verb in ('dir', 'trash', 'restore', 'list', 'status', 'sweep', 'migrate'):
            check(f'scratch {verb}' in out.stdout, f'help misses an example of {verb}: {out.stdout}')
    check(e.scratch('frobnicate', cwd=e.work).returncode == 2, 'an unknown verb must exit 2')
    bare = e.scratch('sweep', cwd=e.work)
    check(bare.returncode == 0 and bare.stdout.strip() == 'nothing to sweep', f'sweep with no scratch: {bare.stdout}{bare.stderr}')
    check(not os.path.exists(e.root), 'help, refusals and an empty sweep must not create the scratch root')


# dir

@test
def dir_session_folder(e: Env):
    repo = e.repo('proj')
    out = e.scratch('dir', cwd=repo)
    expected = f'{e.folder(repo)}/sessions/{ACTOR}'
    check(out.returncode == 0 and out.stdout == expected + '\n', f'dir printed {out.stdout!r}, wanted {expected}')
    check(os.path.isdir(expected), 'dir must create the folder')
    check(Path(f'{e.folder(repo)}/.repo').read_text().strip() == repo, '.repo must hold the repo path')
    sub = os.path.join(repo, 'a', 'b')
    os.makedirs(sub)
    check(e.scratch('dir', cwd=sub).stdout == out.stdout, 'a subfolder must give the same session folder')
    worker = e.scratch('dir', cwd=repo, BEADS_ACTOR=f'{ACTOR}/ffffffff')
    check(worker.stdout == out.stdout, f"a worker uses its session's folder: {worker.stdout!r}")
    subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'x'],
                   cwd=repo, check=True, env=e.environ(False))
    tree = f'{repo}/.worktrees/wt'
    subprocess.run(['git', 'worktree', 'add', '-q', tree], cwd=repo, check=True, env=e.environ(False))
    check(e.scratch('dir', cwd=tree).stdout == out.stdout, 'a worktree must share the main repo folder')


@test
def dir_outside_session_refuses(e: Env):
    repo = e.repo('proj')
    out = e.scratch('dir', cwd=repo, session=False)
    check(out.returncode == 2 and '--for' in out.stderr and '--shared' in out.stderr, f'{out.returncode} {out.stderr!r}')
    check(not os.path.exists(e.root), 'a refusal must create nothing')


@test
def dir_shared_names(e: Env):
    repo = e.repo('proj')
    out = e.scratch('dir', '--shared', 'fixtures', cwd=repo, session=False)
    check(out.stdout == f'{e.folder(repo)}/shared/fixtures\n' and os.path.isdir(out.stdout.strip()), out.stdout + out.stderr)
    for bad in ('../x', 'a/b', '.hidden', '', '-x'):
        refused = e.scratch('dir', '--shared', bad, cwd=repo)
        check(refused.returncode == 2, f'--shared {bad!r} must be refused')
    check(sorted(os.listdir(f'{e.folder(repo)}/shared')) == ['fixtures'], 'a refused name must create nothing')
    check(e.scratch('dir', '--shared', 'a', '--for', 'b', cwd=repo).returncode == 2, '--for with --shared is refused')


@test
def dir_for_needs_board_and_known_id(e: Env):
    plain = e.repo('plain')
    Path(e.items).write_text('t-1 open\n')  # the (fake) board knows it; only the repo's missing .beads refuses
    out = e.scratch('dir', '--for', 't-1', cwd=plain)
    check(out.returncode == 2 and '--shared' in out.stderr and 'board' in out.stderr, f'no board: {out.stderr!r}')
    check(not os.path.exists(e.root), 'a refused --for must create nothing')
    boarded = e.repo('boarded', board=True)
    Path(e.items).write_text('t-1 open\nt-abc open\n')
    out = e.scratch('dir', '--for', 't-9', cwd=boarded)
    check(out.returncode == 2 and '--shared' in out.stderr, f'unknown id: {out.stderr!r}')
    check(not os.path.exists(f'{e.folder(boarded)}/items/t-9'), 'an unknown id must not get a folder')
    out = e.scratch('dir', '--for', 't-1', cwd=boarded, session=False)
    check(out.stdout == f'{e.folder(boarded)}/items/t-1\n', out.stdout + out.stderr)
    out = e.scratch('dir', '--for', 'abc', cwd=boarded)
    check(out.stdout == f'{e.folder(boarded)}/items/t-abc\n', f'the board\'s full id names the folder: {out.stdout!r}')


@test
def repo_folder_naming_and_clash(e: Env):
    paths = [e.repo('a-b', 'c'), e.repo('a', 'b-c'), e.repo('a', 'b', 'c')]
    base = e.folder(paths[0])
    check(base == e.folder(paths[1]) == e.folder(paths[2]), 'the three paths must share one key')
    folders = [e.session_dir(p).rsplit('/sessions/', 1)[0] for p in paths]
    check(folders == [base, base + '-2', base + '-3'], f'clash suffixes: {folders}')
    for folder, path in zip(folders, paths):
        check(Path(f'{folder}/.repo').read_text().strip() == path, f'{folder}/.repo')
    check(e.session_dir(paths[1]).startswith(base + '-2/'), 'a repo keeps its suffixed folder')
    loose = f'{e.work}/nogit'
    os.makedirs(loose)
    check(e.session_dir(loose) == f"{e.root}/{loose.replace('/', '-')}/sessions/{ACTOR}", 'outside git: the resolved folder')


@test
def repo_prints_the_folder_name(e: Env):
    paths = [e.repo('a-b', 'c'), e.repo('a', 'b-c')]
    names = []
    for path in paths:
        out = e.scratch('__repo', cwd=path)
        check(out.returncode == 0, f'repo exit {out.returncode}: {out.stderr}')
        names.append(out.stdout.strip())
    base = os.path.basename(e.folder(paths[0]))
    check(names == [base, base + '-2'], f'repo prints the folder name, -2 for a clashing path: {names}')
    check(Path(f'{e.root}/{names[1]}/.repo').read_text().strip() == paths[1], 'repo reserves the folder with its .repo')
    check(e.scratch('__repo', cwd=paths[1]).stdout.strip() == names[1], 'repo is stable')


@test
def relative_xdg_state_home_is_ignored(e: Env):
    repo = e.repo('rel')
    out = e.scratch('dir', cwd=repo, XDG_STATE_HOME='relative')
    check(out.returncode == 0 and out.stdout.startswith(f'{os.path.realpath(e.home)}/.local/state/agents/scratch/'),
          f'a relative XDG_STATE_HOME falls back to the default under HOME: {out.stdout}{out.stderr}')
    check(not os.path.exists(f'{repo}/relative'), 'nothing is written relative to the working folder')


# trash and restore

@test
def trash_moves_into_trash(e: Env):
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    e.make(mine, 'dump/a.txt', body='data')
    out = e.scratch('trash', 'dump', cwd=mine)
    entry = out.stdout.strip()
    check(out.returncode == 0 and entry == f'{e.root}/.trash/{os.path.basename(e.folder(repo))}/dump',
          f'{out.stdout!r} {out.stderr!r}')
    check(not os.path.exists(f'{mine}/dump') and Path(f'{entry}/data/a.txt').read_text() == 'data', 'moved with content')
    check(Path(f'{entry}/origin').read_text().strip() == f'{mine}/dump', 'origin recorded')
    e.make(mine, 'dump/b.txt')
    second = e.scratch('trash', 'dump', cwd=mine).stdout.strip()
    third = (e.make(mine, 'dump/c.txt'), e.scratch('trash', 'dump', cwd=mine).stdout.strip())[1]
    check([os.path.basename(x) for x in (entry, second, third)] == ['dump', 'dump-2', 'dump-3'], f'a clash numbers the name: {second} {third}')


@test
def trash_refuses_outside_paths(e: Env):
    repo = e.repo('proj')
    other = e.repo('other')
    mine = e.session_dir(repo)
    e.session_dir(other)
    inside = e.make(mine, 'keep.txt')
    outside = e.make(repo, 'checkout.txt')
    foreign = e.make(e.folder(other) + '/sessions/x', 'f.txt')
    link_out = os.path.join(mine, 'link')
    os.symlink(repo, link_out)
    cases = [outside, e.root, e.folder(repo), f'{e.folder(repo)}/.repo', foreign, f'{mine}/../../../../x', f'{mine}/link/../x',
             f'{mine}/missing', '/']
    for path in cases:
        out = e.scratch('trash', path, cwd=repo)
        check(out.returncode == 2, f'{path} must be refused (exit {out.returncode})')
    out = e.scratch('trash', inside, outside, cwd=repo)
    check(out.returncode == 2 and os.path.exists(inside) and os.path.exists(outside), 'one bad path moves nothing')
    for path in (e.root, e.folder(repo), outside, foreign):
        check(os.path.exists(path), f'{path} must survive')
    plain = e.repo('fresh')
    check(e.scratch('trash', outside, cwd=plain).returncode == 2, 'a repo without a scratch folder trashes nothing')


@test
def trash_never_follows_symlinks(e: Env):
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    target = f'{e.tmp}/outside'
    e.make(target, 'precious.txt', body='keep')
    os.symlink(target, f'{mine}/node_modules')
    out = e.scratch('trash', f'{mine}/node_modules', cwd=repo)
    entry = out.stdout.strip()
    check(out.returncode == 0 and os.path.islink(f'{entry}/data') and os.readlink(f'{entry}/data') == target,
          f'the link itself goes to the trash: {out.stdout!r} {out.stderr!r}')
    check(Path(f'{target}/precious.txt').read_text() == 'keep', 'the link target is untouched')
    os.symlink(target, f'{mine}/again')
    check(e.scratch('trash', f'{mine}/again/precious.txt', cwd=repo).returncode == 2, 'a path through a link is outside')
    check(os.path.exists(f'{target}/precious.txt'), 'precious.txt survives')


@test
def restore_lists_and_moves_back(e: Env):
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    e.make(mine, 'dump/a.txt', body='data')
    entry = e.scratch('trash', f'{mine}/dump', cwd=repo).stdout.strip()
    listing = e.scratch('restore', cwd=repo)
    columns = listing.stdout.strip().split('\t')
    check(columns[0] == os.path.basename(entry) and columns[1] == f'{mine}/dump' and 'days left' in columns[2],
          f'listing: {listing.stdout!r}')
    out = e.scratch('restore', 'dump', cwd=repo)
    check(out.returncode == 0 and Path(f'{mine}/dump/a.txt').read_text() == 'data' and not os.path.exists(entry),
          f'restore: {out.stdout!r} {out.stderr!r}')
    check(e.scratch('restore', cwd=repo).stdout == '', 'the trash is empty after restoring')
    check(e.scratch('restore', 'nothing', cwd=repo).returncode == 2, 'an unknown name is refused')
    # parents that vanished are recreated
    e.make(mine, 'deep/er/f.txt')
    entry = e.scratch('trash', f'{mine}/deep/er/f.txt', cwd=repo).stdout.strip()
    shutil.rmtree(f'{mine}/deep')
    check(e.scratch('restore', os.path.basename(entry), cwd=repo).returncode == 0 and os.path.exists(f'{mine}/deep/er/f.txt'),
          'restore recreates missing parents')


@test
def restore_by_name_or_original_path(e: Env):
    repo = e.repo('proj')
    mine = e.session_dir(repo)

    def trash_twice() -> list[str]:
        entries = []
        for body in ('v1', 'v2'):
            e.make(mine, 'dump/a.txt', body=body)
            entries.append(e.scratch('trash', f'{mine}/dump', cwd=repo).stdout.strip())
        age_entry(entries[0], 1)  # the first one is older
        return entries

    first, second = trash_twice()
    check([os.path.basename(x) for x in (first, second)] == ['dump', 'dump-2'], 'plain names, then -2')
    shutil.rmtree(os.path.dirname(first))
    for form in ('absolute', 'relative', '~'):
        trash_twice()
        argument = {'absolute': f'{mine}/dump', 'relative': './dump', '~': f"~{mine[len(e.tmp):]}/dump"}[form]
        out = e.scratch('restore', argument, cwd=mine, HOME=e.tmp)
        check(out.returncode == 0 and Path(f'{mine}/dump/a.txt').read_text() == 'v2', f'{form}: {out.stderr!r}')
        check('newest of 2' in out.stderr and 'dump-2' in out.stderr, f'{form}: the output says which won: {out.stderr!r}')
        shutil.rmtree(f'{mine}/dump')
        shutil.rmtree(os.path.dirname(first))
    trash_twice()
    out = e.scratch('restore', 'dump', cwd=repo)  # a plain trash name picks exactly that entry
    check(out.returncode == 0 and Path(f'{mine}/dump/a.txt').read_text() == 'v1' and not out.stderr, f'by the plain name: {out.stderr!r}')
    check(e.scratch('restore', f'{mine}/never-trashed', cwd=repo).returncode == 2, 'an unknown path is refused')


@test
def restore_refuses_occupied_origin(e: Env):
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    for kind in ('file', 'fulldir'):
        e.make(mine, 'x', body='old')
        entry = e.scratch('trash', f'{mine}/x', cwd=repo).stdout.strip()
        if kind == 'file':
            Path(f'{mine}/x').write_text('new')
        else:
            e.make(mine, 'x/occupant.txt')
        out = e.scratch('restore', os.path.basename(entry), cwd=repo)
        check(out.returncode == 2 and os.path.exists(f'{entry}/data'), f'{kind}: occupied origin must be refused')
        check(os.path.exists(f'{mine}/x'), f'{kind}: the occupant stays')
        shutil.rmtree(entry)
        if kind == 'file':
            os.unlink(f'{mine}/x')
        else:
            shutil.rmtree(f'{mine}/x')


@test
def restore_over_an_empty_folder(e: Env):
    repo = e.repo('proj')
    shared = e.scratch('dir', '--shared', 'x', cwd=repo).stdout.strip()
    e.make(shared, 'f.txt', body='data')
    entry = e.scratch('trash', shared, cwd=repo).stdout.strip()
    e.scratch('dir', '--shared', 'x', cwd=repo)  # recreates the empty folder
    out = e.scratch('restore', 'x', cwd=repo)
    check(out.returncode == 0 and Path(f'{shared}/f.txt').read_text() == 'data' and not os.path.exists(entry), f'{out.stderr!r}')


@test
def restore_dot_name_takes_only_its_own_origin(e: Env):
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    e.make(mine, 'venv/a.txt', body='plain')
    e.scratch('trash', f'{mine}/venv', cwd=repo)
    e.make(mine, '.venv/a.txt', body='dot')
    e.scratch('trash', f'{mine}/.venv', cwd=repo)
    out = e.scratch('restore', '.venv', cwd=repo)
    check(out.returncode == 0 and Path(f'{mine}/.venv/a.txt').read_text() == 'dot' and not os.path.exists(f'{mine}/venv'),
          f'.venv restores the dot entry, not venv: {out.stderr!r}')
    check(e.scratch('restore', '.nothing', cwd=repo).returncode == 2, 'a dot name without an origin of that name is refused')


@test
def newest_wins_when_the_times_tie(e: Env):
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    pinned = {'SCRATCH_NOW': str(time.time())}
    for body in ('v1', 'v2'):
        e.make(mine, 'dump/a.txt', body=body)
        e.scratch('trash', f'{mine}/dump', cwd=repo, **pinned)
    out = e.scratch('restore', f'{mine}/dump', cwd=repo)
    check(out.returncode == 0 and Path(f'{mine}/dump/a.txt').read_text() == 'v2', f'the later trashing wins a tie: {out.stderr!r}')
    # without a pinned clock, a later trashing within the second still sorts later
    shutil.rmtree(f'{mine}/dump')
    stored = []
    for body in ('a', 'b'):
        e.make(mine, 'late/f.txt', body=body)
        stored.append(float(Path(e.scratch('trash', f'{mine}/late', cwd=repo).stdout.strip(), 'trashed').read_text()))
    check(stored[1] > stored[0], f'the stored time has sub-second precision: {stored}')


@test
def purge_after_seven_days(e: Env):
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    entries = {}
    for name in ('old', 'young'):
        e.make(mine, f'{name}/f.txt')
        entries[name] = e.scratch('trash', f'{mine}/{name}', cwd=repo).stdout.strip()
    entries['old'] = age_entry(entries['old'], 8)
    entries['young'] = age_entry(entries['young'], 6)
    out = e.scratch('list', cwd=repo)
    check(out.returncode == 0, out.stderr)
    trash = os.path.dirname(entries['old'])
    check(sorted(os.listdir(trash)) == [os.path.basename(entries['young'])], f'trash after purge: {os.listdir(trash)}')
    check(e.scratch('restore', 'young', cwd=repo).returncode == 0, 'the younger entry is still restorable')
    # background mode: renamed at once, deleted by a detached process
    e.background = True
    e.make(mine, 'old2/f.txt')
    entry = e.scratch('trash', f'{mine}/old2', cwd=repo).stdout.strip()
    entry = age_entry(entry, 8)
    e.scratch('restore', cwd=repo)
    deadline = time.time() + 10
    while os.path.exists(trash) and os.listdir(trash) and time.time() < deadline:
        time.sleep(0.1)
    check(not os.listdir(trash), f'the background delete did not finish: {os.listdir(trash)}')
    wait_idle(e, repo)


# list, ready, scan

def rows(out: subprocess.CompletedProcess) -> list[dict]:
    check(out.returncode == 0, out.stderr)
    return json.loads(out.stdout)


def ready_rows(out: subprocess.CompletedProcess) -> list[dict]:
    return [r for r in rows(out) if r['ready']]


@test
def list_entries_and_owners(e: Env):
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    e.make(mine, 'dump/deep/f.txt', body='12345')
    e.make(mine, 'note.txt')
    shared = f"{e.scratch('dir', '--shared', 'fx', cwd=repo).stdout.strip()}"
    e.make(shared, 'one/a.txt')
    e.make(shared, 'two.txt')
    found = rows(e.scratch('list', '--json', cwd=repo))
    paths = sorted(r['path'] for r in found)
    check(paths == sorted([f'{mine}/dump', f'{mine}/note.txt', shared]), f'top-level entries, shared as one: {paths}')
    by = {r['path']: r for r in found}
    check(by[shared]['owner'] == 'shared fx' and by[f'{mine}/dump']['owner'] == f'session {ACTOR}', f'owners: {found}')
    check(all(r['ready'] is None and r['size'] > 0 and r['modified'].endswith('Z') for r in found), f'fresh and sized: {found}')
    text = e.scratch('list', cwd=repo).stdout.splitlines()
    check(len(text) == 3 and all(l.split('\t')[0].startswith('/') and len(l.split('\t')) == 5 for l in text), f'text rows: {text}')
    check(e.scratch('list', '--ready', cwd=repo).returncode == 2, 'list --ready is gone')
    check(e.scratch('list', cwd=e.repo('empty')).stdout == '', 'a repo without a folder lists nothing')


@test
def ready_idle_judged_per_entry_by_newest_write(e: Env):
    e.skew = 20
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    e.make(mine, 'stale/f.txt', days=15)
    e.make(mine, 'mixed/old.txt', days=15)
    e.make(mine, 'mixed/sub/new.txt')  # newest write keeps the whole entry live
    for folder in ('mixed', 'mixed/sub'):
        old = e.clock() - 15 * DAY
        os.utime(f'{mine}/{folder}', (old, old))  # only the nested file is fresh
    e.make(mine, 'fresh.txt')
    shared_old = e.scratch('dir', '--shared', 'old', cwd=repo).stdout.strip()
    e.make(shared_old, 'a/f.txt', days=15)
    backdate(shared_old, 15, e.clock())
    shared_live = e.scratch('dir', '--shared', 'live', cwd=repo).stdout.strip()
    e.make(shared_live, 'a/f.txt', days=15)
    e.make(shared_live, 'b.txt')
    ready = {r['path']: r['ready'] for r in ready_rows(e.scratch('list', '--json', cwd=repo))}
    check(set(ready) == {f'{mine}/stale', shared_old}, f'ready: {ready}')
    check(all(reason.startswith('idle') for reason in ready.values()), f'reasons: {ready}')


@test
def ready_is_idle_only_whoever_owns_it(e: Env):
    repo = e.repo('proj', board=True)
    Path(e.items).write_text('t-done closed\nt-open open\n')
    for item in ('t-done', 't-open'):
        e.make(e.scratch('dir', '--for', item, cwd=repo).stdout.strip(), 'f.txt')
    sessions = f'{e.folder(repo)}/sessions'
    started = subprocess.run(['ps', '-o', 'lstart=', '-p', str(os.getpid())], capture_output=True, text=True,
                             env={**os.environ, 'LC_ALL': 'C', 'TZ': 'UTC0'}).stdout
    e.register(SESSION_ID, pid=os.getpid(), pid_started=' '.join(started.split()))  # live: this process
    e.register('sess-0002-deadbeef', pid=2 ** 22 - 3, pid_started='Mon Jan  1 00:00:00 2024')  # process ended
    for actor in (ACTOR, 'deadbeef', 'endedone'):
        e.make(f'{sessions}/{actor}', 'f.txt')
    Path(f'{e.sessions}/ended').write_text('endedone\n')
    e.make(e.scratch('dir', '--shared', 'fx', cwd=repo).stdout.strip(), 'f.txt')
    blind = {'AGENT_BOARD_COMMAND': '/nonexistent', 'AGENT_SESSION_COMMAND': '/nonexistent'}  # readiness reads neither

    def ready_at(days: int) -> dict:
        found = rows(e.scratch('list', '--json', cwd=repo, SCRATCH_NOW=str(time.time() + days * DAY), **blind))
        return {r['path']: r['ready'] for r in found if r['ready']}

    check(ready_at(13) == {}, f'nothing idle under 14 days is ready, whatever the owner state: {ready_at(13)}')
    later = ready_at(15)
    check(len(later) == 6 and all(reason == 'idle 15 days' for reason in later.values()),
          f'closed, open, gone, ended, live and shared alike are ready after 15 days: {later}')


@test
def a_change_in_ctime_counts_as_new(e: Env):
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    source = f'{e.tmp}/source'
    e.make(source, 'dir/f.txt')
    e.make(source, 'file.txt')
    for path in (f'{source}/dir/f.txt', f'{source}/dir', f'{source}/file.txt'):
        os.utime(path, (1_600_000_000,) * 2)
    for name in ('dir', 'file.txt'):
        subprocess.run(['cp', '-a', f'{source}/{name}', f'{mine}/{name}'], check=True)
        check(os.lstat(f'{mine}/{name}').st_mtime == 1_600_000_000, 'the copy kept its old mtime')
    found = {r['path']: r['ready'] for r in rows(e.scratch('list', '--json', cwd=repo))}
    check(found == {f'{mine}/dir': None, f'{mine}/file.txt': None}, f'cp -a data is new: {found}')
    e.scratch('__scan', cwd=repo)
    check(os.path.exists(f'{mine}/dir/f.txt') and os.path.exists(f'{mine}/file.txt'), 'the scan keeps it')


@test
def a_file_overwritten_with_old_mtime_keeps_its_entry_live(e: Env):
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    old = (1_600_000_000,) * 2
    e.make(mine, 'dataset/f.txt', body='v1')
    e.make(e.tmp, 'v2.txt', body='v2')
    for path in (f'{mine}/dataset/f.txt', f'{mine}/dataset', f'{e.tmp}/v2.txt'):
        os.utime(path, old)
    time.sleep(1.2)
    subprocess.run(['cp', '-a', f'{e.tmp}/v2.txt', f'{mine}/dataset/f.txt'], check=True)  # in place: the folder is untouched
    check(os.lstat(f'{mine}/dataset/f.txt').st_mtime == old[0] and Path(f'{mine}/dataset/f.txt').read_text() == 'v2', 'overwritten, old mtime')
    changed = os.lstat(f'{mine}/dataset/f.txt').st_ctime
    check(os.lstat(f'{mine}/dataset').st_ctime < changed - 1, 'the folder itself did not change')
    found = rows(e.scratch('list', '--json', cwd=repo, SCRATCH_NOW=str(changed + 14 * DAY - 0.5)))
    check([r['ready'] for r in found] == [None], f'the file\'s ctime keeps the entry live: {found}')


@test
def a_restored_entry_stays_through_the_next_scan(e: Env):
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    e.make(mine, 'keep.txt')
    os.utime(f'{mine}/keep.txt', (1_600_000_000,) * 2)  # old content: only the ctime says otherwise
    entry = e.scratch('trash', f'{mine}/keep.txt', cwd=repo).stdout.strip()
    time.sleep(1.2)
    check(e.scratch('restore', os.path.basename(entry), cwd=repo).returncode == 0, 'restore')
    changed = os.lstat(f'{mine}/keep.txt').st_ctime
    # a clock just short of 14 days after the restore: the rename's ctime (not the trash one, 1.2 s earlier) must count
    clock = str(changed + 14 * DAY - 0.5)
    found = rows(e.scratch('list', '--json', cwd=repo, SCRATCH_NOW=clock))
    check([r['ready'] for r in found] == [None], f'restored entry judged: {found}')
    e.scratch('__scan', cwd=repo, SCRATCH_NOW=clock)
    check(os.path.exists(f'{mine}/keep.txt'), 'the next scan leaves the restored entry')
    e.scratch('__scan', cwd=repo, SCRATCH_NOW=str(changed + 14 * DAY + 5))
    check(not os.path.exists(f'{mine}/keep.txt'), 'it expires 14 days after the restore')


@test
def empty_owner_folders_expire(e: Env):
    repo = e.repo('proj', board=True)
    Path(e.items).write_text('t-1 open\n')
    folder = e.folder(repo)
    mine = e.session_dir(repo)
    e.make(mine, 'f.txt')
    empty_session = f'{folder}/sessions/emptyone'
    empty_item = e.scratch('dir', '--for', 't-1', cwd=repo).stdout.strip()
    os.makedirs(empty_session)
    base = time.time()
    e.scratch('__scan', cwd=repo, SCRATCH_NOW=str(base + 13 * DAY))
    check(os.path.isdir(empty_session) and os.path.isdir(empty_item), 'empty owner folders stay under 14 days')
    e.scratch('__scan', cwd=repo, SCRATCH_NOW=str(base + 15 * DAY))
    check(not os.path.exists(empty_session) and not os.path.exists(empty_item), 'empty owner folders unchanged for 14 days go')
    check(os.path.isdir(mine) and not os.path.exists(f'{mine}/f.txt'), 'a folder that just lost its entry stays (it changed)')
    e.scratch('__scan', cwd=repo, SCRATCH_NOW=str(base + 30 * DAY))
    check(not os.path.exists(mine), 'and goes 14 days after it emptied')
    check(os.path.isdir(f'{folder}/sessions') and os.path.exists(f'{folder}/.repo'), 'only the owner folders go')


@test
def walks_never_follow_symlinks(e: Env):
    e.skew = 20
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    outside = f'{e.tmp}/outside'
    e.make(outside, 'big.bin', body='x' * 2_000_000)
    e.make(mine, 'entry/old.txt', body='y', days=15)
    os.symlink(outside, f'{mine}/entry/node_modules')
    os.symlink('.', f'{mine}/entry/loop')
    backdate(f'{mine}/entry', 15, e.clock())  # the fresh target must not make the entry live
    found = rows(e.scratch('list', '--json', cwd=repo))
    (entry,) = [r for r in found if r['path'] == f'{mine}/entry']
    check(entry['size'] < 500_000, f"the link target was counted: {entry['size']}")
    check(entry['ready'] and entry['ready'].startswith('idle'), f'a fresh link target made the entry live: {entry}')


@test
def list_all_flags_gone_repos(e: Env):
    repo = e.repo('proj')
    e.session_dir(repo)
    gone = f'{e.root}/-nowhere-gone'
    os.makedirs(f'{gone}/sessions/x')
    Path(f'{gone}/.repo').write_text(f'{e.tmp}/nowhere/gone\n')
    e.make(f'{gone}/sessions/x', 'f.txt', body='z')
    os.makedirs(f'{e.root}/.trash/q')
    found = {r['path']: r for r in rows(e.scratch('list', '--all', '--json', cwd=repo))}
    check(set(found) == {e.folder(repo), gone}, f'repo folders: {sorted(found)}')
    check(found[gone]['gone'] is True and found[e.folder(repo)]['gone'] is False, f'gone flags: {found}')
    check(found[gone]['repo'] == f'{e.tmp}/nowhere/gone', 'the .repo path is shown')
    check(os.path.isdir(gone), 'list --all never removes a repo folder')


def wait_idle(e: Env, repo: str) -> None:
    lock = f'{e.root}/.cache/{os.path.basename(e.folder(repo))}/scan.lock'
    deadline = time.time() + 15
    while os.path.exists(lock) and time.time() < deadline:
        time.sleep(0.1)


def cache_path(e: Env, repo: str) -> str:
    return f'{e.root}/.cache/{os.path.basename(e.folder(repo))}/cache.json'


def seed_ready(e: Env, repo: str, count: int = 2) -> str:
    mine = e.session_dir(repo)
    for i in range(count):
        e.make(mine, f'old{i}/f.txt', days=15, body='x' * 1000)
    e.make(mine, 'fresh.txt')
    return mine


@test
def scan_trashes_ready_entries(e: Env):
    e.skew = 20
    repo = e.repo('proj')
    mine = seed_ready(e, repo)
    long_name = 'n' * 255  # cannot be trashed (its trash name is taken and a -2 suffix is too long): skipped, the rest goes
    e.make(mine, long_name, days=15)
    os.makedirs(f'{e.root}/.trash/{os.path.basename(e.folder(repo))}/{long_name}')
    link = f'{mine}/link'
    target = f'{e.tmp}/outside'
    e.make(target, 'precious.txt', body='keep')
    os.symlink(target, link)
    os.utime(link, (e.clock() - 15 * DAY,) * 2, follow_symlinks=False)
    shared = e.scratch('dir', '--shared', 'old', cwd=repo).stdout.strip()
    e.make(shared, 'a/f.txt', days=15)
    backdate(shared, 15, e.clock())
    out = e.scratch('__scan', cwd=repo)
    check(out.returncode == 0 and 'Traceback' not in out.stderr, out.stderr)
    for gone in ('old0', 'old1', 'link'):
        check(not os.path.lexists(f'{mine}/{gone}'), f'{gone} is trashed by the scan')
    check(os.path.exists(f'{mine}/fresh.txt') and os.path.exists(f'{mine}/{long_name}'), 'fresh and untrashable entries stay')
    check(not os.path.exists(shared), 'an idle shared folder goes as one entry')
    check(os.path.isdir(f'{e.folder(repo)}/sessions') and os.path.exists(f'{e.folder(repo)}/.repo'), 'the repo and owner folders stay')
    check(Path(f'{target}/precious.txt').read_text() == 'keep', 'a link is trashed as a link')
    listing = e.scratch('restore', cwd=repo).stdout
    check('old0\t' in listing and 'link\t' in listing, f'trash holds them: {listing!r}')
    cached = json.loads(Path(cache_path(e, repo)).read_text())
    check('ready' not in cached and cached['total_entries'] == 2, f'the cache counts what remains (fresh.txt, long name): {cached}')
    check(e.scratch('restore', 'old0', cwd=repo).returncode == 0 and os.path.exists(f'{mine}/old0/f.txt'), 'scan-trashed entries restore')
    check(not [n for n in os.listdir(os.path.dirname(cache_path(e, repo))) if n.startswith('.') or n.endswith('.lock')],
          'the scan leaves no temporary file or lock behind')


@test
def dir_starts_the_hourly_scan(e: Env):
    e.skew = 20
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    e.make(mine, 'old/f.txt', days=15)
    e.background = True
    e.scratch('dir', cwd=repo)
    deadline = time.time() + 15
    while os.path.exists(f'{mine}/old') and time.time() < deadline:
        time.sleep(0.1)
    check(not os.path.exists(f'{mine}/old'), 'dir starts a background scan that trashes the idle entry')
    wait_idle(e, repo)
    e.make(mine, 'old2/f.txt', days=15)
    e.scratch('dir', cwd=repo)
    time.sleep(1.5)
    check(os.path.exists(f'{mine}/old2'), 'no second scan within the hour')


@test
def trash_age_is_the_stored_time(e: Env):
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    e.make(mine, 'old-contents/f.txt', days=30)
    by_trash = e.scratch('trash', f'{mine}/old-contents', cwd=repo).stdout.strip()
    trash = os.path.dirname(by_trash)
    os.utime(by_trash, (time.time() - 30 * DAY,) * 2)  # the wrapper's mtime says old; the stored time says now
    e.scratch('list', cwd=repo)
    check(os.path.exists(by_trash), 'a folder with 30-day-old contents trashed now is not purged')
    check('within 7 days' in e.scratch('status', '--line', cwd=repo).stdout, 'restorable-until measures from the stored time')
    by_trash = age_entry(by_trash, 8)
    os.utime(by_trash, (time.time(),) * 2)  # fresh mtime, old stamp
    e.scratch('list', cwd=repo)
    check(not os.path.exists(by_trash), 'it is purged once the stored time is over seven days old')
    # the expiry scan trashes by the same rule
    e.skew = 20
    e.make(mine, 'stale/f.txt', days=30)
    e.scratch('__scan', cwd=repo)
    (entry,) = [os.path.join(trash, n) for n in os.listdir(trash)]
    e.scratch('list', cwd=repo)
    check(os.path.exists(entry), 'a scan-trashed 30-day-old folder survives until seven days after the scan')
    # an unparsable name falls back to the mtime
    odd = os.path.join(trash, 'odd-name')
    os.makedirs(odd)
    os.utime(odd, (time.time() - 8 * DAY,) * 2)
    e.scratch('list', cwd=repo)
    check(not os.path.exists(odd) and os.path.exists(entry), 'an entry without a stored time ages by its mtime')
    garbled = os.path.join(trash, 'garbled')
    os.makedirs(garbled)
    Path(f'{garbled}/trashed').write_text('not a time\n')
    os.utime(garbled, (time.time() - 8 * DAY,) * 2)
    e.scratch('list', cwd=repo)
    check(not os.path.exists(garbled), 'an unreadable stored time falls back to the mtime too')


@test
def status_line_reports_the_trash(e: Env):
    repo = e.repo('proj')
    check(e.scratch('status', '--line', cwd=repo).stdout == '' and not os.path.exists(e.root), 'no folder: empty, nothing created')
    mine = e.session_dir(repo)
    check(e.scratch('status', '--line', cwd=repo).stdout == '', 'empty trash: empty line')
    e.make(mine, 'a/f.txt', body='x' * 5000)
    e.make(mine, 'b/f.txt')
    first = e.scratch('trash', f'{mine}/a', cwd=repo).stdout.strip()
    e.scratch('trash', f'{mine}/b', cwd=repo)
    out = e.scratch('status', '--line', cwd=repo)
    check(re.fullmatch(r'scratch: 2 trashed \([\d.]+ (B|KB|MB)\), the first is deleted within 7 days \(scratch restore\)\n', out.stdout), out.stdout)
    age_entry(first, 5.5)
    out = e.scratch('status', '--line', cwd=repo)
    check('deleted within 2 days' in out.stdout, f'the oldest entry sets the time: {out.stdout!r}')
    full = e.scratch('status', cwd=repo).stdout
    check('trash: 2 entries' in full and 'entries:' in full, full)
    other = e.repo('other')
    e.session_dir(other)
    check(e.scratch('status', '--line', cwd=other).stdout == '', 'another repo\'s trash is not counted')


@test
def scan_lock_and_hourly_rule(e: Env):
    repo = e.repo('proj')
    seed_ready(e, repo)
    state = os.path.dirname(cache_path(e, repo))
    os.makedirs(f'{state}/scan.lock')
    e.scratch('__scan', cwd=repo)
    check(not os.path.exists(cache_path(e, repo)), 'a held lock means no second scan')
    old = time.time() - 2 * 3600
    os.utime(f'{state}/scan.lock', (old, old))
    e.scratch('__scan', cwd=repo)
    check(os.path.exists(cache_path(e, repo)) and not os.path.exists(f'{state}/scan.lock'), 'a stale lock is reclaimed')
    # background scans: none within the hour of the root's last scan, one when stale, one when missing
    e.background = True
    marker = f'{e.root}/.cache/.scanned.json'
    sentinel = {'scanned_at': time.time(), 'total_entries': 9, 'total_size': 9, 'ready': []}
    Path(cache_path(e, repo)).write_text(json.dumps(sentinel))
    Path(marker).write_text(json.dumps({'scanned_at': time.time()}))
    e.scratch('status', '--line', cwd=repo)
    time.sleep(1.5)
    check(json.loads(Path(cache_path(e, repo)).read_text()) == sentinel, 'a root scanned within the hour is not rescanned')
    Path(marker).write_text(json.dumps({'scanned_at': time.time() - 2 * 3600}))
    e.scratch('status', '--line', cwd=repo)
    deadline = time.time() + 15
    while json.loads(Path(cache_path(e, repo)).read_text()).get('total_entries') == 9 and time.time() < deadline:
        time.sleep(0.1)
    check(json.loads(Path(cache_path(e, repo)).read_text())['total_entries'] == 3, 'a stale root marker is rescanned in the background')
    wait_idle(e, repo)
    os.unlink(cache_path(e, repo))
    os.unlink(marker)
    e.scratch('status', '--line', cwd=repo)
    deadline = time.time() + 15
    while not os.path.exists(cache_path(e, repo)) and time.time() < deadline:
        time.sleep(0.1)
    check(os.path.exists(cache_path(e, repo)), 'a missing marker is scanned in the background')
    wait_idle(e, repo)


# every repository

def two_repos_with_idle_entries(e: Env) -> tuple:
    e.skew = 20
    here, there = e.repo('here'), e.repo('there')
    mine, theirs = e.session_dir(here), e.session_dir(there)
    e.make(mine, 'old/f.txt', days=15)
    e.make(theirs, 'old/f.txt', days=15, body='x' * 1000)
    e.make(theirs, 'recent/f.txt', days=13)
    e.make(theirs, 'fresh.txt')
    return here, there, mine, theirs


@test
def the_scan_covers_every_repository(e: Env):
    here, there, mine, theirs = two_repos_with_idle_entries(e)
    e.scratch('__scan', cwd=here)
    check(not os.path.exists(f'{mine}/old') and not os.path.exists(f'{theirs}/old'), 'a scan started in one repository trashes every repository\'s idle entry')
    check(os.path.exists(f'{theirs}/recent/f.txt') and os.path.exists(f'{theirs}/fresh.txt'), 'an entry changed within 14 days stays')
    back = e.scratch('restore', f'{theirs}/old', cwd=there)
    check(back.returncode == 0 and os.path.exists(f'{theirs}/old/f.txt'), f'restore from inside that repository brings it back: {back.stderr}')
    check(e.scratch('restore', f'{theirs}/old', cwd=here).returncode != 0, 'the other repository does not restore it')


@test
def sweep_runs_the_scan_now_and_says_what_it_trashed(e: Env):
    here, there, mine, theirs = two_repos_with_idle_entries(e)
    e.scratch('__scan', cwd=here)  # the hourly limit now holds for the root
    e.make(theirs, 'later/f.txt', days=16)
    out = e.scratch('sweep', cwd=here)
    lines = out.stdout.strip().splitlines()
    named = [line for line in lines if line.startswith(os.path.basename(e.folder(there)) + '\t')]
    check(out.returncode == 0 and len(named) == 1 and f'{theirs}/later' in named[0] and 'idle 16 days' in named[0],
          f'sweep ignores the hourly limit and prints repo folder, path, size, idle days per entry: {out.stdout}{out.stderr}')
    check(not os.path.exists(f'{theirs}/later') and os.path.exists(f'{theirs}/recent/f.txt'), 'sweep applies the 14-day rule')
    again = e.scratch('sweep', cwd=here)
    check(again.returncode == 0 and again.stdout.strip() == 'nothing to sweep', f'an empty sweep says so: {again.stdout}')


@test
def sweep_skips_a_locked_repository_and_concurrent_scans_corrupt_nothing(e: Env):
    here, there, mine, theirs = two_repos_with_idle_entries(e)
    for i in range(30):
        e.make(mine, f'bulk{i}/f.txt', days=15)
        e.make(theirs, f'bulk{i}/f.txt', days=15)
    lock = f'{e.root}/.cache/{os.path.basename(e.folder(there))}/scan.lock'
    os.makedirs(lock)
    os.utime(lock, (e.clock(),) * 2)  # fresh by the test clock
    out = e.scratch('sweep', cwd=here)
    check(out.returncode == 0 and os.path.exists(f'{theirs}/old') and not os.path.exists(f'{mine}/old'),
          f'a repository under its scan lock is skipped, the others swept: {out.stdout}{out.stderr}')
    shutil.rmtree(lock)
    runs = [subprocess.Popen([sys.executable, '-B', SCRATCH, 'sweep'], cwd=here, env=e.environ(), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True) for _ in range(2)]
    results = [r.communicate(timeout=60) + (r.returncode,) for r in runs]
    check(all(r[2] == 0 for r in results), f'two sweeps together both exit 0: {results}')
    trash = [(repo, n) for repo in os.listdir(f'{e.root}/.trash') for n in os.listdir(f'{e.root}/.trash/{repo}')]
    check(len(trash) == 62 and len(set(trash)) == 62, f'every idle entry is trashed once: {len(trash)}')
    locks = [str(p) for p in Path(f'{e.root}/.cache').glob('*/scan.lock*')]
    check(not locks, f'no scan lock is left behind: {locks}')
    check(os.path.exists(f'{theirs}/recent/f.txt') and os.path.exists(f'{theirs}/fresh.txt'), 'recent entries stay')


# migrate

@test
def migrate_moves_scratch_folders(e: Env):
    repo = e.repo('proj')
    subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'x'],
                   cwd=repo, check=True, env=e.environ(False))
    tree = f'{repo}/.worktrees/wt'
    subprocess.run(['git', 'worktree', 'add', '-q', tree], cwd=repo, check=True, env=e.environ(False))
    main = f'{repo}/.scratch'
    e.make(main, 'topic/arc/f.txt', body='keep')
    os.symlink('f.txt', f'{main}/topic/arc/inside')
    os.symlink(f'{e.tmp}', f'{main}/topic/absolute')
    os.symlink('../../../outside-file', f'{main}/topic/arc/leaving')
    e.make(main, 'clash/main.txt')
    e.make(main, 'preexisting/f.txt')
    e.make(main, 'loose.txt')
    os.makedirs(f'{main}/emptyclash')
    os.makedirs(f'{e.folder(repo)}/shared/emptyclash')  # macOS rename would replace an empty directory
    e.make(f'{tree}/.scratch', 'wt-topic/f.txt')
    e.make(f'{tree}/.scratch', 'clash/wt.txt')
    e.make(f'{repo}/.worktrees/.scratch', 'stray/f.txt')
    folder = e.folder(repo)
    e.make(f'{e.scratch("dir", "--shared", "preexisting", cwd=repo).stdout.strip()}', 'mine.txt')
    stamp = os.lstat(f'{main}/topic/arc/f.txt').st_mtime
    out = e.scratch('migrate', cwd=repo, session=False)
    check(out.returncode == 0, out.stderr)
    shared = f'{folder}/shared'
    check(Path(f'{shared}/topic/arc/f.txt').read_text() == 'keep' and os.lstat(f'{shared}/topic/arc/f.txt').st_mtime == stamp,
          'folders move unchanged')
    check(os.readlink(f'{shared}/topic/arc/inside') == 'f.txt' and os.readlink(f'{shared}/topic/absolute') == e.tmp, 'links keep their text')
    check(os.path.exists(f'{shared}/wt-topic/f.txt') and os.path.exists(f'{shared}/stray/f.txt'), 'worktree and stray .scratch move too')
    check(Path(f'{shared}/clash/main.txt').exists() and Path(f'{tree}/.scratch/clash/wt.txt').exists(), 'the first clash winner moves, the other stays')
    check(Path(f'{main}/preexisting/f.txt').exists() and Path(f'{shared}/preexisting/mine.txt').exists(), 'an existing shared folder is not merged')
    check(Path(f'{main}/loose.txt').exists(), 'loose files stay')
    check(os.path.isdir(f'{main}/emptyclash'), 'a clash with an empty folder is still a clash')
    for needle in (f'{tree}/.scratch/clash', f'{main}/preexisting', f'{main}/emptyclash', f'{main}/loose.txt', f'{shared}/topic/arc/leaving'):
        check(needle in out.stdout, f'{needle} must be listed:\n{out.stdout}')
    check(f'{shared}/topic/arc/inside' not in out.stdout and f'{shared}/topic/absolute' not in out.stdout, 'working links are not listed')
    check(not os.path.exists(f'{repo}/.worktrees/.scratch'), 'an emptied .scratch is removed')
    again = e.scratch('migrate', cwd=repo, session=False)
    check('moved ' not in again.stdout, f'a second run moves nothing:\n{again.stdout}')


@test
def migrate_runs_the_expiry_scan_at_once(e: Env):
    e.skew = 20
    repo = e.repo('proj')
    main = f'{repo}/.scratch'
    e.make(main, 'stale/f.txt', days=20, body='x' * 3000)
    e.make(main, 'recent/f.txt')
    out = e.scratch('migrate', cwd=repo, session=False)
    shared = f'{e.folder(repo)}/shared'
    check(out.returncode == 0, out.stderr)
    check(not os.path.exists(f'{shared}/stale') and os.path.exists(f'{shared}/recent/f.txt'),
          'the old folder is trashed, the recent one stays in shared/')
    row = next((l for l in lines(out) if l.startswith('trashed ')), '')
    columns = row.split('\t')
    check(len(columns) == 4 and columns[0] == 'trashed stale' and 'KB' in columns[1] and columns[2] == 'idle 20 days'
          and columns[3] == f'{shared}/stale', f'trashed row: {out.stdout!r}')
    check('scratch restore <name' in out.stdout and '7 days' in out.stdout, f'restore hint: {out.stdout!r}')
    check('recent' not in ''.join(l for l in lines(out) if l.startswith('trashed ')), 'only the old one is reported')
    check(e.scratch('restore', 'stale', cwd=repo).returncode == 0 and os.path.exists(f'{shared}/stale/f.txt'), 'it restores')


@test
def migrate_finds_nested_scratch_folders(e: Env):
    repo = e.repo('proj')
    subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'x'],
                   cwd=repo, check=True, env=e.environ(False))
    tree = f'{repo}/.worktrees/wt'
    subprocess.run(['git', 'worktree', 'add', '-q', tree], cwd=repo, check=True, env=e.environ(False))
    outside = f'{e.tmp}/wt-elsewhere'  # a worktree outside the main tree is found through the worktree list
    subprocess.run(['git', 'worktree', 'add', '-q', outside, '-b', 'other'], cwd=repo, check=True, env=e.environ(False))
    e.make(f'{repo}/.scratch', 'clash/root.txt')
    e.make(f'{repo}/base/.scratch', 'clash/nested.txt')
    e.make(f'{repo}/base/.scratch', 'only-nested/f.txt')
    e.make(f'{tree}/deep/er/.scratch', 'in-worktree/f.txt')
    e.make(f'{outside}/sub/.scratch', 'in-outside/f.txt')
    e.make(f'{repo}/.scratch/keep/.scratch', 'inner/f.txt')  # a .scratch inside a .scratch is content
    e.make(f'{repo}/node_modules/pkg/.scratch', 'dep/f.txt')
    e.make(f'{repo}/.git/hooks/.scratch', 'git/f.txt')
    real = f'{e.tmp}/linked-target'
    e.make(f'{real}/.scratch', 'via-link/f.txt')
    os.symlink(real, f'{repo}/linkdir')
    out = e.scratch('migrate', cwd=repo, session=False)
    shared = f'{e.folder(repo)}/shared'
    check(out.returncode == 0, out.stderr)
    for name in ('clash', 'only-nested', 'in-worktree', 'in-outside', 'keep'):
        check(os.path.isdir(f'{shared}/{name}'), f'{name} moved:\n{out.stdout}')
    check(os.path.exists(f'{shared}/keep/.scratch/inner/f.txt'), 'the inner .scratch moved as content of keep')
    check(Path(f'{shared}/clash/root.txt').exists() and Path(f'{repo}/base/.scratch/clash/nested.txt').exists(),
          'the shallower source wins a clash, the other stays')
    check(f'{repo}/base/.scratch/clash' in out.stdout and 'name clash' in out.stdout, f'the clash names its source:\n{out.stdout}')
    check(f'moved {repo}/base/.scratch/only-nested ->' in out.stdout, f'a moved entry shows its source:\n{out.stdout}')
    check(os.path.exists(f'{repo}/node_modules/pkg/.scratch/dep/f.txt') and os.path.exists(f'{repo}/.git/hooks/.scratch/git/f.txt'),
          'node_modules and .git are not walked')
    check(os.path.exists(f'{real}/.scratch/via-link/f.txt') and not os.path.exists(f'{shared}/via-link'), 'symlinks are not followed')
    check(f'{repo}/.scratch/keep/.scratch' not in out.stdout and 'skipped (not a plain folder' not in out.stdout,
          f'a .scratch inside a .scratch is no source, no folder is a source twice:\n{out.stdout}')
    check(out.stdout.count('moved ') == 5, f'each entry moves once (no double count through the worktree list):\n{out.stdout}')


@test
def migrate_does_not_follow_a_symlinked_scratch(e: Env):
    repo = e.repo('proj')
    elsewhere = f'{e.tmp}/elsewhere'
    e.make(elsewhere, 'topic/f.txt')
    os.symlink(elsewhere, f'{repo}/.scratch')
    out = e.scratch('migrate', cwd=repo, session=False)
    check(os.path.exists(f'{elsewhere}/topic/f.txt') and f'{repo}/.scratch' in out.stdout, f'not followed, but listed: {out.stdout}')
    check(not os.path.exists(f'{e.folder(repo)}/shared/topic'), 'nothing is moved out of a linked .scratch')


@test
def trash_dot_named_entry_restores_and_purges(e: Env):
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    e.make(mine, '.venv/f.txt', body='v')
    entry = e.scratch('trash', f'{mine}/.venv', cwd=repo).stdout.strip()
    check(entry and not os.path.basename(entry).startswith('.'), f'a trash name never starts with a dot: {entry!r}')
    check(Path(f'{entry}/origin').read_text().strip() == f'{mine}/.venv', 'the origin keeps the dot name')
    check(os.path.basename(entry) in e.scratch('restore', cwd=repo).stdout, 'the dot entry is listed')
    for name in ('.venv', 'venv'):
        out = e.scratch('restore', name, cwd=repo)
        check(out.returncode == 0 and Path(f'{mine}/.venv/f.txt').read_text() == 'v', f'restore {name!r}: {out.stderr!r}')
        entry = e.scratch('trash', f'{mine}/.venv', cwd=repo).stdout.strip()
    entry = age_entry(entry, 8)
    e.scratch('list', cwd=repo)
    check(not os.path.exists(entry) and e.scratch('restore', cwd=repo).stdout == '', 'a dot entry is purged after seven days')


@test
def session_actor_comes_from_the_registry_for_codex(e: Env):
    repo = e.repo('proj')
    codex = {'CODEX_SESSION_ID': 'sess-0003-codex001', 'CODEX_THREAD_ID': 'thread-0003-thread01'}
    out = e.scratch('dir', cwd=repo, session=False, **codex)
    check(out.returncode == 0 and out.stdout.strip() == f'{e.folder(repo)}/sessions/codex001', f'{out.stdout!r} {out.stderr!r}')
    same = e.scratch('dir', cwd=repo, session=False, CODEX_SESSION_ID='sess-0003-codex001')
    check(same.stdout == out.stdout, 'a Codex thread shares its session folder')
    alone = e.scratch('dir', cwd=repo, session=False, CODEX_THREAD_ID='thread-0003-thread01')
    check(alone.returncode == 2, 'a thread id without a session id is no session (as the registry judges)')


@test
def races_and_unreadable_folders_end_in_messages(e: Env):
    repo = e.repo('proj')
    mine = e.session_dir(repo)
    # restore: the origin cannot be recreated
    e.make(mine, 'x/f.txt')
    entry = e.scratch('trash', f'{mine}/x', cwd=repo).stdout.strip()
    Path(f'{entry}/origin').write_text(f'{mine}/blocker/x\n')
    Path(f'{mine}/blocker').write_text('a file where a folder is needed')
    out = e.scratch('restore', os.path.basename(entry), cwd=repo)
    check(out.returncode == 2 and 'Traceback' not in out.stderr and os.path.exists(f'{entry}/data'), f'restore: {out.returncode} {out.stderr!r}')
    # restore: the entry vanished between listing and moving (a purge took it)
    shutil.rmtree(entry)
    check(e.scratch('restore', os.path.basename(entry), cwd=repo).returncode == 2, 'a vanished entry is refused')
    # over-long names
    long_name = 'n' * 255
    e.make(mine, long_name, body='keep')
    first = e.scratch('trash', f'{mine}/{long_name}', cwd=repo)
    check(first.returncode == 0, f'a 255-character name fits the trash: {first.stderr!r}')
    e.make(mine, long_name, body='keep')
    out = e.scratch('trash', f'{mine}/{long_name}', cwd=repo)  # the -2 suffix does not fit
    check(out.returncode == 2 and 'Traceback' not in out.stderr and os.path.exists(f'{mine}/{long_name}'), f'long name: {out.stderr!r}')
    out = e.scratch('dir', '--shared', 'n' * 300, cwd=repo)
    check(out.returncode == 2 and 'Traceback' not in out.stderr, f'long --shared: {out.stderr!r}')
    if os.geteuid() == 0:
        return
    # an unreadable session folder is skipped, the rest is listed
    e.make(mine, 'seen/f.txt')
    hidden = f'{e.folder(repo)}/sessions/hidden0'
    e.make(hidden, 'f.txt')
    os.chmod(hidden, 0)
    try:
        out = e.scratch('list', cwd=repo)
        check(out.returncode == 0 and 'Traceback' not in out.stderr and f'{mine}/seen' in out.stdout and 'hidden0' in out.stderr,
              f'list: {out.returncode} {out.stdout!r} {out.stderr!r}')
    finally:
        os.chmod(hidden, 0o700)
    # migrate: an unreadable folder inside a moved folder does not stop the run
    main = f'{repo}/.scratch'
    e.make(main, 'topic/locked/f.txt')
    e.make(main, 'second/f.txt')
    os.chmod(f'{main}/topic/locked', 0)
    try:
        out = e.scratch('migrate', cwd=repo, session=False)
        check(out.returncode == 0 and 'Traceback' not in out.stderr and 'second' in out.stdout
              and os.path.isdir(f'{e.folder(repo)}/shared/second'), f'migrate: {out.stdout!r} {out.stderr!r}')
        check('locked' in out.stdout, f'the unchecked folder is named: {out.stdout!r}')
    finally:
        for top, dirs, _ in os.walk(e.folder(repo)):
            for d in dirs:
                os.chmod(os.path.join(top, d), 0o700)


@test
def migrate_lists_absolute_links_into_the_moved_scratch(e: Env):
    repo = e.repo('proj')
    main = f'{repo}/.scratch'
    e.make(main, 'topic/f.txt')
    e.make(main, 'other/f.txt')
    e.make(main, 'kept/f.txt')
    os.makedirs(f'{e.folder(repo)}/shared/kept')  # a clash: kept stays in .scratch
    os.symlink(f'{main}/other/f.txt', f'{main}/topic/into-moved')
    os.symlink(f'{main}/kept/f.txt', f'{main}/topic/into-staying')
    os.symlink('../other/f.txt', f'{main}/topic/sibling')
    os.symlink(f'{main}/gone.txt', f'{main}/topic/dangling')
    out = e.scratch('migrate', cwd=repo, session=False)
    shared = f'{e.folder(repo)}/shared'
    check(out.returncode == 0, out.stderr)
    check(f'{shared}/topic/into-moved' in out.stdout, f'an absolute link into a moved folder is listed:\n{out.stdout}')
    for name in ('into-staying', 'sibling', 'dangling'):
        check(f'{shared}/topic/{name}' not in out.stdout, f'{name} still works or was already broken:\n{out.stdout}')


def main() -> int:
    wanted = [n for n in OPTIONS.only.split(',') if n] or list(TESTS)
    unknown = [n for n in wanted if n not in TESTS]
    if unknown:
        print(f'unknown tests: {unknown}', file=sys.stderr)
        return 2
    failed = 0
    for name in wanted:
        tmp = tempfile.mkdtemp(prefix='test-scratch.')
        try:
            TESTS[name](Env(tmp))
            print(f'ok   {name}')
        except Exception:
            failed += 1
            print(f'FAIL {name}\n{traceback.format_exc()}')
        finally:
            time.sleep(0.05)
            shutil.rmtree(tmp, ignore_errors=True)
    print(f'{len(wanted) - failed} passed, {failed} failed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
