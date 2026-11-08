// The console mod (console-spec 3): a thin adapter between Claude Code and the protocol engine
// and board. It fails open (the CLI works without it) except for recovery, and idles without a
// registered role or a drawing surface. Round features act for lead, solo and autopilot.
import type { EngineInterface, Register } from 'claude-code'

import type { ConsoleStart } from '../types'

import {
  afterTurn, context, continueLater, continueTyped, CONTINUE_COMMAND, dropIfStale, failOpen, message, notice, PANE, placeholderMarker, pressRun, pressSubmit, recordPass, refreshAll, refreshBoard, refreshLater,
  refreshRole, refreshRound, releaseRun, rerunStoppedPass, resetSession, deliverDialogOutcome, stampReleaseRun, withContext,
  midTurnBuiltin, modelStartedPass, notePersonRun, showQuestions, staleDelivery, startedPass, withStartScope,
} from './core'
import { answer, boardShow, decline, isRoundOpen, pass, pending as readPending, protocol, RELEASE_COMMAND, say, statusLine, toolArgv } from './engine'
import { capture, judgeDialog } from './gate'
import type { DialogInput } from './gate'
import { drawBand, drawPane, PANE_MIN_COLUMNS, suggestions } from './pane'
import { addGate, deferCommand, getBoard, getGate, getPass, getPrinted, getRole, getRound, getStart, releaseRefresh, setAskSent, setPaneDismissed, setPrinted, setRound, setStart, setTurnRunning, takeDeferred } from './state'
import {
  compactedNote, consoleText, DECLINED_TEXT, declinedNote, keepRoundText, NO_QUESTION_TEXT, keepStartText, protocolCallText, protocolResultText, STALE_PASS_TEXT, startAbandonedText, toolFailedText, TOOL_IDLE_TEXT, unsavedNote,
} from './words'

const PROTOCOL_TOOL = 'mcp__console__protocol'

const REFRESH_MS = 60_000

/**
 * Skill calls in flight, by skill name: a subagent's, and the main agent's own (r8-q26). `skill.prompt` carries no agent id and fires
 * inside the call's `next(e)`, so these expansions are told apart from a queued command's here.
 */
const subagentSkills = new Map<string, number>()
const modelSkills = new Map<string, number>()
/** The arguments of the main agent's Skill call in flight, by skill name: its expansion names the pass's scope by them (r9-q36). */
const modelArgs = new Map<string, string>()
const bareSkill = (skill: string): string => skill.slice(skill.lastIndexOf(':') + 1)

async function counted<T>(calls: Map<string, number>, name: string, run: () => Promise<T>): Promise<T> {
  calls.set(name, (calls.get(name) ?? 0) + 1)
  try {
    return await run()
  } finally {
    const left = (calls.get(name) ?? 1) - 1
    if (left > 0) calls.set(name, left)
    else calls.delete(name)
  }
}

/** A compaction that ran leaves a small context. Set, not read: `$.session.usage()` still gives the old size inside this hook (probed, r21). */
async function settleContext<T extends { skip?: string }>($: EngineInterface, compacted: T, trigger: string): Promise<T> {
  const round = await getRound($)
  if (compacted.skip === undefined && trigger !== 'precompute' && round !== null) await setRound($, { ...round, isContextLarge: false })
  return compacted
}

/** The stored start goes with the compaction that was to precede it: run once that succeeded, dropped with a notice when it was skipped (a precompute installs nothing and keeps it). */
async function settleStart($: EngineInterface, start: ConsoleStart, compacted: { skip?: string }, trigger: string): Promise<void> {
  if (trigger === 'precompute') return
  if (compacted.skip !== undefined) return abandonStart($, start, `compaction skipped: ${compacted.skip}`)
  await setStart($, null)
  $.clock.after(0, () => pressRun($, start.command, start.args).catch(failOpen($, 'starting the next round')))
}

async function abandonStart($: EngineInterface, start: ConsoleStart, why: string): Promise<void> {
  await setStart($, null)
  $.clock.after(0, () => notice($, startAbandonedText(why, start)).catch(() => undefined))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    resetSession()
    // $.state outlives a reload, the previous environment's refresh does not: its single-flight claim goes.
    await releaseRefresh($)
    await $.command.register({ name: 'console', description: 'Open the console pane (prints the board and round where no pane fits)' })
    await $.command.register({ name: 'console-questions', description: "Print the issued batch's question text", argumentHint: '[batch marker]' })
    await $.command.register({ name: 'console-continue', description: 'Continue a stalled round: run its pending pass, reopen its dialog or wake the model at its step' })
    await $.command.register({ name: 'console-item', description: "Print a board item's summary", argumentHint: '<id>' })
    await refreshRole($).catch(failOpen($, 'reading the session role'))
    $.clock.every(REFRESH_MS, () => refreshAll($).catch(failOpen($, 'refresh')))
    refreshLater($)
    return next(e)
  })

  on('session.attach', async ($, e, next) => {
    const attached = await next(e)
    refreshLater($)
    return attached
  })

  // The model's tool: the console stamps session and origin (R-B11).
  on('tool.call', { tool: PROTOCOL_TOOL }, async ($, e) => {
    const ctx = await context($)
    if (!ctx.isRoundRole) return { result: TOOL_IDLE_TEXT }
    // The input comes from a model: the declared types are not checked at runtime.
    const args = Array.isArray(e.args) ? e.args.filter((arg): arg is string => typeof arg === 'string') : []
    const allowed = toolArgv(args)
    if ('refusal' in allowed) return { result: `Refused: ${allowed.refusal}.` }
    const ran = await protocol($, ctx.session, allowed.argv, typeof e.stdin === 'string' ? e.stdin : undefined)
    await refreshRound($, ctx.session)
    refreshLater($)
    const output = [ran.stdout.trim(), ran.stderr.trim() === '' ? '' : `stderr:\n${ran.stderr.trim()}`].filter(part => part !== '').join('\n\n')
    return { result: ran.exitCode === 0 ? output : `protocol exited ${ran.exitCode}.\n\n${output}` }
  }).catch(($, e, next) => ({ result: toolFailedText(next.error.message) }))

  // Dialog gate and answer capture: only inside an open round.
  on('tool.call', { tool: 'AskUserQuestion' }, async ($, e, next) => {
    const placeholder = placeholderMarker((e as unknown as { questions?: { question?: unknown }[] }).questions?.[0]?.question)
    const ctx = await context($)
    if (!ctx.isRoundRole && placeholder === null) return next(e)
    const round = await refreshRound($, ctx.session)
    if (placeholder !== null && (round === null || !isRoundOpen(round) || round.batch?.marker !== placeholder)) return { deny: `no batch ${placeholder} is out` }
    if (round === null || !isRoundOpen(round)) return next(e)
    // The console's own dialog: the placeholder becomes the issued batch, and the rest of this hook treats it as that batch's dialog.
    const asked = placeholder !== null && round.batch !== null ? { ...e, questions: round.batch.questions, metadata: { source: placeholder } } as typeof e : e
    const verdict = judgeDialog(round, asked as unknown as DialogInput, await getGate($), await getPrinted($))
    if (verdict.action === 'block') {
      await addGate($, verdict.key)
      await notice($, `blocked a dialog once: ${verdict.reason}`)
      return { deny: verdict.reason }
    }
    const ran = await next(asked)
    if (verdict.action === 'note') {
      if (ran.deny !== undefined) return ran
      await notice($, verdict.text)
      return withContext(ran, verdict.text)
    }
    const captured = capture(verdict.marker, ran)
    if (captured.kind === 'none') return ran
    if (await dropIfStale($, { kind: 'batch', marker: verdict.marker })) {  // the batch moved on while the dialog was open: nothing to record or announce
      if (placeholder !== null) deliverDialogOutcome($, verdict.marker, ctx.session, { summary: '', note: null, isDropped: true })
      return ran
    }
    const declined = DECLINED_TEXT
    try {
      const recorded = captured.kind === 'answer'
        ? await answer($, ctx.session, captured.input)
        : await decline($, ctx.session, { marker: verdict.marker, partial: captured.partial })
      await setRound($, recorded)
      // The engine knows what became of each question, so it writes the line the person reads (r36-q197).
      if (placeholder !== null) deliverDialogOutcome($, verdict.marker, ctx.session, { summary: recorded.echo ?? declined, note: recorded.note })
      if (recorded.note === null) return ran
      await notice($, recorded.note.split('\n')[0] ?? '')  // the headline; the model reads the whole note
      return withContext(ran, recorded.note)
    } catch (error) {
      if (captured.kind === 'decline') {
        // Esc aborts this hook's runs and no retry here gets through; the console's own dialog records it once closed (openDialog).
        if (placeholder !== null) deliverDialogOutcome($, verdict.marker, ctx.session, { summary: declined, note: null, unsavedDecline: { marker: verdict.marker, partial: captured.partial } })
        return withContext(ran, declinedNote(verdict.marker))
      }
      const text = unsavedNote(verdict.marker, message(error))
      await setAskSent($, null).catch(() => undefined)
      await notice($, text)
      if (placeholder !== null) deliverDialogOutcome($, verdict.marker, ctx.session, { summary: text, note: text })
      return withContext(ran, text)
    }
    // Never draw the placeholder: a failure here falls back to the model opening the dialog.
  }).catch(($, e, next) => placeholderMarker((e as unknown as { questions?: { question?: unknown }[] }).questions?.[0]?.question) !== null ? { deny: 'the console could not open its dialog' } : next(e))

  // Pass observation: the main agent's Skill call counts once it ran. A subagent's is its own work, not the round's pass.
  on('tool.call', { tool: 'Skill' }, async ($, e, next) => {
    const skill = e as unknown as { skill?: unknown; args?: unknown }
    const name = typeof skill.skill === 'string' ? bareSkill(skill.skill) : ''
    if (e.agentId !== undefined) return counted(subagentSkills, name, () => next(e))
    modelArgs.set(name, typeof skill.args === 'string' ? skill.args : '')
    const ran = await counted(modelSkills, name, () => next(e)).finally(() => { if (!modelSkills.has(name)) modelArgs.delete(name) })
    if (ran.deny === undefined && ran.isError !== true && typeof skill.skill === 'string') {
      await recordPass($, await context($), 'model', skill.skill, typeof skill.args === 'string' ? skill.args : '')
    }
    return ran
  }).catch(($, e, next) => next(e))

  // Typed commands count as the person's passes. The console's own run only counts once its skill expands (`skill.prompt`):
  // this hook fires when the run is queued, and a turn ending before it begins must not ask for its report.
  on('command.run', async ($, e, next) => {
    const origin = e.origin
    if ((origin.kind === 'composer' || origin.kind === 'bridge') && e.command === RELEASE_COMMAND) {
      await stampReleaseRun($, await context($), origin.kind, e.args)
    } else if (origin.kind === 'composer' || origin.kind === 'bridge') {
      notePersonRun(e.command)
      await recordPass($, await context($), origin.kind, e.command, e.args)
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  // A run has started as its skill expands: a press's guard entry goes, and the machine's pass is started. The model's own Skill call
  // runs as called; a queued run the round has left becomes a no-op (r3-q9), the console's own even after the model ran its pass (r8-q26).
  on('skill.prompt', async ($, e, next) => {
    const skill = bareSkill(e.skill)
    if (subagentSkills.has(skill)) return next(e)  // a subagent's call expands here: not the round's pass
    // A pass that starts names what its report must cover, as the engine works it out now (r9-q36); a stale run gets none.
    if (modelSkills.has(skill)) {
      await modelStartedPass($, skill)
      return next({ ...e, text: await withStartScope($, e.text, skill, modelArgs.get(skill) ?? '') })
    }
    await releaseRun($, key => key === skill || key.startsWith(`${skill} `))
    if (await startedPass($, skill)) return next({ ...e, text: STALE_PASS_TEXT })
    return next({ ...e, text: await withStartScope($, e.text, skill) })
  }).catch(($, e, next) => next(e))

  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined) await setTurnRunning($, true)
    if (e.agentId === undefined && e.text !== '') await releaseRun($, key => key === `prompt:${e.text}`)
    return next(e)
  }).catch(($, e, next) => next(e))

  // Chat-typed messages of the person reach the engine's quote check (R-B9).
  on('prompt.submit', async ($, e, next) => {
    const origin = e.origin.kind
    if (e.origin.kind === 'plugin' && e.origin.name === 'console') {
      const stale = e.command === undefined ? await staleDelivery($, e.text).catch(() => null) : null
      if (stale !== null) return { drop: stale }
    }
    const isPerson = (origin === 'composer' || origin === 'bridge') && e.isMeta !== true
    if (isPerson && e.turnId !== undefined && e.command === undefined) {
      // Sent during a turn: a built-in command runs when the turn ends, ahead of anything the console starts (user, 2026-11-06); anything
      // else reaches the model in this turn.
      if (new RegExp(`^/${CONTINUE_COMMAND}(\\s|$)`).test(e.text.trim())) {  // the console's own command: the model cannot run it either
        await continueLater($)
        return { drop: `/${CONTINUE_COMMAND} runs when this turn ends` }
      }
      const builtin = await midTurnBuiltin($, e.text).catch(() => null)
      if (builtin !== null) {
        await deferCommand($, builtin)
        await notice($, `/${builtin.command} runs when this turn ends.`)
        return { drop: `/${builtin.command} runs when this turn ends` }
      }
    }
    if (isPerson) {
      await setStart($, null)  // the person's own prompt: a stored start is moot
      await setAskSent($, null)  // and the dialog message may go again for the batch still out
    }
    if (isPerson && e.command === undefined) {
      const ctx = await context($)
      const round = await getRound($)
      if (ctx.isRoundRole && round !== null && isRoundOpen(round)) {
        await say($, ctx.session, origin, e.text).catch(failOpen($, 'relaying your message to the round'))
      }
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  // Machine-run passes: the engine marks the next pass pending; the turn's end runs it bare.
  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    if (e.agentId !== undefined) return done
    await setTurnRunning($, false)
    for (const command of await takeDeferred($)) void $.command.run(command).catch(failOpen($, `running /${command.command}`))
    const ctx = await refreshRole($)
    if (!ctx.isRoundRole) {
      refreshLater($)
      return done
    }
    try {
      await afterTurn($, ctx.session, e.isAborted)
    } catch (error) {
      $.ui.toast(`console: reading the pending pass failed: ${message(error)}`)
    }
    refreshLater($)
    return done
  })

  // Recovery: the summary keeps the round, and the engine's status line follows it. Not fail-open:
  // a failure shows as a notice and is a defect to fix.
  on('session.compact', async ($, e, next) => {
    await releaseRun($, key => key === 'compact' || key.startsWith('compact '))
    const ctx = await context($)
    if (!ctx.isRoundRole || e.agentId !== undefined) return next(e)
    const round = await refreshRound($, ctx.session)
    const isOpen = round !== null && isRoundOpen(round)
    // No round is open: a stored start (a suggestion that compacts first) is kept through the compaction and sent after it.
    const start = isOpen ? null : await getStart($)
    if (!isOpen && start === null) return settleContext($, await next(e), e.trigger)
    const keep = isOpen
      ? keepRoundText(round.round, round.step)
      : keepStartText(start?.title)
    const compacted = await next({ ...e, instructions: [e.instructions, keep].filter(Boolean).join('\n\n') })
    await settleContext($, compacted, e.trigger)
    if (start !== null) await settleStart($, start, compacted, e.trigger)
    if (compacted.skip !== undefined || e.trigger === 'precompute' || !isOpen) return compacted
    $.clock.after(0, () => rerunStoppedPass($, ctx.session).catch(failOpen($, 'rerunning the stopped pass')))
    try {
      const line = await statusLine($, ctx.session)
      $.clock.after(0, () => notice($, `after compaction: ${line}`).catch(() => undefined))
      return { ...compacted, messages: [...compacted.messages, { role: 'user' as const, text: compactedNote(line), toolUses: [] }] }
    } catch (error) {
      $.clock.after(0, () => notice($, `after compaction the round line failed: ${message(error)}; run protocol status --line`).catch(() => undefined))
      return compacted
    }
  }).catch(async ($, e, next) => {
    // Recovery is not fail-open: say so where the person sees it, and compact without the round's instructions.
    $.clock.after(0, () => notice($, 'the round could not be kept through this compaction; run protocol status --line').catch(() => undefined))
    const start = await getStart($).catch(() => null)
    if (start === null || e.trigger === 'precompute') return next(e)
    try {
      const compacted = await next(e)
      await settleStart($, start, compacted, e.trigger)
      return compacted
    } catch (error) {
      await abandonStart($, start, `compaction failed: ${message(error)}`)
      throw error
    }
  })

  on('command.run', { command: 'console' }, async ($, e) => {
    const ctx = await refreshRole($)
    const role = await getRole($)
    if (role === null) return { text: 'The console waits for a registered role (/role).' }
    if (e.origin.kind === 'composer' && e.presentation.columns >= PANE_MIN_COLUMNS) {
      await setPaneDismissed($, false)
      const opened = await $.ui.open({ id: PANE, title: 'Console' })
      refreshLater($)
      return { text: opened.isPlaced ? 'Console opened.' : `Console waits: ${opened.reason}` }
    }
    if (ctx.isRoundRole) await refreshRound($, ctx.session)
    const board = ctx.isActive ? await refreshBoard($, ctx) : await getBoard($)
    const round = await getRound($)
    return { text: consoleText(role, board, round, ctx.isRoundRole, role.role === 'autopilot' ? [] : suggestions(round)) }
  })

  on('command.run', { command: 'console-item' }, async ($, e) => {
    const id = e.args.trim().split(/\s+/)[0] ?? ''
    if (id === '') return { text: 'Usage: /console-item <id>' }
    return { text: await boardShow($, await $.session.id(), id) }
  })

  // The batch's question text as command output: it draws whole between turns, and the model reads this one copy.
  on('command.run', { command: 'console-questions' }, async ($, e) => {
    const round = await getRound($)
    const batch = round !== null && isRoundOpen(round) ? round.batch : null
    const wanted = e.args.trim()
    const isOurs = e.origin.kind === 'plugin' && e.origin.name === 'console'
    if (batch === null || (wanted !== '' && wanted !== batch.marker)) return { text: NO_QUESTION_TEXT }
    if (isOurs) await showQuestions($, batch.marker, await $.session.id())
    if (batch.notice.trim() === '') return { text: NO_QUESTION_TEXT }
    return { text: `\n${batch.notice}` }  // the host prefixes the output with the plugin's name: the first question starts its own line
  })

  // The turn-end decision on the person's request (r7-q24); a reopened batch's text is its output.
  on('command.run', { command: 'console-continue' }, async $ => ({ text: await continueTyped($) }))

  on('ui.render', { component: 'Pane', requestId: PANE }, ($, e) => drawPane($, e))

  // A pane the person closed stays closed across reloads and /clear until /console opens it.
  on('ui.close', async ($, e, next) => {
    if (e.id === PANE && e.origin.kind === 'person') await setPaneDismissed($, true)
    return next(e)
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => (await drawBand($, e)) ?? next(e))

  // The protocol tool's rows stay one line each; ctrl+o (expanded) shows the full call and result.
  on('ui.render', { component: 'ToolUse' }, ($, e, next) => {
    if (e.props.tool !== PROTOCOL_TOOL || e.props.isExpanded === true) return next(e)
    const { Box, Text } = $.ui.resolve(e) as any
    return (
      <Box flexDirection="row">
        <Text bold>protocol </Text>
        <Text color="inactive" wrap="truncate-end">{protocolCallText(e.props.input)}</Text>
      </Box>
    )
  })
  on('ui.render', { component: 'ToolResult' }, ($, e, next) => {
    if (e.props.tool !== PROTOCOL_TOOL || e.props.isExpanded === true) return next(e)
    const { Text } = $.ui.resolve(e) as any
    return <Text color={e.props.isErrored ? 'error' : 'inactive'} wrap="truncate-end">  ⎿ {protocolResultText(e.props.output)}</Text>
  })
}
