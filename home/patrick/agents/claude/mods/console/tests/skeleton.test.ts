// Walking skeleton: idle rules, the protocol tool, the dialog gate, answer capture,
// machine-run passes, pass observation and recovery.
import { describe, expect, test } from 'claude-code/testing'

import { BATCH, engineLine, NO_ROUND, notes, notices, PROTOCOL, roundJson, SESSION, world } from './fixture'
import { openDialogText } from '../hooks/words'

const start = async ($: any) => $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })

describe('idle', () => {
  test('without a registered role the console registers no tool and runs nothing', async ($, on) => {
    const { w, clock } = world(on, { role: null })
    await start($)
    await clock.settle()
    await $.turn.complete({ answer: 'hi', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' })
    expect(w.tools).toEqual([])
    expect(w.calls.filter(one => one.argv[0] === PROTOCOL)).toEqual([])
  })

  test('without a drawing surface the console stays idle', async ($, on) => {
    const { w, clock } = world(on, { surfaces: [] })
    await start($)
    await clock.settle()
    expect(w.tools).toEqual([])
    expect(w.opened).toEqual([])
  })

  test('an agent role gets the board but no round features', async ($, on) => {
    const { w, clock } = world(on, { role: { session: SESSION, role: 'agent', actor: 'eef8ae5c', tool: 'claude' } })
    await start($)
    await clock.settle()
    expect(w.tools).toEqual([])
    expect(w.opened).toEqual([])
    expect(w.calls.some(one => one.argv[1] === 'console')).toBe(true)
    expect(w.verbs()).toEqual([])
  })

  test('an autopilot role gets the round features too (r28-q127)', async ($, on) => {
    const { w, clock } = world(on, { role: { session: SESSION, role: 'autopilot', actor: 'aut0cafe', tool: 'claude' } })
    await start($)
    await clock.settle()
    expect(w.tools).toEqual([{ name: 'protocol', isDeferred: false }])
    expect(w.opened).toEqual(['console'])
  })

  test('the idle message names the three round roles', async ($, on) => {
    world(on, { role: { session: SESSION, role: 'agent', actor: 'eef8ae5c', tool: 'claude' } })
    await start($)
    const idle = await $.tool.call({ tool: 'mcp__console__protocol', args: ['show'] } as never)
    expect(String(idle.result)).toContain('no lead, solo or autopilot role')
  })

  test('a lead registers the protocol tool undeferred and opens the pane unasked', async ($, on) => {
    const { w, clock } = world(on)
    await start($)
    await clock.settle()
    expect(w.tools).toEqual([{ name: 'protocol', isDeferred: false }])
    expect(w.opened).toEqual(['console'])
  })
})

describe('tool', () => {
  test('stamps --session and --origin model, passes stdin', async ($, on) => {
    const { w } = world(on)
    await start($)
    const ran = await $.tool.call({ tool: 'mcp__console__protocol', args: ['step'], stdin: '{"q2":"ok"}' } as never)
    const call = w.calls.find(one => one.argv[3] === 'step')
    expect(call?.argv).toEqual([PROTOCOL, '--session', SESSION, 'step', '--origin', 'model'])
    expect(call?.stdin).toBe('{"q2":"ok"}')
    expect(String(ran.result)).toContain('"round":"r4"')
  })

  test('answer is the chat route: --origin chat', async ($, on) => {
    const { w } = world(on)
    await start($)
    await $.tool.call({ tool: 'mcp__console__protocol', args: ['answer'], stdin: '{"question":"q2","answer":"flow","quote":"use flow"}' } as never)
    expect(w.calls.find(one => one.argv[3] === 'answer')?.argv.slice(3)).toEqual(['answer', '--origin', 'chat'])
  })

  test('refuses a caller origin, session, and the verbs the console relays', async ($, on) => {
    const { w } = world(on)
    await start($)
    for (const args of [['answer', '--origin', 'dialog'], ['answer', '--orig', 'dialog'], ['show', '--o=dialog'], ['step', '--session=x'], ['step', '--sess', 'x'], ['decline'], ['say'], ['pass']]) {
      const ran = await $.tool.call({ tool: 'mcp__console__protocol', args } as never)
      expect(String(ran.result)).toMatch(/^Refused/)
    }
    expect(w.verbs().filter(verb => !verb.startsWith('show'))).toEqual([])
  })

  test('relays a non-zero exit with stderr', async ($, on) => {
    const { w } = world(on)
    await start($)
    w.protocolExit = 2
    const ran = await $.tool.call({ tool: 'mcp__console__protocol', args: ['step'] } as never)
    expect(String(ran.result)).toContain('protocol exited 2')
    expect(String(ran.result)).toContain('engine down')
  })
})

describe('dialog gate and capture', () => {
  const answered = (answers: Record<string, string>, extra: Record<string, unknown> = {}) =>
    ({ result: { questions: BATCH.questions, answers, ...extra } })

  test('the issued batch passes and its answers are recorded with origin dialog', async ($, on) => {
    const { w } = world(on)
    on('tool.call', { tool: 'AskUserQuestion' }, () => answered({ 'Which engine name?': 'protocol' }, { annotations: { 'Which engine name?': { notes: 'n' } } }) as never)
    await start($)
    const ran = await $.tool.call({ tool: 'AskUserQuestion', questions: BATCH.questions, metadata: { source: BATCH.marker } } as never)
    expect(ran.deny).toBeUndefined()
    const call = w.calls.find(one => one.argv[3] === 'answer')
    expect(call?.argv.slice(3)).toEqual(['answer', '--origin', 'dialog'])
    expect(JSON.parse(call?.stdin ?? '{}')).toEqual({ marker: BATCH.marker, answers: { 'Which engine name?': 'protocol' }, annotations: { 'Which engine name?': { notes: 'n' } }, response: null })
  })

  describe('the batch text prints between turns', () => {
    const NOTICE = 'Engine name\nProblem: which name.\nCases: a typed command.\nOptions:\n- protocol: for: exact; against: long'
    const asking = (notice = NOTICE) => roundJson({ step: 'ask', batch: { ...BATCH, notice } })
    const complete = (extra: Record<string, unknown> = {}) => ({ answer: '', durationMs: 1, isAborted: false, turnId: 't', reason: 'answer', ...extra }) as never
    const typed = { origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } } as const
    const dialog = { tool: 'AskUserQuestion', questions: BATCH.questions, metadata: { source: BATCH.marker } } as never

    test('/console-questions answers with the engine text of the issued batch, and says so when there is none', async ($, on) => {
      const { w, clock } = world(on, { round: asking() })
      await start($)
      await clock.settle()
      expect((await $.command.run({ command: 'console-questions', args: '', ...typed })).text).toBe(`\n${NOTICE}`)
      expect((await $.command.run({ command: 'console-questions', args: BATCH.marker, ...typed })).text).toBe(`\n${NOTICE}`)
      expect((await $.command.run({ command: 'console-questions', args: 'round:r4:9', ...typed })).text).toBe('No question text to print.')
      w.round = asking('')
      await $.tool.call({ tool: 'mcp__console__protocol', args: ['show', '--json'] } as never)
      expect((await $.command.run({ command: 'console-questions', args: '', ...typed })).text).toBe('No question text to print.')
    })

    test('the dialog of a batch with text waits for the print: blocked once with the reason to end the turn, then it passes', async ($, on) => {
      world(on, { round: asking() })
      on('tool.call', { tool: 'AskUserQuestion' }, () => answered({ 'Which engine name?': 'protocol' }) as never)
      await start($)
      const first = await $.tool.call(dialog)
      expect(String(first.deny)).toContain('end your turn')
      expect(String(first.deny)).toContain('opens the dialog')
      expect((await $.tool.call(dialog)).deny).toBeUndefined()
    })

    test('a turn end prints the batch once: the dialog then passes at once, and the answers are recorded', async ($, on) => {
      const { w, clock } = world(on, { round: asking() })
      on('tool.call', { tool: 'AskUserQuestion' }, () => answered({ 'Which engine name?': 'protocol' }) as never)
      await start($)
      await $.turn.complete(complete())
      await $.turn.complete(complete())
      await clock.settle()
      expect((await $.tool.call(dialog)).deny).toBeUndefined()
      expect(w.verbs().some(verb => verb.startsWith('answer'))).toBe(true)
    })

    test('an aborted turn end and a subagent turn end print nothing; an empty text needs no print', async ($, on) => {
      const { w, clock } = world(on, { round: asking() })
      on('tool.call', { tool: 'AskUserQuestion' }, () => answered({ 'Which engine name?': 'protocol' }) as never)
      await start($)
      await $.turn.complete(complete({ isAborted: true, reason: 'aborted' }))
      await $.turn.complete(complete({ agentId: 'a1' }))
      await clock.settle()
      expect(String((await $.tool.call(dialog)).deny)).toContain('end your turn')  // still unprinted
      w.round = asking('')
      expect((await $.tool.call(dialog)).deny).toBeUndefined()
    })

    describe('the console opens the whole batch itself, with no model turn (r32-q149)', () => {
      const QUESTION = 'Which engine name?'
      const label = BATCH.questions[0]?.options[0]?.label ?? ''

      test('the placeholder becomes the issued batch; a plain pick is recorded and the model hears one line', async ($, on) => {
        const { w, clock } = world(on, { round: asking() })
        let drawn: unknown
        on('tool.call', { tool: 'AskUserQuestion' }, (_, e) => { drawn = (e as any); return answered({ [QUESTION]: label }) as never })
        await start($)
        await $.turn.complete(complete())
        await clock.settle()
        expect((drawn as any).questions).toEqual(BATCH.questions)
        expect((drawn as any).metadata).toEqual({ source: BATCH.marker })
        expect(w.verbs()).toContain('answer --origin dialog')
        expect(w.prompts).toEqual([engineLine([label])])
      })

      test('the engine\'s line reads as the person\'s own words; the console\'s own request stays framed', async ($, on) => {
        const { w, clock } = world(on, { round: asking() })
        on('tool.call', { tool: 'AskUserQuestion' }, () => answered({ [QUESTION]: label }) as never)
        await start($)
        await $.turn.complete(complete())
        await clock.settle()
        expect(w.asUser).toEqual([true])
      })

      test('a next batch wakes the model, and its turn end opens that batch', async ($, on) => {
        const { w, clock } = world(on, { round: asking() })
        const asked: string[] = []
        on('tool.call', { tool: 'AskUserQuestion' }, (_, e) => {
          asked.push(String((e as any).metadata?.source))
          if (asked.length === 1) w.round = roundJson({ step: 'ask', batch: { ...BATCH, marker: 'round:r4:3', notice: '' } })
          return answered({ [QUESTION]: label }) as never
        })
        await start($)
        await $.turn.complete(complete())
        await clock.settle()
        expect(asked).toEqual([BATCH.marker])
        expect(w.prompts).toEqual([engineLine([label])])
        await $.turn.complete(complete())
        await clock.settle()
        expect(asked).toEqual([BATCH.marker, 'round:r4:3'])
      })

      test('a pending pass after a plain pick runs with no model turn', async ($, on) => {
        const { w, clock } = world(on, { round: asking() })
        on('tool.call', { tool: 'AskUserQuestion' }, () => {
          w.round = roundJson({ step: 'check', batch: null, pending: { id: 'p9', command: 'challenge-rulings', args: 'q1' } })
          return answered({ [QUESTION]: label }) as never
        })
        await start($)
        await $.turn.complete(complete())
        await clock.settle()
        expect(w.commands.some(one => one.command === 'challenge-rulings')).toBe(true)
        expect(w.prompts).toEqual([])
      })

      test('a typed reply or a note wakes the model even with a next batch out', async ($, on) => {
        const { w, clock } = world(on, { round: asking() })
        on('tool.call', { tool: 'AskUserQuestion' }, () => {
          w.round = roundJson({ step: 'ask', batch: { ...BATCH, marker: 'round:r4:3', notice: '' } })
          return answered({ [QUESTION]: 'my own words' }) as never
        })
        await start($)
        await $.turn.complete(complete())
        await clock.settle()
        expect(w.prompts).toEqual([engineLine(['my own words'])])
      })

      test('a declined dialog is recorded and wakes the model', async ($, on) => {
        const { w, clock } = world(on, { round: asking() })
        on('tool.call', { tool: 'AskUserQuestion' }, () => ({ isError: true, result: 'declined', text: 'declined' }) as never)
        await start($)
        await $.turn.complete(complete())
        await clock.settle()
        expect(w.verbs().some(one => one.startsWith('decline'))).toBe(true)
        expect(w.prompts).toEqual(['The dialog was declined.'])
      })

      test('Esc cancels the save of a decline: it is saved once the dialog closed, with no error shown', async ($, on) => {
        const { w, clock, session } = world(on, { round: asking() })
        w.failVerbs = ['decline']
        on('tool.call', { tool: 'AskUserQuestion' }, () => ({ isError: true, result: 'declined', text: 'declined' }) as never)
        await start($)
        await $.turn.complete(complete())
        await clock.settle()
        expect(w.verbs().filter(one => one.startsWith('decline'))).toHaveLength(2)
        expect(w.prompts).toEqual(['The dialog was declined.'])
        expect(notices(session).filter(text => text.includes('not recorded') || text.includes('not saved'))).toEqual([])
      })

      test('a failed save of answers says so plainly, and the questions come again', async ($, on) => {
        const { w, clock, session } = world(on, { round: asking() })
        w.failVerbs = ['answer']
        let opened = 0
        on('tool.call', { tool: 'AskUserQuestion' }, () => { opened += 1; return answered({ [QUESTION]: label }) as never })
        await start($)
        await $.turn.complete(complete())
        await clock.settle()
        expect(w.prompts.filter(text => text.includes('were not saved') && text.includes('come again'))).toHaveLength(1)
        expect(notices(session).filter(text => text.includes('protocol tool'))).toEqual([])
        await $.turn.complete(complete())
        await clock.settle()
        expect(opened).toBe(2)
      })

      test('without a batch to swap in, the placeholder is never drawn', async ($, on) => {
        world(on, { round: roundJson({ batch: null }) })
        let reached = false
        on('tool.call', { tool: 'AskUserQuestion' }, () => { reached = true; return answered({}) as never })
        await start($)
        const ran = await $.tool.call({ tool: 'AskUserQuestion', questions: [{ question: `Console round dialog ${BATCH.marker}?`, header: 'Round', multiSelect: false, options: [{ label: 'a', description: '' }, { label: 'b', description: '' }] }] } as never)
        expect(String(ran.deny)).toContain('no batch')
        expect(reached).toBe(false)
      })
    })

    describe('when the console cannot open it, the model does (r29-q138, r30-q140)', () => {
      const message = (w: { prompts: string[] }) => w.prompts.filter(text => text === openDialogText(BATCH.marker))
      const composer = (text: string) => ({ text, origin: { kind: 'composer' }, wait: false }) as never

      test('a turn end prints the batch, then sends the message that opens its dialog, once per marker', async ($, on) => {
        const { w, clock } = world(on, { round: asking() })
        await start($)
        await $.turn.complete(complete())
        await clock.settle()
        expect(message(w)).toHaveLength(1)
        // The model did not open it: the console does not ask again for the same batch, however often turns end. The message
        // started its turn, which releases the press guard, so only the marker guard holds the repeat back.
        await $.turn.start({ text: openDialogText(BATCH.marker), turnId: 't1' } as never)
        await $.turn.complete(complete())
        await $.turn.complete(complete())
        await clock.settle()
        expect(message(w)).toHaveLength(1)
      })

      test('a new message of the person resets it: the next turn end sends the message again', async ($, on) => {
        const { w, clock } = world(on, { round: asking() })
        await start($)
        await $.turn.complete(complete())
        await clock.settle()
        await $.turn.start({ text: openDialogText(BATCH.marker), turnId: 't1' } as never)  // the message started its turn: the press guard is released
        await $.prompt.submit({ text: 'hidden', origin: { kind: 'composer' }, isMeta: true, wait: false } as never)
        await $.prompt.submit({ text: 'from a plugin', origin: { kind: 'plugin', name: 'x' }, wait: false } as never)
        await $.turn.complete(complete())
        await clock.settle()
        expect(message(w)).toHaveLength(1)  // neither a hidden prompt nor a plugin's resets it, nor does the console's own message
        await $.turn.start({ text: openDialogText(BATCH.marker), turnId: 't2' } as never)  // the first message started its turn: its repeat guard is released
        await $.prompt.submit(composer('what does flow mean?'))
        await $.turn.complete(complete())
        await clock.settle()
        expect(message(w)).toHaveLength(2)
        await $.turn.start({ text: openDialogText(BATCH.marker), turnId: 't3' } as never)
        await $.prompt.submit({ text: 'and from my phone', origin: { kind: 'bridge' }, wait: false } as never)
        await $.turn.complete(complete())
        await clock.settle()
        expect(message(w)).toHaveLength(3)
      })

      test('another batch gets its own message', async ($, on) => {
        const { w, clock } = world(on, { round: asking() })
        await start($)
        await $.turn.complete(complete())
        w.round = roundJson({ step: 'ask', batch: { ...BATCH, marker: 'round:r4:3', notice: NOTICE } })
        await $.tool.call({ tool: 'mcp__console__protocol', args: ['show', '--json'] } as never)
        await $.turn.complete(complete())
        await clock.settle()
        expect(w.prompts.filter(text => text.startsWith('Open the dialog'))).toEqual([openDialogText(BATCH.marker), openDialogText('round:r4:3')])
      })

      test('a run the hook never answered does not leave the round stuck: the person reads the text and the model opens the dialog', async ($, on) => {
        // The trimmed arguments cannot match this marker, so the hook answers without taking the batch: the kit's stand-in for a run it never answered.
        const marker = `${BATCH.marker} `
        const { w, clock, session } = world(on, { round: roundJson({ step: 'ask', batch: { ...BATCH, marker, notice: NOTICE } }) })
        await start($)
        await $.turn.complete(complete())
        await clock.settle()
        expect(w.prompts).toEqual([openDialogText(marker)])
        expect(notices(session).join(' ')).toContain('Engine name')
      })

      test('run by the console, the command prints the text every time, also for a batch reopened (r36-q198)', async ($, on) => {
        const { clock } = world(on, { round: asking() })
        await start($)
        await clock.settle()
        const own = { command: 'console-questions', args: BATCH.marker, origin: { kind: 'plugin', name: 'console' }, presentation: typed.presentation } as never
        expect((await $.command.run(own)).text).toBe(`\n${NOTICE}`)
        expect((await $.command.run(own)).text).toBe(`\n${NOTICE}`)
      })

      test('an empty text sends at once, with nothing to print', async ($, on) => {
        const { w, clock } = world(on, { round: asking('') })
        await start($)
        await $.turn.complete(complete())
        await clock.settle()
        expect(message(w)).toHaveLength(1)
        expect(w.asUser).toEqual([false])
      })

      test('an aborted turn end, a subagent turn end, a round without a batch and the autopilot role send nothing', async ($, on) => {
        const { w, clock } = world(on, { round: asking() })
        await start($)
        await $.turn.complete(complete({ isAborted: true, reason: 'aborted' }))
        await $.turn.complete(complete({ agentId: 'a1' }))
        w.round = roundJson({ batch: null })
        await $.tool.call({ tool: 'mcp__console__protocol', args: ['show', '--json'] } as never)
        await $.turn.complete(complete())
        await clock.settle()
        expect(w.prompts).toEqual([])
        w.round = asking()
        w.role = { session: SESSION, role: 'autopilot', actor: '617adf08', tool: 'claude' }
        await $.turn.complete(complete())
        await clock.settle()
        expect(w.prompts).toEqual([])
      })

      test('a failed send gives a notice and sends nothing; the next turn end tries again', async ($, on) => {
        const { w, clock, session } = world(on, { round: asking() })
        await start($)
        w.promptError = 'offline'
        await $.turn.complete(complete())
        await clock.settle()
        expect(w.prompts).toEqual([])
        expect(notices(session).some(text => text.includes('sending the message that opens the dialog failed') && text.includes('offline'))).toBe(true)
        w.promptError = null
        await $.turn.complete(complete())
        await clock.settle()
        expect(message(w)).toHaveLength(1)
      })

      test('a release approval takes the same path', async ($, on) => {
        const { w, clock } = world(on, { round: roundJson({ protocol: 'release', step: 'ask', check: null, questions: [], batch: { ...BATCH, notice: 'Release fx-a\nMy ruling: x\nInstead: y\nWhy not: z' } }) })
        await start($)
        await $.turn.complete(complete())
        await clock.settle()
        expect(message(w)).toHaveLength(1)
      })

      test('the gate is unchanged: a dialog before the print is blocked once', async ($, on) => {
        world(on, { round: asking() })
        on('tool.call', { tool: 'AskUserQuestion' }, () => answered({ 'Which engine name?': 'protocol' }) as never)
        await start($)
        expect(String((await $.tool.call(dialog)).deny)).toContain('end your turn')
        expect((await $.tool.call(dialog)).deny).toBeUndefined()
      })
    })

    test('a dialog that is not the issued batch is judged as before, printed or not', async ($, on) => {
      const { clock } = world(on, { round: asking() })
      on('tool.call', { tool: 'AskUserQuestion' }, () => answered({}) as never)
      await start($)
      await $.turn.complete(complete())
      await clock.settle()
      const other = await $.tool.call({ tool: 'AskUserQuestion', questions: BATCH.questions, metadata: { source: 'round:r4:9' } } as never)
      expect(String(other.deny)).toContain('issued round:r4:2')
    })
  })

  test('free text is recorded verbatim as the response', async ($, on) => {
    const { w } = world(on)
    on('tool.call', { tool: 'AskUserQuestion' }, () => answered({}, { response: 'step back first' }) as never)
    await start($)
    await $.tool.call({ tool: 'AskUserQuestion', questions: BATCH.questions, metadata: { source: BATCH.marker } } as never)
    expect(JSON.parse(w.calls.find(one => one.argv[3] === 'answer')?.stdin ?? '{}').response).toBe('step back first')
  })

  test('an error result declines the batch with nothing recorded', async ($, on) => {
    const { w } = world(on)
    on('tool.call', { tool: 'AskUserQuestion' }, () => ({ isError: true, result: 'declined', text: 'declined' }) as never)
    await start($)
    await $.tool.call({ tool: 'AskUserQuestion', questions: BATCH.questions, metadata: { source: BATCH.marker } } as never)
    const call = w.calls.find(one => one.argv[3] === 'decline')
    expect(call?.argv.slice(3)).toEqual(['decline', '--origin', 'dialog'])
    expect(JSON.parse(call?.stdin ?? '{}')).toEqual({ marker: BATCH.marker, partial: null })
    expect(w.verbs().some(verb => verb.startsWith('answer'))).toBe(false)
  })

  test('a dialog that resolved itself declines; followUp records the answers given', async ($, on) => {
    const { w } = world(on)
    let result: unknown = answered({ 'Which engine name?': 'protocol' }, { afkTimeoutMs: 60000 })
    on('tool.call', { tool: 'AskUserQuestion' }, () => result as never)
    await start($)
    await $.tool.call({ tool: 'AskUserQuestion', questions: BATCH.questions, metadata: { source: BATCH.marker } } as never)
    result = answered({ 'Which engine name?': 'protocol' }, { followUp: true })
    await $.tool.call({ tool: 'AskUserQuestion', questions: BATCH.questions, metadata: { source: BATCH.marker } } as never)
    const declines = w.calls.filter(one => one.argv[3] === 'decline').map(one => JSON.parse(one.stdin ?? '{}').partial)
    expect(declines).toEqual([null])
    const answer = w.calls.find(one => one.argv[3] === 'answer')
    expect(JSON.parse(answer?.stdin ?? '{}')).toMatchObject({ answers: { 'Which engine name?': 'protocol' }, followUp: true })
  })

  test('a marked batch that differs from the issued one is blocked once, then passes unrecorded', async ($, on) => {
    const { w, session } = world(on)
    on('tool.call', { tool: 'AskUserQuestion' }, () => answered({ 'Which engine?': 'protocol' }) as never)
    await start($)
    const changed = [{ ...BATCH.questions[0], question: 'Which engine?' }]
    const first = await $.tool.call({ tool: 'AskUserQuestion', questions: changed, metadata: { source: BATCH.marker } } as never)
    expect(String(first.deny)).toContain('differs from the batch round r4 issued')
    const second = await $.tool.call({ tool: 'AskUserQuestion', questions: changed, metadata: { source: BATCH.marker } } as never)
    expect(second.deny).toBeUndefined()
    expect(second.context?.join(' ')).toContain('not recorded')
    expect(w.verbs().some(verb => verb.startsWith('answer'))).toBe(false)
    expect(notices(session).some(text => text.includes('blocked a dialog once'))).toBe(true)
  })

  test('the gate compares option previews: the issued preview passes, a dropped one differs', async ($, on) => {
    const withPreview = { ...BATCH, questions: [{ ...BATCH.questions[0], options: [{ ...BATCH.questions[0]!.options[0]!, preview: 'engine --json' }, BATCH.questions[0]!.options[1]!] }] }
    world(on, { round: roundJson({ batch: withPreview }) })
    on('tool.call', { tool: 'AskUserQuestion' }, () => answered({ 'Which engine name?': 'protocol' }) as never)
    await start($)
    const issued = await $.tool.call({ tool: 'AskUserQuestion', questions: withPreview.questions, metadata: { source: BATCH.marker } } as never)
    expect(issued.deny).toBeUndefined()
    const dropped = await $.tool.call({ tool: 'AskUserQuestion', questions: BATCH.questions, metadata: { source: BATCH.marker } } as never)
    expect(String(dropped.deny)).toContain('differs from the batch round r4 issued')
  })

  test('an unmarked dialog repeating a staged question is blocked once', async ($, on) => {
    world(on)
    on('tool.call', { tool: 'AskUserQuestion' }, () => answered({ 'Which pane layout?': 'one' }) as never)
    await start($)
    const asked = [{ question: 'Which pane layout?', header: 'Pane', multiSelect: false, options: [{ label: 'one', description: '' }, { label: 'two', description: '' }] }]
    const first = await $.tool.call({ tool: 'AskUserQuestion', questions: asked } as never)
    expect(String(first.deny)).toContain('q3 is staged in round r4')
    const second = await $.tool.call({ tool: 'AskUserQuestion', questions: asked } as never)
    expect(second.deny).toBeUndefined()
  })

  test('another unmarked dialog passes with a note for the model', async ($, on) => {
    const { w } = world(on)
    on('tool.call', { tool: 'AskUserQuestion' }, () => answered({ 'Lunch?': 'yes' }) as never)
    await start($)
    const ran = await $.tool.call({ tool: 'AskUserQuestion', questions: [{ question: 'Lunch?', header: 'Lunch', multiSelect: false, options: [{ label: 'yes', description: '' }, { label: 'no', description: '' }] }] } as never)
    expect(ran.context).toEqual(['This dialog was not from round r4; its answers were not recorded in the round.'])
    expect(w.verbs().some(verb => verb.startsWith('answer'))).toBe(false)
  })

  test('outside an open round the gate stays out of the way', async ($, on) => {
    const { w } = world(on, { round: NO_ROUND })
    on('tool.call', { tool: 'AskUserQuestion' }, () => answered({ 'Which pane layout?': 'one' }) as never)
    await start($)
    const ran = await $.tool.call({ tool: 'AskUserQuestion', questions: [{ question: 'Which pane layout?', header: 'Pane', multiSelect: false, options: [{ label: 'one', description: '' }, { label: 'two', description: '' }] }] } as never)
    expect(ran.context).toBeUndefined()
    expect(w.verbs().every(verb => verb.startsWith('show'))).toBe(true)
  })
})

describe('machine-run passes', () => {
  const complete = (isAborted = false) => ({ answer: '', durationMs: 1, isAborted, turnId: 't', reason: isAborted ? 'aborted' : 'answer' }) as never

  test('turn.complete runs the pending pass once, recorded with origin plugin', async ($, on) => {
    const { w, clock } = world(on, { round: roundJson({ pending: { id: 'p7', command: 'ground', args: '' } }) })
    await start($)
    await $.turn.complete(complete())
    await $.turn.complete(complete())
    await clock.settle()
    expect(w.commands.filter(one => one.command === 'ground')).toEqual([{ command: 'ground', args: '' }])
    const pass = w.calls.find(one => one.argv[3] === 'pass')
    await clock.settle()
    expect(pass?.argv.slice(3)).toEqual(['pass', '--origin', 'plugin'])
    expect(JSON.parse(pass?.stdin ?? '{}')).toEqual({ command: 'ground', args: '', pending: 'p7' })
  })

  test('a Think more rerun runs and records its argument verbatim, goal included (r38-q213)', async ($, on) => {
    const args = 'goal foundations q3 Think more on q3: the person asked for a reasoned strong recommendation; what fell short: the lean (your call: taste)'
    const { w, clock } = world(on, { round: roundJson({ pending: { id: 'p8', command: 'step-back', args } }) })
    await start($)
    await $.turn.complete(complete())
    await clock.settle()
    expect(w.commands.filter(one => one.command === 'step-back')).toEqual([{ command: 'step-back', args }])
    const pass = w.calls.find(one => one.argv[3] === 'pass')
    expect(JSON.parse(pass?.stdin ?? '{}')).toEqual({ command: 'step-back', args, pending: 'p8' })
  })

  test('a pass turn that ends with the same pending id asks the model once, then tells the person, and is not re-run', async ($, on) => {
    const { w, session, clock } = world(on, { round: roundJson({ pending: { id: 'p7', command: 'ground', args: '' } }) })
    await start($)
    await $.turn.complete(complete())
    await $.command.run({ command: 'ground', args: '', origin: { kind: 'plugin', name: 'console' }, presentation: { isFullscreen: true, columns: 160 } })
    await $.skill.prompt({ skill: 'ground', text: 'Ground…' } as never)  // the queued run starts as its skill expands
    await $.turn.complete(complete())
    await clock.settle()
    expect(w.prompts.filter(text => text.includes('ended without its report'))).toHaveLength(1)
    expect(notices(session).filter(text => text.includes('The round stopped'))).toHaveLength(0)
    await $.turn.complete(complete())
    await clock.settle()
    expect(notices(session).filter(text => text.includes('The round stopped: the /ground pass has no report. Type /ground to run it again.'))).toHaveLength(1)
    await $.turn.complete(complete())
    await clock.settle()
    expect(w.prompts.filter(text => text.includes('ended without its report'))).toHaveLength(1)
    expect(notices(session).filter(text => text.includes('The round stopped'))).toHaveLength(1)
    expect(w.commands.filter(one => one.command === 'ground' && one.args === '')).toHaveLength(2)
  })

  test('a pending pass the person runs is not queued again, and is asked for when it ends unreported', async ($, on) => {
    const { w, clock } = world(on, { round: roundJson({ pending: { id: 'p7', command: 'ground', args: '' } }) })
    await start($)
    await $.command.run({ command: 'ground', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } })
    await $.skill.prompt({ skill: 'ground', text: 'Ground…' } as never)
    await $.turn.complete(complete())
    await clock.settle()
    expect(w.commands.filter(one => one.command === 'ground')).toHaveLength(1)
    expect(w.prompts.filter(text => text.includes('ended without its report'))).toHaveLength(1)
  })

  test('a turn ending while the pass still waits in the queue asks for no report', async ($, on) => {
    // The false alarm: another prompt runs first (the line after a dialog), and its turn ends before the pass began.
    const { w, clock } = world(on, { round: roundJson({ pending: { id: 'p7', command: 'ground', args: '' } }) })
    await start($)
    await $.turn.complete(complete())
    await clock.settle()
    await $.command.run({ command: 'ground', args: '', origin: { kind: 'plugin', name: 'console' }, presentation: { isFullscreen: true, columns: 160 } })
    await $.turn.complete(complete())
    await clock.settle()
    expect(w.prompts.filter(text => text.includes('ended without its report'))).toHaveLength(0)
    await $.skill.prompt({ skill: 'ground', text: 'Ground…' } as never)
    await $.turn.complete(complete())
    await clock.settle()
    expect(w.prompts.filter(text => text.includes('ended without its report'))).toHaveLength(1)
  })

  test("the pass's skill expanding marks it started too", async ($, on) => {
    const { w, clock } = world(on, { round: roundJson({ pending: { id: 'p7', command: 'ground', args: '' } }) })
    await start($)
    await $.turn.complete(complete())
    await clock.settle()
    await $.skill.prompt({ skill: 'ground', text: 'Ground…' } as never)
    await $.turn.complete(complete())
    await clock.settle()
    expect(w.prompts.filter(text => text.includes('ended without its report'))).toHaveLength(1)
  })

  test('a new pending id runs again', async ($, on) => {
    const { w, clock } = world(on, { round: roundJson({ pending: { id: 'p7', command: 'step-back', args: '' } }) })
    await start($)
    await $.turn.complete(complete())
    w.round = roundJson({ pending: { id: 'p8', command: 'step-back', args: '' } })
    await $.turn.complete(complete())
    await clock.settle()
    expect(w.commands.filter(one => one.command === 'step-back')).toHaveLength(2)
  })

  test('Esc stops the loop: an aborted turn starts nothing', async ($, on) => {
    const { w, clock } = world(on, { round: roundJson({ pending: { id: 'p7', command: 'ground', args: '' } }) })
    await start($)
    await $.turn.complete(complete(true))
    await clock.settle()
    expect(w.commands).toEqual([])
  })

  test("a subagent's turn end runs nothing", async ($, on) => {
    const { w, clock } = world(on, { round: roundJson({ pending: { id: 'p7', command: 'ground', args: '' } }) })
    await start($)
    await $.turn.complete({ ...(complete() as object), agentId: 'a1' } as never)
    await clock.settle()
    expect(w.commands).toEqual([])
  })
})

describe('skill expansion', () => {
  const complete = () => ({ answer: '', durationMs: 1, isAborted: false, turnId: 't', reason: 'answer' }) as never
  const plugin = { kind: 'plugin', name: 'console' } as const
  const presentation = { isFullscreen: true, columns: 160 }

  test("the console's own pass expands to the skill's full text", async ($, on) => {
    const { clock } = world(on, { round: roundJson({ pending: { id: 'p7', command: 'ground', args: 'assumptions' } }) })
    await start($)
    await $.turn.complete(complete())
    await $.command.run({ command: 'ground', args: 'assumptions', origin: plugin, presentation })
    const expanded = await ($.skill.prompt({ skill: 'ground', text: 'Ground, in full.' } as never) as Promise<{ text: string }>)
    expect(expanded.text).toBe('Ground, in full.')
    await clock.settle()
  })
})

describe('pass observation', () => {
  test('a model Skill call counts after it ran, with origin model', async ($, on) => {
    const { w } = world(on)
    on('tool.call', { tool: 'Skill' }, () => ({ result: { success: true } }) as never)
    await start($)
    await $.tool.call({ tool: 'Skill', skill: 'step-back', args: 'bloat' } as never)
    const pass = w.calls.find(one => one.argv[3] === 'pass')
    expect(pass?.argv.slice(3)).toEqual(['pass', '--origin', 'model'])
    expect(JSON.parse(pass?.stdin ?? '{}')).toEqual({ command: 'step-back', args: 'bloat', pending: null })
  })

  test('a failed Skill call does not count', async ($, on) => {
    const { w } = world(on)
    on('tool.call', { tool: 'Skill' }, () => ({ isError: true, result: 'no', text: 'no' }) as never)
    await start($)
    await $.tool.call({ tool: 'Skill', skill: 'ground' } as never)
    expect(w.verbs().some(verb => verb.startsWith('pass'))).toBe(false)
  })

  test('a typed command counts with its origin; other commands do not', async ($, on) => {
    const { w } = world(on)
    await start($)
    await $.tool.call({ tool: 'mcp__console__protocol', args: ['show', '--json'] } as never)
    await $.command.run({ command: 'ground', args: 'probe', origin: { kind: 'bridge' }, presentation: { isFullscreen: true, columns: 160 } })
    await $.command.run({ command: 'commit', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } })
    const passes = w.calls.filter(one => one.argv[3] === 'pass')
    expect(passes.map(one => one.argv.slice(3))).toEqual([['pass', '--origin', 'bridge']])
  })

  test('a typed /release-round reaches the engine as conditional approval, open run or not; a plugin run does not', async ($, on) => {
    const { w, session } = world(on, { round: NO_ROUND })
    await start($)
    await $.command.run({ command: 'release-round', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } })
    await $.command.run({ command: 'release-round', args: 'and close', origin: { kind: 'bridge' }, presentation: { isFullscreen: true, columns: 160 } })
    await $.command.run({ command: 'release-round', args: '', origin: { kind: 'plugin', name: 'console' }, presentation: { isFullscreen: true, columns: 160 } })
    const stamps = w.calls.filter(one => one.argv[3] === 'pass')
    expect(stamps.map(one => [one.argv.slice(3), JSON.parse(one.stdin ?? '{}')])).toEqual([
      [['pass', '--origin', 'composer'], { command: 'release-round', args: '', pending: null }],
      [['pass', '--origin', 'bridge'], { command: 'release-round', args: 'and close', pending: null }],
    ])
    w.protocolExit = 1
    await $.command.run({ command: 'release-round', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } })
    expect(notices(session).some(one => one.includes('/release-round did not reach the release'))).toBe(true)
    expect(w.commands.filter(one => one.command === 'release-round')).toHaveLength(4)  // the skill runs every time
  })

  test("the person's chat messages reach the round; commands and hidden prompts do not", async ($, on) => {
    const { w } = world(on)
    await start($)
    await $.tool.call({ tool: 'mcp__console__protocol', args: ['show', '--json'] } as never)
    await $.prompt.submit({ text: 'use flow, not protocol', origin: { kind: 'composer' }, wait: false } as never)
    await $.prompt.submit({ text: 'hidden', origin: { kind: 'composer' }, isMeta: true, wait: false } as never)
    await $.prompt.submit({ text: 'from a plugin', origin: { kind: 'plugin', name: 'x' }, wait: false } as never)
    const says = w.calls.filter(one => one.argv[3] === 'say')
    expect(says.map(one => [one.argv.slice(3), JSON.parse(one.stdin ?? '{}')])).toEqual([[['say', '--origin', 'composer'], { text: 'use flow, not protocol' }]])
  })
})

describe('recovery', () => {
  test('compaction keeps the round and appends the status line', async ($, on) => {
    world(on)
    let instructions = ''
    on('session.compact', (_, e) => { instructions = e.instructions ?? ''; return { messages: [{ role: 'user', text: 'summary', toolUses: [] }] } })
    await start($)
    const compacted = await $.session.compact({ trigger: 'manual', instructions: 'the plan', messages: [{ role: 'user', text: 'hi', toolUses: [] }] })
    expect(instructions).toContain('the plan')
    expect(instructions).toContain('Keep the protocol round state: round r4')
    expect(compacted.messages?.at(-1)?.text).toContain('round r4 · check 2/3 · next ground')
  })

  test('without an open round compaction is left alone', async ($, on) => {
    world(on, { round: NO_ROUND })
    let instructions: string | undefined = 'unset'
    on('session.compact', (_, e) => { instructions = e.instructions; return { messages: [{ role: 'user', text: 'summary', toolUses: [] }] } })
    await start($)
    await $.session.compact({ trigger: 'auto', messages: [{ role: 'user', text: 'hi', toolUses: [] }] })
    expect(instructions).toBeUndefined()
  })
})

