// The console reads exactly what the engine prints: engine-contract.ts is the real `protocol show --json`
// (the agents validator regenerates and compares it), so a shape change on either side fails here.
import { describe, expect, test } from 'claude-code/testing'

import { parseRound } from '../hooks/engine'
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
    expect(parseRound(ENGINE_CONTRACT.check).pending).toEqual({ id: 'p1', command: 'step-back', args: 'goal foundations' })
    expect(parseRound(ENGINE_CONTRACT.ask).batch?.marker).toBe('round:r1:1')
    expect(parseRound(ENGINE_CONTRACT.answered).questions[0]?.answeredAt).toBe('2026-01-01T00:00:00Z')
    expect(parseRound(ENGINE_CONTRACT.closed).next).toEqual({ release: { round: 'r2', count: 1 } })
    expect(parseRound(ENGINE_CONTRACT.check).next).toBeNull()
    expect(parseRound(ENGINE_CONTRACT.check).questions[0]?.changedBy).toBeNull()
  })
})
