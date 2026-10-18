#!/usr/bin/env python3
"""Report goal-relay counts and board drift for a beads board.

Usage: board-health [<root epic>] [--items VIEW[,VIEW...]]   (run inside the repository; scope = everything below the root epic)

--items lists the items behind the named counts. Views: decided, questions, ratification, released, inbox, dispatch.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

IN_FLIGHT_MINUTES = 25
LIFECYCLE_LABELS = ('human', 'decided', 'review', 'needs-ratification', 'waiting')
CLAIM_MINUTES = 5
VIEWS = ('decided', 'questions', 'ratification', 'released', 'inbox', 'dispatch')


def load_issues():
    out = subprocess.run(['bd', 'list', '--all', '--limit', '0', '--json'], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def parse_views(value):
    views = [view for view in value.split(',') if view]
    if not views:
        raise argparse.ArgumentTypeError(f"no view given; choose from {', '.join(VIEWS)}")
    unknown = [view for view in views if view not in VIEWS]
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown view {', '.join(map(repr, unknown))}; choose from {', '.join(VIEWS)}")
    return set(views)


def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def main():
    issues = load_issues()
    by_id = {issue['id']: issue for issue in issues}

    def ancestors(issue):
        parent = issue.get('parent')
        while parent and parent in by_id:
            yield by_id[parent]
            parent = by_id[parent].get('parent')

    parser = argparse.ArgumentParser(prog='board-health')
    parser.add_argument('root', nargs='?')
    parser.add_argument('--items', type=parse_views, default=set(), metavar='VIEW[,VIEW...]',
                        help=f"list the items behind these counts: {', '.join(VIEWS)}")
    args = parser.parse_args()
    scope_root = args.root
    if scope_root is not None and scope_root not in by_id:
        sys.exit(f'board-health: unknown epic {scope_root}')

    scoped = [issue for issue in issues if scope_root is None or any(a['id'] == scope_root for a in ancestors(issue))]
    open_items = [issue for issue in scoped if issue['status'] != 'closed' and issue['issue_type'] != 'epic']

    def labels(issue):
        return issue.get('labels') or []

    counts = (
        ('decided', 'pending decisions (decided)', [i for i in open_items if i['status'] == 'decided']),
        ('questions', 'open questions (unanswered)', [i for i in open_items if i['issue_type'] == 'decision'
                                                      and i['status'] in ('open', 'in_progress')]),
        ('ratification', 'awaiting ratification (needs_ratification)',
         [i for i in open_items if i['status'] == 'needs_ratification']),
        ('released', 'released, not landed', [i for i in open_items if i['status'] == 'released']),
        ('inbox', 'review inbox (goal-lead)',
         [i for i in open_items if i['status'] == 'in_review' and i.get('assignee') == 'goal-lead']),
        ('dispatch', 'dispatch queue (unassigned open)',
         [i for i in open_items if not i.get('assignee') and i['status'] == 'open']),
    )
    for view, name, items in counts:
        print(f'{name}: {len(items)}')
        if view in args.items:
            for item in items:
                print(f"  {item['id']}  {item.get('title', '')}")

    def epic_of(issue):
        return next((a for a in ancestors(issue) if a['issue_type'] == 'epic'), None)

    outside_epic = [i['id'] for i in issues if i['status'] != 'closed' and i['issue_type'] != 'epic' and epic_of(i) is None]

    def open_blockers(issue):
        return [d['depends_on_id'] for d in issue.get('dependencies') or []
                if d['type'] == 'blocks' and by_id.get(d['depends_on_id'], {}).get('status') not in (None, 'closed')]

    lifecycle_labels = [f"{i['id']} ({', '.join(l for l in labels(i) if l in LIFECYCLE_LABELS)})"
                        for i in open_items if any(l in LIFECYCLE_LABELS for l in labels(i))]
    release_gates_ready = [f"{i['id']} ({i['title']})" for i in open_items
                           if i['issue_type'] == 'gate' and i.get('title', '').startswith('[Gate] Release:') and not open_blockers(i)]

    now = datetime.now(timezone.utc)
    in_flight = []
    stale = []
    unknown = []
    for issue in open_items:
        if issue['status'] != 'in_progress':
            continue
        started = parse_time(issue.get('started_at'))
        heartbeat = parse_time(issue.get('heartbeat_at'))
        lease = parse_time(issue.get('lease_expires_at'))
        owner = issue.get('assignee') or 'unassigned'
        if started is not None and now - started >= timedelta(minutes=IN_FLIGHT_MINUTES):
            in_flight.append(f"{issue['id']} ({int((now - started).total_seconds() // 60)} min, {owner})")

        activity = heartbeat or started
        if activity is None:
            unknown.append(f"{issue['id']} ({owner}; timestamps unavailable)")
            continue
        # bd's lease is the claim expiry; the heartbeat-age rule covers claims without one.
        expired = lease <= now if lease is not None else now - activity >= timedelta(minutes=CLAIM_MINUTES)
        if expired:
            age = int((now - activity).total_seconds() // 60)
            if heartbeat is not None:
                evidence = f"heartbeat {issue['heartbeat_at']}"
            else:
                state = 'missing' if not issue.get('heartbeat_at') else 'invalid'
                evidence = f"heartbeat {state}; started {issue['started_at']}"
            if lease is not None:
                evidence += f"; lease expired {issue['lease_expires_at']}"
            stale.append(f"{issue['id']} ({owner}; {evidence}; {age} min)")

    for name, rows in (('release gates ready (no open blockers)', release_gates_ready),
                       ('outside any epic', outside_epic),
                       ('lifecycle labels (use statuses, assignment or blocks)', lifecycle_labels),
                       (f'in_progress started {IN_FLIGHT_MINUTES}+ min ago', in_flight),
                       (f'possible stale in_progress (lease expired, or no heartbeat for {CLAIM_MINUTES}+ min)', stale),
                       ('in_progress activity unknown', unknown)):
        print(f'{name}: {len(rows)}')
        for row in rows[:50]:
            print(f'  {row}')
        if len(rows) > 50:
            print(f'  … {len(rows) - 50} more')


if __name__ == '__main__':
    main()
