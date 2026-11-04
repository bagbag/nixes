// The console's shared actions over $: refresh, notices, pass records and presses. Function
// declarations throughout: past an import, the engine follows $ only into those.
import type { EngineInterface, ToolCallResult } from 'claude-code'

import type { ConsoleBoard, ConsolePassOrigin, ConsoleRound, ConsoleSuggestion } from '../types'

import { boardItem, boardViews, isRoundOpen, pass, PASS_COMMANDS, pending as readPending, readRole, RELEASE_COMMAND, ROUND_ROLES, setWorkers, show, stampRelease, stateDir } from './engine'
import {
  claimRefresh, getAskSent, getDrawn, getPaneDismissed, getPass, getPrinted, getRole, getRound, releaseRefresh, setAskSent, setBoard, setDrawn, setPass, setPrinted, setRole,
  setRound, setRoundError, setStart, takeRefreshAgain, updateOpened, updateQueued,
} from './state'
import { itemSlot, openDialogText } from './words'

type $ = EngineInterface

export const PANE = 'console'
const QUEUED_EXPIRY_MS = 10 * 60_000
const REFRESH_STALE_MS = 2 * 60_000  // a run this old is stuck (a board call that never returns): take over

// Module state a reload may lose without harm: session.start resets it.
let isToolRegistered = false
let isPaneOpenedUnasked = false

export function resetSession(): void {
  isToolRegistered = false
  isPaneOpenedUnasked = false
}

export const message = (error: unknown): string => error instanceof Error ? error.message : String(error)

/** A transcript notice: the person sees it, the model never reads it. */
export async function notice($: $, text: string): Promise<void> {
  await $.session.append({ message: { type: 'system', content: [{ type: 'text', text: `console: ${text}` }] } })
}

/** The command that prints a batch's question text as its output (register.tsx registers and answers it by this literal name). */
const QUESTIONS_COMMAND = 'console-questions'

const DIALOG_PREFIX = 'Console round dialog '

/** The question `$.ui.ask` carries: the host takes labels only, so the console's AskUserQuestion hook swaps it for the issued batch. */
const dialogPlaceholder = (marker: string): string => `${DIALOG_PREFIX}${marker}?`

/** The marker a placeholder question names, or null for any other question. */
export const placeholderMarker = (question: unknown): string | null =>
  typeof question === 'string' && question.startsWith(DIALOG_PREFIX) ? question.slice(DIALOG_PREFIX.length, -1) : null

/** What the swapped dialog came to, set by the AskUserQuestion hook. `summary`: the visible line; `note`: the engine's text for the model; `needsModel`: typed text, a note or a decline. */
export type DialogOutcome = { summary: string; note: string | null; needsModel: boolean }
let dialogOutcome: DialogOutcome | null = null
export const setDialogOutcome = (outcome: DialogOutcome): void => { dialogOutcome = outcome }

/** Tells the model what came of the dialog: the engine's text as a note, then the visible line, which starts its turn. */
async function wakeModel($: $, outcome: DialogOutcome): Promise<void> {
  if (outcome.note !== null) {
    await $.session.append({ message: { type: 'user', content: [{ type: 'text', text: `<console-note>${outcome.note}</console-note>` }] } })
  }
  await pressSubmit($, outcome.summary, async error => {
    await notice($, `telling the model about the answers failed: ${message(error)}`).catch(() => undefined)
  })
}

/**
 * Opens the batch's whole dialog with no model turn (r32-q149): `$.ui.ask` with a placeholder the AskUserQuestion hook swaps for the
 * batch, then records through its usual capture. `$.ui.ask` itself then has no answer to return, so it rejects; the hook's outcome
 * counts. After plain picks a pending pass just runs; anything else, a next batch included, wakes the model: this hook's `$` cannot run
 * `/console-questions` again (a `$` call skips the hook it came from), and the model's turn end opens that batch. Without an
 * outcome the swap never ran, and the model opens the dialog instead.
 */
export async function openDialog($: $, marker: string, session: string): Promise<void> {
  dialogOutcome = null
  await $.ui.ask(dialogPlaceholder(marker), { options: ['Open the questions', 'Not now'], header: 'Round' }).catch(() => undefined)
  const outcome = dialogOutcome as DialogOutcome | null
  dialogOutcome = null
  if (outcome === null) {
    await pressSubmit($, openDialogText(marker), async error => {
      await setAskSent($, null).catch(() => undefined)
      await notice($, `sending the message that opens the dialog failed: ${message(error)}`).catch(() => undefined)
    })
    return
  }
  if (outcome.needsModel || !(await betweenTurns($, session, false, false))) await wakeModel($, outcome)
}

/**
 * At a main-agent turn's end that was not aborted, with a batch out (r29-q138, r30-q140, r32-q149): runs `/console-questions`, whose
 * hook prints the text and opens the dialog. A command's output draws whole between turns where a transcript row would not, and the hook's
 * fresh `$` matters too: after an awaited call in a chain, `$.ui.ask` skips the swap in the console's hook. One dialog per batch marker until
 * the person sends a new message (`prompt.submit` clears it); a batch already printed prints only a short line. Returns whether one is on its way.
 */
export async function openBatchDialog($: $, round: ConsoleRound | null): Promise<boolean> {
  const batch = round?.batch
  if (round === null || round === undefined || !isRoundOpen(round) || batch === null || batch === undefined || (await getAskSent($)) === batch.marker) return false
  await setAskSent($, batch.marker)
  const isNew = batch.notice.trim() !== '' && (await getPrinted($)) !== batch.marker
  await setPrinted($, batch.marker)
  void $.command.run({ command: QUESTIONS_COMMAND, args: isNew ? batch.marker : `${batch.marker} again` })
    .catch(async error => {
      await setPrinted($, null).catch(() => undefined)
      await setAskSent($, null).catch(() => undefined)
      await notice($, `printing the question text failed: ${message(error)}; nothing opens the dialog`).catch(() => undefined)
    })
  return true
}

/** What follows a turn or a dialog: the pending pass, else the issued batch's print and dialog. Whether either started. */
export async function betweenTurns($: $, session: string, isAborted: boolean, opensDialog = true): Promise<boolean> {
  const pending = await readPending($, session)
  const run = await getPass($)
  let started = false
  if (pending !== null && run !== null && run.id === pending.id) {
    if (run.phase !== 'noted' && isAborted) {
      // Esc stops the loop: the pass stays pending and is not run again.
      await setPass($, { ...run, phase: 'noted' })
    } else if (run.phase === 'started') {
      await setPass($, { ...run, phase: 'noted' })
      await noteModel($, `The /${pending.command} pass (${pending.id}) ended without its report. Report its per-question updates through the protocol tool.`)
    }
  } else if (pending !== null && !isAborted) {
    await setPass($, { id: pending.id, command: pending.command, phase: 'queued' })
    await pass($, session, 'plugin', { command: pending.command, args: pending.args, pending: pending.id })
      .catch(failOpen($, `recording /${pending.command}`))
    void $.command.run({ command: pending.command, args: pending.args }).catch(failOpen($, `running /${pending.command}`))
    started = true
  }
  // The issued batch's text prints between turns, then the console opens its dialog (an aborted turn does neither, as it runs no
  // pass; an away session has no batch to open).
  if (opensDialog && !isAborted && (await getRole($))?.role !== 'autopilot') {
    started = await openBatchDialog($, await refreshRound($, session)) || started
  }
  return started
}

/** A role button's press: the person's own `/role <role>`. A prompt text beginning with `/` is refused by the host, so it runs as a command (the press route of Commit and Retro). */
export async function pressRole($: $, role: 'solo' | 'autopilot'): Promise<void> {
  await pressRun($, 'role', role)
}

/** A note the model reads at its next request, shown to the person as a notice too. */
export async function noteModel($: $, text: string): Promise<void> {
  await $.session.append({ message: { type: 'user', content: [{ type: 'text', text: `<console-note>${text}</console-note>` }] } })
  await notice($, text)
}

/** Adds a note the model reads after the tool's result; a refusal stays as it is. */
export function withContext(ran: ToolCallResult, text: string): ToolCallResult {
  return ran.deny !== undefined ? ran : { ...ran, context: [...(ran.context ?? []), text] }
}

/** A toast for a failure the console survives (it fails open). */
export function failOpen($: $, what: string): (error: unknown) => void {
  return error => { $.ui.toast(`console: ${what} failed: ${message(error)}`) }
}

export type Context = { session: string; isActive: boolean; isRoundRole: boolean }

export async function context($: $): Promise<Context> {
  const role = await getRole($)
  const isActive = role !== null && (await getDrawn($))
  return { session: await $.session.id(), isActive, isRoundRole: isActive && ROUND_ROLES.includes(role.role) }
}

/** Reads the registry and the surfaces; registers the tool and opens the pane when a round role appears. */
export async function refreshRole($: $): Promise<Context> {
  const session = await $.session.id()
  const role = await readRole($, session).catch(() => null)
  const isDrawn = (await $.session.surfaces()).length > 0
  await setRole($, role)
  await setDrawn($, isDrawn)
  const isActive = role !== null && isDrawn
  const isRoundRole = isActive && ROUND_ROLES.includes(role.role)
  if (isRoundRole && !isToolRegistered) {
    isToolRegistered = true
    await registerTool($)
  }
  if (isRoundRole && !isPaneOpenedUnasked && !(await getPaneDismissed($))) {
    // Unasked: the engine seats it from 144 columns, else it waits for the person or a wider terminal.
    isPaneOpenedUnasked = true
    void $.ui.open({ id: PANE, title: 'Console' }).catch(failOpen($, 'opening the pane'))
  }
  return { session, isActive, isRoundRole }
}

/**
 * Above this a compaction frees something. Measured (r21): 56-72k right after a compaction, 91-120k within 25 calls, 272k-687k
 * at proposals after real work. Fixed, as what stays after a compaction does not grow with the window.
 */
const LARGE_CONTEXT_TOKENS = 150_000

/** No reading (a fresh session, one just compacted, a failed read) counts as small: a Start then only starts. */
async function isContextLarge($: $): Promise<boolean> {
  try {
    return ((await $.session.usage()).context.tokens ?? 0) >= LARGE_CONTEXT_TOKENS
  } catch {
    return false
  }
}

export async function refreshRound($: $, session: string): Promise<ConsoleRound | null> {
  try {
    const round = { ...await show($, session), isContextLarge: await isContextLarge($) }
    await setRound($, round)
    await setRoundError($, null)
    return round
  } catch (error) {
    await setRoundError($, message(error))
    return getRound($)
  }
}

export async function refreshBoard($: $, ctx: Context): Promise<ConsoleBoard> {
  const board = await boardViews($, ctx.session)
  await setBoard($, board)
  // Off the caller's path: the claim waits CLAIM_SETTLE_MS.
  $.clock.after(0, () => notifyIdleAgents($, ctx.session, board).catch(failOpen($, 'the idle-agent notification')))
  return board
}

/**
 * Everything the pane draws from; the board view takes about a second, so callers start this
 * from a timer. Single flight: a request while one runs is folded into one more run after it.
 */
export async function refreshAll($: $): Promise<void> {
  const now = await $.clock.now()
  if (!(await claimRefresh($, now, REFRESH_STALE_MS))) return
  try {
    do {
      const ctx = await refreshRole($)
      if (!ctx.isActive) return
      if (ctx.isRoundRole) await refreshRound($, ctx.session)
      await refreshBoard($, ctx)
    } while (await takeRefreshAgain($))
  } finally {
    await releaseRefresh($)
  }
}

export function refreshLater($: $): void {
  $.clock.after(0, () => refreshAll($).catch(failOpen($, 'refresh')))
}

const CLAIM_SETTLE_MS = 2_000

/**
 * An agent session idle with claimable work notifies once across consoles. Each watched
 * session has one marker, `<idle since> <claiming console>`: every console that sees a new
 * episode writes its claim, waits, and only the console whose claim survived notifies ($.fs has
 * no exclusive create; the last writer wins). Markers of sessions the board no longer lists go.
 */
async function notifyIdleAgents($: $, session: string, board: ConsoleBoard): Promise<void> {
  const dir = `${await stateDir($)}/console-notified`
  const listed = new Set(board.sessions.map(one => one.session))
  if (await $.fs.exists(dir)) {
    for (const entry of await $.fs.list(dir)) {
      if (!listed.has(entry.name)) await $.process.run(['rm', '-f', `${dir}/${entry.name}`], { timeoutMs: 5_000 })
    }
  }
  for (const one of board.sessions) {
    // Agents only (console-spec 3): an idle lead or solo waits on the user, and its claimable questions are no news.
    if (one.session === session || one.role !== 'agent' || one.state !== 'idle' || one.idleSince === null || one.claimable <= 0) continue
    const marker = `${dir}/${one.session}`
    if ((await $.fs.exists(marker)) && String(await $.fs.read(marker)).startsWith(`${one.idleSince} `)) continue
    const claim = `${one.idleSince} ${session}\n`
    await $.fs.write(marker, claim)
    await $.clock.sleep(CLAIM_SETTLE_MS)
    if (String(await $.fs.read(marker)) !== claim) continue
    await $.ui.notify(`${one.role} ${one.actor} is idle with ${one.claimable} claimable item${one.claimable === 1 ? '' : 's'}`, { title: 'Console' })
  }
}

async function registerTool($: $): Promise<void> {
  await $.tool.register({
    name: 'protocol',
    description: [
      "Runs the protocol engine for this session's round (`protocol <args>`): one call per step, per-question updates as JSON on stdin; the output is the next step.",
      'Read: ["show","--json"], ["show"], ["show","q3"] (that question whole), ["pending"], ["status","--line"], ["history"], ["next"].',
      'Record an answer the user typed in chat: ["answer"] with stdin {"question","answer","quote"}, the quote being the user\'s exact words.',
      'Apply a change the user asked for to the questions: ["edit"] with stdin {"updates","quote"}, the quote being the user\'s exact words.',
      'The console stamps --session and --origin; dialog answers, declines and passes are recorded by the console from the person\'s actions.',
    ].join(' '),
    inputSchema: {
      type: 'object',
      properties: {
        args: { type: 'array', items: { type: 'string' }, description: 'The verb and its arguments, e.g. ["start","round"], ["step"] or ["show","--json"]' },
        stdin: { type: 'string', description: 'JSON text for the verb (per-question updates), when it reads stdin' },
      },
      required: ['args'],
    },
    isDeferred: false,
  })
}

// Presses: await quick writes, start the run unawaited (the queue can pass the 10 s budget).

const runKey = (command: string, args: string): string => `${command} ${args}`.trim()

/** Claims a run unless the same one is still queued; false for a dropped repeat. */
export async function claimRun($: $, key: string): Promise<boolean> {
  const now = await $.clock.now()
  let isClaimed = false
  await updateQueued($, queued => {
    const live = queued.filter(one => now - one.at < QUEUED_EXPIRY_MS)
    isClaimed = !live.some(one => one.key === key)
    return isClaimed ? [...live, { key, at: now }] : live
  })
  return isClaimed
}

export async function releaseRun($: $, matches: (key: string) => boolean): Promise<void> {
  await updateQueued($, queued => queued.some(one => matches(one.key)) ? queued.filter(one => !matches(one.key)) : queued)
}

/** Records a pass with its origin while a round is open; the pending id when it is the pending pass. */
export async function recordPass($: $, ctx: Context, origin: ConsolePassOrigin, command: string, args: string): Promise<void> {
  if (!ctx.isRoundRole || !PASS_COMMANDS.includes(command)) return
  const round = await refreshRound($, ctx.session)
  if (round === null || !isRoundOpen(round)) return
  const pendingId = round.pending !== null && round.pending.command === command && round.pending.args === args ? round.pending.id : null
  if (pendingId !== null && (await getPass($))?.id !== pendingId) {
    // This run is the pending pass: turn.complete must not queue it again, and notes it if it ends unreported.
    // A model Skill call has already run; a typed or pressed command starts when its skill expands.
    await setPass($, { id: pendingId, command, phase: origin === 'model' ? 'started' : 'queued' })
  }
  try {
    const recorded = await pass($, ctx.session, origin, { command, args, pending: pendingId })
    await setRound($, recorded)
  } catch (error) {
    $.ui.toast(`console: recording /${command} failed: ${message(error)}`)
  }
}

/** The person's /release-round, typed or pressed: conditional approval (r4-q16); the engine starts or stamps the
 * release before the skill tells the model to continue it. A refusal (a round still open) reaches the person as a notice. */
export async function stampReleaseRun($: $, ctx: Context, origin: 'composer' | 'bridge' | 'press', args: string): Promise<void> {
  if (!ctx.isRoundRole) return
  try {
    await setRound($, await stampRelease($, ctx.session, origin, args))
  } catch (error) {
    await notice($, `/release-round did not reach the release: ${message(error)}`)
  }
}

/** Runs `/command args` as the person's press; drops a repeat while the same run is queued. `onFailed` follows a run that failed. */
export async function pressRun($: $, command: string, args: string, onFailed?: () => Promise<void>): Promise<void> {
  const key = runKey(command, args)
  if (!(await claimRun($, key))) {
    $.ui.toast(`/${key} is already queued`)
    return
  }
  if (command === RELEASE_COMMAND) await stampReleaseRun($, await context($), 'press', args)
  else await recordPass($, await context($), 'press', command, args)
  void $.command.run({ command, args }).catch(error => {
    void releaseRun($, one => one === key)
    $.ui.toast(`console: /${command} failed: ${message(error)}`)
    if (onFailed !== undefined) void onFailed().catch(failOpen($, `clearing the stored start after /${command}`))
  })
}

/** A session row's worker select: sets that session's count, without a model turn. */
export async function pressWorkers($: $, session: string, workers: string): Promise<void> {
  await setWorkers($, session, workers).catch(failOpen($, 'setting the worker count'))
  refreshLater($)
}

/** Submits a message as a prompt (Commit and Push, a role button, the dialog message); `onFailed` follows a submit that failed. */
export async function pressSubmit($: $, text: string, onFailed?: (error: unknown) => Promise<void>): Promise<void> {
  if (!(await claimRun($, `prompt:${text}`))) {
    $.ui.toast(`"${text}" is already queued`)
    return
  }
  const report = onFailed ?? failOpen($, `sending "${text}"`)
  const failed = async (error: unknown) => {
    await releaseRun($, key => key === `prompt:${text}`)  // it never started a turn: a retry is no repeat
    await report(error)
  }
  // A prompt that did not enter resolves as a drop with its reason; a refused text (a leading `/`) rejects.
  void $.prompt.submit({ text }).then(sent => { if (sent.drop !== undefined) return failed(new Error(sent.drop)) }).catch(failed)
}

/** The message a Start press sends (or stores, with compact): `protocol start round --topic '<title>: <premise>'`, then the ids that must lead. */
export const startText = (suggestion: Extract<ConsoleSuggestion, { kind: 'round' }>): string => {
  const topic = [suggestion.title, suggestion.premise].filter(part => part !== '').join(': ').replace(/'/g, `'\\''`)
  return `Start the next round: protocol start round --topic '${topic}'${suggestion.ids.map(id => ` ${id}`).join('')}`
}

/**
 * A suggestion's [ Start ]. A round sends its start message as the person's prompt; one that compacts first stores the message
 * and runs /compact (no focus text), and the compaction hook sends it once the compaction succeeded (register.tsx).
 * Release Round and a compact-only proposal run their commands.
 */
export async function pressStart($: $, suggestion: ConsoleSuggestion): Promise<void> {
  if (suggestion.kind === 'release') return pressRun($, RELEASE_COMMAND, '')
  if (suggestion.kind === 'compact') return pressRun($, 'compact', '')
  const text = startText(suggestion)
  if (!suggestion.isCompacting) return pressSubmit($, text)
  await setStart($, { text, at: await $.clock.now() })
  await pressRun($, 'compact', '', async () => {
    await setStart($, null)
    await notice($, `/compact failed: the next round (${suggestion.title}) was not started`)
  })
}

/** Opens (or closes) a suggestion's questions inline below its row; each listed id opens its item. */
export async function pressOpenSuggestion($: $, key: string, ids: readonly string[]): Promise<void> {
  await updateOpened($, current => current?.kind === 'suggestion' && current.key === key ? null : { kind: 'suggestion', key, ids: [...ids] })
}

/**
 * Opens a board item's summary inline below its row, or closes it on a second press; one item is open at a
 * time. The slow read runs on a timer, off the press's budget, and lands only if the item is still the open one.
 */
export async function pressOpenItem($: $, id: string, from: string | null = null): Promise<void> {
  let isOpening = false
  await updateOpened($, current => {
    isOpening = !(current?.kind === 'item' && current.id === id && current.from === from)
    return isOpening ? { kind: 'item', id, from, phase: 'reading', text: '', slot: null } : null
  })
  if (!isOpening) return
  const session = await $.session.id()
  $.clock.after(0, async () => {
    const read = await boardItem($, session, id).then(raw => ({ slot: itemSlot(id, raw), text: '' }), error => ({ slot: null, text: message(error) }))
    await updateOpened($, current => current?.kind === 'item' && current.id === id && current.from === from
      ? { ...current, phase: read.slot === null ? 'failed' : 'read', text: read.text, slot: read.slot } : current)
  })
}

/** Opens (or closes) a question's unresolved overlaps inline below its row; each listed id opens its item. */
export async function pressOpenOverlaps($: $, question: string, overlaps: readonly { id: string; title: string }[]): Promise<void> {
  await updateOpened($, current => current?.kind === 'overlaps' && current.question === question ? null
    : { kind: 'overlaps', question, overlaps: overlaps.map(one => ({ id: one.id, title: one.title })) })
}

/** Opens (or closes) the items a rule question settles inline below its row; each listed id opens its item. */
export async function pressOpenSettles($: $, question: string, ids: readonly string[]): Promise<void> {
  await updateOpened($, current => current?.kind === 'settles' && current.question === question ? null : { kind: 'settles', question, ids: [...ids] })
}

/** Switches the main view to a worker, or back to the main conversation (press only). */
export async function pressView($: $, agentId: string | undefined): Promise<void> {
  const viewed = await $.ui.view(agentId === undefined ? {} : { agentId })
  if (viewed.deny !== undefined) $.ui.toast(`console: ${viewed.deny}`)
}
