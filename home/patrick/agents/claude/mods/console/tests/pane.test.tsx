// The pane, the band, presses, /console and the idle-agent notification.
import { describe, expect, test } from 'claude-code/testing'

import { cr } from './board-console-contract'
import { BATCH, HOME, NO_ROUND, notices, PANE_PROPS, roundJson, SESSION, world } from './fixture'
import { parseBoardConsole, parseRound } from '../hooks/engine'
import type { ConsoleBoard } from '../types'
import { suggestions } from '../hooks/pane'
import { consoleText, openDialogText, protocolCallText, protocolResultText, pullsText, recommendationText, roundWords, suggestionText } from '../hooks/words'

const PANE = { plugin: 'console', component: 'Pane', requestId: 'console', props: PANE_PROPS } as const
const BAND = {
  plugin: 'console', component: 'AbovePrompt',
  props: { hasSurvey: false, isCollapsed: false, isWorking: false, maxRows: 10, bodyColumns: 120, scroll: { offset: 0, bodyRows: 10 }, view: {} },
} as const

/** Starts the session and lets the first refresh (a timer) read the engine and the board. */
async function ready($: any, clock: { settle: () => Promise<void> }) {
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await clock.settle()
}

/** Every text the drawing shows, joined (hover hints included: they are drawn, hidden). */
const texts = async (ui: { findAll: (query: { type: string }) => Promise<{ text: string }[]> }): Promise<string> =>
  (await ui.findAll({ type: 'Text' })).map(one => one.text).join('\n')

describe('pane', () => {
  for (const surface of ['terminal', 'desktop'] as const) {
    test(`draws the board over the round on ${surface}`, async ($, on) => {
      const { clock } = world(on, {
        round: roundJson({ questions: [
          ...(roundJson().questions as unknown[]),
          { id: 'q4', board: null, text: 'Lens sets?', title: 'Lens sets', kind: 'decision', status: 'held', waitsOn: ['q3'], overlaps: [], answer: null },
        ] }),
        agents: [{ id: 'a1', description: 'Worker B', type: 'craft', status: 'running' }],
      })
      await ready($, clock)
      const ui = await $.ui.mount({ ...PANE, surface })
      const drawn = await texts(ui)
      for (const part of ['Board', 'lead 617adf08', 'for you', 'Round r4', 'checking 2/3', 'step-back changed 2, ground none', '1 held', 'Engine name', 'overlaps', 'Pane layout', 'waits on q3', 'where', 'what', 'Decide', 'Actions', 'in_progress']) {
        expect(drawn, part).toContain(part)
      }
      expect(await ui.find({ key: 'item-tstdl-x1-show' })).toBeDefined()
      expect(await ui.find({ key: 'q-q2-ov' })).toBeDefined()
      expect(await ui.find({ key: 'step-back-run' })).toBeUndefined()
      await ui.unmount()
    })
  }

  // r8-q31: a question held on an outside result names it on its row, as the engine's Check list does.
  test('a question held on an outside result names what it waits for', async ($, on) => {
    const { clock } = world(on, {
      round: roundJson({ questions: [
        ...(roundJson().questions as unknown[]),
        { id: 'q4', board: null, text: 'Lens sets?', title: 'Lens sets', kind: 'decision', status: 'held', waitsOn: [], waitsFor: 'the lens spike, in .scratch/lens', overlaps: [], answer: null },
        { id: 'q5', board: null, text: 'Lens order?', title: 'Lens order', kind: 'decision', status: 'held', waitsOn: ['q4'], waitsFor: null, overlaps: [], answer: null },
      ] }),
    })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const drawn = await texts(ui)
    expect(drawn).toContain('(waits for the lens spike, in .scratch/lens)')
    expect(drawn).toContain('(waits on q4)')
    await ui.unmount()
  })

  test('a shared board\'s stopped sync shows with its fix, and its other queues as counts', async ($, on) => {
    const { clock } = world(on, { sync: 'sync stopped by a merge conflict. Fix: board bd conflicts show', queueLine: 'other queues: ben 3' })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await texts(ui)).toContain('sync stopped by a merge conflict')
    expect(await texts(ui)).toContain('other queues: ben 3')
  })

  test('an agent role sees the board and actions, no round block', async ($, on) => {
    const { clock } = world(on, { role: { session: SESSION, role: 'agent', actor: 'eef8ae5c', tool: 'claude' } })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const drawn = await texts(ui)
    expect(drawn).toContain('agent eef8ae5c')
    expect(drawn).not.toContain('Round')
    expect(await ui.find({ key: 'actions-row-commit' })).toBeDefined()
    expect(await ui.find({ key: 'actions-row-release' })).toBeUndefined()
    await ui.unmount()
  })

  test('held questions count toward 10 with the rest: up to 10 all show, beyond it they fill what is left and the rest fold', async ($, on) => {
    const row = (id: string, status: string) => ({ id, board: null, text: `${id}?`, title: `Row ${id}`, kind: 'decision', status, waitsOn: status === 'held' ? ['q1'] : [], overlaps: [], answer: null, answeredAt: null })
    const ten = [...[1, 2, 3, 4, 5, 6, 7].map(n => row(`q${n}`, 'ready')), row('q8', 'held'), row('q9', 'held'), row('q10', 'held')]
    const { w, clock } = world(on, { round: roundJson({ questions: ten }) })
    await ready($, clock)
    let ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await texts(ui)).toContain('Row q8')
    expect(await texts(ui)).toContain('Row q10')
    expect(await ui.find({ key: 'held-toggle' })).toBeUndefined()
    expect(await texts(ui)).not.toContain('more ▸')
    await ui.unmount()
    w.round = roundJson({ questions: [...ten, row('q11', 'ready')] })
    await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
    await clock.settle()
    ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await texts(ui)).toContain('Row q7')
    expect(await texts(ui)).toContain('Row q9')
    expect(await texts(ui)).not.toContain('Row q10')
    expect(await texts(ui)).toContain('1 held')
    await ui.press({ key: 'held-toggle' })
    expect(await texts(ui)).toContain('Row q10')
    expect(await texts(ui)).toContain('3 held')
    await ui.unmount()
  })

  test('beyond 10 questions, 10 show whatever their kinds: held and older answered fill the room upcoming leaves', async ($, on) => {
    const base = (id: string, status: string) => ({ id, board: null, text: `${id}?`, title: `Row ${id}`, kind: 'decision', status, waitsOn: status === 'held' ? ['q1'] : [], overlaps: [], answer: null, answeredAt: null })
    const row = (n: number, status: string) => ({ ...base(`q${n}`, status), title: `Row ${n}.`, answeredAt: status === 'answered' ? `2026-10-31T${String(n).padStart(2, '0')}:00:00Z` : null })
    const heavyHeld = [row(1, 'ready'), row(2, 'ready'), row(3, 'ready'), row(4, 'ready'), ...Array.from({ length: 15 }, (_, i) => row(i + 5, 'held'))]
    const { w, clock } = world(on, { round: roundJson({ questions: heavyHeld }) })
    await ready($, clock)
    let ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const shown = async () => (await texts(ui)).match(/Row \d+\./g)?.filter((t, i, all) => all.indexOf(t) === i) ?? []
    expect((await shown()).length).toBe(10)
    expect(await texts(ui)).toContain('9 held')
    expect(await texts(ui)).not.toContain('more ▸')
    await ui.unmount()
    w.round = roundJson({ questions: [...Array.from({ length: 15 }, (_, i) => row(i + 1, 'answered')), row(16, 'ready'), row(17, 'ready')] })
    await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
    await clock.settle()
    ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await shown()).toEqual(['Row 8.', 'Row 9.', 'Row 10.', 'Row 11.', 'Row 12.', 'Row 13.', 'Row 14.', 'Row 15.', 'Row 16.', 'Row 17.'])
    expect(await texts(ui)).toContain('+7 more ▸')
    await ui.unmount()
  })

  test('the Release Round press stamps the release like a typed /release-round (r4-q16)', async ($, on) => {
    const { w, clock } = world(on)
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'actions-row-release' })
    await clock.settle()
    const stamp = w.calls.find(one => one.argv[3] === 'pass')
    expect([stamp?.argv.slice(3), JSON.parse(stamp?.stdin ?? '{}')]).toEqual([['pass', '--origin', 'press'], { command: 'release-round', args: '', pending: null }])
    expect(w.commands).toEqual([{ command: 'release-round', args: '' }])
    await ui.unmount()
  })

  test('lens toggles show ✓, Run N runs them with the focus, and the selection clears', async ($, on) => {
    const { w, clock } = world(on)
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'step-back-where-row-foundations' })
    await clock.advance(1000)
    await ui.press({ key: 'step-back-what-row-bloat' })
    expect(await texts(ui)).toContain('✓ Foundations')
    await ui.input({ key: 'focus', text: 'the gate', kind: 'change' })
    expect((await ui.find({ key: 'step-back-run' }))?.text).toContain('Run 2')
    await ui.press({ key: 'step-back-run' })
    await clock.settle()
    expect(w.commands).toEqual([{ command: 'step-back', args: 'foundations bloat the gate' }])
    expect(await ui.find({ key: 'step-back-run' })).toBeUndefined()
    const pass = w.calls.find(one => one.argv[3] === 'pass')
    expect(pass?.argv.slice(3)).toEqual(['pass', '--origin', 'press'])
    await ui.unmount()
  })

  test('a double click runs one lens alone', async ($, on) => {
    const { w, clock } = world(on)
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'ground-row-probe' })
    await clock.advance(200)
    await ui.press({ key: 'ground-row-probe' })
    await clock.settle()
    expect(w.commands).toEqual([{ command: 'ground', args: 'probe' }])
    expect(await texts(ui)).not.toContain('✓ Probe')
    await ui.unmount()
  })

  test('Base includes the typed focus, and a repeat press while queued is dropped', async ($, on) => {
    const { w, clock } = world(on)
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.input({ key: 'focus', text: 'the gate', kind: 'change' })
    await ui.press({ key: 'step-back-base' })
    await ui.press({ key: 'ground-base' })
    await ui.press({ key: 'ground-base' })
    await clock.settle()
    expect(w.commands).toEqual([{ command: 'step-back', args: 'the gate' }, { command: 'ground', args: '' }])
    expect(w.toasts).toContain('/ground is already queued')
    await ui.unmount()
  })

  test('a press works again once its run started, namespaced skills included', async ($, on) => {
    const { w, clock } = world(on)
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'ground-base' })
    await $.skill.prompt({ skill: 'ground', text: 'Ground…' } as never)
    await ui.press({ key: 'ground-base' })
    await ui.press({ key: 'actions-row-commit' })
    await $.skill.prompt({ skill: 'commit-commands:commit', text: 'Commit…' } as never)
    await ui.press({ key: 'actions-row-commit' })
    await clock.settle()
    expect(w.commands.map(one => one.command)).toEqual(['ground', 'ground', 'commit', 'commit'])
    expect(w.toasts.filter(text => text.includes('already queued'))).toEqual([])
    await ui.unmount()
  })

  test('All runs every lens of the command in list order with the focus, and keeps the selection', async ($, on) => {
    const { w, clock } = world(on)
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'ground-row-probe' })
    await ui.input({ key: 'focus', text: 'the gate', kind: 'change' })
    await ui.press({ key: 'step-back-all' })
    await ui.press({ key: 'ground-all' })
    await clock.settle()
    expect(w.commands).toEqual([
      { command: 'step-back', args: 'goal decisions foundations consumer root-fix bloat gaps clean overfit mechanics options the gate' },
      { command: 'ground', args: 'assumptions board sources probe' },
    ])
    expect(await texts(ui)).toContain('✓ Probe')
    expect(await texts(ui)).toContain('All: every lens, in list order.')
    await ui.unmount()
  })

  test('Path and Refine run their lens sets with the focus, and the Step Back row offers Base, Path, Refine, All', async ($, on) => {
    const { w, clock } = world(on)
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.input({ key: 'focus', text: 'the gate', kind: 'change' })
    await ui.press({ key: 'step-back-path' })
    await ui.input({ key: 'focus', text: 'the gate', kind: 'change' })
    await ui.press({ key: 'step-back-refine' })
    await clock.settle()
    expect(w.commands).toEqual([
      { command: 'step-back', args: 'goal foundations the gate' },
      { command: 'step-back', args: 'decisions clean overfit mechanics the gate' },
    ])
    expect(await ui.find({ key: 'ground-path' })).toBeUndefined()
    expect(await ui.find({ key: 'ground-refine' })).toBeUndefined()
    const drawn = await texts(ui)
    expect(drawn).toContain('Path: goal and foundations: is the direction right?')
    expect(drawn).toContain('Refine: decisions, clean, overfit, mechanics: sharpen the path.')
    await ui.unmount()
  })

  test('Ground leaves the Step Back focus alone', async ($, on) => {
    const { w, clock } = world(on)
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.input({ key: 'focus', text: 'the gate', kind: 'change' })
    await ui.press({ key: 'ground-base' })
    await clock.settle()
    expect(w.commands).toEqual([{ command: 'ground', args: '' }])
    expect((await ui.find({ key: 'step-back-run' }))?.text).toContain('Run 0')
    await ui.unmount()
  })

  test('per-question buttons run the id plus title; actions run their commands', async ($, on) => {
    const { w, clock } = world(on)
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'q-q3-explain' })
    await ui.press({ key: 'q-q3-sb' })
    await ui.press({ key: 'decide-row-question-me' })
    await ui.press({ key: 'decide-row-intake' })
    await ui.press({ key: 'actions-row-compact' })
    await clock.settle()
    expect(w.commands).toEqual([
      { command: 'explain', args: 'q3 Pane layout' }, { command: 'step-back', args: 'q3 Pane layout' },
      { command: 'question-me', args: '' }, { command: 'round-intake', args: '' }, { command: 'compact', args: '' },
    ])
    expect(w.prompts).toEqual([])
    expect(await ui.find({ key: 'actions-row-push' })).toBeUndefined()
    await ui.unmount()
  })

  const dep = (issue: string, on: string, type: string) => ({ issue_id: issue, depends_on_id: on, type })

  test('an item id opens its Decision and facts inline, reading first; a second press closes it', async ($, on) => {
    const { w, clock, session } = world(on)
    w.show.record = {
      description: '## Question\nWhich?\n\n## Decision\nFail closed (A).\n\n# Sub heading\nSecond line.\nThird.\nFourth.\nFifth line.\n\n## Rationale\nWhy.',
      dependencies: [
        dep('tstdl-x1', 'tstdl-p', 'parent-child'), dep('tstdl-x1', 'tstdl-r1', 'relates-to'), dep('tstdl-r1', 'tstdl-x1', 'relates-to'),
        dep('tstdl-o1', 'tstdl-x1', 'blocks'), dep('tstdl-x1', 'tstdl-b1', 'blocks'), dep('tstdl-c1', 'tstdl-x1', 'parent-child'),
      ],
      issue_type: 'decision', priority: 1, assignee: 'a1b2/c3', labels: ['topic:rpc', 'x'], comment_count: 2,
    }
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'item-tstdl-x1-show' })
    expect(await texts(ui)).toContain('reading…')
    await clock.settle()
    const drawn = await texts(ui)
    expect(drawn).not.toContain('reading…')
    for (const line of ['Fail closed (A).', 'Second line.', 'Third.', 'Fourth. …']) expect(drawn, line).toContain(line)
    for (const gone of ['Question', 'Which?', 'Sub heading', 'Fifth line', 'Rationale']) expect(drawn, gone).not.toContain(gone)
    const facts = 'decision · p1 · held by a1b2/c3 · topic:rpc, x · parent tstdl-p · blocked by 1 · blocks 1 · relates to 1 · children 1 · 2 comments · /console-item tstdl-x1'
    expect((await ui.findAll({ type: 'Text', text: facts })).map(one => one.props.color)).toEqual(['inactive'])
    expect(drawn).toContain('blocked by tstdl-b1 · blocks tstdl-o1 · relates to tstdl-r1 · parent tstdl-p · children tstdl-c1')  // the hover list
    expect(notices(session)).toEqual([])
    await ui.press({ key: 'item-tstdl-x1-show' })
    expect(await texts(ui)).not.toContain('Fail closed (A).')
    await ui.unmount()
  })

  test('a non-decision item shows its description from the start, headings dropped; unassigned, zero counts omitted', async ($, on) => {
    const { w, clock } = world(on)
    w.show.record = { description: '## Purpose\n\nDo the thing.\n# Notes\nMore.', dependencies: [], issue_type: 'task', priority: 2, assignee: null, labels: [], comment_count: 0 }
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'item-tstdl-x1-show' })
    await clock.settle()
    const drawn = await texts(ui)
    expect(drawn).toContain('Do the thing.')
    expect(drawn).toContain('More.')
    expect(drawn).not.toContain('Purpose')
    expect((await ui.findAll({ type: 'Text', text: 'task · p2 · /console-item tstdl-x1' })).length).toBe(1)
    expect(drawn).not.toContain('held by')
    await ui.unmount()
  })

  test('opening another item closes the first; a failed read shows its error in the error color', async ($, on) => {
    const { w, clock } = world(on, { items: [
      { id: 'tstdl-x1', type: 'decision', status: 'open', title: 'First', holder: null },
      { id: 'tstdl-x2', type: 'decision', status: 'open', title: 'Second', holder: null },
    ] })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'item-tstdl-x1-show' })
    await clock.settle()
    await ui.press({ key: 'item-tstdl-x2-show' })
    await clock.settle()
    const drawn = await texts(ui)
    expect(drawn).toContain('Keep it.')
    expect((drawn.match(/Keep it\./g) ?? []).length).toBe(1)
    w.show.exit = 1
    await ui.press({ key: 'item-tstdl-x1-show' })
    await clock.settle()
    expect((await ui.findAll({ type: 'Text', text: 'exit 1: no such item' })).map(one => one.props.color)).toEqual(['error'])
    w.show.exit = 0
    w.show.bad = true
    await ui.press({ key: 'item-tstdl-x2-show' })
    await clock.settle()
    expect((await ui.findAll({ type: 'Text', text: 'output is not JSON' })).map(one => one.props.color)).toEqual(['error'])
    await ui.unmount()
  })

  test('a worker row switches the view', async ($, on) => {
    const { w, clock } = world(on, { agents: [{ id: 'a1', description: 'Worker B', type: 'craft', status: 'running' }] })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'worker-a1' })
    expect(w.views).toEqual([{ agentId: 'a1' }])
    await ui.unmount()
  })

  // r7-q24: the decide row's Continue runs /console-continue; it stands out while the round waits on a pass nobody runs.
  describe('the Continue press', () => {
    const nudged = (w: { calls: { argv: string[] }[] }) => w.calls.filter(one => one.argv[3] === 'nudged').length
    const color = async ($: any) => {
      const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
      const drawn = await ui.find({ key: 'decide-row-continue' })
      const colors = (await ui.findAll({ type: 'Text', text: 'Continue' })).filter((one: { text: string }) => one.text === 'Continue').map((one: { props: { color?: string } }) => one.props.color)
      await ui.unmount()
      return drawn === undefined ? 'absent' : colors[0] ?? 'plain'
    }

    test('sits after Question Me and Intake while a round is open, names its command, and runs at once on every press while idle', async ($, on) => {
      const { w, clock } = world(on, { round: roundJson({ step: 'record', batch: null }) })
      await ready($, clock)
      const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
      const keys = (await ui.findAll({ type: 'Button' })).map((one: { key?: string }) => one.key).filter((key: string | undefined) => key?.startsWith('decide-row-'))
      expect(keys.slice(0, 3)).toEqual(['decide-row-question-me', 'decide-row-intake', 'decide-row-continue'])
      expect(await texts(ui)).toContain('/console-continue')
      await ui.press({ key: 'decide-row-continue' })
      await clock.settle()
      await $.turn.start({ text: w.prompts[0], turnId: 't1' } as never)  // the wake-up started its turn
      await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as never)
      await clock.settle()
      await ui.press({ key: 'decide-row-continue' })
      await clock.settle()
      expect(nudged(w)).toBe(2)
      expect(w.prompts).toHaveLength(2)
      expect(w.toasts).toEqual([])
      await ui.unmount()
    })

    test('pressed during a turn, it runs when the turn ends', async ($, on) => {
      const { w, clock, session } = world(on, { round: roundJson({ step: 'record', batch: null }) })
      await ready($, clock)
      await $.turn.start({ text: 'record', turnId: 't1' } as never)
      const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
      await ui.press({ key: 'decide-row-continue' })
      await ui.unmount()
      await clock.settle()
      expect(nudged(w)).toBe(0)
      expect(notices(session).filter(text => text.includes('/console-continue runs when this turn ends'))).toHaveLength(1)
      await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as never)
      await clock.settle()
      expect(nudged(w)).toBe(1)
      expect(w.prompts).toHaveLength(1)
    })

    // A press's `$` skips the console's own hooks (kit, 2.1.319): the console cannot swap its dialog from there, so the model opens it.
    test('pressed while idle with a batch out, it hands the batch to the model and never draws the stand-in', async ($, on) => {
      const { w, clock } = world(on, { round: roundJson({ step: 'ask', batch: { ...BATCH, notice: '' } }) })
      const drawn: unknown[] = []
      on('tool.call', { tool: 'AskUserQuestion' }, (_, e) => { drawn.push(e); return { deny: 'closed' } as never })
      await ready($, clock)
      await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't0', reason: 'answer' } as never)
      await clock.settle()
      drawn.length = 0
      await $.turn.start({ text: w.prompts[0] ?? '', turnId: 't1' } as never)
      await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as never)
      await clock.settle()
      const before = w.prompts.length
      const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
      await ui.press({ key: 'decide-row-continue' })
      await clock.settle()
      await ui.unmount()
      expect(drawn).toEqual([])
      expect(w.prompts.slice(before)).toEqual([openDialogText(BATCH.marker)])
      expect(w.calls.filter(one => one.argv[3] === 'nudged').map(one => JSON.parse(one.stdin ?? '{}'))).toEqual([{ batch: BATCH.marker }])
    })

    test('is absent with no round open', async ($, on) => {
      const { clock } = world(on, { round: NO_ROUND })
      await ready($, clock)
      expect(await color($)).toBe('absent')
    })

    test('takes the suggestion color only while idle with a pending pass that has no queued or started run', async ($, on) => {
      const { w, clock } = world(on, { round: roundJson({ pending: { id: 'p7', command: 'ground', args: '' } }) })
      await ready($, clock)
      expect(await color($)).toBe('suggestion')  // idle, and nothing runs the pending pass
      await $.turn.start({ text: 'go on', turnId: 't1' } as never)
      expect(await color($)).toBe('plain')  // a turn runs
      await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as never)
      await clock.settle()
      expect(await color($)).toBe('plain')  // idle, the pass queued
      await $.skill.prompt({ skill: 'ground', text: 'Ground…' } as never)
      expect(await color($)).toBe('plain')  // started
      await $.turn.complete({ answer: '', durationMs: 1, isAborted: true, turnId: 't2', reason: 'aborted' } as never)
      await clock.settle()
      expect(await color($)).toBe('suggestion')  // Esc stopped it
      w.round = roundJson()
      await $.tool.call({ tool: 'mcp__console__protocol', args: ['show', '--json'] } as never)
      expect(await color($)).toBe('plain')  // no pending pass
    })
  })
})

describe('band', () => {
  test('shows the round and the Base passes only while a round is open', async ($, on) => {
    const { w, clock } = world(on)
    await ready($, clock)
    const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await texts(ui)).toContain('Round r4')
    await ui.press({ key: 'band-ground' })
    await clock.settle()
    expect(w.commands).toEqual([{ command: 'ground', args: '' }])
    await ui.unmount()
  })

  const closed = (next: unknown) => roundJson({ round: null, step: null, check: null, pending: null, batch: null, questions: [], next })

  test('after a close with records to release the band offers Release Round in the suggestion color', async ($, on) => {
    const { w, clock } = world(on, { round: closed({ release: { count: 3 } }) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await texts(ui)).toContain('3 records decided ·')
    expect(await ui.find({ key: 'band-ground' })).toBeUndefined()
    expect((await ui.findAll({ type: 'Text', text: 'Release Round' })).filter(one => one.text === 'Release Round').map(one => one.props.color)).toEqual(['suggestion'])
    await ui.press({ key: 'band-release' })
    await clock.settle()
    expect(w.commands).toEqual([{ command: 'release-round', args: '' }])
    expect(JSON.parse(w.calls.find(one => one.argv[3] === 'pass')?.stdin ?? '{}')).toEqual({ command: 'release-round', args: '', pending: null })
    await ui.unmount()
    const pane = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect((await pane.findAll({ type: 'Text', text: 'Release Round' })).filter(one => one.text === 'Release Round').map(one => one.props.color)).toEqual(['suggestion'])
    await pane.unmount()
  })

  test('the band and the pane show the count of decided records the session holds: one Release Round takes all of them', async ($, on) => {
    const { clock } = world(on, { round: closed({ release: { count: 5 } }) })
    await ready($, clock)
    const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await texts(band)).toContain('5 records decided ·')
    await band.unmount()
    const pane = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect((await pane.findAll({ type: 'Text', text: 'Release Round · 5 records decided' })).length).toBeGreaterThan(0)
    await pane.unmount()
  })

  test('the pane keeps the Release Round label plain while nothing waits for release', async ($, on) => {
    const { clock } = world(on)
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await ui.findAll({ type: 'Text', text: 'Release Round' })).toEqual([])
    expect((await ui.find({ key: 'actions-row-release' }))?.text).toBe('Release Round')
    await ui.unmount()
  })

  test('the band shows an open release run like a round, and waits on its dialog', async ($, on) => {
    const release = { protocol: 'release', round: 'r5', step: 'ask', title: "r4's records", check: null, pending: null, questions: [], next: null }
    const { w, clock } = world(on, { round: roundJson({ ...release, batch: null }) })
    await ready($, clock)
    let ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await texts(ui)).toContain("Release r5 · r4's records · approval to ask again")
    expect(await texts(ui)).not.toContain('waiting on your answer')
    await ui.unmount()
    w.round = roundJson({ ...release, questions: [{ id: 'q9', board: null, text: 'Release r4\'s 3 records?', title: 'Release', kind: 'confirm-own-rulings', status: 'asked', waitsOn: [], overlaps: [], answer: null }] })
    await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
    await clock.settle()
    ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await texts(ui)).toContain("Release r5 · r4's records · asking your approval")
    expect(await texts(ui)).toContain('waiting on your answer')
    await ui.unmount()
  })

  describe('no Ask button', () => {
    const asking = (notice = 'Engine name\nProblem: which name.') => roundJson({ step: 'ask', batch: { ...BATCH, notice } })
    const complete = (extra: Record<string, unknown> = {}) => ({ answer: '', durationMs: 1, isAborted: false, turnId: 't', reason: 'answer', ...extra }) as never

    test('neither the band nor the Actions offer Ask, before or after the print: the dialog opens by itself (r29-q138)', async ($, on) => {
      const { w, clock } = world(on, { round: asking() })
      await ready($, clock)
      for (const printed of [false, true]) {
        if (printed) {
          await $.turn.complete(complete())
          await clock.settle()
          expect(w.prompts).toEqual([openDialogText(BATCH.marker)])
        }
        const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
        expect(await band.find({ key: 'band-ask' })).toBeUndefined()
        expect(await texts(band)).not.toMatch(/\bAsk\b/)
        await band.unmount()
        const pane = await $.ui.mount({ ...PANE, surface: 'terminal' })
        expect(await pane.find({ key: 'actions-row-ask' })).toBeUndefined()
        expect(await texts(pane)).not.toMatch(/press Ask|reply ask|go-ahead/)
        await pane.unmount()
      }
    })
  })

  describe('roles', () => {
    const lead = { session: SESSION, role: 'lead', actor: '617adf08', tool: 'claude' }
    const solo = { ...lead, role: 'solo' }
    const autopilot = { ...lead, role: 'autopilot' }
    const proposed = { rounds: [{ ids: [], title: 'Cache questions', summary: 'one store', estimate: { questions: 3, unblocks: 8 }, why: 'same module', fresh: false }], release: { count: 2 } }
    const closedWith = (next: unknown) => roundJson({ round: null, step: null, check: null, pending: null, batch: null, questions: [], next })

    test("while autopilot a Solo button is in the band and the Actions; a press runs /role solo as the person's press", async ($, on) => {
      const { w, clock } = world(on, { role: autopilot })
      await ready($, clock)
      const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
      expect((await band.find({ key: 'band-role-solo' }))?.text).toContain('Solo')
      expect(await texts(band)).not.toContain('Autopilot ')
      await band.press({ key: 'band-role-solo' })
      await clock.settle()
      expect(w.commands).toEqual([{ command: 'role', args: 'solo' }])
      expect(w.prompts).toEqual([])
      await band.unmount()
      const pane = await $.ui.mount({ ...PANE, surface: 'terminal' })
      expect((await pane.find({ key: 'actions-row-role-solo' }))?.text).toContain('Solo')
      expect(await pane.find({ key: 'actions-row-role-autopilot' })).toBeUndefined()
      expect(await texts(pane)).toContain('Round r4')  // the round block stays: autopilot is a round role
      await pane.unmount()
    })

    describe('worker selects in the session rows', () => {
      const row = (session: string, role: string, workers: { active: number; cap: number } | null, state = 'active') =>
        ({ session, role, actor: session.slice(-8), tool: 'claude', pulls: [], holds: 0, workers, state, idleSince: null, claimable: 0 })
      const set = (w: { calls: { argv: string[] }[] }) => w.calls.filter(one => one.argv.includes('set-workers')).map(one => one.argv.slice(2))

      test('a pick on another session sets that session, without a model turn', async ($, on) => {
        const { w, clock } = world(on, { role: lead, sessions: [row(SESSION, 'lead', { active: 0, cap: 3 }), row('other-agent-1', 'agent', { active: 1, cap: 3 })] })
        await ready($, clock)
        const pane = await $.ui.mount({ ...PANE, surface: 'terminal' })
        await pane.select({ key: 'workers-other-agent-1', value: '5' })
        await clock.settle()
        expect(set(w)).toEqual([['set-workers', 'other-agent-1', '--workers', '5']])
        expect(w.prompts).toEqual([])
        expect(w.commands).toEqual([])
        await pane.unmount()
      })

      test('a failed set gives a toast', async ($, on) => {
        const { w, clock } = world(on, { role: solo, activateError: 'nope', sessions: [row(SESSION, 'solo', { active: 0, cap: 3 })] })
        await ready($, clock)
        const pane = await $.ui.mount({ ...PANE, surface: 'terminal' })
        await pane.select({ key: `workers-${SESSION}`, value: '2' })
        await clock.settle()
        expect(w.toasts.join(' ')).toContain('nope')
        await pane.unmount()
      })

      test('leads, gone sessions and sessions without a count show text', async ($, on) => {
        const { clock } = world(on, { role: lead, sessions: [row(SESSION, 'lead', { active: 1, cap: 3 }), row('gone-agent-1', 'agent', { active: 0, cap: 3 }, 'gone'), row('none-agent-1', 'agent', null)] })
        await ready($, clock)
        const pane = await $.ui.mount({ ...PANE, surface: 'terminal' })
        expect(await pane.find({ key: `workers-${SESSION}` })).toBeUndefined()
        expect(await pane.find({ key: 'workers-gone-agent-1' })).toBeUndefined()
        expect(await pane.find({ key: 'workers-none-agent-1' })).toBeUndefined()
        expect(await texts(pane)).toContain('workers 1/3')
        await pane.unmount()
      })
    })

    test('the band has its Solo button with no round open too', async ($, on) => {
      const { clock } = world(on, { role: autopilot, round: NO_ROUND })
      await ready($, clock)
      const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
      expect(await band.find({ key: 'band-role-solo' })).toBeDefined()
      expect(await texts(band)).toContain('Autopilot · away')
      await band.unmount()
    })

    test('while autopilot the pane hides the proposals, Start and Release Round; solo shows them', async ($, on) => {
      const { clock } = world(on, { role: autopilot, round: closedWith(proposed) })
      await ready($, clock)
      let pane = await $.ui.mount({ ...PANE, surface: 'terminal' })
      expect(await pane.find({ key: 'sg-round-0-start' })).toBeUndefined()
      expect(await pane.find({ key: 'sg-release-start' })).toBeUndefined()
      expect(await pane.find({ key: 'actions-row-release' })).toBeUndefined()
      expect(await texts(pane)).not.toContain('the next step, proposed')
      await pane.unmount()
      const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
      expect(await band.find({ key: 'band-start' })).toBeUndefined()
      expect(await band.find({ key: 'band-release' })).toBeUndefined()
      await band.unmount()
    })

    test('while solo an Autopilot button is in the Actions only; a press runs /role autopilot', async ($, on) => {
      const { w, clock } = world(on, { role: solo, round: closedWith(proposed) })
      await ready($, clock)
      const pane = await $.ui.mount({ ...PANE, surface: 'terminal' })
      expect(await texts(pane)).toContain('the next step, proposed')
      expect(await pane.find({ key: 'sg-round-0-start' })).toBeDefined()
      expect(await pane.find({ key: 'actions-row-release' })).toBeDefined()
      expect((await pane.find({ key: 'actions-row-role-autopilot' }))?.text).toContain('Autopilot')
      expect(await pane.find({ key: 'actions-row-role-solo' })).toBeUndefined()
      await pane.press({ key: 'actions-row-role-autopilot' })
      await clock.settle()
      expect(w.commands).toEqual([{ command: 'role', args: 'autopilot' }])
      await pane.unmount()
      const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
      expect(await band.find({ key: 'band-role-autopilot' })).toBeUndefined()
      expect(await band.find({ key: 'band-role-solo' })).toBeUndefined()
      await band.unmount()
    })

    for (const role of ['lead', 'agent']) {
      test(`a ${role} session has no role button`, async ($, on) => {
        const { clock } = world(on, { role: { ...lead, role } })
        on('ui.render', ($, e) => {
          const { Text } = $.ui.resolve(e) as any
          return <Text>engine</Text>
        })
        await ready($, clock)
        const pane = await $.ui.mount({ ...PANE, surface: 'terminal' })
        expect(await pane.find({ key: 'actions-row-role-solo' })).toBeUndefined()
        expect(await pane.find({ key: 'actions-row-role-autopilot' })).toBeUndefined()
        await pane.unmount()
        const band = await $.ui.mount({ ...BAND, surface: 'terminal' })
        expect(await band.find({ key: 'band-role-solo' })).toBeUndefined()
        await band.unmount()
      })
    }

    test('a parked question shows in the round block', async ($, on) => {
      const parked = { id: 'q7', board: 'tstdl-p1', text: 'Parked?', title: 'Parked one', kind: 'decision', status: 'parked', waitsOn: [], overlaps: [], answer: null }
      const { clock } = world(on, { role: autopilot, round: roundJson({ questions: [parked] }) })
      await ready($, clock)
      const pane = await $.ui.mount({ ...PANE, surface: 'terminal' })
      expect(await texts(pane)).toContain('Parked one')
      await pane.unmount()
    })
  })

  test('the band stays away without a release next', async ($, on) => {
    const { clock } = world(on, { round: closed(null) })
    on('ui.render', ($, e) => {
      const { Text } = $.ui.resolve(e) as any
      return <Text>engine</Text>
    })
    await ready($, clock)
    const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await texts(ui)).toContain('engine')
    await ui.unmount()
  })

  test('draws nothing of its own without an open round', async ($, on) => {
    const { clock } = world(on, { round: roundJson({ round: null, step: null, check: null, batch: null, questions: [] }) })
    on('ui.render', ($, e) => {
      const { Text } = $.ui.resolve(e) as any
      return <Text>engine</Text>
    })
    await ready($, clock)
    const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await texts(ui)).toContain('engine')
    await ui.unmount()
  })
})

describe('/console', () => {
  const run = ($: any, origin: object, columns: number) =>
    $.command.run({ command: 'console', args: '', origin, presentation: { isFullscreen: true, columns } })

  test('from the terminal it opens the pane', async ($, on) => {
    const { w, clock } = world(on)
    await ready($, clock)
    w.opened.length = 0
    const ran = await run($, { kind: 'composer' }, 160)
    expect(ran.text).toBe('Console opened.')
    expect(w.opened).toEqual(['console'])
  })

  test('too narrow for the layout, or from the bridge, it prints the board and round', async ($, on) => {
    const { w, clock } = world(on)
    await ready($, clock)
    w.opened.length = 0
    for (const [origin, columns] of [[{ kind: 'composer' }, 50], [{ kind: 'bridge' }, 160]] as const) {
      const ran = await run($, origin, columns)
      expect(ran.text).toContain('Board · lead 617adf08')
      expect(ran.text).toContain('for you 3')
      expect(ran.text).toContain('Round r4 · checking 2/3')
      expect(ran.text).toContain('q2  Engine name · overlaps tstdl-ab12')
    }
    expect(w.opened).toEqual([])
  })

  test('/console-item prints the summary', async ($, on) => {
    const { clock } = world(on)
    await ready($, clock)
    const ran = await $.command.run({ command: 'console-item', args: 'tstdl-x1', origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } })
    expect(ran.text).toContain('tstdl-x1: Which engine name?')
  })
})

describe('notification', () => {
  test('an idle agent with claimable work notifies once per idle episode', async ($, on) => {
    const idle = { session: 's-2', role: 'agent', actor: 'eef8ae5c', pulls: ['implement'], holds: 0, workers: { active: 0, cap: 6 }, state: 'idle', idleSince: '2026-10-31T10:00:00Z', claimable: 3 }
    const { w, clock } = world(on, { sessions: [idle] })
    await ready($, clock)
    await clock.advance(62_000)  // a refresh tick plus the claim's settle time
    expect(w.notified).toEqual(['agent eef8ae5c is idle with 3 claimable items'])
    w.sessions = [{ ...idle, idleSince: '2026-10-31T11:00:00Z' }, { ...idle, session: 's-3', role: 'lead', actor: 'lead0002' }]
    await clock.advance(62_000)
    expect(w.notified).toHaveLength(2)  // the new episode only: an idle lead waits on the user
    // Another console's later claim on the same marker wins: this one stays quiet.
    w.sessions = [{ ...idle, idleSince: '2026-10-31T12:00:00Z' }]
    await clock.advance(56_500)  // the next tick (at 180 s) has written this console's claim and waits
    w.files.set(`${HOME}/.local/state/agent-sessions/console-notified/s-2`, '2026-10-31T12:00:00Z s-other\n')
    await clock.advance(2_000)
    expect(w.notified).toHaveLength(2)
  })
})

describe('accept notification', () => {
  const MARKERS = `${HOME}/.local/state/agent-sessions/console-accept-notified`
  const start = async ($: any, on: any, crs: unknown[], init: Parameters<typeof world>[1] = {}) => {
    const made = world(on, { round: NO_ROUND, crs, ...init })
    await ready($, made.clock)
    return made
  }

  test('a request that reaches to-accept after the console started notifies once; those waiting at start do not', async ($, on) => {
    const { w, clock } = await start($, on, [cr({ id: 'p-old', title: 'Old one' })])
    await clock.advance(62_000)
    expect(w.notified).toEqual([])
    w.crs = [cr({ id: 'p-old', title: 'Old one' }), cr({ id: 'p-new', title: 'New one' })]
    await clock.advance(62_000)
    expect(w.notified).toEqual(['p-new is ready to accept: New one'])
    await clock.advance(62_000)
    expect(w.notified).toHaveLength(1)
  })

  test('a design checkpoint says so; one in agent review is not yours yet', async ($, on) => {
    const { w, clock } = await start($, on, [])
    w.crs = [cr({ id: 'p-d', title: 'Design Y', checkpoint: 'user', tip: null }), cr({ id: 'p-r', status: 'in_review' })]
    await clock.advance(62_000)
    expect(w.notified).toEqual(['p-d is ready to accept (design): Design Y'])
  })

  test('returned and then waiting again, it notifies again', async ($, on) => {
    const { w, clock } = await start($, on, [])
    w.crs = [cr({ id: 'p-cr1', title: 'X' })]
    await clock.advance(62_000)
    w.crs = [cr({ id: 'p-cr1', title: 'X', status: 'open' })]
    await clock.advance(62_000)
    w.crs = [cr({ id: 'p-cr1', title: 'X' })]
    await clock.advance(62_000)
    expect(w.notified).toHaveLength(2)
  })

  test('another console\'s later claim on the same marker wins: this one stays quiet', async ($, on) => {
    const { w, clock } = await start($, on, [])
    w.crs = [cr({ id: 'p-cr1', title: 'X' })]
    await clock.advance(58_500)  // the tick at 60 s has written this console's claim and waits
    await clock.advance(1_000)
    w.files.set(`${MARKERS}/p-cr1`, 'accept s-other\n')
    await clock.advance(3_000)
    expect(w.notified).toEqual([])
  })

  test('markers of other projects\' requests survive; a request still listed but no longer waiting loses its marker', async ($, on) => {
    const { w, clock } = await start($, on, [cr({ id: 'p-cr1' })])
    w.files.set(`${MARKERS}/other-cr9`, 'accept s-other\n')
    w.files.set(`${MARKERS}/p-cr1`, 'accept s-1\n')
    await clock.advance(62_000)
    expect(w.files.has(`${MARKERS}/other-cr9`)).toBe(true)
    expect(w.files.has(`${MARKERS}/p-cr1`)).toBe(true)
    w.crs = [cr({ id: 'p-cr1', status: 'open' })]
    await clock.advance(62_000)
    expect(w.files.has(`${MARKERS}/p-cr1`)).toBe(false)
    expect(w.files.has(`${MARKERS}/other-cr9`)).toBe(true)
  })

  test('an agent session cannot accept: no notification', async ($, on) => {
    const { w, clock } = await start($, on, [], { role: { session: SESSION, role: 'agent', actor: 'eef8ae5c', tool: 'claude' } })
    w.crs = [cr({ id: 'p-cr1' })]
    await clock.advance(62_000)
    expect(w.notified).toEqual([])
  })
})

describe('board block', () => {
  const item = (n: number) => ({ id: `tstdl-u${n}`, type: 'task', status: 'open', title: `Your task ${n}`, holder: 'user' })

  test('for you: the ready items under the counts, 3 shown, the rest behind +N more; an id opens its summary', async ($, on) => {
    const { w, clock } = world(on, { forYou: [1, 2, 3, 4, 5].map(item) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const drawn = await texts(ui)
    for (const n of [1, 2, 3]) expect(drawn).toContain(`Your task ${n}`)
    expect(drawn).not.toContain('Your task 4')
    expect(drawn).toContain('+2 more ▸')
    expect(drawn.indexOf('to review')).toBeLessThan(drawn.indexOf('Your task 1'))
    expect(drawn.indexOf('Your task 1')).toBeLessThan(drawn.indexOf('holds 2'))
    expect((await ui.find({ key: 'foryou-tstdl-u1' }))?.text).toMatch(/tstdl-u1\s*task\s*Your task 1/)
    await ui.press({ key: 'forYou-toggle' })
    expect(await texts(ui)).toContain('Your task 5')
    await ui.press({ key: 'foryou-tstdl-u1-show' })
    await clock.settle()
    expect(w.calls.some(one => one.argv[1] === 'show' && one.argv[2] === 'tstdl-u1')).toBe(true)
    await ui.unmount()
  })

  test('nothing for you: no list', async ($, on) => {
    const { clock } = world(on)
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await ui.find({ key: 'board-foryou' })).toBeUndefined()
    await ui.unmount()
  })

  test("this session's holds sit under the sessions table, labelled", async ($, on) => {
    const { clock } = world(on)
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const drawn = await texts(ui)
    expect(drawn.indexOf('holds 2')).toBeLessThan(drawn.indexOf('this session holds'))
    expect(drawn.indexOf('this session holds')).toBeLessThan(drawn.indexOf('tstdl-x1'))
    await ui.unmount()
  })

  test('/console text: the for-you lines under the counts, the holds labelled under the sessions', async ($, on) => {
    const { clock } = world(on, { forYou: [item(1)] })
    await ready($, clock)
    const ran = await $.command.run({ command: 'console', args: '', origin: { kind: 'bridge' }, presentation: { isFullscreen: true, columns: 160 } })
    const text = ran.text ?? ''
    expect(text).toContain('  for you: tstdl-u1  task  Your task 1')
    expect(text.indexOf('for you: tstdl-u1')).toBeLessThan(text.indexOf('holds 2'))
    expect(text).toContain('  this session holds:\n    tstdl-x1  in_progress  Which engine name?')
    expect(text.indexOf('holds 2')).toBeLessThan(text.indexOf('this session holds'))
  })
})

describe('header counts', () => {
  test('split by who acts: you, then the agents; a zero count is dim', async ($, on) => {
    const { clock } = world(on)
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    type Part = { props?: { dimColor?: boolean }; children: unknown[] }
    // Texts carry no key in the tree: a group's counts box holds one Text per count.
    const group = async (key: string) => ((await ui.find({ key: `${key}-counts` }))?.children ?? []) as Part[]
    const labels = (parts: Part[]) => parts.map(one => one.children[0])
    const you = await group('board-counts-you')
    const agents = await group('board-counts-agents')
    expect((await ui.find({ key: 'board-counts-you-label' }))?.text).toBe('you')
    expect(labels(you)).toEqual(['for you', 'to accept', 'to ratify', 'decided', 'questions'])
    expect((await ui.find({ key: 'board-counts-agents-label' }))?.text).toBe('agents')
    expect(labels(agents)).toEqual(['to plan', 'to design', 'to implement', 'to review'])
    expect(you.map(one => one.props?.dimColor === true)).toEqual([false, false, false, true, false])  // only decided is zero
    expect(agents.map(one => one.props?.dimColor === true)).toEqual([true, true, true, true])  // the agents' group is dim whatever it holds
    await ui.unmount()
  })

  test('no board: a dim notice beside the title and nothing else from the board', async ($, on) => {
    const { clock } = world(on, { noBoard: true, sessions: [], items: [] })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect((await ui.find({ key: 'board-banner' }))?.text).toContain('no board')
    expect(await ui.find({ key: 'board-counts' })).toBeUndefined()
    const drawn = await texts(ui)
    for (const part of ['to plan', 'to accept', 'reading the board']) expect(drawn, part).not.toContain(part)
    expect(consoleText({ session: 's', role: 'lead', actor: 'a', tool: 'claude' }, parseBoardConsole({ noBoard: true }) as unknown as ConsoleBoard, null, false, [])).toBe('Board · lead a · no board')
    await ui.unmount()
  })

  test('a group is one line each; its counts wrap under the first count, not under the label', async ($, on) => {
    const { clock } = world(on)
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal', props: { ...PANE_PROPS, bodyColumns: 40 } })
    expect((await ui.find({ key: 'board-counts' }))?.props).toMatchObject({ flexDirection: 'column' })
    for (const who of ['you', 'agents']) {
      expect((await ui.find({ key: `board-counts-${who}` }))?.props.flexWrap, who).toBeUndefined()
      expect((await ui.find({ key: `board-counts-${who}-label` }))?.props, who).toMatchObject({ width: 8, flexShrink: 0 })
      expect((await ui.find({ key: `board-counts-${who}-counts` }))?.props, who).toMatchObject({ flexWrap: 'wrap', flexShrink: 1 })
    }
    await ui.unmount()
  })
})

describe('question row', () => {
  test('explain and step back sit in a group that keeps its width, with a margin and a fixed-width bullet; the title is what shrinks', async ($, on) => {
    const { clock } = world(on)
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal', props: { ...PANE_PROPS, bodyColumns: 40 } })
    expect((await ui.find({ key: 'q-q2-actions' }))?.props).toMatchObject({ flexShrink: 0, marginLeft: 2 })
    expect((await ui.find({ key: 'q-q2-bullet' }))?.props).toMatchObject({ width: 3, flexShrink: 0 })
    expect(JSON.stringify((await ui.find({ key: 'q-q2-actions' }))?.children)).toMatch(/q-q2-explain.*q-q2-bullet.*q-q2-sb/)
    expect((await ui.find({ key: 'q-q2-body' }))?.props).toMatchObject({ flexShrink: 1, minWidth: 0 })
    expect((await ui.find({ key: 'q-q2-text-box' }))?.props).toMatchObject({ flexShrink: 1 })
    expect((await ui.find({ key: 'q-q2-marks' }))?.props).toMatchObject({ flexShrink: 0 })
    await ui.unmount()
  })
})

describe('long lists', () => {
  const q = (n: number, status: string, extra: Record<string, unknown> = {}) =>
    ({ id: `q${n}`, board: null, text: `Q${n}?`, title: `Title ${n}`, kind: 'decision', status, waitsOn: [], overlaps: [], answer: status === 'answered' ? 'A' : null, answeredAt: null, ...extra })

  test('the question cap keeps every asked one and the 2 latest answered; upcoming ones fill the rest', async ($, on) => {
    const questions = [
      ...[1, 2, 3, 4].map(n => q(n, 'answered', { answeredAt: `2026-10-31T0${n}:00:00Z` })),
      q(5, 'asked'), q(6, 'asked'),
      ...[7, 8, 9, 10, 11, 12, 13, 14].map(n => q(n, 'ready')),
    ]
    const { clock } = world(on, { round: roundJson({ questions }) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const shown = async () => (await texts(ui)).match(/Title \d+/g)?.filter((t, i, all) => all.indexOf(t) === i) ?? []
    expect(await shown()).toEqual(['Title 3', 'Title 4', 'Title 5', 'Title 6', 'Title 7', 'Title 8', 'Title 9', 'Title 10', 'Title 11', 'Title 12'])
    expect(await texts(ui)).toContain('+4 more ▸')
    await ui.press({ key: 'questions-toggle' })
    expect((await shown()).length).toBe(14)
  })

  test('overlaps open inline with clickable ids; an id opens its item under the question', async ($, on) => {
    const overlaps = [{ id: 'tstdl-a', title: 'Alpha', outcome: null }, { id: 'tstdl-b', title: 'Beta', outcome: null }]
    const { clock, session } = world(on, { round: roundJson({ questions: [q(1, 'draft', { overlaps })] }) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await texts(ui)).toContain('2 overlaps')
    await ui.press({ key: 'q-q1-ov' })
    const open = await texts(ui)
    expect(open).toContain('Alpha')
    expect(open).toContain('Beta')
    await ui.press({ key: 'ov-q1-tstdl-b-open' })
    await clock.settle()
    expect(await texts(ui)).toContain('Keep it.')
    expect(notices(session)).toEqual([])
    await ui.press({ key: 'q-q1-ov' })
    await ui.press({ key: 'q-q1-ov' })
    expect(await texts(ui)).not.toContain('Alpha')
  })

  test('a rule question shows a settles mark; its row opens the settled ids, a board id opens its item', async ($, on) => {
    const { clock, session } = world(on, { round: roundJson({ questions: [q(1, 'draft', { settles: ['tstdl-a', 'pt2'] }), q(2, 'draft')] }) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const drawn = await texts(ui)
    expect(drawn).toContain('settles 2')
    expect(drawn.match(/settles \d/g)).toHaveLength(1)
    await ui.press({ key: 'q-q1-st' })
    const open = await texts(ui)
    expect(open).toContain('tstdl-a')
    expect(open).toContain('pt2')
    await ui.press({ key: 'st-q1-tstdl-a-open' })
    await clock.settle()
    expect(await texts(ui)).toContain('Keep it.')
    expect(notices(session)).toEqual([])
    await ui.press({ key: 'q-q1-st' })
    await ui.press({ key: 'q-q1-st' })
    expect(await texts(ui)).not.toContain('pt2')
  })

  test('board lists cap at 10 rows, active sessions first', async ($, on) => {
    const items = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map(n => ({ id: `tstdl-i${n}`, type: 'decision', status: 'open', title: `Item ${n}`, holder: '617adf08' }))
    const session = (n: number, state: string) => ({ session: `s-${n}`, role: 'agent', actor: `actor00${n}`, pulls: [], holds: 0, workers: null, state, idleSince: null, claimable: 0 })
    const sessions = [session(1, 'gone'), ...[2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map(n => session(n, 'active'))]
    const { clock } = world(on, { items, sessions })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const drawn = await texts(ui)
    expect(drawn).toContain('Item 10')
    expect(drawn).not.toContain('Item 11')
    expect(drawn).toContain('+2 more ▸')
    expect(drawn).not.toContain('actor001\n')  // gone sorts last, past the cap
    await ui.press({ key: 'items-toggle' })
    expect(await texts(ui)).toContain('Item 12')
  })

  test('the role column shows autopilot as auto, so the row keeps to one line', async ($, on) => {
    const row = { session: 's-a', role: 'autopilot', actor: 'auto0001', tool: 'claude', pulls: [], holds: 0, workers: null, state: 'active', idleSince: null, claimable: 0 }
    const { clock } = world(on, { sessions: [row] })
    await ready($, clock)
    const drawn = await texts(await $.ui.mount({ ...PANE, surface: 'terminal' }))
    expect(drawn).toContain('auto')
    expect(drawn).not.toContain('autopilot')
  })

  test('stale sessions become one stale-holds line; pulls read as fixed-position initials', async ($, on) => {
    const session = (actor: string, state: string, holds: number) =>
      ({ session: `s-${actor}`, role: 'agent', actor, tool: 'codex', pulls: ['plan', 'design', 'implement', 'review'], holds, workers: null, state, idleSince: null, claimable: 0 })
    const sessions = [session('live0001', 'active', 1), session('dead0001', '', 2), session('busy0001', '', 1)]
    const held = [
      { id: 'tstdl-l1', holder: 'live0001', mark: null },
      { id: 'tstdl-d1', holder: 'dead0001/w1', mark: 'idle' }, { id: 'tstdl-d2', holder: 'dead0001', mark: 'idle' },
      { id: 'tstdl-b1', holder: 'busy0001', mark: null },
    ]
    const { clock } = world(on, { sessions, held })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const drawn = await texts(ui)
    expect(drawn).toContain('stale holds: ')
    expect(drawn).toContain('tstdl-d1')
    expect(drawn).not.toContain('tstdl-b1')  // unknown state with a live hold stays a session row
    expect(drawn).toContain('busy0001')
    expect(drawn).toContain('p d i r')
    expect(drawn).toContain('codex')
    expect(drawn).toContain('Controls')
  })

  test('pull initials keep their positions', () => {
    expect(pullsText(['plan', 'design', 'implement', 'review'])).toBe('p d i r')
    expect(pullsText(['implement', 'design'])).toBe('· d i ·')
    expect(pullsText([])).toBe('')
  })

  test('finished workers leave the pane', async ($, on) => {
    const { clock } = world(on, { agents: [
      { id: 'a1', description: 'Worker live', type: 'craft', status: 'running' },
      { id: 'a2', description: 'Worker done', type: 'craft', status: 'completed' },
    ] })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const drawn = await texts(ui)
    expect(drawn).toContain('Worker live')
    expect(drawn).not.toContain('Worker done')
  })

  test('the round words name what each step works on', () => {
    const progress = { items: 4, points: 1, classified: 2, candidates: 3, selected: ['tstdl-a', 'tstdl-b', 'pt1', 'pt2'] }
    const at = (step: string) => roundWords({ ...roundJson({ step, pending: null, batch: null, questions: [], progress }), check: null, counts: null, note: null } as never)
    expect(at('collect')).toBe('collecting · 2/5 classified')
    expect(at('select')).toBe('selecting from 3 candidates')
    expect(at('stage')).toBe('staging questions for tstdl-a, tstdl-b, pt1 +1')
  })

  test('the round words name the pre-pass and its subject', () => {
    const at = (subject: string | null) => roundWords({ ...roundJson({ step: 'prepass', subject, pending: { id: 'p1', command: 'step-back', args: 'goal decisions; pre-pass' }, batch: null, questions: [] }), check: null, counts: null, note: null } as never)
    expect(at(null)).toBe('pre-pass over the points · next /step-back')
    expect(at('Cache design')).toBe('pre-pass on Cache design · next /step-back')
  })

  test('the round banner carries its title, the summary sits under it, a question shows its full text on hover', async ($, on) => {
    const { clock } = world(on, { round: roundJson({ title: 'Queue retries', summary: 'Which limits retries use, and when they stop.' }) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const drawn = await texts(ui)
    expect(drawn).toContain('Queue retries')
    expect(drawn).toContain('Which limits retries use, and when they stop.')
    expect(drawn).toContain('q3: Which pane layout?')
  })

  test('the pending pass is marked next in the controls', async ($, on) => {
    const { clock } = world(on, { round: roundJson({ pending: { id: 'p7', command: 'ground', args: '' } }) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const drawn = (await texts(ui)).split('\n')
    expect(drawn.filter(line => line.includes('◂ next'))).toHaveLength(1)
  })

  test('a refine pass with lens arguments is marked next like any pending pass', async ($, on) => {
    const { clock } = world(on, { round: roundJson({ pending: { id: 'p8', command: 'step-back', args: 'decisions clean overfit mechanics' } }) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect((await texts(ui)).split('\n').filter(line => line.includes('◂ next'))).toHaveLength(1)
    expect(await texts(ui)).toContain('next /step-back')
  })

  test('the pending pass reads running once the console started it', async ($, on) => {
    const { clock } = world(on, { round: roundJson({ pending: { id: 'p7', command: 'ground', args: '' } }) })
    await ready($, clock)
    await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't', reason: 'answer' } as never)
    await $.skill.prompt({ skill: 'ground', text: 'Ground…' } as never)
    await clock.settle()
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await texts(ui)).toContain('◂ running')
  })

  test('the round shows its recent log, refusals in warning color', async ($, on) => {
    const log = [{ at: '13:05', text: 'step-back: 4 changes' }, { at: '13:06', text: 'refused step: a ground pass that changes nothing' }]
    const { clock } = world(on, { round: roundJson({ log }) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const drawn = await texts(ui)
    expect(drawn.indexOf('13:06')).toBeGreaterThan(drawn.indexOf('Actions'))  // below the controls
    expect(drawn.indexOf('13:06')).toBeLessThan(drawn.indexOf('13:05'))  // newest first
  })

  test('the log shows the last 10 lines; +N more opens the whole round', async ($, on) => {
    const log = Array.from({ length: 13 }, (_, i) => ({ at: '13:00', text: `log line ${i + 1}` }))
    const { clock } = world(on, { round: roundJson({ log }) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    let drawn = await texts(ui)
    expect(drawn).toContain('log line 13')
    expect(drawn).toContain('log line 4')
    expect(drawn).not.toContain('log line 3\n')
    expect(drawn).toContain('+3 more ▸')
    await ui.press({ key: 'log-toggle' })
    drawn = await texts(ui)
    expect(drawn).toContain('log line 1\n')
    expect(drawn).toContain('show fewer ▾')
    await ui.unmount()
  })

  test('a release run lists its records with their state, the reason on hover, and why it stopped', async ($, on) => {
    const records = [
      { id: 'tstdl-a', title: 'Cache store', state: 'set', reason: null },
      { id: 'tstdl-b', title: 'Cache size', state: 'dropped', reason: 'changed (contained): size moved' },
    ]
    const { clock } = world(on, { round: roundJson({ protocol: 'release', round: 'r5', step: 'board-check', title: "r4's records", check: null,
      batch: null, questions: [], records, stopped: null }) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const drawn = await texts(ui)
    for (const part of ['Release r5', "r4's records", 'board check of 1 record', 'Cache store', 'dropped', 'tstdl-b: changed (contained): size moved']) {
      expect(drawn, part).toContain(part)
    }
    expect(drawn).not.toContain('Round r5')
    await ui.unmount()
    expect(roundWords({ ...roundJson({ protocol: 'release', step: 'recheck', records, pending: null, batch: null, questions: [] }), stopped: null } as never))
      .toBe('re-checking 1 record')
  })

  test('a stopped release stays in view after it closed: its reason and the round its records go to', async ($, on) => {
    const stopped = { run: 'r5', reason: 'tstdl-a changed: the premise moved', ids: ['tstdl-a', 'tstdl-b'] }
    const { clock } = world(on, { round: { ...roundJson({ round: null, step: null, check: null, pending: null, batch: null, questions: [] }), records: [], stopped } })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await texts(ui)).toContain('release r5 stopped: tstdl-a changed: the premise moved · next: a round on tstdl-a, tstdl-b')
    await ui.unmount()
  })

  test('question rows carry the recommendation mark, the answer and the last pass that changed them', async ($, on) => {
    const base = { board: null, kind: 'decision', waitsOn: [], overlaps: [], answeredAt: null, changedBy: null }
    const questions = [
      { ...base, id: 'q1', text: 'A?', title: 'Strong one', status: 'ready', strength: 'strong', answer: null },
      { ...base, id: 'q2', text: 'B?', title: 'Pref one', status: 'ready', strength: 'lean', leanBecause: { cause: 'preference', detail: 'x' }, answer: null, changedBy: 'ground' },
      { ...base, id: 'q3', text: 'C?', title: 'Evidence one', status: 'draft', strength: 'lean', leanBecause: { cause: 'evidence', detail: 'y' }, answer: null },
      { ...base, id: 'q4', text: 'D?', title: 'Done one', status: 'answered', strength: 'lean', leanBecause: { cause: 'evidence', detail: 'y' }, answer: 'Keep' },
      { ...base, id: 'q5', text: 'E?', title: 'Typed one', status: 'answered', answer: 'a very long typed answer that goes on and on and on' },
    ]
    const { clock } = world(on, { round: roundJson({ questions }) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const color = async (text: string) => (await ui.findAll({ type: 'Text', text })).map(one => one.props.color)
    expect(await color('◆ strong')).toEqual(['inactive'])
    expect(await color('your call')).toEqual(['claude'])
    expect(await color('unverified')).toEqual(['warning'])  // the answered row shows no mark
    expect(await color('→ Keep')).toEqual(['inactive'])
    expect(await color('↻ ground')).toEqual(['inactive'])
    expect(await texts(ui)).toContain('→ a very long typed answer that goes on a…')
    await ui.unmount()
  })

  test('a long title truncates while the answer and marks keep their line', async ($, on) => {
    const long = 'A very long question title that would push the answer onto a second line of the pane'
    const base = { board: null, kind: 'decision', waitsOn: [], overlaps: [], answeredAt: null, changedBy: 'edit', answer: null }
    const questions = [
      { ...base, id: 'q1', text: 'A?', title: long, status: 'answered', answer: 'Keep' },
      { ...base, id: 'q2', text: 'B?', title: long + ' 2', status: 'ready', strength: 'lean', leanBecause: { cause: 'preference', detail: 'x' } },
    ]
    const { clock } = world(on, { round: roundJson({ questions }) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect((await ui.findAll({ type: 'Text', text: long })).filter(one => one.text === long).map(one => one.props.wrap)).toEqual(['truncate-end'])
    for (const mark of ['→ Keep', 'your call', '↻ edit']) {
      const found = await ui.findAll({ type: 'Text', text: mark })
      expect(found.length, mark).toBeGreaterThan(0)
      expect(found.some(one => one.props.wrap === 'truncate-end'), mark).toBe(false)
    }
    expect(await texts(ui)).toContain(`q1: A?`)  // the hover keeps the full text
    await ui.unmount()
  })

  test('a question hover carries its recommendation and backing', () => {
    const base = { id: 'q1', board: null, text: 'Q?', title: 'Q', kind: 'decision', status: 'ready', waitsOn: [], overlaps: [], answer: null, answeredAt: null }
    expect(recommendationText({ ...base, recommendation: 'Keep', strength: 'lean', leanBecause: { cause: 'evidence', detail: 'bd order' }, strongBecause: null } as never))
      .toBe('lean (unverified: bd order): Keep')
    expect(recommendationText({ ...base, recommendation: 'Keep', strength: 'strong', leanBecause: null, strongBecause: { noAssumptions: 'true: read' } } as never))
      .toBe('strong: Keep (noAssumptions true: read)')
  })

  test("the protocol tool reads as one line in the transcript: the call's arguments, then the engine's headline", () => {
    const stdin = JSON.stringify({ pass: 'ground', updates: [{ id: 'q1' }, { id: 'q2' }], checked: ['a'] })
    expect(protocolCallText({ args: ['step'], stdin })).toBe('step')
    expect(protocolCallText({ args: ['show', '--json'] })).toBe('show --json')
    expect(protocolResultText('r1 · ground: q1 changed · next: step-back, cycle 2/3\nRound r1 · Check cycle 2/3: step-back next.'))
      .toBe('r1 · ground: q1 changed · next: step-back, cycle 2/3')
    expect(protocolResultText(JSON.stringify({ version: 1, note: 'r1 · answered q1 (chat) · next: record the answers\nRecorded.' })))
      .toBe('r1 · answered q1 (chat) · next: record the answers')
  })

  test('a refused or malformed protocol call shows the engine\'s reason, not the exit code', () => {
    const refusal = 'protocol exited 1.\n\nstderr:\nprotocol: checked.q62: 260 characters; one line of about 120 (the finding itself goes in an update or `summary`)\nAfter the pass, report each change as a per-question update'
    expect(protocolResultText(refusal))
      .toBe('refused: checked.q62: 260 characters; one line of about 120 (the finding itself goes in an update or `summary`)')
    expect(protocolResultText({ result: refusal })).toBe(protocolResultText(refusal))
    const usage = 'protocol exited 2.\n\nstderr:\nusage: protocol [-h] [--session SESSION]\n                {start,step}\nprotocol: error: unrecognized arguments: --bogus'
    expect(protocolResultText(usage)).toBe('usage error: unrecognized arguments: --bogus')
    expect(protocolResultText('protocol exited 2.\n\nstderr:\nsomething odd')).toBe('usage error: something odd')
    expect(protocolResultText('protocol exited 3.\n\nstderr:\nboom')).toBe('protocol exited 3.')  // no reading for other codes
    expect(protocolResultText('r1 · ground: q1 changed\nstderr:\nprotocol: not a failure')).toBe('r1 · ground: q1 changed')
  })
})

describe('suggestions', () => {
  const closed = (next: unknown) => roundJson({ round: null, step: null, check: null, pending: null, batch: null, questions: [], next })
  const PROPOSED = {
    rounds: [
      { ids: [], title: 'Cache questions', summary: 'Which cache store both modules use.', estimate: { questions: 3, unblocks: 8 }, why: 'same module as the context read', fresh: false },
      { ids: ['tstdl-c'], idTitles: { 'tstdl-c': 'Retry backoff' }, title: 'Queue retry', summary: "How a failed queue job is retried, the user's way.", estimate: { questions: 1, unblocks: 5 }, why: 'highest priority left', fresh: true },
    ],
  }
  const START_0 = { command: 'start-round', args: '1' }
  const START_1 = { command: 'start-round', args: '2' }
  const parsed = (next: unknown) => ({ ...parseRound(closed(next)), isContextLarge: true })

  test('suggestions() offers rounds first (the first recommended), then Release Round, then a compact-only proposal', () => {
    expect(suggestions(null)).toEqual([])
    expect(suggestions(parsed(null))).toEqual([])
    expect(suggestions(parsed({ release: { count: 3 } }))).toEqual([
      { kind: 'release', key: 'release', count: 3, isRecommended: true }])
    expect(suggestions(parsed(PROPOSED)).map(one => [one.kind, one.key, one.isRecommended])).toEqual([['round', 'round-0', true], ['round', 'round-1', false]])
    expect(suggestions(parsed(PROPOSED))[1]).toMatchObject({ ids: ['tstdl-c'], idTitles: { 'tstdl-c': 'Retry backoff' }, number: 2, fresh: true, isCompacting: true })
    expect(suggestions(parsed(PROPOSED))[0]).toMatchObject({ ids: [], idTitles: {}, number: 1, fresh: false, isCompacting: false })
    expect(suggestions(parsed({ ...PROPOSED, release: { count: 1 } })).map(one => [one.kind, one.isRecommended]))
      .toEqual([['round', true], ['round', false], ['release', false]])
    expect(suggestions(parsed({ rounds: [] }))).toEqual([{ kind: 'compact', key: 'compact', isRecommended: true }])
    // a proposal with rounds has no Compact suggestion of its own
    expect(suggestions(parsed({ rounds: [PROPOSED.rounds[0]] })).map(one => one.kind)).toEqual(['round'])
  })

  test('below the size limit no row compacts first and a compact-only proposal is not offered', () => {
    const small = (next: unknown) => parseRound(closed(next))
    expect(small(PROPOSED).isContextLarge).toBe(false)
    expect(suggestions(small(PROPOSED)).map(one => one.kind === 'round' ? one.isCompacting : 'other')).toEqual([false, false])
    expect(suggestions(small({ rounds: [] }))).toEqual([])
    expect(suggestions(small({ rounds: [], release: { count: 1 } })).map(one => one.kind)).toEqual(['release'])
  })

  test('suggestions() stays empty while a round is open or a dialog is', () => {
    expect(suggestions(parseRound(roundJson()))).toEqual([])
    expect(suggestions(parseRound(roundJson({ next: PROPOSED })))).toEqual([])
    expect(suggestions(parsed(PROPOSED), true)).toEqual([])
  })

  test('the pane lists a row per round with its Start, the recommended one in the suggestion color; a row that names ids opens them inline', async ($, on) => {
    const { w, clock } = world(on, { round: closed(PROPOSED) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const color = async (text: string) => (await ui.findAll({ type: 'Text', text })).filter(one => one.text === text).map(one => one.props.color)
    expect(await texts(ui)).toContain('the next step, proposed')
    expect(await color('Cache questions · ~3 questions · unblocks ~8 items')).toEqual(['suggestion'])
    expect(await color('Queue retry · ~1 question · unblocks ~5 items · compacts first')).toEqual([undefined])
    // the summary is the dim wrapping second line; the model's `why` is the Start's hover hint, with what Start runs
    expect(await texts(ui)).toContain('Which cache store both modules use.')
    expect(await color('Which cache store both modules use.')).toEqual(['inactive'])
    expect(await texts(ui)).toContain('highest priority left · Start runs /start-round 2 after /compact; click the row to list the leading questions')
    expect(await texts(ui)).toContain('same module as the context read · Start runs /start-round 1')
    expect((await ui.find({ key: 'sg-round-0-start' }))?.text).toBe('Start')
    expect(await ui.find({ key: 'sg-round-1-start' })).toBeDefined()
    expect(await texts(ui)).not.toContain('click an id to open it')
    expect(await ui.find({ key: 'sg-round-0-row' })).toBeUndefined()  // no ids to list: a plain row
    await ui.press({ key: 'sg-round-1-row' })
    expect(await texts(ui)).toContain('click an id to open it')
    expect(await texts(ui)).toContain('Retry backoff')  // a leading question is listed by its title
    await ui.press({ key: 'sg-round-1-tstdl-c-open' })
    await clock.settle()
    expect(await texts(ui)).toContain('Keep it.')
    expect(w.calls.some(one => one.argv[1] === 'show' && one.argv[2] === 'tstdl-c')).toBe(true)
    await ui.press({ key: 'sg-round-1-row' })  // the item replaced the list; the row lists the ids again, a second press closes
    expect(await texts(ui)).toContain('click an id to open it')
    await ui.press({ key: 'sg-round-1-row' })
    expect(await texts(ui)).not.toContain('click an id to open it')
    await ui.unmount()
  })

  test('the pane shows no proposals without one, with a round open, or for an agent', async ($, on) => {
    const { w, clock } = world(on, { round: closed(null) })
    await ready($, clock)
    let ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await texts(ui)).not.toContain('the next step, proposed')
    expect(await texts(ui)).toContain('none open')
    await ui.unmount()
    w.round = roundJson({ next: PROPOSED })
    await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
    await clock.settle()
    ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await texts(ui)).not.toContain('the next step, proposed')
    await ui.unmount()
  })

  test('the proposals fill the Round slot: below the board, in place of none open, with no section of their own', async ($, on) => {
    const { clock } = world(on, { round: closed(PROPOSED) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const drawn = await texts(ui)
    expect(drawn).not.toContain('Suggestions')
    expect(drawn).not.toContain('none open')
    expect((await ui.find({ key: 'round-banner' }))?.text).toContain('the next step, proposed')
    expect(drawn.indexOf('holds 2')).toBeLessThan(drawn.indexOf('the next step, proposed'))
    expect(drawn.indexOf('the next step, proposed')).toBeLessThan(drawn.indexOf('Cache questions'))
    expect(drawn.indexOf('Cache questions')).toBeLessThan(drawn.indexOf('Controls'))
    await ui.unmount()
  })

  test('Release Round and a compact-only proposal show among the proposals, and their Actions twins take the suggestion color exactly then', async ($, on) => {
    const { w, clock } = world(on, { round: closed({ release: { count: 3 } }) })
    await ready($, clock)
    let ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const color = async (text: string) => (await ui.findAll({ type: 'Text', text })).filter(one => one.text === text).map(one => one.props.color)
    expect(await color('Release Round · 3 records decided')).toEqual(['suggestion'])
    expect(await color('Release Round')).toEqual(['suggestion'])
    expect(await color('Compact')).toEqual([])
    await ui.press({ key: 'sg-release-start' })
    await clock.settle()
    expect(w.commands).toEqual([{ command: 'release-round', args: '' }])
    await ui.unmount()
    w.round = closed({ rounds: [] })
    await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
    await clock.settle()
    ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await color('Compact')).toEqual(['suggestion', 'suggestion'])  // the row and its Actions twin
    expect(await color('Release Round')).toEqual([])
    await ui.press({ key: 'sg-compact-start' })
    await clock.settle()
    expect(w.commands.at(-1)).toEqual({ command: 'compact', args: '' })
    await ui.unmount()
    w.round = closed(PROPOSED)  // rounds alone twin neither
    await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
    await clock.settle()
    ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await color('Release Round')).toEqual([])
    expect(await color('Compact')).toEqual([])
    expect((await ui.find({ key: 'actions-row-compact' }))?.text).toBe('Compact')
    await ui.unmount()
  })

  test('a press returns before its engine call: a slow release stamp runs after it, then the command (the press budget)', async ($, on) => {
    const { w, clock } = world(on, { round: closed({ release: { count: 3 } }) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    let release = () => {}
    w.hold = { verb: 'pass', until: new Promise<void>(resolve => { release = resolve }) }
    await ui.press({ key: 'sg-release-start' })  // resolves while the stamp is held
    await clock.settle()
    expect(w.verbs()).toContain('pass --origin press')
    expect(w.commands).toEqual([])
    release()
    await clock.settle()
    expect(w.commands).toEqual([{ command: 'release-round', args: '' }])
    await ui.unmount()
  })

  test('the band shows the recommended suggestion; its Start runs /start-round for it', async ($, on) => {
    const { w, clock } = world(on, { round: closed(PROPOSED) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await texts(ui)).toContain('Cache questions · ~3 questions · unblocks ~8 items ·')
    expect(await texts(ui)).not.toContain('Queue retry')
    expect((await ui.findAll({ type: 'Text', text: 'Start' })).map(one => one.props.color)).toEqual(['suggestion'])
    await ui.press({ key: 'band-start' })
    await clock.settle()
    expect(w.commands).toEqual([START_0])  // the press runs /start-round 1 as a command; no prompt
    expect(w.prompts).toEqual([])
    await ui.unmount()
  })

  test('the band offers a compact-only proposal, and leaves the prompt to a dialog', async ($, on) => {
    const { w, clock } = world(on, { round: closed({ rounds: [] }) })
    on('ui.render', ($, e) => {
      const { Text } = $.ui.resolve(e) as any
      return <Text>engine</Text>
    })
    await ready($, clock)
    let ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await texts(ui)).toContain('Compact ·')
    await ui.press({ key: 'band-compact' })
    await clock.settle()
    expect(w.commands).toEqual([{ command: 'compact', args: '' }])
    await ui.unmount()
    ui = await $.ui.mount({ ...BAND, props: { ...BAND.props, hasSurvey: true }, surface: 'terminal' })
    expect(await texts(ui)).toContain('engine')
    expect(await texts(ui)).not.toContain('Compact')
    await ui.unmount()
  })

  test('a Start on a round that does not compact runs /start-round at once; a repeat is dropped', async ($, on) => {
    const { w, clock } = world(on, { round: closed(PROPOSED) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'sg-round-0-start' })
    await ui.press({ key: 'sg-round-0-start' })
    await clock.settle()
    expect(w.commands).toEqual([START_0])
    expect(w.prompts).toEqual([])
    expect(w.verbs().filter(verb => verb.startsWith('pass'))).toEqual([])  // the press is the go-ahead: no stamp, unlike /release-round
    await ui.unmount()
  })

  describe('the context size decides whether a Start compacts first', () => {
    const FIRST = 'Queue retry · ~1 question · unblocks ~5 items'
    async function mounted($: any, on: any, tokens: number | undefined | 'fails') {
      const found = world(on, { round: closed(PROPOSED) })
      found.w.tokens = tokens
      const compaction = { answer: { messages: [{ role: 'user', text: 'summary', toolUses: [] }] } as unknown }
      const ranBefore: number[] = []  // how many commands had run when each compaction began
      on('session.compact', () => { ranBefore.push(found.w.commands.length); return compaction.answer })
      await ready($, found.clock)
      return { ...found, compaction, ranBefore, ui: await $.ui.mount({ ...PANE, surface: 'terminal' }) }
    }

    for (const [name, tokens] of [['a fresh session (no reading yet)', undefined], ['just under the limit', 149_999], ['a failing reading', 'fails']] as const) {
      test(`${name}: the row does not say it, and its Start only starts`, async ($, on) => {
        const { w, clock, ui } = await mounted($, on, tokens)
        expect(await texts(ui)).toContain(FIRST)
        expect(await texts(ui)).not.toContain(`${FIRST} · compacts first`)
        await ui.press({ key: 'sg-round-1-start' })
        await clock.settle()
        expect(w.commands).toEqual([START_1])
        expect(w.prompts).toEqual([])
        await ui.unmount()
      })
    }

    test('at the limit the row says it and its Start compacts first; a row the model did not mark never does', async ($, on) => {
      const { w, clock, ui, ranBefore } = await mounted($, on, 150_000)
      expect(await texts(ui)).toContain(`${FIRST} · compacts first`)
      expect(await texts(ui)).toContain('Cache questions · ~3 questions · unblocks ~8 items')
      expect(await texts(ui)).not.toContain('Cache questions · ~3 questions · unblocks ~8 items · compacts first')
      await ui.press({ key: 'sg-round-1-start' })
      await clock.settle()
      expect(ranBefore).toEqual([0])  // r9-q48: the /start-round hook compacts first, then the command runs
      expect(w.commands).toEqual([START_1])
      await ui.unmount()
    })

    test('a proposal stored small compacts first once the context has grown', async ($, on) => {
      const { w, clock, ui } = await mounted($, on, 71_000)
      expect(await texts(ui)).not.toContain(`${FIRST} · compacts first`)
      w.tokens = 300_000
      await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't', reason: 'answer' } as never)
      await clock.settle()
      expect(await texts(ui)).toContain(`${FIRST} · compacts first`)
      await ui.unmount()
    })

    const messages = [{ role: 'user' as const, text: 'hi', toolUses: [] }]
    test('after a compaction a Start does not compact again, though the reading inside the hook is still the old one', async ($, on) => {
      const { w, clock, ui } = await mounted($, on, 500_000)
      expect(await texts(ui)).toContain(`${FIRST} · compacts first`)
      await $.session.compact({ trigger: 'manual', messages })
      await clock.settle()
      expect(await texts(ui)).not.toContain(`${FIRST} · compacts first`)
      await ui.press({ key: 'sg-round-1-start' })
      await clock.settle()
      expect(w.commands).toEqual([START_1])  // it starts; no /compact first
      await ui.unmount()
    })

    test('a skipped compaction or a precompute changes nothing', async ($, on) => {
      const { clock, compaction, ui } = await mounted($, on, 500_000)
      await $.session.compact({ trigger: 'precompute', messages })
      await clock.settle()
      expect(await texts(ui)).toContain(`${FIRST} · compacts first`)
      compaction.answer = { skip: 'vetoed by a hook' }
      await $.session.compact({ trigger: 'manual', messages })
      await clock.settle()
      expect(await texts(ui)).toContain(`${FIRST} · compacts first`)
      await ui.unmount()
    })
  })

  describe('/start-round on a row that compacts first (r9-q48), typed or pressed', () => {
    const messages = [{ role: 'user' as const, text: 'hi', toolUses: [] }]

    async function started($: any, on: any, answer: (instructions: string) => unknown = () => ({ messages })) {
      const found = world(on, { round: closed(PROPOSED) })
      found.w.tokens = 500_000
      const compactions: { instructions: string; ran: number }[] = []
      on('session.compact', (_: unknown, e: { instructions?: string }) => { compactions.push({ instructions: e.instructions ?? '', ran: found.w.commands.length }); return answer(e.instructions ?? '') })
      await ready($, found.clock)
      return { ...found, compactions }
    }
    const typed = async ($: any, clock: { settle: () => Promise<void> }, args = '2') => {
      await $.command.run({ command: 'start-round', args, origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } })
      await clock.settle()
    }

    test('a press compacts once with the proposal kept, then runs the command; nothing runs before the compaction', async ($, on) => {
      const { w, clock, compactions } = await started($, on)
      const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
      await ui.press({ key: 'sg-round-1-start' })
      await clock.settle()
      expect(compactions).toEqual([{ instructions: 'Keep the proposed next round, which starts right after this compaction: Queue retry.', ran: 0 }])
      expect(w.commands).toEqual([START_1])
      expect(w.prompts).toEqual([])
      await ui.unmount()
    })

    test('the typed command does the same', async ($, on) => {
      const { w, clock, compactions } = await started($, on)
      await typed($, clock)
      expect(compactions.map(one => one.ran)).toEqual([0])
      expect(w.commands).toEqual([START_1])
    })

    test('a bare /start-round is row 1 and compacts when row 1 does', async ($, on) => {
      const found = world(on, { round: closed({ rounds: [{ ids: [], title: 'Only row', premise: 'p', why: 'w', fresh: true }] }) })
      found.w.tokens = 500_000
      const ran: number[] = []
      on('session.compact', () => { ran.push(found.w.commands.length); return { messages } })
      await ready($, found.clock)
      await typed($, found.clock, '')
      expect(ran).toEqual([0])
      expect(found.w.commands).toEqual([{ command: 'start-round', args: '1' }])
    })

    test('after a skipped compaction the Start button works again', async ($, on) => {
      let calls = 0
      const { w, clock } = await started($, on, () => (++calls === 1 ? { skip: 'vetoed' } : { messages }))
      const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
      await ui.press({ key: 'sg-round-1-start' })
      await clock.settle()
      expect(w.commands).toEqual([])
      await ui.press({ key: 'sg-round-1-start' })
      await clock.settle()
      expect(w.toasts).not.toContain('/start-round 2 is already queued')
      expect(w.commands).toEqual([START_1])
      await ui.unmount()
    })

    test('a row that does not compact (not marked fresh) or a small context only starts', async ($, on) => {
      const { w, clock, compactions } = await started($, on)
      await typed($, clock, '1')
      expect(compactions).toEqual([])
      expect(w.commands).toEqual([START_0])
      w.tokens = 1_000
      await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't', reason: 'answer' } as never)
      await typed($, clock)
      expect(compactions).toEqual([])
      expect(w.commands).toEqual([START_0, START_1])
    })

    test('a skipped compaction starts nothing and says so', async ($, on) => {
      const { w, clock, session } = await started($, on, () => ({ skip: 'vetoed by a hook' }))
      await typed($, clock)
      expect(w.commands).toEqual([])
      expect(notices(session).some(one => one.includes('the next round was not started (compaction skipped: vetoed by a hook)') && one.includes('Queue retry') && one.includes('type /start-round 2'))).toBe(true)
    })

    test('a failing compaction starts nothing and says so', async ($, on) => {
      const { w, clock, session } = await started($, on, () => { throw new Error('summarizer down') })
      await typed($, clock)
      expect(w.commands).toEqual([])
      expect(notices(session).some(one => one.includes('the next round was not started (compaction failed') && one.includes('Queue retry'))).toBe(true)
    })
  })

  describe('a row stored before the swap, and /console', () => {
    const OLD = { rounds: [{ ids: [], title: 'Old row', premise: 'an old premise', why: 'older', fresh: false }] }

    test('a row without a summary or estimate shows its title alone and still starts', async ($, on) => {
      const { w, clock } = world(on, { round: closed(OLD) })
      await ready($, clock)
      const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
      expect(await texts(ui)).toContain('Old row')
      expect(await texts(ui)).not.toContain('an old premise')
      expect(await texts(ui)).not.toContain('unblocks')
      await ui.press({ key: 'sg-round-0-start' })
      await clock.settle()
      expect(w.commands).toEqual([START_0])
      await ui.unmount()
    })

    test('suggestionText: the title, the model\'s estimates, and what Start does first', () => {
      const rows = suggestions(parsed(PROPOSED)).flatMap(one => one.kind === 'round' ? [suggestionText(one)] : [])
      expect(rows).toEqual(['Cache questions · ~3 questions · unblocks ~8 items', 'Queue retry · ~1 question · unblocks ~5 items · compacts first'])
      const old = suggestions(parsed(OLD))[0]
      expect(old?.kind === 'round' ? suggestionText(old) : '').toBe('Old row')
    })

    test('/console text lists a line per proposal with its summary and the command to type', () => {
      const role = { session: SESSION, role: 'lead', actor: '617adf08', tool: 'claude' } as never
      const round = parsed(PROPOSED)
      const text = consoleText(role, null, round, true, suggestions(round))
      expect(text).toContain('Suggestions\n  1. Cache questions · ~3 questions · unblocks ~8 items · Which cache store both modules use. · type /start-round 1\n')
      expect(text).toContain("  2. Queue retry · ~1 question · unblocks ~5 items · compacts first · How a failed queue job is retried, the user's way. · type /start-round 2")
      expect(consoleText(role, null, round, true, [])).not.toContain('Suggestions')
      expect(consoleText(role, null, round, false, suggestions(round))).not.toContain('Suggestions')  // an agent has no rounds
    })
  })
})

describe('placed question rows', () => {
  const NOTICE = 'Engine name\nProblem: which name.'
  const typed = { origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 160 } } as const
  const row = (props: Record<string, unknown>, requestId: string) => ({ plugin: 'console', component: 'Placed', requestId, props, surface: 'terminal' }) as never
  const markdown = async (ui: { findAll: (query: { type: string }) => Promise<unknown[]> }) =>
    (await ui.findAll({ type: 'Markdown' })).map(one => (one as { props: { text: string } }).props.text)

  test('draw the stored text, and nothing for another plugin or an id with no text', async ($, on) => {
    const { clock } = world(on, { round: roundJson({ step: 'ask', batch: { ...BATCH, notice: NOTICE } }) })
    on('ui.render', ($, e) => {
      const { Text } = $.ui.resolve(e) as any
      return <Text>another plugin</Text>
    })
    await ready($, clock)
    await $.command.run({ command: 'console-questions', args: '', ...typed })
    expect(await markdown(await $.ui.mount(row({ id: 'questions-round-r4-2', plugin: 'console' }, 'own')))).toEqual([NOTICE])
    for (const [i, props] of [{ id: 'questions-round-r4-2', plugin: 'other' }, { id: 'questions-round-r4-9', plugin: 'console' }].entries()) {
      expect(await markdown(await $.ui.mount(row(props, `other-${i}`)))).toEqual([])
    }
  })
})
