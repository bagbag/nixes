// Stale console actions (r3-q9, r3-q10): the host queues what the console sends and cannot recall it, so each action is
// re-checked against the round where it is delivered, and a stale one is dropped and reported.
import { describe, expect, test } from 'claude-code/testing'

import { BATCH, notices, roundJson, world } from './fixture'
import { missingReportText, openDialogText, STALE_PASS_TEXT } from '../hooks/words'

const start = async ($: any) => $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
const complete = (extra: Record<string, unknown> = {}) => ({ answer: '', durationMs: 1, isAborted: false, turnId: 't', reason: 'answer', ...extra }) as never
const plugin = { kind: 'plugin', name: 'console' } as const
const presentation = { isFullscreen: true, columns: 160 }
const pending = (id: string, args = '', command = 'ground') => roundJson({ pending: { id, command, args } })
const asking = (marker = BATCH.marker) => roundJson({ step: 'ask', batch: { ...BATCH, marker, notice: '' } })
const drops = (w: { calls: { argv: string[]; stdin: string | undefined }[] }) =>
  w.calls.filter(one => one.argv[3] === 'dropped').map(one => ({ origin: one.argv.slice(4), report: JSON.parse(one.stdin ?? '{}') }))

describe('a pass run the console queued', () => {
  const expand = async ($: any) => ($.skill.prompt({ skill: 'ground', text: 'Ground, in full.' } as never) as Promise<{ text: string }>)
  const queued = async ($: any, clock: { settle: () => Promise<void> }) => {
    await start($)
    await $.turn.complete(complete())
    await clock.settle()
  }

  test('expands in full while its pass is the pending one', async ($, on) => {
    const { w, clock } = world(on, { round: pending('p7', 'assumptions') })
    await queued($, clock)
    expect((await expand($)).text).toBe('Ground, in full.')
    expect(drops(w)).toEqual([])
  })

  test('is rewritten to a no-op and reported once its pass is no longer pending', async ($, on) => {
    const { w, clock } = world(on, { round: pending('p7') })
    await queued($, clock)
    w.round = pending('p8')
    expect((await expand($)).text).toBe(STALE_PASS_TEXT)
    expect(drops(w)).toEqual([{ origin: ['--origin', 'plugin'], report: { kind: 'pass', id: 'p7' } }])
  })

  test('is rewritten when the pending pass carries other arguments', async ($, on) => {
    const { w, clock } = world(on, { round: pending('p7', 'assumptions') })
    await queued($, clock)
    w.round = pending('p7', 'probe')
    expect((await expand($)).text).toBe(STALE_PASS_TEXT)
    expect(drops(w)).toHaveLength(1)
  })

  test('starts its pass only if that pass is the pending one: the stale run leaves it unstarted', async ($, on) => {
    const { w, clock } = world(on, { round: pending('p7') })
    await queued($, clock)
    w.round = pending('p8')
    await expand($)  // an older run of the command arrives
    w.round = pending('p7')
    await $.turn.complete(complete())
    await clock.settle()
    expect(w.prompts.filter(text => text.includes('ended without its report'))).toEqual([])
  })

  test("a run the person typed for the new pending pass is not rewritten", async ($, on) => {
    const { w, clock } = world(on, { round: pending('p7') })
    await queued($, clock)
    w.round = pending('p8')
    await $.command.run({ command: 'ground', args: '', origin: { kind: 'composer' }, presentation })
    expect((await expand($)).text).toBe('Ground, in full.')
    expect(drops(w)).toEqual([])
  })
})

describe('a plain-text prompt the console queued', () => {
  const reportedMeanwhile = async ($: any, on: any, flip: (verb: string, shows: number) => boolean) => {
    const { w, clock, session } = world(on, { round: pending('p7') })
    await start($)
    await $.turn.complete(complete())
    await $.command.run({ command: 'ground', args: '', origin: plugin, presentation })
    await $.skill.prompt({ skill: 'ground', text: 'Ground…' } as never)
    let shows = -1  // counts the shows after the pending read
    w.onVerb = verb => { if (verb === 'show' && shows >= 0) shows += 1; if (verb === 'pending') shows = 0; if (shows >= 0 && flip(verb, shows)) w.round = roundJson() }  // the report lands while the request waits
    await $.turn.complete(complete())
    await clock.settle()
    expect(w.prompts.filter(text => text === missingReportText('ground', 'p7'))).toEqual([])
    expect(drops(w)).toEqual([{ origin: ['--origin', 'plugin'], report: { kind: 'pass', id: 'p7' } }])
    expect(notices(session)).toEqual([])
    expect(w.toasts).toEqual([])
  }

  test('the missing-report request is dropped before it is sent when its pass reported already', async ($, on) => {
    await reportedMeanwhile($, on, verb => verb === 'pending')
  })

  test('and where the host delivers it, when its pass reported while it waited', async ($, on) => {
    await reportedMeanwhile($, on, (verb, shows) => verb === 'show' && shows === 1)  // the send-time check still finds it pending
  })

  test('the open-the-dialog message is dropped when its batch is no longer out', async ($, on) => {
    const marker = `${BATCH.marker} `  // the kit's stand-in for a run the console's hook never answered: the model is asked to open it
    const { w, clock, session } = world(on, { round: asking(marker) })
    await start($)
    await clock.settle()
    let isArmed = false
    w.onVerb = verb => {
      if (verb === 'show' && isArmed) w.round = roundJson({ batch: null })  // the batch is read once, then it is gone
      isArmed = isArmed || verb === 'pending'
    }
    await $.turn.complete(complete())
    await clock.settle()
    expect(w.prompts.filter(text => text === openDialogText(marker))).toEqual([])
    expect(drops(w)).toEqual([{ origin: ['--origin', 'plugin'], report: { kind: 'batch', marker } }])
    expect(notices(session).filter(text => text.includes('failed'))).toEqual([])
  })

  test("the person's own message is never dropped, whatever it says", async ($, on) => {
    const { w, clock } = world(on, { round: roundJson() })
    await start($)
    await clock.settle()
    const text = openDialogText('round:r4:1')
    expect((await $.prompt.submit({ text, origin: { kind: 'composer' }, wait: false } as never)).drop).toBeUndefined()
    expect(w.prompts).toEqual([text])
    expect(drops(w)).toEqual([])
  })
})

describe('/console-questions', () => {
  const answered = { result: { questions: BATCH.questions, answers: { 'Which engine name?': 'protocol' } } }

  test('does not open a batch whose dialog is open in this console', async ($, on) => {
    const { w, clock } = world(on, { round: asking() })
    let release: () => void = () => undefined
    const held = new Promise<void>(resolve => { release = resolve })
    let opened = 0
    on('tool.call', { tool: 'AskUserQuestion' }, async () => { opened += 1; await held; return answered as never })
    await start($)
    await $.turn.complete(complete())
    await clock.settle()
    await $.prompt.submit({ text: 'while it is open', origin: { kind: 'composer' }, wait: false } as never)  // clears the repeat guard
    await $.turn.complete(complete())
    await clock.settle()
    expect(opened).toBe(1)
    expect(drops(w)).toEqual([{ origin: ['--origin', 'plugin'], report: { kind: 'batch', marker: BATCH.marker } }])
    release()
    await clock.settle()
  })
})

describe('a dialog outcome for a batch that is no longer out', () => {
  const answered = { result: { questions: BATCH.questions, answers: { 'Which engine name?': 'protocol' } } }
  const dialog = { tool: 'AskUserQuestion', questions: BATCH.questions, metadata: { source: BATCH.marker } } as never

  test('is dropped without a record or a notice', async ($, on) => {
    const { w, session } = world(on)
    on('tool.call', { tool: 'AskUserQuestion' }, () => { w.round = roundJson({ batch: null }); return answered as never })
    await start($)
    await $.tool.call(dialog)
    expect(w.verbs().filter(verb => verb.startsWith('answer') || verb.startsWith('decline'))).toEqual([])
    expect(drops(w)).toEqual([{ origin: ['--origin', 'plugin'], report: { kind: 'batch', marker: BATCH.marker } }])
    expect(notices(session)).toEqual([])
  })

  test('a late decline is dropped the same way', async ($, on) => {
    const { w, session } = world(on)
    on('tool.call', { tool: 'AskUserQuestion' }, () => { w.round = roundJson({ batch: null }); return { isError: true, result: 'declined', text: 'declined' } as never })
    await start($)
    await $.tool.call(dialog)
    expect(w.verbs().filter(verb => verb.startsWith('decline'))).toEqual([])
    expect(drops(w)).toHaveLength(1)
    expect(notices(session)).toEqual([])
  })

  test("the console's own dialog drops it too and does not wake the model", async ($, on) => {
    const { w, clock, session } = world(on, { round: asking() })
    on('tool.call', { tool: 'AskUserQuestion' }, () => { w.round = roundJson({ batch: null }); return answered as never })
    await start($)
    await $.turn.complete(complete())
    await clock.settle()
    expect(w.verbs().filter(verb => verb.startsWith('answer'))).toEqual([])
    expect(w.prompts).toEqual([])
    expect(drops(w)).toHaveLength(1)
    expect(notices(session)).toEqual([])
  })

  test('a batch still out is recorded as before', async ($, on) => {
    const { w } = world(on)
    on('tool.call', { tool: 'AskUserQuestion' }, () => answered as never)
    await start($)
    await $.tool.call(dialog)
    expect(w.verbs()).toContain('answer --origin dialog')
    expect(drops(w)).toEqual([])
  })
})
