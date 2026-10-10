#!/usr/bin/env python3
"""List a session's workers active within the warm-reuse window, by minutes since their last transcript event (Codex and Claude Code).

Usage: worker-last-use [<parent session id>]   (default: current session from the environment)
A worker not listed has been idle longer than the window.
"""
import glob
import json
import os
import sys
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
    for path in glob.glob(os.path.expanduser(f'~/.claude/projects/*/{parent}/subagents/agent-*.jsonl')):
        if not recent(path):
            continue
        meta_path = path.removesuffix('.jsonl') + '.meta.json'
        meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
        timestamp = last_timestamp(path)
        if timestamp is None:
            continue
        agent_id = os.path.basename(path).removeprefix('agent-').removesuffix('.jsonl')
        yield minutes_since(timestamp), meta.get('description') or agent_id, meta.get('agentType') or '?', agent_id


def main():
    parent = sys.argv[1] if len(sys.argv) > 1 else (os.environ.get('CLAUDE_CODE_SESSION_ID') or os.environ.get('CODEX_THREAD_ID') or os.environ.get('CODEX_SESSION_ID'))
    if not parent:
        sys.exit('worker-last-use: pass the parent session id')
    rows = sorted(row for row in [*codex_workers(parent), *claude_workers(parent)] if row[0] <= WARM_MINUTES)
    if not rows:
        print(f'no worker active within {WARM_MINUTES} min')
    for minutes, name, role, worker_id in rows:
        print(f'{minutes:>6} min  {role:<16} {name}  [{worker_id}]')


if __name__ == '__main__':
    main()
