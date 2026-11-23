#!/usr/bin/env python3
"""Convert a board's design checkpoint records to ordinary design change requests, on the runtime without checkpoints.

    convert-design-checkpoints.py inventory [--mapping FILE]   read-only: records, transitions, manual steps
    convert-design-checkpoints.py apply MAPPING [--apply]      recheck, then write (a dry run without --apply)
    convert-design-checkpoints.py verify                       read-only: what is left to convert

Run it in the project's checkout after installing the new runtime. The mapping is the owner-approved file that
`inventory --mapping` drafts; `apply` writes only what it lists: `return`, `wait`, `unlink`, `link`, and raw bd
writes for what no board verb does any more (clearing the checkpoint marker, reopening a returned design item).
Waits the old runtime counted as met (on a closed design inside an unlanded change request) become `relates-to`
links, which keeps their meaning. Text placement, documentation CRs, ratification verdicts and the choices on
missing provenance stay with their owners: `inventory` lists them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

BOARD = Path.home() / '.agents' / 'bin' / 'board'
SESSION = Path.home() / '.agents' / 'bin' / 'session'
BLOCKING = ('blocks', 'blocked-by', 'depends-on', 'conditional-blocks', 'waits-for')
AT_REVIEW = ('in_review', 'needs_acceptance')
VERDICT = re.compile(r'(passed|accepted) (agent )?design checkpoint')
SCRATCH_REF = re.compile(r'[~/.][^\s`"\')\]>,;]*scratch[^\s`"\')\]>,;]*')
DOC_REF = re.compile(r'(?<![\w/])(?:[\w.-]+/)*docs/[\w./-]+\.md')
RETURN_NOTE = 'design checkpoint converted to an ordinary design change request: author the doc on the branch'
TRANSITIONS = {
    'authoring-return': 'live checkpoint with outstanding design: return to authoring, doc on branch, ordinary review',
    'authoring-clear': 'returned or queued checkpoint: clear the marker, doc on branch, ordinary review',
    'preserve-passed': 'passed checkpoint with implementation live: preserve verdict and branch; documentation CR if the text has no doc owner',
    'hold': 'hold: no write; the owner resolves the reasons',
}


class ConversionError(Exception):
    pass


def run(path: Path, *args: str, cwd: Path | None = None) -> str:
    result = subprocess.run([str(path), *args], capture_output=True, text=True, cwd=cwd)
    if result.returncode:
        raise ConversionError(f"{path.name} {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def board(*args: str) -> str:
    return run(BOARD, *args)


def raw(*args: str) -> str:
    """A bd write no board verb does on the new runtime; the owner's approval of the mapping authorizes it."""
    return board('bd', '--raw', '--yes', *args)


def git(cwd: Path, *args: str) -> str | None:
    result = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def active_decider() -> None:
    actor = run(SESSION, 'actor').strip().split('/', 1)[0]
    registrations = [json.loads(line) for line in run(SESSION, 'list').splitlines() if line.strip()]
    role = next((row.get('role') for row in registrations if row.get('actor') == actor), None)
    if role not in ('lead', 'solo'):
        raise ConversionError('run the conversion in a registered lead or solo session')


# --- reading the board -------------------------------------------------------------------------------------------

def show(ids: list[str]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for start in range(0, len(ids), 40):
        found.update(json.loads(board('show', '--json', *ids[start:start + 40])))
    return found


def read_board() -> dict:
    """Rows of every item (closed too), the full record of each live change request, its children and each
    needs_ratification item, and the blocking edges."""
    rows = json.loads(board('bd', 'list', '--all', '--json', '--limit', '0'))
    by_id = {row['id']: row for row in rows}
    live = [row['id'] for row in rows if row['issue_type'] == 'change-request' and row['status'] != 'closed']
    children = {cr: sorted(row['id'] for row in rows if row.get('parent') == cr) for cr in live}
    ratifying = [row['id'] for row in rows if row['status'] == 'needs_ratification']
    detail = show(sorted({*live, *(child for kids in children.values() for child in kids), *ratifying}))
    edges = {(dep['issue_id'], dep['depends_on_id'], dep['type']) for row in rows for dep in row.get('dependencies') or []}
    return {'rows': by_id, 'live': live, 'children': children, 'ratifying': ratifying, 'detail': detail,
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
    designs = {child: data['detail'][child] for child in data['children'][cr_id] if data['detail'][child]['issue_type'] == 'design'}
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
    designs = {key: item for key, item in children.items() if item['issue_type'] == 'design'}
    bodies = {key: body_facts(item) for key, item in designs.items()}
    comments = [str(c.get('text') or '') for c in record.get('comments') or []]
    meta = record.get('metadata') or {}
    row = {'cr': cr_id, 'title': record['title'], 'state': state, 'git': facts, 'bodies': bodies, 'reasons': [], 'manual': [], 'notes': []}
    implementation = sorted(key for key, item in children.items() if item['issue_type'] != 'design' and item['status'] != 'closed'
                            and not (item.get('metadata') or {}).get('ratification'))
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
        elif state['status'] not in ('open', 'needs_acceptance'):
            row['reasons'].append(f"status {state['status']}: the owner resolves it first")
        if state['opened_review']:
            row['reasons'].append('open user review: the owner ends it and records the edits')
        if facts['dirty']:
            row['reasons'].append('dirty worktree: unrecorded edits stay with their owner')
        if not facts['tip']:
            row['reasons'].append('no branch cr/' + cr_id)
        row['kind'] = 'hold' if row['reasons'] else ('authoring-return' if state['status'] == 'needs_acceptance' else 'authoring-clear')
        row['manual'].append(f'place the design text in the topic document on cr/{cr_id}; compare it with the approved or reviewed range, then ordinary handover')
        if open_designs and not designs:
            row['manual'].append('design items missing')
        if implementation:
            row['manual'].append(f"move implementation items {', '.join(implementation)} into a distinct dependent change request (planning)")
    else:
        passed = [key for key, item in designs.items() if item['status'] == 'closed' and VERDICT.search(str(item.get('close_reason') or ''))]
        unproven = [key for key, item in designs.items() if key not in passed]
        if not designs:
            return {**row, 'kind': None}
        if unproven:
            row['reasons'].append(f"missing provenance: design item {', '.join(unproven)} carries no passed or accepted verdict in its close reason")
        row['kind'] = 'hold' if row['reasons'] else 'preserve-passed'
        row['manual'].append('if the accepted text has no durable doc owner, carry it unchanged into a documentation CR linked to this record and its verdict; land it before new dependent authoring')
        if implementation:
            row['notes'].append(f"implementation items live: {', '.join(implementation)}")
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
        if (w and b and cr and b['issue_type'] == 'design' and b['status'] == 'closed' and w['status'] != 'closed'
                and cr_of.get(waiter) != cr):
            found.append({'waiter': waiter, 'on': blocker, 'cr': cr})
    return found


def inventory(data: dict, main: Path) -> dict:
    rows = [row for row in (classify(data, main, cr) for cr in data['live']) if row['kind']]
    ratifications = []
    for item_id in data['ratifying']:
        item = data['detail'][item_id]
        if (item.get('metadata') or {}).get('ratification') == 'design':
            ratifications.append({'id': item_id, 'cr': item.get('parent'), 'title': item['title'],
                                  'review_worktree': bool((item.get('metadata') or {}).get('opened_tip')) or (main / '.worktrees' / item_id / '.git').is_file()})
    return {'records': rows, 'ratifications': ratifications, 'met': met_waits(data)}


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
    for item in found['ratifications']:
        print(f"{item['id']}  design ratification of {item['cr']}  review worktree={'yes' if item['review_worktree'] else 'no'}")
        print('  transition: resolve it with agents board ratify; closed ratifications stay')
    for edge in found['met']:
        print(f"{edge['waiter']} waits on {edge['on']}, a closed design in unlanded {edge['cr']}: met under the old runtime; apply makes it relates-to")
    if not found['records'] and not found['ratifications'] and not found['met']:
        print('no live checkpoint, passed design, design ratification or met design wait')


def draft_mapping(found: dict) -> dict:
    records = []
    for row in found['records']:
        steps = {'authoring-return': ['return', 'clear'], 'authoring-clear': ['clear']}.get(row['kind'], [])
        entry = {'cr': row['cr'], 'kind': row['kind'], 'steps': steps, 'expect': row['state']}
        if row['kind'] != 'hold':
            entry['edges'] = row['edges']
        records.append(entry)
    return {'version': 1, 'approved_by': '', 'records': records, 'ratifications': [item['id'] for item in found['ratifications']],
            'met': found['met']}


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
    """Recheck: the approved state returns to authoring, reopens its design items and clears; a returned state finishes
    the reopens and clears; a cleared marker is done; anything else stops."""
    cr_id, expect, steps = entry['cr'], entry['expect'], entry.get('steps', [])
    current = current_state(main, cr_id)
    if current['checkpoint'] is None:
        log.append(f'{cr_id}: converted already (no checkpoint marker)')
        return
    reopened = {key: 'open' if status == 'in_review' else status for key, status in expect['design'].items()}
    returned = {**expect, 'status': 'open', 'design': reopened}
    # Returned with any of its design items still unreopened: a run stopped between the return and the last reopen.
    resumable = ({**current, 'design': expect['design']} == {**expect, 'status': 'open'} and current['design'].keys() == expect['design'].keys()
                 and all(status in (expect['design'][key], reopened[key]) for key, status in current['design'].items()))
    needs_return = 'return' in steps and current == expect
    if not needs_return and current != expect and not resumable:
        raise diverged(cr_id, expect, current, ('status', 'holder', 'checkpoint', 'tip', 'design', 'opened_review', 'dirty'))
    if needs_return:
        log.append(f'{cr_id}: return to authoring')
        if write:
            board('return', cr_id, RETURN_NOTE)
    reopen = [key for key, status in (current_state(main, cr_id) if write and needs_return else current)['design'].items() if status == 'in_review']
    if reopen:  # the new runtime's return leaves design items as they are; idempotent on a rerun
        log.append(f"{cr_id}: reopen design items {', '.join(reopen)}")
        if write:
            for key in reopen:
                raw('update', key, '--status', 'open')
    if write and 'return' in steps:
        after = current_state(main, cr_id)
        if after != returned:
            raise diverged(cr_id, returned, after, tuple(returned))
    log.append(f'{cr_id}: clear the checkpoint marker')
    if write:
        raw('update', cr_id, '--unset-metadata', 'checkpoint')
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
    rows = {row['id']: row for row in json.loads(board('bd', 'list', '--all', '--json', '--limit', '0'))}
    waits = {(dep['issue_id'], dep['depends_on_id']) for row in rows.values() for dep in row.get('dependencies') or [] if dep['type'] in BLOCKING}
    if (waiter, cr_id) in waits:
        log.append(f'{waiter}: already waits on {cr_id}')
        return
    row = rows.get(waiter, {})
    current = {'status': row.get('status'), 'holder': row.get('assignee') or None}
    if current != edge['expect'] or (waiter, via) not in waits:
        raise ConversionError(f"{waiter} diverged from the approved mapping (expected {edge['expect']} waiting on {via}, found {current}"
                              f"{'' if (waiter, via) in waits else ', the old wait is gone'}); stopped before writing")
    log.append(f'{waiter}: wait on {cr_id}')
    if write:
        board('wait', waiter, '--on', cr_id, '--for', f'waits for the design change request {cr_id} to land (checkpoint conversion)')
        if (waiter, cr_id) not in {(a, b) for a, b in read_waits()}:
            raise ConversionError(f'{waiter}: the wait on {cr_id} is not recorded after block')


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
        if kind in BLOCKING:
            board('unlink', waiter, on)
        board('link', waiter, on, '--type', 'relates-to')


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
    for item_id in mapping.get('ratifications', []):
        record = json.loads(board('show', '--json', item_id))[item_id]
        log.append(f"{item_id}: design ratification {record['status']}: resolve through agents board ratify" if record['status'] != 'closed'
                   else f'{item_id}: ratification closed')
    return log


def verify(found: dict, data: dict) -> list[str]:
    left = [f"{cr}: live checkpoint metadata ({(data['detail'][cr].get('metadata') or {}).get('checkpoint')})"
            for cr in data['live'] if (data['detail'][cr].get('metadata') or {}).get('checkpoint')]
    return (left + [f"{item['id']}: design ratification still needs ratification" for item in found['ratifications']]
            + [f"{edge['waiter']}: still waits on {edge['on']}, a closed design in unlanded {edge['cr']}" for edge in found['met']])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='verb', required=True)
    inv = sub.add_parser('inventory')
    inv.add_argument('--mapping', metavar='FILE', help='write the draft mapping for the owner to review and approve')
    app = sub.add_parser('apply')
    app.add_argument('mapping')
    app.add_argument('--apply', action='store_true', help='write; without it, print the steps a run would take after its rechecks')
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
            print('conversion incomplete' if left else 'no live checkpoint metadata, design ratification or met design wait left: conversion complete')
            return 1 if left else 0
    except (ConversionError, OSError, ValueError, KeyError) as error:
        print(f'checkpoint conversion stopped: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
