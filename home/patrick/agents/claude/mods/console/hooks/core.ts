// The console's shared actions over $: refresh, notices, pass records and presses. Function
// declarations throughout: past an import, the engine follows $ only into those.
import type { EngineInterface, ToolCallResult } from 'claude-code'

import type { ConsoleAction, ConsoleBoard, ConsolePassOrigin, ConsolePassRun, ConsolePending, ConsoleRound, ConsoleSuggestion } from '../types'

import { boardItem, boardViews, decline, dropped, isRoundOpen, pass, PASS_COMMANDS, pending as readPending, readRole, RELEASE_COMMAND, ROUND_ROLES, setWorkers, show, stampRelease, START_COMMAND, stateDir } from './engine'
import {
  claimRefresh, getAskSent, getDrawn, getPaneDismissed, getPass, getQueued, getRole, getRound, releaseRefresh, setAskSent, setBoard, setDrawn, setPass, setPrinted, setRole,
  setRound, setRoundError, setStart, takeRefreshAgain, updateOpened, updateQueued,
} from './state'
import {
  declineFailedNote, itemSlot, missingReportText, openDialogText, PROTOCOL_ARGS_DESCRIPTION, PROTOCOL_STDIN_DESCRIPTION, PROTOCOL_TOOL_DESCRIPTION, STALE_DROP, stuckPassText,
} from './words'

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

/**
 * A built-in command the person sent during a turn (`/compact`): its name and arguments, else null. Claude Code delivers what
 * arrives during a turn into it as text, a command included (2.1.318), and the model cannot run a built-in; the console runs it
 * when the turn ends instead (a run from the prompt hook would wait on that turn). Retire once Claude Code runs commands sent during
 * a turn as commands.
 */
export async function midTurnBuiltin($: $, text: string): Promise<{ command: string; args: string } | null> {
  const match = /^\/([\w:-]+)(?:\s+([\s\S]*))?$/.exec(text.trim())
  if (match === null) return null
  const [, name = '', args = ''] = match
  const commands = await $.command.list()
  return commands.some(one => one.name === name && one.source === 'builtin') ? { command: name, args: args.trim() } : null
}

/** The command that prints a batch's question text as its output (register.tsx registers and answers it by this literal name). */
const QUESTIONS_COMMAND = 'console-questions'

const OPEN_LABEL = 'Open the questions'
const NOT_NOW_LABEL = 'Not now'

/** Whether the drawn stand-in was answered Not now (`undefined`: `$.ui.ask` rejected); free text under "Other" is not. */
export const holdsQuestions = (chosen: string | undefined): boolean => chosen === NOT_NOW_LABEL

const DIALOG_PREFIX = 'Open the questions for batch '

/** The question `$.ui.ask` carries: the host takes labels only, so the console's AskUserQuestion hook swaps it for the issued batch. */
const dialogPlaceholder = (marker: string): string => `${DIALOG_PREFIX}${marker}?`

/** The marker a placeholder question names, or null for any other question. */
export const placeholderMarker = (question: unknown): string | null =>
  typeof question === 'string' && question.startsWith(DIALOG_PREFIX) ? question.slice(DIALOG_PREFIX.length, -1) : null

/** What the swapped dialog came to, set by the AskUserQuestion hook. `summary`: the visible line; `note`: the engine's text for the model; `isDropped`: the batch was no longer out, so nothing follows. */
export type DialogOutcome = { summary: string; note: string | null; unsavedDecline?: { marker: string; partial: Record<string, string> | null }; isDropped?: true }
let dialogOutcome: DialogOutcome | null = null
/** The marker openDialog waits on in this instance of the console; a reload starts it over, with the dialog still open. */
let dialogAwaited: string | null = null

/** The AskUserQuestion hook's outcome of the console's own dialog: to the openDialog waiting on it, else (opened before a reload)
 * the hook finishes it itself, so the answers are never left recorded and unannounced. */
export function deliverDialogOutcome($: $, marker: string, session: string, outcome: DialogOutcome): void {
  if (dialogAwaited === marker) {
    dialogOutcome = outcome
    return
  }
  void finishDialog($, marker, session, outcome).catch(failOpen($, 'handing on the dialog\'s answers'))
}

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
 * counts. Every outcome wakes the model with the answers line as its prompt, and its turn end runs a pending pass or opens the
 * next batch: a `$` call from this command hook skips every console hook (Claude Code 2.1.318, against its docs), so it can
 * neither print the line through a console command nor run `/console-questions` again. Without an outcome the swap never ran
 * and the stand-in was drawn: Not now holds the batch until the person's next message, anything else (a pick of Open, a close, a
 * timeout) has the model open the dialog.
 */
export async function openDialog($: $, marker: string, session: string): Promise<void> {
  dialogOutcome = null
  dialogAwaited = marker
  const chosen = await $.ui.ask(dialogPlaceholder(marker), { options: [OPEN_LABEL, NOT_NOW_LABEL], header: 'Round' }).catch(() => undefined)
  const outcome = dialogOutcome as DialogOutcome | null
  dialogOutcome = null
  dialogAwaited = null
  if (outcome === null) {
    // Not now leaves the batch out: askSent stays set, so the console reopens it after the person's next message (prompt.submit clears it).
    if (!holdsQuestions(chosen)) await askModelToOpen($, marker)
    return
  }
  await finishDialog($, marker, session, outcome)
}

/** What follows the console's own dialog: a decline Esc left unsaved is recorded, then the model wakes. */
async function finishDialog($: $, marker: string, session: string, outcome: DialogOutcome): Promise<void> {
  if (outcome.isDropped) return
  if (outcome.unsavedDecline !== undefined) {
    // Esc aborts the dialog hook's own runs, a retry there included; a run from here, after the dialog closed, goes through.
    try {
      const recorded = await decline($, session, outcome.unsavedDecline)
      await setRound($, recorded)
      outcome.note = recorded.note
    } catch (error) {
      outcome.note = declineFailedNote(marker, message(error))
      await notice($, outcome.note)
    }
  }
  await wakeModel($, outcome)
}

/**
 * At a main-agent turn's end that was not aborted, with a batch out (r29-q138, r30-q140, r32-q149): runs `/console-questions`, whose
 * hook prints the text and opens the dialog. A command's output draws whole between turns where a transcript row would not, and the hook's
 * fresh `$` matters too: after an awaited call in a chain, `$.ui.ask` skips the swap in the console's hook. One dialog per batch marker until
 * the person sends a new message (`prompt.submit` clears it) and none is open. A run that settles unanswered
 * by the hook takes the model's route instead of leaving the round waiting.
 */
export async function openBatchDialog($: $, round: ConsoleRound | null): Promise<void> {
  const batch = round?.batch
  if (round === null || round === undefined || !isRoundOpen(round) || batch === null || batch === undefined || (await getAskSent($)) === batch.marker) return
  if (dialogAwaited === batch.marker) {  // the person's message cleared the repeat guard while this console's dialog is still open
    await reportDrop($, await $.session.id(), { kind: 'batch', marker: batch.marker })
    return
  }
  await setAskSent($, batch.marker)
  questionsAnswered = null
  void $.command.run({ command: QUESTIONS_COMMAND, args: batch.marker })
    .then(() => questionsAnswered === batch.marker ? undefined : openUnanswered($, batch))
    .catch(async error => {
      await setPrinted($, null).catch(() => undefined)
      await setAskSent($, null).catch(() => undefined)
      await notice($, `printing the question text failed: ${message(error)}; nothing opens the dialog`).catch(() => undefined)
    })
}

/** The marker the `/console-questions` hook last answered; a run that settles without it never reached the hook. */
let questionsAnswered: string | null = null
export const setQuestionsAnswered = (marker: string): void => { questionsAnswered = marker }

/** The command's hook never ran: the person reads any new text as a notice, and the model opens the dialog. */
async function openUnanswered($: $, batch: { marker: string; notice: string }): Promise<void> {
  if (batch.notice.trim() !== '') await notice($, `\n${batch.notice}`)
  await setPrinted($, batch.marker)
  await askModelToOpen($, batch.marker)
}

/** The route when the console cannot open the dialog itself. */
async function askModelToOpen($: $, marker: string): Promise<void> {
  await pressSubmit($, openDialogText(marker), async error => {
    await setAskSent($, null).catch(() => undefined)
    await notice($, `sending the message that opens the dialog failed: ${message(error)}`).catch(() => undefined)
  }, true, { kind: 'batch', marker })
}

/** What follows a turn: the pending pass, and the issued batch's print and dialog. */
export async function betweenTurns($: $, session: string, isAborted: boolean): Promise<void> {
  const pending = await readPending($, session)
  const run = await getPass($)
  if (pending !== null && run !== null && run.id === pending.id) {
    if (run.phase !== 'noted' && run.phase !== 'stopped' && isAborted) {
      // Esc stops the loop: the pass stays pending and is not run again, except by a compaction right after (rerunStoppedPass).
      await setPass($, { ...run, phase: 'stopped' })
    } else if (run.phase === 'started') {
      await setPass($, { ...run, phase: 'asked' })
      await pressSubmit($, missingReportText(pending.command, pending.id, pending.args), undefined, true, { kind: 'pass', id: pending.id, command: pending.command, args: pending.args })
    } else if (run.phase === 'asked') {
      await setPass($, { ...run, phase: 'noted' })
      await notice($, stuckPassText(pending.command, pending.args))
    }
  } else if (pending !== null && !isAborted) {
    await queuePending($, session, pending)
  }
  // The issued batch's text prints between turns, then the console opens its dialog (an aborted turn does neither, as it runs no
  // pass; an away session has no batch to open).
  if (!isAborted && (await getRole($))?.role !== 'autopilot') {
    await openBatchDialog($, await refreshRound($, session))
  }
}

/** Queues the engine's pending pass: stores it, records it with origin plugin, and runs it. The run goes last: later `$` calls in the chain skip the console's hooks. */
async function queuePending($: $, session: string, pending: ConsolePending): Promise<void> {
  await setPass($, { id: pending.id, command: pending.command, args: pending.args, phase: 'queued' })
  await pass($, session, 'plugin', { command: pending.command, args: pending.args, pending: pending.id })
    .catch(failOpen($, `recording /${pending.command}`))
  void $.command.run({ command: pending.command, args: pending.args }).catch(failOpen($, `running /${pending.command}`))
}

/** After a successful compaction: runs the pass an Esc stopped once more, if it is still the engine's pending pass. Queued again, so it never runs twice. */
export async function rerunStoppedPass($: $, session: string): Promise<void> {
  const run = await getPass($)
  if (run === null || run.phase !== 'stopped') return
  const pending = await readPending($, session)
  if (pending !== null && pending.id === run.id) await queuePending($, session, pending)
}

/** A role button's press: the person's own `/role <role>`. A prompt text beginning with `/` is refused by the host, so it runs as a command (the press route of Commit and Retro). */
export async function pressRole($: $, role: 'solo' | 'autopilot'): Promise<void> {
  await pressRun($, 'role', role)
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
    description: PROTOCOL_TOOL_DESCRIPTION,
    inputSchema: {
      type: 'object',
      properties: {
        args: { type: 'array', items: { type: 'string' }, description: PROTOCOL_ARGS_DESCRIPTION },
        stdin: { type: 'string', description: PROTOCOL_STDIN_DESCRIPTION },
      },
      required: ['args'],
    },
    isDeferred: false,
  })
}

// Presses: await quick writes, start the run unawaited (the queue can pass the 10 s budget).

const runKey = (command: string, args: string): string => `${command} ${args}`.trim()

/** Claims a run unless the same one is still queued; false for a dropped repeat. A prompt's `action` is re-checked where it is delivered. */
export async function claimRun($: $, key: string, action?: ConsoleAction): Promise<boolean> {
  const now = await $.clock.now()
  let isClaimed = false
  await updateQueued($, queued => {
    const live = queued.filter(one => now - one.at < QUEUED_EXPIRY_MS)
    isClaimed = !live.some(one => one.key === key)
    return isClaimed ? [...live, { key, at: now, ...(action === undefined ? {} : { action }) }] : live
  })
  return isClaimed
}

export async function releaseRun($: $, matches: (key: string) => boolean): Promise<void> {
  await updateQueued($, queued => queued.some(one => matches(one.key)) ? queued.filter(one => !matches(one.key)) : queued)
}

/** Arguments compare with whitespace collapsed: the same words typed with other spacing are the same run. */
const collapsed = (args: string): string => args.split(/\s+/).filter(word => word !== '').join(' ')

/**
 * The one staleness test of every queued console action: whether the round no longer holds what the action was queued for.
 * The host queues what the console sends and cannot recall it, so each delivery point asks this against a fresh read.
 */
export function isStale(round: ConsoleRound | null, action: ConsoleAction): boolean {
  if (round === null || !isRoundOpen(round)) return true
  if (action.kind === 'batch') return round.batch?.marker !== action.marker
  const waiting = round.pending
  return waiting === null || waiting.id !== action.id || waiting.command !== action.command || collapsed(waiting.args) !== collapsed(action.args)
}

/** Logs a dropped action in the engine's history; a failed report is a toast, the drop stands. */
export async function reportDrop($: $, session: string, action: ConsoleAction): Promise<void> {
  await dropped($, session, action).catch(failOpen($, 'reporting a dropped action'))
}

/** Reads the round and, when the action is stale, reports the drop: true means the caller drops it. A failed read keeps the last one. */
export async function dropIfStale($: $, action: ConsoleAction): Promise<boolean> {
  const session = await $.session.id()
  if (!isStale(await refreshRound($, session), action)) return false
  await reportDrop($, session, action)
  return true
}

/**
 * A prompt the console queued, as the host delivers it (`prompt.submit`, origin the console's): the reason to drop it when the
 * round moved on meanwhile, else null. The prompts are registered by their text with their action (claimRun).
 */
export async function staleDelivery($: $, text: string): Promise<string | null> {
  const key = `prompt:${text}`
  const action = (await getQueued($)).find(one => one.key === key)?.action
  if (action === undefined || !(await dropIfStale($, action))) return null
  await releaseRun($, one => one === key)  // a dropped prompt starts no turn, which would release it
  return STALE_DROP
}

/** The pass a skill expansion belongs to: the stored queued run of that command; null when there is none or the engine's pending pass is another (a stale run, dropped and reported). */
export async function startedPass($: $, skill: string): Promise<{ run: ConsolePassRun; isStale: boolean } | null> {
  const run = await getPass($)
  if (run === null || run.phase !== 'queued' || run.command !== skill) return null
  const session = await $.session.id()
  const stale = isStale(await refreshRound($, session), { kind: 'pass', ...run })
  if (stale) {
    await setPass($, { ...run, phase: 'noted' })  // one stale run per stored pass: a later run of the command is not it
    await reportDrop($, session, { kind: 'pass', ...run })
  }
  return { run, isStale: stale }
}

/** Records a pass with its origin while a round is open; the pending id when it is the pending pass. */
export async function recordPass($: $, ctx: Context, origin: ConsolePassOrigin, command: string, args: string): Promise<void> {
  if (!ctx.isRoundRole || !PASS_COMMANDS.includes(command)) return
  const round = await refreshRound($, ctx.session)
  if (round === null || !isRoundOpen(round)) return
  const pendingId = round.pending !== null && round.pending.command === command && collapsed(round.pending.args) === collapsed(args) ? round.pending.id : null
  if (pendingId !== null && (await getPass($))?.id !== pendingId) {
    // This run is the pending pass: turn.complete must not queue it again, and notes it if it ends unreported.
    // A model Skill call has already run; a typed or pressed command starts when its skill expands.
    await setPass($, { id: pendingId, command, args, phase: origin === 'model' ? 'started' : 'queued' })
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

/** Submits the person's press or picks as their own words, read without the host's plugin frame; `isConsoleWords` keeps the frame on the console's own request. `onFailed` follows a submit that failed; `action` is what the prompt is about, dropped where it is delivered if the round moved on. */
export async function pressSubmit($: $, text: string, onFailed?: (error: unknown) => Promise<void>, isConsoleWords = false, action?: ConsoleAction): Promise<void> {
  // Checked here as well as at delivery: the console's own prompt reaches its prompt.submit hook only from some call chains (the kit skips it after an awaited console command).
  if (action !== undefined && (await dropIfStale($, action))) return
  if (!(await claimRun($, `prompt:${text}`, action))) {
    $.ui.toast(`"${text}" is already queued`)
    return
  }
  const report = onFailed ?? failOpen($, `sending "${text}"`)
  const failed = async (error: unknown) => {
    await releaseRun($, key => key === `prompt:${text}`)  // it never started a turn: a retry is no repeat
    await report(error)
  }
  // A prompt that did not enter resolves as a drop with its reason; a refused text (a leading `/`) rejects.
  void $.prompt.submit(isConsoleWords ? { text } : { text, asUser: true }).then(sent => { if (sent.drop !== undefined && sent.drop !== STALE_DROP) return failed(new Error(sent.drop)) }).catch(failed)
}

/**
 * A suggestion's [ Start ]. A round runs `/start-round <row>`, which starts that row of the stored proposal (the press is the
 * go-ahead, so no stamp); one that compacts first stores the command and runs /compact (no focus text), and the compaction hook
 * runs it once the compaction succeeded (register.tsx). Release Round and a compact-only proposal run their commands.
 */
export async function pressStart($: $, suggestion: ConsoleSuggestion): Promise<void> {
  if (suggestion.kind === 'release') return pressRun($, RELEASE_COMMAND, '')
  if (suggestion.kind === 'compact') return pressRun($, 'compact', '')
  const args = String(suggestion.number)
  if (!suggestion.isCompacting) return pressRun($, START_COMMAND, args)
  await setStart($, { command: START_COMMAND, args, title: suggestion.title, at: await $.clock.now() })
  await pressRun($, 'compact', '', async () => {
    await setStart($, null)
    await notice($, `/compact failed: the next round (${suggestion.title}) was not started`)
  })
}

/** Opens (or closes) a suggestion's leading questions inline below its row, each with its title; each listed id opens its item. */
export async function pressOpenSuggestion($: $, key: string, leads: readonly { id: string; title: string }[]): Promise<void> {
  await updateOpened($, current => current?.kind === 'suggestion' && current.key === key ? null : { kind: 'suggestion', key, leads: leads.map(one => ({ id: one.id, title: one.title })) })
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
