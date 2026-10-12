#!/usr/bin/env python3
"""Report goal-relay counts and board drift for a beads board.

Usage: board-health [<root epic>]   (run inside the repository; scope = everything below the root epic)
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

IN_FLIGHT_MINUTES = 25


def load_issues():
    out = subprocess.run(['bd', 'list', '--all', '--limit', '0', '--json'], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def started_at(issue_id):
    out = subprocess.run(['bd', 'show', issue_id, '--json'], check=True, capture_output=True, text=True).stdout
    issue = json.loads(out)
    issue = issue[0] if isinstance(issue, list) else issue
    return issue.get('started_at')


def parse_time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def main():
    issues = load_issues()
    by_id = {issue['id']: issue for issue in issues}

    def ancestors(issue):
        parent = issue.get('parent')
        while parent and parent in by_id:
            yield by_id[parent]
            parent = by_id[parent].get('parent')

    scope_root = sys.argv[1] if len(sys.argv) > 1 else None
    if scope_root is not None and scope_root not in by_id:
        sys.exit(f'board-health: unknown epic {scope_root}')

    scoped = [issue for issue in issues if scope_root is None or any(a['id'] == scope_root for a in ancestors(issue))]
    open_items = [issue for issue in scoped if issue['status'] != 'closed' and issue['issue_type'] != 'epic']

    def labels(issue):
        return issue.get('labels') or []

    counts = {
        'pending decisions (decided)': [i for i in open_items if 'decided' in labels(i)],
        'open questions (human)': [i for i in open_items if 'human' in labels(i)],
        'released, not landed': [i for i in open_items if i['issue_type'] == 'decision' and i.get('assignee') == 'goal-agent'],
        'review inbox (goal-lead)': [i for i in open_items if 'review' in labels(i) and i.get('assignee') == 'goal-lead'],
        'dispatch queue (unassigned open)': [i for i in open_items if not i.get('assignee') and i['status'] == 'open'],
    }
    for name, items in counts.items():
        print(f'{name}: {len(items)}')

    def epic_of(issue):
        return next((a for a in ancestors(issue) if a['issue_type'] == 'epic'), None)

    outside_epic = [i['id'] for i in issues if i['status'] != 'closed' and i['issue_type'] != 'epic' and epic_of(i) is None]

    def open_blockers(issue):
        return [d['depends_on_id'] for d in issue.get('dependencies') or []
                if d['type'] == 'blocks' and by_id.get(d['depends_on_id'], {}).get('status') not in (None, 'closed')]

    waiting = [f"{i['id']} ({len(open_blockers(i))} open blockers)" for i in open_items if 'waiting' in labels(i)]

    now = datetime.now(timezone.utc)
    in_flight = []
    for issue in open_items:
        if issue['status'] != 'in_progress':
            continue
        started = started_at(issue['id'])
        if started is not None and now - parse_time(started) >= timedelta(minutes=IN_FLIGHT_MINUTES):
            in_flight.append(f"{issue['id']} ({int((now - parse_time(started)).total_seconds() // 60)} min, {issue.get('assignee') or 'unassigned'})")

    for name, rows in (('outside any epic', outside_epic),
                       ('waiting label (use a blocks dependency)', waiting), (f'in_progress started {IN_FLIGHT_MINUTES}+ min ago', in_flight)):
        print(f'{name}: {len(rows)}')
        for row in rows[:50]:
            print(f'  {row}')
        if len(rows) > 50:
            print(f'  … {len(rows) - 50} more')


if __name__ == '__main__':
    main()
