// The console pane and the band above the prompt (console-spec 3 Pane, Band). Look: the probe
// mod round-probe as approved: Board block over Round block, brackets = action, plain labels with
// ` • ` = toggle or link, secondary text `inactive`, hover hints gathered at the bottom.
import type { EngineInterface, RenderPropsOf } from 'claude-code'

import type { ConsoleBoard, ConsoleQuestion, ConsoleRecord, ConsoleRole, ConsoleRound, ConsoleSection, ConsoleSession } from '../types'

import { pressOpenItem, pressOpenOverlaps, pressRun, pressSubmit, pressView } from './core'
import { isRoundOpen, RELEASE_COMMAND, ROUND_ROLES } from './engine'
import { getBoard, getExpanded, getLenses, getOpened, getPass, getRole, getRound, getRoundError, toggleExpanded, updateLenses } from './state'
import { answerText, COUNT_LABELS, GROUND, GROUND_BASE, lensArgs, LENS_SETS, pullsText, recommendationMark, recommendationText, roundWords, runNoun, staleHolds, staleSessions, STEP_BACK_BASE, WHAT, WHERE } from './words'
import type { Lens, LensCommand } from './words'

type $ = EngineInterface

export const DOUBLE_PRESS_MS = 450
const HELD_COLLAPSE_FROM = 3
const QUESTIONS_SHOWN = 10  // every asked question and the 2 latest answered always show; upcoming ones fill the rest
const ANSWERED_SHOWN = 2
const BOARD_ROWS_SHOWN = 6
const SESSION_ORDER: Record<string, number> = { active: 0, idle: 1, gone: 3 }
const LIVE_AGENT: readonly string[] = ['pending', 'running', 'waiting', 'idle']
const LABEL = 11
const SESSION_COLUMNS = { role: 7, tool: 8, actor: 10, pulls: 9, holds: 9, workers: 13, state: 9 } as const

/** No run is open and the engine names a release next: the last round's recorded records wait for it. */
const isReleaseNext = (round: ConsoleRound): round is ConsoleRound & { next: NonNullable<ConsoleRound['next']> } =>
  !isRoundOpen(round) && round.next !== null

/** The narrowest body the layout's fixed columns fit: below it /console prints instead of opening. */
export const PANE_MIN_COLUMNS = Object.values(SESSION_COLUMNS).reduce((sum, width) => sum + width, 0) + 2

const QUESTION_COLOR: Record<ConsoleQuestion['status'], string> = { answered: 'success', asked: 'suggestion', ready: 'claude', draft: 'subtle', held: 'warning' }
const ITEM_COLOR: Record<string, string> = { open: 'claude', in_progress: 'suggestion', in_review: 'warning', decided: 'success', released: 'success', blocked: 'error' }
const SESSION_COLOR: Record<string, string> = { active: 'success', idle: 'warning', stopped: 'error', gone: 'inactive' }
const RECORD_COLOR: Record<ConsoleRecord['state'], string> = { set: 'claude', dropped: 'warning', changed: 'error', released: 'success' }

// A lens press within DOUBLE_PRESS_MS of the same lens runs it alone; a reload forgetting it is harmless.
let lastLensPress: { key: string; at: number } | undefined

type Hints = { add: (scope: string, text: string) => void; list: { scope: string; text: string }[] }

const hints = (): Hints => {
  const list: { scope: string; text: string }[] = []
  return { list, add: (scope, text) => { if (!list.some(one => one.scope === scope)) list.push({ scope, text }) } }
}

export async function drawPane($: $, e: { surface: string; props: RenderPropsOf['Pane'] } & Parameters<$['ui']['resolve']>[0]) {
  const { Box, Text, Button, Input } = $.ui.resolve(e) as any
  const role = await getRole($)
  const board = await getBoard($)
  const round = await getRound($)
  const lenses = await getLenses($)
  const expanded = await getExpanded($)
  const opened = await getOpened($)
  const roundError = await getRoundError($)
  const passRun = await getPass($)
  const hint = hints()
  const isRoundRole = role !== null && ROUND_ROLES.includes(role.role)

  const banner = (key: string, title: string, meta: string, top: number) => (
    <Box key={key} flexDirection="row" columnGap={1} marginTop={top} alignItems="flex-start">
      <Box flexShrink={0}><Text bold inverse> {title} </Text></Box>
      <Box flexShrink={1}><Text color="inactive">{meta}</Text></Box>
    </Box>
  )
  const labelled = (key: string, label: any, body: any, top = 0) => (
    <Box key={key} flexDirection="row" marginTop={top}>
      <Box width={LABEL} flexShrink={0}>{label}</Box>
      <Box flexDirection="column" flexGrow={1}>{body}</Box>
    </Box>
  )
  const rightLabel = (word: string) => <Box width={LABEL - 2} justifyContent="flex-end"><Text color="inactive">{word}</Text></Box>
  const divided = (key: string, entries: { key: string; scope?: string; label: any; onPress: () => Promise<void> }[]) => (
    <Box key={key} flexDirection="row" flexWrap="wrap">
      {entries.map((one, i) => (
        <Box key={`${key}-${one.key}-box`} flexDirection="row" hover={one.scope === undefined ? undefined : { scope: one.scope }}>
          {i > 0 && <Text color="inactive"> • </Text>}
          <Button key={`${key}-${one.key}`} plain onPress={one.onPress}>{one.label}</Button>
        </Box>
      ))}
    </Box>
  )
  // What the person opened inline below a row (one at a time): an item's first lines, or a question's overlaps.
  const slot = (id: string, from: string | null = null) => {
    if (opened?.kind !== 'item' || opened.id !== id || opened.from !== from) return null
    const read = opened.phase === 'read' ? opened.slot : null
    if (read !== null && read.linked !== '') hint.add(`slot-${id}`, `${id}: ${read.linked}`)
    return (
      <Box key={`open-${from ?? ''}-${id}`} flexDirection="column" paddingLeft={2}>
        {opened.phase === 'reading' && <Text color="inactive">reading…</Text>}
        {opened.phase === 'failed' && <Text color="error" wrap="wrap">{opened.text}</Text>}
        {read !== null && read.lines.map((line, i) => <Text key={`open-${id}-${i}`} wrap="truncate-end">{line}</Text>)}
        {read !== null && (
          <Box key={`open-${id}-facts`} hover={read.linked === '' ? undefined : { scope: `slot-${id}` }}>
            <Text color="inactive" wrap="truncate-end">{read.facts}</Text>
          </Box>
        )}
      </Box>
    )
  }
  const overlapSlot = (question: string) => {
    if (opened?.kind === 'item' && opened.from === question) return slot(opened.id, question)
    if (opened?.kind !== 'overlaps' || opened.question !== question) return null
    return (
      <Box key={`open-ov-${question}`} flexDirection="column" paddingLeft={2}>
        <Text color="inactive">each needs an outcome before asking; click an id to open it</Text>
        {opened.overlaps.map(one => (
          <Box key={`ov-${question}-${one.id}`} flexDirection="row">
            <Box width={14} flexShrink={0}><Button key={`ov-${question}-${one.id}-open`} plain onPress={() => pressOpenItem($, one.id, question)}><Text bold>{one.id}</Text></Button></Box>
            <Box flexGrow={1} flexShrink={1}><Text wrap="truncate-end">{one.title}</Text></Box>
          </Box>
        ))}
      </Box>
    )
  }
  const run = (command: string, args = '') => () => pressRun($, command, args)
  const more = (section: ConsoleSection, hidden: number, what: string) => {
    const isOpen = expanded.includes(section)
    if (!isOpen && hidden === 0) return null
    hint.add(`${section}-toggle`, isOpen ? `Show fewer ${what}` : `Show all ${what}`)
    return (
      <Box key={`${section}-toggle-box`} hover={{ scope: `${section}-toggle` }}>
        <Button key={`${section}-toggle`} plain onPress={() => toggleExpanded($, section)}>
          <Text color="inactive">{isOpen ? 'show fewer ▾' : `+${hidden} more ▸`}</Text>
        </Button>
      </Box>
    )
  }
  const capped = <T,>(section: ConsoleSection, rows: readonly T[]): { shown: readonly T[]; hidden: number } =>
    expanded.includes(section) || rows.length <= BOARD_ROWS_SHOWN
      ? { shown: rows, hidden: 0 }
      : { shown: rows.slice(0, BOARD_ROWS_SHOWN), hidden: rows.length - BOARD_ROWS_SHOWN }

  // Board block

  const boardBlock = (who: ConsoleRole, view: ConsoleBoard | null) => {
    const rows: any[] = [banner('board-banner', 'Board', `${who.role} ${who.actor}`, 0)]
    if (view === null) {
      rows.push(<Box key="board-wait" marginTop={1}><Text color="inactive">reading the board…</Text></Box>)
      return rows
    }
    if (view.counts !== null) {
      const counts = view.counts
      rows.push(
        <Box key="board-counts" flexDirection="row" columnGap={2} flexWrap="wrap" marginTop={1}>
          {COUNT_LABELS.map(([key, label]) => key === 'forUser'
            ? <Text key={`count-${key}`} color="warning">{label} <Text bold>{counts[key]}</Text></Text>
            : <Text key={`count-${key}`} color="inactive">{label} <Text bold color="text">{counts[key]}</Text></Text>)}
        </Box>,
      )
    }
    if (view.items.length > 0) {
      const items = capped('items', view.items)
      rows.push(
        <Box key="board-items" flexDirection="column" marginTop={1}>
          {items.shown.map(item => {
            hint.add(`item-${item.id}`, `${item.id}: open its summary here (/console-item ${item.id} prints it in the chat)`)
            return (
              <Box key={`item-${item.id}`} flexDirection="column">
                <Box flexDirection="row">
                  <Box key={`item-${item.id}-idbox`} width={12} flexShrink={0} hover={{ scope: `item-${item.id}` }}>
                    <Button key={`item-${item.id}-show`} plain onPress={() => pressOpenItem($, item.id)}>{item.id}</Button>
                  </Box>
                  <Box width={13} flexShrink={0}><Text color={ITEM_COLOR[item.status] ?? 'inactive'}>{item.status}</Text></Box>
                  <Box flexGrow={1} flexShrink={1}><Text wrap="truncate-end">{item.title}</Text></Box>
                </Box>
                {slot(item.id)}
              </Box>
            )
          })}
          {more('items', items.hidden, 'items')}
        </Box>,
      )
    }
    if (view.sessions.length > 0) {
      const rank = (one: ConsoleSession) => SESSION_ORDER[one.state] ?? 2
      hint.add('stale-holds', 'Holds of sessions that are gone or unknown with only idle holds: board take <id> or board unclaim <id>')
      const stale = staleSessions(view)
      const holds = staleHolds(view, stale)
      const sessions = capped('sessions', view.sessions.filter(one => !stale.has(one.actor)).sort((a, b) => rank(a) - rank(b)))
      rows.push(
        <Box key="board-sessions" flexDirection="column" marginTop={1}>
          {sessions.shown.map(session => {
            if (session.pulls.length > 0) hint.add(`pulls-${session.session}`, `${session.actor} pulls: ${session.pulls.join(', ')}`)
            return (
            <Box key={`session-${session.session}`} flexDirection="row">
              <Box width={SESSION_COLUMNS.role} flexShrink={0}><Text>{session.role}</Text></Box>
              <Box width={SESSION_COLUMNS.tool} flexShrink={0}><Text color="inactive">{session.tool || '?'}</Text></Box>
              <Box width={SESSION_COLUMNS.actor} flexShrink={0}><Text color="inactive">{session.actor}</Text></Box>
              <Box width={SESSION_COLUMNS.pulls} flexShrink={0} hover={{ scope: `pulls-${session.session}` }}><Text color="inactive">{pullsText(session.pulls)}</Text></Box>
              <Box width={SESSION_COLUMNS.holds} flexShrink={0}><Text color="inactive">holds {session.holds}</Text></Box>
              <Box width={SESSION_COLUMNS.workers} flexShrink={0}>
                {/* Over the cap: a worker ended without its stop event (Codex after an error) and still counts for 15 min. */}
                <Text color={session.workers !== null && session.workers.active > session.workers.cap ? 'warning' : 'inactive'}>
                  {session.workers === null ? '' : `workers ${session.workers.active}/${session.workers.cap}`}
                </Text>
              </Box>
              <Text color={SESSION_COLOR[session.state] ?? 'inactive'}>{session.state || 'unknown'}</Text>
            </Box>
            )
          })}
          {more('sessions', sessions.hidden, 'sessions')}
          {holds.length > 0 && (
            <Box key="stale-holds" flexDirection="row" flexWrap="wrap">
              <Text color="warning">stale holds: </Text>
              {holds.map((one, i) => (
                <Box key={`stale-${one.id}-box`} flexDirection="row" hover={{ scope: 'stale-holds' }}>
                  {i > 0 && <Text color="inactive">, </Text>}
                  <Button key={`stale-${one.id}`} plain onPress={() => pressOpenItem($, one.id)}><Text color="warning">{one.id}</Text></Button>
                  <Text color="inactive"> ({one.actor})</Text>
                </Box>
              ))}
            </Box>
          )}
          {holds.map(one => slot(one.id))}
        </Box>,
      )
    }
    const viewed = e.props.view.agentId
    // Live workers only: Claude Code keeps finished ones listed for the whole session. The one in view stays.
    const workers = view.agents.filter(agent => LIVE_AGENT.includes(agent.status) || agent.id === viewed)
    if (workers.length > 0 || viewed !== undefined) {
      rows.push(
        <Box key="board-workers" flexDirection="column" marginTop={1}>
          {viewed !== undefined && (
            <Box key="worker-main-box" hover={{ scope: 'worker-main' }}>
              <Button key="worker-main" plain onPress={() => pressView($, undefined)}>◂ <Text color="inactive">main conversation</Text></Button>
            </Box>
          )}
          {workers.map(agent => {
            hint.add(`worker-${agent.id}`, `Show ${agent.description} in the main view`)
            return (
              <Box key={`worker-${agent.id}-box`} flexDirection="row" hover={{ scope: `worker-${agent.id}` }}>
                <Button key={`worker-${agent.id}`} plain onPress={() => pressView($, agent.id)}>
                  {agent.id === viewed ? '▸ ' : '  '}{agent.description} <Text color="inactive">{agent.type} · {agent.status}</Text>
                </Button>
              </Box>
            )
          })}
        </Box>,
      )
      hint.add('worker-main', 'Back to the main conversation')
    }
    if (view.error !== null) rows.push(<Box key="board-error" marginTop={1}><Text color="error" wrap="truncate-end">{view.error}</Text></Box>)
    return rows
  }

  // Round block

  const questionRow = (question: ConsoleQuestion) => {
    const overlaps = question.overlaps.filter(one => one.outcome === null)
    const focus = `${question.id} ${question.title}`
    const backing = recommendationText(question)
    const mark = recommendationMark(question)
    hint.add(`q-${question.id}-text`, `${question.id}: ${question.text}${backing === '' ? '' : ` — ${backing}`}`)
    hint.add(`q-${question.id}-explain`, `Runs /explain ${focus}`)
    hint.add(`q-${question.id}-sb`, `Runs /step-back ${focus}`)
    hint.add(`q-${question.id}-ov`, `Open the board items ${question.id} overlaps here; each needs an outcome before asking`)
    return (
      <Box key={`q-${question.id}`} flexDirection="column">
      <Box flexDirection="row">
        <Box width={10} flexShrink={0}><Text color={QUESTION_COLOR[question.status]}>{question.status}</Text></Box>
        <Box width={5} flexShrink={0}><Text bold>{question.id}</Text></Box>
        <Box flexGrow={1} flexShrink={1} flexDirection="row">
          {/* The title shrinks and truncates; the answer, marks and overlap link keep their width on the line. */}
          <Box key={`q-${question.id}-text-box`} flexShrink={1} hover={{ scope: `q-${question.id}-text` }}>
            <Text wrap="truncate-end">{question.title}{question.waitsOn.length > 0 ? <Text color="inactive"> (waits on {question.waitsOn.join(', ')})</Text> : ''}</Text>
          </Box>
          <Box key={`q-${question.id}-marks`} flexShrink={0} flexDirection="row">
            {question.status === 'answered' && question.answer !== null && <Text color="inactive"> → {answerText(question.answer)}</Text>}
            {question.status !== 'answered' && mark !== null && <Text color={mark.color}> {mark.text}</Text>}
            {question.changedBy !== null && <Text color="inactive"> ↻ {question.changedBy}</Text>}
            {overlaps.length > 0 && (
              <Box key={`q-${question.id}-ov-box`} flexDirection="row" hover={{ scope: `q-${question.id}-ov` }}>
                <Text color="warning"> · </Text>
                <Button key={`q-${question.id}-ov`} plain onPress={() => pressOpenOverlaps($, question.id, overlaps)}>
                  <Text color="warning">{overlaps.length === 1 ? '1 overlap' : `${overlaps.length} overlaps`}</Text>
                </Button>
              </Box>
            )}
          </Box>
        </Box>
        <Box key={`q-${question.id}-explain-box`} flexShrink={0} hover={{ scope: `q-${question.id}-explain` }}>
          <Button key={`q-${question.id}-explain`} plain onPress={run('explain', focus)}><Text color="inactive">explain</Text></Button>
        </Box>
        <Text color="inactive"> • </Text>
        <Box key={`q-${question.id}-sb-box`} flexShrink={0} hover={{ scope: `q-${question.id}-sb` }}>
          <Button key={`q-${question.id}-sb`} plain onPress={run('step-back', focus)}><Text color="inactive">step back</Text></Button>
        </Box>
      </Box>
      {overlapSlot(question.id)}
      </Box>
    )
  }

  // In reading order: answered, asked, then the upcoming ones in the engine's ask order (its list order).
  const questionRows = (open: ConsoleRound) => {
    const held = open.questions.filter(one => one.status === 'held')
    const answered = open.questions.filter(one => one.status === 'answered')
      .sort((a, b) => (a.answeredAt ?? '').localeCompare(b.answeredAt ?? ''))
    const asked = open.questions.filter(one => one.status === 'asked')
    const upcoming = [...open.questions.filter(one => one.status === 'ready'), ...open.questions.filter(one => one.status === 'draft')]
    const isAll = expanded.includes('questions')
    const latest = isAll ? answered : answered.slice(-ANSWERED_SHOWN)
    const next = isAll ? upcoming : upcoming.slice(0, Math.max(0, QUESTIONS_SHOWN - asked.length - latest.length))
    const hidden = answered.length + asked.length + upcoming.length - (latest.length + asked.length + next.length)
    const isHeldOpen = expanded.includes('held')
    const isCollapsed = held.length >= HELD_COLLAPSE_FROM && !isHeldOpen
    hint.add('held-toggle', isHeldOpen ? 'Collapse the held questions' : 'Show the held questions')
    return (
      <Box key="round-questions" flexDirection="column" marginTop={1}>
        {[...latest, ...asked, ...next].map(questionRow)}
        {more('questions', hidden, 'questions')}
        {!isCollapsed && held.map(questionRow)}
        {held.length >= HELD_COLLAPSE_FROM && (
          <Box key="held-toggle-box" hover={{ scope: 'held-toggle' }}>
            <Button key="held-toggle" plain onPress={() => toggleExpanded($, 'held')}>
              <Text color="warning">{held.length} held</Text><Text color="inactive"> {isCollapsed ? '▸' : '▾'}</Text>
            </Button>
          </Box>
        )}
      </Box>
    )
  }

  // The free focus belongs to Step Back (its Input sits in the where row); Ground leaves it alone.
  const runLenses = async (command: LensCommand) => {
    const now = await getLenses($)
    const hasFocus = command === 'step-back'
    const args = lensArgs(now[command], hasFocus ? now.focus : '')
    await updateLenses($, current => ({ ...current, [command]: [], ...(hasFocus ? { focus: '' } : {}) }))
    await pressRun($, command, args)
  }
  const runBase = async (command: LensCommand) => {
    if (command !== 'step-back') return pressRun($, command, '')
    const focus = (await getLenses($)).focus
    await updateLenses($, current => ({ ...current, focus: '' }))
    await pressRun($, command, focus.trim())
  }
  // A fixed lens set (Path, Refine, All), the focus included (Step Back); the toggled selection stays.
  const runSet = async (command: LensCommand, set: readonly string[]) => {
    const hasFocus = command === 'step-back'
    const focus = hasFocus ? (await getLenses($)).focus : ''
    if (hasFocus) await updateLenses($, current => ({ ...current, focus: '' }))
    await pressRun($, command, lensArgs(set, focus))
  }
  const toggleLens = (command: LensCommand, lens: string) => async () => {
    const now = await $.clock.now()
    const key = `${command}:${lens}`
    const isDouble = lastLensPress !== undefined && lastLensPress.key === key && now - lastLensPress.at < DOUBLE_PRESS_MS
    lastLensPress = isDouble ? undefined : { key, at: now }
    if (isDouble) {
      // The first press of the pair toggled it; the double runs it alone and clears the selection.
      await updateLenses($, current => ({ ...current, [command]: [] }))
      await pressRun($, command, lens)
      return
    }
    await updateLenses($, current => {
      const picked = current[command]
      return { ...current, [command]: picked.includes(lens) ? picked.filter(one => one !== lens) : [...picked, lens] }
    })
  }
  const toggles = (key: string, command: LensCommand, list: readonly Lens[]) => {
    const picked = lenses[command]
    return divided(key, list.map(lens => {
      hint.add(`${command}-${lens.name}`, `${lens.label}: ${lens.hint} Double click runs it alone.`)
      return {
        key: lens.name,
        scope: `${command}-${lens.name}`,
        onPress: toggleLens(command, lens.name),
        label: picked.includes(lens.name) ? <Text bold color="suggestion">✓ {lens.label}</Text> : <Text>{lens.label}</Text>,
      }
    }))
  }
  // The round's pending pass carries the accent color: "next" until its run starts, then "running" until its report
  // moves the engine on. The pass after it depends on that report, so the pane never shows two.
  const pendingPass = round !== null && isRoundOpen(round) ? round.pending?.command ?? null : null
  const isPassRunning = pendingPass !== null && passRun !== null && passRun.id === round?.pending?.id && passRun.phase !== 'queued'
  const passWord = isPassRunning ? 'running' : 'next'
  const nextMark = (command: string) => pendingPass === command ? <Text color="claude"> ◂ {passWord}</Text> : null
  const lensHead = (command: LensCommand, title: string, base: string, hasFocus: boolean) => {
    const picked = lenses[command]
    const focus = hasFocus ? lenses.focus.trim() : ''
    const isRunShown = picked.length > 0 || focus !== ''
    hint.add(`${command}-base`, `Base: ${base}${focus === '' ? '' : ` Focus: ${focus}`}`)
    const sets = LENS_SETS[command]
    for (const set of sets) hint.add(`${command}-${set.key}`, `${set.label}: ${set.hint}${focus === '' ? '' : ` Focus: ${focus}`}`)
    hint.add(`${command}-run`, `Runs /${command} ${lensArgs(picked, focus)}`)
    return labelled(`${command}-head`, <Text bold color={pendingPass === command ? 'claude' : undefined}>{title}</Text>, (
      <Box flexDirection="row" columnGap={1}>
        <Box key={`${command}-base-box`} hover={{ scope: `${command}-base` }}>
          <Button key={`${command}-base`} onPress={() => runBase(command)}>Base</Button>
        </Box>
        {sets.map(set => (
          <Box key={`${command}-${set.key}-box`} hover={{ scope: `${command}-${set.key}` }}>
            <Button key={`${command}-${set.key}`} onPress={() => runSet(command, set.lenses)}>{set.label}</Button>
          </Box>
        ))}
        {isRunShown && (
          <Box key={`${command}-run-box`} hover={{ scope: `${command}-run` }}>
            <Button key={`${command}-run`} onPress={() => runLenses(command)}>Run {picked.length} ▸</Button>
          </Box>
        )}
        {nextMark(command)}
      </Box>
    ), 1)
  }
  const focusInput = Input === undefined ? null : (
    <Box key="focus-box" flexGrow={1} minWidth={16}>
      <Input key="focus" placeholder="your focus…" value={lenses.focus} submitLabel="Run"
        onInput={(typed: string) => updateLenses($, current => ({ ...current, focus: typed }))}
        onSubmit={async (typed: string) => {
          await updateLenses($, current => ({ ...current, focus: typed }))
          await runLenses('step-back')
        }} />
    </Box>
  )

  // A release run lists its records, each with its state; a reason (dropped, changed) shows on hover.
  const recordRows = (open: ConsoleRound) => (
    <Box key="release-records" flexDirection="column" marginTop={1}>
      {open.records.map(one => {
        if (one.reason !== null) hint.add(`rec-${one.id}`, `${one.id}: ${one.reason}`)
        return (
          <Box key={`rec-${one.id}`} flexDirection="column">
            <Box flexDirection="row" hover={one.reason === null ? undefined : { scope: `rec-${one.id}` }}>
              <Box width={10} flexShrink={0}><Text color={RECORD_COLOR[one.state]}>{one.state}</Text></Box>
              <Box key={`rec-${one.id}-idbox`} width={14} flexShrink={0}>
                <Button key={`rec-${one.id}-show`} plain onPress={() => pressOpenItem($, one.id)}><Text bold>{one.id}</Text></Button>
              </Box>
              <Box flexGrow={1} flexShrink={1}><Text wrap="truncate-end">{one.title}</Text></Box>
            </Box>
            {slot(one.id)}
          </Box>
        )
      })}
    </Box>
  )

  const roundBlock = (current: ConsoleRound | null) => {
    const isOpen = current !== null && isRoundOpen(current)
    const rows: any[] = [banner('round-banner', isOpen ? `${runNoun(current)} ${current.round}` : 'Round',
      isOpen ? [current.title, roundWords(current)].filter(Boolean).join(' · ') : 'none open', 1)]
    if (isOpen && current.summary !== null) rows.push(<Box key="round-summary" marginTop={1}><Text color="inactive">{current.summary}</Text></Box>)
    if (roundError !== null) rows.push(<Box key="round-error"><Text color="error" wrap="truncate-end">{roundError}</Text></Box>)
    if (!isOpen && current !== null && current.stopped !== null) {
      const { run: id, reason, ids } = current.stopped
      rows.push(<Box key="release-stopped" marginTop={1}><Text color="warning" wrap="wrap">release {id} stopped: {reason} · next: a round on {ids.join(', ')}</Text></Box>)
    }
    if (isOpen && current.records.length > 0) rows.push(recordRows(current))
    if (isOpen && current.questions.length > 0) rows.push(questionRows(current))
    return rows
  }

  // The round's log, below the controls: newest first.
  const logBlock = (current: ConsoleRound | null) => {
    if (current === null || !isRoundOpen(current) || current.log.length === 0) return []
    return [
      banner('log-banner', 'Log', `round ${current.round}`, 1),
      <Box key="round-log" flexDirection="column" marginTop={1}>
        {[...current.log].reverse().map((line, i) => (
          <Box key={`log-${i}`} flexDirection="row">
            <Box width={7} flexShrink={0}><Text color="inactive">{line.at}</Text></Box>
            <Box flexGrow={1} flexShrink={1}><Text color={line.text.startsWith('refused') ? 'warning' : 'inactive'} wrap="truncate-end">{line.text}</Text></Box>
          </Box>
        ))}
      </Box>,
    ]
  }

  // Controls: the passes and decide commands work with or without an open round.
  const controlsBlock = () => {
    const rows: any[] = [banner('controls-banner', 'Controls', '', 1)]
    rows.push(
      lensHead('step-back', 'Step Back', STEP_BACK_BASE, true),
      labelled('step-back-where', rightLabel('where'), (
        <Box flexDirection="row">
          {toggles('step-back-where-row', 'step-back', WHERE)}
          {focusInput !== null && <Text color="inactive"> • </Text>}
          {focusInput}
        </Box>
      )),
      labelled('step-back-what', rightLabel('what'), toggles('step-back-what-row', 'step-back', WHAT)),
      lensHead('ground', 'Ground', GROUND_BASE, false),
      labelled('ground-lenses', <Text> </Text>, toggles('ground-row', 'ground', GROUND)),
      labelled('decide', <Text bold>Decide</Text>, divided('decide-row', [
        { key: 'question-me', scope: 'decide-question-me', label: 'Question Me', onPress: run('question-me') },
        { key: 'challenge-rulings', scope: 'decide-challenge-rulings', onPress: run('challenge-rulings'),
          label: pendingPass === 'challenge-rulings' ? <Text color="claude">Challenge Rulings ◂ {passWord}</Text> : 'Challenge Rulings' },
        { key: 'explain', scope: 'decide-explain', label: 'Explain', onPress: run('explain') },
      ]), 1),
    )
    hint.add('decide-question-me', 'Runs /question-me: starts or resumes the round')
    hint.add('decide-challenge-rulings', 'Runs /challenge-rulings')
    hint.add('decide-explain', 'Runs /explain')
    return rows
  }

  const actionsRow = () => {
    const entries = [
      { key: 'commit', scope: 'action-commit', label: 'Commit', onPress: run('commit') },
      { key: 'push', scope: 'action-push', label: 'Commit and Push', onPress: () => pressSubmit($, 'commit and push') },
      ...(isRoundRole ? [{ key: 'release', scope: 'action-release', onPress: run(RELEASE_COMMAND),
        label: round !== null && isReleaseNext(round) ? <Text color="claude">Release Round</Text> : 'Release Round' }] : []),
      { key: 'retro', scope: 'action-retro', label: 'Retro', onPress: run('retro') },
      { key: 'compact', scope: 'action-compact', label: 'Compact', onPress: run('compact') },
    ]
    hint.add('action-commit', 'Runs /commit')
    hint.add('action-push', 'Sends "commit and push" as your message')
    hint.add('action-release', 'Runs /release-round')
    hint.add('action-retro', 'Runs /retro')
    hint.add('action-compact', 'Runs /compact; the round state is kept')
    return labelled('actions', <Text bold>Actions</Text>, divided('actions-row', entries), 1)
  }

  if (role === null) return <Text color="inactive">The console waits for a registered role (/role).</Text>
  const body = [
    ...boardBlock(role, board),
    ...(isRoundRole ? [...roundBlock(round), ...controlsBlock()] : []),
    ...(isRoundRole ? [] : [banner('controls-banner', 'Controls', '', 1)]),
    actionsRow(),
    ...(isRoundRole ? logBlock(round) : []),
  ]
  return (
    <Box flexDirection="column">
      {body}
      <Box key="hints" flexDirection="column" marginTop={1}>
        {hint.list.map(one => (
          <Box key={`hint-${one.scope}`} display="none" hover={{ scope: one.scope, display: 'flex' }}>
            <Text color="inactive">{one.text}</Text>
          </Box>
        ))}
      </Box>
    </Box>
  )
}

/** The band above the prompt: an open run in words plus the Base passes; after a close with records to release, the way to release them. */
export async function drawBand($: $, e: { props: RenderPropsOf['AbovePrompt'] } & Parameters<$['ui']['resolve']>[0]) {
  const role = await getRole($)
  const round = await getRound($)
  if (e.props.hasSurvey || role === null || !ROUND_ROLES.includes(role.role) || round === null) return undefined
  const { Box, Text, Button } = $.ui.resolve(e) as any
  if (!isRoundOpen(round)) {
    if (!isReleaseNext(round)) return undefined
    const { round: closed, count } = round.next.release
    return (
      <Box flexDirection="row" columnGap={1} flexWrap="wrap">
        <Text color="inactive">{closed} closed · {count} {count === 1 ? 'record' : 'records'} decided ·</Text>
        <Button key="band-release" onPress={() => pressRun($, RELEASE_COMMAND, '')}><Text color="claude">Release Round</Text></Button>
      </Box>
    )
  }
  return (
    <Box flexDirection="row" columnGap={1} flexWrap="wrap">
      <Text color="inactive">{runNoun(round)} {round.round}{round.protocol === 'release' && round.title ? ` · ${round.title}` : ''} · {roundWords(round)}</Text>
      {round.batch !== null && <Text color="warning">· waiting on your answer</Text>}
      {(['step-back', 'ground'] as const).map(command => (
        <Button key={`band-${command}`} onPress={() => pressRun($, command, '')}>
          <Text color={round.pending?.command === command ? 'claude' : undefined}>{command === 'step-back' ? 'Step Back' : 'Ground'}</Text>
        </Button>
      ))}
    </Box>
  )
}
