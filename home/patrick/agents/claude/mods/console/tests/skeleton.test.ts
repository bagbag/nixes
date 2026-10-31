// Walking skeleton: idle rules, the protocol tool, the dialog gate, answer capture,
// machine-run passes, pass observation and recovery.
import { describe, expect, test } from 'claude-code/testing'

import { BATCH, NO_ROUND, notes, notices, PROTOCOL, roundJson, SESSION, world } from './fixture'

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

  test('a pass turn that ends with the same pending id gets a note, and is not re-run', async ($, on) => {
    const { w, session, clock } = world(on, { round: roundJson({ pending: { id: 'p7', command: 'ground', args: '' } }) })
    await start($)
    await $.turn.complete(complete())
    // The queued run starts as a command the console itself ran.
    await $.command.run({ command: 'ground', args: '', origin: { kind: 'plugin', name: 'console' }, presentation: { isFullscreen: true, columns: 160 } })
    await $.turn.complete(complete())
    await $.turn.complete(complete())
    await clock.settle()
    expect(notes(session).filter(text => text.includes('ended without its report'))).toHaveLength(1)
    expect(notices(session).some(text => text.includes('ended without its report'))).toBe(true)
    await clock.settle()
    expect(w.commands.filter(one => one.command === 'ground' && one.args === '')).toHaveLength(2)
  })

  test('a pending pass the person runs is not queued again, and is noted when it ends unreported', async ($, on) => {
    const { w, session, clock } = world(on, { round: roundJson({ pending: { id: 'p7', command: 'ground', args: '' } }) })
    await start($)
    await $.command.run({ command: 'ground', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } })
    await $.skill.prompt({ skill: 'ground', text: 'Ground…' } as never)
    await $.turn.complete(complete())
    await clock.settle()
    expect(w.commands.filter(one => one.command === 'ground')).toHaveLength(1)
    expect(notes(session).filter(text => text.includes('ended without its report'))).toHaveLength(1)
  })

  test("the pass's skill expanding marks it started too", async ($, on) => {
    const { session, clock } = world(on, { round: roundJson({ pending: { id: 'p7', command: 'ground', args: '' } }) })
    await start($)
    await $.turn.complete(complete())
    await clock.settle()
    await $.skill.prompt({ skill: 'ground', text: 'Ground…' } as never)
    await $.turn.complete(complete())
    await clock.settle()
    expect(notes(session).filter(text => text.includes('ended without its report'))).toHaveLength(1)
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

