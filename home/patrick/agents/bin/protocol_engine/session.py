"""The session registry: session resolves sessions and owns the state dir."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .base import ProtocolError, REGISTRY, _call, env


# Session and registry: session owns the resolution.

def state_root() -> Path:
    """The registry's state dir; session owns its location."""
    call = _call.get()
    if call.state_root is None:
        call.state_root = Path(registry('state-dir').strip())
    return call.state_root


def registry(*args: str) -> str:
    call = _call.get()
    result = subprocess.run(['bash', str(REGISTRY), *args], capture_output=True, text=True, env=call.env, cwd=call.cwd)
    if result.returncode != 0:
        raise ProtocolError((result.stderr or result.stdout).strip() or f'session {args[0]} failed')
    return result.stdout


def resolve_session(flag: str | None) -> tuple[str, dict]:
    """(session id, registry entry): --session, else CODEX_THREAD_ID, else the registered session whose actor
    session derives from the environment."""
    if flag or env().get('CODEX_THREAD_ID'):
        session = flag or env()['CODEX_THREAD_ID']
        entry = json.loads(registry('show', session))
        if not flag and not entry.get('tool'):
            entry['tool'] = 'codex'  # an unregistered Codex thread is still Codex
        return session, entry
    try:
        actor = registry('actor').strip()
    except ProtocolError as error:
        raise ProtocolError(f'no session: pass --session <id> ({error})') from None
    entry = next((json.loads(row) for row in registry('list').splitlines()
                  if row.strip() and json.loads(row).get('actor') == actor.split('/', 1)[0]), None)
    if entry is None:
        raise ProtocolError(f'no registered session for actor {actor}: pass --session <id> or register a role (/role)')
    return entry['session'], entry
