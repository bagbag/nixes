// The pane, the band, presses, /console and the idle-agent notification.
import { describe, expect, test } from 'claude-code/testing'

import { HOME, notices, PANE_PROPS, roundJson, SESSION, world } from './fixture'
import { parseRound } from '../hooks/engine'
import { suggestions } from '../hooks/pane'
import { protocolCallText, protocolResultText, pullsText, recommendationText, roundWords } from '../hooks/words'

const PANE = { plugin: 'console', component: 'Pane', requestId: 'console', props: PANE_PROPS } as const
const BAND = {
  plugin: 'console', component: 'AbovePrompt',
  props: { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 120, scroll: { offset: 0, bodyRows: 10 }, view: {} },
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
      { command: 'step-back', args: 'goal decisions foundations consumer root-fix bloat gaps clean overfit mechanics the gate' },
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
    await ui.press({ key: 'actions-row-compact' })
    await ui.press({ key: 'actions-row-push' })
    await clock.settle()
    expect(w.commands).toEqual([
      { command: 'explain', args: 'q3 Pane layout' }, { command: 'step-back', args: 'q3 Pane layout' },
      { command: 'question-me', args: '' }, { command: 'compact', args: '' },
    ])
    expect(w.prompts).toEqual(['commit and push'])
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
})

describe('suggestions', () => {
  const closed = (next: unknown) => roundJson({ round: null, step: null, check: null, pending: null, batch: null, questions: [], next })
  const PROPOSED = {
    rounds: [
      { ids: ['tstdl-a', 'tstdl-b'], title: 'Cache questions', why: 'same module as the context read', fresh: false },
      { ids: ['tstdl-c'], title: 'Queue retry', why: 'highest priority left', fresh: true },
    ],
    compact: { keep: 'the cache decisions' },
  }
  const parsed = (next: unknown) => ({ ...parseRound(closed(next)), isContextLarge: true })

  test('suggestions() offers rounds first (the first recommended), then Release Round, then a compact-only proposal', () => {
    expect(suggestions(null)).toEqual([])
    expect(suggestions(parsed(null))).toEqual([])
    expect(suggestions(parsed({ release: { count: 3 } }))).toEqual([
      { kind: 'release', key: 'release', count: 3, isRecommended: true }])
    expect(suggestions(parsed(PROPOSED)).map(one => [one.kind, one.key, one.isRecommended])).toEqual([['round', 'round-0', true], ['round', 'round-1', false]])
    expect(suggestions(parsed(PROPOSED))[1]).toMatchObject({ ids: ['tstdl-c'], fresh: true, keep: 'the cache decisions' })
    expect(suggestions(parsed(PROPOSED))[0]).toMatchObject({ fresh: false, keep: null })
    expect(suggestions(parsed({ ...PROPOSED, release: { count: 1 } })).map(one => [one.kind, one.isRecommended]))
      .toEqual([['round', true], ['round', false], ['release', false]])
    expect(suggestions(parsed({ compact: { keep: 'all decisions' } }))).toEqual([{ kind: 'compact', key: 'compact', keep: 'all decisions', isRecommended: true }])
    // a compact proposal beside rounds is the rounds' keep, not a Compact suggestion of its own
    expect(suggestions(parsed({ rounds: [PROPOSED.rounds[0]], compact: { keep: 'x' } })).map(one => one.kind)).toEqual(['round'])
  })

  test('below the size limit no row compacts first and a compact-only proposal is not offered', () => {
    const small = (next: unknown) => parseRound(closed(next))
    expect(small(PROPOSED).isContextLarge).toBe(false)
    expect(suggestions(small(PROPOSED)).map(one => one.kind === 'round' ? one.keep : 'other')).toEqual([null, null])
    expect(suggestions(small({ compact: { keep: 'all decisions' } }))).toEqual([])
    expect(suggestions(small({ compact: { keep: 'all decisions' }, release: { count: 1 } })).map(one => one.kind)).toEqual(['release'])
  })

  test('suggestions() stays empty while a round is open or a dialog is', () => {
    expect(suggestions(parseRound(roundJson()))).toEqual([])
    expect(suggestions(parseRound(roundJson({ next: PROPOSED })))).toEqual([])
    expect(suggestions(parsed(PROPOSED), true)).toEqual([])
  })

  test('the pane lists a row per round with its Start, the recommended one in the suggestion color; a row opens its ids inline', async ($, on) => {
    const { w, clock } = world(on, { round: closed(PROPOSED) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const color = async (text: string) => (await ui.findAll({ type: 'Text', text })).filter(one => one.text === text).map(one => one.props.color)
    expect(await texts(ui)).toContain('Suggestions')
    expect(await color('Cache questions · 2 questions · same module as the context read')).toEqual(['suggestion'])
    expect(await color('Queue retry · 1 question · highest priority left · compacts first')).toEqual([undefined])
    expect((await ui.find({ key: 'sg-round-0-start' }))?.text).toBe('Start')
    expect(await ui.find({ key: 'sg-round-1-start' })).toBeDefined()
    expect(await texts(ui)).not.toContain('click an id to open it')
    await ui.press({ key: 'sg-round-0-row' })
    expect(await texts(ui)).toContain('click an id to open it')
    await ui.press({ key: 'sg-round-0-tstdl-b-open' })
    await clock.settle()
    expect(await texts(ui)).toContain('Keep it.')
    expect(w.calls.some(one => one.argv[1] === 'show' && one.argv[2] === 'tstdl-b')).toBe(true)
    await ui.press({ key: 'sg-round-0-row' })  // the item replaced the list; the row lists the ids again, a second press closes
    expect(await texts(ui)).toContain('click an id to open it')
    await ui.press({ key: 'sg-round-0-row' })
    expect(await texts(ui)).not.toContain('click an id to open it')
    await ui.unmount()
  })

  test('the pane shows no Suggestions area without a proposal, with a round open, or for an agent', async ($, on) => {
    const { w, clock } = world(on, { round: closed(null) })
    await ready($, clock)
    let ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await texts(ui)).not.toContain('Suggestions')
    await ui.unmount()
    w.round = roundJson({ next: PROPOSED })
    await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
    await clock.settle()
    ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await texts(ui)).not.toContain('Suggestions')
    await ui.unmount()
  })

  test('Release Round and a compact-only proposal show in Suggestions, and their Actions twins take the suggestion color exactly then', async ($, on) => {
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
    w.round = closed({ compact: { keep: 'all decisions' } })
    await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
    await clock.settle()
    ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await color('Compact · keeps all decisions')).toEqual(['suggestion'])
    expect(await color('Compact')).toEqual(['suggestion'])
    expect(await color('Release Round')).toEqual([])
    await ui.press({ key: 'sg-compact-start' })
    await clock.settle()
    expect(w.commands.at(-1)).toEqual({ command: 'compact', args: 'all decisions' })
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

  test('the band shows the recommended suggestion; its Start sends the start message', async ($, on) => {
    const { w, clock } = world(on, { round: closed(PROPOSED) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await texts(ui)).toContain('Cache questions · 2 questions ·')
    expect(await texts(ui)).not.toContain('Queue retry')
    expect((await ui.findAll({ type: 'Text', text: 'Start' })).map(one => one.props.color)).toEqual(['suggestion'])
    await ui.press({ key: 'band-start' })
    await clock.settle()
    expect(w.prompts).toEqual(['Start the next round on Cache questions: protocol start round tstdl-a tstdl-b'])
    expect(w.commands).toEqual([])
    await ui.unmount()
  })

  test('the band offers a compact-only proposal, and leaves the prompt to a dialog', async ($, on) => {
    const { w, clock } = world(on, { round: closed({ compact: { keep: 'all decisions' } }) })
    on('ui.render', ($, e) => {
      const { Text } = $.ui.resolve(e) as any
      return <Text>engine</Text>
    })
    await ready($, clock)
    let ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
    expect(await texts(ui)).toContain('Compact · keeps all decisions ·')
    await ui.press({ key: 'band-compact' })
    await clock.settle()
    expect(w.commands).toEqual([{ command: 'compact', args: 'all decisions' }])
    await ui.unmount()
    ui = await $.ui.mount({ ...BAND, props: { ...BAND.props, hasSurvey: true }, surface: 'terminal' })
    expect(await texts(ui)).toContain('engine')
    expect(await texts(ui)).not.toContain('Compact')
    await ui.unmount()
  })

  test('a Start on a round that does not compact sends the start message at once; a repeat is dropped', async ($, on) => {
    const { w, clock } = world(on, { round: closed(PROPOSED) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'sg-round-0-start' })
    await ui.press({ key: 'sg-round-0-start' })
    await clock.settle()
    expect(w.prompts).toEqual(['Start the next round on Cache questions: protocol start round tstdl-a tstdl-b'])
    expect(w.commands).toEqual([])
    await ui.unmount()
  })

  describe('the context size decides whether a Start compacts first', () => {
    const FIRST = 'Queue retry · 1 question · highest priority left'
    async function mounted($: any, on: any, tokens: number | undefined | 'fails') {
      const found = world(on, { round: closed(PROPOSED) })
      found.w.tokens = tokens
      const compaction = { answer: { messages: [{ role: 'user', text: 'summary', toolUses: [] }] } as unknown }
      on('session.compact', () => compaction.answer)
      await ready($, found.clock)
      return { ...found, compaction, ui: await $.ui.mount({ ...PANE, surface: 'terminal' }) }
    }

    for (const [name, tokens] of [['a fresh session (no reading yet)', undefined], ['just under the limit', 149_999], ['a failing reading', 'fails']] as const) {
      test(`${name}: the row does not say it, and its Start only starts`, async ($, on) => {
        const { w, clock, ui } = await mounted($, on, tokens)
        expect(await texts(ui)).toContain(FIRST)
        expect(await texts(ui)).not.toContain(`${FIRST} · compacts first`)
        await ui.press({ key: 'sg-round-1-start' })
        await clock.settle()
        expect(w.commands).toEqual([])
        expect(w.prompts).toEqual(['Start the next round on Queue retry: protocol start round tstdl-c'])
        await ui.unmount()
      })
    }

    test('at the limit the row says it and its Start compacts first; a row the model did not mark never does', async ($, on) => {
      const { w, clock, ui } = await mounted($, on, 150_000)
      expect(await texts(ui)).toContain(`${FIRST} · compacts first`)
      expect(await texts(ui)).toContain('Cache questions · 2 questions · same module as the context read')
      await ui.press({ key: 'sg-round-1-start' })
      await clock.settle()
      expect(w.commands).toEqual([{ command: 'compact', args: 'the cache decisions' }])
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
      expect(w.commands).toEqual([])
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

  describe('a Start on a round that compacts first', () => {
    const START = 'Start the next round on Queue retry: protocol start round tstdl-c'
    const messages = [{ role: 'user' as const, text: 'hi', toolUses: [] }]
    const compact = ($: any) => $.session.compact({ trigger: 'manual', instructions: 'the cache decisions', messages })

    /** The press: stores the start message and runs /compact with the proposal's keep. */
    async function pressed($: any, on: any, answer: (instructions: string) => unknown = () => ({ messages: [{ role: 'user', text: 'summary', toolUses: [] }] })) {
      const found = world(on, { round: closed(PROPOSED) })
      const seen: string[] = []
      on('session.compact', (_: unknown, e: { instructions?: string }) => { seen.push(e.instructions ?? ''); return answer(e.instructions ?? '') })
      await ready($, found.clock)
      const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
      await ui.press({ key: 'sg-round-1-start' })
      await found.clock.settle()
      await ui.unmount()
      return { ...found, seen }
    }

    test('stores the message and runs /compact with the keep; the compaction hook keeps the proposal and sends it once compaction succeeded', async ($, on) => {
      const { w, clock, seen } = await pressed($, on)
      expect(w.commands).toEqual([{ command: 'compact', args: 'the cache decisions' }])
      expect(w.prompts).toEqual([])  // nothing is sent before the compaction
      await compact($)
      expect(seen[0]).toContain('the cache decisions')
      expect(seen[0]).toContain(`Keep the proposed next round, which starts right after this compaction: ${START}.`)
      expect(seen[0]?.match(/the cache decisions/g)).toHaveLength(1)  // the keep is in the instructions once
      await clock.settle()
      expect(w.prompts).toEqual([START])
      await compact($)  // cleared: the next compaction sends nothing
      await clock.settle()
      expect(w.prompts).toEqual([START])
    })

    test('a precompute installs nothing: the stored message waits for the compaction itself', async ($, on) => {
      const { w, clock } = await pressed($, on)
      await $.session.compact({ trigger: 'precompute', messages })
      await clock.settle()
      expect(w.prompts).toEqual([])
      await compact($)
      await clock.settle()
      expect(w.prompts).toEqual([START])
    })

    test('a skipped compaction clears it and says so', async ($, on) => {
      const { w, clock, session } = await pressed($, on, () => ({ skip: 'vetoed by a hook' }))
      await compact($)
      await clock.settle()
      expect(w.prompts).toEqual([])
      expect(notices(session).some(one => one.includes('the next round was not started (compaction skipped: vetoed by a hook)') && one.includes(START))).toBe(true)
      await $.session.compact({ trigger: 'manual', messages })
      await clock.settle()
      expect(w.prompts).toEqual([])
    })

    test('a failing compaction clears it and says so', async ($, on) => {
      const { w, clock, session } = await pressed($, on, () => { throw new Error('summarizer down') })
      await compact($).catch(() => undefined)
      await clock.settle()
      expect(w.prompts).toEqual([])
      expect(notices(session).some(one => one.includes('the next round was not started (compaction failed') && one.includes(START))).toBe(true)
    })

    test("a plugin's prompt or a hidden one does not clear it", async ($, on) => {
      const { w, clock } = await pressed($, on)
      await $.prompt.submit({ text: 'from a plugin', origin: { kind: 'plugin', name: 'x' }, wait: false } as never)
      await $.prompt.submit({ text: 'hidden', origin: { kind: 'composer' }, isMeta: true, wait: false } as never)
      await compact($)
      await clock.settle()
      expect(w.prompts).toEqual(['from a plugin', 'hidden', START])
    })

    for (const kind of ['composer', 'bridge'] as const) {
      test(`a prompt the person types (${kind}) drops it`, async ($, on) => {
        const { w, clock } = await pressed($, on)
        await $.prompt.submit({ text: 'use flow, not protocol', origin: { kind }, wait: false } as never)
        await compact($)
        await clock.settle()
        expect(w.prompts).toEqual(['use flow, not protocol'])
      })
    }

    test('a round start drops it', async ($, on) => {
      const { w, clock } = await pressed($, on)
      w.round = roundJson()
      await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
      await clock.settle()
      await compact($)
      await clock.settle()
      expect(w.prompts).toEqual([])
    })
  })
})
