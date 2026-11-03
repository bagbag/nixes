// The console mod (console-spec 3): a thin adapter between Claude Code and the protocol engine
// and board. It fails open (the CLI works without it) except for recovery, and idles without a
// registered role or a drawing surface. Round features act for lead and solo only.
import type { EngineInterface, Register } from 'claude-code'

import type { ConsolePassRun, ConsoleStart } from '../types'

import {
  context, failOpen, message, notice, noteModel, PANE, pressSubmit, recordPass, refreshAll, refreshBoard, refreshLater,
  refreshRole, refreshRound, releaseRun, resetSession, stampReleaseRun, withContext,
} from './core'
import { answer, boardShow, decline, isRoundOpen, pass, pending as readPending, protocol, RELEASE_COMMAND, say, statusLine, toolArgv } from './engine'
import { capture, judgeDialog } from './gate'
import type { DialogInput } from './gate'
import { drawBand, drawPane, PANE_MIN_COLUMNS } from './pane'
import { addGate, getBoard, getGate, getPass, getRole, getRound, getStart, releaseRefresh, setPaneDismissed, setPass, setRound, setStart } from './state'
import { consoleText, protocolCallText, protocolResultText } from './words'

const PROTOCOL_TOOL = 'mcp__console__protocol'

const REFRESH_MS = 60_000

/** The engine's reminder for the console's own run of its pending pass; null when the pass is no longer pending or gets the full text. */
async function ownReminder($: EngineInterface, run: ConsolePassRun): Promise<string | null> {
  const pending = await readPending($, await $.session.id())
  return pending !== null && pending.id === run.id && pending.command === run.command ? pending.reminder : null
}

/** A compaction that ran leaves a small context. Set, not read: `$.session.usage()` still gives the old size inside this hook (probed, r21). */
async function settleContext<T extends { skip?: string }>($: EngineInterface, compacted: T, trigger: string): Promise<T> {
  const round = await getRound($)
  if (compacted.skip === undefined && trigger !== 'precompute' && round !== null) await setRound($, { ...round, isContextLarge: false })
  return compacted
}

/** The stored start goes with the compaction that was to precede it: sent once that succeeded, dropped with a notice when it was skipped (a precompute installs nothing and keeps it). */
async function settleStart($: EngineInterface, start: ConsoleStart, compacted: { skip?: string }, trigger: string): Promise<void> {
  if (trigger === 'precompute') return
  if (compacted.skip !== undefined) return abandonStart($, start, `compaction skipped: ${compacted.skip}`)
  await setStart($, null)
  $.clock.after(0, () => pressSubmit($, start.text).catch(failOpen($, 'sending the next round')))
}

async function abandonStart($: EngineInterface, start: ConsoleStart, why: string): Promise<void> {
  await setStart($, null)
  $.clock.after(0, () => notice($, `the next round was not started (${why}): ${start.text}`).catch(() => undefined))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    resetSession()
    // $.state outlives a reload, the previous environment's refresh does not: its single-flight claim goes.
    await releaseRefresh($)
    await $.command.register({ name: 'console', description: 'Open the console pane (prints the board and round where no pane fits)' })
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
  on('tool.call', { tool: 'mcp__console__protocol' }, async ($, e) => {
    const ctx = await context($)
    if (!ctx.isRoundRole) return { result: 'The console is idle in this session (no lead or solo role, or nothing draws); run `protocol` through Bash.' }
    const input = e as unknown as { args?: unknown; stdin?: unknown }
    const args = Array.isArray(input.args) ? input.args.filter((arg): arg is string => typeof arg === 'string') : []
    const allowed = toolArgv(args)
    if ('refusal' in allowed) return { result: `Refused: ${allowed.refusal}.` }
    const ran = await protocol($, ctx.session, allowed.argv, typeof input.stdin === 'string' ? input.stdin : undefined)
    await refreshRound($, ctx.session)
    refreshLater($)
    const output = [ran.stdout.trim(), ran.stderr.trim() === '' ? '' : `stderr:\n${ran.stderr.trim()}`].filter(part => part !== '').join('\n\n')
    return { result: ran.exitCode === 0 ? output : `protocol exited ${ran.exitCode}.\n\n${output}` }
  }).catch(() => ({ result: 'The console failed to run protocol (see the debug log); run `protocol` through Bash.' }))

  // Dialog gate and answer capture: only inside an open round.
  on('tool.call', { tool: 'AskUserQuestion' }, async ($, e, next) => {
    const ctx = await context($)
    if (!ctx.isRoundRole) return next(e)
    const round = await refreshRound($, ctx.session)
    if (round === null || !isRoundOpen(round)) return next(e)
    const verdict = judgeDialog(round, e as unknown as DialogInput, await getGate($))
    if (verdict.action === 'block') {
      await addGate($, verdict.key)
      await notice($, `blocked a dialog once: ${verdict.reason}`)
      return { deny: verdict.reason }
    }
    const ran = await next(e)
    if (verdict.action === 'note') {
      if (ran.deny !== undefined) return ran
      await notice($, verdict.text)
      return withContext(ran, verdict.text)
    }
    const captured = capture(verdict.marker, ran)
    if (captured.kind === 'none') return ran
    try {
      const recorded = captured.kind === 'answer'
        ? await answer($, ctx.session, captured.input)
        : await decline($, ctx.session, { marker: verdict.marker, partial: captured.partial })
      await setRound($, recorded)
      if (recorded.note === null) return ran
      await notice($, recorded.note.split('\n')[0] ?? '')  // the headline; the model reads the whole note
      return withContext(ran, recorded.note)
    } catch (error) {
      const text = `the answers of ${verdict.marker} were not recorded: ${message(error)}. Record them with the protocol tool before going on.`
      await notice($, text)
      return withContext(ran, text)
    }
  }).catch(($, e, next) => next(e))

  // Pass observation: the model's Skill call counts once it ran.
  on('tool.call', { tool: 'Skill' }, async ($, e, next) => {
    const ran = await next(e)
    const skill = e as unknown as { skill?: unknown; args?: unknown }
    if (ran.deny === undefined && ran.isError !== true && typeof skill.skill === 'string') {
      await recordPass($, await context($), 'model', skill.skill, typeof skill.args === 'string' ? skill.args : '')
    }
    return ran
  }).catch(($, e, next) => next(e))

  // Typed commands count as the person's passes; the console's own machine run is marked started.
  on('command.run', async ($, e, next) => {
    const origin = e.origin
    if (origin.kind === 'plugin' && origin.name === 'console') {
      const run = await getPass($)
      if (run !== null && run.phase === 'queued' && run.command === e.command) await setPass($, { ...run, phase: 'started' })
    } else if ((origin.kind === 'composer' || origin.kind === 'bridge') && e.command === RELEASE_COMMAND) {
      await stampReleaseRun($, await context($), origin.kind, e.args)
    } else if (origin.kind === 'composer' || origin.kind === 'bridge') {
      await recordPass($, await context($), origin.kind, e.command, e.args)
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  // A run has started as its skill expands: a press's guard entry goes, and the machine's pass is started. The console's own pass
  // reads the engine's reminder in place of the skill's full text when the cycle told that kind already (r17-q62); a typed
  // command and the model's own Skill call keep the full text, and a failing read passes it through.
  on('skill.prompt', async ($, e, next) => {
    const skill = e.skill.slice(e.skill.lastIndexOf(':') + 1)
    await releaseRun($, key => key === skill || key.startsWith(`${skill} `))
    const run = await getPass($)
    if (run !== null && run.phase === 'queued' && run.command === skill) await setPass($, { ...run, phase: 'started' })
    const isOwnRun = run !== null && run.isOwn === true && run.phase !== 'noted' && run.command === skill
    if (isOwnRun) await setPass($, { id: run.id, command: run.command, phase: 'started' })  // its one expansion: a later Skill call in the run is the model's own
    const reminder = isOwnRun ? await ownReminder($, run).catch(() => null) : null
    const expanded = await next(e)
    return reminder === null ? expanded : { ...expanded, text: reminder }
  }).catch(($, e, next) => next(e))

  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined && e.text !== '') await releaseRun($, key => key === `prompt:${e.text}`)
    return next(e)
  }).catch(($, e, next) => next(e))

  // Chat-typed messages of the person reach the engine's quote check (R-B9).
  on('prompt.submit', async ($, e, next) => {
    const origin = e.origin.kind
    if ((origin === 'composer' || origin === 'bridge') && e.isMeta !== true) await setStart($, null)  // the person's own prompt: a stored start is moot
    if ((origin === 'composer' || origin === 'bridge') && e.isMeta !== true && e.command === undefined) {
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
    const ctx = await refreshRole($)
    if (!ctx.isRoundRole) {
      refreshLater($)
      return done
    }
    try {
      const pending = await readPending($, ctx.session)
      const run = await getPass($)
      if (pending !== null && run !== null && run.id === pending.id) {
        if (run.phase !== 'noted' && e.isAborted) {
          // Esc stops the loop: the pass stays pending and is not run again.
          await setPass($, { ...run, phase: 'noted' })
        } else if (run.phase === 'started') {
          await setPass($, { ...run, phase: 'noted' })
          await noteModel($, `The /${pending.command} pass (${pending.id}) ended without its report. Report its per-question updates through the protocol tool.`)
        }
      } else if (pending !== null && !e.isAborted) {
        await setPass($, { id: pending.id, command: pending.command, phase: 'queued', isOwn: true })
        await pass($, ctx.session, 'plugin', { command: pending.command, args: pending.args, pending: pending.id })
          .catch(failOpen($, `recording /${pending.command}`))
        void $.command.run({ command: pending.command, args: pending.args }).catch(failOpen($, `running /${pending.command}`))
      }
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
    const proposed = round?.next?.compact?.keep
    const keep = isOpen
      ? `Keep the protocol round state: round ${round.round}, step ${round.step}, each question's id, status and open overlap, the pending pass, and that the round runs through the protocol tool (mcp__console__protocol).`
      : [`Keep the proposed next round, which starts right after this compaction: ${start?.text}.`,
        proposed === undefined || e.instructions?.includes(proposed) === true ? '' : `Keep: ${proposed}`].filter(Boolean).join(' ')
    const compacted = await next({ ...e, instructions: [e.instructions, keep].filter(Boolean).join('\n\n') })
    await settleContext($, compacted, e.trigger)
    if (start !== null) await settleStart($, start, compacted, e.trigger)
    if (compacted.skip !== undefined || e.trigger === 'precompute' || !isOpen) return compacted
    try {
      const line = await statusLine($, ctx.session)
      $.clock.after(0, () => notice($, `after compaction: ${line}`).catch(() => undefined))
      return { ...compacted, messages: [...compacted.messages, { role: 'user' as const, text: `<console-note>Protocol state after compaction: ${line}</console-note>`, toolUses: [] }] }
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
    return { text: consoleText(role, board, await getRound($), ctx.isRoundRole) }
  })

  on('command.run', { command: 'console-item' }, async ($, e) => {
    const id = e.args.trim().split(/\s+/)[0] ?? ''
    if (id === '') return { text: 'Usage: /console-item <id>' }
    return { text: await boardShow($, await $.session.id(), id) }
  })

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
