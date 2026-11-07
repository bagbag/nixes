"""The per-session state file and its history."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import tempfile

from .base import ProtocolError, VERSION, utcnow
from .session import state_root


# State: one JSON file per session, written atomically under a lock; history appends to its own file.

class Store:
    def __init__(self, session: str):
        if not re.fullmatch(r'[A-Za-z0-9._-]{8,}', session):
            raise ProtocolError(f"invalid session id '{session}'")
        self.dir = state_root() / f'{session}.protocol'
        self.session = session
        self.pending: list[dict] = []
        self.written: list[dict] = []  # this call's events flushed already: the headline still names them

    @contextlib.contextmanager
    def locked(self, write: bool):
        if write:
            self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        elif not self.dir.is_dir():
            yield
            return
        with open(self.dir / '.lock', 'a+') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
            yield

    def load(self) -> dict:
        try:
            state = json.loads((self.dir / 'state.json').read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {'version': VERSION, 'session': self.session, 'seq': {}, 'round': None,
                    'answers': {}, 'counts': None}
        except ValueError as error:
            raise ProtocolError(f'unreadable protocol state {self.dir / "state.json"}: {error}') from None
        if state.get('version') != VERSION:
            raise ProtocolError(f"protocol state version {state.get('version')} is not {VERSION}: {self.dir}")
        return state

    def save(self, state: dict) -> None:
        handle, temporary = tempfile.mkstemp(dir=self.dir, prefix='.state.')
        with os.fdopen(handle, 'w', encoding='utf-8') as out:
            json.dump(state, out, indent=1, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, self.dir / 'state.json')

    def log(self, event: dict) -> None:
        """Queues a history event; `flush` writes the queue once the state it describes is saved, so a failed call
        leaves no event behind (refusals are written directly)."""
        self.pending.append({'at': utcnow(), 'session': self.session, **event})

    def flush(self) -> None:
        if self.pending:
            with open(self.dir / 'history.jsonl', 'a', encoding='utf-8') as out:
                out.writelines(json.dumps(event, ensure_ascii=False) + '\n' for event in self.pending)
            self.written += self.pending
            self.pending = []


def next_id(state: dict, kind: str, prefix: str) -> str:
    state['seq'][kind] = state['seq'].get(kind, 0) + 1
    return f'{prefix}{state["seq"][kind]}'
