"""Steps, protocols, the call context, the protocol registry and question accessors."""
from __future__ import annotations

from .base import ProtocolError
from .store import Store, next_id
from .boards import Board


# Engine: a protocol is a definition of steps; each step has an entry hook (side effects, may redirect), a
# validator taking the model's report, and the instructions for the model.

class Step:
    def __init__(self, name: str, text, accept=None, enter=None):
        self.name, self.text, self.accept, self.enter = name, text, accept, enter


class Protocol:
    def __init__(self, name: str, steps: list[Step], after_ask: str):
        """`after_ask`: the step Ask hands over to once no question waits (the ask machinery is shared)."""
        self.name, self.steps, self.after_ask = name, {step.name: step for step in steps}, after_ask


class Context:
    def __init__(self, store: Store, state: dict, entry: dict, board: Board | None):
        self.store, self.state, self.entry, self.board = store, state, entry, board
        self.codex = entry.get('tool') == 'codex'
        self.away = entry.get('role') == 'autopilot'  # the registered role says whether the person can answer (r28-q126)
        self.complete = False  # a read the model asked for (`show`): says everything, records nothing as told
        self.formats: dict[str, str] = {}  # report formats the step text offered, by kind (a refused report reprints them)
        self.messages: list[str] = []  # said once, ahead of the step's instructions
        self.applied, self.added = [], []  # this call's updates: changed ids, new ids

    @property
    def round(self) -> dict:
        return self.state['round']

    def go(self, name: str) -> None:
        """Enters a step, following redirects of entry hooks."""
        for _ in range(20):
            self.round['step'] = name
            step = PROTOCOLS[self.round['protocol']].steps[name]
            redirect = step.enter(self) if step.enter else None
            if not redirect or redirect == name:
                return
            name = redirect
        raise ProtocolError(f'step loop at {name}')

    def set_pending(self, command: str | None, args: str = '') -> None:
        self.round['pending'] = {'id': next_id(self.state, 'pending', 'p'), 'command': command, 'args': args} \
            if command else None

    def log(self, event: str, **data) -> None:
        self.store.log({'round': self.round['id'] if self.round else None, 'event': event, **data})


def fail(message: str):
    raise ProtocolError(message)


def questions(ctx: Context, *statuses: str) -> list[dict]:
    return [q for q in ctx.round['questions'] if not statuses or q['status'] in statuses]


def by_id(ctx: Context, qid: str) -> dict:
    found = next((q for q in ctx.round['questions'] if q['id'] == qid), None)
    return found or fail(f'unknown question {qid}')


def answered(ctx: Context, qid: str) -> bool:
    return qid in ctx.state['answers']


def premise_status(ctx: Context, q: dict) -> str:
    return 'held' if any(not answered(ctx, other) for other in q.get('waitsOn') or []) else 'draft'


def unresolved(ctx: Context) -> list[tuple[dict, dict]]:
    return [(q, hit) for q in ctx.round['questions'] for hit in q['overlaps'] if hit['outcome'] is None]


PROTOCOLS: dict[str, Protocol] = {}  # name -> protocol; round.py and release.py register theirs
