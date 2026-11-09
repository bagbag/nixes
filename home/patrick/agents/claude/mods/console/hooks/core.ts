// The console's shared actions over $: refresh, notices, pass records and presses. Function
// declarations throughout: past an import, the engine follows $ only into those.
import type { EngineInterface, ToolCallResult } from 'claude-code'

import type { ConsoleAction, ConsoleBatch, ConsoleBoard, ConsolePassOrigin, ConsolePassRun, ConsolePending, ConsoleQueued, ConsoleRound, ConsoleSuggestion } from '../types'

import { boardItem, boardViews, decline, dropped, isRoundOpen, nudged, pass, PASS_COMMANDS, pending as readPending, readRole, RELEASE_COMMAND, ROUND_ROLES, setWorkers, show, stampRelease, START_COMMAND, startScope, stateDir, statusLine } from './engine'
import type { ConsoleNudge } from './engine'
import {
  claimRefresh, getAskSent, getDrawn, getPaneDismissed, getPass, getQueued, getRole, getRound, getTurnRunning, releaseRefresh, setAskSent, setBoard, setContinueAsked, setDrawn, setPass, setPrinted, setRole,
  setRound, setRoundError, setStart, takeContinueAsked, takeRefreshAgain, updateOpened, updateQueued,
} from './state'
import {
  CONTINUE_NO_ROUND, continueInHandText, continueText, declineFailedNote, itemSlot, missingReportText, openDialogText, PROTOCOL_ARGS_DESCRIPTION, PROTOCOL_STDIN_DESCRIPTION, PROTOCOL_TOOL_DESCRIPTION, STALE_DROP, stuckPassText,
} from './words'

type $ = EngineInterface

export const PANE = 'console'
const QUEUED_EXPIRY_MS = 10 * 60_000
const QUEUED_PASS_EXPIRY_MS = 60 * 60_000  // a queued pass command waits out the turns before it; a record past this is an orphan the host never ran
const REFRESH_STALE_MS = 2 * 60_000  // a run this old is stuck (a board call that never returns): take over

// Module state a reload may lose without harm: session.start resets it.
let isToolRegistered = false
let isPaneOpenedUnasked = false
/** The person's typed or pressed pass commands not yet expanded, by command: their expansion is no console-queued pass (startedPass). */
const personRuns = new Map<string, number>()

export function resetSession(): void {
  isToolRegistered = false
  isPaneOpenedUnasked = false
  personRuns.clear()
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

/**
 * What the swapped dialog came to, set by the AskUserQuestion hook. `summary`: the visible line; `note`: the engine's text for the model;
 * `unsavedDecline`: a decline Esc kept the hook from saving; `isDropped`: the batch was no longer out, so nothing follows; `isWoken`: the
 * hook already woke the model with it.
 */
export type DialogOutcome = { summary: string; note: string | null; unsavedDecline?: { marker: string; partial: Record<string, string> | null }; isDropped?: true; isWoken?: true }
let dialogOutcome: DialogOutcome | null = null
/** The marker openDialog waits on in this instance of the console; a reload starts it over, with the dialog still open. */
let dialogAwaited: string | null = null

/**
 * The AskUserQuestion hook's outcome of the console's own dialog (r7-q25). What the hook recorded, or failed to save for a reason other
 * than Esc, wakes the model from here at once: the opener's `$.ui.ask` may never settle (a reload while the dialog was open), and a
 * recorded answer must never wait on it. The opener, when this instance has one, only learns that it was handled. A drop and a decline
 * Esc left unsaved go to the opener (Esc aborts the hook's own runs, a retry included), else the hook finishes them itself.
 */
export function deliverDialogOutcome($: $, marker: string, session: string, outcome: DialogOutcome): void {
  const isWaking = outcome.unsavedDecline === undefined && !outcome.isDropped
  if (isWaking) {
    void wakeModel($, outcome).catch(async error => {
      await notice($, `telling the model about the answers failed: ${message(error)}`).catch(() => undefined)
    })
  }
  if (dialogAwaited === marker) {
    dialogOutcome = isWaking ? { ...outcome, isWoken: true } : outcome
    return
  }
  if (!isWaking) void finishDialog($, marker, session, outcome).catch(failOpen($, 'handing on the dialog\'s answers'))
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
 * counts. Every outcome wakes the model with the answers line as its prompt (the hook itself, r7-q25, but for a decline Esc left
 * unsaved, recorded and announced here), and its turn end runs a pending pass or opens the next batch: by the time the dialog closes
 * the opener's command hook has returned, and its later `$` calls skip every console hook (showQuestions), so it can neither print
 * the line through a console command nor run `/console-questions` again. Without an outcome the swap never ran and the stand-in was
 * drawn: Not now holds the batch until the person's next message, anything else (a pick of Open, a close, a timeout) has the model
 * open the dialog.
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
  if (!outcome.isWoken) await finishDialog($, marker, session, outcome)
}

/** What follows a drop or a decline Esc left unsaved: the decline is recorded, then the model wakes; a drop ends here. */
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
 * Takes the issued batch for its dialog: null when no batch is out, the repeat guard holds it (one dialog per batch marker until the
 * person sends a new message, `prompt.submit` clearing it) or this console's dialog for it is still open (a drop, reported).
 */
async function claimBatch($: $, round: ConsoleRound | null): Promise<ConsoleBatch | null> {
  const batch = round?.batch
  if (round === null || round === undefined || !isRoundOpen(round) || batch === null || batch === undefined || (await getAskSent($)) === batch.marker) return null
  if (dialogAwaited === batch.marker) {  // the person's message cleared the repeat guard while this console's dialog is still open
    await reportDrop($, await $.session.id(), { kind: 'batch', marker: batch.marker })
    return null
  }
  await setAskSent($, batch.marker)
  return batch
}

/** How long showQuestions holds its command hook for the swap: past it the text prints, and the dialog fares as the host lets it. */
const SWAP_WAIT_MS = 2_000

/** Ends showQuestions' hold once the AskUserQuestion hook swapped in its batch (dialogSwapped). */
let swapWaited: { marker: string; resolve: () => void } | null = null

/** Called by the AskUserQuestion hook as it swaps a placeholder for its batch. */
export function dialogSwapped(marker: string): void {
  if (swapWaited?.marker !== marker) return
  swapWaited.resolve()
  swapWaited = null
}

/**
 * The batch's dialog from a console hook whose `$` reaches the console's own hooks (`/console-questions` run by the console, a typed
 * `/console-continue`): marks its text printed and opens the dialog, unless this console's dialog for it is open already. The caller
 * awaits it and then prints the text as its command output. It returns once the AskUserQuestion hook swapped in the batch (or the
 * dialog settled, or SWAP_WAIT_MS passed): the host credits a `$` call to its hook only while that hook's dispatch is in flight, and
 * counts one it takes later as the whole console's, skipping every console hook. The calls and the hook's return cross on separate
 * channels (Claude Code 2.1.319), so a `$.ui.ask` made just before the return could land after it, and the stand-in was drawn.
 */
export async function showQuestions($: $, marker: string, session: string): Promise<void> {
  await setPrinted($, marker)
  questionsAnswered = marker
  if (dialogAwaited === marker) return
  const swapped = new Promise<void>(resolve => { swapWaited = { marker, resolve } })
  const opened = openDialog($, marker, session).catch(failOpen($, 'opening the dialog'))
  await Promise.race([swapped, opened, $.clock.sleep(SWAP_WAIT_MS)])
}

/**
 * At a main-agent turn's end that was not aborted, or a continue the person asked for, with a batch out (r29-q138, r30-q140,
 * r32-q149): runs `/console-questions`, whose hook prints the text and opens the dialog. A command's output draws whole between turns
 * where a transcript row would not, and the hook's own dispatch matters too: it is in flight while the dialog opens (showQuestions).
 * The caller's hook stays in flight until the host has the run: one more round trip on the console's channel, which the host takes
 * in order, follows it. A run that settles unanswered by the hook (one from a press or a timer, whose `$` skips the console's own
 * hooks) takes the model's route instead of leaving the round waiting. Returns the marker it took, else null.
 */
export async function openBatchDialog($: $, round: ConsoleRound | null): Promise<string | null> {
  const batch = await claimBatch($, round)
  if (batch === null) return null
  questionsAnswered = null
  void $.command.run({ command: QUESTIONS_COMMAND, args: batch.marker })
    .then(() => questionsAnswered === batch.marker ? undefined : openUnanswered($, batch))
    .catch(async error => {
      await setPrinted($, null).catch(() => undefined)
      await setAskSent($, null).catch(() => undefined)
      await notice($, `printing the question text failed: ${message(error)}; nothing opens the dialog`).catch(() => undefined)
    })
  await $.session.id()  // the round trip that holds the caller's hook until the host has the run
  return batch.marker
}

/** The marker the `/console-questions` hook last answered; a run that settles without it never reached the hook. */
let questionsAnswered: string | null = null

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

/** When the turn-end decision runs: at a main-agent turn's end (`ended`, `aborted`), or on the person's /console-continue (`asked`). */
type Occasion = 'ended' | 'aborted' | 'asked'

/** How the batch's dialog opens: `openBatchDialog`, or from a typed /console-continue's own hook (continueTyped). Returns the marker taken, else null. */
type BatchOpener = (round: ConsoleRound | null) => Promise<string | null>

/** What the turn-end decision started: the pending pass it queued, the batch whose dialog it took; `inHand`: the pending pass, left alone as queued already. */
type Started = { pass: ConsolePending | null; batch: string | null; inHand: ConsolePending | null }

/**
 * The turn-end decision's pass part. Asked for (/console-continue, r7-q24), it queues the pending pass whatever its stored run came to
 * (stopped, asked for or noted) unless that run is still queued; a started one gets the turn end's request for its report.
 */
async function decidePass($: $, session: string, occasion: Occasion): Promise<Omit<Started, 'batch'>> {
  const pending = await readPending($, session)
  const run = await getPass($)
  const isStored = pending !== null && run !== null && run.id === pending.id
  if (isStored && run.phase === 'started' && occasion !== 'aborted') {
    await setPass($, { ...run, phase: 'asked' })
    await pressSubmit($, missingReportText(pending.command, pending.id, pending.args), undefined, true, { kind: 'pass', id: pending.id, command: pending.command, args: pending.args })
  } else if (occasion === 'asked' && pending !== null) {
    if (isStored && run.phase === 'queued') return { pass: null, inHand: pending }
    await queuePending($, session, pending)
    return { pass: pending, inHand: null }
  } else if (isStored) {
    if (run.phase !== 'noted' && run.phase !== 'stopped' && occasion === 'aborted') {
      // Esc stops the loop: the pass stays pending and is not run again, except by a compaction right after (rerunStoppedPass).
      await setPass($, { ...run, phase: 'stopped' })
    } else if (run.phase === 'asked') {
      await setPass($, { ...run, phase: 'noted' })
      await notice($, stuckPassText(pending.command, pending.args))
    }
  } else if (pending !== null && occasion === 'ended') {
    await queuePending($, session, pending)
    return { pass: pending, inHand: null }
  }
  return { pass: null, inHand: null }
}

/**
 * The turn-end decision's batch part: the issued batch's text prints between turns, then the console opens its dialog (an aborted
 * turn does neither, as it runs no pass; an away session has no batch to open). Asked for, it reopens a batch the repeat guard holds,
 * as the person's own message would.
 */
async function decideBatch($: $, session: string, occasion: Occasion, openBatch: BatchOpener): Promise<string | null> {
  if (occasion === 'aborted' || (await getRole($))?.role === 'autopilot') return null
  if (occasion === 'asked') await setAskSent($, null)
  return openBatch(await refreshRound($, session))
}

/** The turn-end decision: the pending pass, and the issued batch's print and dialog. */
async function decideNext($: $, session: string, occasion: Occasion): Promise<Started> {
  const passed = await decidePass($, session, occasion)
  return { ...passed, batch: await decideBatch($, session, occasion, round => openBatchDialog($, round)) }
}

/** What follows a turn. */
export async function betweenTurns($: $, session: string, isAborted: boolean): Promise<void> {
  await decideNext($, session, isAborted ? 'aborted' : 'ended')
}

/** The command that runs the turn-end decision on the person's request (register.tsx registers and answers it by this literal name). */
export const CONTINUE_COMMAND = 'console-continue'

/**
 * A continue the person asked for (r7-q24): a round that stalled picks up where the turn-end decision would take it. With nothing
 * pending or out, it wakes the model at the open step with the engine's status line: the press is the request. Each use is
 * logged with what it did (`nudged`). It runs only while no turn does: asked during one, it waits for the turn's end (continueLater).
 * `taken`: the batch a typed continue's own hook already took (continueTyped).
 */
async function continueRound($: $, taken?: { batch: string | null }): Promise<void> {
  const ctx = await refreshRole($)
  if (!ctx.isRoundRole) return notice($, CONTINUE_NO_ROUND)
  const before = await refreshRound($, ctx.session)
  if (before === null || !isRoundOpen(before)) {
    await notice($, CONTINUE_NO_ROUND)
    return reportNudge($, ctx.session, {})
  }
  const started = taken === undefined ? await decideNext($, ctx.session, 'asked') : { ...await decidePass($, ctx.session, 'asked'), batch: taken.batch }
  if (started.pass !== null || started.batch !== null) {
    return reportNudge($, ctx.session, { ...(started.pass === null ? {} : { pass: started.pass.id }), ...(started.batch === null ? {} : { batch: started.batch }) })
  }
  if (started.inHand !== null) {
    await notice($, continueInHandText(started.inHand.command, started.inHand.id))
    return reportNudge($, ctx.session, {})
  }
  const round = (await getRound($)) ?? before
  if (round.pending !== null) return reportNudge($, ctx.session, {})  // a started pass: asked for its report above
  let line: string
  try {
    line = await statusLine($, ctx.session)
  } catch (error) {
    return notice($, `reading the round's status failed: ${message(error)}; nothing was continued`)
  }
  if (!isRoundOpen(round)) {
    await notice($, CONTINUE_NO_ROUND)
    return reportNudge($, ctx.session, {})
  }
  await pressSubmit($, continueText(line), async error => {
    await notice($, `waking the model to continue the round failed: ${message(error)}`).catch(() => undefined)
  }, true)
  await reportNudge($, ctx.session, { step: round.step ?? '' })
}

/**
 * A typed /console-continue, from its command hook; returns the command's output, a reopened batch's text. The batch's dialog opens
 * here, as `/console-questions` opens it: from a later event `$.ui.ask` would skip the console's own swap. The rest runs on a timer
 * once the hook answered, as the host refuses a command run from a command hook (it would wait on the turn the hook holds).
 */
export async function continueTyped($: $): Promise<string | undefined> {
  const ctx = await refreshRole($)
  let text: string | undefined
  const opened = ctx.isRoundRole ? await decideBatch($, ctx.session, 'asked', async round => {
    const batch = await claimBatch($, round)
    if (batch === null) return null
    await showQuestions($, batch.marker, ctx.session)
    if (batch.notice.trim() !== '') text = `\n${batch.notice}`
    return batch.marker
  }) : null
  $.clock.after(0, () => continueRound($, { batch: opened }).catch(failOpen($, 'continuing the round')))
  return text
}

/** A continue asked for during a turn, by a press or typed: the turn's end runs it (register.tsx) unless Esc ended the turn. */
export async function continueLater($: $): Promise<void> {
  await setContinueAsked($, true)
  await notice($, '/console-continue runs when this turn ends (Esc drops it).')
}

/**
 * The Continue press: runs at once while the session is idle (off the press's budget), else at the turn's end. A press's `$` skips the
 * console's own hooks, so an idle press hands a batch to the model to open.
 */
export async function pressContinue($: $): Promise<void> {
  if (await getTurnRunning($)) return continueLater($)
  $.clock.after(0, () => continueRound($).catch(failOpen($, 'continuing the round')))
}

/** At a main-agent turn's end: a continue asked for during the turn runs in place of the plain decision; Esc drops it. */
export async function afterTurn($: $, session: string, isAborted: boolean): Promise<void> {
  const isAsked = await takeContinueAsked($)
  if (isAsked && !isAborted) return continueRound($)
  await betweenTurns($, session, isAborted)
}

/** Logs a continue in the engine's history; a failed report is a toast, what it did stands. */
async function reportNudge($: $, session: string, report: ConsoleNudge): Promise<void> {
  await nudged($, session, report).catch(failOpen($, 'logging the continue'))
}

/**
 * Queues the engine's pending pass: stores it, remembers the queued command until its skill expands (r8-q26), records it with origin
 * plugin, and runs it. The run goes last: later `$` calls in the chain skip the console's hooks. A run the host refuses (an unknown
 * name, past a Stop) clears its stored run and its queued record, so nothing counts as in hand for the next turn end or a continue
 * (r7-q24).
 */
async function queuePending($: $, session: string, pending: ConsolePending): Promise<void> {
  const action: ConsoleAction = { kind: 'pass', id: pending.id, command: pending.command, args: pending.args }
  const key = `${QUEUED_PASS_KEY}${pending.id}`
  await setPass($, { id: pending.id, command: pending.command, args: pending.args, phase: 'queued' })
  const now = await $.clock.now()
  await updateQueued($, queued => [...queued, { key, at: now, action }])  // not claimRun: a pass queued again is a second command
  await pass($, session, 'plugin', { command: pending.command, args: pending.args, pending: pending.id })
    .catch(failOpen($, `recording /${pending.command}`))
  void $.command.run({ command: pending.command, args: pending.args }).catch(async error => {
    const run = await getPass($).catch(() => null)
    if (run !== null && run.id === pending.id && run.phase === 'queued') await setPass($, null).catch(() => undefined)
    await updateQueued($, queued => {
      const at = queued.findLastIndex(one => one.key === key)
      return at < 0 ? queued : queued.filter((_, index) => index !== at)
    }).catch(() => undefined)
    failOpen($, `running /${pending.command}`)(error)
  })
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

/** The key prefix of a pass command the console queued (queuePending): it waits in the host's queue behind whole turns, so it keeps the longer expiry. */
const QUEUED_PASS_KEY = 'pass:'

const isLive = (one: { key: string; at: number }, now: number): boolean =>
  now - one.at < (one.key.startsWith(QUEUED_PASS_KEY) ? QUEUED_PASS_EXPIRY_MS : QUEUED_EXPIRY_MS)

/** Claims a run unless the same one is still queued; false for a dropped repeat. A prompt's `action` is re-checked where it is delivered. */
export async function claimRun($: $, key: string, action?: ConsoleAction): Promise<boolean> {
  const now = await $.clock.now()
  let isClaimed = false
  await updateQueued($, queued => {
    const live = queued.filter(one => isLive(one, now))
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

/** A typed or pressed pass command, as it is queued: its expansion is the person's run (startedPass). */
export function notePersonRun(command: string): void {
  if (PASS_COMMANDS.includes(command)) personRuns.set(command, (personRuns.get(command) ?? 0) + 1)
}

function takePersonRun(command: string): boolean {
  const count = personRuns.get(command) ?? 0
  if (count > 1) personRuns.set(command, count - 1)
  else personRuns.delete(command)
  return count > 0
}

const isQueuedPassOf = (one: ConsoleQueued[number], skill: string): boolean => one.key.startsWith(QUEUED_PASS_KEY) && one.action?.kind === 'pass' && one.action.command === skill

/**
 * The pass command the console queued for this skill that this expansion is, taken off the list (expired records go too): one still
 * pending, else the oldest. An orphan (a queued command the host never ran) thus never takes a fresh run's place; the other records
 * stay for the commands still waiting behind it.
 */
async function takeQueuedPass($: $, skill: string, round: ConsoleRound | null): Promise<ConsoleAction | null> {
  const now = await $.clock.now()
  let taken: ConsoleAction | null = null
  await updateQueued($, all => {
    const queued = all.filter(one => isLive(one, now))
    const fresh = queued.findIndex(one => isQueuedPassOf(one, skill) && one.action !== undefined && !isStale(round, one.action))
    const at = fresh >= 0 ? fresh : queued.findIndex(one => isQueuedPassOf(one, skill))
    taken = queued[at]?.action ?? null
    return at < 0 && queued.length === all.length ? all : queued.filter((_, index) => index !== at)
  })
  return taken
}

/**
 * A skill expansion other than the model's own Skill call (modelStartedPass): the console's queued pass command (its queued
 * record of the skill, r8-q26), else the person's run, which only the stored queued run of that command can belong to. Starts the
 * stored run it belongs to; true when the round has left that pass: the caller rewrites the expansion, the drop is reported and the
 * stored run noted (one stale run per stored pass: a later run of the command is not it).
 */
export async function startedPass($: $, skill: string): Promise<boolean> {
  const isPerson = takePersonRun(skill)
  const run = await getPass($)
  const stored = run !== null && run.phase === 'queued' && run.command === skill ? run : null
  const isRecorded = !isPerson && (await getQueued($)).some(one => isQueuedPassOf(one, skill))
  if (stored === null && !isRecorded) return false
  const session = await $.session.id()
  const round = await refreshRound($, session)
  const queued = isRecorded ? await takeQueuedPass($, skill, round) : null
  const action: ConsoleAction | null = queued ?? (stored === null ? null : { kind: 'pass', id: stored.id, command: stored.command, args: stored.args })
  if (action === null || action.kind !== 'pass') return false
  const stale = isStale(round, action)
  const isStored = stored !== null && stored.id === action.id
  if (stale) {
    if (isStored) await setPass($, { ...stored, phase: 'noted' })
    await reportDrop($, session, action)
  } else if (isStored) {
    await setPass($, { ...stored, phase: 'started' })
  }
  return stale
}

/**
 * The model's own Skill call expanding a pass skill: it never takes the console's queued record, is never rewritten and drops nothing.
 * It starts the stored queued run of that command while that run is the pending pass, so a turn end asks for its report.
 */
export async function modelStartedPass($: $, skill: string): Promise<void> {
  const run = await getPass($)
  if (run === null || run.phase !== 'queued' || run.command !== skill) return
  if (!isStale(await refreshRound($, await $.session.id()), { kind: 'pass', ...run })) await setPass($, { ...run, phase: 'started' })
}

/** The stamp a run of `command args` carries: the pending pass's id when it is that pass, else null. */
const pendingStamp = (round: ConsoleRound, command: string, args: string): string | null =>
  round.pending !== null && round.pending.command === command && collapsed(round.pending.args) === collapsed(args) ? round.pending.id : null

/**
 * A pass skill's expanded text with the line naming what its report must cover, worked out by the engine as the pass starts
 * (r9-q36): the step named the scope a turn earlier, and it may have changed since. `modelArgs`: a model Skill call's arguments,
 * whose run is recorded only once it ran; left out, the run is recorded already. The text stays as it is when there is nothing to
 * name or the engine fails (fail open).
 */
export async function withStartScope($: $, text: string, skill: string, modelArgs?: string): Promise<string> {
  try {
    const ctx = await context($)
    if (!ctx.isRoundRole || !PASS_COMMANDS.includes(skill)) return text
    let pending: { pending?: string | null } = {}
    if (modelArgs !== undefined) {
      const round = await refreshRound($, ctx.session)
      if (round === null || !isRoundOpen(round)) return text
      pending = { pending: pendingStamp(round, skill, modelArgs) }
    }
    const line = await startScope($, ctx.session, { command: skill, ...pending })
    return line === '' ? text : `${text}\n\n${line}`
  } catch {
    return text
  }
}

/** Records a pass with its origin while a round is open; the pending id when it is the pending pass. */
export async function recordPass($: $, ctx: Context, origin: ConsolePassOrigin, command: string, args: string): Promise<void> {
  if (!ctx.isRoundRole || !PASS_COMMANDS.includes(command)) return
  const round = await refreshRound($, ctx.session)
  if (round === null || !isRoundOpen(round)) return
  const pendingId = pendingStamp(round, command, args)
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
  notePersonRun(command)
  void $.command.run({ command, args }).catch(error => {
    takePersonRun(command)
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
