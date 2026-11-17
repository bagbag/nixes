// Change requests (r25): the queue section, Open (the board opens the request's worktree for your review, on its own branch), and the Accept / Return /
// Refresh presses, which send requests as your message (Return fills the prompt; the console never lands); the counts display (r21-q141, q146).
import { describe, expect, test } from 'claude-code/testing'
import type { Mounted } from 'claude-code/testing'

import { BOARD_CONSOLE_CONTRACT, cr } from './board-console-contract'
import { COUNTS, NO_ROUND, PANE_PROPS, SESSION, world } from './fixture'
import { CR_TREE, git, repo, sha } from './review-world'
import type { Repo } from './review-world'
import { parseBoardConsole, parseRound } from '../hooks/engine'
import { canUpdateCr, consoleText, countText, crCheckText, crDetailsText, crFailuresText, crMarks, crPriorityHint, crRows, crUnblocksHint, crUnblocksText, fitText } from '../hooks/words'
import type { ConsoleBoard, ConsoleCr } from '../types'

const PANE = { plugin: 'console', component: 'Pane', requestId: 'console', props: PANE_PROPS } as const

async function ready($: any, clock: { settle: () => Promise<void> }) {
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await clock.settle()
}

const texts = async (ui: { findAll: (query: { type: string }) => Promise<{ text: string }[]> }): Promise<string> =>
  (await ui.findAll({ type: 'Text' })).map(one => one.text).join('\n')

type Crs = Record<string, unknown>[]

/** A world over a stand-in repo and a board queue; mounts the pane. */
async function queued($: any, on: any, crs: Crs, r: Repo = repo(), init: Parameters<typeof world>[1] = {}) {
  const made = world(on, { round: NO_ROUND, crs, ...init })
  made.w.git = git(r)
  await ready($, made.clock)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  return { ...made, ui, r }
}

const WAITING = (): Crs => [cr({ id: 'p-cr1' })]
const BLOCKED = (paths: string[]) => ({ kind: 'land-blocked', text: `land blocked: ${paths.join(', ')}`, next: { action: 'ask-user', paths } })
const REFRESH = (id: string) => ({ kind: 'check', text: 'check stale', next: { action: 'refresh', command: `board cr refresh ${id}` } })
const short = (n: number) => sha(n).slice(0, 7)

describe('change request queue', () => {
  test('no change requests: no section', async ($, on) => {
    const { ui } = await queued($, on, [])
    expect(await texts(ui)).not.toContain('Change requests')
    expect(await ui.find({ key: 'cr-open-p-cr1' })).toBeUndefined()
    await ui.unmount()
  })

  test('a stack: the child stands under its parent with stage, check state and look', async ($, on) => {
    const { ui } = await queued($, on, [...BOARD_CONSOLE_CONTRACT.crs] as unknown as Crs, repo(), { ratifications: [...BOARD_CONSOLE_CONTRACT.ratifications] })
    const drawn = await texts(ui)
    for (const part of ['Change requests', 'Remove the legacy cache', 'Drop the cache config', 'code', '2 new', 'checkpoint review', 'stale', 'to ratify', 'Ratify: Move the clock']) {
      expect(drawn, part).toContain(part)
    }
    expect(drawn).not.toContain('checks current')  // the normal state stays off the row
    expect(drawn).not.toContain('0 new')  // a zero count stays in the opened summary
    // The row holds the short status; counts, names, look and view wait in the opened summary.
    for (const part of ['base 3012', 'src/a.ts', 'look before', 'look after']) expect(drawn, part).not.toContain(part)
    expect(drawn.indexOf('Remove the legacy cache')).toBeLessThan(drawn.indexOf('Drop the cache config'))
    await ui.unmount()
  })

  test('rows nest children under their parent whatever the queue order; an unqueued parent leaves the child on top', () => {
    const rows = crRows([cr({ id: 'c', parent: 'p' }), cr({ id: 'x', parent: 'gone' }), cr({ id: 'p' })] as unknown as ConsoleCr[])
    expect(rows.map(one => `${one.depth}${one.cr.id}`)).toEqual(['0x', '0p', '1c'])
  })

  test('a parent cycle still lists its members once', () => {
    const rows = crRows([cr({ id: 'a', parent: 'b' }), cr({ id: 'b', parent: 'a' })] as unknown as ConsoleCr[])
    expect(rows.map(one => one.cr.id).sort()).toEqual(['a', 'b'])
  })

  test('an open request in work shows no check line until it has one', async ($, on) => {
    const { ui } = await queued($, on, [cr({ id: 'p-cr1', status: 'in_progress', holder: 'a1', check: { state: 'unchecked', tip: null, baseTip: null, at: null, result: null, newFailures: null, baseCount: null, tipCount: null } })])
    const drawn = await texts(ui)
    expect(drawn).toContain('in work')
    expect(drawn).not.toContain('unchecked')
    expect(await ui.find({ key: 'cr-open-p-cr1' })).toBeUndefined()
    await ui.unmount()
  })

  test('Open, Accept and Return only where the request waits for you', async ($, on) => {
    const { ui } = await queued($, on, [cr({ id: 'p-cr1' }), cr({ id: 'p-cr2', status: 'in_review' })])
    for (const key of ['cr-open-p-cr1', 'cr-accept-p-cr1', 'cr-return-p-cr1']) expect(await ui.find({ key }), key).toBeDefined()
    for (const key of ['cr-open-p-cr2', 'cr-accept-p-cr2', 'cr-return-p-cr2']) expect(await ui.find({ key }), key).toBeUndefined()
    await ui.unmount()
  })

  test('a request whose landing waits on a parent shows the wait and no Accept; Open and Return stay', async ($, on) => {
    const WAITS = { kind: 'waits', text: 'waits on p-cr0 (returned)', next: { action: 'wait' } }
    const { ui } = await queued($, on, [cr({ id: 'p-cr1', problems: [WAITS] }), cr({ id: 'p-cr2' })])
    expect(await ui.find({ key: 'cr-accept-p-cr1' })).toBeUndefined()
    for (const key of ['cr-open-p-cr1', 'cr-return-p-cr1', 'cr-accept-p-cr2']) expect(await ui.find({ key }), key).toBeDefined()
    const drawn = await texts(ui)
    expect(drawn).toContain('waits on p-cr0 (returned)')
    expect(drawn).toContain('1 to accept · 1 waits to land')
    await ui.unmount()
  })

  test('Update: a deciding session dispatches the refresh the board names; absent where the board names none', async ($, on) => {
    const { ui, w, clock } = await queued($, on, [cr({ id: 'p-cr1', problems: [REFRESH('p-cr1')] }), cr({ id: 'p-cr2', problems: [{ ...REFRESH('p-cr2'), next: { action: 'wait' } }] })])
    expect(await ui.find({ key: 'cr-update-p-cr2' })).toBeUndefined()
    await ui.press({ key: 'cr-update-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual(["Update p-cr1 (Title of p-cr1): its check stale; dispatch its refresh (`board cr refresh p-cr1`) under the review protocol's Refresh."])
    await ui.unmount()
  })

  const agent = (pulls: string[]) => ({ sessions: [{ session: SESSION, role: 'agent', actor: 'a1', pulls, holds: 0, workers: null, state: 'active', idleSince: null, claimable: 0 }],
    role: { session: SESSION, role: 'agent', actor: 'a1', tool: 'claude' } })

  test('a review-pulling session runs the refresh itself', async ($, on) => {
    const { ui, w, clock } = await queued($, on, [cr({ id: 'p-cr1', problems: [REFRESH('p-cr1')] })], repo(), agent(['review']))
    await ui.press({ key: 'cr-update-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual(["Refresh p-cr1 under the review protocol's Refresh."])
    await ui.unmount()
  })

  test('a session with another pull sees no Update', async ($, on) => {
    const { ui } = await queued($, on, [cr({ id: 'p-cr1', problems: [REFRESH('p-cr1')] })], repo(), agent(['implement']))
    expect(await ui.find({ key: 'cr-update-p-cr1' })).toBeUndefined()
    await ui.unmount()
  })
})

describe('no new failures', () => {
  const checked = (over: Record<string, unknown>) => cr({ id: 'p-cr1', check: { state: 'failed', tip: sha(2), baseTip: sha(1), at: null, result: 'fail', ...over } }) as unknown as ConsoleCr

  test('none new reads with both totals; the new ones are named, three at most', () => {
    expect(crFailuresText(checked({ newFailures: [], baseCount: 3012, tipCount: 2972 }))).toBe('0 new (base 3012, tip 2972)')
    expect(crFailuresText(checked({ newFailures: ['a TS1', 'b TS2'], baseCount: 5, tipCount: 7 }))).toBe('2 new: a TS1, b TS2 (base 5, tip 7)')
    expect(crFailuresText(checked({ newFailures: ['a 1', 'b 2', 'c 3', 'd 4'], baseCount: null, tipCount: null }))).toBe('4 new: a 1, b 2, c 3, …')
  })

  test('no comparison ran: nothing is said', () => {
    expect(crFailuresText(checked({ newFailures: null, baseCount: null, tipCount: null }))).toBeNull()
  })

  test('the row draws the new-failure count beside the check state; the opened summary names the files', async ($, on) => {
    const { ui, clock } = await queued($, on, [checked({ newFailures: ['src/a.ts TS2322'], baseCount: 3, tipCount: 4 }) as unknown as Record<string, unknown>])
    const row = await texts(ui)
    expect(row).toContain('1 new')
    expect(row).not.toContain('src/a.ts')
    await ui.press({ key: 'cr-p-cr1-show' })
    await clock.settle()
    expect(await texts(ui)).toContain('base 3, tip 4')
    await ui.unmount()
  })

  test('a request for you names what you look at on its row; its opened summary says it waits to accept', async ($, on) => {
    const { ui, clock } = await queued($, on, [cr({ id: 'p-cr1', checkpoint: 'user' }), cr({ id: 'p-cr2', view: 'result' }), cr({ id: 'p-cr3' })])
    const legend = (await ui.find({ key: 'cr-legend' }))?.text ?? ''  // the kinds as words, above the rows
    for (const kind of ['design', 'result', 'code']) expect(legend, kind).toContain(kind)
    expect(legend).not.toContain('in work')  // no request of that kind shows
    for (const id of ['p-cr1', 'p-cr2', 'p-cr3']) expect((await ui.find({ key: `cr-${id}` }))?.text ?? '', id).not.toContain('to accept')
    await ui.press({ key: 'cr-p-cr1-show' })
    await clock.settle()
    expect((await ui.find({ key: 'cr-p-cr1-details' }))?.text).toContain('to accept (design)')
    await ui.unmount()
  })

  test('unchecked is hidden on a design checkpoint (landing it ignores checks) and shown on a code request', async ($, on) => {
    const unchecked = { state: 'unchecked', tip: null, baseTip: null, at: null, result: null, newFailures: null, baseCount: null, tipCount: null }
    const { ui } = await queued($, on, [cr({ id: 'p-d', checkpoint: 'user', check: unchecked }), cr({ id: 'p-c', check: unchecked })])
    expect(await texts(ui)).toContain('unchecked')
    expect((await texts(ui)).match(/unchecked/g)).toHaveLength(1)
    await ui.unmount()
  })

  test('a request in agent review is not yours to accept', async ($, on) => {
    const { ui } = await queued($, on, [cr({ id: 'p-cr1', status: 'in_review' })])
    expect(await ui.find({ key: 'cr-accept-p-cr1' })).toBeUndefined()
    await ui.unmount()
  })
})

describe('Open', () => {
  const boardCalls = (w: { calls: { argv: string[] }[] }, verb: string) => w.calls.filter(one => one.argv[1] === verb).map(one => one.argv.slice(2))

  test('view=code presses `board review open <id>` and opens what it prints; the console writes no git', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1' })], r)
    w.reviewOpen.stdout = `${CR_TREE}/t.code-workspace\n`
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(boardCalls(w, 'review')).toEqual([['open', 'p-cr1']])
    expect(r.opened).toEqual([`${CR_TREE}/t.code-workspace`])
    expect(w.toasts.at(-1)).toBe(`p-cr1 is opening in VS Code (${CR_TREE}/t.code-workspace)`)
    expect(r.all).toEqual([])  // the board owns the marker and the view (r3-q14)
    await ui.unmount()
  })

  test('a ratification row presses `board review open` for its own id, and has no Open without a landed range', async ($, on) => {
    const r = repo()
    const ratifications = [{ id: 'p-rat1', cr: 'p-cr0', title: 'Ratify: Move the clock', tip: sha(6), baseTip: sha(5), review: null }, { id: 'p-rat2', cr: '', title: 'Ratify: unknown', tip: null, baseTip: null, review: null }]
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1' })], r, { ratifications })
    expect(await ui.find({ key: 'ratify-p-rat2-open' })).toBeUndefined()
    await ui.press({ key: 'ratify-p-rat1-open' })
    await clock.settle()
    expect(boardCalls(w, 'review')).toEqual([['open', 'p-rat1']])
    expect(r.opened).toEqual(['/main/.worktrees/p-rat1'])
    expect(r.all).toEqual([])
    await ui.unmount()
  })

  test('the board\'s refusal is the toast, as it said it; nothing opens', async ($, on) => {
    const r = repo()
    const ratifications = [{ id: 'p-rat1', cr: 'p-cr0', title: 'Ratify: Move the clock', tip: sha(6), baseTip: sha(5), review: null }]
    const { ui, clock, w } = await queued($, on, WAITING(), r, { ratifications })
    w.reviewOpen = { exit: 1, stdout: '', stderr: 'p-cr1: held by a1b2, an agent session at work in its worktree (a refresh): open it once that session releases it\n' }
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(w.toasts.at(-1)).toBe('Change request: p-cr1: held by a1b2, an agent session at work in its worktree (a refresh): open it once that session releases it')
    await ui.press({ key: 'ratify-p-rat1-open' })
    await clock.settle()
    expect(w.toasts.at(-1)).toMatch(/^Ratification: p-cr1: held by a1b2/)
    expect(r.opened).toEqual([])
    await ui.unmount()
  })

  test('a VS Code that does not open says so, naming where the review is', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, WAITING(), r)
    const run = w.git as NonNullable<typeof w.git>
    w.git = (argv, env) => argv[0] === 'code' ? { exitCode: 1, stderr: 'no code\n' } : run(argv, env)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(w.toasts.at(-1)).toBe(`Change request: p-cr1 is open for your review (${CR_TREE}); VS Code did not open it (no code)`)
    await ui.unmount()
  })

  const boardReads = (w: { calls: { argv: string[] }[] }) => w.calls.filter(one => one.argv[1] === 'console').length

  test('a press acts on the shown board: no board read before the action, whatever the board holds now (r1-q5)', async ($, on) => {
    const r = repo()
    const { w, ui, clock } = await queued($, on, WAITING(), r)
    w.crs = [cr({ id: 'p-cr1', status: 'open' })]  // returned meanwhile; the pane still shows the old board
    const before = boardReads(w)
    const openedAt: number[] = []
    const run = w.git as NonNullable<typeof w.git>
    w.git = (argv, env) => { if (argv[0] === 'code') openedAt.push(boardReads(w)); return run(argv, env) }
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(openedAt).toEqual([before])  // the action ran with no read since the press
    expect(r.opened).toEqual([CR_TREE])
    await ui.unmount()
  })

  test('a press acts on the shown board although a failing agent list put an error on the shown board (r9-q29)', async ($, on) => {
    const r = repo()
    const made = world(on, { round: NO_ROUND, crs: WAITING() })
    made.w.git = git(r)
    made.w.agentsFail = true
    await ready($, made.clock)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const before = boardReads(made.w)
    const openedAt: number[] = []
    const run = made.w.git as NonNullable<typeof made.w.git>
    made.w.git = (argv, env) => { if (argv[0] === 'code') openedAt.push(boardReads(made.w)); return run(argv, env) }
    await ui.press({ key: 'cr-open-p-cr1' })
    await made.clock.settle()
    expect(openedAt).toEqual([before])  // no fresh read before the action: the shown board is used
    expect(r.opened).toEqual([CR_TREE])
    await ui.unmount()
  })

  test('after any press the board refreshes once the action is done (r3-q14)', async ($, on) => {
    const ratifications = [{ id: 'p-rat1', cr: 'p-cr0', title: 'Ratify: Move the clock', tip: sha(6), baseTip: sha(5), review: null }]
    const { w, ui, clock } = await queued($, on, [cr({ id: 'p-cr1' }), cr({ id: 'p-cr2', view: 'result' })], repo(), { ratifications })
    for (const key of ['cr-open-p-cr1', 'cr-accept-p-cr1', 'cr-return-p-cr1', 'cr-open-p-cr2', 'ratify-p-rat1-open', 'ratify-p-rat1-yes']) {
      const before = boardReads(w)
      await ui.press({ key })
      await clock.settle()
      expect(boardReads(w), key).toBeGreaterThan(before)
    }
    w.reviewOpen = { exit: 1, stdout: '', stderr: 'refused' }
    const before = boardReads(w)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(boardReads(w), 'a refused press').toBeGreaterThan(before)
    await ui.unmount()
  })

  test('the pressed Open shows at once: inverse, its step in its hover hint (no line added), a second press says it is busy, the end a toast', async ($, on) => {
    const r = repo()
    const { w, ui, clock } = await queued($, on, WAITING(), r)
    const isInverse = async () => ((await ui.findAll({ type: 'Text' })) as { text: string; props?: { inverse?: boolean } }[]).some(one => one.text === 'Open' && one.props?.inverse === true)
    const rows = async () => ((await ui.find({ key: 'cr-p-cr1-lines' })) as { children?: unknown[] }).children?.length
    const height = async () => ((await ui.find({ key: 'cr-p-cr1' })) as { children?: unknown[] }).children?.length
    const calm = { height: await height(), rows: await rows() }
    let release = () => {}
    w.hold = { verb: 'board review', until: new Promise<void>(resolve => { release = resolve }) }
    expect(await isInverse()).toBe(false)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(await texts(ui)).toContain('Open · opening your review…')
    expect({ height: await height(), rows: await rows() }).toEqual(calm)
    expect(await isInverse()).toBe(true)
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.toasts.at(-1)).toBe('Open p-cr1 is still at work (opening your review); press again when it is done')
    release()
    w.hold = null
    await clock.settle()
    expect(r.opened).toEqual([CR_TREE])
    expect(w.toasts.at(-1)).toBe(`p-cr1 is opening in VS Code (${CR_TREE})`)
    expect(await texts(ui)).not.toContain('opening your review')
    expect(await isInverse()).toBe(false)
    expect(w.prompts).toEqual([])  // the busy Accept sent nothing
    await ui.unmount()
  })

  test('a pressed ratification Open shows its step in its hover hint: the row gains nothing', async ($, on) => {
    const ratifications = [{ id: 'p-rat1', cr: 'p-cr0', title: 'Ratify: Move the clock', tip: sha(6), baseTip: sha(5), review: null }]
    const { w, ui, clock } = await queued($, on, [], repo(), { ratifications })
    const rowChildren = async () => ((await ui.find({ key: 'ratify-p-rat1' })) as { children?: unknown[] }).children?.length
    const calm = await rowChildren()
    let release = () => {}
    w.hold = { verb: 'board review', until: new Promise<void>(resolve => { release = resolve }) }
    await ui.press({ key: 'ratify-p-rat1-open' })
    await clock.settle()
    const drawn = (await texts(ui)).split('\n')
    expect(drawn).toContain('Open · opening your review…')  // the button's hover hint, at the pane's bottom
    expect(drawn[drawn.indexOf('Ratify: Move the clock') + 1]).not.toContain('opening your review')
    expect(await rowChildren()).toBe(calm)
    release()
    w.hold = null
    await clock.settle()
    await ui.unmount()
  })

  test('view=result sets no view: the walk-through request is sent', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', view: 'result', title: 'Remove X' })], r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual(["Walk me through p-cr1's result (Remove X)."])
    expect(boardCalls(w, 'review')).toEqual([])
    expect(r.opened).toEqual([])
    await ui.unmount()
  })

  test('a design has no branch: its button is Walk through, and it sends the walk-through request', async ($, on) => {
    const r = repo()
    const design = cr({ id: 'p-cr1', title: 'Design Y', checkpoint: 'user', tip: null, baseTip: null, worktree: null })
    const { ui, clock, w } = await queued($, on, [design], r)
    expect((await ui.find({ key: 'cr-open-p-cr1' }))?.text).toBe('Walk through')
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual(["Walk me through p-cr1's design (Design Y)."])
    expect(w.toasts).toEqual([])
    expect(boardCalls(w, 'review')).toEqual([])
    await ui.unmount()
  })

  test('the button reads Walk through for a result view and Open for code', async ($, on) => {
    const { ui } = await queued($, on, [cr({ id: 'p-code' }), cr({ id: 'p-res', view: 'result' })])
    expect((await ui.find({ key: 'cr-open-p-code' }))?.text).toBe('Open')
    expect((await ui.find({ key: 'cr-open-p-res' }))?.text).toBe('Walk through')
    await ui.unmount()
  })

  const IN_VIEW = { opened: sha(2), edited: false, files: [] }
  const shownOpen = async (ui: any, id: string) => { await ui.press({ key: `cr-${id}-show` }) }

  test('a request open for your review says so in its opened summary; edited adds to it', async ($, on) => {
    const { ui, clock } = await queued($, on, [cr({ id: 'p-cr1', review: IN_VIEW }), cr({ id: 'p-cr3', review: { ...IN_VIEW, edited: true, files: ['a.ts'] } })])
    const summary = async (id: string) => { await shownOpen(ui, id); await clock.settle(); const drawn = await texts(ui); await shownOpen(ui, id); await clock.settle(); return drawn }
    expect(await summary('p-cr1')).toContain('· in review\n')
    expect(await summary('p-cr3')).toContain('· in review, edited\n')
    await ui.unmount()
  })

  test('the row mark follows the board: once it reports no review, nothing is said', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', review: IN_VIEW })])
    await shownOpen(ui, 'p-cr1')
    await clock.settle()
    expect(await texts(ui)).toContain('in review')
    w.crs = [cr({ id: 'p-cr1' })]  // accepted or returned: the board's opened tip is gone
    await clock.advance(60_000)
    await clock.settle()
    expect(await texts(ui)).not.toContain('in review')
    await ui.unmount()
  })

  test('a request open for your review says so on its row and in the /console text; edited adds to it; others do not', async ($, on) => {
    const { ui } = await queued($, on, [cr({ id: 'p-cr1', review: { ...IN_VIEW, edited: true, files: ['a.ts'] } }), cr({ id: 'p-cr2' })])
    const drawn = await texts(ui)
    expect(drawn.match(/in review, edited/g)).toHaveLength(1)
    expect(drawn.indexOf('in review, edited')).toBeLessThan(drawn.indexOf('p-cr2'))
    const text = consoleText({ session: 's', role: 'lead', actor: 'a', tool: 'claude' }, { ...parseBoardConsole({ ...BOARD_CONSOLE_CONTRACT, crs: [cr({ id: 'p-cr1', review: IN_VIEW })] }), agents: [], scratch: null, error: null }, null, false, [])
    expect(text).toContain('in review')
    await ui.unmount()
  })
})

describe('scratch line', () => {
  const LINE = 'scratch: 3 trashed (1.0 GB), the first is deleted within 7 days (scratch restore)'
  const lineOf = async (init: Parameters<typeof world>[1], $: any, on: any) => {
    const { ui, clock, w } = await queued($, on, [], repo(), init)
    return { ui, clock, w, drawn: await texts(ui) }
  }

  test('the line shows as one line, with no button', async ($, on) => {
    const { ui, drawn } = await lineOf({ scratch: { line: `${LINE}\n`, exit: 0 } }, $, on)
    expect(drawn).toContain(LINE)
    expect(await ui.find({ key: 'scratch-sweep' })).toBeUndefined()
    await ui.unmount()
  })

  test('an empty line shows nothing', async ($, on) => {
    const { ui, drawn } = await lineOf({ scratch: { line: '\n', exit: 0 } }, $, on)
    expect(drawn).not.toContain('scratch')
    expect(await ui.find({ key: 'scratch-sweep' })).toBeUndefined()
    await ui.unmount()
  })

  test('a failing or missing scratch shows nothing, and no error row', async ($, on) => {
    const failing = await lineOf({ scratch: { line: LINE, exit: 1 } }, $, on)
    expect(failing.drawn).not.toContain(LINE)
    expect(await failing.ui.find({ key: 'scratch-sweep' })).toBeUndefined()
    expect(failing.drawn).not.toContain('boom')
    await failing.ui.unmount()
  })

  test('a missing scratch shows nothing', async ($, on) => {
    const { ui, drawn } = await lineOf({}, $, on)
    expect(drawn).not.toContain('scratch')
    await ui.unmount()
  })
})

describe('Accept, Return', () => {
  /** The board's `review` for a request open for your review since the tip `opened`. */
  const viewAt = (opened: string, over: Record<string, unknown> = {}) => ({ opened, edited: false, files: [], ...over })
  const landLine = (n: number) => `board cr land p-cr1 --tip ${short(n)}`

  test('Accept of a request not open for review names its own tip and the board command that lands it', async ($, on) => {
    const { ui, clock, w, r } = await queued($, on, [cr({ id: 'p-cr1', title: 'Remove X', tip: sha(4) })])
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual([`Accept p-cr1 (Remove X): land it with \`${landLine(4)}\`.`])
    expect(r.all).toEqual([])  // the pane reads the board's JSON only, never git
    await ui.unmount()
  })

  test('another request\'s view is not this one\'s: only this row\'s own review counts', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', tip: sha(4) }), cr({ id: 'p-cr2', review: viewAt(sha(2), { edited: true, files: ['a.ts'] }) })])
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual([`Accept p-cr1 (Title of p-cr1): land it with \`${landLine(4)}\`.`])
    await ui.unmount()
  })

  describe('fails closed: a review the board showed but could not read', () => {
    test('Accept and Return send and fill nothing; the person is told', async ($, on) => {
      const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', tip: sha(4), review: viewAt(sha(4), { edited: null }) })])
      await ui.press({ key: 'cr-accept-p-cr1' })
      await clock.settle()
      await ui.press({ key: 'cr-return-p-cr1' })
      await clock.settle()
      expect(w.prompts).toEqual([])
      expect(w.box).toBe('')
      expect(w.toasts.filter(one => one.startsWith('Change request: p-cr1: the board could not read your review'))).toHaveLength(2)
      await ui.unmount()
    })

    test('edits with no worktree to name say so', async ($, on) => {
      const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', worktree: null, review: viewAt(sha(2), { edited: true, files: ['a.ts'] }) })])
      await ui.press({ key: 'cr-accept-p-cr1' })
      await clock.settle()
      expect(w.prompts).toEqual([])
      expect(w.toasts.some(one => one.includes('has no worktree to name your review from'))).toBe(true)
      await ui.unmount()
    })
  })

  test('a design checkpoint for you is accepted as a design: nothing lands', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', checkpoint: 'user', title: 'Design Y' })])
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual([`Accept the design of p-cr1 (Design Y) at ${short(2)}: planning continues in the same request, nothing lands.`])
    await ui.unmount()
  })

  test('accepting a design with no branch sends no sha', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', checkpoint: 'user', title: 'Design Y', tip: null, baseTip: null, worktree: null })])
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual(['Accept the design of p-cr1 (Design Y): planning continues in the same request, nothing lands.'])
    expect(w.toasts).toEqual([])
    await ui.unmount()
  })

  test('a code request with no branch tip still refuses its Accept', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', tip: null })])
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual([])
    expect(w.toasts.at(-1)).toContain('has no branch tip')
    await ui.unmount()
  })

  test('Return puts the request with room for your changes; a draft is kept', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', title: 'Remove X' })])
    await ui.press({ key: 'cr-return-p-cr1' })
    await clock.settle()
    expect(w.box).toBe('Return p-cr1 (Remove X): ')
    w.box = 'my words'
    await ui.press({ key: 'cr-return-p-cr1' })
    await clock.settle()
    expect(w.box.startsWith('my words\nReturn p-cr1')).toBe(true)
    expect(w.prompts).toEqual([])
    await ui.unmount()
  })

  test('Accept with edits in the review names them and the exact board cr edits line (the opened tip, no --from); no new button', async ($, on) => {
    const { ui, clock, w, r } = await queued($, on, [cr({ id: 'p-cr1', title: 'Remove X', tip: sha(2), review: viewAt(sha(2), { edited: true, files: ['a.ts'] }) })])
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    const prompt = w.prompts.join('\n')
    expect(prompt).toContain(`Accept p-cr1 (Remove X) at ${short(2)}`)
    expect(prompt).toContain(`board cr edits p-cr1 --tip ${sha(2)}`)
    expect(prompt).toContain(`I edited it in the review folder ${CR_TREE}`)
    expect(prompt).toContain('--commit -m')
    expect(prompt).toContain('board cr land p-cr1 --tip')
    expect(prompt).not.toContain('--from')
    expect(r.all).toEqual([])
    expect(await ui.find({ key: 'cr-done-p-cr1' })).toBeUndefined()
    await ui.unmount()
  })

  test('Return with edits says they are committed without a check and gives the --commit line; the words stay yours', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', title: 'Remove X', tip: sha(2), review: viewAt(sha(2), { edited: true }) })])
    await ui.press({ key: 'cr-return-p-cr1' })
    await clock.settle()
    expect(w.box).toContain(`Return p-cr1 (Remove X) with my edits from the review folder ${CR_TREE}`)
    expect(w.box).toContain(`board cr edits p-cr1 --tip ${sha(2)} --commit -m`)
    expect(w.box).not.toContain('--from')
    expect(w.box.endsWith(': ')).toBe(true)
    await ui.unmount()
  })

  test('edits the board recorded are not pending: the review the board shows is unedited, so Accept names the tip and no edits', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', tip: sha(9), review: viewAt(sha(9)) })])
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual([`Accept p-cr1 (Title of p-cr1): land it with \`${landLine(9)}\`.`])
    await ui.unmount()
  })

  test('your commits after the opened tip are pending edits: the line names the opened tip, the board records them', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', tip: sha(12), review: viewAt(sha(9), { edited: true, files: ['a.ts'] }) })])
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts.join('\n')).toContain(`at ${short(9)}`)
    expect(w.prompts.join('\n')).toContain(`board cr edits p-cr1 --tip ${sha(9)}`)
    await ui.unmount()
  })


  test('a targeted or no-gate result reads as what it was, never as a full check', () => {
    const checked = (over: Record<string, unknown>) => cr({ id: 'p-cr1', check: { state: 'current', tip: sha(2), baseTip: sha(1), at: null, result: 'pass', newFailures: null, baseCount: null, tipCount: null, ...over } }) as unknown as ConsoleCr
    expect(crCheckText(checked({ kind: 'targeted', command: 'pnpm test a' }))).toBe('targeted check current')
    expect(crCheckText(checked({ kind: 'targeted', command: 'pnpm test a', state: 'failed', result: 'fail' }))).toBe('targeted check failed')
    expect(crCheckText(checked({ kind: 'none', reason: 'docs only' }))).toBe('no check run')
    expect(crCheckText(checked({ kind: 'full' }))).toBe('checks current')
    expect(crDetailsText(checked({ kind: 'targeted', command: 'pnpm test a' }))).toContain('ran: pnpm test a')
    expect(crDetailsText(checked({ kind: 'none', reason: 'docs only' }))).toContain('no check: docs only')
  })

  test('without a prompt box the press says so', async ($, on) => {
    const { ui, clock, w } = await queued($, on, WAITING())
    w.hasBox = false
    await ui.press({ key: 'cr-return-p-cr1' })
    await clock.settle()
    expect(w.toasts.at(-1)).toContain('the prompt box is not available')
    await ui.unmount()
  })

  test('the console never lands or writes git: no press runs a git change, and the board runs only review open', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', review: { opened: sha(2), edited: true, files: ['a.ts'] } }), cr({ id: 'p-cr2', view: 'result' })], r)
    for (const key of ['cr-open-p-cr1', 'cr-accept-p-cr1', 'cr-return-p-cr1', 'cr-open-p-cr2', 'cr-accept-p-cr2', 'cr-return-p-cr2']) {
      await ui.press({ key })
      await clock.settle()
    }
    expect(r.all).toEqual([])
    expect(w.calls.filter(one => one.argv[0]?.endsWith('/bin/board')).map(one => one.argv[1]).filter(verb => verb !== 'console')).toEqual(['review'])
    expect(w.commands.filter(one => /land|reject|refresh/.test(one.command))).toEqual([])
    await ui.unmount()
  })
})

describe('change requests in the /console text', () => {
  const text = async ($: any, ui: any, clock: any) => {
    await ui.unmount()
    const ran = await $.command.run({ command: 'console', args: '', origin: { kind: 'bridge' }, presentation: { isFullscreen: true, columns: 160 } })
    await clock.settle()
    return ran.text as string
  }
  const PRESSES = /Open|Accept|Return|Refresh/

  test('the stack, each request\'s state, and the ratifications: no press labels', async ($, on) => {
    const { ui, clock } = await queued($, on, [...BOARD_CONSOLE_CONTRACT.crs] as unknown as Crs, repo(), { ratifications: [...BOARD_CONSOLE_CONTRACT.ratifications] })
    const out = await text($, ui, clock)
    expect(out).toContain('Change requests')
    expect(out).toContain('  p-cr1  Remove the legacy cache · to accept · P2 · unblocks 14 · 1.0-beta scope · checks current · 0 new (base 3012, tip 2972) · look before · code')
    expect(out).toContain('    p-cr2  Drop the cache config · checkpoint review · P2 · stale · 2 new: src/a.ts TS2322, src/b.ts TS2345 (base 3012, tip 3014) · look after · result · held by a1b2')
    expect(out).toContain('To ratify\n  p-rat1  Ratify: Move the clock · landed in p-cr0')
    expect(out.split('\n').filter(line => line.includes('p-cr')).join('\n')).not.toMatch(PRESSES)
  })

  test('the request open for your review is named, with whether you edited it', async ($, on) => {
    const { ui, clock } = await queued($, on, [cr({ id: 'p-cr1', review: { opened: sha(2), edited: true, files: ['a.ts'] } })])
    expect(await text($, ui, clock)).toContain('· in review, edited')
  })

  test('no requests: no section', async ($, on) => {
    const { ui, clock } = await queued($, on, [])
    expect(await text($, ui, clock)).not.toMatch(/^Change requests/m)
  })
})

describe('counts', () => {
  test('each count is ready now plus (k wait); the labels follow the step', async ($, on) => {
    const { ui } = await queued($, on, [])
    const drawn = await texts(ui)
    for (const part of ['questions', '186 (2 held)', 'to plan', '0 (57 wait)', 'to review', 'to accept', '13 (1 wait)', 'to ratify', 'for you', '3']) expect(drawn, part).toContain(part)
    expect(drawn).not.toContain('in review')
    await ui.unmount()
  })

  test('countText omits the suffix without waiting items', () => {
    expect(countText({ ready: 4, held: 0, waiting: 0 })).toBe('4')
    expect(countText({ ready: 0, held: 0, waiting: 57 })).toBe('0 (57 wait)')
    expect(countText({ ready: 1, held: 2, waiting: 0 })).toBe('1 (2 held)')
    expect(countText({ ready: 1, held: 2, waiting: 3 })).toBe('1 (2 held, 3 wait)')
    expect(countText(undefined)).toBe('0')
  })

  test('the /console text prints the same labels', () => {
    const text = consoleText({ session: 's', role: 'lead', actor: 'a', tool: 'claude' }, { isMissing: false, counts: { ...COUNTS, toDesign: { ready: 6, held: 1, waiting: 0 }, toImplement: { ready: 90, held: 1, waiting: 1 } }, forYou: [], items: [], sessions: [], held: [], crs: [], queued: 0, waitingOnYou: 0, prefix: null, ratifications: [], agents: [], scratch: null, sync: null, queues: null, error: null }, null, false, [])
    expect(text).toContain('you: for you 3 · to accept 13 (1 wait) · to ratify 1 · decided 0 · questions 186 (2 held)')
    expect(text).toContain('agents: to plan 0 (57 wait) · to design 6 (1 held) · to implement 90 (1 held, 1 wait) · to review 0')
  })

  test('the engine counts parse as ready/waiting; a bare number reads as all ready', () => {
    const round = parseRound({ version: 1, counts: { questions: { ready: 2, held: 4, waiting: 1 }, toPlan: 5 } })
    expect(round.counts).toMatchObject({ questions: { ready: 2, held: 4, waiting: 1 }, toPlan: { ready: 5, held: 0, waiting: 0 }, toAccept: { ready: 0, held: 0, waiting: 0 }, toRatify: { ready: 0, held: 0, waiting: 0 } })
  })
})

describe('what holds a request up', () => {
  test('a fresh request says nothing more', () => {
    expect(crMarks(cr({ id: 'p-cr1' }) as unknown as ConsoleCr)).toEqual([])
  })

  test('the board\'s problems in its order (land blocked: three paths at most, the check left to the check text), then a hold, then lands-with', () => {
    const marks = crMarks(cr({ id: 'p-cr1', holder: 'b2c3', after: 'p-cr0', problems: [
      { kind: 'setup-failed', text: 'setup failed', next: { action: 'claim' } }, REFRESH('p-cr1'),
      { kind: 'land-blocked', text: 'land blocked: a, b, c, d', next: { action: 'ask-user', paths: ['a', 'b', 'c', 'd'] } }] }) as unknown as ConsoleCr)
    expect(marks).toEqual([
      { text: 'setup failed', isProblem: true }, { text: 'land blocked: a, b, c, …', isProblem: true },
      { text: 'held by b2c3', isProblem: false, isWarning: true }, { text: 'lands with p-cr0', isProblem: false },
    ])
  })

  test('lands-with names the short id under the board prefix', () => {
    const one = cr({ id: 'p-cr2', after: 'p-cr1' }) as unknown as ConsoleCr
    expect(crMarks(one, 'p')).toEqual([{ text: 'lands with cr1', isProblem: false }])
    expect(crDetailsText(one, 'p')).toContain('lands with cr1')
  })

  test('problems stay on the request row; lands-with waits in the opened summary', async ($, on) => {
    const { ui, clock } = await queued($, on, [cr({ id: 'p-cr1', problems: [BLOCKED(['src/x.ts']), { kind: 'setup-failed', text: 'setup failed', next: { action: 'claim' } }, { kind: 'review-stale', text: 'review stale', next: { action: 'wait' } }] }), cr({ id: 'p-cr2', status: 'in_review', base: 'p-cr1', parent: 'p-cr1', after: 'p-cr1' })])
    const all = await texts(ui)
    for (const part of ['land blocked: src/x.ts', 'setup failed', 'review stale']) expect(all, part).toContain(part)
    expect(all).not.toContain('lands with p-cr1')
    await ui.press({ key: 'cr-p-cr2-show' })
    await clock.settle()
    const opened = await texts(ui)
    expect(opened).toContain('lands with p-cr1')
    await ui.unmount()
  })
})

describe('a stale review', () => {
  test('a request waiting for its Accept says so; the board decides whether it is refresh work', () => {
    const stale = cr({ id: 'p-cr1', problems: [{ kind: 'review-stale', text: 'review stale', next: { action: 'refresh', command: 'board cr refresh p-cr1' } }] }) as unknown as ConsoleCr
    expect(crMarks(stale)).toEqual([{ text: 'review stale', isProblem: true }])
    expect(canUpdateCr(stale, false, ['review'])).toBe(true)
    expect(canUpdateCr(stale, true, [])).toBe(true)
    expect(canUpdateCr(stale, false, ['implement'])).toBe(false)
    expect(canUpdateCr(cr({ id: 'p-cr2', problems: [{ kind: 'review-stale', text: 'review stale', next: { action: 'wait' } }] }) as unknown as ConsoleCr, true, ['review'])).toBe(false)  // stale, not the queue head
  })

  test('a hold marks only a request waiting for the Accept', () => {
    expect(crMarks(cr({ id: 'p-cr1', status: 'in_review', holder: 'b2c3' }) as unknown as ConsoleCr)).toEqual([])
  })
})

describe('request rows', () => {
  const WIDE = { ...PANE_PROPS, bodyColumns: 200 }
  const NARROW = { ...PANE_PROPS, bodyColumns: 50 }
  const mounted = async ($: any, on: any, crs: Crs, props: typeof PANE_PROPS, init: Parameters<typeof world>[1] = {}) => {
    const made = world(on, { round: NO_ROUND, crs, ...init })
    made.w.git = git(repo())
    await ready($, made.clock)
    const ui: Mounted = await $.ui.mount({ ...PANE, surface: 'terminal', props })
    return { ...made, ui }
  }
  const children = (found: { children: unknown[] } | undefined) => JSON.stringify(found?.children)
  const ui_line2 = async (ui: Mounted, id: string) => (await ui.find({ key: `cr-${id}-line2` }))?.text ?? ''

  test('two lines: the title and the buttons at the right edge so Accept and Return line up, then the id and the facts', async ($, on) => {
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1', unblocks: 14, unblocksDirect: 7, milestone: '1.0-beta scope' }), cr({ id: 'p-cr2', view: 'result' })], WIDE)
    for (const id of ['p-cr1', 'p-cr2']) {
      const first = (await ui.find({ key: `cr-${id}-line1` }))?.text ?? ''
      expect(first, id).toContain(`Title of ${id}`)
      expect(first, `${id} line one`).not.toContain('checks current')
      expect(children(await ui.find({ key: `cr-${id}-line1` })), id).toContain(`cr-accept-${id}`)
      const line = (await ui.find({ key: `cr-${id}-line2` }))?.text ?? ''
      const at = (part: string) => line.indexOf(part)
      expect(children(await ui.find({ key: `cr-${id}-line2` })), id).not.toContain(`cr-accept-${id}`)
      const places = [id, ...(id === 'p-cr1' ? ['unblocks 14', '1.0-beta scope'] : [])].map(at)
      expect(places.every(place => place >= 0), id).toBe(true)
      expect(places, id).toEqual([...places].sort((a, b) => a - b))
      expect((await ui.find({ key: `cr-${id}-buttons` }))?.props, id).toMatchObject({ width: id === 'p-cr1' ? 22 : 30, flexShrink: 0 })  // Open • Accept • Return; Walk through • Accept • Return
    }
    await ui.unmount()
  })

  test('the buttons are as wide as their labels and sit at the right edge', async ($, on) => {
    const code = await mounted($, on, [cr({ id: 'p-cr1' })], WIDE)
    expect((await code.ui.find({ key: 'cr-p-cr1-buttons' }))?.props.width).toBe(22)
    await code.ui.unmount()
  })

  test('the title keeps line one to itself and truncates only at the pane edge, however narrow the pane', async ($, on) => {
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1', unblocks: 3, unblocksDirect: 1, milestone: 'M' })], NARROW)
    expect((await ui.find({ key: 'cr-p-cr1-title' }))?.props).toMatchObject({ flexShrink: 1, flexGrow: 1 })
    expect(children(await ui.find({ key: 'cr-p-cr1-line1' }))).toContain('cr-accept-p-cr1')
    expect(children(await ui.find({ key: 'cr-p-cr1-line2' }))).not.toContain('cr-accept-p-cr1')
    await ui.unmount()
  })

  test('a bar in the first cell of the title line marks each request and shows its kind: design, code, or in work', async ($, on) => {
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1' }), cr({ id: 'p-cr2', checkpoint: 'user', tip: null, baseTip: null }), cr({ id: 'p-cr3', status: 'in_progress' })], WIDE)
    for (const id of ['p-cr1', 'p-cr2', 'p-cr3']) {
      expect((await ui.find({ key: `cr-${id}-bar1` }))?.text, id).toBe('▌')
      expect((await ui.find({ key: `cr-${id}-bar2` }))?.text, `${id} line two`).toBe(' ')  // the second line only keeps the cell
    }
    const color = async (id: string) => ((await ui.find({ key: `cr-${id}-bar1` }))?.children?.[0] as { props: { color?: string } } | undefined)?.props.color
    expect([await color('p-cr1'), await color('p-cr2'), await color('p-cr3')]).toEqual(['claude', 'planMode', 'success'])  // code, design, in work
    expect(await texts(ui)).toContain('in work')  // the stage the legend's word cannot give, on the bar's hover
    await ui.unmount()
  })

  test('the priority and unblocks stand in columns as wide as the widest request, so what follows starts at one cell', async ($, on) => {
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1' }), cr({ id: 'p-cr2', checkpoint: 'user', tip: null, baseTip: null, unblocks: 14, unblocksDirect: 7 })], WIDE)
    for (const id of ['p-cr1', 'p-cr2']) {
      expect((await ui.find({ key: `cr-${id}-col-priority` }))?.props.width, `${id} priority`).toBe('P2'.length + 2)
      expect((await ui.find({ key: `cr-${id}-col-unblocks` }))?.props.width, `${id} unblocks`).toBe('unblocks 14'.length + 2)  // blank on the request without one
    }
    expect(await ui.find({ key: 'cr-p-cr1-unblocks' })).toBeUndefined()
    expect(await ui.find({ key: 'cr-p-cr1-leader' })).toBeUndefined()
    await ui.unmount()
  })

  test('the title is bold, the milestone dim, Open is the accent and Accept and Return are dim', async ($, on) => {
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1', milestone: '1.0-beta' }), cr({ id: 'p-cr2', problems: [BLOCKED(['src/a.ts'])] })], WIDE)
    const title = async (id: string) => (await ui.findAll({ type: 'Text' })).find(one => one.text === `Title of ${id}`)?.props
    for (const id of ['p-cr1', 'p-cr2']) expect((await title(id))?.bold, id).toBe(true)
    expect((await (await ui.findAll({ type: 'Text' })).find(one => one.text === '1.0-beta'))?.props.dimColor).toBe(true)
    for (const [key, isDim] of [['cr-open-p-cr1', false], ['cr-return-p-cr1', true], ['cr-accept-p-cr1', true]] as const) expect(!!(await ui.find({ key }))?.props.dimColor, key).toBe(isDim)
    await ui.unmount()
  })

  test('the id sits on line two, dim, in front of the facts', async ($, on) => {
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1' })], WIDE)
    expect(children(await ui.find({ key: 'cr-p-cr1-line1' }))).not.toContain('cr-p-cr1-idbox')
    expect(children(await ui.find({ key: 'cr-p-cr1-line2' }))).toContain('cr-p-cr1-idbox')
    await ui.unmount()
  })

  test('unblocks N shows only above zero, and its hover adds the direct count', async ($, on) => {
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1', unblocks: 14, unblocksDirect: 7 }), cr({ id: 'p-cr2' })], WIDE)
    const drawn = await texts(ui)
    expect(drawn.split('\n').filter(one => one.startsWith('unblocks '))).toEqual(['unblocks 14'])
    expect(drawn).toContain('p-cr1 unblocks 14 open items in all, 7 waiting on it directly')
    expect(drawn).not.toContain('p-cr2 unblocks')
    await ui.unmount()
  })

  test('the milestone title shows when there is one', async ($, on) => {
    const wide = await mounted($, on, [cr({ id: 'p-cr1', milestone: '1.0-beta scope' }), cr({ id: 'p-cr2' })], WIDE)
    expect(await texts(wide.ui)).toContain('1.0-beta scope')
    expect((await ui_line2(wide.ui, 'p-cr2'))).not.toContain('1.0-beta')
    await wide.ui.unmount()
  })

  test('a long milestone title is cut to what the line has left, not wrapped', async ($, on) => {
    const long = 'A-milestone-title-without-spaces-far-longer-than-any-narrow-pane-could-ever-show-in-one-line'  // no space at the cut, which fitText would trim
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1', milestone: long })], { ...PANE_PROPS, bodyColumns: 90 })
    const shown = (await texts(ui)).split('\n').find(one => one.startsWith('A-milestone')) ?? ''
    expect(shown.endsWith('…') && shown.length < long.length).toBe(true)
    expect(shown.length).toBe(90 - 1 - 7 - (2 + 3) - 1)  // pane minus the bar, the id column (p-cr1 and a gap), the column (P2 with its divider and gap) and a spare cell; a current check has no right group
    await ui.unmount()
  })

  test('line two wraps when its facts do not fit; a cut milestone keeps its full title on hover', async ($, on) => {
    const long = 'A milestone with a title that is far longer than any narrow pane could ever show in one line'
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1', unblocks: 14, unblocksDirect: 7, milestone: long, problems: [BLOCKED(['src/aaaa.ts', 'src/bbbb.ts'])] }), cr({ id: 'p-cr2', milestone: 'Short' })], { ...PANE_PROPS, bodyColumns: 90 })
    expect((await ui.find({ key: 'cr-p-cr1-facts' }))?.props).toMatchObject({ flexWrap: 'wrap', flexGrow: 1 })
    const line = (await ui.find({ key: 'cr-p-cr1-line2' }))?.text ?? ''
    for (const part of ['unblocks 14', 'land blocked: src/aaaa.ts, src/bbbb.ts']) expect(line, part).toContain(part)
    expect(children(await ui.find({ key: 'cr-p-cr1-line1' }))).toContain('cr-accept-p-cr1')
    expect(await ui.find({ key: 'cr-p-cr1-milestone-box' })).toBeDefined()
    expect(await texts(ui)).toContain(`p-cr1 belongs to: ${long}`)
    expect(await ui.find({ key: 'cr-p-cr2-milestone-box' })).toBeUndefined()  // a milestone shown whole has no hover
    expect(await texts(ui)).not.toContain('p-cr2 belongs to')
    await ui.unmount()
  })

  test('the banner counts what waits for you, what is in work and what is queued; queued requests are no rows', async ($, on) => {
    const { ui } = await queued($, on, [cr({ id: 'p-a' }), cr({ id: 'p-b' }), cr({ id: 'p-c', status: 'in_review' })], repo(), { queued: 97 })
    expect((await ui.find({ key: 'cr-banner' }))?.text).toContain('2 to accept · 1 in work · 97 queued')
    expect(await ui.find({ key: 'cr-p-a' })).toBeDefined()
    await ui.unmount()
  })

  test('zero parts of the banner are left out', async ($, on) => {
    const { ui } = await queued($, on, [cr({ id: 'p-c', status: 'in_progress', holder: 'a1' })], repo(), { queued: 0 })
    const banner = (await ui.find({ key: 'cr-banner' }))?.text ?? ''
    expect(banner).toContain('1 in work')
    for (const part of ['to accept', 'queued', '0']) expect(banner, part).not.toContain(part)
    await ui.unmount()
  })

  test('only queued requests: the banner says how many and no row is drawn', async ($, on) => {
    const { ui } = await queued($, on, [], repo(), { queued: 12 })
    expect((await ui.find({ key: 'cr-banner' }))?.text).toContain('12 queued')
    expect(await ui.find({ key: 'cr-rows' })).toBeUndefined()
    await ui.unmount()
  })

  test('only requests waiting on your answers: the banner says how many', async ($, on) => {
    const { ui } = await queued($, on, [], repo(), { waitingOnYou: 3 })
    expect((await ui.find({ key: 'cr-banner' }))?.text).toContain('3 wait on your answers')
    expect(await ui.find({ key: 'cr-rows' })).toBeUndefined()
    await ui.unmount()
  })

  test('the /console text shows the block when only waiting-on-you is non-zero', () => {
    const board = { isMissing: false, counts: null, forYou: [], items: [], sessions: [], held: [], queued: 0, waitingOnYou: 3, prefix: null, crs: [], ratifications: [], agents: [], sync: null, queues: null, error: null }
    expect(consoleText({ session: 's', role: 'lead', actor: 'a', tool: 'claude' }, board as unknown as ConsoleBoard, null, false, [])).toContain('Change requests · 3 wait on your answers')
  })

  test('the /console text names the same parts', () => {
    const board = { isMissing: false, counts: null, forYou: [], items: [], sessions: [], held: [], queued: 92, waitingOnYou: 5, prefix: null, crs: [cr({ id: 'p-cr1' }), cr({ id: 'p-cr2', status: 'in_review' })] as unknown as ConsoleCr[], ratifications: [], agents: [], sync: null, queues: null, error: null }
    const text = consoleText({ session: 's', role: 'lead', actor: 'a', tool: 'claude' }, board as unknown as ConsoleBoard, null, false, [])
    expect(text).toContain('Change requests · 1 to accept · 1 in work · 5 wait on your answers · 92 queued')
    expect(consoleText({ session: 's', role: 'lead', actor: 'a', tool: 'claude' }, { ...board, crs: [], queued: 0, waitingOnYou: 0 } as unknown as ConsoleBoard, null, false, [])).not.toContain('Change requests')
  })

  test('the right edge of line two holds the problem marks, then the new-failure count, then the check state, flush right; a current check is not shown', async ($, on) => {
    const check = (state: string, over: Record<string, unknown> = {}) => ({ state, kind: 'full', tip: sha(2), baseTip: sha(1), at: null, result: 'fail', newFailures: null, baseCount: null, tipCount: null, ...over })
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1', problems: [BLOCKED(['src/a.ts'])], check: check('conflict', { newFailures: ['x TS1'] }) } as never), cr({ id: 'p-cr2', check: check('stale') } as never), cr({ id: 'p-cr3' })], WIDE)
    const line = async (id: string) => (await ui.find({ key: `cr-${id}-line2` }))?.text ?? ''
    const [one, two, three] = [await line('p-cr1'), await line('p-cr2'), await line('p-cr3')]
    expect(one.indexOf('land blocked: src/a.ts')).toBeLessThan(one.indexOf('1 new'))
    expect(one.indexOf('1 new')).toBeLessThan(one.indexOf('conflict'))
    expect(await ui.find({ key: 'cr-p-cr3-right' })).toBeUndefined()  // nothing to show, nothing reserved
    expect((await ui.find({ key: 'cr-p-cr2-right' }))?.props).toMatchObject({ flexShrink: 0 })
    expect(three).not.toContain('checks current')
    await ui.unmount()
  })

  test('words: unblocks text, hover and cut', () => {
    const one = cr({ id: 'p-cr1', unblocks: 14, unblocksDirect: 7 }) as unknown as ConsoleCr
    expect(crUnblocksText(one)).toBe('unblocks 14')
    expect(crUnblocksText(cr({ id: 'p-cr1' }) as unknown as ConsoleCr)).toBeNull()
    expect(crUnblocksHint(one)).toBe('p-cr1 unblocks 14 open items in all, 7 waiting on it directly')
    expect(fitText('abcdef', 4)).toBe('abc…')
    expect(fitText('abc', 4)).toBe('abc')
    expect(fitText('abcdef', 0)).toBe('a…')
  })

  test('the /console text row names unblocks and the milestone', () => {
    const board = { isMissing: false, counts: null, forYou: [], items: [], sessions: [], held: [], queued: 0, waitingOnYou: 0, prefix: null, crs: [cr({ id: 'p-cr1', unblocks: 14, unblocksDirect: 7, milestone: '1.0-beta scope' }), cr({ id: 'p-cr2' })] as unknown as ConsoleCr[], ratifications: [], agents: [], sync: null, queues: null, error: null }
    const text = consoleText({ session: 's', role: 'lead', actor: 'a', tool: 'claude' }, board as unknown as ConsoleBoard, null, false, [])
    const [first, second] = ['p-cr1', 'p-cr2'].map(id => text.split('\n').find(line => line.includes(`${id}  `)) ?? '')
    expect(first).toContain('unblocks 14 · 1.0-beta scope')
    expect(second).not.toContain('unblocks')
  })

  test('every second request has a stripe behind its two lines; the first and the third have none', async ($, on) => {
    const { ui } = await mounted($, on, [1, 2, 3].map(n => cr({ id: `p-cr${n}` })), WIDE)
    const lines = async (n: number) => (await ui.find({ key: `cr-p-cr${n}-lines` }))?.props
    expect((await lines(1))?.backgroundColor).toBeUndefined()
    expect((await lines(2))?.backgroundColor).toBe('rgb(50,50,50)')
    expect((await lines(3))?.backgroundColor).toBeUndefined()
    await ui.unmount()
  })

  test('three requests show, the rest fold behind +N more, and the toggle shows them all', async ($, on) => {
    const five = [1, 2, 3, 4, 5].map(n => cr({ id: `p-cr${n}` }))
    const { ui } = await mounted($, on, five, WIDE)
    expect(await ui.find({ key: 'cr-p-cr3-show' })).toBeDefined()
    expect(await ui.find({ key: 'cr-p-cr4-show' })).toBeUndefined()
    expect((await ui.find({ key: 'crs-toggle' }))?.text).toBe('+2 more ▸')
    await ui.press({ key: 'crs-toggle' })
    expect(await ui.find({ key: 'cr-p-cr5-show' })).toBeDefined()
    expect((await ui.find({ key: 'crs-toggle' }))?.text).toBe('show fewer ▾')
    await ui.unmount()
  })

  test('the to-ratify list folds the same way, and holds its own toggle', async ($, on) => {
    const ratifications = [1, 2, 3, 4].map(n => ({ id: `p-rat${n}`, cr: 'p-cr0', title: `Ratify: ${n}` }))
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1' })], WIDE, { ratifications })
    expect(await ui.find({ key: 'ratify-p-rat3-show' })).toBeDefined()
    expect(await ui.find({ key: 'ratify-p-rat4-show' })).toBeUndefined()
    expect((await ui.find({ key: 'ratify-toggle' }))?.text).toBe('+1 more ▸')
    expect(await ui.find({ key: 'crs-toggle' })).toBeUndefined()
    await ui.unmount()
  })

  test('the board\'s own lists keep their cap of ten', async ($, on) => {
    const items = Array.from({ length: 11 }, (_, n) => ({ id: `tstdl-i${n}`, type: 'task', status: 'open', title: `Item ${n}`, holder: null }))
    const { ui } = await mounted($, on, [], WIDE, { items })
    expect(await ui.find({ key: 'item-tstdl-i9-show' })).toBeDefined()
    expect(await ui.find({ key: 'item-tstdl-i10-show' })).toBeUndefined()
    await ui.unmount()
  })

  test('the opened summary gains a details line: look, view, counts, and the failing files as editor links', async ($, on) => {
    const failing = cr({ id: 'p-cr1', look: 'after', view: 'result', worktree: '/main/.worktrees/p-cr1', check: { state: 'failed', tip: sha(2), baseTip: sha(1), at: null, result: 'fail', newFailures: ['src/a.ts TS2322', 'src/b.ts TS2345'], baseCount: 3012, tipCount: 3014 } })
    const { ui, clock } = await mounted($, on, [failing], WIDE)
    await ui.press({ key: 'cr-p-cr1-show' })
    await clock.settle()
    const drawn = await texts(ui)
    expect(drawn).toContain('look after · result')
    expect(drawn).toContain('base 3012, tip 3014')
    const links = await ui.findAll({ type: 'Link' })
    expect(links.map(one => one.props.href)).toEqual(['vscode://file/main/.worktrees/p-cr1/src/a.ts', 'vscode://file/main/.worktrees/p-cr1/src/b.ts'])
    expect(links.map(one => one.props.label)).toEqual(['src/a.ts TS2322', 'src/b.ts TS2345'])
    await ui.unmount()
  })

  test('no worktree, no links: the failing names show as text', async ($, on) => {
    const failing = cr({ id: 'p-cr1', worktree: null, check: { state: 'failed', tip: sha(2), baseTip: sha(1), at: null, result: 'fail', newFailures: ['src/a.ts TS2322'], baseCount: 1, tipCount: 2 } })
    const { ui, clock } = await mounted($, on, [failing], WIDE)
    await ui.press({ key: 'cr-p-cr1-show' })
    await clock.settle()
    expect(await ui.findAll({ type: 'Link' })).toEqual([])
    expect(await texts(ui)).toContain('src/a.ts TS2322')
    await ui.unmount()
  })
})

describe('priority, waiting on answers and the board prefix', () => {
  const lead = { session: 's', role: 'lead', actor: 'a', tool: 'claude' }
  const raised = cr({ id: 'p-cr1', priority: 1, ownPriority: 2, raisedBy: { id: 'p-x1', isItem: false } })

  test('the banner puts "wait on your answers" between in work and queued', async ($, on) => {
    const { ui } = await queued($, on, [cr({ id: 'p-a' }), cr({ id: 'p-c', status: 'in_progress', holder: 'a1' })], repo(), { queued: 92, waitingOnYou: 5 })
    expect((await ui.find({ key: 'cr-banner' }))?.text).toContain('1 to accept · 1 in work · 5 wait on your answers · 92 queued')
    await ui.unmount()
  })

  test('a row shows its effective priority dim on line two; a raised one explains itself on hover', async ($, on) => {
    const { ui } = await queued($, on, [raised, cr({ id: 'p-cr2' })])
    expect(await ui.find({ key: 'cr-p-cr1-line2' })).toBeDefined()
    expect((await ui.findAll({ type: 'Text' })).find((one: { text: string }) => one.text === 'P1')?.props).toMatchObject({ color: 'inactive' })
    expect((await ui.find({ key: 'cr-p-cr1-line2' }))?.text).toContain('P1')
    expect(await ui.find({ key: 'cr-p-cr1-priority-box' })).toBeDefined()
    const drawn = await texts(ui)
    expect(drawn).toContain('P2, counts as P1: blocks p-x1')
    expect(await ui.find({ key: 'cr-p-cr2-priority-box' })).toBeUndefined()  // its own priority stands: no hover
    expect(drawn).not.toContain('counts as P2')
    await ui.unmount()
  })

  test('words: the hover names the item when one of its own items sets the priority', () => {
    const own = cr({ id: 'p-cr1', priority: 0, ownPriority: 2, raisedBy: { id: 'p-i1', isItem: true } }) as unknown as ConsoleCr
    expect(crPriorityHint(own, null)).toBe('P2, counts as P0: its item p-i1')
    expect(crPriorityHint(own, 'p')).toBe('P2, counts as P0: its item i1')
    expect(crPriorityHint(cr({ id: 'p-cr1' }) as unknown as ConsoleCr, 'p')).toBeNull()
    expect(crPriorityHint(cr({ id: 'p-cr1', priority: 2, ownPriority: 2, raisedBy: { id: 'p-i1', isItem: true } }) as unknown as ConsoleCr, 'p')).toBeNull()
  })

  test('the pane leaves the board prefix off ids, presses keep the full id, another prefix stays', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', title: 'Long', children: ['p-cr2'] }), cr({ id: 'p-cr2', parent: 'p-cr1', base: 'p-cr1' }), cr({ id: 'o-cr7' })], repo(), { prefix: 'p', ratifications: [{ id: 'p-rat1', cr: 'p-cr0', title: 'Ratify: it' }] })
    const drawn = (await texts(ui)).split('\n')
    for (const id of ['cr1', 'cr2', 'rat1', 'o-cr7']) expect(drawn, id).toContain(id)
    expect(drawn).not.toContain('p-cr1')
    expect(drawn).toContain('cr1: open its summary here')
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts.join('\n')).toContain('Accept p-cr1 (')
    await ui.unmount()
  })

  test('the id column is as wide as the widest id shown and the ids are dim', async ($, on) => {
    const { ui } = await queued($, on, [cr({ id: 'p-cr1' }), cr({ id: 'p-cr22222' })], repo(), { prefix: 'p' })
    for (const id of ['p-cr1', 'p-cr22222']) expect((await ui.find({ key: `cr-${id}-idbox` }))?.props.width).toBe('cr22222'.length + 2)
    const id = (await ui.findAll({ type: 'Text' })).find((one: { text: string }) => one.text === 'cr1')
    expect(id?.props).toMatchObject({ color: 'inactive' })
    await ui.unmount()
  })

  test('the /console text drops the prefix too', () => {
    const board = { isMissing: false, counts: null, forYou: [], items: [], sessions: [], held: [], queued: 0, waitingOnYou: 0, prefix: 'p', crs: [raised, cr({ id: 'o-cr7' })] as unknown as ConsoleCr[], ratifications: [{ id: 'p-rat1', cr: 'p-cr0', title: 'T' }], agents: [], sync: null, queues: null, error: null }
    const text = consoleText(lead, board as unknown as ConsoleBoard, null, false, [])
    expect(text).toContain('  cr1  Title of p-cr1 · ')
    expect(text).toContain('  o-cr7  Title of o-cr7')
    expect(text).toContain('rat1  T · landed in cr0')
  })
})
