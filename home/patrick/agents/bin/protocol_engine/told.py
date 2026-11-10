"""What a session was told: report formats and lists said once."""
from __future__ import annotations

from .engine import Context
from . import words


# What a session was told, in one place: `state['told']`, a list of keys, cleared by `protocol compacted` (r17-q62, q63, q67,
# r18-q68..q70). Keys: `format:<step>` (a step's report format), `ask`, `owners`, `items`, `routes` (the answer-routes note) and `same-options:<round>:<ids>` (advice on
# questions offering identical options). Beside it `state['rows']` holds the question rows last printed (r13-q66).

def first_time(ctx: Context, key: str) -> bool:
    """True when this session was not told `key` since its last compaction, and records it. A read the model asked for says
    everything again and records nothing."""
    if ctx.complete:
        return True
    told = ctx.state.setdefault('told', [])
    if key in told:
        return False
    told.append(key)
    return True


def changed_rows(ctx: Context, round_id: str, rows: dict[str, str]) -> list[str]:
    """The question rows that differ from what this session last saw printed (`state['rows']`, cleared by a compaction), and
    records the new rows. A read the model asked for lists every row and records nothing."""
    if ctx.complete:
        return list(rows.values())
    seen = ctx.state.get('rows') or {}
    before = seen.get('rows', {}) if seen.get('round') == round_id else {}
    ctx.state['rows'] = {'round': round_id, 'rows': rows}
    return [row for qid, row in rows.items() if before.get(qid) != row]


def report_format(ctx: Context, kind: str, text: str) -> str:
    """A step's report format: sent the first time per kind since a compaction, empty after. A refused report reprints
    `ctx.formats`, which keeps every format the step text offered."""
    ctx.formats[kind] = text
    return text if first_time(ctx, f'format:{kind}') else ''


def report_hint(ctx: Context, kind: str, example) -> str:
    return report_format(ctx, kind, words.report_hint(example))
