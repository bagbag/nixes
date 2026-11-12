// Change requests (r25): the queue section, the review tree set to a request's (base tip, tip), and the Open / Accept / Return /
// Refresh presses, which put requests in the prompt (the console never lands); the counts display (r21-q141, q146).
import { describe, expect, test } from 'claude-code/testing'
import type { Mounted } from 'claude-code/testing'

import { BOARD_CONSOLE_CONTRACT, cr } from './board-console-contract'
import { COUNTS, NO_ROUND, PANE_PROPS, SESSION, world } from './fixture'
import { git, MAIN_TREE, repo, REVIEW_END_REF, REVIEW_TREE, sha } from './review-world'
import type { Repo } from './review-world'
import { parseRound } from '../hooks/engine'
import { canRefreshCr, consoleText, countText, crFailuresText, crMarks, crRows, crUnblocksHint, crUnblocksText, fitText } from '../hooks/words'
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
    for (const part of ['Change requests', 'Remove the legacy cache', 'Drop the cache config', 'code', 'checks current', '0 new', '2 new', 'checkpoint review', 'stale', 'to ratify', 'Ratify: Move the clock']) {
      expect(drawn, part).toContain(part)
    }
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
    expect(w.box).toBe("Refresh p-cr1 under the review protocol's Refresh.")
    expect(w.prompts).toEqual([])
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
    for (const [id, kind] of [['p-cr1', 'design'], ['p-cr2', 'result'], ['p-cr3', 'code']]) {
      const row = (await ui.find({ key: `cr-${id}` }))?.text ?? ''
      expect(row, id).toContain(kind)
      expect(row, id).not.toContain('to accept')
    }
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

  test('view=result sets no tree: the walk-through request goes in the prompt', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', view: 'result', title: 'Remove X' })], r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(w.box).toBe("Walk me through p-cr1's result (Remove X).")
    expect(w.prompts).toEqual([])
    expect(r.all).toEqual([])
    expect(r.opened).toEqual([])
    await ui.unmount()
  })

  test('a design has no branch: its button is Walk through, and it puts the walk-through request in the prompt', async ($, on) => {
    const r = repo()
    const design = cr({ id: 'p-cr1', title: 'Design Y', checkpoint: 'user', tip: null, baseTip: null, worktree: null })
    const { ui, clock, w } = await queued($, on, [design], r)
    expect((await ui.find({ key: 'cr-open-p-cr1' }))?.text).toBe('Walk through')
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    expect(w.box).toBe("Walk me through p-cr1's design (Design Y).")
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

describe('Accept, Return', () => {
  test('Accept puts the lead\'s request in the prompt with the tip you looked at; nothing is sent', async ($, on) => {
    const r = repo()
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', title: 'Remove X', tip: sha(2) })], r)
    await ui.press({ key: 'cr-open-p-cr1' })
    await clock.settle()
    w.crs = [cr({ id: 'p-cr1', title: 'Remove X', tip: sha(9) })]  // the branch moved after you looked
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.box).toBe(`Accept p-cr1 (Remove X) at ${short(2)}: land it.`)
    expect(w.prompts).toEqual([])
    await ui.unmount()
  })

  test('without an open tree Accept names the current tip', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', tip: sha(4) })])
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.box).toContain(`at ${short(4)}`)
    await ui.unmount()
  })

  test('a design checkpoint for you is accepted as a design: nothing lands', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', checkpoint: 'user', title: 'Design Y' })])
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.box).toBe(`Accept the design of p-cr1 (Design Y) at ${short(2)}: planning continues in the same request, nothing lands.`)
    await ui.unmount()
  })

  test('accepting a design with no branch sends no sha', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', checkpoint: 'user', title: 'Design Y', tip: null, baseTip: null })])
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.box).toBe('Accept the design of p-cr1 (Design Y): planning continues in the same request, nothing lands.')
    expect(w.toasts).toEqual([])
    await ui.unmount()
  })

  test('a code request with no branch tip still refuses its Accept', async ($, on) => {
    const { ui, clock, w } = await queued($, on, [cr({ id: 'p-cr1', tip: null })])
    await ui.press({ key: 'cr-accept-p-cr1' })
    await clock.settle()
    expect(w.box).toBe('')
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
    expect(out).toContain('  p-cr1  Remove the legacy cache · to accept · unblocks 14 · 1.0-beta scope · checks current · 0 new (base 3012, tip 2972) · look before · code')
    expect(out).toContain('    p-cr2  Drop the cache config · checkpoint review · stale · 2 new: src/a.ts TS2322, src/b.ts TS2345 (base 3012, tip 3014) · look after · result · held by a1b2')
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
    const text = consoleText({ session: 's', role: 'lead', actor: 'a', tool: 'claude' }, { counts: COUNTS, forYou: [], items: [], sessions: [], held: [], crs: [], ratifications: [], agents: [], sync: null, queues: null, error: null }, null, false, [])
    expect(text).toContain('you: for you 3 · to accept 13 (1 wait) · to ratify 1 · decided 0 · questions 186 (2 held)')
    expect(text).toContain('agents: to plan 0 (57 wait) · to review 0')
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

  test('setup failed, land blocked (three paths at most), returned and lands-with read in that order', () => {
    const marks = crMarks(cr({ id: 'p-cr1', setupFailed: true, landBlocked: ['a', 'b', 'c', 'd'], returned: true, after: 'p-cr0' }) as unknown as ConsoleCr)
    expect(marks).toEqual([
      { text: 'setup failed', isProblem: true }, { text: 'land blocked: a, b, c, …', isProblem: true },
      { text: 'returned', isProblem: false }, { text: 'lands with p-cr0', isProblem: false },
    ])
  })

  test('problems stay on the request row; returned and lands-with wait in the opened summary', async ($, on) => {
    const { ui, clock } = await queued($, on, [cr({ id: 'p-cr1', landBlocked: ['src/x.ts'], setupFailed: true, reviewState: 'stale' }), cr({ id: 'p-cr2', status: 'in_review', base: 'p-cr1', parent: 'p-cr1', after: 'p-cr1', returned: true })])
    const all = await texts(ui)
    for (const part of ['land blocked: src/x.ts', 'setup failed', 'review stale']) expect(all, part).toContain(part)
    for (const part of ['lands with p-cr1', 'returned']) expect(all, part).not.toContain(part)
    await ui.press({ key: 'cr-p-cr2-show' })
    await clock.settle()
    const opened = await texts(ui)
    expect(opened).toContain('returned')
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

  test('two lines: id and title, then the stage, the facts and the buttons in a fixed right-aligned slot so Accept and Return line up', async ($, on) => {
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1', unblocks: 14, unblocksDirect: 7, milestone: '1.0-beta scope' }), cr({ id: 'p-cr2', view: 'result' })], WIDE)
    for (const id of ['p-cr1', 'p-cr2']) {
      const first = (await ui.find({ key: `cr-${id}-line1` }))?.text ?? ''
      expect(first, id).toContain(`Title of ${id}`)
      for (const part of ['checks current', 'Accept', 'code', 'result']) expect(first, `${id} line one ${part}`).not.toContain(part)
      const line = (await ui.find({ key: `cr-${id}-line2` }))?.text ?? ''
      const at = (part: string) => line.indexOf(part)
      const places = [id === 'p-cr1' ? 'code' : 'result', ...(id === 'p-cr1' ? ['unblocks 14', '1.0-beta scope'] : []), 'checks current', '0 new', 'Accept'].map(at)
      expect(places.every(place => place >= 0), id).toBe(true)
      expect(places, id).toEqual([...places].sort((a, b) => a - b))
      expect((await ui.find({ key: `cr-${id}-buttons` }))?.props, id).toMatchObject({ width: 38, justifyContent: 'flex-end', flexShrink: 0 })
    }
    await ui.unmount()
  })

  test('the buttons slot is as wide as the widest row needs: code-only rows reserve no Walk through', async ($, on) => {
    const code = await mounted($, on, [cr({ id: 'p-cr1' })], WIDE)
    expect((await code.ui.find({ key: 'cr-p-cr1-buttons' }))?.props.width).toBe(30)
    await code.ui.unmount()
  })

  test('the title keeps line one to itself and truncates only at the pane edge, however narrow the pane', async ($, on) => {
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1', unblocks: 3, unblocksDirect: 1, milestone: 'M' })], NARROW)
    expect((await ui.find({ key: 'cr-p-cr1-title' }))?.props).toMatchObject({ flexShrink: 1, flexGrow: 1 })
    expect(children(await ui.find({ key: 'cr-p-cr1-line1' }))).not.toContain('cr-accept-p-cr1')
    expect(children(await ui.find({ key: 'cr-p-cr1-line2' }))).toContain('cr-accept-p-cr1')
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
    const long = 'A milestone with a title that is far longer than any narrow pane could ever show in one line'
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1', milestone: long })], { ...PANE_PROPS, bodyColumns: 110 })
    const shown = (await texts(ui)).split('\n').find(one => one.startsWith('A milestone')) ?? ''
    expect(shown.endsWith('…') && shown.length < long.length).toBe(true)
    expect(shown.length).toBe(110 - 12 - 26 - 31 - 1)  // pane minus the id column, the facts (code, checks current, 0 new, with gaps), the buttons slot and a spare cell
    await ui.unmount()
  })

  test('only problem marks join line two, after the check and the new-failure count', async ($, on) => {
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1', landBlocked: ['src/a.ts'], returned: true })], WIDE)
    const line = (await ui.find({ key: 'cr-p-cr1-line2' }))?.text ?? ''
    expect(line.indexOf('land blocked: src/a.ts')).toBeGreaterThan(line.indexOf('0 new'))
    expect(line).not.toContain('returned')
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
    const board = { counts: null, forYou: [], items: [], sessions: [], held: [], crs: [cr({ id: 'p-cr1', unblocks: 14, unblocksDirect: 7, milestone: '1.0-beta scope' }), cr({ id: 'p-cr2' })] as unknown as ConsoleCr[], ratifications: [], agents: [], sync: null, queues: null, error: null }
    const text = consoleText({ session: 's', role: 'lead', actor: 'a', tool: 'claude' }, board as unknown as ConsoleBoard, null, false, [])
    const [first, second] = ['p-cr1', 'p-cr2'].map(id => text.split('\n').find(line => line.includes(`${id}  `)) ?? '')
    expect(first).toContain('unblocks 14 · 1.0-beta scope')
    expect(second).not.toContain('unblocks')
  })

  test('the stage is colored text without a background: warning while it waits for you', async ($, on) => {
    const { ui } = await mounted($, on, [cr({ id: 'p-cr1' }), cr({ id: 'p-cr2', status: 'in_review' })], WIDE)
    const stage = async (text: string) => (await ui.findAll({ type: 'Text' })).find(one => one.text === text)?.props
    expect(await stage('code')).toMatchObject({ color: 'warning' })
    expect(await stage('in review')).toMatchObject({ color: 'inactive' })
    expect((await stage('code'))?.inverse).toBeUndefined()
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
