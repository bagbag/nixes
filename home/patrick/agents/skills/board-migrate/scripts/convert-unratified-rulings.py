#!/usr/bin/env python3
"""Convert live legacy needs_ratification decisions into released rulings."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


BOARD = Path.home() / '.agents' / 'bin' / 'board'
SESSION = Path.home() / '.agents' / 'bin' / 'session'
RECORD_SECTIONS = ('Question', 'Alternatives Considered', 'Decision', 'Rationale', 'Rule owner', 'Reversal')


class ConversionError(Exception):
    pass


def command(path: Path, *args: str) -> str:
    result = subprocess.run([str(path), *args], capture_output=True, text=True)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise ConversionError(f"{path.name} {' '.join(args)} failed: {detail}")
    return result.stdout


def active_decider() -> None:
    actor = command(SESSION, 'actor').strip().split('/', 1)[0]
    registrations = [json.loads(line) for line in command(SESSION, 'list').splitlines() if line.strip()]
    role = next((row.get('role') for row in registrations if row.get('actor') == actor), None)
    if role not in ('lead', 'solo'):
        raise ConversionError('run this conversion in a registered lead or solo session')


def missing_sections(description: str) -> list[str]:
    headings = {match.group(1).strip().lower() for match in re.finditer(r'^##\s+(.+?)\s*$', description, re.MULTILINE)}
    return [section for section in RECORD_SECTIONS
            if not any(heading.startswith(section.lower()) for heading in headings)]


def live_legacy_rulings() -> list[dict]:
    rows = json.loads(command(BOARD, 'bd', 'list', '--status', 'needs_ratification', '--type', 'decision', '--json', '--limit', '0'))
    return sorted(rows, key=lambda row: row['id'])


def descriptions(rows: list[dict]) -> dict[str, str]:
    records = {}
    problems = []
    for row in rows:
        item_id = row['id']
        shown = json.loads(command(BOARD, 'show', item_id, '--json'))
        description = str((shown.get(item_id) or {}).get('description') or '')
        missing = missing_sections(description)
        if missing:
            problems.append(f"{item_id} lacks {', '.join('## ' + section for section in missing)}")
        else:
            records[item_id] = description
    if problems:
        raise ConversionError('preflight stopped before claiming anything:\n  ' + '\n  '.join(problems))
    return records


def convert(rows: list[dict], records: dict[str, str]) -> list[str]:
    confirmations = []
    for row in rows:
        item_id = row['id']
        command(BOARD, 'claim', item_id)
        with tempfile.TemporaryDirectory(prefix='unratified-ruling-') as directory:
            record_file = Path(directory) / f'{item_id}.md'
            record_file.write_text(records[item_id], encoding='utf-8')
            output = command(BOARD, 'ruling', 'record', item_id, str(record_file), '--unratified')
        match = re.search(r'confirmation question: ([^\s]+)', output)
        if not match:
            raise ConversionError(f"{item_id} was recorded but printed no confirmation question id; inspect board show {item_id}")
        confirmations.append(match.group(1))
        print(f'{item_id}: released; confirmation question {match.group(1)}')
    return confirmations


def main() -> int:
    try:
        active_decider()
        rows = live_legacy_rulings()
        records = descriptions(rows)
        confirmations = convert(rows, records)
    except (ConversionError, OSError, ValueError, KeyError) as error:
        print(f'legacy ruling conversion stopped: {error}', file=sys.stderr)
        return 1
    if not confirmations:
        print('no live legacy rulings')
        return 0
    print('confirmation questions: ' + ', '.join(confirmations))
    print('Next, ask one rule question that settles these confirmation questions; split out any rulings the user revises.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
