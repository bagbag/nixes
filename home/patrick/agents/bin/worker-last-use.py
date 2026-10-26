#!/usr/bin/env python3
"""List a session's workers active within the warm-reuse window, by minutes since their last transcript event (Codex and Claude Code).

Unknown sessions and worker IDs are errors, not evidence that no warm workers exist.
Transcript recency does not establish native worker liveness.
"""
import argparse
import glob
import json
import os
import time
from datetime import datetime, timezone

WARM_MINUTES = 30


def last_line(path):
    with open(path, 'rb') as file:
        file.seek(0, os.SEEK_END)
        position = file.tell()
        buffer = b''
        while position > 0:
            step = min(65536, position)
            position -= step
            file.seek(position)
            buffer = file.read(step) + buffer
            lines = buffer.rstrip(b'\n').split(b'\n')
            if len(lines) > 1 or position == 0:
                return lines[-1]
    return b''


def last_timestamp(path):
    try:
        return json.loads(last_line(path)).get('timestamp')
    except ValueError:
        return None


def minutes_since(timestamp):
    moment = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    return int((datetime.now(timezone.utc) - moment).total_seconds() // 60)


def recent(path):
    return os.path.getmtime(path) >= time.time() - WARM_MINUTES * 60


def codex_workers(parent):
    for path in glob.glob(os.path.expanduser('~/.codex/sessions/*/*/*/rollout-*.jsonl')):
        if not recent(path):
            continue
        with open(path) as file:
            try:
                meta = json.loads(file.readline()).get('payload', {})
            except ValueError:
                continue
        if meta.get('parent_thread_id') != parent or not meta.get('agent_role'):
            continue
        timestamp = last_timestamp(path)
        if timestamp is None:
            continue
        yield minutes_since(timestamp), meta.get('agent_nickname') or meta.get('id'), meta['agent_role'], meta.get('id')


def claude_workers(parent):
    escaped = glob.escape(parent)
    for path in glob.glob(os.path.expanduser(f'~/.claude/projects/*/{escaped}/subagents/agent-*.jsonl')):
        if not recent(path):
            continue
        meta_path = path.removesuffix('.jsonl') + '.meta.json'
        meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
        timestamp = last_timestamp(path)
        if timestamp is None:
            continue
        agent_id = os.path.basename(path).removeprefix('agent-').removesuffix('.jsonl')
        yield minutes_since(timestamp), meta.get('description') or agent_id, meta.get('agentType') or '?', agent_id


def identify_parent(parent):
    """Recognize parent metadata and reject a known worker's own identifier."""
    escaped = glob.escape(parent)
    known = False
    for path in glob.glob(os.path.expanduser(f'~/.codex/sessions/*/*/*/rollout-*-{escaped}.jsonl')):
        try:
            with open(path) as file:
                meta = json.loads(file.readline()).get('payload', {})
        except (OSError, ValueError):
            continue
        if meta.get('id') != parent:
            continue
        worker_parent = meta.get('parent_thread_id')
        if worker_parent and meta.get('agent_role'):
            raise ValueError(f'{parent!r} is a worker ID; pass its parent session ID {worker_parent!r}')
        known = True

    claude_id = glob.escape(parent.removeprefix('agent-'))
    worker_paths = glob.glob(os.path.expanduser(f'~/.claude/projects/*/*/subagents/agent-{claude_id}.jsonl'))
    if worker_paths:
        parents = sorted({os.path.basename(os.path.dirname(os.path.dirname(path))) for path in worker_paths})
        raise ValueError(f'{parent!r} is a worker ID; pass its parent session ID: {", ".join(parents)}')
    if glob.glob(os.path.expanduser(f'~/.claude/projects/*/{escaped}.jsonl')):
        known = True
    if any(os.path.isdir(path) for path in glob.glob(os.path.expanduser(f'~/.claude/projects/*/{escaped}/subagents'))):
        known = True
    return known


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('parent', nargs='?', metavar='PARENT_SESSION_ID',
                        help='parent session ID (defaults to the current session from the environment)')
    arguments = parser.parse_args(argv)
    parent = arguments.parent or (os.environ.get('CLAUDE_CODE_SESSION_ID') or os.environ.get('CODEX_THREAD_ID') or os.environ.get('CODEX_SESSION_ID'))
    if not parent:
        parser.error('pass the parent session ID')
    if parent in ('.', '..') or '/' in parent or '\\' in parent:
        parser.error('pass a parent session ID, not a path')
    try:
        known = identify_parent(parent)
    except ValueError as error:
        parser.error(str(error))
    rows = sorted(row for row in [*codex_workers(parent), *claude_workers(parent)] if row[0] <= WARM_MINUTES)
    if not known and not rows:
        parser.error(f'parent session {parent!r} was not found; warm-worker availability is unknown')
    if not rows:
        print(f'parent {parent}: no worker active within {WARM_MINUTES} min')
    for minutes, name, role, worker_id in rows:
        print(f'{minutes:>6} min  {role:<16} {name}  [{worker_id}]')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
