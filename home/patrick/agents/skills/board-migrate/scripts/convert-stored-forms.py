#!/usr/bin/env python3
"""Convert the board's stored old forms to the current model, then write the model marker.

    convert-stored-forms.py            dry run: every change, and every form left for the user
    convert-stored-forms.py --apply    write the changes; it ends by planning again and exits 0 only when nothing is left to convert
    convert-stored-forms.py --mark     with nothing left to convert and `agents board check` clean: write the model marker
    convert-stored-forms.py --rehearse run the whole conversion on a copy of this board's export in a temporary board; this board is only read

Every write is a raw bd write, because the board's own write verbs refuse a board without the marker. A rerun finds
what is left, so an interruption needs no cleanup. The converter writes only what the model maps one to one: a case that
needs a choice is listed ("for the user:") and left for the agent to settle under the skill before --mark.
Identical writes of a phase go out as one multi-id `bd update` and one `bd batch`, and each phase reads the board once.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

BOARD = Path(__file__).resolve().parents[3] / 'bin' / 'board'  # agents/bin/board, beside agents/skills
MODEL_KEY, MODEL = 'custom.board.model', '1'
ACTOR = re.compile(r'[0-9a-f]{8}(/.+)?')
KIND_OF_TYPE = {'bug': 'bug', 'feature': 'feature', 'design': 'design', 'chore': 'cleanup', 'spike': None}  # old bd type -> its kind label (None: a plain task)
OLD_WAITS = ('waits-for', 'conditional-blocks')  # old spellings of a wait; bd's own `blocks` is the stored form
CONDITION = re.compile(r'\b(after|until|when|once|waits? on|blocked by)\b', re.IGNORECASE)  # a deferral reason that named a condition
HANDOVER = 'board handover: '
Step = tuple[str, Callable[[], None]]


class Stop(Exception):
    pass


def board(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([str(BOARD), *args], input=stdin, capture_output=True, text=True)


def read(*args: str) -> str:
    result = board(*args)
    if result.returncode:
        raise Stop(f"board {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def write(*args: str, stdin: str | None = None) -> str:
    result = board('bd', '--raw', '--yes', *args, stdin=stdin)
    if result.returncode:
        raise Stop(f"bd {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def snapshot() -> dict[str, dict]:
    rows = [json.loads(line) for line in read('bd', 'export').splitlines() if line.strip()]
    return {row['id']: row for row in rows if row.get('_type', 'issue') == 'issue'}


def meta(issue: dict) -> dict:
    return issue.get('metadata') if isinstance(issue.get('metadata'), dict) else {}


def edges(issue: dict) -> list[tuple[str, str]]:
    """(target, type) of the links this record starts."""
    return [(dep['depends_on_id'], dep.get('type') or 'blocks') for dep in issue.get('dependencies') or [] if dep.get('issue_id') == issue['id']]


class Board:
    def __init__(self) -> None:
        self.issues = snapshot()
        self.parents: dict[str, list[str]] = {}
        self.waiters: dict[str, list[str]] = {}  # target -> the live records waiting on it
        for issue in self.issues.values():
            for target, kind in edges(issue):
                if kind == 'parent-child':
                    self.parents.setdefault(issue['id'], []).append(target)
                elif kind in ('blocks', *OLD_WAITS) and issue['status'] != 'closed':
                    self.waiters.setdefault(target, []).append(issue['id'])

    def waits_on_decision(self, item_id: str, seen: set[str] | None = None) -> bool:
        """An open decision holds it, directly or through open blockers: the board keeps it out of a change request until that closes."""
        seen = set() if seen is None else seen
        for target, kind in edges(self.issues[item_id]):
            if kind == 'blocks' and target in self.issues and self.issues[target]['status'] != 'closed' and target not in seen:
                seen.add(target)
                if self.issues[target].get('issue_type') == 'decision' or self.waits_on_decision(target, seen):
                    return True
        return False

    def reaches(self, start: str, goal: str) -> bool:
        """Whether `start` depends on `goal` through waits or parenthood: a wait of `goal` on `start` would close a cycle bd refuses."""
        seen, todo = set(), [start]
        while todo:
            node = todo.pop()
            if node == goal:
                return True
            if node in seen or node not in self.issues:
                continue
            seen.add(node)
            todo += [target for target, kind in edges(self.issues[node]) if kind in ('blocks', 'parent-child')]  # bd's cycle check follows both, whatever the status
        return False

    def live(self) -> list[dict]:
        return [i for i in self.issues.values() if i['status'] != 'closed']

    def cr_of(self, item_id: str) -> str | None:
        return next((p for p in self.parents.get(item_id, []) if self.issues.get(p, {}).get('issue_type') == 'change-request'), None)

    def is_item(self, issue: dict) -> bool:
        return issue.get('issue_type') == 'task' and self.cr_of(issue['id']) is not None


class Update:
    """One record's `bd update`; the steps of a phase with the same flags go out as one call."""
    def __init__(self, item_id: str, *flags: str) -> None:
        self.item_id, self.flags = item_id, flags

    def __call__(self) -> None:
        write('update', self.item_id, *self.flags, '--json')


class Lines:
    """One record's `bd batch` lines; the steps of a phase go out as one batch."""
    def __init__(self, item_id: str, *lines: str) -> None:
        self.item_id, self.lines = item_id, lines

    def __call__(self) -> None:
        write('batch', '-m', f'board-migrate {self.item_id}', '--json', stdin='\n'.join(self.lines) + '\n')


def update(item_id: str, *flags: str) -> Update:
    return Update(item_id, *flags)


GROUP = 100  # ids or lines per grouped call


def apply_grouped(todo: list[tuple[str, Update | Lines]]) -> dict[str, str]:
    """Writes the grouped steps of a phase: records with the same update flags in one `bd update`, every batch line in one `bd batch`. A call that
    fails is retried one record at a time, so the record that bd refuses is named and the rest are written. Returns what failed, by step."""
    failed: dict[str, str] = {}
    updates: dict[tuple[str, ...], list[tuple[str, Update]]] = {}
    batches: list[tuple[str, Lines]] = []
    for what, action in todo:
        (updates.setdefault(action.flags, []) if isinstance(action, Update) else batches).append((what, action))
    calls: list[tuple[list[tuple[str, Update | Lines]], Callable[[], None]]] = []
    for flags, group in updates.items():
        for at in range(0, len(group), GROUP):
            part = group[at:at + GROUP]
            calls.append((part, lambda part=part, flags=flags: write('update', *(a.item_id for _, a in part), *flags, '--json')))
    for at in range(0, len(batches), GROUP):
        part = batches[at:at + GROUP]
        calls.append((part, lambda part=part: write('batch', '-m', 'board-migrate', '--json', stdin=''.join(line + '\n' for _, a in part for line in a.lines))))
    for part, call in calls:
        try:
            call()
        except Stop:
            for what, action in part:
                try:
                    action()
                except Stop as error:
                    failed[what] = str(error).splitlines()[0][:300]
    return failed


# Each phase reads a fresh snapshot and returns its steps: a line saying what, and the writes. Left: forms only the user can settle.

PLAN_FIRST = 'plan_first'  # a change request's mark that it needs planning before work (model.md, change request fields)
FILED_REASON = 'the earlier board kept this work outside any change request: plan what it commits before work starts'


def orphans(b: Board, status: str) -> list[dict]:
    """Change requests an interrupted run made and never gave their item: live, childless, in the status a run makes them in. A rerun reuses one
    instead of making a second."""
    parents = {p for ps in b.parents.values() for p in ps}
    return [i for i in b.live() if i.get('issue_type') == 'change-request' and i['id'] not in parents and i['status'] == status]


def take_orphan(free: list[dict], title: str) -> dict | None:
    """The first of `free` with this title, taken out of the list."""
    found = next((i for i in free if i.get('title') == title), None)
    if found:
        free.remove(found)
    return found


def files(b: Board, left: list[str]) -> list[Step]:
    """Work that commits something belongs to a change request: a work item outside any becomes the only item of one of its own, marked for planning."""
    steps = []
    free = [i for i in orphans(b, 'open') if PLAN_FIRST in meta(i)]
    for issue in b.live():
        item_id = issue['id']
        if (issue.get('issue_type') != 'task' or b.cr_of(item_id) or issue['status'] == 'deferred' or meta(issue).get('no_commit') is True
                or issue.get('assignee') == 'user' or b.waits_on_decision(item_id)):
            continue
        parents = [p for p in b.parents.get(item_id, []) if b.issues.get(p, {}).get('status') != 'closed']
        if parents:
            left.append(f'{item_id}: a work item outside any change request under {", ".join(parents)}; move it into a change request, or mark it no-commit')
            continue
        orphan = take_orphan(free, issue.get('title', item_id))
        steps.append((f'{item_id}: becomes the only item of a change request of its own, marked for planning', lambda issue=issue, orphan=orphan: file_item(issue, orphan['id'] if orphan else None)))
        left.append(f'{item_id}: a work item outside any change request became the only item of one of its own, marked {PLAN_FIRST}; plan the change request')
    return steps


def carried_labels(issue: dict) -> tuple[list[str], list[str]]:
    """(the labels a change request made from this record carries, the routing labels the record gives up: a child takes its parent's queue)"""
    routed = [label for label in issue.get('labels') or [] if label.startswith(('queue:', 'for:'))]
    return [label for label in issue.get('labels') or [] if label.startswith('topic:')] + routed, routed


def make_change_request(issue: dict, *extra: str) -> str:
    carried, _ = carried_labels(issue)
    return write('create', issue.get('title', issue['id']), '-t', 'change-request', '-d', str(issue.get('description') or issue.get('title') or issue['id']),
                 '--priority', str(issue.get('priority', 2)), '--silent', *extra, *(f'--labels={label}' for label in carried)).strip().splitlines()[-1]


def file_item(issue: dict, orphan: str | None) -> None:
    item_id = issue['id']
    _, routed = carried_labels(issue)
    cr = orphan or make_change_request(issue, '--metadata', json.dumps({PLAN_FIRST: FILED_REASON}))  # the item's parent is the only trace: a rerun finds it there
    write('update', item_id, '--parent', cr, *(flag for label in routed for flag in ('--remove-label', label)), '--json')


def holds(b: Board, left: list[str]) -> list[Step]:
    steps = []
    for issue in b.live():
        item_id, holder = issue['id'], issue.get('assignee') or ''
        if b.is_item(issue) and (holder or 'hold' in meta(issue)):
            if holder == 'user':
                left.append(f'{item_id}: an item of {b.cr_of(item_id)} was held by you, so its hold is cleared; a step only you take is a human gate (agents board gate create --blocks {b.cr_of(item_id)})')
            steps.append((f'{item_id}: the hold on an item is cleared (holder {holder or "none"})',
                          update(item_id, *(['--assignee', ''] if holder else []), *(['--unset-metadata', 'hold'] if 'hold' in meta(issue) else []))))
        elif holder and not ACTOR.fullmatch(holder) and not (holder == 'user' and issue.get('issue_type') == 'task'):
            steps.append((f'{item_id}: the legacy holder {holder} is cleared', update(item_id, '--assignee', '')))
    return steps


def kinds(b: Board, left: list[str]) -> list[Step]:
    steps = []
    for issue in b.live():
        label = KIND_OF_TYPE.get(issue.get('issue_type'), 0)
        if label != 0:
            steps.append((f'{issue["id"]}: type {issue["issue_type"]} becomes task' + (f' labelled kind:{label}' if label else ''),
                          update(issue['id'], '--type', 'task', *(['--add-label', f'kind:{label}'] if label else []))))
    return steps


def default_look() -> str:
    return json.loads(read('bd', 'config', 'get', '--json', 'custom.board.look') or '{}').get('value') or ''


def statuses(b: Board, left: list[str]) -> list[Step]:
    steps = []
    lost = orphans(b, 'deferred')
    for issue in b.live():
        item_id, kind, status = issue['id'], issue.get('issue_type'), issue['status']
        if status == 'in_progress':
            working = kind == 'change-request' and issue.get('assignee')  # a held change request is a hold on its work, which claim reads from `hold`
            steps.append((f'{item_id}: in_progress becomes open (the holder stays' + (', its hold is work)' if working else ')'),
                          update(item_id, '--status', 'open', *(['--set-metadata', 'hold=work'] if working else []))))
        elif status == 'needs_acceptance' and kind == 'change-request':
            own = meta(issue).get('look') or default_look()
            steps.append((f'{item_id}: needs_acceptance becomes passed' + ('' if own == 'before' else ' (look before: it waits for the Accept)'),
                          update(item_id, '--status', 'passed', *(['--set-metadata', 'look=before'] if own != 'before' else []))))
        elif status == 'in_review' and kind != 'change-request':
            steps.append((f'{item_id}: in_review becomes open (work outside a change request has no review)', update(item_id, '--status', 'open')))
        elif status == 'released' and kind == 'decision':
            steps.append((f'{item_id}: released becomes in_force', update(item_id, '--status', 'in_force')))
        elif status == 'needs_ratification' and kind == 'decision':
            steps.append((f'{item_id}: needs_ratification becomes in_force, with a question to confirm or revise it', lambda issue=issue: confirm_ruling(b, issue)))
            left.append(f'{item_id}: a ruling taken without your judgment stays in force; answer its "Confirm or revise" question')
        elif status == 'deferred' and b.is_item(issue):
            cr = b.cr_of(item_id)  # an item has no deferral of its own
            if b.issues[cr]['status'] == 'deferred':
                steps.append((f'{item_id}: open again, the deferral of {cr} holds it',
                              update(item_id, '--status', 'open', '--defer', '', '--unset-metadata', 'revisit', '--unset-metadata', 'deferred_by')))
            else:
                orphan = take_orphan(lost, issue.get('title', item_id))
                steps.append((f'{item_id}: leaves {cr} as the only item of a deferred change request of its own, related to {cr}',
                              lambda issue=issue, cr=cr, orphan=orphan: leave_deferred(issue, cr, orphan)))
                left.append(f'{item_id}: a deferred item of {cr} is now the only item of a deferred change request of its own, related to {cr}; undefer it when it is due')
    return steps


def revisit_day(until: str) -> str | None:
    try:
        return datetime.fromisoformat(until.replace('Z', '+00:00')).astimezone().date().isoformat()
    except ValueError:
        return None


def leave_deferred(issue: dict, cr: str, orphan: dict | None) -> None:
    """An item has no deferral of its own: it leaves its live change request as the only item of a deferred one, related to the old. The new request
    is made and linked first and the item moves last, so an interruption leaves a childless request the rerun reuses."""
    item_id = issue['id']
    _, routed = carried_labels(issue)
    revisit = meta(issue).get('revisit') or (revisit_day(issue['defer_until']) if issue.get('defer_until') else None)
    new = orphan['id'] if orphan else make_change_request(issue)
    write('update', new, '--status', 'deferred', *(['--set-metadata', f'revisit={revisit}'] if revisit else []),
          *(['--set-metadata', f'deferred_by={meta(issue)["deferred_by"]}'] if meta(issue).get('deferred_by') else []), '--json')
    if not orphan or (cr, 'relates-to') not in edges(orphan):
        write('batch', '-m', f'board-migrate {item_id}', '--json', stdin=f'dep add {new} {cr} relates-to\n')
    write('update', item_id, '--parent', new, '--status', 'open', '--defer', '', '--unset-metadata', 'revisit', '--unset-metadata', 'deferred_by',
          *(flag for label in routed for flag in ('--remove-label', label)), '--json')


def confirm_ruling(b: Board, issue: dict) -> None:
    """What `ruling record --unratified` writes: the ruling in force and an ordinary question that relates to it. The question goes first, so a rerun finds it."""
    item_id = issue['id']
    found = re.search(r'^##\s+Reversal\s*\n(.*?)(?=^##\s|\Z)', str(issue.get('description') or ''), re.MULTILINE | re.DOTALL | re.IGNORECASE)
    reversal = found.group(1).strip() if found else 'Reversal: not recorded.'
    found_question = next((i for i in b.live() if i.get('external_ref') == f'confirm:{item_id}'), None)
    question = found_question['id'] if found_question else None
    if question is None:
        question = write('create', f'Confirm or revise: {issue.get("title", "")}?', '-t', 'decision', '-d', f'## Question\nConfirm ruling {item_id} or revise it?\n\n{reversal}\n',
                         '--priority', str(issue.get('priority', 2)), '--external-ref', f'confirm:{item_id}', '--silent', *([] if b.parents.get(item_id) else shared_queue()),
                         *(['--parent', b.parents[item_id][0]] if b.parents.get(item_id) else []),
                         *(f'--labels={label}' for label in issue.get('labels') or [] if label.startswith('topic:'))).strip().splitlines()[-1]
    if not found_question or (item_id, 'relates-to') not in edges(found_question):  # a stop between the create and the link leaves the question unlinked
        write('batch', '-m', f'board-migrate {item_id}', '--json', stdin=f'dep add {question} {item_id} relates-to\n')
    write('update', item_id, '--status', 'in_force', '--json')


def authors(b: Board, left: list[str]) -> list[Step]:
    steps = []
    for issue in b.live():
        if issue.get('issue_type') != 'change-request' or issue['status'] != 'in_review' or meta(issue).get('author'):
            continue
        who = handed_over_by(issue)
        if who:
            steps.append((f'{issue["id"]}: author {who} recorded from its hand-over', update(issue['id'], '--set-metadata', f'author={who}')))
        else:
            left.append(f'{issue["id"]}: in review with no recorded author, so its self-review check fails closed; another session reviews it, or the user passes it')
    return steps


def handed_over_by(issue: dict) -> str | None:
    """What the old code read: the newest hand-over comment by an actor, else bd's status history, else the holder of record."""
    shown = board('show', issue['id'], '--json')
    try:
        notes = (json.loads(shown.stdout or '{}').get(issue['id']) or {}).get('comments') or [] if shown.returncode == 0 else []
    except ValueError:
        notes = []
    for note in sorted(notes, key=lambda c: c.get('created_at') or '', reverse=True):
        if str(note.get('text') or '').startswith(HANDOVER) and ACTOR.fullmatch(note.get('author') or ''):
            return note['author']
    history = board('bd', 'history', issue['id'], '--events', '--json')
    try:
        events = json.loads(history.stdout or '[]') if history.returncode == 0 else []
    except ValueError:
        events = []
    for event in events:
        try:
            status = json.loads(event.get('new_value') or '{}').get('status')
        except (ValueError, AttributeError):
            continue
        if event.get('event_type') == 'status_changed' and status == 'in_review' and ACTOR.fullmatch(event.get('actor') or ''):
            return event['actor']
    holder = issue.get('assignee') or ''
    return holder if ACTOR.fullmatch(holder) else None


def links(b: Board, left: list[str]) -> list[Step]:
    steps = []
    for issue in b.live():
        item_id = issue['id']
        for target, kind in edges(issue):
            if issue.get('issue_type') == 'milestone' and kind in ('blocks', *OLD_WAITS):
                part = b.issues.get(target, {})
                if part.get('issue_type') == 'change-request' and not [p for p in b.parents.get(target, []) if p != item_id]:
                    steps.append((f'{item_id}: its wait on {target} becomes membership ({target} is part of the milestone)',
                                  Lines(item_id, f'dep remove {item_id} {target}', f'dep add {target} {item_id} parent-child')))
                else:
                    left.append(f'{item_id}: a milestone waits on {target} ({part.get("issue_type")}), which cannot be part of it: put the work in a change request and move that in, or drop the wait')
            elif kind in OLD_WAITS:
                def wait(i=item_id, t=target, k=kind) -> None:
                    write('batch', '-m', f'board-migrate {i}', '--json', stdin=f'dep remove {i} {t}\ndep add {i} {t} blocks\n')
                    write('comments', 'add', i, f'Waits on {t} for an earlier {k} link; the reason is not recorded')
                steps.append((f'{item_id}: the {kind} link to {target} becomes a wait', wait))
            elif kind == 'discovered-from':
                def found(i=item_id, t=target) -> None:
                    write('update', i, '--set-metadata', f'found_in={t}', '--json')
                    write('dep', 'remove', i, t)
                steps.append((f'{item_id}: discovered-from {target} becomes the found_in field', found))
            elif kind == 'related':
                steps.append((f'{item_id}: related {target} becomes relates-to', Lines(item_id, f'dep remove {item_id} {target}', f'dep add {item_id} {target} relates-to')))
    return steps


def dates(b: Board, left: list[str]) -> list[Step]:
    steps = []
    for issue in b.live():
        until = issue.get('defer_until')
        if until and not b.is_item(issue):
            try:
                moment = datetime.fromisoformat(until.replace('Z', '+00:00')).astimezone()
            except ValueError:
                left.append(f'{issue["id"]}: defer_until {until!r} is not a date; set its revisit date by hand')
                continue
            if issue['status'] != 'deferred' and not (moment > datetime.now().astimezone() and issue['status'] == 'open' and not issue.get('assignee')):
                continue  # bd keeps defer_until on a record put back to work: a live record is not parked by a stale date
            day = moment.date().isoformat()
            steps.append((f'{issue["id"]}: defer_until {until} becomes revisit {day}',  # bd's own date wakes a record, so it leaves bd; clearing it reopens, so the status goes with it
                          update(issue['id'], '--set-metadata', f'revisit={day}', '--defer', '', '--status', 'deferred')))
    return steps


def deferrals(b: Board, left: list[str]) -> list[Step]:
    """A deferral whose reason named a condition (the words the old check refused) on open records is a wait; a deferral set aside is someday."""
    steps = []
    for issue in b.live():
        item_id = issue['id']
        reason = str(issue.get('notes') or '')
        if issue['status'] != 'deferred' or issue.get('defer_until') or b.is_item(issue) or issue.get('issue_type') == 'milestone' or not CONDITION.search(reason):
            continue
        named = [i for i in dict.fromkeys(re.findall(r'[a-z][a-z0-9]*-[a-z0-9]{3,}(?:\.\d+)*', reason))
                 if i in b.issues and i != item_id and b.issues[i]['status'] not in ('closed', 'deferred')]
        cyclic = [target for target in named if b.reaches(target, item_id)]
        named = [target for target in named if target not in cyclic]
        if cyclic:
            left.append(f'{item_id}: its deferral condition names {", ".join(cyclic)}, which already wait on it: a wait would form a cycle, so none is written for them')
        if not named:
            if cyclic:
                continue
            left.append(f'{item_id}: deferred on a condition no open record carries ("{reason[:100]}"); it stays set aside, or wait it on what it needs')
            continue

        def wait(i=item_id, targets=named, why=reason) -> None:
            present = {t for t, _ in edges(b.issues[i])}
            for target in targets:  # the record reopens last: an interruption leaves it deferred, found again
                if target not in present:
                    write('comments', 'add', i, f'Waits on {target} for {why[:300]}')
                    write('batch', '-m', f'board-migrate {i}', '--json', stdin=f'dep add {i} {target} blocks\n')
            write('update', i, '--status', 'open', '--json')
        steps.append((f'{item_id}: the deferral condition becomes a wait on {", ".join(named)} (open again)', wait))
        left.append(f'{item_id}: its deferral condition became a wait on {", ".join(named)}; check the wait says what you meant')
    return steps


def outcomes(b: Board, left: list[str]) -> list[Step]:
    steps = []
    for issue in b.issues.values():
        item_id, kind = issue['id'], issue.get('issue_type')
        if issue['status'] != 'closed':
            if 'outcome' in meta(issue):
                steps.append((f'{item_id}: an open record carries no outcome', update(item_id, '--unset-metadata', 'outcome')))
        elif 'outcome' not in meta(issue):
            outcome = {'gate': 'resolved', 'milestone': 'accepted'}.get(kind)
            if kind == 'decision':
                outcome = 'superseded' if any(k == 'supersedes' for _, k in edges(issue)) \
                    else 'planned' if re.match(r'\s*planned in\b', str(issue.get('close_reason') or ''), re.IGNORECASE) else 'dropped'
            if outcome:
                steps.append((f'{item_id}: closed {kind}, outcome {outcome}', update(item_id, '--set-metadata', f'outcome={outcome}')))
    return steps


def epics(b: Board, left: list[str]) -> list[Step]:
    steps = []
    for epic in b.live():
        if epic.get('issue_type') != 'epic':
            continue
        topics = [label for label in epic.get('labels') or [] if label.startswith('topic:')]
        topic = topics[0] if topics else 'topic:' + (re.sub(r'[^a-z0-9]+', '-', epic.get('title', '').lower()).strip('-') or epic['id'])
        for child in b.live():
            if epic['id'] in b.parents.get(child['id'], []) and topic not in (child.get('labels') or []):
                steps.append((f'{child["id"]}: topic label {topic} from epic {epic["id"]}', update(child['id'], '--add-label', topic)))
        steps.append((f'{epic["id"]}: epic closed, its children carry {topic}',
                      lambda e=epic['id'], t=topic: write('close', e, '--force', '--reason', f'board-migrate: the epic is retired, its children carry {t}')))
    return steps


def shared_person() -> str | None:
    """The board's person on a shared board (whose queue holds what is for the user), else None."""
    if not json.loads(read('bd', 'config', 'get', '--json', 'custom.board.shared') or '{}').get('value'):
        return None
    person = subprocess.run(['git', 'config', 'agents.person'], capture_output=True, text=True).stdout.strip()
    if not person:
        raise Stop('this board is shared: set the person first (git config agents.person <name>)')
    return person


def shared_queue() -> list[str]:
    person = shared_person()
    return ['--labels', f'queue:{person}'] if person else []


def ratifications(b: Board, left: list[str]) -> list[Step]:
    """An open design or landing ratification has no place in the model (ratify is of choices): the agent resolves each before --mark."""
    for old in b.live():
        if old['status'] == 'needs_ratification' and old.get('issue_type') != 'decision':
            cr = b.issues.get(b.cr_of(old['id']) or '', {})
            form = meta(old).get('ratification') or ('landing' if 'landing' in old.get('title', '').lower() else 'design')
            left.append(f'{old["id"]}: an open {form} ratification of {cr.get("id", "a change request")} ("{old.get("title", "")}"); resolve it under the skill before --mark')
    return []


def human_gates(b: Board, left: list[str]) -> list[Step]:
    """A gate that is not a human gate, or an item assigned to the user, becomes a human gate of the same title that supersedes it."""
    steps = []
    for old in b.live():
        kind, item_id = old.get('issue_type'), old['id']
        if kind == 'gate' and old.get('await_type') == 'human':
            if re.match(r'user\s', old.get('title', ''), re.IGNORECASE):
                steps.append((f'{item_id}: the gate title loses its "user " prefix', update(item_id, '--title', old['title'][5:].strip())))
            continue
        user_item = kind == 'task' and old.get('assignee') == 'user' and not b.cr_of(item_id)
        if not (user_item or kind == 'gate'):
            continue
        if kind == 'gate' and old.get('await_type'):
            left.append(f'{item_id}: a {old["await_type"]} gate is no step a person takes; resolve or drop it')
            continue
        title = re.sub(r'^user\s+', '', old.get('title', ''), flags=re.IGNORECASE).strip() or old.get('title', '')
        steps.append((f'{item_id}: becomes a human gate "{title}" that supersedes it', lambda old=old, title=title: regate(b, old, title)))
    return steps


def regate(now: Board, old: dict, title: str) -> None:
    item_id = old['id']
    human = [g for g in now.issues.values() if g.get('issue_type') == 'gate' and g.get('await_type') == 'human' and g['status'] != 'closed']
    gate = next((g['id'] for g in human if (item_id, 'supersedes') in edges(g)), None)  # an earlier run got as far as the links
    if gate is None:
        gate = next((g['id'] for g in human if g.get('title') == title and (g['id'], 'blocks') in edges(now.issues[item_id])), None)  # ...or only as far as the gate: one with the title this run gave it, not any human gate the old record waited on
        if gate is None:  # the gate is made holding up the old record, whose waiters then move to it
            made = write('gate', 'create', '--type=human', '--blocks', item_id, '--reason', (str(old.get('description') or '') or title)[:500], '--title', title)
            found = re.search(r'Created gate (\S+)', made)
            if not found:
                raise Stop(f'bd gate create for {item_id} printed no gate id: {made.strip()[:200]}')
            gate = found.group(1)
        person = shared_person()
        labels = [label for label in old.get('labels') or [] if label.startswith(('queue:', 'for:', 'topic:'))]
        if person and not any(label.startswith('for:') for label in labels):
            labels.append(f'for:{person}')
        if labels:
            write('update', gate, *(flag for label in labels for flag in ('--add-label', label)), '--json')
        lines = []
        for waiter in now.waiters.get(item_id, []):
            if waiter != gate:
                lines += [f'dep remove {waiter} {item_id}', f'dep add {waiter} {gate} blocks']
        lines += [f'dep remove {item_id} {gate}', f'dep add {gate} {item_id} supersedes']
        write('batch', '-m', f'board-migrate {item_id}', '--json', stdin='\n'.join(lines) + '\n')
    write('update', item_id, '--set-metadata', f'outcome={"resolved" if old.get("issue_type") == "gate" else "dropped"}', '--assignee', '', '--json')
    write('close', item_id, '--force', '--reason', f'board-migrate: replaced by the human gate {gate}')


def rulings(b: Board, left: list[str]) -> list[Step]:
    """An in-force ruling waits only for its planning, a question not yet in force or a human gate. The old board also let it wait on a design or spike:
    each such wait becomes a relates-to link (the planner makes the work wait on that design, plan.md), and the ruling is listed for planning."""
    steps, planned = [], []
    for ruling in b.live():
        if ruling.get('issue_type') != 'decision' or ruling['status'] != 'in_force':
            continue
        for target, kind in edges(ruling):
            other = b.issues.get(target)
            if kind != 'blocks' or other is None or other['status'] == 'closed':
                continue
            planning = (other.get('issue_type') == 'gate' and other.get('await_type') == 'human') or (other.get('issue_type') == 'decision' and other['status'] in ('open', 'decided'))
            if planning:
                continue
            steps.append((f'{ruling["id"]}: its wait on {target} becomes relates-to', Lines(ruling['id'], f'dep remove {ruling["id"]} {target}', f'dep add {ruling["id"]} {target} relates-to')))
            planned.append(ruling['id'])
    if planned:
        left.append(f'{len(steps)} wait(s) of in-force rulings on work became relates-to links; plan each ruling and make its work wait on the related design (rulings: {", ".join(dict.fromkeys(planned))})')
    return steps


RETIRED_METADATA = {'no_code': 'no_commit', 'triaged_tip': None, 'triaged_base_tip': None}  # keys the board once wrote: their new name, or none


def retired_metadata(b: Board, left: list[str]) -> list[Step]:
    """Metadata keys an earlier board wrote: dropped, or moved to the key that replaced them (no_code is no_commit on work items only)."""
    steps = []
    for issue in b.live():
        retired = sorted(set(meta(issue)) & set(RETIRED_METADATA))
        if retired:
            moved = sorted({RETIRED_METADATA[key] for key in retired if RETIRED_METADATA[key] and issue.get('issue_type') == 'task'})
            steps.append((f"{issue['id']}: retired metadata {', '.join(retired)} dropped{''.join(f'; {new} set' for new in moved)}",
                          update(issue['id'], *(flag for new in moved for flag in ('--set-metadata', f'{new}=true')), *(flag for key in retired for flag in ('--unset-metadata', key)))))
    return steps


PHASES = (kinds, retired_metadata, statuses, epics, deferrals, files, holds, authors, dates, outcomes, links, ratifications, human_gates, rulings)  # kinds first: an item is a task in a change request


def check_status_custom() -> None:
    value = json.loads(read('bd', 'config', 'get', '--json', 'status.custom') or '{}').get('value') or ''
    missing = [name for name in ('decided', 'in_force', 'passed') if f'{name}:' not in value]
    if missing:
        raise Stop(f'status.custom lacks {", ".join(missing)}: run agents board setup first')


FAILED: dict[str, str] = {}  # step -> why it stopped; the run goes on with the rest
BY_KIND: dict[str, int] = {}  # conversions per phase of the last run


def run(apply: bool) -> tuple[int, list[str]]:
    """Every phase on a fresh snapshot; returns the steps found (applied when `apply`) and the forms left for the user."""
    found, left = 0, []
    BY_KIND.clear()
    for phase in PHASES:
        steps = phase(Board(), left)
        if steps:
            BY_KIND[phase.__name__] = len([what for what, _ in steps if what not in FAILED])
        todo = [(what, step) for what, step in steps if what not in FAILED]  # a step that failed this run is reported at the end, not found again
        for what, _ in todo:
            print(('' if apply else 'would: ') + what)
        if apply:
            failed = apply_grouped([(what, step) for what, step in todo if isinstance(step, (Update, Lines))])
            for what, step in todo:
                if what in failed:
                    FAILED[what] = failed[what]
                elif not isinstance(step, (Update, Lines)):
                    try:
                        step()
                    except Stop as error:
                        FAILED[what] = 'bd refused it: the wait would form a cycle' if 'cycle' in str(error) else str(error).splitlines()[0][:300]
            for what, _ in todo:
                if what in FAILED:
                    print(f'  not converted: {what}: {FAILED[what]}')
        found += len([what for what, _ in todo if what not in FAILED])
    return found, list(dict.fromkeys(left))


def rehearse() -> int:
    """The export of this board, imported into a temporary board of its own and taken through the whole flow there: setup, the conversion, the checkpoint
    conversion, check, and a mark that shows what blocks it. Nothing of this board is written. The copy has the branches this checkout has for live change
    requests (at its HEAD) and a worktree for each that has one here."""
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # a kill unwinds through the cleanup below
    exported = read('bd', 'export')
    setting = lambda key: json.loads(read('bd', 'config', 'get', '--json', key) or '{}').get('value') or ''
    prefix, carried = setting('issue_prefix'), {name: setting(f'custom.board.{name}') for name in ('target', 'setup', 'checks', 'look', 'view')}
    env = {key: value for key, value in os.environ.items()  # the copy must never be this board, and it is worked as a person's
           if key not in ('BEADS_DIR', 'BEADS_DB', 'BEADS_ACTOR', 'CODEX_SESSION_ID', 'CODEX_THREAD_ID', 'CLAUDE_CODE_SESSION_ID')}
    here = Path(__file__).resolve()
    checkpoints = here.with_name('convert-design-checkpoints.py')
    rows = [json.loads(line) for line in exported.splitlines() if line.strip()]
    branches = [row['id'] for row in rows if row.get('issue_type') == 'change-request' and row.get('status') not in ('closed', None)
                and subprocess.run(['git', 'rev-parse', '--verify', '-q', f'refs/heads/cr/{row["id"]}'], capture_output=True).returncode == 0]
    common = subprocess.run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'], capture_output=True, text=True).stdout.strip()
    main_tree = Path(common).parent if common else Path.cwd()
    worktrees = [cr for cr in branches if (main_tree / '.worktrees' / cr / '.git').is_file()]
    # A SIGTERM must find everything it has to undo already recorded: it is held back while a child is spawned or the folder made, and delivered
    # once they are recorded, so no child (and no server it would start) and no folder is left unknown to the cleanup below.
    children: list[subprocess.Popen] = []
    folder = ''
    held = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
    try:
        folder = tempfile.mkdtemp(prefix='board-rehearsal-')
        signal.pthread_sigmask(signal.SIG_SETMASK, held)  # a pending SIGTERM unwinds from here, into the cleanup

        def run(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
            held = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
            try:
                child = subprocess.Popen(args, cwd=folder, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
                                         start_new_session=True)  # its own group: the cleanup kills it with everything it spawned
                children.append(child)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, held)
            out, err = child.communicate(stdin)
            children.remove(child)
            return subprocess.CompletedProcess(args, child.returncode, out, err)

        def on_copy(*args: str) -> str:
            result = run(str(BOARD), *args)
            if result.returncode:
                raise Stop(f"on the copy: board {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}")
            return result.stdout

        for command in (['git', 'init', '-q', '-b', 'main'], ['git', '-c', 'user.name=rehearsal', '-c', 'user.email=rehearsal@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'copy'],
                        *(['git', 'branch', f'cr/{cr}'] for cr in branches), *(['git', 'worktree', 'add', '-q', f'.worktrees/{cr}', f'cr/{cr}'] for cr in worktrees)):
            run(*command)
        on_copy('setup', *(['--prefix', prefix] if prefix else []))  # a server board, like the real ones: embedded calls cost four times as much
        current = json.loads(on_copy('bd', 'config', 'get', '--json', 'status.custom') or '{}').get('value') or ''
        # the copy takes the old statuses too, then setup puts the current list back
        on_copy('bd', '--raw', '--yes', 'config', 'set', 'status.custom', f'{current},released:active,needs_ratification:wip,needs_acceptance:wip')
        types = json.loads(on_copy('bd', 'config', 'get', '--json', 'types.custom') or '{}').get('value') or ''
        on_copy('bd', '--raw', '--yes', 'config', 'set', 'types.custom', f'{types},design')  # the import reads design-typed records of the export; the setup below puts the current list back, so the copy keeps no old type
        for name, value in carried.items():
            if value:
                on_copy('bd', '--raw', '--yes', 'config', 'set', f'custom.board.{name}', value)
        Path(folder, 'export.jsonl').write_text(exported, encoding='utf-8')
        on_copy('bd', '--raw', '--yes', 'import', str(Path(folder, 'export.jsonl')))
        on_copy('setup')
        on_copy('bd', '--raw', '--yes', 'config', 'unset', MODEL_KEY)
        mapping = Path(folder, 'checkpoint-mapping.json')
        detail = {}
        detail['conversion'] = run(sys.executable, '-B', str(here), '--apply')
        inventory = run(sys.executable, '-B', str(checkpoints), 'inventory', '--mapping', str(mapping))
        detail['checkpoint inventory'] = inventory
        if mapping.is_file():
            approved = json.loads(mapping.read_text(encoding='utf-8'))
            approved['approved_by'] = 'rehearsal'
            mapping.write_text(json.dumps(approved), encoding='utf-8')
            detail['checkpoint conversion'] = run(sys.executable, '-B', str(checkpoints), 'apply', str(mapping), '--apply', '--copy')
            detail['checkpoint verify'] = run(sys.executable, '-B', str(checkpoints), 'verify')
        detail['check'] = run(str(BOARD), 'check', '--limit', '0')
        detail['mark'] = run(sys.executable, '-B', str(here), '--mark')
        found = json.loads(run(str(BOARD), 'check', '--json').stdout or '{}').get('deviations') or []
    finally:  # every way out: stop what is still running, stop the copy's server (its command line names the folder), then the folder goes
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
        for child in children:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        if folder:
            quiet = 0
            for _ in range(240):  # until the server stays gone: one still starting when the stop came shows up in the next round
                subprocess.run([str(BOARD), 'bd', '--raw', '--yes', 'dolt', 'stop'], cwd=folder, capture_output=True, env=env)
                subprocess.run(['pkill', '-f', folder], capture_output=True)
                quiet = quiet + 1 if subprocess.run(['pgrep', '-f', folder], capture_output=True).returncode != 0 else 0
                if quiet == 2:
                    break
                time.sleep(0.25)
            shutil.rmtree(folder, ignore_errors=True)
    classes: dict[str, int] = {}
    for row in found:
        classes[row['class']] = classes.get(row['class'], 0) + 1
    converted = detail['conversion'].stdout
    print(f'rehearsal on a copy of {len(rows)} export rows; this board is not written')
    print('--- summary')
    print('conversion: ' + next((line for line in converted.splitlines() if 'conversion(s)' in line), f'stopped: {detail["conversion"].stderr.strip()[:300]}'))
    print(next((line for line in converted.splitlines() if line.startswith('by kind: ')), 'by kind: none'))
    print('deviations after: ' + (', '.join(f'{name} {count}' for name, count in classes.items()) or 'none'))
    marked = detail['mark']
    print('mark: ' + ('would be written' if marked.returncode == 0 else 'blocked'))
    for line in (marked.stderr + marked.stdout).strip().splitlines() if marked.returncode else []:
        print(f'  blocks: {line}')
    for line in converted.splitlines():
        if line.startswith('for the user: '):
            print(f'  {line}')
    for title, result in detail.items():
        print(f'--- {title} (exit {result.returncode})\n{(result.stdout + result.stderr).strip()}')
    return 0


def mark() -> int:
    with contextlib.redirect_stdout(io.StringIO()):  # only the count matters here
        found, left = run(False)
    if found:
        print(f'{found} conversion(s) remain: run convert-stored-forms.py --apply first', file=sys.stderr)
        return 1
    deviations = json.loads(read('check', '--json'))['deviations']
    if deviations:
        for row in deviations:
            print(f"{row['id']}  {row['class']}  {row['detail']}", file=sys.stderr)
        print(f'agents board check reports {len(deviations)} deviation(s): settle them, then rerun --mark', file=sys.stderr)
        return 1
    write('config', 'set', MODEL_KEY, MODEL)
    committed = board('bd', '--raw', '--yes', 'dolt', 'commit', '-m', 'board-migrate: model marker')
    if committed.returncode and 'nothing to commit' not in (committed.stdout + committed.stderr).lower():
        raise Stop(f'the marker is set but not committed: {(committed.stderr or committed.stdout).strip()}')
    print(f'{MODEL_KEY} = {MODEL}')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='write the conversions')
    mode.add_argument('--mark', action='store_true', help='write the model marker once nothing is left and check is clean')
    mode.add_argument('--rehearse', action='store_true', help='convert a copy of this board in a temporary board and report; writes nothing here')
    args = parser.parse_args()
    try:
        if args.rehearse:
            return rehearse()  # the copy gets the current statuses from setup; this board may still lack them
        check_status_custom()
        if args.mark:
            return mark()
        found, left = run(args.apply)
        kinds = dict(BY_KIND)
        if args.apply:
            again, rest = run(False)
            left = list(dict.fromkeys([*left, *rest]))  # what the conversions listed, and what is still open after them
            if again:
                print(f'{again} conversion(s) still found after applying; rerun, or settle them by hand', file=sys.stderr)
                for row in left:
                    print(f'for the user: {row}')
                for what, why in FAILED.items():
                    print(f'for the user: not converted, {what}: {why}')
                return 1
        print(f'{found} conversion(s) {"applied" if args.apply else "found"}')
        if kinds:
            print('by kind: ' + ', '.join(f'{name} {count}' for name, count in kinds.items()))
    except Stop as error:
        print(f'convert-stored-forms stopped: {error}', file=sys.stderr)
        return 1
    for row in left:
        print(f'for the user: {row}')
    for what, why in FAILED.items():
        print(f'for the user: not converted, {what}: {why}')
    return 1 if FAILED else 0


if __name__ == '__main__':
    raise SystemExit(main())
