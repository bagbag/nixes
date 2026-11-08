// r9-q36: a pass that starts names what its report must cover, as the engine works it out at that moment (`protocol scope`):
// the step named the scope a turn earlier, and it may have changed since.
import { describe, expect, test } from 'claude-code/testing'

import { roundJson, world } from './fixture'
import { STALE_PASS_TEXT } from '../hooks/words'

const start = async ($: any) => $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
const complete = () => ({ answer: '', durationMs: 1, isAborted: false, turnId: 't', reason: 'answer' }) as never
const presentation = { isFullscreen: true, columns: 160 }
const pending = (id: string, args = '', command = 'ground') => roundJson({ pending: { id, command, args } })
const expand = async ($: any, skill = 'ground') => ($.skill.prompt({ skill, text: 'Pass, in full.' } as never) as Promise<{ text: string }>)
const scopeCalls = (w: { calls: { argv: string[]; stdin: string | undefined }[] }) =>
  w.calls.filter(one => one.argv[3] === 'scope').map(one => ({ flags: one.argv.slice(4), input: JSON.parse(one.stdin ?? '{}') }))
const LINE = 'Use this scope, not one printed earlier. This pass covers q2 q3: …'

describe('a pass that starts names its scope (r9-q36)', () => {
  test('a console-run pass: the line the engine works out is appended, for the run already recorded', async ($, on) => {
    const { w, clock } = world(on, { round: pending('p7', 'assumptions') })
    w.scope = LINE
    await start($)
    await $.turn.complete(complete())  // the console queues the pending pass and records its run
    await clock.settle()
    expect((await expand($)).text).toBe(`Pass, in full.\n\n${LINE}`)
    expect(scopeCalls(w)).toEqual([{ flags: ['--origin', 'plugin'], input: { command: 'ground' } }])
  })

  test('an options pass also names the questions its explored list covers', async ($, on) => {
    const { w, clock } = world(on, { round: pending('p7', 'options', 'step-back') })
    w.scope = `${LINE} Give \`explored\` an entry for each of q2 q3 and no other.`
    await start($)
    await $.turn.complete(complete())
    await clock.settle()
    expect((await expand($, 'step-back')).text).toBe(`Pass, in full.\n\n${w.scope}`)
    expect(scopeCalls(w)).toEqual([{ flags: ['--origin', 'plugin'], input: { command: 'step-back' } }])
  })

  test('a stale queued pass gets the no-op text alone', async ($, on) => {
    const { w, clock } = world(on, { round: pending('p7') })
    w.scope = LINE
    await start($)
    await $.turn.complete(complete())
    await clock.settle()
    w.round = pending('p8')
    expect((await expand($)).text).toBe(STALE_PASS_TEXT)
    expect(scopeCalls(w)).toEqual([])
  })

  test('a person-typed pass gets the line', async ($, on) => {
    const { w } = world(on, { round: pending('p7') })
    w.scope = LINE
    await start($)
    await $.command.run({ command: 'ground', args: '', origin: { kind: 'composer' }, presentation })
    expect((await expand($)).text).toBe(`Pass, in full.\n\n${LINE}`)
    expect(scopeCalls(w)).toEqual([{ flags: ['--origin', 'plugin'], input: { command: 'ground' } }])
  })

  test("a model-run pass gets the line, with the stamp its run is recorded with once it ran", async ($, on) => {
    const { w } = world(on, { round: pending('p7', 'assumptions') })
    w.scope = LINE
    const read: string[] = []
    on('tool.call', { tool: 'Skill' }, async () => { read.push((await expand($)).text); return { result: { success: true } } as never })
    await start($)
    await $.tool.call({ tool: 'Skill', skill: 'ground', args: 'assumptions ' } as never)
    await $.tool.call({ tool: 'Skill', skill: 'ground', args: 'probe' } as never)  // not the pending pass: an extra run
    expect(read).toEqual([`Pass, in full.\n\n${LINE}`, `Pass, in full.\n\n${LINE}`])
    expect(scopeCalls(w).map(one => one.input)).toEqual([{ command: 'ground', pending: 'p7' }, { command: 'ground', pending: null }])
    const recorded = w.calls.filter(one => one.argv[3] === 'pass').map(one => JSON.parse(one.stdin ?? '{}').pending)
    expect(recorded).toEqual(['p7', null])  // the stamps the scope was worked out for
  })

  test('a failing engine or an empty scope leaves the text as it is', async ($, on) => {
    const { w } = world(on, { round: pending('p7') })
    await start($)
    await $.command.run({ command: 'ground', args: '', origin: { kind: 'composer' }, presentation })
    expect((await expand($)).text).toBe('Pass, in full.')  // nothing to name
    w.scope = LINE
    w.failVerbs = ['scope']
    await $.command.run({ command: 'ground', args: '', origin: { kind: 'composer' }, presentation })
    expect((await expand($)).text).toBe('Pass, in full.')
    w.protocolThrows = 'timed out'
    expect((await expand($)).text).toBe('Pass, in full.')
  })

  test("another skill, a subagent's pass and a session without a round role get no line", async ($, on) => {
    const { w } = world(on, { round: pending('p7') })
    w.scope = LINE
    on('tool.call', { tool: 'Skill' }, async () => { await expand($); return { result: { success: true } } as never })
    await start($)
    expect((await expand($, 'commit-commands:commit')).text).toBe('Pass, in full.')
    await $.tool.call({ tool: 'Skill', skill: 'ground', args: '', agentId: 'a1' } as never)
    w.role = { session: 's-1', role: 'worker', actor: 'x', tool: 'claude' }
    await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
    expect((await expand($)).text).toBe('Pass, in full.')
    expect(scopeCalls(w)).toEqual([])
  })
})
