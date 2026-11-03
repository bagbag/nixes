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
    expect(parseRound(ENGINE_CONTRACT.check).pending).toEqual({ id: 'p1', command: 'step-back', args: 'goal foundations', reminder: null })
    // the cycle told step-back already: the next pending one carries the engine's cut of the installed SKILL.md
    expect(parseRound(ENGINE_CONTRACT.reminder).pending?.reminder).toMatch(/^Reminder for \/step-back\..*Judge greenfield/s)
    expect(parseRound(ENGINE_CONTRACT.ask).batch?.marker).toBe('round:r1:1')
    expect(parseRound(ENGINE_CONTRACT.answered).questions[0]?.answeredAt).toBe('2026-01-01T00:00:00Z')
    expect(parseRound(ENGINE_CONTRACT.closed).next).toEqual({ release: { count: 1 } })
    expect(parseRound(ENGINE_CONTRACT.check).next).toBeNull()
    // the stopped release dropped its record from the default set: no release beside the proposal
    expect(parseRound(ENGINE_CONTRACT.proposed).next).toEqual({
      rounds: [
        { ids: ['fx-q1', 'fx-q2'], title: 'Cache questions', why: 'same module as the context read', fresh: false },
        { ids: ['fx-q3'], title: 'Queue retry', why: 'highest priority left', fresh: true },
      ],
      compact: { keep: 'the cache decisions' },
    })
    expect(parseRound(ENGINE_CONTRACT.compactOnly).next).toEqual({ compact: { keep: 'all decisions of this session' } })
    expect(parseRound(ENGINE_CONTRACT.check).questions[0]?.changedBy).toBeNull()
    expect(parseRound(ENGINE_CONTRACT.revised).records.map(one => one.state)).toEqual(['set', 'revised'])
    expect(parseRound(ENGINE_CONTRACT.revised).records[1]?.reason).toBe('changed (contained, own): the rationale cited a wrong size')
  })
})
