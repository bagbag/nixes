"""The board CLI and the board reads several steps share (holds, statuses)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .base import BOARD, OVERLAP_LIMIT, ProtocolError, env

if TYPE_CHECKING:
    from .engine import Context


# Board access through the board CLI (sibling board; PROTOCOL_BOARD overrides for tests).

def board_root(start: Path) -> Path | None:
    return next((d for d in (start, *start.parents) if (d / '.beads').is_dir()), None)


class Board:
    def __init__(self, repo: str | None, actor: str):
        self.repo, self.actor = repo, actor

    def run(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
        command = [env()['PROTOCOL_BOARD']] if env().get('PROTOCOL_BOARD') else [sys.executable, str(BOARD)]
        return subprocess.run([*command, *args], input=stdin, capture_output=True, text=True, cwd=self.repo,
                              env={**env(), 'BEADS_ACTOR': self.actor})

    def checked(self, *args: str, stdin: str | None = None) -> str:
        result = self.run(*args, stdin=stdin)
        if result.returncode != 0:
            raise ProtocolError(f"`board {' '.join(args)}` failed: {(result.stderr or result.stdout).strip()}")
        return result.stdout

    def json(self, *args: str, stdin: str | None = None):
        output = self.checked(*args, stdin=stdin)
        try:
            return json.loads(output)
        except ValueError:
            raise ProtocolError(f"`board {' '.join(args)}` printed no JSON: {output[:200]}") from None


def related_hits(board: Board, text: str) -> list[tuple[str, str]]:
    """(id, title) of the board items a new draft's text resembles, rarest shared words first."""
    found = board.json('related', '--like', '-', '--json', '--limit', str(OVERLAP_LIMIT), stdin=text)
    return [(item['id'], (item.get('title') or '') + (f" (queue {item['queue']})" if item.get('queue') else ''))
            for item in found.get('items') or []]


COUNT_KEYS = ('questions', 'decided', 'toPlan', 'inReview', 'forUser')


def held_decided(board: Board, found: dict | None = None) -> list[str]:
    """The decided records this session holds, a worker's holds included (r13 q50): `board health --items decided`
    rows carry their `holder`."""
    found = found if found is not None else board.json('health', '--json', '--items', 'decided')
    me = board.actor.split('/', 1)[0]
    return [row['id'] for row in (found.get('items') or {}).get('decided') or []
            if row.get('holder') and str(row['holder']).split('/', 1)[0] == me]


def claim_items(ctx: Context, items: list[str]) -> None:
    """Claims items for the round. A hold the session had before (a decided record awaiting release, `board claim`'s
    "already held" line) stays the session's: the round releases only what it claimed itself."""
    output = ctx.board.checked('claim', *items)
    before = {line.split(':', 1)[0] for line in output.splitlines() if ': already held by ' in line}
    ctx.round['claimed'] = [*ctx.round.get('claimed', []), *(item for item in items if item not in before)]


def split_holds(ctx: Context, holders: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """(live, gone) among the records another session holds (id -> holder), by the board's mark for the holder."""
    me = ctx.board.actor.split('/', 1)[0]
    foreign = {rid: holder for rid, holder in holders.items() if holder and holder.split('/', 1)[0] != me}
    if not foreign:
        return {}, {}
    return foreign_holds(ctx, [{'id': rid, 'holder': holder} for rid, holder in foreign.items()], ctx.board.json('position', '--json'))


def foreign_holds(ctx: Context, items: list[dict], position: dict) -> tuple[dict[str, str], dict[str, str]]:
    """(live, gone): item id -> holder of the items another session holds, split by the board's mark for the holder
    (`board position` `held`): a gone session's hold can be taken over, a live one's cannot be claimed."""
    me = ctx.board.actor.split('/', 1)[0]
    holders = {item['id']: str(item['holder']) for item in items
               if item.get('holder') and str(item['holder']).split('/', 1)[0] != me}
    marks = {h['id']: h.get('mark') for h in position.get('held') or []} if holders else {}
    return ({rid: holder for rid, holder in holders.items() if marks.get(rid) != 'gone'},
            {rid: holder for rid, holder in holders.items() if marks.get(rid) == 'gone'})


def statuses(ctx: Context, ids) -> dict[str, str | None]:
    ids = list(dict.fromkeys(ids))
    found = ctx.board.json('show', *ids, '--json', '--field', 'status') if ids else {}
    return {rid: (found.get(rid) or {}).get('status') for rid in ids}
