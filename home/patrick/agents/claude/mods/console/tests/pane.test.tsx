// The pane, the band, presses, /console and the idle-agent notification.
import { describe, expect, test } from 'claude-code/testing'

import { HOME, notices, PANE_PROPS, roundJson, SESSION, world } from './fixture'
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

  test('held questions collapse from 3 on and expand on press', async ($, on) => {
    const held = (id: string) => ({ id, board: null, text: `${id}?`, title: `Held ${id}`, kind: 'decision', status: 'held', waitsOn: ['q1'], overlaps: [], answer: null })
    const { clock } = world(on, { round: roundJson({ questions: [held('q5'), held('q6'), held('q7')] }) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await texts(ui)).not.toContain('Held q5')
    await ui.press({ key: 'held-toggle' })
    expect(await texts(ui)).toContain('Held q5')
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

  test('an item id prints its summary as a notice; a worker row switches the view', async ($, on) => {
    const { w, clock, session } = world(on, { agents: [{ id: 'a1', description: 'Worker B', type: 'craft', status: 'running' }] })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'item-tstdl-x1-show' })
    await clock.settle()
    expect(notices(session).some(text => text.includes('tstdl-x1: Which engine name?'))).toBe(true)
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

  test('overlaps are one count link that prints ids and titles', async ($, on) => {
    const overlaps = [{ id: 'tstdl-a', title: 'Alpha', outcome: null }, { id: 'tstdl-b', title: 'Beta', outcome: null }]
    const { clock, session } = world(on, { round: roundJson({ questions: [q(1, 'draft', { overlaps })] }) })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await texts(ui)).toContain('2 overlaps')
    await ui.press({ key: 'q-q1-ov' })
    expect(notices(session).some(text => text.includes('tstdl-a  Alpha') && text.includes('tstdl-b  Beta'))).toBe(true)
  })

  test('board lists cap at 6 rows, active sessions first', async ($, on) => {
    const items = [1, 2, 3, 4, 5, 6, 7, 8].map(n => ({ id: `tstdl-i${n}`, type: 'decision', status: 'open', title: `Item ${n}`, holder: '617adf08' }))
    const session = (n: number, state: string) => ({ session: `s-${n}`, role: 'agent', actor: `actor00${n}`, pulls: [], holds: 0, workers: null, state, idleSince: null, claimable: 0 })
    const sessions = [session(1, 'gone'), ...[2, 3, 4, 5, 6, 7].map(n => session(n, 'active'))]
    const { clock } = world(on, { items, sessions })
    await ready($, clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const drawn = await texts(ui)
    expect(drawn).toContain('Item 6')
    expect(drawn).not.toContain('Item 7')
    expect(drawn).toContain('+2 more ▸')
    expect(drawn).not.toContain('actor001')  // gone sorts last, past the cap
    await ui.press({ key: 'items-toggle' })
    expect(await texts(ui)).toContain('Item 8')
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
    expect(protocolResultText('r1 · ground: q1 changed, 1 not applied · next: step-back, cycle 2/3\nRound r1 · Check cycle 2/3: step-back next.'))
      .toBe('r1 · ground: q1 changed, 1 not applied · next: step-back, cycle 2/3')
    expect(protocolResultText(JSON.stringify({ version: 1, note: 'r1 · answered q1 (chat) · next: record the answers\nRecorded.' })))
      .toBe('r1 · answered q1 (chat) · next: record the answers')
  })
})
