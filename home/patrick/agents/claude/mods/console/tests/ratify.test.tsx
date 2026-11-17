// The board's git-state problem on a request row and the ratification verdicts: Ratify, Ratify with edits and Not OK call
// `board ratify <id> yes|edits|no`; its review state comes from the ratification's own `review`.
import { describe, expect, test } from 'claude-code/testing'

import { BOARD_CONSOLE_CONTRACT, cr, sha } from './board-console-contract'
import { NO_ROUND, PANE_PROPS, world } from './fixture'
import { parseBoardConsole } from '../hooks/engine'
import { crMarks } from '../hooks/words'
import type { ConsoleCr } from '../types'

const PANE = { plugin: 'console', component: 'Pane', requestId: 'console', props: PANE_PROPS } as const
const RATIFICATION = { id: 'p-rat1', cr: 'p-cr0', title: 'Move the clock', tip: sha(6), baseTip: sha(5), review: null }
/** The ratification as the board lists it, with its review (open for you since the landed tip). */
const rat = (review: Record<string, unknown> | null) => ({ ...RATIFICATION, review })
const view = (over: Record<string, unknown> = {}) => ({ opened: sha(6), edited: false, files: [], ...over })

const texts = async (ui: { findAll: (query: { type: string }) => Promise<{ text: string }[]> }): Promise<string> =>
  (await ui.findAll({ type: 'Text' })).map(one => one.text).join('\n')

async function mounted($: any, on: any, init: Parameters<typeof world>[1] = {}) {
  const made = world(on, { round: NO_ROUND, ratifications: [RATIFICATION], ...init })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await made.clock.settle()
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  const boardRatify = () => made.w.calls.filter(one => one.argv[1] === 'ratify').map(one => one.argv.slice(2))
  return { ...made, ui, boardRatify }
}

describe('a git state the board did not start', () => {
  const gitState = (state: string) => ({ kind: 'git-state', text: `mid ${state} (not the board's)`, next: { action: 'owner', paths: ['/main/.worktrees/x'] } })
  test('is read from the row\'s problems and marked as a problem on it', async ($, on) => {
    const parsed = parseBoardConsole({ crs: [{ id: 'p-cr1', problems: [gitState('rebase')] }, { id: 'p-cr2', problems: [{ text: 'no kind' }, 'junk'] }, { id: 'p-cr3' }] }).crs
    expect(parsed.map(one => one.problems.map(problem => problem.kind))).toEqual([['git-state'], [], []])
    expect(parsed[0]?.problems[0]?.next).toEqual({ action: 'owner', command: null, paths: ['/main/.worktrees/x'] })
    expect(crMarks(parsed[0] as ConsoleCr)).toContainEqual({ text: "mid rebase (not the board's)", isProblem: true })
    expect(crMarks(parsed[2] as ConsoleCr).map(one => one.text)).toEqual([])
    const { ui } = await mounted($, on, { crs: [cr({ id: 'p-cr1', problems: [gitState('cherry-pick')] }), cr({ id: 'p-cr2' })] })
    const drawn = await texts(ui)
    expect(drawn).toContain("mid cherry-pick (not the board's)")
    expect(drawn.split("(not the board's)").length).toBe(2)  // one row only
    await ui.unmount()
  })
})

describe('the board\'s review', () => {
  test('is read from crs and ratifications; an unreadable edited state is null, no view is null', () => {
    const board = parseBoardConsole(BOARD_CONSOLE_CONTRACT)
    expect(board.ratifications[0]?.review).toEqual({ opened: sha(6), edited: false, files: [] })
    expect(board.crs[0]?.review).toEqual({ opened: sha(2), edited: true, files: ['src/a.ts'] })
    expect(board.crs[1]?.review).toBeNull()
    expect(parseBoardConsole({ ratifications: [{ id: 'r', review: { opened: sha(2), files: ['a.ts', ''] } }] }).ratifications[0]?.review).toEqual({ opened: sha(2), edited: null, files: ['a.ts'] })
    expect(parseBoardConsole({ ratifications: [{ id: 'r', review: null }, { id: 's' }] }).ratifications.map(one => one.review)).toEqual([null, null])
  })
})

describe('ratification verdicts', () => {
  test('Ratify calls board ratify yes; the row refreshes', async ($, on) => {
    const { ui, clock, w, boardRatify } = await mounted($, on, { ratifications: [rat(view())] })
    await ui.press({ key: 'ratify-p-rat1-yes' })
    await clock.settle()
    expect(boardRatify()).toEqual([['p-rat1', 'yes']])
    expect(w.toasts).toContain('p-rat1 is ratified')
    expect(await ui.find({ key: 'ratify-p-rat1-edits' })).toBeUndefined()  // no unrecorded edits: no Ratify with edits
    await ui.unmount()
  })

  test('the board\'s refusal reaches the person as it said it', async ($, on) => {
    const { ui, clock, w, boardRatify } = await mounted($, on)
    w.ratify = { exit: 1, stderr: 'your review holds edits (a.ts)\n' }
    await ui.press({ key: 'ratify-p-rat1-yes' })
    await clock.settle()
    expect(boardRatify()).toEqual([['p-rat1', 'yes']])
    expect(w.toasts).toContain('Ratification: p-rat1: your review holds edits (a.ts)')
    await ui.unmount()
  })

  test('a refusal re-reads the board, so the buttons follow what the board says now', async ($, on) => {
    const { ui, clock, w } = await mounted($, on, { ratifications: [rat(view())] })
    const reads = () => w.calls.filter(one => one.argv[1] === 'console').length
    w.ratify = { exit: 1, stderr: 'your review holds edits (a.ts)' }
    const before = reads()
    w.ratifications = [rat(view({ edited: true, files: ['a.ts'] }))]  // what the board reads after the refusal
    await ui.press({ key: 'ratify-p-rat1-yes' })
    await clock.settle()
    expect(reads()).toBeGreaterThan(before)
    expect(await ui.find({ key: 'ratify-p-rat1-edits' })).toBeDefined()
    await ui.unmount()
  })

  test('edits in this ratification\'s range: Ratify with edits shows and calls edits, Ratify waits', async ($, on) => {
    const { ui, clock, boardRatify } = await mounted($, on, { ratifications: [rat(view({ edited: true, files: ['a.ts'] }))] })
    expect(await ui.find({ key: 'ratify-p-rat1-yes' })).toBeUndefined()
    expect(await texts(ui)).toContain('Ratify with edits')
    await ui.press({ key: 'ratify-p-rat1-edits' })
    await clock.settle()
    expect(boardRatify()).toEqual([['p-rat1', 'edits']])
    await ui.unmount()
  })

  // Ratify with edits needs this ratification's own edits: not a clean view, not an unreadable one, not no view.
  const withoutEdits: [string, Record<string, unknown> | null][] = [['a clean review', view({ edited: false })], ['an unreadable review', view({ edited: null })], ['no review open', null]]
  for (const [name, review] of withoutEdits) {
    test(`Ratify with edits is not offered for ${name}; Ratify is`, async ($, on) => {
      const { ui } = await mounted($, on, { ratifications: [rat(review)] })
      expect(await ui.find({ key: 'ratify-p-rat1-edits' })).toBeUndefined()
      expect(await ui.find({ key: 'ratify-p-rat1-yes' })).toBeDefined()
      await ui.unmount()
    })
  }

  test('another ratification\'s edits leave this one\'s Ratify alone', async ($, on) => {
    const other = { ...rat(view({ edited: true, files: ['a.ts'] })), id: 'p-rat2', title: 'Other' }
    const { ui } = await mounted($, on, { ratifications: [rat(null), other] })
    expect(await ui.find({ key: 'ratify-p-rat1-yes' })).toBeDefined()
    expect(await ui.find({ key: 'ratify-p-rat2-yes' })).toBeUndefined()
    expect(await ui.find({ key: 'ratify-p-rat2-edits' })).toBeDefined()
    await ui.unmount()
  })

  test('Not OK asks for the reason and sends it with no; an empty reason sends nothing', async ($, on) => {
    const { ui, clock, w, boardRatify } = await mounted($, on)
    await ui.press({ key: 'ratify-p-rat1-no' })
    await clock.settle()
    expect(boardRatify()).toEqual([])  // the button only asks
    await ui.input({ key: 'ratify-p-rat1-reason', text: '   ', kind: 'submit' })
    await clock.settle()
    expect(boardRatify()).toEqual([])
    expect(w.toasts.some(one => one.includes('Not OK needs what you want'))).toBe(true)
    await ui.input({ key: 'ratify-p-rat1-reason', text: ' revert the clock move ', kind: 'submit' })
    await clock.settle()
    expect(boardRatify()).toEqual([['p-rat1', 'no', '-m', 'revert the clock move']])
    expect(await ui.find({ key: 'ratify-p-rat1-reason' })).toBeUndefined()  // closed once the board took it
    await ui.unmount()
  })

  test('a refused Not OK keeps the reason field open', async ($, on) => {
    const { ui, clock, w } = await mounted($, on)
    w.ratify = { exit: 1, stderr: 'no is refused' }
    await ui.press({ key: 'ratify-p-rat1-no' })
    await ui.input({ key: 'ratify-p-rat1-reason', text: 'fix it', kind: 'submit' })
    await clock.settle()
    expect(w.toasts).toContain('Ratification: p-rat1: no is refused')
    expect(await ui.find({ key: 'ratify-p-rat1-reason' })).toBeDefined()
    await ui.unmount()
  })
})
