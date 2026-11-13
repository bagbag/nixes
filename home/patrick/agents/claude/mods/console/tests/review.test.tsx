// Change requests (r25): the queue section, the review tree set to a request's (base tip, tip), and the Open / Accept / Return /
// Refresh presses, which send requests as your message (Return fills the prompt; the console never lands); the counts display (r21-q141, q146).
import { describe, expect, test } from 'claude-code/testing'
import type { Mounted } from 'claude-code/testing'

import { BOARD_CONSOLE_CONTRACT, cr } from './board-console-contract'
import { COUNTS, NO_ROUND, PANE_PROPS, SESSION, world } from './fixture'
import { git, MAIN_TREE, repo, REVIEW_END_REF, REVIEW_TREE, sha, SNAPSHOT_DIR } from './review-world'
import type { Repo } from './review-world'
import { parseBoardConsole, parseRound } from '../hooks/engine'
import { canRefreshCr, consoleText, countText, crCheckText, crDetailsText, crFailuresText, crMarks, crPriorityHint, crRows, crUnblocksHint, crUnblocksText, fitText } from '../hooks/words'
import { parseWorktrees } from '../hooks/review'
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
/** `board cr edits --commit` made `commit` of the review tree's files and moved the tree's marker to it. */
const committed = (r: Repo, commit: string) => { r.end = commit; r.editsAt = commit }
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

  test('Refresh is a review session\'s press: absent in the lead console, absent where the checks are current', async ($, on) => {
    const stale = cr({ id: 'p-cr1', refreshWork: true, check: { state: 'stale', tip: sha(2), baseTip: sha(1), at: null, result: 'pass' } })
    const lead = await queued($, on, [stale])
    expect(await lead.ui.find({ key: 'cr-refresh-p-cr1' })).toBeUndefined()
    await lead.ui.unmount()
  })

  test('a review-pulling session sees Refresh only on the request the board marks as refresh work', async ($, on) => {
    const sessions = [{ session: SESSION, role: 'agent', actor: 'a1', pulls: ['review'], holds: 0, workers: null, state: 'active', idleSince: null, claimable: 0 }]
    const { ui, w, clock } = await queued($, on, [
      cr({ id: 'p-cr1', refreshWork: true, check: { state: 'conflict', tip: sha(2), baseTip: sha(1), at: null, result: 'pass' } }),
      cr({ id: 'p-cr2', check: { state: 'stale', tip: sha(2), baseTip: sha(1), at: null, result: 'pass' } }),
    ], repo(), { sessions, role: { session: SESSION, role: 'solo', actor: 'a1', tool: 'claude' } })
    expect(await ui.find({ key: 'cr-refresh-p-cr1' })).toBeDefined()
    expect(await ui.find({ key: 'cr-refresh-p-cr2' })).toBeUndefined()
    await ui.press({ key: 'cr-refresh-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual(["Refresh p-cr1 under the review protocol's Refresh."])
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
  test('view=code sets the review tree to the fork point and the tip, unstaged, and opens it', async ($, on) => {
    const r = repo({ workspaces: ['t.code-workspace'], fork: sha(7) })
    const { ui, clock } = await queued($, on, [cr({ id: 'p-cr1', tip: sha(2), baseTip: sha(5) })], r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(r.changes).toEqual([
      `${MAIN_TREE} worktree add --detach ${REVIEW_TREE} ${sha(2)}`,
      `${REVIEW_TREE} reset --hard ${sha(2)}`,
      `${REVIEW_TREE} reset -N ${sha(7)}`,
      `${REVIEW_TREE} update-ref ${REVIEW_END_REF} ${sha(2)}`,
    ])
    expect(r.all).toContain(`${MAIN_TREE} merge-base ${sha(5)} ${sha(2)}`)
    expect(r.opened).toEqual([`${REVIEW_TREE}/t.code-workspace`])
    expect(await texts(ui)).not.toContain('in review tree')  // the summary's, not the row's
    await ui.press({ key: 'cr-p-cr1-show' })
    await clock.settle()
    expect(await texts(ui)).toContain('in review tree')
    await ui.unmount()
  })

  test('a ratification row opens the range its request landed (fork point to tip), and has no Open without one', async ($, on) => {
    const r = repo({ workspaces: ['t.code-workspace'], fork: sha(7) })
    const ratifications = [{ id: 'p-rat1', cr: 'p-cr0', title: 'Ratify: Move the clock', tip: sha(6), baseTip: sha(5) }, { id: 'p-rat2', cr: '', title: 'Ratify: unknown', tip: null, baseTip: null }]
    const { ui, clock } = await queued($, on, [cr({ id: 'p-cr1' })], r, { ratifications })
    expect(await ui.find({ key: 'ratify-p-rat2-open' })).toBeUndefined()
    await ui.press({ key: 'ratify-p-rat1-open' })
    await clock.settle()
    expect(r.changes).toEqual([
      `${MAIN_TREE} worktree add --detach ${REVIEW_TREE} ${sha(6)}`,
      `${REVIEW_TREE} reset --hard ${sha(6)}`,
      `${REVIEW_TREE} reset -N ${sha(7)}`,
      `${REVIEW_TREE} update-ref ${REVIEW_END_REF} ${sha(6)}`,
    ])
    expect(r.all).toContain(`${MAIN_TREE} merge-base ${sha(5)} ${sha(6)}`)
    expect(r.opened).toEqual([`${REVIEW_TREE}/t.code-workspace`])
    await ui.unmount()
  })

  for (const workspaces of [[], ['a.code-workspace', 'b.code-workspace']]) {
    test(`the review tree opens as its folder with ${workspaces.length} workspace files`, async ($, on) => {
      const r = repo({ workspaces })
      const { ui, clock } = await queued($, on, WAITING(), r)
      await ui.press({ key: 'cr-open-p-cr1' })
      await clock.settle()
      expect(r.opened).toEqual([REVIEW_TREE])
      await ui.unmount()
    })
  }

  test('a press returns before its board read: a slow read runs after it, then the tree is set (the press budget)', async ($, on) => {
    const r = repo()
    const { w, ui, clock } = await queued($, on, WAITING(), r)
    let release = () => {}
    w.hold = { verb: 'board console', until: new Promise<void>(resolve => { release = resolve }) }
    await ui.press({ key: 'cr-open-p-cr1' })  // resolves while the read is held
    await clock.settle()
    expect(r.opened).toEqual([])
    release()
    await clock.settle()
    expect(r.opened).toEqual([REVIEW_TREE])
    await ui.unmount()
  })

  test('the tree sits beside the first worktree git lists, not beside the session\'s folder', async ($, on) => {
    const r = repo()
    const { ui, clock } = await queued($, on, WAITING(), r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(r.all[0]).toBe('/repo worktree list --porcelain')
    expect(r.changes[0]).toContain(`${MAIN_TREE} worktree add --detach ${REVIEW_TREE}`)
    await ui.unmount()
  })

  test('a second Open moves an existing review tree, but never over your edits', async ($, on) => {
    const r = repo({ hasReviewTree: true })
    const { ui, clock } = await queued($, on, WAITING(), r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(r.changes[0]).toBe(`${REVIEW_TREE} reset --hard ${sha(2)}`)
    await ui.unmount()
  })

  for (const edit of ['hasEdits', 'hasUntracked'] as const) {
    test(`Open leaves a review tree with ${edit} alone`, async ($, on) => {
      const r = repo({ hasReviewTree: true, [edit]: true })
      const { ui, clock, w } = await queued($, on, WAITING(), r)
      await ui.press({ key: 'cr-open-p-cr1' })
      await clock.settle()
      expect(r.changes).toEqual([])
      expect(w.toasts.at(-1)).toContain('the review tree has edits of yours')
      expect(r.opened).toEqual([])
      expect(await texts(ui)).not.toContain('in review tree')
      await ui.unmount()
    })
  }

  test('a tip git does not know changes nothing', async ($, on) => {
    const r = repo({ unknown: [sha(2)] })
    const { ui, clock, w } = await queued($, on, WAITING(), r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(r.changes).toEqual([])
    expect(w.toasts.at(-1)).toContain('is not a commit here')
    await ui.unmount()
  })

  test('two commits with no common base change nothing', async ($, on) => {
    const r = repo({ fork: null })
    const { ui, clock, w } = await queued($, on, WAITING(), r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(r.changes).toEqual([])
    expect(w.toasts.at(-1)).toContain('no common base')
    await ui.unmount()
  })

  test('view=result sets no tree: the walk-through request is sent', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', view: 'result', title: 'Remove X' })], r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual(["Walk me through p-cr1's result (Remove X)."])
    expect(r.all).toEqual([])
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
    expect(r.all).toEqual([])
    await ui.unmount()
  })

  test('the button reads Walk through for a result view and Open for code', async ($, on) => {
    const { ui } = await queued($, on, [cr({ id: 'p-code' }), cr({ id: 'p-res', view: 'result' })])
    expect((await ui.find({ key: 'cr-open-p-code' }))?.text).toBe('Open')
    expect((await ui.find({ key: 'cr-open-p-res' }))?.text).toBe('Walk through')
    await ui.unmount()
  })

  test('a request that left the accept stage since the last draw is refused', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, WAITING(), r)
    w.crs = [cr({ id: 'p-cr1', status: 'open' })]  // returned meanwhile; the pane still shows the old draw
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(w.toasts.at(-1)).toContain('p-cr1 is not waiting for you any more')
    expect(r.changes).toEqual([])
    await ui.unmount()
  })

  test('the open tree ends with its request: landed, it leaves the queue and nothing stays open', async ($, on) => {
    const { ui, clock, w } = await queued($, on, WAITING())
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    await ui.press({ key: 'cr-p-cr1-show' })
    await clock.settle()
    expect(await texts(ui)).toContain('in review tree')
    w.crs = []
    await clock.advance(60_000)
    await clock.settle()
    w.crs = WAITING()
    await clock.advance(60_000)
    await clock.settle()
    expect(await texts(ui)).not.toContain('in review tree')
    await ui.unmount()
  })

  test('a request the review tree holds says so on its row and in the /console text; others do not', async ($, on) => {
    const { ui } = await queued($, on, [cr({ id: 'p-cr1', heldByReviewTree: true }), cr({ id: 'p-cr2' })])
    const drawn = await texts(ui)
    expect(drawn.match(/held by your review tree/g)).toHaveLength(1)
    expect(drawn.indexOf('held by your review tree')).toBeLessThan(drawn.indexOf('p-cr2'))
    const text = consoleText({ session: 's', role: 'lead', actor: 'a', tool: 'claude' }, { ...parseBoardConsole({ ...BOARD_CONSOLE_CONTRACT, crs: [cr({ id: 'p-cr1', heldByReviewTree: true })] }), agents: [], scratch: null, error: null }, null, false, [])
    expect(text).toContain('held by your review tree')
    await ui.unmount()
  })

  test('a tip that moved past the open tree reads "review tree behind"', async ($, on) => {
    const { ui, clock, w } = await queued($, on, WAITING())
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    await ui.press({ key: 'cr-p-cr1-show' })
    await clock.settle()
    w.crs = [cr({ id: 'p-cr1', tip: sha(9) })]
    await clock.advance(60_000)
    await clock.settle()
    expect(await texts(ui)).toContain('review tree behind')
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
  test('Accept sends the lead\'s request with the tip you looked at', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', title: 'Remove X', tip: sha(2) })], r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    w.crs = [cr({ id: 'p-cr1', title: 'Remove X', tip: sha(9) })]  // the branch moved after you looked
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual([`Accept p-cr1 (Remove X) at ${short(2)}: land it.`])
    await ui.unmount()
  })

  test('without an open tree Accept names the current tip', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', tip: sha(4) })])
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts.join('\n')).toContain(`at ${short(4)}`)
    await ui.unmount()
  })

  test('a design checkpoint for you is accepted as a design: nothing lands', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', checkpoint: 'user', title: 'Design Y' })])
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual([`Accept the design of p-cr1 (Design Y) at ${short(2)}: planning continues in the same request, nothing lands.`])
    await ui.unmount()
  })

  test('accepting a design with no branch sends no sha', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', checkpoint: 'user', title: 'Design Y', tip: null, baseTip: null })])
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

  test('Accept with edits in the review tree names them and the exact board cr edits line; no new button', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', title: 'Remove X', tip: sha(2) })], r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    r.hasEdits = true
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts.join('\n')).toContain(`Accept p-cr1 (Remove X) at ${short(2)}: land it.`)
    expect(w.prompts.join('\n')).toContain(`board cr edits p-cr1 --from ${REVIEW_TREE} --tip ${sha(2)}`)
    expect(r.changes.filter(one => !one.includes('worktree add') && !one.includes('reset') && !one.includes('update-ref'))).toEqual([])
    expect(await ui.find({ key: 'cr-done-p-cr1' })).toBeUndefined()
    await ui.unmount()
  })

  test('a new file alone counts as edits of yours on Accept', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', tip: sha(2) })], r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    r.hasUntracked = true
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts.join('\n')).toContain('board cr edits p-cr1')
    await ui.unmount()
  })

  test('Return with edits says they are committed without a check and gives the line; the words stay yours', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', title: 'Remove X', tip: sha(2) })], r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    r.hasEdits = true
    await ui.press({ key: 'cr-return-p-cr1' })
    await clock.settle()
    expect(w.box).toContain(`Return p-cr1 (Remove X) with my edits from the review tree ${REVIEW_TREE}`)
    expect(w.box).toContain(`board cr edits p-cr1 --from ${REVIEW_TREE} --tip ${sha(2)}`)
    expect(w.box.endsWith(': ')).toBe(true)
    await ui.unmount()
  })

  test('edits the board committed are not pending: Accept names the edit commit and no edits', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', tip: sha(2) })], r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    r.hasEdits = true
    committed(r, sha(9))
    w.crs = [cr({ id: 'p-cr1', tip: sha(9) })]
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual([`Accept p-cr1 (Title of p-cr1) at ${short(9)}: land it.`])
    await ui.unmount()
  })

  test('a branch that moved past the edit commit (a worker built on it) is not what you looked at: Accept names the edit commit, so the board refuses', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', tip: sha(2) })], r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    r.hasEdits = true
    committed(r, sha(9))
    w.crs = [cr({ id: 'p-cr1', tip: sha(12) })]
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual([`Accept p-cr1 (Title of p-cr1) at ${short(9)}: land it.`])
    await ui.unmount()
  })

  test('edits made on top of an edit commit (after a failed check) are pending against it: the line names the edit commit', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', tip: sha(2) })], r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    r.hasEdits = true
    committed(r, sha(9))
    r.editsAt = null  // more edits since: the files are no commit's tree
    w.crs = [cr({ id: 'p-cr1', tip: sha(12) })]  // the failed check rebased the branch: the edits are still against the edit commit
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts.join('\n')).toContain(`at ${short(9)}: land it.`)
    expect(w.prompts.join('\n')).toContain(`board cr edits p-cr1 --from ${REVIEW_TREE} --tip ${sha(9)}`)
    await ui.unmount()
  })

  test('the pane reads the tree\'s marker: after the edit commit the request is in the review tree again', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, WAITING(), r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    await ui.press({ key: 'cr-p-cr1-show' })
    await clock.settle()
    r.hasEdits = true
    committed(r, sha(9))
    w.crs = [cr({ id: 'p-cr1', tip: sha(9) })]
    await clock.advance(60_000)
    await clock.settle()
    expect(await texts(ui)).toContain('in review tree')
    expect(await texts(ui)).not.toContain('review tree behind')
    await ui.unmount()
  })

  for (const tip of [9, 12]) {
    test(`Open moves a tree whose edits the board committed, the request's tip now ${tip === 9 ? 'the edit commit' : 'past it'}`, async ($, on) => {
      const r = repo()
      const { ui, clock, w } = await queued($, on, WAITING(), r)
      await ui.press({ key: 'cr-open-p-cr1' })
      await clock.settle()
      r.hasEdits = true
      committed(r, sha(9))
      w.crs = [cr({ id: 'p-cr1', tip: sha(tip) })]
      r.changes.length = 0
      await ui.press({ key: 'cr-open-p-cr1' })
      await clock.settle()
      expect(r.changes[0]).toBe(`${REVIEW_TREE} reset --hard ${sha(tip)}`)
      await ui.unmount()
    })
  }

  test('a ratification edit the board committed (its follow-up request is no row) leaves the tree clean: Open moves it', async ($, on) => {
    const r = repo({ fork: sha(7) })
    const ratifications = [{ id: 'p-rat1', cr: 'p-cr0', title: 'Ratify: Move the clock', tip: sha(6), baseTip: sha(5) }]
    const { ui, clock } = await queued($, on, [cr({ id: 'p-cr1' })], r, { ratifications })
    await ui.press({ key: 'ratify-p-rat1-open' })
    await clock.settle()
    r.hasUntracked = true
    committed(r, sha(9))  // the follow-up's first commit
    r.changes.length = 0
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(r.changes[0]).toBe(`${REVIEW_TREE} reset --hard ${sha(2)}`)
    await ui.unmount()
  })

  test('opening a ratification ends the request\'s review tree: no status, and Accept names the request\'s tip', async ($, on) => {
    const r = repo({ fork: sha(7) })
    const ratifications = [{ id: 'p-rat1', cr: 'p-cr0', title: 'Ratify: Move the clock', tip: sha(6), baseTip: sha(5) }]
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', tip: sha(2) })], r, { ratifications })
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    await ui.press({ key: 'cr-p-cr1-show' })
    await clock.settle()
    expect(await texts(ui)).toContain('in review tree')
    await ui.press({ key: 'ratify-p-rat1-open' })
    await clock.settle()
    await clock.advance(60_000)
    await clock.settle()
    expect(await texts(ui)).not.toContain('in review tree')
    expect(await texts(ui)).not.toContain('review tree behind')
    r.hasEdits = true  // edits on the ratification's range are not this request's
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.prompts).toEqual([`Accept p-cr1 (Title of p-cr1) at ${short(2)}: land it.`])
    await ui.unmount()
  })

  test('edits the board committed stay committed after their request landed and left the queue', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1' }), cr({ id: 'p-cr2' })], r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    r.hasEdits = true
    committed(r, sha(9))
    w.crs = [cr({ id: 'p-cr2' })]  // p-cr1 landed
    await clock.advance(60_000)
    await clock.settle()
    r.changes.length = 0
    await ui.press({ key: 'cr-open-p-cr2' })
    await clock.settle()
    expect(r.changes[0]).toBe(`${REVIEW_TREE} reset --hard ${sha(2)}`)
    await ui.unmount()
  })

  test('the clean check writes its tree in a throwaway index outside the review tree and removes it; the tree\'s own index is untouched', async ($, on) => {
    const r = repo({ hasReviewTree: true })
    const { ui, clock } = await queued($, on, WAITING(), r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(r.changes[0]).toBe(`${REVIEW_TREE} reset --hard ${sha(2)}`)  // a snapshot step outside the throwaway index would be a change
    const snapshot = r.all.slice(r.all.indexOf('mktemp -d'))
    expect(snapshot.slice(0, 5)).toEqual(['mktemp -d', `${REVIEW_TREE} read-tree ${sha(2)}`, `${REVIEW_TREE} add -A`, `${REVIEW_TREE} write-tree`, `rm -rf ${SNAPSHOT_DIR}`])
    await ui.unmount()
  })

  test('a targeted or no-gate result reads as what it was, never as a full check', () => {
    const checked = (over: Record<string, unknown>) => cr({ id: 'p-cr1', check: { state: 'current', tip: sha(2), baseTip: sha(1), at: null, result: 'pass', newFailures: null, baseCount: null, tipCount: null, ...over } }) as unknown as ConsoleCr
    expect(crCheckText(checked({ kind: 'targeted', command: 'pnpm test a' }))).toBe('targeted check current')
    expect(crCheckText(checked({ kind: 'targeted', command: 'pnpm test a', state: 'failed', result: 'fail' }))).toBe('targeted check failed')
    expect(crCheckText(checked({ kind: 'none', reason: 'docs only' }))).toBe('no check run')
    expect(crCheckText(checked({ kind: 'full' }))).toBe('checks current')
    expect(crDetailsText(checked({ kind: 'targeted', command: 'pnpm test a' }), null)).toContain('ran: pnpm test a')
    expect(crDetailsText(checked({ kind: 'none', reason: 'docs only' }), null)).toContain('no check: docs only')
  })

  test('without a prompt box the press says so', async ($, on) => {
    const { ui, clock, w } = await queued($, on, WAITING())
    w.hasBox = false
    await ui.press({ key: 'cr-return-p-cr1' })
    await clock.settle()
    expect(w.toasts.at(-1)).toContain('the prompt box is not available')
    await ui.unmount()
  })

  test('the console never lands: no presses run a merge, a ref update on a branch or a worktree removal', async ($, on) => {
    const r = repo({ workspaces: ['t.code-workspace'] })
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1' }), cr({ id: 'p-cr2', view: 'result' })], r)
    for (const key of ['cr-open-p-cr1', 'cr-accept-p-cr1', 'cr-return-p-cr1', 'cr-open-p-cr2', 'cr-accept-p-cr2', 'cr-return-p-cr2']) {
      await ui.press({ key })
      await clock.settle()
    }
    const run = r.all.join('\n')
    expect(run).not.toMatch(/ merge |refs\/heads|worktree remove|branch -|push/)
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

  test('the request open in the review tree is named', async ($, on) => {
    const { ui, clock } = await queued($, on, WAITING())
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(await text($, ui, clock)).toContain('· in review tree')
  })

  test('no requests: no section', async ($, on) => {
    const { ui, clock } = await queued($, on, [])
    expect(await text($, ui, clock)).not.toMatch(/^Change requests/m)
  })
})

describe('review git parsing', () => {
  test('worktrees name their branch, none when detached', () => {
    expect(parseWorktrees('worktree /a\nHEAD 1\nbranch refs/heads/main\n\nworktree /b\nHEAD 2\ndetached\n')).toEqual([
      { path: '/a', branch: 'refs/heads/main' }, { path: '/b', branch: null },
    ])
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

  test('setup failed, land blocked (three paths at most) and lands-with read in that order', () => {
    const marks = crMarks(cr({ id: 'p-cr1', setupFailed: true, landBlocked: ['a', 'b', 'c', 'd'], after: 'p-cr0' }) as unknown as ConsoleCr)
    expect(marks).toEqual([
      { text: 'setup failed', isProblem: true }, { text: 'land blocked: a, b, c, …', isProblem: true },
      { text: 'lands with p-cr0', isProblem: false },
    ])
  })

  test('lands-with names the short id under the board prefix', () => {
    const one = cr({ id: 'p-cr2', after: 'p-cr1' }) as unknown as ConsoleCr
    expect(crMarks(one, 'p')).toEqual([{ text: 'lands with cr1', isProblem: false }])
    expect(crDetailsText(one, null, 'p')).toContain('lands with cr1')
  })

  test('problems stay on the request row; lands-with waits in the opened summary', async ($, on) => {
    const { ui, clock } = await queued($, on, [cr({ id: 'p-cr1', landBlocked: ['src/x.ts'], setupFailed: true, reviewState: 'stale' }), cr({ id: 'p-cr2', status: 'in_review', base: 'p-cr1', parent: 'p-cr1', after: 'p-cr1' })])
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
  const stale = cr({ id: 'p-cr1', reviewState: 'stale', refreshWork: true }) as unknown as ConsoleCr

  test('a request waiting for its Accept says so, and review pulls may refresh it though its check is current', () => {
    expect(crMarks(stale)).toEqual([{ text: 'review stale', isProblem: true }])
    expect(canRefreshCr(stale, ['review'])).toBe(true)
    expect(canRefreshCr(stale, ['implement'])).toBe(false)
    expect(canRefreshCr(cr({ id: 'p-cr1' }) as unknown as ConsoleCr, ['review'])).toBe(false)
    expect(canRefreshCr(cr({ id: 'p-cr2', reviewState: 'stale' }) as unknown as ConsoleCr, ['review'])).toBe(false)  // stale, not the queue head
  })

  test('in review it is no mark: the reviewer passes it again', () => {
    expect(crMarks(cr({ id: 'p-cr1', status: 'in_review', reviewState: 'stale' }) as unknown as ConsoleCr)).toEqual([])
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
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1', milestone: '1.0-beta' }), cr({ id: 'p-cr2', landBlocked: ['src/a.ts'] })], WIDE)
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
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1', unblocks: 14, unblocksDirect: 7, milestone: long, landBlocked: ['src/aaaa.ts', 'src/bbbb.ts'] }), cr({ id: 'p-cr2', milestone: 'Short' })], { ...PANE_PROPS, bodyColumns: 90 })
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
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1', landBlocked: ['src/a.ts'], check: check('conflict', { newFailures: ['x TS1'] }) } as never), cr({ id: 'p-cr2', check: check('stale') } as never), cr({ id: 'p-cr3' })], WIDE)
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
