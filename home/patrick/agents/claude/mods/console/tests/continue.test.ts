// /console-continue (r7-q24): the turn-end decision on the person's request, for a round that stalled. It queues the pending
// pass whatever became of its stored run but a run still in hand, reopens the issued batch past the repeat guard, wakes the model
// at Record or a release step, and logs each use with what it did (`nudged`).
import { describe, expect, test } from 'claude-code/testing'

import { BATCH, engineLine, NO_ROUND, notices, roundJson, SESSION, world } from './fixture'
import { continueText, openDialogText } from '../hooks/words'

const start = async ($: any) => $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
const complete = (isAborted = false) => ({ answer: '', durationMs: 1, isAborted, turnId: 't', reason: isAborted ? 'aborted' : 'answer' }) as never
const typed = { origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } } as const
const PENDING = { pending: { id: 'p88', command: 'ground', args: 'assumptions' }, batch: null }
const STATUS = 'round r4 · check 2/3 · next ground'

type W = { calls: { argv: string[]; stdin: string | undefined }[]; commands: { command: string; args: string }[] }
const nudges = (w: W) => w.calls.filter(one => one.argv[3] === 'nudged').map(one => ({ origin: one.argv.slice(4), report: JSON.parse(one.stdin ?? '{}') }))
const grounds = (w: W) => w.commands.filter(one => one.command === 'ground')
const passRecords = (w: W) => w.calls.filter(one => one.argv[3] === 'pass').map(one => JSON.parse(one.stdin ?? '{}'))

async function proceed($: any, clock: { settle: () => Promise<void> }) {
  await $.command.run({ command: 'console-continue', args: '', ...typed })
  await clock.settle()
}

describe('/console-continue', () => {
  test('is registered beside /console-questions', async ($, on) => {
    const { w } = world(on)
    await start($)
    expect(w.registered).toContain('console-continue')
  })

  describe('queues the pending pass with its arguments', () => {
    test('when Esc stopped its stored run', async ($, on) => {
      const { w, clock } = world(on, { round: roundJson(PENDING) })
      await start($)
      await $.turn.complete(complete())
      await $.skill.prompt({ skill: 'ground', text: 'Ground…' } as never)
      await $.turn.complete(complete(true))
      await clock.settle()
      expect(grounds(w)).toHaveLength(1)
      await proceed($, clock)
      expect(grounds(w)).toEqual([{ command: 'ground', args: 'assumptions' }, { command: 'ground', args: 'assumptions' }])
      expect(passRecords(w).at(-1)).toEqual({ command: 'ground', args: 'assumptions', pending: 'p88' })
      expect(nudges(w)).toEqual([{ origin: ['--origin', 'plugin'], report: { pass: 'p88' } }])
    })

    test('when the console asked for its report, and when it noted it stuck', async ($, on) => {
      const { w, clock } = world(on, { round: roundJson(PENDING) })
      await start($)
      await $.turn.complete(complete())
      await $.skill.prompt({ skill: 'ground', text: 'Ground…' } as never)
      await $.turn.complete(complete())  // asked for the report
      await clock.settle()
      await proceed($, clock)
      expect(grounds(w)).toHaveLength(2)
      await $.skill.prompt({ skill: 'ground', text: 'Ground…' } as never)
      await $.turn.complete(complete())  // asked again
      await $.turn.complete(complete())  // noted: the round stopped
      await clock.settle()
      expect(grounds(w)).toHaveLength(2)
      await proceed($, clock)
      expect(grounds(w)).toHaveLength(3)
      expect(nudges(w).map(one => one.report)).toEqual([{ pass: 'p88' }, { pass: 'p88' }])
    })

    test('when no run of it is stored (a lost wake-up)', async ($, on) => {
      const { w, clock } = world(on, { round: roundJson(PENDING) })
      await start($)
      await clock.settle()
      await proceed($, clock)
      expect(grounds(w)).toEqual([{ command: 'ground', args: 'assumptions' }])
      expect(nudges(w).map(one => one.report)).toEqual([{ pass: 'p88' }])
    })

    test('but not while its run is still queued: it says so', async ($, on) => {
      const { w, clock, session } = world(on, { round: roundJson(PENDING) })
      await start($)
      await $.turn.complete(complete())
      await clock.settle()
      await proceed($, clock)
      expect(grounds(w)).toHaveLength(1)
      expect(notices(session).filter(text => text.includes('/ground (p88) is already queued or running'))).toHaveLength(1)
      expect(nudges(w).map(one => one.report)).toEqual([{}])
    })

    test('a started run gets the turn end\'s request for its report, not a second run', async ($, on) => {
      const { w, clock } = world(on, { round: roundJson(PENDING) })
      await start($)
      await $.turn.complete(complete())
      await $.skill.prompt({ skill: 'ground', text: 'Ground…' } as never)
      await clock.settle()
      await proceed($, clock)
      expect(grounds(w)).toHaveLength(1)
      expect(w.prompts.filter(text => text.includes('ended without its report'))).toHaveLength(1)
      expect(nudges(w).map(one => one.report)).toEqual([{}])
    })
  })

  test('reopens the issued batch past the repeat guard, as the person\'s message would', async ($, on) => {
    const { w, clock } = world(on, { round: roundJson({ step: 'ask', batch: { ...BATCH, notice: '' } }) })
    const asked: unknown[] = []
    let isAnswering = false  // the first dialog goes unanswered: the console asks the model to open it
    on('tool.call', { tool: 'AskUserQuestion' }, (_, e) => {
      if (!isAnswering) throw new Error('not drawn')
      asked.push((e as any).metadata?.source)
      return { result: { questions: BATCH.questions, answers: { [BATCH.questions[0]?.question ?? '']: 'flow' } } } as never
    })
    await start($)
    await $.turn.complete(complete())
    await clock.settle()
    expect(w.prompts).toEqual([openDialogText(BATCH.marker)])  // no swap here: the model was asked to open it
    await $.turn.start({ text: openDialogText(BATCH.marker), turnId: 't1' } as never)
    await $.turn.complete(complete())
    await clock.settle()
    expect(w.prompts).toHaveLength(1)  // the repeat guard holds at a plain turn end
    isAnswering = true
    await proceed($, clock)
    expect(asked).toEqual([BATCH.marker])  // the console's own dialog, swapped for the batch, with no model turn
    expect(w.prompts).toEqual([openDialogText(BATCH.marker), engineLine(['flow'])])
    expect(nudges(w).map(one => one.report)).toEqual([{ batch: BATCH.marker }])
  })

  test('at Record with no pending pass, wakes the model with the engine\'s status line', async ($, on) => {
    const { w, clock } = world(on, { round: roundJson({ step: 'record', batch: null }) })
    await start($)
    await clock.settle()
    await proceed($, clock)
    expect(w.prompts).toEqual([continueText(STATUS)])
    expect(w.calls.some(one => one.argv[3] === 'status' && one.argv[4] === '--line')).toBe(true)
    expect(nudges(w).map(one => one.report)).toEqual([{ step: 'record' }])
  })

  test('at a release step with no pending pass, wakes the model too', async ($, on) => {
    const { w, clock } = world(on, { round: roundJson({ protocol: 'release', step: 'owners', check: null, questions: [], batch: null }) })
    await start($)
    await clock.settle()
    await proceed($, clock)
    expect(w.prompts).toEqual([continueText(STATUS)])
    expect(nudges(w).map(one => one.report)).toEqual([{ step: 'owners' }])
  })

  test('a failed status read says so and wakes nobody', async ($, on) => {
    const { w, clock, session } = world(on, { round: roundJson({ step: 'record', batch: null }) })
    w.failVerbs = ['status']
    await start($)
    await clock.settle()
    await proceed($, clock)
    expect(w.prompts).toEqual([])
    expect(notices(session).some(text => text.includes('reading the round\'s status failed'))).toBe(true)
  })

  test('at another step with nothing to start, it says so with the status line and wakes nobody', async ($, on) => {
    const { w, clock, session } = world(on, { round: roundJson({ step: 'stage', batch: null }) })
    await start($)
    await clock.settle()
    await proceed($, clock)
    expect(w.prompts).toEqual([])
    expect(notices(session).some(text => text.includes('nothing to continue at stage') && text.includes(STATUS))).toBe(true)
    expect(nudges(w).map(one => one.report)).toEqual([{}])
  })

  test('with no round open, it says so', async ($, on) => {
    const { w, clock, session } = world(on, { round: NO_ROUND })
    await start($)
    await clock.settle()
    await proceed($, clock)
    expect(w.prompts).toEqual([])
    expect(w.commands).toEqual([])
    expect(notices(session).some(text => text.includes('nothing to continue: no round is open'))).toBe(true)
    expect(nudges(w).map(one => one.report)).toEqual([{}])
  })

  test('outside a round role it says so and logs nothing', async ($, on) => {
    const { w, clock, session } = world(on, { role: { session: SESSION, role: 'agent', actor: 'eef8ae5c', tool: 'claude' }, round: roundJson(PENDING) })
    await start($)
    await clock.settle()
    await proceed($, clock)
    expect(grounds(w)).toEqual([])
    expect(notices(session).some(text => text.includes('nothing to continue: no round is open'))).toBe(true)
    expect(nudges(w)).toEqual([])
  })

  test('a reopened batch\'s text is its output', async ($, on) => {
    const NOTICE = 'Engine name\nProblem: which name.'
    const { clock } = world(on, { round: roundJson({ step: 'ask', batch: { ...BATCH, notice: NOTICE } }) })
    on('tool.call', { tool: 'AskUserQuestion' }, () => ({ deny: 'closed' }) as never)
    await start($)
    await clock.settle()
    expect((await $.command.run({ command: 'console-continue', args: '', ...typed })).text).toBe(`\n${NOTICE}`)
    await clock.settle()
  })

  describe('typed during a turn', () => {
    const during = { text: '/console-continue', origin: { kind: 'composer' }, turnId: 't', wait: false } as never

    test('runs when the turn ends, in place of the plain turn end', async ($, on) => {
      const { w, clock, session } = world(on, { round: roundJson({ ...PENDING }) })
      await start($)
      await $.turn.complete(complete())
      await $.skill.prompt({ skill: 'ground', text: 'Ground…' } as never)
      await $.turn.complete(complete(true))  // Esc stopped the pass: a plain turn end leaves it
      await clock.settle()
      await $.turn.start({ text: 'what now?', turnId: 't' } as never)
      expect((await $.prompt.submit(during)).drop).toBe('/console-continue runs when this turn ends')
      expect(notices(session).filter(text => text.includes('/console-continue runs when this turn ends'))).toHaveLength(1)
      expect(w.prompts).not.toContain('/console-continue')
      await $.turn.complete(complete())
      await clock.settle()
      expect(grounds(w)).toHaveLength(2)
      expect(nudges(w).map(one => one.report)).toEqual([{ pass: 'p88' }])
      await $.turn.complete(complete())  // asked once: the next turn end is a plain one
      await clock.settle()
      expect(nudges(w)).toHaveLength(1)
    })

    test('with the repeat guard holding a batch, the turn\'s end opens the console\'s own dialog', async ($, on) => {
      const { w, clock } = world(on, { round: roundJson({ step: 'ask', batch: { ...BATCH, notice: '' } }) })
      const asked: unknown[] = []
      let isAnswering = false  // the first dialog goes unanswered: the console asks the model to open it, and the guard holds the batch
      on('tool.call', { tool: 'AskUserQuestion' }, (_, e) => {
        if (!isAnswering) throw new Error('not drawn')
        asked.push((e as any).metadata?.source)
        return { deny: 'closed' } as never
      })
      await start($)
      await $.turn.complete(complete())
      await clock.settle()
      await $.turn.start({ text: openDialogText(BATCH.marker), turnId: 't1' } as never)
      isAnswering = true
      await $.prompt.submit({ ...(during as object), turnId: 't1' } as never)
      await $.turn.complete(complete())
      await clock.settle()
      expect(asked).toEqual([BATCH.marker])
      expect(nudges(w).map(one => one.report)).toEqual([{ batch: BATCH.marker }])
    })

    test('a turn Esc ends drops it', async ($, on) => {
      const { w, clock } = world(on, { round: roundJson({ step: 'record', batch: null }) })
      await start($)
      await $.turn.start({ text: 'record', turnId: 't' } as never)
      await $.prompt.submit(during)
      await $.turn.complete(complete(true))
      await $.turn.complete(complete())
      await clock.settle()
      expect(w.prompts).toEqual([])
      expect(nudges(w)).toEqual([])
    })
  })

  test('the model\'s tool cannot log a continue', async ($, on) => {
    const { w } = world(on)
    await start($)
    const ran = await $.tool.call({ tool: 'mcp__console__protocol', args: ['nudged'], stdin: '{}' } as never)
    expect(String(ran.result)).toMatch(/^Refused/)
    expect(nudges(w)).toEqual([])
  })
})
