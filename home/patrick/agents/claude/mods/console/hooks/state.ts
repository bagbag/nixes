// The console's $.state values (contract: types/index.d.ts), owned here: the engine's scan reads
// a state reference only from a literal const in the file that uses it, so the other modules use
// these functions. The engine's own state stays authoritative; `round` and `board` are the last
// reads. Change a shape tag when its value's fields change.
import { atom, read, update } from 'claude-code'
import type { EngineInterface } from 'claude-code'

import type { ConsoleBoard, ConsoleLenses, ConsoleReviewing, ConsoleOpened, ConsolePassRun, ConsolePersonOrigin, ConsolePlaced, ConsoleQueued, ConsoleRefresh, ConsoleRole, ConsoleRound, ConsoleSection, ConsoleStart, ConsoleDeferred } from '../types'

import { isRoundOpen } from './engine'

type $ = EngineInterface

const roleState = atom({ plugin: 'console', key: 'role' } as const, null, { shape: 'role-1' })
const drawnState = atom({ plugin: 'console', key: 'isDrawn' } as const, false)
const roundState = atom({ plugin: 'console', key: 'round' } as const, null, { shape: 'round-11' })
const roundErrorState = atom({ plugin: 'console', key: 'roundError' } as const, null)
const printedState = atom({ plugin: 'console', key: 'printed' } as const, null)
const askSentState = atom({ plugin: 'console', key: 'askSent' } as const, null)
const boardState = atom({ plugin: 'console', key: 'board' } as const, null, { shape: 'board-8' })
const reviewingState = atom({ plugin: 'console', key: 'reviewing' } as const, null, { shape: 'reviewing-2' })
const passState = atom({ plugin: 'console', key: 'pass' } as const, null, { shape: 'pass-5' })
const queuedState = atom({ plugin: 'console', key: 'queued' } as const, [], { shape: 'queued-2' })
const gateState = atom({ plugin: 'console', key: 'gate' } as const, [], { shape: 'gate-1' })
const lensState = atom({ plugin: 'console', key: 'lenses' } as const, { 'step-back': [], ground: [], focus: '' } as ConsoleLenses, { shape: 'lenses-1' })
const refreshState = atom({ plugin: 'console', key: 'refresh' } as const, { since: null, again: false } as ConsoleRefresh, { shape: 'refresh-1' })
const dismissedState = atom({ plugin: 'console', key: 'isPaneDismissed' } as const, false)
const turnRunningState = atom({ plugin: 'console', key: 'isTurnRunning' } as const, false)
const continueAskedState = atom({ plugin: 'console', key: 'isContinueAsked' } as const, false)
const expandedState = atom({ plugin: 'console', key: 'expanded' } as const, [] as ConsoleSection[], { shape: 'expanded-1' })

const openedState = atom({ plugin: 'console', key: 'opened' } as const, null, { shape: 'opened-4' })
const startState = atom({ plugin: 'console', key: 'start' } as const, null, { shape: 'start-2' })
const deferredState = atom({ plugin: 'console', key: 'deferred' } as const, [] as ConsoleDeferred[], { shape: 'deferred-1' })

const personOriginState = atom({ plugin: 'console', key: 'personOrigin' } as const, null as ConsolePersonOrigin | null)
const placedState = atom({ plugin: 'console', key: 'placed' } as const, [] as ConsolePlaced[], { shape: 'placed-1' })

const GATE_KEYS_KEPT = 200
const PLACED_KEPT = 20

export async function getRole($: $): Promise<ConsoleRole | null> { return read($, roleState) }
export async function setRole($: $, value: ConsoleRole | null): Promise<void> { await update($, roleState, () => value) }

/** Where the person's latest message came from; null before any this session. */
export async function getPersonOrigin($: $): Promise<ConsolePersonOrigin | null> { return read($, personOriginState) }
export async function setPersonOrigin($: $, value: ConsolePersonOrigin): Promise<void> { await update($, personOriginState, () => value) }

/** The placed question rows' text, newest last: the `Placed` render hook draws a row from here, not from the round, which moves on. */
export async function getPlaced($: $): Promise<ConsolePlaced[]> { return read($, placedState) }
export async function addPlaced($: $, row: ConsolePlaced): Promise<void> {
  await update($, placedState, rows => [...rows.filter(one => one.id !== row.id), row].slice(-PLACED_KEPT))
}

export async function getDrawn($: $): Promise<boolean> { return read($, drawnState) }
export async function setDrawn($: $, value: boolean): Promise<void> { await update($, drawnState, () => value) }

export async function getRound($: $): Promise<ConsoleRound | null> { return read($, roundState) }
export async function setRound($: $, value: ConsoleRound | null): Promise<void> {
  await update($, roundState, () => value)
  if (isRoundOpen(value)) await setStart($, null)  // a round started: the stored start is moot
}

export async function getRoundError($: $): Promise<string | null> { return read($, roundErrorState) }
export async function setRoundError($: $, value: string | null): Promise<void> { await update($, roundErrorState, () => value) }

/** The batch marker whose question text the console last printed; the dialog gate reads it. */
export async function getPrinted($: $): Promise<string | null> { return read($, printedState) }
export async function setPrinted($: $, value: string | null): Promise<void> { await update($, printedState, () => value) }

/** The batch marker the console last sent the open-the-dialog message for; a message of the person clears it. */
export async function getAskSent($: $): Promise<string | null> { return read($, askSentState) }
export async function setAskSent($: $, value: string | null): Promise<void> { await update($, askSentState, () => value) }

export async function getBoard($: $): Promise<ConsoleBoard | null> { return read($, boardState) }
export async function setBoard($: $, value: ConsoleBoard | null): Promise<void> { await update($, boardState, () => value) }

/** What the review tree holds, as the person last opened it. */
export async function getReviewing($: $): Promise<ConsoleReviewing | null> { return read($, reviewingState) }
export async function setReviewing($: $, value: ConsoleReviewing | null): Promise<void> { await update($, reviewingState, () => value) }

export async function getPass($: $): Promise<ConsolePassRun | null> { return read($, passState) }
export async function setPass($: $, value: ConsolePassRun | null): Promise<void> { await update($, passState, () => value) }

export async function getQueued($: $): Promise<ConsoleQueued> { return read($, queuedState) }
export async function updateQueued($: $, change: (queued: ConsoleQueued) => ConsoleQueued): Promise<void> { await update($, queuedState, change) }

export async function getGate($: $): Promise<string[]> { return read($, gateState) }
export async function addGate($: $, key: string): Promise<void> { await update($, gateState, keys => [...keys, key].slice(-GATE_KEYS_KEPT)) }

export async function getLenses($: $): Promise<ConsoleLenses> { return read($, lensState) }
export async function updateLenses($: $, change: (lenses: ConsoleLenses) => ConsoleLenses): Promise<void> { await update($, lensState, change) }

export async function getExpanded($: $): Promise<ConsoleSection[]> { return read($, expandedState) }
export async function toggleExpanded($: $, section: ConsoleSection): Promise<void> {
  await update($, expandedState, open => open.includes(section) ? open.filter(one => one !== section) : [...open, section])
}

/** The start message waiting for a compaction (the suggestion's Start with compact); null when none. */
export async function getStart($: $): Promise<ConsoleStart | null> { return read($, startState) }
export async function setStart($: $, value: ConsoleStart | null): Promise<void> { await update($, startState, () => value) }

/** Built-in commands the person sent during the running turn; taking them empties the list. */
export async function deferCommand($: $, command: ConsoleDeferred): Promise<void> { await update($, deferredState, all => [...all, command]) }
export async function takeDeferred($: $): Promise<ConsoleDeferred[]> {
  const all = await read($, deferredState)
  if (all.length > 0) await update($, deferredState, () => [])
  return all
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

/** A main-agent turn runs: set at its start, cleared at its end (aborted included); the Continue press reads it. */
export async function getTurnRunning($: $): Promise<boolean> { return read($, turnRunningState) }
export async function setTurnRunning($: $, value: boolean): Promise<void> { await update($, turnRunningState, () => value) }

/** A /console-continue asked for during a turn, by a press or typed: the turn's end runs it; taking it clears it. */
export async function setContinueAsked($: $, value: boolean): Promise<void> { await update($, continueAskedState, () => value) }
export async function takeContinueAsked($: $): Promise<boolean> {
  const isAsked = await read($, continueAskedState)
  if (isAsked) await update($, continueAskedState, () => false)
  return isAsked
}
