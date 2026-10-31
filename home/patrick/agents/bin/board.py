#!/usr/bin/env python3
"""board: the agents' interface to a beads board (bd 1.3.1).

Run inside the repository. Views, `board show` and the write helpers read one
`bd export` snapshot; `board bd <args>` runs any other bd command (raw item
reads excepted: `board show` renders them within the read budget). Every bd call carries the caller's
actor (`derived_actor`) and, on a server-mode board, finds the server running.

Routing: skills/shared/board-core.md#routing; `ROLE_KINDS` and `Board.kind`
implement it.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import re
import shutil
import shlex
import socket
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

IDLE_HOURS = 1  # holds without activity (holder's tool call, else item update) for longer are hinted as idle
WORKER_CAP = 6  # concurrent workers per session; a Codex session's agents thread limits lower it
WORKER_ACTIVE_MINUTES = 15  # a running worker with a tool call this recently counts as active
CODEX_SYSTEM_CONFIG = Path('/etc/codex/config.toml')  # Codex's system layer, under $CODEX_HOME/config.toml
CAPACITY_ROLES = ('agent', 'solo', 'autopilot')  # roles that dispatch workers
WORKER_KINDS = ('design', 'implement', 'review')  # kinds workers take; an agent's pulls narrow them
ROWS = 50  # rows per view section unless --limit (0: all)
READ_BUDGET = 35_000  # characters per command output; Codex cuts a call's output above ~40,000 from the middle
PREVIEW = 600  # characters a cut section still prints
SHOWN_COMMENTS = 3
SESSION_HOURS = 24  # position lists sessions registered this recently (plus any holding items)
PULLS = ('plan', 'design', 'implement', 'review')
KINDS = (*PULLS, 'question', 'accept', 'ratify', 'milestone')
WORK_TYPES = ('task', 'bug', 'spike')
# Kinds a bare `board claim` takes per role (agent: its pulls).
ROLE_KINDS = {'lead': ('question',), 'agent': None, 'solo': ('question', 'plan', 'ratify', 'accept'),
              'autopilot': ('question', 'plan', 'accept')}
# Kinds each role handles, by bare claim or by id; `board position` counts sessions from these.
# A ready milestone is accepted with the user: claimed by id only, never by autopilot.
ROLE_HANDLES = {'lead': ('question', 'accept', 'ratify', 'milestone'), 'agent': None,
                'solo': ('question', 'plan', 'ratify', 'accept', 'milestone'), 'autopilot': ('question', 'plan', 'accept')}
TEXT_FIELDS = ('title', 'description', 'design', 'acceptance_criteria', 'notes', 'close_reason')
SHOW_FIELDS = TEXT_FIELDS[1:]
# A decision record's `##` sections (board-coordination.md#rulings). bd lint accepts the words anywhere in the text,
# so board checks the headings itself.
RECORD_SECTIONS = ('Question', 'Alternatives Considered', 'Decision', 'Rationale', 'Rule owner')
# A pending revision is a `tracks` edge from the new decision to the record it revises: bd 1.3.1 rejects custom
# dependency types, `tracks` never blocks, no other board use exists, and `supersede` replaces the pair's edge, so the
# link lives exactly until release. The partial rule's name sits in the new record's metadata.
REVISES = 'tracks'
REVISES_RULE = 'board.revises_rule'
REGISTRY = Path(__file__).resolve().parent / 'session-lead-mode.sh'


class BoardError(Exception):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


_actors: dict[tuple, str | None] = {}


def derived_actor() -> str | None:
    """BEADS_ACTOR (bd-guard sets it for Claude subagents), else the session's actor."""
    actor = os.environ.get('BEADS_ACTOR', '').strip()
    if actor:
        return actor
    key = tuple(os.environ.get(name, '') for name in ('CODEX_SESSION_ID', 'CODEX_THREAD_ID', 'CLAUDE_CODE_SESSION_ID'))
    if key not in _actors:
        result = subprocess.run(['bash', str(REGISTRY), 'actor'], capture_output=True, text=True)
        _actors[key] = result.stdout.strip() if result.returncode == 0 else None
    return _actors[key]


def bd_env() -> dict[str, str]:
    actor = derived_actor()
    return {**os.environ, **({'BEADS_ACTOR': actor} if actor else {})}


_server_checked = False


def ensure_server(start: Path | None = None) -> None:
    """Start a stopped server of a server-mode board; bd's own auto-start is off."""
    global _server_checked
    if _server_checked:
        return
    _server_checked = True
    start = (start or Path.cwd()).resolve()
    root = next((d for d in (start, *start.parents) if (d / '.beads' / 'metadata.json').is_file()), None)
    if root is None:
        return
    beads = root / '.beads'
    try:
        if json.loads((beads / 'metadata.json').read_text(encoding='utf-8')).get('dolt_mode') != 'server':
            return
        port = int((beads / 'dolt-server.port').read_text(encoding='utf-8').strip())
        socket.create_connection(('127.0.0.1', port), timeout=1).close()
        return
    except (OSError, ValueError):
        pass
    if os.environ.get('CODEX_SANDBOX'):
        raise BoardError('the board server is unreachable from this sandbox: rerun with elevated sandbox permissions')
    subprocess.run(['bd', 'dolt', 'start'], cwd=root, capture_output=True, env=bd_env())


def bd(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    ensure_server()
    return subprocess.run(['bd', *args], input=stdin, capture_output=True, text=True, env=bd_env())


def bd_checked(*args: str, stdin: str | None = None) -> str:
    result = bd(*args, stdin=stdin)
    if result.returncode != 0:
        raise BoardError(f"`bd {' '.join(args)}` failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def registrations() -> list[dict]:
    result = subprocess.run(['bash', str(REGISTRY), 'list'], capture_output=True, text=True)
    if result.returncode != 0:
        raise BoardError(f'session registry unreadable: {result.stderr.strip()}')
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def parse_time(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def age(moment: datetime | None) -> str:
    if moment is None:
        return 'age unknown'
    minutes = int((utcnow() - moment).total_seconds() // 60)
    if minutes < 120:
        return f'{minutes} min'
    if minutes < 48 * 60:
        return f'{minutes // 60} h'
    return f'{minutes // 1440} d'


def session_actor(actor: str) -> str:
    return actor.split('/', 1)[0]


_processes: dict[int, str | None] = {}  # pid -> start time, 'GONE', or None (unknown); per run


def holder_worker(holder: str) -> str | None:
    """The holding worker's marker name (its id's last 8 characters), None for a session hold."""
    return holder.split('/', 1)[1][-8:] if '/' in holder else None


def hooks_live(entry: dict | None) -> bool:
    """The session's activity hooks run: its own activity file exists. Without it, a missing worker marker or a
    marker's age proves nothing (a worker spawned before the hooks, or hooks not yet trusted)."""
    return bool(entry and entry.get('active_at'))


def worker_stopped(entry: dict | None, issue: dict) -> bool:
    """The holding worker has no running marker, and the session's own activity is newer than the item's
    `updated_at`: every claim updates it (later updates only raise it), so the hooks ran after this claim and a
    running worker would have a marker. Not `started_at`: it can predate the hold (a reclaim, a reviewer's claim).
    Only its owning session (`board mine`) acts on it: only the owner knows whether it continues the worker."""
    worker = holder_worker(issue.get('assignee') or '')
    if not (entry and worker) or worker in (entry.get('workers') or {}):
        return False
    active, claimed = parse_time(entry.get('active_at')), parse_time(issue.get('updated_at'))
    return bool(active and claimed and active > claimed)


def holder_activity(entry: dict | None, holder: str) -> datetime | None:
    """The holder's last tool call: a running worker's marker, else (a session hold, a stopped worker) the session's
    own; None without activity data (the session's hooks not live)."""
    if not hooks_live(entry):
        return None
    worker = holder_worker(holder)
    moment = parse_time((entry.get('workers') or {}).get(worker)) if worker else None
    return moment or parse_time(entry.get('active_at'))


def active_workers(entry: dict | None) -> list[str]:
    """The session's running workers with a tool call within WORKER_ACTIVE_MINUTES."""
    since = utcnow() - timedelta(minutes=WORKER_ACTIVE_MINUTES)
    return [worker for worker, moment in ((entry or {}).get('workers') or {}).items()
            if (parse_time(moment) or since) > since]


def worker_cap(entry: dict) -> int:
    """WORKER_CAP, lowered for a Codex session by the effective `agents.max_threads` or
    `agents.max_concurrent_threads_per_session`: Codex's layers, the system config (CODEX_SYSTEM_CONFIG; tests set
    AGENT_CODEX_SYSTEM_CONFIG) overridden per key by `$CODEX_HOME/config.toml` (default ~/.codex)."""
    cap = WORKER_CAP
    if entry.get('tool') != 'codex':
        return cap
    layers = (Path(os.environ.get('AGENT_CODEX_SYSTEM_CONFIG') or CODEX_SYSTEM_CONFIG),
              Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'config.toml')
    agents: dict = {}
    for path in layers:
        try:
            layer = tomllib.loads(path.read_text(encoding='utf-8')).get('agents')
        except (OSError, ValueError):  # a missing or unreadable layer sets nothing
            continue
        agents.update(layer if isinstance(layer, dict) else {})
    for key in ('max_threads', 'max_concurrent_threads_per_session'):
        value = agents.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            cap = min(cap, value)
    return cap


def process_started(pid: int) -> str | None:
    """The process's start time as `ps -o lstart=` prints it in UTC (whitespace-normalized; session-lead-mode
    stores the same form), or None when ps fails for any reason."""
    try:
        result = subprocess.run([shutil.which('ps') or '/bin/ps', '-o', 'lstart=', '-p', str(pid)], capture_output=True,
                                text=True, env={**os.environ, 'LC_ALL': 'C', 'TZ': 'UTC0'})
    except OSError:
        return None
    started = ' '.join(result.stdout.split())
    return started if result.returncode == 0 and started else None


def liveness(entry: dict | None) -> str | None:
    """'GONE' when the session's registered pid no longer exists or now names a process started at another
    time, 'alive' when it matches, None when unknown (no entry, no pid, ps failed): unknown keeps the idle hint."""
    if entry is None:
        return None
    pid, started = entry.get('pid'), entry.get('pid_started')
    if not isinstance(pid, int) or pid <= 1 or not isinstance(started, str):
        return None
    if pid not in _processes:
        try:
            os.kill(pid, 0)
            _processes[pid] = process_started(pid)
        except ProcessLookupError:
            _processes[pid] = 'GONE'
        except PermissionError:  # exists, owned by another user
            _processes[pid] = process_started(pid)
        except OSError:
            _processes[pid] = None
    current = _processes[pid]
    if current is None:
        return None
    return 'GONE' if current == 'GONE' or current != ' '.join(started.split()) else 'alive'


class Board:
    def __init__(self, issues: list[dict]):
        self.issues = issues
        self._milestone_work: dict[str, set[str]] = {}
        self._in_milestone: dict[str, list[str]] | None = None
        self.by_id = {issue['id']: issue for issue in issues}
        self.parent: dict[str, str] = {}
        self.children: dict[str, list[str]] = {}
        self.blockers: dict[str, list[str]] = {}  # waiting id -> ids it waits on
        self.dependents: dict[str, list[str]] = {}  # blocker id -> waiting ids
        self.linked: dict[str, set[str]] = {}  # id -> ids sharing any non-parent edge
        self.related: dict[str, set[str]] = {}  # relates-to, both ends
        self.edges: dict[str, list[tuple[str, str, bool]]] = {}  # id -> (other id, type, outgoing)
        for issue in issues:
            for dep in issue.get('dependencies') or []:
                waiting, target, kind = dep['issue_id'], dep['depends_on_id'], dep['type']
                self.edges.setdefault(waiting, []).append((target, kind, True))
                self.edges.setdefault(target, []).append((waiting, kind, False))
                if kind == 'parent-child':
                    self.parent[waiting] = target
                    self.children.setdefault(target, []).append(waiting)
                    continue
                self.linked.setdefault(waiting, set()).add(target)
                self.linked.setdefault(target, set()).add(waiting)
                if kind == 'blocks':
                    self.blockers.setdefault(waiting, []).append(target)
                    self.dependents.setdefault(target, []).append(waiting)
                elif kind in ('relates-to', 'related'):
                    self.related.setdefault(waiting, set()).add(target)
                    self.related.setdefault(target, set()).add(waiting)

    @classmethod
    def load(cls) -> 'Board':
        lines = bd_checked('export').splitlines()
        return cls([issue for issue in map(json.loads, filter(str.strip, lines)) if issue.get('_type', 'issue') == 'issue'])

    def ancestors(self, item_id: str):
        seen = set()
        while item_id in self.parent and item_id not in seen:
            seen.add(item_id)
            item_id = self.parent[item_id]
            yield item_id

    def scoped(self, root: str | None) -> list[dict]:
        if root is None:
            return self.issues
        if root not in self.by_id:
            raise BoardError(f'unknown root {root}')
        if self.by_id[root].get('issue_type') == 'milestone':
            work = self.milestone_work(root) | {root}
            return [issue for issue in self.issues if issue['id'] in work]
        return [issue for issue in self.issues if root in self.ancestors(issue['id'])]

    def milestone_work(self, milestone_id: str) -> set[str]:
        """Open items the milestone waits on (board-coordination.md#milestones): its open blockers, the open
        descendants of every reached epic, and transitively the open blockers of every reached item."""
        if milestone_id not in self._milestone_work:
            work: set[str] = set()
            visited: set[tuple[str, bool]] = set()  # an item reached as a blocker may be reached again as a descendant
            pending = [(blocker, False) for blocker in self.blockers.get(milestone_id, [])]
            while pending:
                visit = pending.pop()
                item_id, descendant = visit
                if visit in visited or not self.is_open(item_id):
                    continue
                visited.add(visit)
                work.add(item_id)
                pending += [(blocker, False) for blocker in self.blockers.get(item_id, [])]
                if descendant or self.by_id[item_id].get('issue_type') == 'epic':
                    pending += [(child, True) for child in self.children.get(item_id, [])]
            self._milestone_work[milestone_id] = work
        return self._milestone_work[milestone_id]

    def milestones(self) -> list[dict]:
        return [issue for issue in self.issues if issue.get('issue_type') == 'milestone' and issue['status'] != 'closed']

    @property
    def in_milestone(self) -> dict[str, list[str]]:
        """Item id -> the open milestones it is work of."""
        if self._in_milestone is None:
            self._in_milestone = {}
            for milestone in self.milestones():
                for item_id in self.milestone_work(milestone['id']):
                    self._in_milestone.setdefault(item_id, []).append(milestone['id'])
        return self._in_milestone

    def between(self, a: str, b: str) -> list[tuple[str, str, str]]:
        """(from, to, type) of every edge between the pair, either direction."""
        return [(a, other, kind) if outgoing else (other, a, kind) for other, kind, outgoing in self.edges.get(a, [])
                if other == b]

    def revises(self, item_id: str) -> list[str]:
        """Records a decision revises (pending until release)."""
        if self.by_id.get(item_id, {}).get('issue_type') != 'decision':
            return []
        return [other for other, kind, outgoing in self.edges.get(item_id, []) if outgoing and kind == REVISES]

    def is_open(self, item_id: str) -> bool:
        return item_id in self.by_id and self.by_id[item_id]['status'] != 'closed'

    def open_blockers(self, item_id: str) -> list[str]:
        # A blocker missing from the snapshot counts as open (fail closed);
        # `external:` references never block in bd 1.3.1.
        return [blocker for blocker in self.blockers.get(item_id, [])
                if self.is_open(blocker) or (blocker not in self.by_id and not blocker.startswith('external:'))]

    def kind(self, issue: dict) -> str | None:
        status, kind = issue['status'], issue.get('issue_type')
        if kind == 'decision':
            return {'released': 'plan', 'open': 'question', 'needs_ratification': 'ratify'}.get(status)
        if status == 'in_review':
            return 'review' if kind in WORK_TYPES else 'accept' if kind == 'design' else None
        if status != 'open':
            return None
        if kind in ('design', 'milestone'):
            return kind
        return 'implement' if kind in WORK_TYPES else None

    def claimable(self, issue: dict) -> str | None:
        kind = self.kind(issue)
        if kind is None or issue.get('assignee') or self.open_blockers(issue['id']):
            return None
        return kind

    def downstream(self, item_id: str) -> int:
        seen: set[str] = set()
        pending = [item_id]
        while pending:
            for waiting in self.dependents.get(pending.pop(), []):
                if waiting not in seen and self.is_open(waiting):
                    seen.add(waiting)
                    pending.append(waiting)
        return len(seen)

    def last_activity(self, issue: dict) -> datetime | None:
        moments = [parse_time(issue.get('updated_at'))]
        moments += [parse_time(comment.get('created_at')) for comment in issue.get('comments') or []]
        moments = [moment for moment in moments if moment is not None]
        return max(moments) if moments else None

    def text(self, issue: dict) -> str:
        parts = [str(issue.get(field) or '') for field in TEXT_FIELDS]
        parts += issue.get('labels') or []
        parts += [comment.get('text') or '' for comment in issue.get('comments') or []]
        return '\n'.join(parts)


def line(issue: dict, *extra: str) -> str:
    fields = [issue['id'], issue['status'], issue.get('issue_type', ''), *extra]
    return '  ' + '  '.join(field for field in fields if field) + f"  {issue.get('title', '')}"


def section(title: str, rows: list[str], limit: int | None = None) -> None:
    print(f'{title}: {len(rows)}')
    shown = rows[:limit] if limit else rows  # None or 0: every row
    for row in shown:
        print(row)
    if len(shown) < len(rows):
        print(f'  ... {len(rows) - len(shown)} more')


def by_priority(issue: dict):
    return (issue.get('priority', 9), issue.get('created_at') or '', issue['id'])


def claim_order(board: Board, issue: dict):
    # P0 first, then milestone work (board-coordination.md#milestones), each by priority; at equal priority
    # a released ruling goes first: it blocks the work it changes until planned.
    priority, created, item_id = by_priority(issue)
    return (priority != 0, item_id not in board.in_milestone, priority, board.kind(issue) != 'plan', created, item_id)


# Views

HEALTH_VIEWS = ('questions', 'decided', 'ratification', 'released', 'review', 'user', 'ready', 'held', 'blocked',
                'outside', 'labels')
LIFECYCLE_LABELS = ('human', 'decided', 'review', 'needs-ratification', 'waiting')


def health(board: Board, args) -> None:
    items = [issue for issue in board.scoped(args.root) if issue['status'] != 'closed' and issue.get('issue_type') != 'epic']
    decisions = [issue for issue in items if issue.get('issue_type') == 'decision']

    def epic_of(issue):
        return next((a for a in board.ancestors(issue['id']) if board.by_id.get(a, {}).get('issue_type') == 'epic'), None)

    views = {
        'questions': ('open questions', [i for i in decisions if i['status'] in ('open', 'in_progress')]),
        'decided': ('decided, not released', [i for i in decisions if i['status'] == 'decided']),
        'ratification': ('awaiting ratification', [i for i in items if i['status'] == 'needs_ratification']),
        'released': ('released rulings to plan', [i for i in decisions if i['status'] == 'released']),
        'review': ('in review', [i for i in items if i['status'] == 'in_review']),
        'user': ('waiting on the user (gates titled user, items assigned to user)',
                 [i for i in items if (i.get('issue_type') == 'gate' and i.get('title', '').startswith('user '))
                  or i.get('assignee') == 'user']),
        'ready': ('claimable now (unassigned, unblocked)', [i for i in items if board.claimable(i)]),
        'held': ('held (assigned, not closed)', [i for i in items if i.get('assignee')]),
        'blocked': ('waiting on open blockers', [i for i in items if board.open_blockers(i['id'])]),
        'outside': ('outside any epic', [i for i in items if epic_of(i) is None and i.get('issue_type') != 'gate']),
        'labels': ('lifecycle labels (use statuses, assignment or blocks)',
                   [i for i in items if set(i.get('labels') or []) & set(LIFECYCLE_LABELS)]),
    }
    for view, (name, rows) in views.items():
        print(f'{name}: {len(rows)}')
        if view == 'ready':
            counts = {kind: sum(1 for i in rows if board.claimable(i) == kind) for kind in KINDS}
            print('  by kind: ' + ', '.join(f'{pull} {count}' for pull, count in counts.items()))
        if view in args.items:
            listed = [line(issue, issue.get('assignee') or '') for issue in sorted(rows, key=by_priority)]
            for row in listed[:args.limit] if args.limit else listed:
                print(row)
            if args.limit and len(listed) > args.limit:
                print(f'  ... {len(listed) - args.limit} more')
    scope = {issue['id'] for issue in board.scoped(args.root)}
    for milestone in (m for m in board.milestones() if m['id'] in scope):
        work = [board.by_id[item_id] for item_id in board.milestone_work(milestone['id'])]
        work = [issue for issue in work if issue.get('issue_type') != 'epic']
        state = 'not ready' if board.open_blockers(milestone['id']) else 'ready'
        print(f"milestone {milestone['id']} ({milestone.get('title', '')}): open work {len(work)}, "
              f"ready {sum(1 for i in work if board.claimable(i))}, held {sum(1 for i in work if i.get('assignee'))}, "
              f"blocked {sum(1 for i in work if board.open_blockers(i['id']))}; milestone {state}")
    found = deviations(board, args.root)
    if found:
        stuck = sum(1 for _, kind, _ in found if kind == 'review-blocked')  # fixed by board return, not a migration
        hints = (['run /board-migrate'] if stuck < len(found) else []) + ([f'{stuck} in review while blocked: board check'] if stuck else [])
        print(f"convention deviations: {len(found)} — {'; '.join(hints)}")


def registry_by_actor(entries: list[dict]) -> dict[str, dict]:
    known: dict[str, dict] = {}
    for entry in sorted(entries, key=lambda e: e.get('registered_at') or ''):
        known[entry.get('actor') or ''] = entry
    return known


def holder_label(holder: str, known: dict[str, dict]) -> str:
    entry = known.get(session_actor(holder))
    if entry is None:
        return holder
    pulls = f" {'+'.join(entry.get('pulls') or [])}" if entry.get('pulls') else ''
    return f"{holder} ({entry.get('role')}{pulls}, {entry.get('tool') or 'tool unknown'})"


def position(board: Board, args) -> None:
    items = [issue for issue in board.scoped(args.root) if issue['status'] != 'closed']
    entries = registrations()
    known = registry_by_actor(entries)
    now = utcnow()

    ready = [issue for issue in items if board.claimable(issue)]
    held = sorted((issue for issue in items if issue.get('assignee') and issue.get('issue_type') != 'epic'),
                  key=lambda issue: (issue['assignee'], by_priority(issue)))
    holding = {session_actor(issue['assignee']) for issue in held}
    sessions = [entry for entry in known.values()
                if entry.get('actor') in holding
                or (parse_time(entry.get('registered_at')) or now) > now - timedelta(hours=SESSION_HOURS)]

    print('ready work by kind vs sessions handling it:')
    for kind in KINDS:
        work = sum(1 for issue in ready if board.claimable(issue) == kind)
        pulling = sum(1 for entry in sessions if kind in session_kinds(entry, ROLE_HANDLES))
        print(f'  {kind}: {work} ready, {pulling} sessions')
    limit = args.limit
    section(f'sessions (registered within {SESSION_HOURS} h or holding items)',
            [f"  {entry.get('actor')}  {entry.get('role')}  {entry.get('tool') or 'tool unknown'}"
             f"  handles {','.join(session_kinds(entry, ROLE_HANDLES)) or '-'}  registered {age(parse_time(entry.get('registered_at')))} ago"
             f"  holds {sum(1 for issue in held if session_actor(issue['assignee']) == entry.get('actor'))}"
             f"  workers {len(active_workers(entry))}/{worker_cap(entry)}"
             + {'alive': '  process alive', 'GONE': '  GONE'}.get(liveness(entry) or '', '')
             for entry in sessions], limit)

    idle, gone = [], []
    rows = []
    for issue in held:
        entry = known.get(session_actor(issue['assignee']))
        updated = board.last_activity(issue)
        recorded = holder_activity(entry, issue['assignee'])
        activity = recorded or updated
        state = liveness(entry)
        is_idle = state != 'GONE' and (activity is None or (now - activity).total_seconds() > IDLE_HOURS * 3600)
        marker = ' GONE' if state == 'GONE' else ' IDLE' if is_idle else ''
        rows.append(line(issue, holder_label(issue['assignee'], known), f'updated {age(updated)} ago'
                         + (f', active {age(recorded)} ago' if recorded else '') + marker))
        if is_idle:
            idle.append(issue['id'])
        elif marker:
            gone.append(issue['id'])
    section('held items', rows, limit)
    if gone:
        print(f"  GONE = the holding session's process ended. Free {', '.join(gone)}: board take <id> | board unclaim <id>")
    if idle:
        print(f'  idle = no activity for {IDLE_HOURS} h (the holder\'s last tool call, else the item\'s last update); '
              'a single long-running tool call looks idle too. '
              'If that session is gone: board take <id> | board unclaim <id>')

    questions = []
    for issue in items:
        if issue.get('issue_type') == 'decision' and issue['status'] not in ('released', 'deferred'):
            waiting = board.downstream(issue['id'])
            if waiting:
                questions.append((waiting, issue))
    section('open questions holding work',
            [line(issue, f'holds {waiting}', issue.get('assignee') or 'unassigned')
             for waiting, issue in sorted(questions, key=lambda pair: (-pair[0], by_priority(pair[1])))], limit)

    section('ready milestones', [line(issue, issue.get('assignee') or 'unassigned') for issue in
                                 sorted((i for i in items if board.kind(i) == 'milestone' and not board.open_blockers(i['id'])),
                                        key=by_priority)], limit)

    finished = [issue for issue in items if issue.get('issue_type') == 'epic' and board.children.get(issue['id'])
                and not any(board.is_open(child) for child in board.children[issue['id']])]
    section('finished epics not closed', [line(issue) for issue in sorted(finished, key=by_priority)], limit)


def session_kinds(entry: dict, table: dict = ROLE_KINDS) -> tuple[str, ...]:
    kinds = table.get(entry.get('role'), ())
    return tuple(entry.get('pulls') or ()) if kinds is None else kinds


def holders(board: Board, args) -> None:
    rows = []
    for issue in board.scoped(args.root):
        if issue['status'] != 'closed':
            count = board.downstream(issue['id'])
            if count:
                rows.append((count, issue))
    rows.sort(key=lambda pair: (-pair[0], by_priority(pair[1])))
    section('items holding open work (transitive blocks dependents)',
            [line(issue, f'holds {count}', issue.get('assignee') or 'unassigned') for count, issue in rows], args.limit)


# Conformance with skills/shared/board-core.md and board-coordination.md: mechanical classes only.
ACTOR = re.compile(r'[0-9a-f]{8}(/.+)?')
TITLE_PREFIXES = ('[Design]', '[Gate]', '[Checkpoint]', '[Review]')
RETIRED_TYPES = ('feature', 'chore', 'check')
CHECK_CLASSES = {  # class -> board-core anchor
    'holder': 'actors-and-holds',
    'retired-type': 'kinds',
    'title-prefix': 'kinds',
    'release-gate': 'kinds',
    'label-status': 'statuses-and-labels',
    'review-blocked': 'hand-over-and-acceptance',
}
# Squashed text (words run together): a flag, never a deviation. Calibrated on
# the retro's samples (tools/ctx): clean board text 0 per 1,000 words, prompt
# text 8.8, squashed board text 210.
SQUASH_PER_1K = 50
SQUASH_MIN_HITS = 2
WORD_LIST = Path('/usr/share/dict/words')
EXTRA_WORDS = {'lint', 'typecheck', 'json', 'readonly', 'repo', 'config', 'dms', 'orm', 'api', 'ai', 'auth', 'pass',
               'fronts', 'checkpoint', 'workers', 'worker', 'diagnostics', 'integration', 'preexisting', 'canonical',
               'held', 'scoped', 'errors', 'queue', 'install', 'workaround', 'workarounds'}
SUFFIXES = ('s', 'es', 'ed', 'd', 'ing', 'ly', 'ized', 'ised', 'ation', 'ations', 'ies')


def deviations(board: Board, root: str | None) -> list[tuple[str, str, str]]:
    """(id, class, detail) for every convention deviation of a live (not closed) item in scope."""
    found = []
    for issue in board.scoped(root):
        item_id, kind, title = issue['id'], issue.get('issue_type'), issue.get('title', '')
        if issue['status'] == 'closed':
            continue  # closed items are immutable history
        holder = issue.get('assignee')
        if holder and holder != 'user' and not ACTOR.fullmatch(holder):
            found.append((item_id, 'holder', f'held by {holder}'))
        if kind in RETIRED_TYPES:
            found.append((item_id, 'retired-type', f'type {kind}'))
        prefix = next((p for p in TITLE_PREFIXES if title.startswith(p)), None)
        if prefix:
            found.append((item_id, 'title-prefix', f'title starts with {prefix}'))
        if kind == 'gate' and title.startswith('[Gate] Release'):
            found.append((item_id, 'release-gate', 'release gate title'))
        labels = sorted(set(issue.get('labels') or []) & set(LIFECYCLE_LABELS))
        if labels:
            found.append((item_id, 'label-status', f"labels {', '.join(labels)}"))
        waits = board.open_blockers(item_id) if issue['status'] == 'in_review' else []
        if waits:
            found.append((item_id, 'review-blocked', f"in review while waiting on {', '.join(waits)}: "
                                                     f'claim it and board return {item_id} "<amend to the blocker>"'))
    return found


# Passive forms first: "revised by <id>" means <id> revises this record.
REVISION_WORDS = re.compile(r'\b(?:(?P<passive>(?:revised|superseded|replaced)\s+by)|'
                            r'(?P<active>revis(?:es|ing|ion of)|supersed(?:es|ing)|replac(?:es|ing)))\b', re.IGNORECASE)
ITEM_ID = re.compile(r'[A-Za-z0-9][\w-]*(?:\.[\w-]+)*')
REJECTED = re.compile(r'^##\s+alternatives considered\b.*?(?=^##\s|\Z)', re.IGNORECASE | re.MULTILINE | re.DOTALL)
WINDOW = 60  # characters after the verb searched for the record it names


def unlinked_revisions(board: Board, root: str | None) -> list[tuple[str, str]]:
    """(id, detail) per live decision whose editable text says it revises, supersedes or replaces another decision
    (or is revised by one) without a supersedes or revise edge between them. Comments are history (moved packets
    quote old records); rejected alternatives describe what the record does not do."""
    flagged = []
    for issue in board.scoped(root):
        if issue['status'] == 'closed' or issue.get('issue_type') != 'decision':
            continue
        text = '\n'.join(REJECTED.sub('', str(issue.get(f) or '')) for f in ('title', 'description', 'design', 'notes'))
        named: dict[str, tuple[str, bool]] = {}  # other id -> (verb, other revises this one)
        covered = 0
        for match in REVISION_WORDS.finditer(text):
            if match.start() < covered:
                continue  # inside the previous verb's window ("revised by the superseding rulings: <id>")
            covered = match.end() + WINDOW
            for other in ITEM_ID.findall(text[match.end():covered]):
                if other != issue['id'] and board.by_id.get(other, {}).get('issue_type') == 'decision':
                    named.setdefault(other, (' '.join(match.group(0).lower().split()), bool(match.group('passive'))))
        for other, (word, passive) in named.items():
            if not any(kind in ('supersedes', REVISES) for _, _, kind in board.between(issue['id'], other)):
                old, new = (issue['id'], other) if passive else (other, issue['id'])
                flagged.append((issue['id'], f'{word} {other} without a supersedes or revise link: board supersede '
                                             f'{old} --with {new} [--partial "<rule>"]'))
    return flagged


def unnamed_waits(board: Board, root: str | None) -> list[tuple[str, str]]:
    """(id, detail) per open blocker a live item's text does not name: a flag, never a deviation, because bd keeps
    no reason on the edge and legacy waits have none to recover."""
    flagged = []
    for issue in board.scoped(root):
        if issue['status'] == 'closed' or issue.get('issue_type') == 'milestone':
            continue  # a milestone's blockers are its members (board-coordination.md#milestones)
        text = board.text(issue)
        # A gate carries its own reason (bd gate create --reason); a closed blocker holds nothing up.
        flagged += [(issue['id'], f'waits on {b} without naming it') for b in board.blockers.get(issue['id'], [])
                    if b not in text and board.is_open(b) and board.by_id.get(b, {}).get('issue_type') != 'gate']
    return flagged


def word_list() -> set[str]:
    try:
        words = {w.strip().lower() for w in WORD_LIST.read_text(encoding='utf-8', errors='ignore').split() if len(w.strip()) >= 3}
    except OSError:
        words = set()
    return words | EXTRA_WORDS


class Squash:
    """Port of the retro's detect.py: letter-digit runs and long lowercase
    tokens that split into dictionary words. Without a word list only the
    letter-digit runs count."""

    def __init__(self, words: set[str]):
        self.words = words
        self.cache: dict[tuple[str, int], bool] = {}

    def split(self, text: str, depth: int = 0) -> bool:
        key = (text, depth)
        if key not in self.cache:
            if text in self.words and depth > 0:
                result = True
            elif depth >= 3:
                result = False
            else:
                result = any(text[:i] in self.words and self.split(text[i:], depth + 1) for i in range(3, len(text) - 2))
            self.cache[key] = result
        return self.cache[key]

    def squashed(self, token: str) -> bool:
        if re.fullmatch(r'[A-Za-z]+\d+[A-Za-z]{3,}|\d+[a-z]{4,}[A-Z]*|[a-z]{3,}\d+[a-z]*', token):
            return True
        if not self.words or not re.fullmatch(r'[A-Z]?[a-z]{10,}', token):
            return False
        lower = token.lower()
        if lower in self.words or any(lower.endswith(x) and lower[:-len(x)] in self.words for x in SUFFIXES) \
                or (lower.endswith('ies') and lower[:-3] + 'y' in self.words):
            return False
        return self.split(lower)

    def score(self, texts: list[str]) -> tuple[int, int, list[str]]:
        words, hits = 0, []
        for text in texts:
            for token in re.split(r'[\s,;:()\[\]"\'→=+]+', re.sub(r'`[^`]*`', '', text)):
                token = token.strip('.!?')
                if not token:
                    continue
                words += 1
                if not any(c in token for c in '/._-') and self.squashed(token):
                    hits.append(token)
        return words, len(hits), hits


def squash_flags(board: Board, root: str | None, words: set[str]) -> list[tuple[str, str]]:
    squash = Squash(words)
    flagged = []
    for issue in board.scoped(root):
        if issue['status'] == 'closed':
            continue
        # Editable fields only: comments are history.
        texts = [str(issue.get(f) or '') for f in ('title', 'description', 'design', 'acceptance_criteria', 'notes')]
        total, hits, examples = squash.score(texts)
        if hits >= SQUASH_MIN_HITS and 1000 * hits / max(total, 1) > SQUASH_PER_1K:
            flagged.append((issue['id'], f"{1000 * hits / total:.0f} squashed per 1,000 words, e.g. {', '.join(examples[:3])}"))
    return flagged


def check(board: Board, args) -> int:
    limit = args.limit
    found = deviations(board, args.root)
    print(f'convention deviations: {len(found)}')
    for name, anchor in CHECK_CLASSES.items():
        rows = [f'  {item_id}  {name}  board-core.md#{anchor}  {detail}'
                for item_id, kind, detail in found if kind == name]
        if rows:
            section(f'{name} (board-core.md#{anchor})', rows, limit)
    words = word_list()
    flags = squash_flags(board, args.root, words)
    note = '' if len(words) > len(EXTRA_WORDS) else f'; no word list at {WORD_LIST}, letter-digit runs only'
    section(f'flag, not a deviation: squashed text on open items{note}',
            [f'  {item_id}  squashed  {detail}' for item_id, detail in flags], limit)
    section('flag, not a deviation: unnamed waits on open items (board-core.md#dependencies)',
            [f'  {item_id}  unnamed-blocker  {detail}' for item_id, detail in unnamed_waits(board, args.root)], limit)
    section('flag, not a deviation: revisions without a supersedes or revise link (board-coordination.md#rulings)',
            [f'  {item_id}  unlinked-revision  {detail}' for item_id, detail in unlinked_revisions(board, args.root)], limit)
    return 1 if found else 0


STOPWORDS = set("""a about after all also an and any are as at be because been before being both but by can could do
does each either for from had has have how if in into is it its may might more most must no not of on once only or other
our out over own same should so such than that the their them then there these they this those through to under until up
use used uses using via was we were what when where whether which while who why will with without would you your""".split())
COMMON_SHARE = 0.2  # a --like word on more of the board's items than this says nothing about the draft
LIKE_TERMS = 15


def lowered(board: Board, issue: dict) -> str:
    cache = board.__dict__.setdefault('_lowered', {})
    if issue['id'] not in cache:
        cache[issue['id']] = board.text(issue).lower()
    return cache[issue['id']]


def related(board: Board, args) -> None:
    """Ranks by inverse document frequency: a rare shared word says more than a template word every item carries."""
    scoped = board.scoped(args.root)
    texts = [(issue, lowered(board, issue)) for issue in scoped]
    total = max(len(texts), 1)
    frequency: dict[str, int] = {}

    def weight(term: str) -> float:
        if term not in frequency:
            frequency[term] = sum(1 for _, text in texts if term in text)
        return math.log((total + 1) / (frequency[term] + 1))

    terms = list(dict.fromkeys(term.lower() for term in args.terms))
    chosen = []
    if args.like is not None:
        words = dict.fromkeys(w for w in re.findall(r'[a-z][a-z0-9_.-]*[a-z0-9]', args.like.lower())
                              if len(w) >= 3 and w not in STOPWORDS and w not in terms)
        for word in words:
            weight(word)  # fills frequency
        # A word on no item matches nothing; one on many items is template text.
        candidates = [w for w in words if 0 < frequency[w] <= COMMON_SHARE * total]
        chosen = sorted(candidates, key=lambda w: (-weight(w), w))[:LIKE_TERMS]
        terms += chosen
    rows = []
    for issue, text in texts:
        hits = [term for term in terms if term in text]
        if hits:
            rows.append((sum(weight(term) for term in hits), len(hits), issue))
    rows.sort(key=lambda row: (-row[0], -row[1], by_priority(row[2])))
    like = f"; from --like: {', '.join(chosen) or 'no distinctive words'}" if args.like is not None else ''
    section(f"items matching {', '.join(terms)}, rarest matches first (all text fields, closed included{like})",
            [line(issue, f'{count}/{len(terms)} terms', issue.get('assignee') or 'unassigned') for _, count, issue in rows],
            args.limit)
    if args.docs:
        matches = []
        for root in (part for value in args.docs for part in value.split(',') if part.strip()):
            path = Path(root.strip())
            files = sorted(path.rglob('*.md')) if path.is_dir() else [path]
            for file in files:
                try:
                    lines = file.read_text(encoding='utf-8').splitlines()
                except (OSError, UnicodeDecodeError) as error:
                    raise BoardError(f'cannot read {file}: {error}') from None
                matches += [f'  {file}:{number}: {text.strip()}' for number, text in enumerate(lines, 1)
                            if any(term in text.lower() for term in terms)]
        section('doc lines', matches, args.limit)


def queue(board: Board, args) -> None:
    ready = sorted((issue for issue in board.scoped(args.root) if board.claimable(issue)),
                   key=lambda issue: claim_order(board, issue))

    def marker(issue: dict) -> str:
        milestones = board.in_milestone.get(issue['id'])
        return f"m:{','.join(milestones)}" if milestones else ''

    for kind in KINDS:
        section(kind, [line(issue, f"p{issue.get('priority', '?')}", marker(issue))
                       for issue in ready if board.claimable(issue) == kind], args.limit)


# board show: items rendered from the snapshot, unwrapped, within READ_BUDGET (`--full` lifts it).

LINK_KINDS = {  # (type, outgoing) -> label from the shown item's side; order is print order
    ('blocks', True): 'blocked by', ('blocks', False): 'blocks', ('parent-child', True): 'parent',
    ('parent-child', False): 'children', ('relates-to', True): 'relates to', ('relates-to', False): 'relates to',
    ('related', True): 'relates to', ('related', False): 'relates to', ('supersedes', False): 'supersedes',
    ('supersedes', True): 'superseded by', ('discovered-from', True): 'discovered from',
    ('discovered-from', False): 'discovered here',
}
LINK_ORDER = ('blocked by', 'blocks', 'parent', 'children', 'relates to', 'supersedes', 'superseded by',
              'discovered from', 'discovered here', 'revises', 'revision pending')
HEADING = re.compile(r'^(#{2,3})\s+(.+?)\s*#*\s*$')


def normalized(name: str) -> str:
    return ' '.join(name.replace('_', ' ').lower().split())


def comment_list(issue: dict) -> list[dict]:
    return [{'author': c.get('author'), 'created_at': c.get('created_at'), 'text': c.get('text') or ''}
            for c in sorted(issue.get('comments') or [], key=lambda c: c.get('created_at') or '')]


def link_lines(board: Board, issue: dict) -> list[str]:
    grouped: dict[str, list[str]] = {}
    for other, kind, outgoing in board.edges.get(issue['id'], []):
        if kind == REVISES and issue.get('issue_type') == 'decision' and outgoing:
            label = 'revises'
        elif kind == REVISES and not outgoing and board.by_id.get(other, {}).get('issue_type') == 'decision':
            label = 'revision pending'
        else:
            label = LINK_KINDS.get((kind, outgoing), kind if outgoing else f'{kind} (from)')
        target = board.by_id.get(other, {})
        new = issue if label == 'revises' else target if label == 'revision pending' else {}
        rule = (new.get('metadata') or {}).get(REVISES_RULE) if isinstance(new.get('metadata'), dict) else None
        grouped.setdefault(label, []).append(f"  {label}: {other}  {target.get('status', 'not on board')}  "
                                             f"{target.get('title', '')}" + (f'  (partial: {rule})' if rule else ''))
    order = [*LINK_ORDER, *sorted(set(grouped) - set(LINK_ORDER))]
    return [row for label in order for row in sorted(set(grouped.get(label, [])))]  # relates-to may be stored twice


def field_units(issue: dict, field: str) -> list[tuple[str, str]]:
    """(section name, text) chunks of one field: its preamble under the field name, then one per heading."""
    text = str(issue.get(field) or '').strip('\n')
    if not text.strip():
        return []
    units, name, chunk = [], field, [f'{field}:']
    for row in text.splitlines():
        heading = HEADING.match(row)
        if heading:
            if name == field and len(chunk) == 1:  # no preamble: the field label leads its first heading
                name = heading.group(2)
                chunk.append(row)
                continue
            units.append((name, '\n'.join(chunk)))
            name, chunk = heading.group(2), [row]
        else:
            chunk.append(row)
    units.append((name, '\n'.join(chunk)))
    return units


def section_text(issue: dict, field: str, title: str) -> str:
    """A heading's text through the next heading of the same or a higher level."""
    rows, level, out = str(issue.get(field) or '').splitlines(), None, []
    for row in rows:
        heading = HEADING.match(row)
        if level is not None and heading and len(heading.group(1)) <= level:
            break
        if level is None and heading and heading.group(2) == title:
            level = len(heading.group(1))
        if level is not None:
            out.append(row)
    return '\n'.join(out)


def show_sections(board: Board, issue: dict, query: str) -> list[tuple[str, str]]:
    candidates = [(field, f'{field}:\n' + str(issue.get(field)).strip('\n')) for field in SHOW_FIELDS
                  if str(issue.get(field) or '').strip()]
    links = link_lines(board, issue)
    if links:
        candidates.append(('links', 'links:\n' + '\n'.join(links)))
    for field in SHOW_FIELDS:
        candidates += [(name, section_text(issue, field, name)) for name, _ in field_units(issue, field)[1:]
                       if name != field]
    wanted = normalized(query)
    matches = [c for c in candidates if normalized(c[0]) == wanted] \
        or [c for c in candidates if normalized(c[0]).startswith(wanted)]
    names = sorted({name for name, _ in matches})
    if not matches:
        raise BoardError(f"{issue['id']}: no section {query!r}; sections: " + ', '.join(dict.fromkeys(n for n, _ in candidates)))
    if len(names) > 1:
        raise BoardError(f"{issue['id']}: section {query!r} is ambiguous:\n" + '\n'.join(
            f'  board show {issue["id"]} --section {shlex.quote(name)}' for name in names))
    return matches


class Budget:
    """Prints units whole while the budget lasts; a unit that doesn't fit prints its first PREVIEW characters and
    the command that prints the rest. Past the budget, one line per item names the remaining sections."""

    def __init__(self, limit: int | None):
        self.remaining, self.skipped = limit, {}

    def out(self, text: str) -> None:
        """Always printed (headers, counts, footers); still spends the budget."""
        print(text)
        if self.remaining is not None:
            self.remaining -= len(text) + 1

    def emit(self, text: str, rest: str, name: str | None = None, item: str | None = None) -> None:
        if self.remaining is None or len(text) + 1 <= self.remaining - 300:  # 300: room for the closing lines
            self.out(text)
        elif self.remaining >= PREVIEW + 500:
            cut = text[:PREVIEW]
            self.out(f'{cut}\n… {len(text) - len(cut)} more chars: {rest}')
        else:
            self.skipped.setdefault(item, []).append((name, rest))

    def flush(self, item: str) -> None:
        skipped = self.skipped.pop(item, [])
        if skipped:
            names = ', '.join(f'"{name}"' for name, _ in skipped[:20]) + (', …' if len(skipped) > 20 else '')
            self.out(f'… {len(skipped)} more sections of {item} ({names}): {skipped[0][1]}')


def show(board: Board, args) -> int:
    missing = [item_id for item_id in args.ids if item_id not in board.by_id]
    if missing:
        raise BoardError(f"unknown {', '.join(missing)}")
    issues = [board.by_id[item_id] for item_id in args.ids]
    known = {key for issue in board.issues for key in issue} | set(TEXT_FIELDS) | {'comments'}
    unknown = [field for field in args.fields if field not in known]
    if unknown:
        raise BoardError(f"unknown field {', '.join(unknown)}; fields: {', '.join(sorted(known - {'_type'}))}")
    if args.json:
        if not args.fields:
            raise BoardError('--json needs --field <field> (repeatable)')
        print(json.dumps({issue['id']: {field: comment_list(issue) if field == 'comments' else issue.get(field)
                                        for field in args.fields} for issue in issues}, indent=2, ensure_ascii=False))
        return 0
    budget = Budget(None if args.full else READ_BUDGET)
    full = ' --full'
    for issue in issues:
        item_id = issue['id']
        q = shlex.quote
        header = [item_id, issue['status'], issue.get('issue_type', ''), f"p{issue.get('priority', '?')}",
                  issue.get('assignee') or 'unassigned']
        if item_id in board.parent:
            header.append(f'parent {board.parent[item_id]}')
        if issue.get('labels'):
            header.append('labels ' + ','.join(issue['labels']))
        budget.out('  '.join(header) + '\n' + issue.get('title', ''))
        selected = bool(args.sections or args.fields or args.comments)
        for query in args.sections:
            for name, text in show_sections(board, issue, query):
                budget.emit(text, f'board show {item_id} --section {q(name)}{full}', name, item_id)
        for field in args.fields:
            value = comment_list(issue) if field == 'comments' else issue.get(field)
            text = f'{field}:\n' + (value.strip('\n') if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
            budget.emit(text, f'board show {item_id} --field {q(field)}{full}', field, item_id)
        if not selected:
            links = link_lines(board, issue)
            if links:
                budget.emit('links:\n' + '\n'.join(links), f'board show {item_id} --section links', 'links', item_id)
            for field in SHOW_FIELDS:
                for name, text in field_units(issue, field):
                    budget.emit(text, f'board show {item_id} --section {q(name)}', name, item_id)
        comments = comment_list(issue)
        if args.comments or not selected:
            shown = comments if args.comments else comments[-SHOWN_COMMENTS:]
            if comments:
                budget.out(f'comments: {len(comments)}' + (f', newest {len(shown)}' if len(shown) < len(comments) else ''))
            for note in reversed(shown):
                budget.emit(f"--- {note['author']} {note['created_at']}\n{note['text']}",
                            f'board show {item_id} --comments --full', f"comment {note['created_at']}", item_id)
            if len(shown) < len(comments):
                budget.out(f'… {len(comments) - len(shown)} older: board show {item_id} --comments')
        budget.flush(item_id)
    return 0


def budgeted(run, board: Board, args, argv: list[str]) -> int:
    """Runs a view within READ_BUDGET. Rows are the indented lines; --offset skips that many, keeping the heading of
    the section it lands in. A cut names the --offset that prints the next rows."""
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = run(board, args) or 0
    lines = output.getvalue().splitlines()
    kept, size, row, pending, cut, heading = [], 0, 0, [], None, None
    for text in lines:
        is_row = text.startswith('  ')
        if row < args.offset:
            if is_row:
                row += 1
                pending = [heading] if heading else []  # the section heading prints again before its next shown row
            else:
                heading = text
                pending.append(text)
            continue
        block = [*pending, text] if is_row else [text]
        cost = sum(len(item) + 1 for item in block)
        if size + cost > READ_BUDGET - 300:
            cut = row
            break
        kept += block
        size += cost
        pending = []
        row += is_row
    if pending and cut is None:
        kept += pending
    print('\n'.join(kept))
    if cut is not None:
        words, skip = [], False
        for word in argv:
            if skip:
                skip = False
            elif word == '--offset':
                skip = True
            elif not word.startswith('--offset='):
                words.append(word)
        total = sum(1 for text in lines if text.startswith('  '))
        print(f'… {total - cut} more rows: board {shlex.join([*words, "--offset", str(cut)])}')
    return code


# Writes

def caller() -> str:
    actor = derived_actor()
    if not actor:
        raise BoardError('no actor: run inside a Claude Code or Codex session, or set BEADS_ACTOR')
    return actor


HANDOVER = 'board handover: '


def authorship(issue: dict) -> tuple[str | None, str | None]:
    """(author, legacy holder): who handed the item over, from its handover comment,
    else bd's status history; a hand-over by a pre-actor holder (goal-agent) is legacy."""
    legacy = None
    for note in sorted(issue.get('comments') or [], key=lambda c: c.get('created_at') or '', reverse=True):
        if (note.get('text') or '').startswith(HANDOVER):
            if ACTOR.fullmatch(note.get('author') or ''):
                return note['author'], None
            legacy = legacy or note.get('author')
    for event in json.loads(bd_checked('history', issue['id'], '--events', '--json') or '[]'):
        try:
            status = json.loads(event.get('new_value') or '{}').get('status')
        except (ValueError, AttributeError):
            continue
        if event.get('event_type') == 'status_changed' and status == 'in_review':
            if ACTOR.fullmatch(event.get('actor') or ''):
                return event['actor'], None
            legacy = legacy or event.get('actor')
    return None, legacy


def author_label(issue: dict) -> str:
    actor, legacy = authorship(issue)
    return f'author {actor}' if actor else f'author unknown ({legacy})' if legacy else 'standalone'


def held_by_session(board: Board, actor: str) -> list[dict]:
    session = session_actor(actor)
    return sorted((issue for issue in board.issues if issue['status'] != 'closed' and issue.get('assignee')
                   and (issue['assignee'] == session or issue['assignee'].startswith(session + '/'))),
                  key=by_priority)


def mine(board: Board, args) -> None:
    actor = caller()
    scoped = {issue['id'] for issue in board.scoped(args.root)}
    you = f' (you: {actor})' if actor != session_actor(actor) else ''
    try:
        entry = registry_by_actor(registrations()).get(session_actor(actor))
    except BoardError:
        entry = None  # no marks without the registry; the holds still list
    rows, stopped = [], []
    for issue in held_by_session(board, actor):
        if issue['id'] in scoped:
            mark = worker_stopped(entry, issue)
            rows.append(line(issue, issue['assignee'], f'updated {age(board.last_activity(issue))} ago'
                             + (' WORKER STOPPED' if mark else '')))
            if mark:
                stopped.append(issue['id'])
    section(f'held by session {session_actor(actor)}{you}', rows, args.limit)
    if stopped:
        print(f"  WORKER STOPPED = the holding worker finished its last turn ({', '.join(stopped)}): "
              'continue the worker, hand the item over, or free it (board unclaim <id>)')


def capacity(board: Board, args) -> None:
    """The session's refill hint: printed for the session itself (no worker caller) in a dispatching role while
    fewer than its cap of workers were active and worker work (WORKER_KINDS, an agent's within its pulls) is
    claimable. A session's own hand-overs count: another of its workers may review them. The snapshot predates a write, so the
    items the command named or claimed are left out (one read per command). Never fails the command it follows."""
    actor = derived_actor()
    if not actor or actor != session_actor(actor):
        return
    try:
        entry = registry_by_actor(registrations()).get(actor)
        if entry is None or entry.get('role') not in CAPACITY_ROLES:
            return
        active, cap = len(active_workers(entry)), worker_cap(entry)
        if active >= cap:
            return
        pulls = entry.get('pulls') or ()
        kinds = tuple(kind for kind in WORKER_KINDS if entry.get('role') != 'agent' or kind in pulls)
        changed = {*(getattr(args, 'ids', None) or ()), getattr(args, 'id', None), *getattr(args, 'claimed', ())}
        counts = {kind: sum(1 for issue in board.scoped(args.root)
                            if board.claimable(issue) == kind and issue['id'] not in changed) for kind in kinds}
    except BoardError:
        return
    ready = sorted(((kind, count) for kind, count in counts.items() if count), key=lambda pair: -pair[1])
    if ready:
        print(f"capacity: {active} of {cap} workers active in the last {WORKER_ACTIVE_MINUTES} min; "
              f"ready for your pulls: {', '.join(f'{kind} {count}' for kind, count in ready)} → refill (plan Dispatch)")


def claim_one(issue: dict, actor: str) -> tuple[bool, str]:
    """Atomically claim one item. Open items use bd's claim; in_review and
    released items keep their status through a compare-and-set on the assignee."""
    if issue['status'] == 'open':
        result = bd('update', issue['id'], '--claim', '--json')
    else:
        result = bd('update', issue['id'], '--assignee', actor, '--if-assignee', '', '--json')
    return result.returncode == 0, (result.stderr or result.stdout).strip()


def claim(board: Board, args) -> int:
    actor = caller()
    claimed, failed = [], []
    if args.ids:
        for item_id in args.ids:
            issue = board.by_id.get(item_id)
            if issue is None or issue['status'] == 'closed':
                raise BoardError(f'{item_id}: unknown or closed')
            holder = issue.get('assignee')
            if holder == actor:
                print(f'{item_id}: already held by {actor}')
                continue
            if holder and session_actor(holder) == session_actor(actor):
                # The session owns its workers' holds (design item 16): hand the item down.
                bd_checked('update', item_id, '--assignee', actor, '--force', '--json')
                comment(item_id, f'board claim: {actor} took this item over from {holder} in the same session.')
                claimed.append(issue)
                continue
            if holder:
                failed.append(item_id)
                print(f'{item_id}: held by {holder}; the user or a deciding session frees it with board take or board unclaim once its session is gone',
                      file=sys.stderr)
                continue
            if board.kind(issue) == 'milestone' and board.open_blockers(item_id):
                # Accepting a milestone needs its work done (board-coordination.md#milestones).
                failed.append(item_id)
                print(f"{item_id}: milestone not ready, waits on {', '.join(board.open_blockers(item_id))}", file=sys.stderr)
                continue
            ok, message = claim_one(issue, actor)
            if ok:
                claimed.append(issue)
            else:
                failed.append(item_id)
                print(f'{item_id}: not claimed: {message}', file=sys.stderr)
    else:
        entry = registry_by_actor(registrations()).get(session_actor(actor))
        if entry is None:
            raise BoardError(f'no registered role for session {session_actor(actor)}; run /role first')
        kinds = session_kinds(entry)
        scoped = board.scoped(args.root)
        candidates = sorted((issue for issue in scoped if board.claimable(issue) in kinds),
                            key=lambda issue: claim_order(board, issue))
        for issue in candidates:
            if issue['status'] == 'in_review' and authorship(issue)[0] == actor:
                continue  # your own hand-over needs another reviewer
            ok, _ = claim_one(issue, actor)
            if ok:
                claimed.append(issue)
                break
        if not claimed:
            print(f"nothing claimable for {entry.get('role')} ({','.join(kinds)})")
    args.claimed = [issue['id'] for issue in claimed]
    for issue in claimed:
        by = f'; {author_label(issue)}' if issue['status'] == 'in_review' else ''
        print(f"claimed {issue['id']} ({board.kind(issue) or issue.get('issue_type')}{by}): {issue.get('title', '')}")
    still = [issue for issue in held_by_session(board, actor) if issue not in claimed]
    if still:
        section('this session still holds', [line(issue, issue['assignee']) for issue in still])
    return 1 if failed or not (claimed or args.ids) else 0


def comment(item_id: str, text: str) -> None:
    bd_checked('comments', 'add', item_id, text)


def require_open(board: Board, ids: list[str]) -> list[dict]:
    missing = [item_id for item_id in ids if not board.is_open(item_id)]
    if missing:
        raise BoardError(f"unknown or closed: {', '.join(missing)}")
    return [board.by_id[item_id] for item_id in ids]


def take(board: Board, args) -> None:
    actor = caller()
    for issue in require_open(board, args.ids):
        previous = issue.get('assignee') or 'nobody'
        if previous == actor:
            print(f"{issue['id']}: already held by {actor}")
            continue
        bd_checked('update', issue['id'], '--assignee', actor, '--force', '--json')
        comment(issue['id'], f'board take: {actor} took this item over from {previous}.')
        print(f"took {issue['id']} from {previous}")


def unclaim(board: Board, args) -> None:
    actor = caller()
    for issue in require_open(board, args.ids):
        holder = issue.get('assignee')
        if not holder:
            print(f"{issue['id']}: not held")
            continue
        reason = f"board unclaim: {actor} released {holder}'s hold."
        if issue['status'] == 'in_progress':
            # bd unclaim resets to open; it refuses other statuses.
            bd_checked('unclaim', issue['id'], '--reason', reason, *(['--force'] if holder != actor else []))
        else:
            # in_review and released items keep their status for the next claimer.
            bd_checked('update', issue['id'], '--assignee', '', '--json')
            comment(issue['id'], reason)
        print(f"unclaimed {issue['id']} from {holder} ({issue['status']})")


def held(board: Board, item_id: str, actor: str, status: str | None = None) -> dict:
    issue = require_open(board, [item_id])[0]
    if issue.get('assignee') != actor or (status and issue['status'] != status):
        raise BoardError(f"{item_id}: {issue['status']}, held by {issue.get('assignee') or 'nobody'}; claim it first")
    return issue


def handover(board: Board, args) -> None:
    actor = caller()
    held(board, args.id, actor)
    bd_checked('update', args.id, '--status', 'in_review', '--assignee', '', '--if-assignee', actor, '--json')
    comment(args.id, HANDOVER + args.evidence)
    print(f'handed over {args.id} for review')


def return_item(board: Board, args) -> None:
    actor = caller()
    held(board, args.id, actor, 'in_review')
    bd_checked('update', args.id, '--status', 'open', '--assignee', '', '--if-assignee', actor, '--json')
    comment(args.id, f'board return: {args.findings}')
    print(f'returned {args.id} to the queue')


SHOW_PASSTHROUGH = ('--refs', '--children', '--as-of', '--long', '--watch', '--current', '--thread', '-w', '-h', '--help')
GLOBAL_VALUES = ('-C', '--directory', '--db', '--database', '--actor', '--dolt-auto-commit', '--mem-profile')
SHOW_USAGE = 'use board show <ids> [--section …] [--field …] [--comments] [--full]'


def passthrough(argv: list[str]) -> int:
    if argv[:1] == ['dolt'] and argv[1:2] in (['start'], ['restart']):
        raise BoardError('board starts the server before every bd call; rerun the failing command with elevated sandbox permissions')
    at = 0
    while at < len(argv) and argv[at].startswith('-'):
        at += 2 if argv[at] in GLOBAL_VALUES else 1
    command, rest = (argv[at], argv[at + 1:]) if at < len(argv) else ('', [])
    flags = {arg.split('=', 1)[0] for arg in rest}
    # Raw show output is padded and wraps; it cut most agent reads mid-item. board show renders and budgets it.
    if (command in ('show', 'view') and not flags & set(SHOW_PASSTHROUGH)) \
            or (command == 'comments' and rest[:1] != ['add'] and not flags & {'-h', '--help'}):
        print(f'board: {SHOW_USAGE}', file=sys.stderr)
        return 2
    if command in ('list', 'create', 'query') and any(
            pair in (('--type', 'question'), ('-t', 'question')) for pair in zip(rest, rest[1:])) \
            or any(arg in ('--type=question', '-t=question') or re.search(r'\btype\s*=\s*"?question\b', arg)
                   for arg in rest if command in ('list', 'create', 'query')):
        print('board: questions are type decision (--type decision; open ones have status open)', file=sys.stderr)
        return 2
    directory = next((argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg in ('-C', '--directory')),
                     next((arg.split('=', 1)[1] for arg in argv if arg.startswith('--directory=')), None))
    ensure_server(Path(directory) if directory else None)
    os.execvpe('bd', ['bd', *argv], bd_env())


def with_file(text: str, run):
    """Long text goes to bd through a file, never argv."""
    with tempfile.NamedTemporaryFile('w', suffix='.md', encoding='utf-8', delete=False) as handle:
        handle.write(text)
    try:
        return run(handle.name)
    finally:
        os.unlink(handle.name)


def comment_long(item_id: str, text: str) -> None:
    with_file(text, lambda path: bd_checked('comments', 'add', item_id, '-f', path))


def missing_sections(text: str, sections=RECORD_SECTIONS) -> list[str]:
    headings = [normalized(match.group(1)) for match in re.finditer(r'^##\s+(.+?)\s*$', text, re.MULTILINE)]
    return [name for name in sections if not any(heading.startswith(normalized(name)) for heading in headings)]


def record(board: Board, args) -> None:
    actor = caller()
    issue = held(board, args.id, actor)
    if issue.get('issue_type') != 'decision':
        raise BoardError(f'{args.id}: {issue.get("issue_type")}, not a decision')
    if issue['status'] not in ('open', 'in_progress', 'decided', 'needs_ratification'):
        raise BoardError(f"{args.id}: {issue['status']}; a released record changes through board revise")
    try:
        text = Path(args.file).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as error:
        raise BoardError(f'cannot read {args.file}: {error}') from None
    # Autopilot's unratified rulings carry how to reverse them (unattended protocol).
    required = RECORD_SECTIONS + (('Reversal',) if args.status == 'needs_ratification' else ())
    missing = missing_sections(text, required)
    if missing:
        raise BoardError(f"{args.file} lacks the record section(s) {', '.join('## ' + name for name in missing)}")
    old = str(issue.get('description') or '').strip()
    moved = ''
    if old and missing_sections(old):
        packet = f'Decision packet (moved from the description at decision time, {utcnow().date().isoformat()}):\n\n{old}'
        # A rerun after a failed update finds the packet already moved.
        if not any((c.get('text') or '').endswith(f'\n\n{old}') and (c.get('text') or '').startswith('Decision packet (moved')
                   for c in issue.get('comments') or []):
            comment_long(args.id, packet)
        moved = '; packet moved to a comment'
    # An unratified autopilot record waits unheld for the user's ratification; a decided one stays held to release.
    unheld = ['--assignee', ''] if args.status == 'needs_ratification' else []
    bd_checked('update', args.id, '--body-file', args.file, '--status', args.status, *unheld, '--json')
    lint = json.loads(bd_checked('lint', args.id, '--json') or '{}')
    unlinted = [', '.join(result.get('missing') or []) for result in lint.get('results') or [] if result.get('missing')]
    if unlinted:
        raise BoardError(f"{args.id}: recorded ({args.status}{moved}), but bd lint reports missing {'; '.join(unlinted)}")
    print(f"recorded {args.id} ({args.status}{moved}): {issue.get('title', '')}")


def block_one(board: Board, item_id: str, blocker: str, reason: str, actor: str) -> tuple[str, bool]:
    """Blocks one item with its reason as a comment. (result line, returned from review)."""
    issue = board.by_id[item_id]
    edges = board.between(item_id, blocker)
    other = [kind for a, _, kind in edges if kind not in ('relates-to', 'related') and not (kind == 'blocks' and a == item_id)]
    if other:
        raise BoardError(f"{item_id}: already linked to {blocker} by {', '.join(other)}; bd keeps one edge per pair")
    # bd allows one edge per pair: a relates-to link between the two gives way to the wait.
    operations = [f'dep remove {a} {b}' for a, b, kind in edges if kind in ('relates-to', 'related')]
    if not any(kind == 'blocks' for _, _, kind in edges):
        operations.append(f'dep add {item_id} {blocker} blocks')
    holder = issue.get('assignee')
    reviewing = issue['status'] == 'in_review' and board.is_open(blocker)
    returning = reviewing and not holder
    if returning:
        # An unheld review waiting on an open blocker would be accepted against a moving premise (hand-over).
        operations.append(f'update {item_id} status=open assignee=""')
    if operations:
        bd_checked('batch', '-m', f'board block {item_id} --on {blocker}', '--json', stdin='\n'.join(operations) + '\n')
    # The comment names the wait for board check (unnamed waits read comments too); an append to a field would
    # rewrite it and lose a concurrent edit.
    comment(item_id, f'Blocked by {blocker}: {reason}')
    result = f'blocked {item_id} on {blocker}'
    if returning:
        comment(item_id, f'board block: returned from review; amend to {blocker}: {reason}')
        result += '; returned from review to open'
    elif reviewing and holder != actor:
        print(f'{item_id}: in review held by {holder}; it stays there, tell its holder about {blocker}', file=sys.stderr)
        result += f'; stays in review with {holder}'
    return result, returning


def block_items(board: Board, ids: list[str], blocker: str, reason: str, actor: str) -> tuple[list[str], list[str]]:
    """Blocks each item, one result line each; (returned from review, failed)."""
    returned, failed = [], []
    for item_id in ids:
        try:
            if item_id == blocker:
                raise BoardError(f'{item_id}: cannot block an item on itself')
            require_open(board, [item_id])
            result, back = block_one(board, item_id, blocker, reason, actor)
            print(result)
            returned += [item_id] if back else []
        except BoardError as error:
            failed.append(item_id)
            print(f'{item_id}: not blocked: {error}', file=sys.stderr)
    return returned, failed


def block(board: Board, args) -> int:
    actor = caller()
    if args.blocker not in board.by_id:
        raise BoardError(f'unknown blocker {args.blocker}')
    _, failed = block_items(board, args.ids, args.blocker, args.reason, actor)
    return 1 if failed else 0


def revise(board: Board, args) -> None:
    caller()
    old = board.by_id.get(args.old)
    if old is None or old.get('issue_type') != 'decision':
        raise BoardError(f'{args.old}: unknown or not a decision')
    if old['status'] in ('open', 'in_progress'):
        raise BoardError(f"{args.old}: {old['status']}, not yet a ruling; amend the question instead")
    parent = args.parent or board.parent.get(args.old)
    labels = [label for value in args.labels for label in value.split(',') if label] if args.labels \
        else [label for label in old.get('labels') or [] if label.startswith('topic:')]
    command = ['create', '--type', 'decision', '--title', args.title, '--body-file', args.body_file,
               '--priority', str(args.priority if args.priority is not None else old.get('priority', 2)),
               '--deps', f'{REVISES}:{args.old}']
    command += ['--parent', parent] if parent else []
    command += ['--labels', ','.join(labels)] if labels else []
    command += ['--metadata', json.dumps({REVISES_RULE: args.partial})] if args.partial is not None else []
    created = json.loads(bd_checked(*command, '--json') or '{}')
    new = created.get('id') if isinstance(created, dict) else None
    if not new:
        raise BoardError(f'bd create returned no id: {created!r}')
    print(new)


def release(board: Board, args) -> int:
    actor = caller()
    rulings = require_open(board, args.ids)
    problems = []
    for issue in rulings:
        if issue.get('issue_type') != 'decision':
            problems.append(f"{issue['id']}: not a decision")
        elif issue['status'] != 'decided':
            problems.append(f"{issue['id']}: {issue['status']}, not decided")
        blocking = [b for b in board.open_blockers(issue['id']) if b not in args.ids]
        if blocking:
            problems.append(f"{issue['id']}: waits on open {', '.join(blocking)}")
    if problems:
        raise BoardError('release refused:\n  ' + '\n  '.join(problems))

    lint = json.loads(bd_checked('lint', *args.ids, '--json') or '{}')
    unlinted = [f"{result['id']}: missing {', '.join(result.get('missing') or [])}"
                for result in lint.get('results') or [] if result.get('missing')]
    if unlinted:
        raise BoardError('release refused, record text fails bd lint (write the record first):\n  ' + '\n  '.join(unlinted))

    # A released ruling keeps blocking the items it changes; planning closes it and unblocks them.
    operations = [f"update {issue['id']} status=released assignee=\"\"" for issue in rulings]
    bd_checked('batch', '-m', f"board release {' '.join(args.ids)}", '--json', stdin='\n'.join(operations) + '\n')
    returned, failed = [], []
    for issue in rulings:
        print(f"released {issue['id']}: {issue.get('title', '')}")
        for old in board.revises(issue['id']):
            metadata = issue.get('metadata') if isinstance(issue.get('metadata'), dict) else {}
            rule = metadata.get(REVISES_RULE)
            try:
                back, lost = supersede_pair(board, old, issue['id'], rule, actor)
            except BoardError as error:
                failed.append(old)
                print(f"{old}: not superseded by {issue['id']}: {error}; finish with board supersede {old} --with {issue['id']}"
                      + (f' --partial {shlex.quote(rule)}' if rule is not None else ''), file=sys.stderr)
                continue
            returned += back
            failed += lost
    if returned:
        print(f"returned from review: {', '.join(returned)}")
    return 1 if failed else 0


def supersede_pair(board: Board, old: str, new: str, rule: str | None, actor: str) -> tuple[list[str], list[str]]:
    """Supersedes old by new, wholly or (rule not None) one rule; (returned from review, failed items)."""
    # bd allows one edge per pair: drop an existing link between the two records (a revise link included) first.
    operations = [f'dep remove {a} {b}' for a, b, kind in board.between(old, new) if kind != 'parent-child']
    if rule is not None:
        operations.append(f'dep add {old} {new} supersedes')
    if operations:
        bd_checked('batch', '-m', f'board supersede {old} --with {new}', '--json', stdin='\n'.join(operations) + '\n')
    if rule is not None:
        if rule:
            comment(old, f'board supersede: rule "{rule}" superseded by {new}.')
        print(f"{old}: one rule{f' ({rule})' if rule else ''} superseded by {new}")
        return [], []
    # The new record restates the whole rule: the old record's open items wait for its planning.
    items = sorted(i for i in board.related.get(old, set()) | set(board.dependents.get(old, []))
                   if i != new and board.is_open(i)
                   and all(kind in ('relates-to', 'related') for _, _, kind in board.between(i, new)))
    returned, failed = block_items(board, items, new, f'supersedes {old}; replan against it', actor)
    bd_checked('supersede', old, '--with', new)
    print(f"superseded {old} by {new}; blocked {', '.join(i for i in items if i not in failed) or 'none'}")
    return returned, failed


def supersede(board: Board, args) -> int:
    actor = caller()
    if args.old not in board.by_id:
        raise BoardError(f'unknown {args.old}')
    if args.partial is None:
        require_open(board, [args.new])  # a full replacement blocks items on the new record until it is planned
    elif args.new not in board.by_id:
        raise BoardError(f'unknown {args.new}')  # a closed record still supersedes one rule: the edge is the record
    returned, failed = supersede_pair(board, args.old, args.new, args.partial, actor)
    if returned:
        print(f"returned from review: {', '.join(returned)}")
    return 1 if failed else 0


EXAMPLES = {
    'health': 'board health --items ready,blocked',
    'position': 'board position --limit 20',
    'holders': 'board holders --root <epic>',
    'check': 'board check --all',
    'related': 'board related --like draft.md tenancy --docs docs,README.md',
    'queue': 'board queue --root <epic>',
    'mine': 'board mine',
    'show': 'board show <id> --section Decision',
    'claim': 'board claim',
    'record': 'board record <id> .scratch/<topic>/<arc>/record.md',
    'block': 'board block <item> <item> --on <blocker> --reason "waits for the cache ruling"',
    'revise': 'board revise <old> --title "May X replace Y?" --body-file packet.md --partial "Rule 2"',
    'release': 'board release <id> <id>',
    'supersede': 'board supersede <old> --with <new> --partial "Rule 2"',
    'bd': 'board bd list --status open --json',
    'handover': 'board handover <id> "pnpm test: exit 0, 412 passed; typecheck exit 0"',
    'return': 'board return <id> "test x fails: <finding>"',
    'take': 'board take <id>',
    'unclaim': 'board unclaim <id>',
    'help': 'board help',
}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ['bd']:
        try:
            return passthrough(argv[1:])
        except BoardError as error:
            print(f'board: {error}', file=sys.stderr)
            return 1
    parser = argparse.ArgumentParser(prog='board', description=__doc__.split('\n\n')[0])
    scope = argparse.ArgumentParser(add_help=False)
    scope.add_argument('--root', metavar='EPIC', help="limit to items below this epic, or to a milestone's work "
                       '(default: whole board)')
    listing = argparse.ArgumentParser(add_help=False)
    listing.add_argument('--offset', type=int, default=0, metavar='N', help='skip the first N rows (paging a cut output)')
    listing.add_argument('--limit', type=int, default=ROWS, help=f'rows per section (default {ROWS}, 0: all); the output '
                       f'stays within {READ_BUDGET} characters')
    commands = parser.add_subparsers(dest='command', required=True)

    def add(name: str, text: str, run, parents=()):
        sub = commands.add_parser(name, help=text, description=text, parents=list(parents), epilog=f'example: {EXAMPLES[name]}',
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
        sub.set_defaults(run=run)
        return sub

    def nonempty(value: str) -> str:
        if not value.strip():
            raise argparse.ArgumentTypeError('must not be empty')
        return value

    def views(value: str) -> set[str]:
        chosen = {view for view in value.split(',') if view}
        unknown = chosen - set(HEALTH_VIEWS)
        if not chosen or unknown:
            raise argparse.ArgumentTypeError(f"choose from {', '.join(HEALTH_VIEWS)}")
        return chosen

    sub = add('health', 'counts', health, [scope, listing])
    sub.add_argument('--items', type=views, default=set(), metavar='VIEW[,VIEW...]',
                     help=f"list the items behind these counts: {', '.join(HEALTH_VIEWS)}")
    sub = add('position', 'ready work vs sessions, held items with gone and idle marks, questions holding work, '
              'ready milestones, finished epics', position, [scope, listing])
    sub.add_argument('--all', dest='limit', action='store_const', const=0, help='every row (--limit 0)')
    add('holders', 'items by open downstream work', holders, [scope, listing])
    sub = add('check', 'deviations from the board conventions', check, [scope, listing])
    sub.add_argument('--all', dest='limit', action='store_const', const=0, help='every row (--limit 0)')
    sub = add('related', 'items and doc lines mentioning terms', related, [scope, listing])
    sub.add_argument('terms', nargs='*')

    def draft(value: str) -> str:
        try:
            return sys.stdin.read() if value == '-' else Path(value).read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as error:
            raise argparse.ArgumentTypeError(f'cannot read {value}: {error}') from None

    sub.add_argument('--like', type=draft, metavar='FILE|-', help=f'terms from a draft: its {LIKE_TERMS} rarest board words')
    sub.add_argument('--docs', nargs='+', default=[], metavar='PATH',
                     help='canonical docs (files or directories of .md), separated by spaces or commas')
    add('queue', 'claimable work by pull', queue, [scope, listing])
    add('mine', 'items held by this session and its workers', mine, [scope, listing])
    sub = add('show', 'items with links, fields and newest comments, within the read budget', show)
    sub.add_argument('ids', nargs='+')
    sub.add_argument('--section', dest='sections', action='append', default=[], metavar='NAME',
                     help='a field or a ##/### heading (case-insensitive prefix; repeatable)')
    sub.add_argument('--field', dest='fields', action='append', default=[], metavar='FIELD',
                     help='a named field, comments included (repeatable)')
    sub.add_argument('--comments', action='store_true', help='every comment, newest first')
    sub.add_argument('--full', action='store_true', help=f'no {READ_BUDGET}-character budget')
    sub.add_argument('--json', action='store_true', help='with --field: {id: {field: value}}, unbudgeted')
    sub = add('claim', 'claim the next item routed to your role, or the given ids', claim, [scope])
    sub.add_argument('ids', nargs='*')
    sub = add('record', 'write the decision record you hold from a file and set it decided', record)
    sub.add_argument('id')
    sub.add_argument('file')
    sub.add_argument('--status', choices=('decided', 'needs_ratification'), default='decided',
                     help='needs_ratification: an autopilot ruling; requires ## Reversal and frees the hold')
    sub = add('block', 'make items wait on a blocker, with the reason commented on each item', block)
    sub.add_argument('ids', nargs='+', metavar='item')
    sub.add_argument('--on', dest='blocker', required=True)
    sub.add_argument('--reason', required=True, type=nonempty)
    sub = add('revise', 'open a revision question linked to the record it revises; prints its id', revise)
    sub.add_argument('old')
    sub.add_argument('--title', required=True, type=nonempty)
    sub.add_argument('--body-file', required=True)
    sub.add_argument('--partial', metavar='RULE', help='revise one named rule; the rest stays in force')
    sub.add_argument('-p', '--priority', type=int, choices=range(5), help="default: the old record's")
    sub.add_argument('--parent', help="default: the old record's parent")
    sub.add_argument('-l', '--labels', action='append', default=[], help="default: the old record's topic: labels")
    sub = add('release', 'release decided rulings in one bd batch; supersedes the records they revise', release)
    sub.add_argument('ids', nargs='+')
    sub = add('supersede', "supersede a ruling; a full replacement blocks the old record's open items", supersede)
    sub.add_argument('old')
    sub.add_argument('--with', dest='new', required=True)
    sub.add_argument('--partial', metavar='RULE', nargs='?', const='', help='one rule of the old record: add the edge only')
    add('bd', 'run any bd command with your actor (board bd <args>)', None)
    sub = add('handover', 'comment the evidence and hand your item over for review', handover)
    sub.add_argument('id')
    sub.add_argument('evidence', type=nonempty)
    sub = add('return', 'return a claimed review to the work queue with its findings', return_item)
    sub.add_argument('id')
    sub.add_argument('findings', type=nonempty)
    for name, run, text in (('take', take, 'reassign held items to yourself (with a comment)'),
                            ('unclaim', unclaim, "free a hold, yours or another's (with a comment)")):
        add(name, text, run).add_argument('ids', nargs='+')
    add('help', 'every command with an example', None)

    args, extra = parser.parse_known_args(argv)
    if args.command == 'related' and not args.terms and args.like is None:
        commands.choices['related'].error('give terms, --like <draft>, or both')
    if extra:
        hint = next((word for word in extra if word in HEALTH_VIEWS), None)
        commands.choices[args.command].error(f"unrecognized arguments: {' '.join(extra)}"
                                             + (f'; for that list run board health --items {hint}' if hint else ''))
    if args.run is None:
        print(parser.format_usage().strip() + '\n')
        for name, sub in commands.choices.items():
            print(sub.format_usage().strip() + f'\n  {sub.description or ""}'.rstrip() + f'\n  example: {EXAMPLES[name]}')
        return 0
    args.root = getattr(args, 'root', None)
    try:
        board = Board.load()
        if args.run in (health, position, holders, check, related, queue, mine):
            code = budgeted(args.run, board, args, argv)
        else:
            code = args.run(board, args) or 0
        if args.run in (claim, handover, return_item, block, mine, queue):
            capacity(board, args)
        return code
    except BoardError as error:
        print(f'board: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
