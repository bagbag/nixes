#!/usr/bin/env python3
"""Convert a board's design checkpoint records to ordinary design change requests, on the runtime without checkpoints.

    convert-design-checkpoints.py inventory [--mapping FILE]   read-only: records, transitions, manual steps
    convert-design-checkpoints.py apply MAPPING [--apply]      recheck, then write (a dry run without --apply)
    convert-design-checkpoints.py verify                       read-only: what is left to convert

Run it in the project's checkout after `convert-stored-forms.py --apply` (designs are tasks labelled kind:design,
design ratifications are questions already) and before its `--mark`. The mapping is the owner-approved file that
`inventory --mapping` drafts; `apply` writes only what it lists, through raw bd because the board's write verbs refuse a
board without the model marker: returning a change request to open, the wait on the change request, the relates-to
link, clearing the checkpoint marker. Waits the old runtime counted as met (on a closed design inside an unlanded
change request) become `relates-to` links, which keeps their meaning. Text placement, documentation CRs and the
choices on missing provenance stay with their owners: `inventory` lists them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

BIN = Path(__file__).resolve().parents[3] / 'bin'  # agents/bin, beside agents/skills
BOARD, SESSION = BIN / 'board', BIN / 'session'
BLOCKING = ('blocks',)
AT_REVIEW = ('in_review', 'passed')
SCRATCH_REF = re.compile(r'[~/.][^\s`"\')\]>,;]*scratch[^\s`"\')\]>,;]*')
DOC_REF = re.compile(r'(?<![\w/])(?:[\w.-]+/)*docs/[\w./-]+\.md')
RETURN_NOTE = 'design checkpoint converted to an ordinary design change request: author the doc on the branch'
TRANSITIONS = {
    'authoring-return': 'live checkpoint with outstanding design: back to open, doc on branch, ordinary review',
    'authoring-clear': 'returned or queued checkpoint: clear the marker, doc on branch, ordinary review',
    'hold': 'hold: no write; the owner resolves the reasons',
}


def is_design(item: dict) -> bool:
    return item.get('issue_type') == 'task' and 'kind:design' in (item.get('labels') or [])


class ConversionError(Exception):
    pass


def run(path: Path, *args: str, cwd: Path | None = None, stdin: str | None = None) -> str:
    result = subprocess.run([str(path), *args], capture_output=True, text=True, cwd=cwd, input=stdin)
    if result.returncode:
        raise ConversionError(f"{path.name} {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def board(*args: str) -> str:
    return run(BOARD, *args)


def raw(*args: str, stdin: str | None = None) -> str:
    """A bd write no board verb does on the new runtime; the owner's approval of the mapping authorizes it."""
    return run(BOARD, 'bd', '--raw', '--yes', *args, stdin=stdin)


def comment_once(item_id: str, text: str) -> None:
    """A comment is permanent: an interrupted step's rerun writes it only when the record does not carry it yet."""
    comments = json.loads(board('show', '--json', item_id))[item_id].get('comments') or []
    if text not in [str(c.get('text') or '') for c in comments]:
        raw('comments', 'add', item_id, text)


def git(cwd: Path, *args: str) -> str | None:
    result = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def active_decider() -> None:
    actor = run(SESSION, 'actor').strip().split('/', 1)[0]
    registrations = [json.loads(line) for line in run(SESSION, 'list').splitlines() if line.strip()]
    role = next((row.get('role') for row in registrations if row.get('actor') == actor), None)
    if role not in ('lead', 'solo'):
        raise ConversionError('run the conversion in a registered lead or solo session')


def rehearsal_copy(folder: str, main_root: Path) -> None:
    """Only a rehearsal may skip the deciding-session check: its folder is the board-rehearsal-* one it made, and this checkout is that folder."""
    path = Path(folder).resolve()
    if not path.name.startswith('board-rehearsal-') or main_root.resolve() != path:
        raise ConversionError(f'--copy {folder}: this board is not that rehearsal copy; a real board needs a lead or solo session')


# --- reading the board -------------------------------------------------------------------------------------------

def show(ids: list[str]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for start in range(0, len(ids), 40):
        found.update(json.loads(board('show', '--json', *ids[start:start + 40])))
    return found


def read_board() -> dict:
    """Rows of every item (closed too), the full record of each live change request and its children, and the waits."""
    rows = json.loads(board('bd', 'list', '--all', '--json', '--limit', '0'))
    by_id = {row['id']: row for row in rows}
    live = [row['id'] for row in rows if row['issue_type'] == 'change-request' and row['status'] != 'closed']
    children = {cr: sorted(row['id'] for row in rows if row.get('parent') == cr) for cr in live}
    detail = show(sorted({*live, *(child for kids in children.values() for child in kids)}))
    edges = {(dep['issue_id'], dep['depends_on_id'], dep['type']) for row in rows for dep in row.get('dependencies') or []}
    return {'rows': by_id, 'live': live, 'children': children, 'detail': detail,
            'waits': sorted((a, b) for a, b, kind in edges if kind in BLOCKING)}


def main_checkout() -> Path:
    listing = subprocess.run(['git', 'worktree', 'list', '--porcelain'], capture_output=True, text=True)
    first = listing.stdout.splitlines()[0] if listing.returncode == 0 and listing.stdout.strip() else ''
    if not first.startswith('worktree '):
        raise ConversionError('run the conversion inside the project checkout')
    return Path(first.removeprefix('worktree '))


def git_facts(main: Path, cr_id: str) -> dict:
    tree = main / '.worktrees' / cr_id
    present = (tree / '.git').is_file()
    dirty = git(tree, 'status', '--porcelain') if present else None
    return {'tip': git(main, 'rev-parse', '--verify', '-q', f'refs/heads/cr/{cr_id}'),
            'worktree': present, 'dirty': bool(dirty)}


def body_facts(item: dict) -> dict:
    text = '\n'.join(str(item.get(field) or '') for field in ('description', 'design', 'acceptance_criteria', 'notes'))
    scratch = []
    for token in sorted(set(SCRATCH_REF.findall(text))):
        path = Path(token.rstrip('.:')).expanduser()
        if path.is_file():
            scratch.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()[:12]})
        else:
            scratch.append({'path': str(path), 'sha256': None})
    return {'inline': bool(text.strip()), 'scratch': scratch, 'docs': sorted(set(DOC_REF.findall(text)))}


def cr_state(data: dict, main: Path, cr_id: str) -> dict:
    """What a conversion step rechecks: the fields of one change request that its mapping row expects."""
    record = data['detail'][cr_id]
    meta = record.get('metadata') or {}
    designs = {child: data['detail'][child] for child in data['children'][cr_id] if is_design(data['detail'][child])}
    return {'status': record['status'], 'holder': record.get('assignee') or None, 'checkpoint': meta.get('checkpoint') or None,
            'opened_review': bool(meta.get('opened_tip')), 'design': {key: item['status'] for key, item in designs.items()},
            **{key: value for key, value in git_facts(main, cr_id).items() if key in ('tip', 'dirty')}}


# --- inventory -------------------------------------------------------------------------------------------------------

def waiter_edges(data: dict, cr_id: str, design_ids: list[str]) -> tuple[list[dict], list[str]]:
    """Waits from items outside the change request on its design items or on it: (proposed new waits, listed notes)."""
    inside = {cr_id, *data['children'][cr_id]}
    proposed, notes = [], []
    for waiter, blocker in data['waits']:
        if waiter in inside or blocker not in (cr_id, *design_ids) or waiter not in data['rows']:
            continue
        row = data['rows'][waiter]
        if row['status'] == 'closed':
            continue
        edge = f'{waiter} waits on {blocker}'
        if blocker == cr_id:
            notes.append(f'{edge} (the change request: implementation wait, kept)')
        elif data['rows'][blocker]['status'] == 'closed':
            notes.append(f'{edge} (met under the old runtime: apply makes it relates-to)')
        elif (waiter, cr_id) in data['waits']:
            notes.append(f'{edge} (also waits on {cr_id}: kept)')
        elif row.get('assignee'):
            notes.append(f"{edge} (held by {row['assignee']}: quiesce {waiter}, then add the wait on {cr_id})")
        else:
            proposed.append({'waiter': waiter, 'on': cr_id, 'via': blocker, 'expect': {'status': row['status'], 'holder': None}})
            notes.append(f'{edge} (unsatisfied delivery wait: add {waiter} waits on {cr_id}, keep the old edge)')
    return proposed, notes


def classify(data: dict, main: Path, cr_id: str) -> dict:
    record = data['detail'][cr_id]
    state = cr_state(data, main, cr_id)
    facts = git_facts(main, cr_id)
    children = {child: data['detail'][child] for child in data['children'][cr_id]}
    designs = {key: item for key, item in children.items() if is_design(item)}
    bodies = {key: body_facts(item) for key, item in designs.items()}
    comments = [str(c.get('text') or '') for c in record.get('comments') or []]
    meta = record.get('metadata') or {}
    row = {'cr': cr_id, 'title': record['title'], 'state': state, 'git': facts, 'bodies': bodies, 'reasons': [], 'manual': [], 'notes': []}
    implementation = sorted(key for key, item in children.items() if not is_design(item) and item['status'] != 'closed')
    if state['checkpoint']:
        open_designs = [key for key, status in state['design'].items() if status != 'closed']
        if not designs:
            row['reasons'].append('missing body: no design item')
        elif not any(b['inline'] or any(s['sha256'] for s in b['scratch']) for b in bodies.values()):
            row['reasons'].append('missing provenance: no design text and no readable scratch file')
        if any(s['sha256'] is None for b in bodies.values() for s in b['scratch']) and not any(b['inline'] for b in bodies.values()):
            row['reasons'].append('missing body: a scratch reference names no readable file')
        if state['status'] in AT_REVIEW and not (meta.get('review_tip') or any(c.startswith(('board handover: ', 'board pass: ')) for c in comments)):
            row['reasons'].append('missing provenance: no handover or pass evidence for the reviewed range')
        if state['holder']:
            row['reasons'].append(f"held by {state['holder']}: the owner ends the hold")
        if state['status'] == 'in_review':
            row['reasons'].append('in review: end the review through the current workflow (a reviewer passes or returns it), then rerun')
        elif state['status'] not in ('open', 'passed'):
            row['reasons'].append(f"status {state['status']}: the owner resolves it first")
        if state['opened_review']:
            row['reasons'].append('open user review: the owner ends it and records the edits')
        if facts['dirty']:
            row['reasons'].append('dirty worktree: unrecorded edits stay with their owner')
        if not facts['tip']:
            row['reasons'].append('no branch cr/' + cr_id)
        row['kind'] = 'hold' if row['reasons'] else ('authoring-return' if state['status'] == 'passed' else 'authoring-clear')
        row['manual'].append(f'place the design text in the topic document on cr/{cr_id}; compare it with the approved or reviewed range, then ordinary handover')
        if open_designs and not designs:
            row['manual'].append('design items missing')
        if implementation:
            row['manual'].append(f"move implementation items {', '.join(implementation)} into a distinct dependent change request (planning)")
    else:
        return {**row, 'kind': None}  # only a change request with checkpoint metadata is a checkpoint
    for key, body in bodies.items():
        for scratch in body['scratch']:
            row['manual'].append(f"{key}: body held in scratch {scratch['path']} (sha256 {scratch['sha256'] or 'unreadable'}): move it into the doc; the reference alone is not the approved text")
    row['edges'], edge_notes = waiter_edges(data, cr_id, sorted(designs))
    row['notes'] += edge_notes
    return row


def met_waits(data: dict) -> list[dict]:
    """Waits the old runtime counted as met and the new one reads as waiting for a landing: a live item waiting on a
    closed design inside an unlanded change request other than its own."""
    cr_of = {child: cr for cr, kids in data['children'].items() for child in kids}
    found = []
    for waiter, blocker in data['waits']:
        w, b, cr = data['rows'].get(waiter), data['rows'].get(blocker), cr_of.get(blocker)
        if (w and b and cr and is_design(b) and b['status'] == 'closed' and w['status'] != 'closed'
                and cr_of.get(waiter) != cr):
            found.append({'waiter': waiter, 'on': blocker, 'cr': cr})
    return found


def inventory(data: dict, main: Path) -> dict:
    rows = [row for row in (classify(data, main, cr) for cr in data['live']) if row['kind']]
    return {'records': rows, 'met': met_waits(data)}


def print_inventory(found: dict) -> None:
    for row in found['records']:
        state = row['state']
        designs = ','.join(f'{key}:{status}' for key, status in state['design'].items()) or 'none'
        body = ','.join(sorted({'scratch' if b['scratch'] else 'inline' if b['inline'] else 'none' for b in row['bodies'].values()})) or 'none'
        print(f"{row['cr']}  {state['status']}  holder={state['holder'] or '-'}  checkpoint={state['checkpoint'] or '-'}  "
              f"tip={(state['tip'] or 'none')[:12]}  designs={designs}  body={body}")
        print(f"  transition: {TRANSITIONS[row['kind']]}")
        for text in row['reasons']:
            print(f'  reason: {text}')
        for text in row['notes']:
            print(f'  edge: {text}')
        for text in row['manual']:
            print(f'  manual: {text}')
    for edge in found['met']:
        print(f"{edge['waiter']} waits on {edge['on']}, a closed design in unlanded {edge['cr']}: met under the old runtime; apply makes it relates-to")
    if not found['records'] and not found['met']:
        print('no live checkpoint or met design wait')


def draft_mapping(found: dict) -> dict:
    records = []
    for row in found['records']:
        steps = {'authoring-return': ['return', 'clear'], 'authoring-clear': ['clear']}.get(row['kind'], [])
        entry = {'cr': row['cr'], 'kind': row['kind'], 'steps': steps, 'expect': row['state']}
        if row['kind'] != 'hold':
            entry['edges'] = row['edges']
        records.append(entry)
    return {'version': 1, 'approved_by': '', 'records': records, 'met': found['met']}


# --- applying a mapping -------------------------------------------------------------------------------------------------

def load_mapping(path: str) -> dict:
    mapping = json.loads(Path(path).read_text(encoding='utf-8'))
    if mapping.get('version') != 1 or not isinstance(mapping.get('records'), list):
        raise ConversionError('the mapping is not a version 1 mapping file')
    if not str(mapping.get('approved_by') or '').strip():
        raise ConversionError('the mapping names no approver: the owner sets approved_by after review')
    return mapping


def diverged(cr_id: str, expected: dict, current: dict, fields: tuple[str, ...]) -> ConversionError:
    differing = [f'{field}: expected {expected.get(field)!r}, found {current.get(field)!r}' for field in fields if expected.get(field) != current.get(field)]
    return ConversionError(f"{cr_id} diverged from the approved mapping ({'; '.join(differing)}); stopped before writing, re-inventory and re-approve")


def convert_record(entry: dict, main: Path, write: bool, log: list[str]) -> None:
    """Recheck: the approved state returns to open and clears; a returned state finishes the clear; a cleared marker is done; anything else stops."""
    cr_id, expect, steps = entry['cr'], entry['expect'], entry.get('steps', [])
    current = current_state(main, cr_id)
    if current['checkpoint'] is None:
        log.append(f'{cr_id}: converted already (no checkpoint marker)')
        return
    returned = {**expect, 'status': 'open'}
    needs_return = 'return' in steps and current == expect
    if not needs_return and current != expect and current != returned:
        raise diverged(cr_id, expect, current, ('status', 'holder', 'checkpoint', 'tip', 'design', 'opened_review', 'dirty'))
    if needs_return:
        log.append(f'{cr_id}: back to open')
        if write:
            comment_once(cr_id, RETURN_NOTE)  # before the status write: the rerun of a stop between them finds the checkpoint still approved, not returned
            raw('update', cr_id, '--status', 'open', '--assignee', '', '--json')
    log.append(f'{cr_id}: clear the checkpoint marker')
    if write:
        raw('update', cr_id, '--unset-metadata', 'checkpoint', '--json')
        if current_state(main, cr_id)['checkpoint'] is not None:
            raise ConversionError(f'{cr_id}: the marker is still set after the update; inspect agents board show {cr_id}')


def current_state(main: Path, cr_id: str) -> dict:
    record = json.loads(board('show', '--json', cr_id))[cr_id]
    rows = json.loads(board('bd', 'list', '--all', '--json', '--limit', '0', '--parent', cr_id))
    detail = show([row['id'] for row in rows])
    data = {'detail': {cr_id: record, **detail}, 'children': {cr_id: [row['id'] for row in rows]}}
    return cr_state(data, main, cr_id)


def add_wait(edge: dict, cr_id: str, main: Path, write: bool, log: list[str]) -> None:
    waiter, via = edge['waiter'], edge['via']
    waits = set(read_waits())
    if (waiter, cr_id) in waits:
        log.append(f'{waiter}: already waits on {cr_id}')
        return
    row = {row['id']: row for row in json.loads(board('bd', 'list', '--all', '--json', '--limit', '0'))}.get(waiter, {})
    current = {'status': row.get('status'), 'holder': row.get('assignee') or None}
    if current != edge['expect'] or (waiter, via) not in waits:
        raise ConversionError(f"{waiter} diverged from the approved mapping (expected {edge['expect']} waiting on {via}, found {current}"
                              f"{'' if (waiter, via) in waits else ', the old wait is gone'}); stopped before writing")
    log.append(f'{waiter}: wait on {cr_id}')
    if write:
        comment_once(waiter, f'Waits on {cr_id} for the design change request to land (checkpoint conversion)')
        raw('batch', '-m', f'board-migrate {waiter}', '--json', stdin=f'dep add {waiter} {cr_id} blocks\n')
        if (waiter, cr_id) not in read_waits():
            raise ConversionError(f'{waiter}: the wait on {cr_id} is not recorded after the write')


def to_relates(edge: dict, write: bool, log: list[str]) -> None:
    """A met wait becomes relates-to; rerunnable, and stops when the design was reopened since the inventory."""
    waiter, on = edge['waiter'], edge['on']
    rows = {row['id']: row for row in json.loads(board('bd', 'list', '--all', '--json', '--limit', '0'))}
    edges = {(dep['issue_id'], dep['depends_on_id']): dep['type'] for row in rows.values() for dep in row.get('dependencies') or []}
    kind = edges.get((waiter, on))
    if kind is not None and kind not in BLOCKING:  # relates-to from an earlier run, or another link (bd keeps one per pair)
        log.append(f'{waiter}: linked to {on} already ({kind})')
        return
    if kind in BLOCKING and rows.get(on, {}).get('status') != 'closed':
        raise ConversionError(f'{on} was reopened since the inventory, so {waiter} waits on it again; stopped before writing, re-inventory')
    log.append(f'{waiter}: wait on {on} becomes relates-to (met under the old runtime)')
    if write:
        raw('batch', '-m', f'board-migrate {waiter}', '--json', stdin=f'dep remove {waiter} {on}\ndep add {waiter} {on} relates-to\n')


def read_waits() -> list[tuple[str, str]]:
    rows = json.loads(board('bd', 'list', '--all', '--json', '--limit', '0'))
    return [(dep['issue_id'], dep['depends_on_id']) for row in rows for dep in row.get('dependencies') or [] if dep['type'] in BLOCKING]


def apply(mapping: dict, main: Path, write: bool) -> list[str]:
    log: list[str] = []
    for entry in mapping['records']:
        if entry['kind'] == 'hold':
            log.append(f"{entry['cr']}: hold, no write (owner resolves)")
            continue
        if entry['kind'] in ('authoring-return', 'authoring-clear'):
            convert_record(entry, main, write, log)
        for edge in entry.get('edges', []):
            add_wait(edge, entry['cr'], main, write, log)
    for edge in mapping.get('met', []):
        to_relates(edge, write, log)
    return log


def verify(found: dict, data: dict) -> list[str]:
    left = [f"{cr}: live checkpoint metadata ({(data['detail'][cr].get('metadata') or {}).get('checkpoint')})"
            for cr in data['live'] if (data['detail'][cr].get('metadata') or {}).get('checkpoint')]
    return (left + [f"{edge['waiter']}: still waits on {edge['on']}, a closed design in unlanded {edge['cr']}" for edge in found['met']])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='verb', required=True)
    inv = sub.add_parser('inventory')
    inv.add_argument('--mapping', metavar='FILE', help='write the draft mapping for the owner to review and approve')
    app = sub.add_parser('apply')
    app.add_argument('mapping')
    app.add_argument('--apply', action='store_true', help='write; without it, print the steps a run would take after its rechecks')
    app.add_argument('--copy', metavar='FOLDER', help='the board is the rehearsal copy in FOLDER (convert-stored-forms.py --rehearse makes it): no deciding session is required')
    sub.add_parser('verify')
    args = parser.parse_args()
    try:
        main_root = main_checkout()
        if args.verb == 'inventory':
            data = read_board()
            found = inventory(data, main_root)
            print_inventory(found)
            if args.mapping:
                Path(args.mapping).write_text(json.dumps(draft_mapping(found), indent=2) + '\n', encoding='utf-8')
                print(f'draft mapping written to {args.mapping}; set approved_by after the owner approves it')
        elif args.verb == 'apply':
            mapping = load_mapping(args.mapping)
            if args.apply:
                if args.copy:
                    rehearsal_copy(args.copy, main_root)
                else:
                    active_decider()
                apply(mapping, main_root, False)  # recheck every record before the first write
            for line in apply(mapping, main_root, args.apply):
                print(line)
            if not args.apply:
                print('dry run: nothing written; rerun with --apply')
        else:
            data = read_board()
            left = verify(inventory(data, main_root), data)
            for line in left:
                print(line)
            print('conversion incomplete' if left else 'no live checkpoint metadata or met design wait left: conversion complete')
            return 1 if left else 0
    except (ConversionError, OSError, ValueError, KeyError) as error:
        print(f'checkpoint conversion stopped: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
