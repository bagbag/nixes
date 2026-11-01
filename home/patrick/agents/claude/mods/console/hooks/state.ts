// The console's $.state values (contract: types/index.d.ts), owned here: the engine's scan reads
// a state reference only from a literal const in the file that uses it, so the other modules use
// these functions. The engine's own state stays authoritative; `round` and `board` are the last
// reads. Change a shape tag when its value's fields change.
import { atom, read, update } from 'claude-code'
import type { EngineInterface } from 'claude-code'

import type { ConsoleBoard, ConsoleLenses, ConsoleOpened, ConsolePassRun, ConsoleQueued, ConsoleRefresh, ConsoleRole, ConsoleRound, ConsoleSection } from '../types'

type $ = EngineInterface

const roleState = atom({ plugin: 'console', key: 'role' } as const, null, { shape: 'role-1' })
const drawnState = atom({ plugin: 'console', key: 'isDrawn' } as const, false)
const roundState = atom({ plugin: 'console', key: 'round' } as const, null, { shape: 'round-6' })
const roundErrorState = atom({ plugin: 'console', key: 'roundError' } as const, null)
const boardState = atom({ plugin: 'console', key: 'board' } as const, null, { shape: 'board-4' })
const passState = atom({ plugin: 'console', key: 'pass' } as const, null, { shape: 'pass-2' })
const queuedState = atom({ plugin: 'console', key: 'queued' } as const, [], { shape: 'queued-1' })
const gateState = atom({ plugin: 'console', key: 'gate' } as const, [], { shape: 'gate-1' })
const lensState = atom({ plugin: 'console', key: 'lenses' } as const, { 'step-back': [], ground: [], focus: '' } as ConsoleLenses, { shape: 'lenses-1' })
const refreshState = atom({ plugin: 'console', key: 'refresh' } as const, { since: null, again: false } as ConsoleRefresh, { shape: 'refresh-1' })
const dismissedState = atom({ plugin: 'console', key: 'isPaneDismissed' } as const, false)
const expandedState = atom({ plugin: 'console', key: 'expanded' } as const, [] as ConsoleSection[], { shape: 'expanded-1' })

const openedState = atom({ plugin: 'console', key: 'opened' } as const, null, { shape: 'opened-2' })

const GATE_KEYS_KEPT = 200

export async function getRole($: $): Promise<ConsoleRole | null> { return read($, roleState) }
export async function setRole($: $, value: ConsoleRole | null): Promise<void> { await update($, roleState, () => value) }

export async function getDrawn($: $): Promise<boolean> { return read($, drawnState) }
export async function setDrawn($: $, value: boolean): Promise<void> { await update($, drawnState, () => value) }

export async function getRound($: $): Promise<ConsoleRound | null> { return read($, roundState) }
export async function setRound($: $, value: ConsoleRound | null): Promise<void> { await update($, roundState, () => value) }

export async function getRoundError($: $): Promise<string | null> { return read($, roundErrorState) }
export async function setRoundError($: $, value: string | null): Promise<void> { await update($, roundErrorState, () => value) }

export async function getBoard($: $): Promise<ConsoleBoard | null> { return read($, boardState) }
export async function setBoard($: $, value: ConsoleBoard | null): Promise<void> { await update($, boardState, () => value) }

export async function getPass($: $): Promise<ConsolePassRun | null> { return read($, passState) }
export async function setPass($: $, value: ConsolePassRun | null): Promise<void> { await update($, passState, () => value) }

export async function updateQueued($: $, change: (queued: ConsoleQueued) => ConsoleQueued): Promise<void> { await update($, queuedState, change) }

export async function getGate($: $): Promise<string[]> { return read($, gateState) }
export async function addGate($: $, key: string): Promise<void> { await update($, gateState, keys => [...keys, key].slice(-GATE_KEYS_KEPT)) }

export async function getLenses($: $): Promise<ConsoleLenses> { return read($, lensState) }
export async function updateLenses($: $, change: (lenses: ConsoleLenses) => ConsoleLenses): Promise<void> { await update($, lensState, change) }

export async function getExpanded($: $): Promise<ConsoleSection[]> { return read($, expandedState) }
export async function toggleExpanded($: $, section: ConsoleSection): Promise<void> {
  await update($, expandedState, open => open.includes(section) ? open.filter(one => one !== section) : [...open, section])
}

export async function getOpened($: $): Promise<ConsoleOpened | null> { return read($, openedState) }
export async function updateOpened($: $, change: (opened: ConsoleOpened | null) => ConsoleOpened | null): Promise<void> { await update($, openedState, change) }

/** Single flight for refreshAll: true when this call runs; otherwise the running one runs once more. */
export async function claimRefresh($: $, now: number, staleMs: number): Promise<boolean> {
  let isClaimed = false
  await update($, refreshState, current => {
    isClaimed = current.since === null || now - current.since > staleMs
    return isClaimed ? { since: now, again: false } : { ...current, again: true }
  })
  return isClaimed
}

export async function takeRefreshAgain($: $): Promise<boolean> {
  let isAgain = false
  await update($, refreshState, current => {
    isAgain = current.again
    return { ...current, again: false }
  })
  return isAgain
}

export async function releaseRefresh($: $): Promise<void> { await update($, refreshState, () => ({ since: null, again: false })) }

/** The person closed the pane: no unasked reopen until they open it again with /console. */
export async function getPaneDismissed($: $): Promise<boolean> { return read($, dismissedState) }
export async function setPaneDismissed($: $, value: boolean): Promise<void> { await update($, dismissedState, () => value) }
