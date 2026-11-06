"""What a session was told: report formats and lists said once."""
from __future__ import annotations

from .base import json_block
from .engine import Context


# What a session was told, in one place: `state['told']`, a list of keys, cleared by `protocol compacted` (r17-q62, q63, q67,
# r18-q68..q70). Keys: `format:<step>` (a step's report format), `ask`, `owners`, `items`, and per check cycle
# `cycle:<what>:<round>:<check run>.<cycle>` (the question list).

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


def cycle_key(ctx: Context, what: str) -> str:
    r = ctx.round
    return f"cycle:{what}:{r['id']}:{r.get('checkRun', 0)}.{r['check'].get('cycle', 0)}"


def forget_runs(ctx: Context) -> None:
    """A new run starts: the old runs' cycles go from the record."""
    ctx.state['told'] = [key for key in ctx.state.get('told') or [] if not key.startswith('cycle:')]


def report_format(ctx: Context, kind: str, text: str) -> str:
    """A step's report format: sent the first time per kind since a compaction, empty after. A refused report reprints
    `ctx.formats`, which keeps every format the step text offered."""
    ctx.formats[kind] = text
    return text if first_time(ctx, f'format:{kind}') else ''


def report_hint(ctx: Context, kind: str, example) -> str:
    return report_format(ctx, kind, f'Report with `protocol step` (stdin JSON), e.g. {json_block(example)}')
