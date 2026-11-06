"""Release: the Approval, Owners, Release and Closed steps and the `release` protocol."""
from __future__ import annotations

import itertools
import re
import subprocess
from pathlib import Path

from .base import ProtocolError, TEXT_MAX, TITLE_MAX, cut, env, lines, plural, utcnow
from .store import next_id
from .boards import statuses
from .engine import Context, PROTOCOLS, Protocol, Step, fail, questions
from .told import first_time, report_hint
from .record import refresh_board
from .ask import approval_question, approval_reasons, ask_enter, ask_text
from .release_set import (
    APPROVE, HOLD, in_set, recheck_accept, recheck_text, release_label, set_record, set_rows, start_release, stop
)
from .release_checks import (
    board_check_accept, board_check_enter, board_check_text, own_rulings_accept, own_rulings_text, scoped_accept,
    scoped_enter, scoped_text
)


def release_question_text(ctx: Context) -> str:
    """`Release 3 records? Unsure: tstdl-a (…) Revised: tstdl-b (…)`: an unsure ruling first (r14 q56), within the dialog
    limits whatever the set holds; `unsure_rulings` gives it in full."""
    count = plural(len(in_set(ctx)), 'record')
    text = f"Release the session's {count}?" if ctx.round.get('source') else f"Release {count}?"
    unsure = '; '.join(f"{x['record']} ({x['ruling']})" for x in ctx.round['rulings'] or [] if not x['sure'])
    changes = '; '.join(f"{rec['id']} ({cut(rec['change'], 80)})" for rec in ctx.round['set'] if rec['state'] == 'revised')
    return cut(' '.join(filter(None, [text, f'Unsure: {unsure}' if unsure else '', f'Revised: {changes}' if changes else ''])), TEXT_MAX)


def unsure_rulings(ctx: Context) -> str:
    """The unsure rulings in full, for the Release option's preview: the question text cuts them."""
    return '\n\n'.join(f"{x['record']}: {x['ruling']}\nAlternative: {x['alternative']}"
                        for x in ctx.round['rulings'] or [] if not x['sure'])


def approve(ctx: Context, origin: str, how: str, quote: str | None = None) -> str:
    ctx.round['approval'] = {'origin': origin, 'how': how, 'quote': quote, 'at': utcnow()}
    ctx.log('approved', origin=origin, how=how)
    return 'owners'


def approval_enter(ctx: Context) -> str | None:
    """Approval from a person only (r3-q7): a typed or pressed /release-round counts when every own ruling is sure and the set
    is unchanged (r4-q16); otherwise an engine-issued dialog question asks."""
    r = ctx.round
    if r['approval']:
        return 'owners'
    q = approval_question(ctx)
    if q and q['status'] == 'answered':
        if q['answer'] == APPROVE:
            return approve(ctx, q['origin'], 'dialog question', q.get('quote'))
        if q['answer'] == HOLD:
            return stop(ctx, f"held at approval ({q['origin']})", [], hold=True)
        # the user's own words (Codex model-reported) pick no option: ask again
        q.update(status='ready', answer=None, typed=q['answer'])
        ctx.state['answers'].pop(q['id'], None)
        ctx.messages.append(f"The approval needs the user's pick of {APPROVE} or {HOLD}; they wrote \"{q['typed']}\". "
                            'Ask again (`protocol step` with {}).')
        return 'ask'
    changed = [rec['id'] for rec in r['set'] if rec['state'] != 'set']
    unsure = [x for x in r['rulings'] or [] if not x['sure']]
    if r['conditional'] and not changed and not unsure:
        return approve(ctx, r['conditional']['origin'], '/release-round')
    if q is None:
        reasons = approval_reasons(ctx)
        q = {'id': next_id(ctx.state, 'question', 'q'), 'board': None, 'kind': 'confirm-own-rulings', 'multiSelect': False,
             'waitsOn': [], 'for': None, 'settles': [], 'premises': None, 'round': r['id'], 'status': 'draft', 'overlaps': [],
             'searched': True, 'answer': None,
             'text': release_question_text(ctx),
             'title': f'Release {release_label(ctx)}'[:TITLE_MAX], 'header': 'Release',
             'options': [{'label': APPROVE, 'description': 'Owner writes, then board release',
                          **({'preview': unsure_rulings(ctx)} if unsure else {})},
                         {'label': HOLD, 'description': 'Nothing releases; the records stay decided. Say why: a round takes what you held'}],
             'recommendation': APPROVE, 'strength': None, 'strongBecause': None, 'leanBecause': None}
        r['questions'].append(q)
        ctx.log('approval-asked', question=q['id'], reasons=reasons)
    return 'ask'


def approval_text(ctx: Context) -> str:
    reasons = approval_reasons(ctx)
    return f"Release {ctx.round['id']} · Approval: `protocol step` with {{}} continues." \
        + (f" The dialog asks because: {'; '.join(reasons)}." if reasons else '')


def release_ask_accept(ctx: Context, report: dict) -> str:
    if ctx.round['batch']:
        fail(f"waiting on the user's answer to {ctx.round['batch']['marker']}")
    for q in questions(ctx):
        q.pop('typed', None)  # read: the question goes out again
    ctx.round.pop('reading', None)
    return 'ask'


def anchors_of(text: str) -> set[str]:
    """GitHub heading slugs (lowercase; punctuation but hyphens and spaces dropped; spaces to hyphens; repeats get
    -1, -2) outside code fences, plus explicit `<a id=…>` and `{#…}` anchors. Mirrors the validator's heading_anchors."""
    found, seen, fenced = set(), {}, False
    for line in text.splitlines():
        if re.match(r'\s*(```|~~~)', line):
            fenced = not fenced
            continue
        if fenced:
            continue
        found.update(re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)["\']', line))
        found.update(re.findall(r'\{#([\w-]+)\}', line))
        heading = re.match(r'#{1,6}\s+(.+?)\s*#*\s*$', line)
        if heading:
            title = re.sub(r'\s*\{#[\w-]+\}\s*$', '', heading.group(1))
            slug = re.sub(r'[^\w\- ]', '', title.strip().lower()).replace(' ', '-')
            count = seen.get(slug, 0)
            seen[slug] = count + 1
            found.add(slug if not count else f'{slug}-{count}')
    return found


def owner_path(ctx: Context, written: str) -> Path:
    """Repo-relative paths resolve from the board's repository root; absolute and ~ or $HOME paths as written."""
    home = env().get('HOME') or str(Path.home())
    if written.startswith('$HOME/') or written == '$HOME':
        written = home + written[5:]
    elif written.startswith('~/') or written == '~':
        written = home + written[1:]
    path = Path(written)
    return path if path.is_absolute() else Path(ctx.board.repo) / path


def git_ignored(ctx: Context, shown: str) -> bool:
    """Whether git ignores a repository-relative owner path (an installed `~`/`$HOME` or absolute path is not checked).
    Without git, or outside a git repository, nothing is ignored: the check is skipped."""
    if shown.startswith(('~', '$HOME', '/')):
        return False
    try:
        return subprocess.run(['git', 'check-ignore', '-q', '--', shown], cwd=ctx.board.repo, capture_output=True).returncode == 0
    except OSError:
        return False


def rule_owner_text(description: str) -> str:
    match = re.search(r'^##\s+Rule owner\s*$(.*?)(?=^##\s|\Z)', description or '', re.M | re.S)
    return match.group(1) if match else ''


def memory_section(name: str) -> str:
    """A `##` section of project-memory.md, read from the installed file. Durable owners says where each kind of rule is
    written, Closure what a doc write owes (r20-q72)."""
    path = Path(env().get('HOME') or str(Path.home())) / '.agents' / 'skills' / 'shared' / 'project-memory.md'
    try:
        match = re.search(rf'^## {name}\s*$(.*?)(?=^## |\Z)', path.read_text(encoding='utf-8'), re.M | re.S)
    except OSError:
        match = None
    if match is None or not match.group(1).strip():
        return f'{name}: the `## {name}` section of {path} is missing; read it before writing durable docs.'
    return f'## {name} (project-memory.md)' + match.group(1).rstrip()


def owners_text(ctx: Context) -> str:
    return lines(
        f"Release {ctx.round['id']} · Owner writes (decide.md Release 5): write each rule into its one owner, replacing "
        "the text it supersedes, and name each path (with its anchor) in the record's `## Rule owner` (rewrite the "
        'record with `board record <id> <file>`). A rule a topic\'s design-target doc states is written now, not pending. Report per record its owners: written {path, anchor} (a repo path '
        'from the board root, or absolute/~; installed files by their installed path), none {reason}, or '
        'pending {item} (an open board item).',
        lines(memory_section('Durable owners'), memory_section('Closure')) if first_time(ctx, 'owners') else '',
        *set_rows(ctx),
        report_hint(ctx, 'owners', {'owners': {(in_set(ctx) or ['<id>'])[0]: [{'written': {'path': 'docs/x.md', 'anchor': 'the-rule'}},
                                                                              {'pending': {'item': '<task id>'}}]}}),
    )


def owners_accept(ctx: Context, report: dict) -> str:
    owners = report.get('owners')
    current = in_set(ctx)
    if not isinstance(owners, dict):
        fail('`owners` maps each record to its owner entries')
    problems = [f'no owners for {rid}' for rid in current if not owners.get(rid)]
    problems += [f'{rid} is not in the set' for rid in owners if rid not in current]
    written, pending = {}, {}
    for rid, entries in owners.items():
        for index, entry in enumerate(entries if isinstance(entries, list) else [None]):
            where = f'owners.{rid}[{index}]'
            kind = next(iter(entry), None) if isinstance(entry, dict) and len(entry) == 1 else None
            body = entry.get(kind) if kind else None
            if kind == 'written' and isinstance(body, dict) and isinstance(body.get('path'), str) and body['path'].strip() \
                    and isinstance(body.get('anchor') or '', str):
                written.setdefault(rid, []).append((body['path'].strip(), (body.get('anchor') or '').lstrip('#')))
            elif kind == 'none' and isinstance(body, dict) and str(body.get('reason') or '').strip():
                pass
            elif kind == 'pending' and isinstance(body, dict) and str(body.get('item') or '').strip():
                pending.setdefault(body['item'].strip(), []).append(rid)
            else:
                problems.append(f'{where}: one of {{"written": {{"path", "anchor"?}}}}, {{"none": {{"reason"}}}}, '
                                '{"pending": {"item"}}')
    if problems:
        fail('owner writes: ' + '; '.join(problems))
    for rid, paths in written.items():
        for shown, anchor in paths:
            path = owner_path(ctx, shown)
            resolved = path.resolve()
            if not resolved.is_file():  # the installed state: a rendered, linked file counts as it reads
                problems.append(f'{rid}: {shown} does not exist ({path})')
            elif git_ignored(ctx, shown):
                problems.append(f'{rid}: {shown} is ignored by git (e.g. .scratch): write the rule into a tracked or trackable owner')
            elif anchor and resolved.suffix.lower() not in ('.md', '.markdown'):
                problems.append(f'{rid}: {shown}#{anchor}: anchors name Markdown headings; name the section in words')
            elif anchor and anchor not in anchors_of(resolved.read_text(encoding='utf-8', errors='replace')):
                problems.append(f'{rid}: {shown} has no heading or anchor #{anchor}')
    if pending:
        try:
            found = ctx.board.json('show', *pending, '--json', '--field', 'status')
        except ProtocolError as error:
            found = {}
            problems.append(f"pending items: {error}")
        problems += [f"{', '.join(rids)}: pending item {item} is {(found.get(item) or {}).get('status')}, not open"
                     for item, rids in pending.items() if item in found and found[item].get('status') == 'closed']
    if written:
        texts = ctx.board.json('show', *written, '--json', '--field', 'description')
        for rid, paths in written.items():
            section = rule_owner_text((texts.get(rid) or {}).get('description') or '')
            problems += [f'{rid}: its ## Rule owner does not name {shown}; fix the record text and run '
                         f'`board record {rid} <file>`' for shown, _ in paths if shown not in section]
    if problems:
        fail('owner writes: ' + '; '.join(problems))
    ctx.round['owners'] = owners
    ctx.log('owners-checked', written=sum(len(paths) for paths in written.values()), pending=sorted(pending))
    return 'release'


def release_enter(ctx: Context) -> str | None:
    """Runs board release (with the answered closes), then the other supersedes. Resumable (r4-q19): statuses come
    first, and released records, closed questions and done supersedes are not run again."""
    r = ctx.round
    ids = [rec['id'] for rec in r['set'] if rec['state'] in ('set', 'revised', 'released')]  # a rerun keeps the released ones
    fulls = [sup['old'] for sup in r['supersedes'] if sup['partial'] is None]
    now = statuses(ctx, [*ids, *fulls, *r['closes']])
    stray = [rid for rid in ids if now[rid] not in ('decided', 'released')]
    if stray:
        ctx.messages.append('Not released: ' + ', '.join(f'{rid} is {now[rid]}' for rid in stray)
                            + '; settle them on the board, then `protocol step` with {}.')
        return None
    still = [q for q in r['closes'] if now[q] != 'closed']
    if r['retry'] or still or any(now[rid] == 'decided' for rid in ids):
        argv = ['release', *ids, *(['--closes', *(f"{q}={','.join(r['closes'][q])}" for q in still)] if still else [])]
        result = ctx.board.run(*argv)
        r['retry'] = result.returncode != 0
        ctx.log('board-release', records=ids, closes=still, exit=result.returncode)
        if result.returncode != 0:
            ctx.messages.append(f"`board {' '.join(argv)}` exited {result.returncode}:\n"
                                + (result.stderr.strip() or result.stdout.strip()))
    for sup in r['supersedes']:
        key = f"{sup['old']}>{sup['new']}"
        if key in r['done'] or (sup['partial'] is None and now.get(sup['old']) == 'closed'):
            continue
        partial = ['--partial', sup['partial']] if sup['partial'] is not None else []
        result = ctx.board.run('supersede', sup['old'], '--with', sup['new'], *partial)
        if result.returncode == 0:
            r['done'].append(key)
            ctx.log('superseded', old=sup['old'], new=sup['new'], partial=sup['partial'])
        else:
            ctx.messages.append(f"`board supersede {sup['old']} --with {sup['new']}` exited {result.returncode}: "
                                + (result.stderr.strip() or result.stdout.strip()))
    try:  # the writes above stand: a failing read leaves the step to rerun, statuses first
        after = statuses(ctx, [*ids, *fulls, *r['closes']])
    except ProtocolError as error:
        ctx.messages.append(f'Board statuses unavailable after the writes ({error}); `protocol step` with {{}} rereads them.')
        return None
    for rid in ids:
        if after[rid] == 'released':
            set_record(ctx, rid)['state'] = 'released'
    for sup in r['supersedes']:
        if sup['partial'] is None and after.get(sup['old']) == 'closed' and f"{sup['old']}>{sup['new']}" not in r['done']:
            r['done'].append(f"{sup['old']}>{sup['new']}")
    r['outcome'] = {'closed': [q for q in r['closes'] if after[q] == 'closed'],
                    'open': [q for q in r['closes'] if after[q] != 'closed']}
    finished = not r['retry'] and all(after[rid] == 'released' for rid in ids) and not r['outcome']['open'] \
        and all(f"{sup['old']}>{sup['new']}" in r['done'] for sup in r['supersedes'])
    if not finished:
        ctx.messages.append('Release not finished: fix what the board reported, then `protocol step` with {} reruns '
                            'only what remains (released records, closed questions and done supersedes stay done).')
        return None
    ctx.log('release-done', records=ids, closed=r['outcome']['closed'])
    return 'closed'


def release_text(ctx: Context) -> str:
    return f"Release {ctx.round['id']} · Release: waiting for a rerun (`protocol step` with {{}})."


def release_step_accept(ctx: Context, report: dict) -> str:
    return 'release'


def release_closed_enter(ctx: Context) -> None:
    """A release that ran to its close settles what it did to the records: a released one is clear of any drop reason; a
    dropped one, and each record a stop held back, gets one (the next round's Stage shows it, a bare release leaves the record
    out until a round records it again or a release releases it). A person's Hold gives none (r14 q52). An abandoned release
    gets here never."""
    r = ctx.round
    r['pending'], r['batch'] = None, None
    r['closedAt'] = utcnow()
    reasons = ctx.state.setdefault('dropReasons', {})
    stopped = r.get('stopped') or {'reason': None, 'ids': []}
    held_back = [] if stopped.get('hold') else stopped['ids']
    for rec in r['set']:
        if rec['state'] == 'released':
            reasons.pop(rec['id'], None)
        elif rec['state'] == 'dropped' or rec['id'] in held_back:
            reasons[rec['id']] = rec['reason'] if rec['state'] == 'dropped' else stopped['reason']
    if refresh_board(ctx):
        r['countsAt'] = r['closedAt']
    ctx.log('closed', protocol='release', released=[rec['id'] for rec in r['set'] if rec['state'] == 'released'])


def release_closed_text(ctx: Context) -> str:
    r = ctx.round
    counts = ctx.state.get('counts')
    board = (f"Board: {counts['questions']} open questions, {counts['decided']} decided awaiting release, "
             f"{counts['toPlan']} released to plan, {counts['inReview']} in review, {counts['forUser']} waiting on the user."
             if counts and r.get('countsAt') else 'No board counts.')
    if r['stopped'] and r['stopped'].get('hold'):
        return '\n'.join([
            f"Release {r['id']} held: nothing released; the records stay decided and held.",
            'Next: ask what it was held for, then a round on those records, or on the set when the reason spreads to the others '
            '(`protocol start round`; its check loop opens with step-back). A later `protocol start release` takes the rest.', board])
    if r['stopped']:
        ids = ', '.join(r['stopped']['ids'])
        return '\n'.join([
            f"Release {r['id']} stopped: {r['stopped']['reason']}. Nothing released; {ids} stay decided and held.",
            f'Next: a round on {ids} (`protocol start round`, then classify and select them; its check loop opens '
            'with step-back).', board])
    dropped = [rec for rec in r['set'] if rec['state'] == 'dropped']
    outcome = r.get('outcome') or {'closed': [], 'open': []}
    return '\n'.join([
        f"Release {r['id']} closed.",
        *(f"- released {rec['id']}: {rec['title']}" + (f" (revised: {rec['change']})" if rec.get('change') else '')
          for rec in r['set'] if rec['state'] == 'released'),
        *(f"- superseded {sup['old']} by {sup['new']}" + (f" (rule: {sup['partial']})" if sup['partial'] is not None else '')
          for sup in r['supersedes']),
        *(f"- closed {q}: answered by released {', '.join(r['closes'][q])}" for q in outcome['closed']),
        *(f"- dropped {rec['id']} ({rec['reason']}): it stays decided and held for a round" for rec in dropped),
        board,
        'Next (decide.md Release 7): run `protocol next`.'
        + (f" Dropped records go to a round: {', '.join(rec['id'] for rec in dropped)}." if dropped else '') + ' Wait for the user.',
    ])


ID_WORD = re.compile(r'^[A-Za-z][\w]*-[\w.]+$')


def stamp_release(ctx: Context, origin: str, args: str = '') -> str:
    """A /release-round the person typed or pressed (r4-q16, press: user 2026-10-31): conditional approval of the open
    release, or of the release it starts. Leading id-shaped words after the command name the set; the rest is the
    skill's focus. The stamp lapses when the run stops or its set changes."""
    if origin not in ('composer', 'bridge', 'press'):
        fail(f'release-round: only the person approves (origin composer, bridge or press), not {origin}')
    ids = list(itertools.takewhile(ID_WORD.match, str(args or '').split()))
    r = ctx.round
    if r and r['step'] != 'closed' and r['protocol'] != 'release':
        fail(f"round {r['id']} is open at {r['step']}: the release starts once it closes")
    if not r or r['step'] == 'closed':
        start_release(ctx, ids)
        r = ctx.round
    elif ids and sorted(ids) != sorted(rec['id'] for rec in r['set']):
        fail(f"release {r['id']} is open on {', '.join(rec['id'] for rec in r['set'])}: finish it, or `protocol abandon`, "
             'before releasing other ids')
    if r['approval']:
        return f"Release {r['id']} is approved already."
    r['conditional'] = {'origin': origin, 'at': utcnow()}
    ctx.log('stamped', origin=origin)
    return (f"Release {r['id']}: the /release-round approves it if every own ruling is sure and no record "
            'leaves the set or is revised; otherwise a dialog asks.')


RELEASE = Protocol('release', [
    Step('recheck', recheck_text, recheck_accept),
    Step('board-check', board_check_text, board_check_accept, board_check_enter),
    Step('own-rulings', own_rulings_text, own_rulings_accept),
    Step('scoped', scoped_text, scoped_accept, scoped_enter),
    Step('approval', approval_text, release_ask_accept, approval_enter),
    Step('ask', ask_text, release_ask_accept, ask_enter),
    Step('owners', owners_text, owners_accept),
    Step('release', release_text, release_step_accept, release_enter),
    Step('closed', release_closed_text, None, release_closed_enter),
], after_ask='approval')
PROTOCOLS['release'] = RELEASE
