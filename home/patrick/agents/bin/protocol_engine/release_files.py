"""Release of a --no-board round's record files: the set, the Released block, the file counterparts of the board steps."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .base import _call, lines
from . import words
from .store import next_id
from .engine import Context, fail
from .away import SWITCH_TO_SOLO


# A no-board release (r27-q243) runs the board release's steps on record files: the board check is skipped, the owner writes
# stay uncommitted for the user, and the release appends the Released block to each file. A set entry's id is the file stem
# (`r27-q242`); `file` holds its path.

RECORD_FILE = re.compile(r'^(r(\d+))-(q\d+)\.md$')
RELEASED = re.compile(r'^## Released[ \t]*$', re.M)
# The approval's origin as the hand-written blocks word it (`user in chat: "…"`).
WHERE = {'dialog': 'in the question dialog', 'model-reported': 'in the question dialog', 'chat': 'in chat'}


def is_released(text: str) -> bool:
    return RELEASED.search(text) is not None


def question_title(text: str, fallback: str) -> str:
    found = re.search(r'^## Question[ \t]*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    first = next((line.strip() for line in (found.group(1) if found else '').splitlines() if line.strip()), '')
    return first or fallback


def record_files(folder: Path) -> dict[str, Path]:
    return {path.stem: path for path in folder.iterdir() if RECORD_FILE.match(path.name) and path.is_file()}


def select_files(folder: Path, ids: list[str]) -> list[str]:
    """The stems a no-board release takes: the named ids (`q242`, or `r27-q242` when q-ids repeat across rounds), else the
    newest round's records without a Released section."""
    found = record_files(folder)
    if not ids:
        newest = max((int(RECORD_FILE.match(f'{stem}.md').group(2)) for stem in found), default=None)
        stems = sorted((stem for stem in found if int(RECORD_FILE.match(f'{stem}.md').group(2)) == newest),
                       key=lambda stem: int(stem.rsplit('-q', 1)[1]))
        open_stems = [stem for stem in stems if not is_released(found[stem].read_text(encoding='utf-8'))]
        if not open_stems:
            fail(f"no default set: " + (f"every record of the newest round {stems[0].split('-')[0]} in {folder} is released"
                                         if stems else f'{folder} holds no record files')
                 + '; name the ids: `protocol start release --no-board <dir> <id> …`')
        return open_stems
    chosen, problems = [], []
    for one in dict.fromkeys(ids):
        stems = [one] if one in found else sorted(stem for stem in found if stem.endswith(f'-{one}'))
        if not stems:
            problems.append(f'unknown record {one}: no <round>-{one if re.fullmatch(r"q\d+", one) else "<qid>"}.md in {folder}')
        elif len(stems) > 1:
            problems.append(f"{one} names several records ({', '.join(stems)}): name one by its file stem")
        else:
            chosen.append(stems[0])
    already = [stem for stem in chosen if is_released(found[stem].read_text(encoding='utf-8'))]
    if already:
        problems.append('already released: ' + ', '.join(already))
    if problems:
        fail('; '.join(problems))
    return chosen


def start_files(ctx: Context, folder: Path, ids: list[str]) -> None:
    """Starts a release on record files in `folder` (the session needs no board; one in a board repository does not use it)."""
    if ctx.away:
        fail(f'only the person approves a release: {SWITCH_TO_SOLO}')
    folder = folder.resolve()
    if not folder.is_dir():
        fail(f'{folder} is no folder of records')
    stems = select_files(folder, ids)
    files = record_files(folder)
    ctx.state['round'] = {
        'id': next_id(ctx.state, 'round', 'r'), 'protocol': 'release', 'step': 'recheck',
        'repo': None, 'scope': 'release', 'source': None, 'title': None, 'summary': None,
        'records': str(folder), 'cwd': str(_call.get().cwd),
        'items': [], 'points': [], 'classes': {}, 'selected': [], 'questions': [], 'check': {},
        'pending': None, 'observed': {}, 'batch': None, 'batchSeq': 0, 'messages': [],
        'set': [{'id': stem, 'title': question_title(files[stem].read_text(encoding='utf-8'), stem), 'state': 'set',
                 'reason': None, 'file': str(files[stem])} for stem in stems],
        'checks': {}, 'supersedes': [], 'closes': {}, 'rulings': None, 'conditional': None, 'approval': None,
        'owners': {}, 'done': [], 'retry': False, 'stopped': None, 'outcome': None, 'scoped': {'done': []},
    }
    ctx.round['title'] = words.release_label(False, stems)
    ctx.log('start', protocol='release', repo=None, records=stems, taken=[], source=None)
    ctx.go('recheck')


def write_atomic(path: Path, text: str) -> None:
    handle, name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as out:
            out.write(text)
        os.chmod(name, path.stat().st_mode & 0o7777)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def released_line(approval: dict) -> str:
    """`2026-11-11, user in the question dialog: "Release"`, from the approval the person gave."""
    date = approval['at'][:10]
    if approval['origin'] == 'press':
        return f'{date}, user pressed /release-round.'
    quote = (approval.get('quote') or '').strip() or ('/release-round' if approval['how'] == '/release-round' else 'Release')
    return f"{date}, user {WHERE.get(approval['origin'], 'in chat')}: \"{quote}\"."


def read_correction(ctx: Context, rec: dict, source: str) -> tuple[str, str]:
    """(the corrected text, the record file's text) of an own change; a relative `file` starts at the release's directory."""
    try:
        return (Path(ctx.round['cwd']) / source).read_text(encoding='utf-8'), Path(rec['file']).read_text(encoding='utf-8')
    except OSError as error:
        fail(f"{rec['id']}: {error}; fix the file and report again")


def decision_changed_file(ctx: Context, rec: dict, source: str) -> bool:
    from .release_set import decision_text
    after, before = read_correction(ctx, rec, source)
    return decision_text(before) is None or decision_text(after) != decision_text(before)


def write_correction(ctx: Context, rec: dict, source: str) -> None:
    """The file counterpart of `board record`: the corrected text replaces the record file."""
    after, _ = read_correction(ctx, rec, source)
    write_atomic(Path(rec['file']), after)


def release_files_enter(ctx: Context) -> str | None:
    """Appends the Released block to each file. Per file: re-read, skip one that has the block, write beside it and
    replace; a rerun after a failure takes up the files left (never a second block)."""
    r = ctx.round
    block = f"\n## Released\n{released_line(r['approval'])}\n"
    failed = []
    for rec in r['set']:
        if rec['state'] not in ('set', 'revised', 'released'):
            continue
        path = Path(rec['file'])
        try:
            text = path.read_text(encoding='utf-8')
            if not is_released(text):
                write_atomic(path, text.rstrip('\n') + '\n' + block)
        except OSError as error:
            failed.append(f'{rec["id"]}: {error}')
            continue
        rec['state'] = 'released'
    if failed:
        ctx.messages.append(words.files_not_released(failed))
        return None
    ctx.log('release-done', records=[rec['id'] for rec in r['set'] if rec['state'] == 'released'], closed=[])
    return 'closed'
