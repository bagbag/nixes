#!/usr/bin/env python3
"""Rewrite old in-repo `.scratch/` paths in a board's live items and memories (board-migrate Scratch step 3).

    rewrite-scratch-paths.py --moves <log> [--moves <log>]... [--apply]

Maps each moved path (the `moved <old> -> <new>` lines of move-scratch-records.py and `scratch migrate`)
in its absolute, `~` and repository-relative forms to the new path in `~` form. Writes description, design, acceptance and
notes of items that are not closed (decision records past decision stay as written) and memory values, only with
--apply; comments are never changed. A form several moves share (a repository-relative path present in more than one
checkout) is rewritten where exactly one of their new paths holds the rest of the named path, else left as written and
printed as `ambiguous <path>: <new> | <new>` for the session. Every run also reports, without changing the exit code or
blocking --apply, each new path it writes that does not exist (`missing <path>: <n> items (scratch restore <name>)`) and each cited `.scratch/<name>` no move covers, left as written (`unmapped .scratch/<name>:
<n> items`). Run it in the repository after the moves; AGENT_BOARD_COMMAND overrides the board command.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

BOARD = os.environ.get('AGENT_BOARD_COMMAND') or os.path.expanduser('~/.agents/bin/board')
FIELDS = (('description', '--description'), ('design', '--design'), ('acceptance_criteria', '--acceptance'), ('notes', '--notes'))
UNDECIDED = ('open', 'in_progress')  # a decision item in another live status is a record past decision
PATH_CHAR = r'[\w.~/-]'


def board(*args: str) -> str:
    result = subprocess.run([BOARD, *args], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if result.returncode:
        sys.exit(f'board {" ".join(args[:2])} exited {result.returncode}: {result.stderr.strip()}')
    return result.stdout


def tilde(path: str) -> str:
    for home in {os.path.expanduser('~'), os.path.realpath(os.path.expanduser('~'))}:
        if path == home or path.startswith(home + '/'):
            return '~' + path[len(home):]
    return path


def forms(old: str) -> set[str]:
    """The ways an item may name `old`: absolute (as given and resolved), `~`, and relative to its checkout's root."""
    found = {old, os.path.realpath(old)}
    found |= {tilde(f) for f in found}
    parent = old.split('/.scratch/')[0]
    top = subprocess.run(['git', '-C', parent, 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    root = os.path.realpath(top.stdout.strip()) if top.returncode == 0 else os.path.realpath(parent)
    if os.path.realpath(old).startswith(root + '/'):
        found.add(os.path.realpath(old)[len(root) + 1:])
    return found


def moves(logs: list[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """(form -> new path, ambiguous form -> its new paths) over the `moved` lines of the logs."""
    targets: dict[str, set[str]] = {}
    for log in logs:
        for line in open(log, encoding='utf-8').read().splitlines():
            if line.startswith('moved ') and ' -> ' in line:
                old, new = line[len('moved '):].rsplit(' -> ', 1)
                for form in forms(old.rstrip('/')):
                    targets.setdefault(form, set()).add(tilde(new))
    return ({form: next(iter(new)) for form, new in targets.items() if len(new) == 1},
            {form: sorted(new) for form, new in targets.items() if len(new) > 1})


def resolver(mapping: dict[str, str], ambiguous: dict[str, list[str]]):
    """rewrite(text) -> (text, lines, written): each mapped form replaced, an ambiguous one only where exactly one of
    its new paths holds the rest of the named path; lines name each replacement and each ambiguous path left as
    written; written lists (new path as written, moved folder's name) of each mapped replacement."""
    keys = sorted({*mapping, *ambiguous}, key=len, reverse=True)
    pattern = re.compile(rf'(?<!{PATH_CHAR})(' + '|'.join(map(re.escape, keys)) + rf')(/{PATH_CHAR}*)?(?!{PATH_CHAR})')

    def rewrite(text: str) -> tuple[str, list[str], list[tuple[str, str]]]:
        lines, written = [], []

        def one(match: re.Match) -> str:
            form, rest = match.group(1), match.group(2) or ''
            if form in mapping:
                lines.append(f'  {form} -> {mapping[form]}')
                written.append((mapping[form] + rest.rstrip('.'), os.path.basename(mapping[form])))
                return mapping[form] + rest
            tail = rest.rstrip('.')  # a sentence's full stop
            held = [new for new in ambiguous[form] if os.path.lexists(os.path.expanduser(new) + tail)]
            if len(held) != 1:
                lines.append(f"  ambiguous {form}{tail}: {' | '.join(held or ambiguous[form])}")
                return match.group(0)
            lines.append(f'  {form}{tail} -> {held[0]}{tail}')
            return held[0] + rest

        return pattern.sub(one, text), lines, written

    return rewrite


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--moves', action='append', default=[], metavar='LOG', help='a move log (repeat for each)')
    parser.add_argument('--apply', action='store_true', help='write; without it, print what would change')
    args = parser.parse_args()
    mapping, ambiguous = moves(args.moves)
    if not mapping and not ambiguous:
        sys.exit('no moves: pass --moves <log> (the output of move-scratch-records.py --apply, scratch migrate)')
    rewrite = resolver(mapping, ambiguous)
    items = memories = unresolved = 0
    moved = {form.split('.scratch/')[-1] for form in (*mapping, *ambiguous) if '.scratch/' in form}  # whole top-level moves
    missing: dict[tuple[str, str], set[str]] = {}  # (new path, moved name) -> the items and memories writing it
    unmapped: dict[str, set[str]] = {}  # .scratch/<name> left as written -> the items and memories citing it

    def report(owner: str, texts) -> None:
        for text in texts:
            new, _, written = rewrite(text)
            for path, name in written:
                if not os.path.lexists(os.path.expanduser(path.rstrip('/'))):
                    missing.setdefault((path.rstrip('/'), name), set()).add(owner)
            for name in re.findall(r'\.scratch/([\w.-]*[\w-])', new):
                if name not in moved:
                    unmapped.setdefault(name, set()).add(owner)

    def show(head: str, texts) -> None:
        nonlocal unresolved
        lines = list(dict.fromkeys(line for text in texts for line in rewrite(text)[1]))
        if lines:
            print(head + '\n' + '\n'.join(lines))
        unresolved += sum(line.startswith('  ambiguous ') for line in lines)

    for line in board('bd', 'export').splitlines():
        row = json.loads(line) if line.strip() else {}
        if row.get('_type', 'issue') != 'issue' or row.get('status') == 'closed' \
                or (row.get('issue_type') == 'decision' and row.get('status') not in UNDECIDED):
            continue
        texts = {flag: row.get(field) or '' for field, flag in FIELDS}
        changed = {flag: new for flag, text in texts.items() if (new := rewrite(text)[0]) != text}
        show(f"{row['id']}: {', '.join(flag[2:] for flag in changed) or 'nothing rewritten'}", texts.values())
        report(row['id'], texts.values())
        if changed:
            items += 1
            if args.apply:  # flag=value: a text starting with '-' stays a value
                board('bd', 'update', row['id'], *[f'{flag}={text}' for flag, text in changed.items()])
    for key, value in json.loads(board('bd', 'memories', '--json') or '{}').items():
        if not isinstance(value, str):  # bd adds schema_version
            continue
        new = rewrite(value)[0]
        show(f'memory {key}', [value])
        report(f'memory {key}', [value])
        if new != value:
            memories += 1
            if args.apply:
                board('bd', 'remember', '--key', key, '--', new)
    for (path, name), owners in sorted(missing.items()):
        print(f'missing {path}: {len(owners)} items (scratch restore {name})')
    for name, owners in sorted(unmapped.items()):
        print(f'unmapped .scratch/{name}: {len(owners)} items')
    print(f"{items} items, {memories} memories" + (' rewritten' if args.apply else ' (dry run; --apply writes)')
          + (f'; {unresolved} ambiguous paths left as written' if unresolved else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
