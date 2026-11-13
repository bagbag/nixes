#!/usr/bin/env python3
"""Move decision records out of a repository's old in-repo `.scratch` folders (board-migrate Scratch step 1, r20-q99).

    move-scratch-records.py [--apply]

A record is a Markdown file with `## Question` and `## Decision` sections. Each moves to the folder `protocol records`
prints, at its path below the checkout with the `.scratch` part dropped (a worktree outside the main tree: under its
folder name); an existing file there is never overwritten. Without --apply it prints `would move` lines; with it,
`moved <old> -> <new>` lines for rewrite-scratch-paths.py. Everything else stays for `scratch migrate`.
AGENT_PROTOCOL_COMMAND overrides the protocol command.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys

PROTOCOL = os.environ.get('AGENT_PROTOCOL_COMMAND') or os.path.expanduser('~/.agents/bin/protocol')
SKIP_WALK = {'.git', 'node_modules'}
HEADINGS = [re.compile(rf'^## {name}\s*$', re.M) for name in ('Question', 'Decision')]


def git(cwd: str, *args: str) -> str:
    result = subprocess.run(['git', '-C', cwd, *args], capture_output=True, text=True)
    if result.returncode:
        sys.exit(f'git {" ".join(args)}: {result.stderr.strip()}')
    return result.stdout


def scratch_folders(tree: str, visited: set[str]) -> list[str]:
    """Every real `.scratch` folder below tree, not descending into one, .git, node_modules or symlinks."""
    found, stack = [], [os.path.realpath(tree)]
    while stack:
        here = stack.pop()
        if here in visited:
            continue
        visited.add(here)
        try:
            with os.scandir(here) as entries:
                for entry in entries:
                    if entry.name == '.scratch' and entry.is_dir(follow_symlinks=False):
                        found.append(entry.path)
                    elif entry.name not in SKIP_WALK and entry.name != '.scratch' and entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
        except OSError:
            continue
    return sorted(found)


def is_record(path: str) -> bool:
    try:
        text = open(path, encoding='utf-8').read()
    except (OSError, UnicodeDecodeError):
        return False
    return all(h.search(text) for h in HEADINGS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--apply', action='store_true', help='move; without it, print what would move')
    args = parser.parse_args()
    listed = [line[len('worktree '):] for line in git(os.getcwd(), 'worktree', 'list', '--porcelain').splitlines() if line.startswith('worktree ')]
    trees = [os.path.realpath(t) for t in listed]
    top = trees[0]
    result = subprocess.run([PROTOCOL, 'records'], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if result.returncode or not result.stdout.strip():
        sys.exit(f'protocol records failed: {result.stderr.strip()}')
    records = result.stdout.strip()
    visited: set[str] = set()
    moved = skipped = 0
    for tree in trees:
        base = os.path.relpath(tree, top) if tree == top or tree.startswith(top + '/') else os.path.basename(tree)
        for scratch in scratch_folders(tree, visited):
            for here, dirs, files in os.walk(scratch, followlinks=False):
                for name in sorted(files):
                    path = os.path.join(here, name)
                    if not name.endswith('.md') or os.path.islink(path) or not is_record(path):
                        continue
                    below = os.path.relpath(os.path.dirname(scratch), tree)
                    target = os.path.normpath(os.path.join(records, base, below, os.path.relpath(path, scratch)))
                    if os.path.lexists(target):
                        print(f'skipped (exists: {target}): {path}')
                        skipped += 1
                        continue
                    if args.apply:
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        shutil.move(path, target)  # the data folder may sit on another volume
                    print(f"{'moved' if args.apply else 'would move'} {path} -> {target}")
                    moved += 1
    print(f"{moved} records {'moved' if args.apply else 'to move (dry run; --apply moves)'}, {skipped} skipped", file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
