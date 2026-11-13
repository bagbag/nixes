// The console reads exactly what the engine prints: engine-contract.ts is the real `protocol show --json`
// (the agents validator regenerates and compares it), so a shape change on either side fails here.
import { describe, expect, test } from 'claude-code/testing'

import { parseBoardConsole, parseRound } from '../hooks/engine'
import { BOARD_CONSOLE_CONTRACT } from './board-console-contract'
import { ENGINE_CONTRACT } from './engine-contract'

describe('engine contract', () => {
  for (const [state, raw] of Object.entries(ENGINE_CONTRACT)) {
    test(`parses the engine's ${state} state with every field read`, () => {
      const parsed = parseRound(raw) as Record<string, unknown>
      for (const key of Object.keys(raw)) expect(Object.keys(parsed), `round field ${key}`).toContain(key)
      const questions = (raw as { questions: readonly Record<string, unknown>[] }).questions
      const parsedQuestions = parsed.questions as Record<string, unknown>[]
      questions.forEach((question, i) => {
        for (const key of Object.keys(question)) expect(Object.keys(parsedQuestions[i] ?? {}), `question field ${key}`).toContain(key)
        expect(parsedQuestions[i]).toMatchObject(question)
      })
    })
  }

  test('the states carry what the console acts on', () => {
    expect(parseRound(ENGINE_CONTRACT.none).round).toBeNull()
    expect(parseRound(ENGINE_CONTRACT.prepass)).toMatchObject({ step: 'prepass', subject: 'Cache design', pending: { command: 'step-back' } })
    expect(parseRound(ENGINE_CONTRACT.check).pending).toEqual({ id: 'p2', command: 'step-back', args: 'goal foundations' })
    expect(parseRound(ENGINE_CONTRACT.ask).batch?.marker).toBe('round:r1:1')
    expect(parseRound(ENGINE_CONTRACT.ask).batch?.notice).toMatch(/^\*\*Cache\*\*\n\nProblem: .*\n\nCases: /)  // the text the console prints between turns
    expect(parseRound(ENGINE_CONTRACT.answered).questions[0]?.answeredAt).toBe('2026-01-01T00:00:00Z')
    expect(parseRound(ENGINE_CONTRACT.closed).next).toEqual({ release: { count: 1 } })
    expect(parseRound(ENGINE_CONTRACT.check).next).toBeNull()
    // the stopped release dropped its record from the default set: no release beside the proposal
    expect(parseRound(ENGINE_CONTRACT.proposed).next).toEqual({
      rounds: [
        { ids: [], idTitles: {}, title: 'Cache questions', summary: 'Which cache store both modules use.', estimate: { questions: 3, unblocks: 8 }, why: 'same module as the context read', fresh: false },
        { ids: ['fx-q3'], idTitles: { 'fx-q3': 'Retry backoff' }, title: 'Queue retry', summary: 'How a failed queue job is retried.', estimate: { questions: 1, unblocks: 5 }, why: 'highest priority left', fresh: true },
      ],
    })
    expect(parseRound(ENGINE_CONTRACT.compactOnly).next).toEqual({ rounds: [] })
    expect(parseRound(ENGINE_CONTRACT.check).questions[0]?.changedBy).toBeNull()
    expect(parseRound(ENGINE_CONTRACT.revised).records.map(one => one.state)).toEqual(['set', 'revised'])
    expect(parseRound(ENGINE_CONTRACT.parked).questions.map(one => one.status)).toEqual(['parked'])  // an away round's parked question
    expect(parseRound(ENGINE_CONTRACT.parked).batch).toBeNull()
    expect(parseRound(ENGINE_CONTRACT.revised).records[1]?.reason).toBe('changed (contained, own): the rationale cited a wrong size')
  })
})

// `board console` change requests, to the spec in build-r24-r25-plan.md Front B (a stub fixture until the board's own output replaces it).
describe('board console contract', () => {
  test('every crs and ratifications field is read, and the counts carry toRatify', () => {
    const board = parseBoardConsole(BOARD_CONSOLE_CONTRACT)
    BOARD_CONSOLE_CONTRACT.crs.forEach((raw, i) => {
      const parsed = board.crs[i] as unknown as Record<string, unknown>
      for (const key of Object.keys(raw)) expect(Object.keys(parsed), `cr field ${key}`).toContain(key)
      expect(parsed).toMatchObject(raw)
    })
    expect(board.ratifications).toEqual(BOARD_CONSOLE_CONTRACT.ratifications)
    expect(board.counts?.toRatify).toEqual({ ready: 1, held: 0, waiting: 0 })
  })

  test('the agent steps design and implement are counted, the queue is a count, and a board is there', () => {
    const board = parseBoardConsole(BOARD_CONSOLE_CONTRACT)
    expect(board.counts).toMatchObject({ toDesign: { ready: 6, held: 1, waiting: 0 }, toImplement: { ready: 90, held: 1, waiting: 1 } })
    expect(board.queued).toBe(92)
    expect(board.waitingOnYou).toBe(5)
    expect(board.prefix).toBe('p')
    expect(board.isMissing).toBe(false)
  })

  test('no board is data: the board says so and the rest reads empty', () => {
    const missing = parseBoardConsole({ noBoard: true, counts: null, forYou: [], items: [], crs: [], queued: 0, ratifications: [], sessions: [], held: [] })
    expect(missing).toMatchObject({ isMissing: true, counts: null, crs: [], queued: 0, items: [], sessions: [] })
  })

  test('a board without the new fields reads as a board with none queued and nothing to design or implement', () => {
    const board = parseBoardConsole({ counts: { toPlan: { ready: 1, held: 0, waiting: 0 } } })
    expect(board).toMatchObject({ isMissing: false, queued: 0 })
    expect(board.counts?.toDesign).toEqual({ ready: 0, held: 0, waiting: 0 })
  })

  test('an unknown check state reads as unchecked, a missing check as nothing run', () => {
    const board = parseBoardConsole({ crs: [{ id: 'x', check: { state: 'weird' } }, { id: 'y' }] })
    expect(board.crs.map(one => one.check.state)).toEqual(['unchecked', 'unchecked'])
    expect(board.crs[1]).toMatchObject({ holder: null, parent: null, children: [], reviewState: null, landBlocked: null, after: null, setupFailed: false, unblocks: 0, unblocksDirect: 0, milestone: null })
  })
})

test('a check without a comparison reads as none ran', () => {
  const check = parseBoardConsole({ crs: [{ id: 'x', check: { state: 'current' } }] }).crs[0]?.check
  expect(check).toMatchObject({ newFailures: null, baseCount: null, tipCount: null })
})

test('the check kind is read; a missing or unknown one is a full check', () => {
  const kinds = parseBoardConsole({ crs: [{ id: 'a', check: { state: 'current', kind: 'targeted', command: 'pnpm test a' } }, { id: 'b', check: { state: 'current', kind: 'none', reason: 'docs' } }, { id: 'c', check: { kind: 'weird' } }, { id: 'd' }] }).crs
  expect(kinds.map(one => one.check.kind)).toEqual(['targeted', 'none', 'full', 'full'])
  expect(kinds[0]?.check.command).toBe('pnpm test a')
  expect(kinds[1]?.check.reason).toBe('docs')
})

test('the priority fields, the answers count and the prefix are read', () => {
  const board = parseBoardConsole({ waitingOnYou: 5, prefix: 'p', crs: [{ id: 'x', priority: 1, ownPriority: 2, raisedBy: { id: 'p-i', isItem: true } }, { id: 'y' }] })
  expect(board).toMatchObject({ waitingOnYou: 5, prefix: 'p' })
  expect(board.crs[0]).toMatchObject({ priority: 1, ownPriority: 2, raisedBy: { id: 'p-i', isItem: true } })
  expect(board.crs[1]?.raisedBy).toBeNull()
  expect(parseBoardConsole({ noBoard: true })).toMatchObject({ waitingOnYou: 0, prefix: null })
})
