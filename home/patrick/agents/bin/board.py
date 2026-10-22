#!/usr/bin/env python3
"""board: the agents' interface to a beads board (bd 1.3.1).

Run inside the repository. Views and hand-offs read one `bd export` snapshot;
`board bd <args>` runs any other bd command. Every bd call carries the caller's
actor (`derived_actor`) and, on a server-mode board, finds the server running.

Routing: skills/shared/work-tracking.md#routing; `ROLE_KINDS` and `Board.kind`
implement it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

IDLE_HOURS = 1  # held items without an update for longer are hinted as idle; confirm in use
POSITION_ROWS = 50  # rows per position section unless --all
SESSION_HOURS = 24  # position lists sessions registered this recently (plus any holding items)
PULLS = ('plan', 'design', 'implement', 'review')
KINDS = (*PULLS, 'question', 'accept', 'ratify')
WORK_TYPES = ('task', 'bug', 'spike')
# Kinds a bare `board claim` takes per role (agent: its pulls).
ROLE_KINDS = {'lead': ('question',), 'agent': None, 'solo': ('question', 'plan', 'ratify', 'accept'),
              'autopilot': ('question', 'plan', 'accept')}
# Kinds each role handles, by bare claim or by id; `board position` counts sessions from these.
ROLE_HANDLES = {'lead': ('question', 'accept', 'ratify'), 'agent': None,
                'solo': ('question', 'plan', 'ratify', 'accept'), 'autopilot': ('question', 'plan', 'accept')}
TEXT_FIELDS = ('title', 'description', 'design', 'acceptance_criteria', 'notes', 'close_reason')
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


class Board:
    def __init__(self, issues: list[dict]):
        self.issues = issues
        self.by_id = {issue['id']: issue for issue in issues}
        self.parent: dict[str, str] = {}
        self.children: dict[str, list[str]] = {}
        self.blockers: dict[str, list[str]] = {}  # waiting id -> ids it waits on
        self.dependents: dict[str, list[str]] = {}  # blocker id -> waiting ids
        self.linked: dict[str, set[str]] = {}  # id -> ids sharing any non-parent edge
        self.related: dict[str, set[str]] = {}  # relates-to, both ends
        for issue in issues:
            for dep in issue.get('dependencies') or []:
                waiting, target, kind = dep['issue_id'], dep['depends_on_id'], dep['type']
                if kind == 'parent-child':
                    self.parent[waiting] = target
                    self.children.setdefault(target, []).append(waiting)
                    continue
                self.linked.setdefault(waiting, set()).add(target)
                self.linked.setdefault(target, set()).add(waiting)
                if kind == 'blocks':
                    self.blockers.setdefault(waiting, []).append(target)
                    self.dependents.setdefault(target, []).append(waiting)
                elif kind == 'relates-to':
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
        return [issue for issue in self.issues if root in self.ancestors(issue['id'])]

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
        if kind == 'design':
            return 'design'
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
    shown = rows if limit is None else rows[:limit]
    for row in shown:
        print(row)
    if len(shown) < len(rows):
        print(f'  ... {len(rows) - len(shown)} more')


def by_priority(issue: dict):
    return (issue.get('priority', 9), issue.get('created_at') or '', issue['id'])


# Views

HEALTH_VIEWS = ('questions', 'decided', 'ratification', 'released', 'review', 'ready', 'held', 'blocked',
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
        'ready': ('claimable now (unassigned, unblocked)', [i for i in items if board.claimable(i)]),
        'held': ('held (assigned, not closed)', [i for i in items if i.get('assignee')]),
        'blocked': ('waiting on open blockers', [i for i in items if board.open_blockers(i['id'])]),
        'outside': ('outside any epic', [i for i in items if epic_of(i) is None]),
        'labels': ('lifecycle labels (use statuses, assignment or blocks)',
                   [i for i in items if set(i.get('labels') or []) & set(LIFECYCLE_LABELS)]),
    }
    for view, (name, rows) in views.items():
        print(f'{name}: {len(rows)}')
        if view == 'ready':
            counts = {kind: sum(1 for i in rows if board.claimable(i) == kind) for kind in KINDS}
            print('  by kind: ' + ', '.join(f'{pull} {count}' for pull, count in counts.items()))
        if view in args.items:
            for issue in sorted(rows, key=by_priority):
                print(line(issue, issue.get('assignee') or ''))
    found = deviations(board, args.root)
    if found:
        print(f'convention deviations: {len(found)} — run /board-migrate')


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
    limit = None if args.all else POSITION_ROWS
    section(f'sessions (registered within {SESSION_HOURS} h or holding items)',
            [f"  {entry.get('actor')}  {entry.get('role')}  {entry.get('tool') or 'tool unknown'}"
             f"  handles {','.join(session_kinds(entry, ROLE_HANDLES)) or '-'}  registered {age(parse_time(entry.get('registered_at')))} ago"
             f"  holds {sum(1 for issue in held if session_actor(issue['assignee']) == entry.get('actor'))}"
             for entry in sessions], limit)

    idle = []
    rows = []
    for issue in held:
        activity = board.last_activity(issue)
        is_idle = activity is None or (now - activity).total_seconds() > IDLE_HOURS * 3600
        row = line(issue, holder_label(issue['assignee'], known), f'updated {age(activity)} ago' + (' IDLE' if is_idle else ''))
        rows.append(row)
        if is_idle:
            idle.append(issue['id'])
    section('held items', rows, limit)
    if idle:
        print(f'  idle = no update for {IDLE_HOURS} h; quiet long jobs look idle too. '
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


# Conformance with skills/shared/work-tracking.md: mechanical classes only.
ACTOR = re.compile(r'[0-9a-f]{8}(/.+)?')
TITLE_PREFIXES = ('[Design]', '[Gate]', '[Checkpoint]', '[Review]')
RETIRED_TYPES = ('milestone', 'feature', 'chore', 'check')
CHECK_CLASSES = {  # class -> work-tracking anchor
    'holder': 'actors-and-holds',
    'retired-type': 'kinds',
    'title-prefix': 'kinds',
    'release-gate': 'kinds',
    'label-status': 'statuses-and-labels',
    'released-blocks': 'questions-and-rulings',
    'record-format': 'questions-and-rulings',
    'unnamed-blocker': 'dependencies',
}
RECORD_STATUSES = ('decided', 'released', 'needs_ratification')
RECORD_SECTIONS = ('Question', 'Alternatives Considered', 'Decision', 'Rationale', 'Rule owner')
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
        blockers = board.blockers.get(item_id, [])
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
        if kind == 'gate':
            gated = [d for d in board.dependents.get(item_id, []) if board.by_id.get(d, {}).get('issue_type') == 'decision']
            if title.startswith('[Gate] Release') or gated:
                found.append((item_id, 'release-gate', f"gates {', '.join(gated)}" if gated else 'release gate title'))
        labels = sorted(set(issue.get('labels') or []) & set(LIFECYCLE_LABELS))
        if labels:
            found.append((item_id, 'label-status', f"labels {', '.join(labels)}"))
        if kind == 'decision' and issue['status'] == 'released':
            found += [(item_id, 'released-blocks', f'released, still blocks {d}')
                      for d in board.dependents.get(item_id, []) if board.is_open(d)]
        if kind == 'decision' and issue['status'] in RECORD_STATUSES:
            description = issue.get('description') or ''
            missing = [name for name in RECORD_SECTIONS
                       if not re.search(rf'^##\s*{re.escape(name)}\s*$', description, re.MULTILINE | re.IGNORECASE)]
            if missing:
                found.append((item_id, 'record-format', f"lacks sections {', '.join(missing)}"))
        text = board.text(issue)
        # A gate carries its own reason (bd gate create --reason); a closed blocker holds nothing up.
        found += [(item_id, 'unnamed-blocker', f'waits on {b} without naming it') for b in blockers
                  if b not in text and board.is_open(b)
                  and board.by_id.get(b, {}).get('issue_type') != 'gate']
    return found


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
    limit = None if args.all else POSITION_ROWS
    found = deviations(board, args.root)
    print(f'convention deviations: {len(found)}')
    for name, anchor in CHECK_CLASSES.items():
        rows = [f'  {item_id}  {name}  work-tracking.md#{anchor}  {detail}'
                for item_id, kind, detail in found if kind == name]
        if rows:
            section(f'{name} (work-tracking.md#{anchor})', rows, limit)
    words = word_list()
    flags = squash_flags(board, args.root, words)
    note = '' if len(words) > len(EXTRA_WORDS) else f'; no word list at {WORD_LIST}, letter-digit runs only'
    section(f'flag, not a deviation: squashed text on open items{note}',
            [f'  {item_id}  squashed  {detail}' for item_id, detail in flags], limit)
    return 1 if found else 0


def related(board: Board, args) -> None:
    terms = [term.lower() for term in args.terms]
    rows = []
    for issue in board.issues:
        text = board.text(issue).lower()
        hits = [term for term in terms if term in text]
        if hits:
            rows.append((len(hits), issue))
    rows.sort(key=lambda pair: (-pair[0], pair[1]['status'] == 'closed', by_priority(pair[1])))
    section(f"items matching {', '.join(args.terms)} (all text fields, closed included)",
            [line(issue, f'{count}/{len(terms)} terms', issue.get('assignee') or 'unassigned') for count, issue in rows],
            args.limit)
    if args.docs:
        matches = []
        for root in args.docs:
            path = Path(root)
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
    ready = sorted((issue for issue in board.scoped(args.root) if board.claimable(issue)), key=by_priority)
    for kind in KINDS:
        section(kind, [line(issue, f"p{issue.get('priority', '?')}")
                       for issue in ready if board.claimable(issue) == kind], args.limit)


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
    section(f'held by session {session_actor(actor)}{you}',
            [line(issue, issue['assignee'], f'updated {age(board.last_activity(issue))} ago')
             for issue in held_by_session(board, actor) if issue['id'] in scoped])


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
        candidates = sorted((issue for issue in scoped if board.claimable(issue) in kinds), key=by_priority)
        for issue in candidates:
            if issue['status'] == 'in_review' and authorship(issue)[0] == actor:
                continue  # your own hand-over needs another reviewer
            ok, _ = claim_one(issue, actor)
            if ok:
                claimed.append(issue)
                break
        if not claimed:
            print(f"nothing claimable for {entry.get('role')} ({','.join(kinds)})")
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


def passthrough(argv: list[str]) -> int:
    if argv[:1] == ['dolt'] and argv[1:2] in (['start'], ['restart']):
        raise BoardError('board starts the server before every bd call; rerun the failing command with elevated sandbox permissions')
    directory = next((argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg in ('-C', '--directory')),
                     next((arg.split('=', 1)[1] for arg in argv if arg.startswith('--directory=')), None))
    ensure_server(Path(directory) if directory else None)
    os.execvpe('bd', ['bd', *argv], bd_env())


def release(board: Board, args) -> None:
    caller()
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

    operations = []
    for issue in rulings:
        operations.append(f"update {issue['id']} status=released assignee=\"\"")
        for waiting in board.dependents.get(issue['id'], []):
            # A released ruling never blocks; the link stays as context for the work protocol.
            operations += [f"dep remove {waiting} {issue['id']}", f"dep add {waiting} {issue['id']} relates-to"]
    bd_checked('batch', '-m', f"board release {' '.join(args.ids)}", '--json', stdin='\n'.join(operations) + '\n')
    for issue in rulings:
        print(f"released {issue['id']}: {issue.get('title', '')}")


def supersede(board: Board, args) -> None:
    caller()
    if args.old not in board.by_id:
        raise BoardError(f'unknown {args.old}')
    require_open(board, [args.new])
    # bd allows one edge per pair: drop an existing link between the two records first.
    operations = [f'dep remove {a} {b}' for a, b in ((args.old, args.new), (args.new, args.old))
                  if any(dep['depends_on_id'] == b and dep['type'] != 'parent-child'
                         for dep in board.by_id[a].get('dependencies') or [])]
    if args.partial:
        operations.append(f'dep add {args.old} {args.new} supersedes')
        items = []
    else:
        # The new record restates the whole rule: the old record's open items now follow it.
        items = sorted(i for i in board.related.get(args.old, set()) | set(board.dependents.get(args.old, []))
                       if i != args.new and board.is_open(i) and i not in board.linked.get(args.new, set()))
        operations += [f'dep add {item} {args.new} relates-to' for item in items]
    if operations:
        bd_checked('batch', '-m', f'board supersede {args.old} --with {args.new}', '--json',
                   stdin='\n'.join(operations) + '\n')
    if args.partial:
        print(f'{args.old}: one rule superseded by {args.new}')
        return
    bd_checked('supersede', args.old, '--with', args.new)
    print(f"superseded {args.old} by {args.new}; related {', '.join(items) or 'none'}")


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
    scope.add_argument('--root', metavar='EPIC', help='limit to items below this epic (default: whole board)')
    listing = argparse.ArgumentParser(add_help=False)
    listing.add_argument('--limit', type=int, default=50, help='rows per section (default 50)')
    commands = parser.add_subparsers(dest='command', required=True)

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

    sub = commands.add_parser('health', parents=[scope], help='counts')
    sub.add_argument('--items', type=views, default=set(), metavar='VIEW[,VIEW...]',
                     help=f"list the items behind these counts: {', '.join(HEALTH_VIEWS)}")
    sub.set_defaults(run=health)
    sub = commands.add_parser('position', parents=[scope], help='ready work vs sessions, held and idle items, '
                              'questions holding work, finished epics')
    sub.add_argument('--all', action='store_true', help=f'show every row (default: {POSITION_ROWS} per section)')
    sub.set_defaults(run=position)
    commands.add_parser('holders', parents=[scope, listing], help='items by open downstream work').set_defaults(run=holders)
    sub = commands.add_parser('check', parents=[scope], help='deviations from the work-tracking conventions')
    sub.add_argument('--all', action='store_true', help=f'show every row (default: {POSITION_ROWS} per section)')
    sub.set_defaults(run=check)
    sub = commands.add_parser('related', parents=[listing], help='items and doc lines mentioning terms')
    sub.add_argument('terms', nargs='+')
    sub.add_argument('--docs', nargs='+', default=[], metavar='PATH', help='canonical docs (files or directories of .md)')
    sub.set_defaults(run=related)
    commands.add_parser('queue', parents=[scope, listing], help='claimable work by pull').set_defaults(run=queue)
    sub = commands.add_parser('claim', parents=[scope], help='claim the next item routed to your role, or the given ids')
    sub.add_argument('ids', nargs='*')
    sub.set_defaults(run=claim)
    sub = commands.add_parser('release', help='release decided rulings in one bd batch')
    sub.add_argument('ids', nargs='+')
    sub.set_defaults(run=release)
    sub = commands.add_parser('supersede', help="supersede a ruling; a full replacement relates the old record's open items")
    sub.add_argument('old')
    sub.add_argument('--with', dest='new', required=True)
    sub.add_argument('--partial', action='store_true', help='one rule of the old record: add the edge only')
    sub.set_defaults(run=supersede)
    commands.add_parser('mine', parents=[scope], help="items held by this session and its workers").set_defaults(run=mine)
    commands.add_parser('bd', help='run any bd command with your actor (board bd <args>)')
    sub = commands.add_parser('handover', help='comment the evidence and hand your item over for review')
    sub.add_argument('id')
    sub.add_argument('evidence', type=nonempty)
    sub.set_defaults(run=handover)
    sub = commands.add_parser('return', help='return a claimed review to the work queue with its findings')
    sub.add_argument('id')
    sub.add_argument('findings', type=nonempty)
    sub.set_defaults(run=return_item)
    for name, run, text in (('take', take, 'reassign held items to yourself (with a comment)'),
                            ('unclaim', unclaim, "free a hold, yours or another's (with a comment)")):
        sub = commands.add_parser(name, help=text)
        sub.add_argument('ids', nargs='+')
        sub.set_defaults(run=run)

    args = parser.parse_args(argv)
    args.root = getattr(args, 'root', None)
    try:
        return args.run(Board.load(), args) or 0
    except BoardError as error:
        print(f'board: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
