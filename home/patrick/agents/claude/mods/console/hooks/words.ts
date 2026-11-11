// Lens names, the words the pane, the band and /console print, and every text the model reads from the console (its tool's
// description, notes on tool results, compaction instructions). Lens names and focus follow
// skills/step-back/SKILL.md and skills/ground/SKILL.md, which own them: typed name = label in
// lowercase with hyphens.
import type { ConsoleBoard, ConsoleCount, ConsoleCr, ConsoleItemSlot, ConsoleQuestion, ConsoleReviewing, ConsoleRole, ConsoleRound, ConsoleSuggestion } from '../types'

import { isRoundOpen, START_COMMAND } from './engine'

export type Lens = { name: string; label: string; hint: string }
export type LensCommand = 'step-back' | 'ground'

export const STEP_BACK_BASE = 'Stance on the current focus (greenfield, cleanest end state with DX, whole picture), judged by Consumer, Root Fix, Bloat and Gaps.'
export const GROUND_BASE = 'Ground every open recommendation until it is strong; re-verify the premises of every reversed one.'

export const WHERE: readonly Lens[] = [
  { name: 'goal', label: 'Goal', hint: 'Where: one level up; judge the design against the goal behind it; dig into the real problem and the root fix (workaround, XY problem).' },
  { name: 'decisions', label: 'Decisions', hint: 'Where: every decision in the discussion together, not only the latest.' },
  { name: 'foundations', label: 'Foundations', hint: 'Where: what the design builds on: earlier rulings, conventions and contracts; re-judge them too.' },
]

export const WHAT: readonly Lens[] = [
  { name: 'consumer', label: 'Consumer', hint: 'What (base): walk a realistic consumer through the whole flow end to end.' },
  { name: 'root-fix', label: 'Root Fix', hint: 'What (base): fixes the root cause, not a symptom; the root may lie outside this module or repo.' },
  { name: 'bloat', label: 'Bloat', hint: 'What (base): over-engineered? Too much magic?' },
  { name: 'gaps', label: 'Gaps', hint: 'What (base): under-built; does anything the goal or realistic consumers need fall short?' },
  { name: 'clean', label: 'Clean', hint: 'What: the six cleanliness tests, one by one.' },
  { name: 'overfit', label: 'Overfit', hint: 'What: tailored to this case, or does it hold for the neighbouring cases?' },
  { name: 'mechanics', label: 'Mechanics', hint: 'What: how each part actually works end to end, and what breaks.' },
  { name: 'options', label: 'Options', hint: 'What: radically different ways (other mechanisms, owners, removing the need), each at its strongest; dropped only for a stated constraint or sourced fact.' },
]

export const GROUND: readonly Lens[] = [
  { name: 'assumptions', label: 'Assumptions', hint: 'Re-verify every premise in current source, decided items and prior rulings included.' },
  { name: 'board', label: 'Board', hint: 'Open items the result makes moot, duplicates, answers or contradicts; act on each.' },
  { name: 'sources', label: 'Sources', hint: 'Read the owning docs, READMEs, sibling modules and transcripts not yet read.' },
  { name: 'probe', label: 'Probe', hint: 'Settle facts by running something: a probe, a test, a count over real data.' },
]

/** Every lens of a command in list order: what the All button runs. */
export const ALL_LENSES: Record<LensCommand, readonly string[]> = {
  'step-back': [...WHERE, ...WHAT].map(lens => lens.name),
  ground: GROUND.map(lens => lens.name),
}

/** The Path and Refine buttons' Step Back lenses; the engine's check sequence runs the same sets (the validator compares them). */
export const PATH_LENSES: readonly string[] = ['goal', 'foundations']
export const REFINE_LENSES: readonly string[] = ['decisions', 'clean', 'overfit', 'mechanics']

/** The fixed lens sets each row offers after Base, in button order; Path and Refine are Step Back's only. */
export const LENS_SETS: Record<LensCommand, readonly { key: string; label: string; hint: string; lenses: readonly string[] }[]> = {
  'step-back': [
    { key: 'path', label: 'Path', hint: 'goal and foundations: is the direction right?', lenses: PATH_LENSES },
    { key: 'options', label: 'Options', hint: 'options: radically different ways to the outcome.', lenses: ['options'] },
    { key: 'refine', label: 'Refine', hint: 'decisions, clean, overfit, mechanics: sharpen the path.', lenses: REFINE_LENSES },
    { key: 'all', label: 'All', hint: 'every lens, in list order.', lenses: ALL_LENSES['step-back'] },
  ],
  ground: [{ key: 'all', label: 'All', hint: 'every lens, in list order.', lenses: ALL_LENSES.ground }],
}

/** Lens names first, then the free focus: the typed form both skills read. */
export const lensArgs = (lenses: readonly string[], focus: string): string =>
  [...lenses, focus.trim()].filter(part => part !== '').join(' ')

const PULLS: readonly string[] = ['plan', 'design', 'implement', 'review']

/** A session's role for the pane's fixed column, which `autopilot` would overflow. */
export const roleText = (role: string): string => role === 'autopilot' ? 'auto' : role

/** An agent's pulls as fixed-position initials, a missing pull as `·`: `p d i r`, `· d i ·`; empty without pulls. */
export const pullsText = (pulls: readonly string[]): string =>
  pulls.length === 0 ? '' : PULLS.map(pull => pulls.includes(pull) ? pull[0] : '·').join(' ')

/**
 * Sessions the board can only show through stale holds: gone, or with unknown state and every
 * hold idle or gone. The pane lists their holds in one line instead of session rows.
 */
export function staleSessions(board: ConsoleBoard): Set<string> {
  const holdsOf = (actor: string) => board.held.filter(one => one.holder === actor || one.holder.startsWith(`${actor}/`))
  return new Set(board.sessions.filter(one => one.state === 'gone'
    || (one.state === '' && one.holds > 0 && holdsOf(one.actor).every(hold => hold.mark !== null))).map(one => one.actor))
}

export const staleHolds = (board: ConsoleBoard, stale: Set<string>): { id: string; actor: string }[] =>
  board.held.map(one => ({ id: one.id, actor: one.holder.split('/')[0] ?? '' })).filter(one => stale.has(one.actor))

export const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`

/** The protocol tool's call in one line: its arguments (`step`, `show --json`); the result's headline says what it did. */
export function protocolCallText(input: unknown): string {
  const raw = typeof input === 'object' && input !== null ? (input as { args?: unknown }).args : undefined
  const args = Array.isArray(raw) ? raw.filter((arg): arg is string => typeof arg === 'string') : []
  return args.join(' ') || 'protocol'
}

/** The protocol tool's result in one line: the engine's headline, its first line (for answers, the note's). */
export function protocolResultText(output: unknown): string {
  let text = typeof output === 'string' ? output
    : typeof output === 'object' && output !== null && typeof (output as { result?: unknown }).result === 'string' ? (output as { result: string }).result
      : JSON.stringify(output ?? '')
  try {
    const parsed = JSON.parse(text) as { note?: unknown }
    if (typeof parsed?.note === 'string') text = parsed.note
  } catch {
    // not JSON: the engine's text
  }
  return text.split('\n').find(line => line.trim() !== '') ?? ''  // the row truncates at the terminal's width
}

/** A question's recommendation with its backing: `lean (unverified: …): Keep`, `strong: Keep (noAssumptions true: …)`. */
export function recommendationText(question: ConsoleQuestion): string {
  if (question.recommendation === null || question.strength === null) return ''
  if (question.strength === 'lean') {
    const because = question.leanBecause
    const kind = because?.cause === 'evidence' ? 'unverified' : 'your call'
    return `lean (${kind}: ${because?.detail ?? ''}): ${question.recommendation}`
  }
  const claims = Object.entries(question.strongBecause ?? {}).map(([name, value]) => `${name} ${value}`).join('; ')
  return `strong: ${question.recommendation}${claims === '' ? '' : ` (${claims})`}`
}

/** The row mark of a question's recommendation: strong, or what a lean rests on (colors are the pane's palette names). */
export function recommendationMark(question: ConsoleQuestion): { text: string; color: string } | null {
  if (question.strength === 'strong') return { text: '◆ strong', color: 'inactive' }
  if (question.strength !== 'lean') return null
  return question.leanBecause?.cause === 'evidence' ? { text: 'unverified', color: 'warning' } : { text: 'your call', color: 'claude' }
}

const ANSWER_SHOWN = 40

/** The answer on an answered row, cut to keep the row one line (typed and model-reported answers can be long). */
export function answerText(answer: string): string {
  const one = answer.replace(/\s+/g, ' ').trim()
  return one.length > ANSWER_SHOWN ? `${one.slice(0, ANSWER_SHOWN - 1).trimEnd()}…` : one
}

const SLOT_TEXT_LINES = 4

/** The text of a slot: the `## Decision` body when there is one, else the description from its start; heading and blank lines dropped, at most four lines (`…` ends a cut one). */
function slotLines(description: string): string[] {
  const decision = /^##\s+Decision\s*$([\s\S]*?)(?=^##\s|(?![\s\S]))/m.exec(description)
  const lines = (decision?.[1] ?? description).split('\n').map(line => line.trimEnd()).filter(line => line.trim() !== '' && !/^\s*#/.test(line))
  return lines.length > SLOT_TEXT_LINES ? [...lines.slice(0, SLOT_TEXT_LINES - 1), `${lines[SLOT_TEXT_LINES - 1]} …`] : lines
}

/** A board item's fields as the slot shows them (the row above already has id, status and title). */
export function itemSlot(id: string, raw: Record<string, unknown>): ConsoleItemSlot {
  const str = (value: unknown): string => typeof value === 'string' ? value : ''
  const links = (Array.isArray(raw.dependencies) ? raw.dependencies : []).map(one => {
    const entry = typeof one === 'object' && one !== null ? one as Record<string, unknown> : {}
    return { issue: str(entry.issue_id), on: str(entry.depends_on_id), type: str(entry.type) }
  })
  const unique = (ids: string[]): string[] => [...new Set(ids)]
  const groups: [string, string[]][] = [
    ['blocked by', unique(links.filter(one => one.type === 'blocks' && one.issue === id).map(one => one.on))],
    ['blocks', unique(links.filter(one => one.type === 'blocks' && one.on === id).map(one => one.issue))],
    ['relates to', unique(links.filter(one => one.type === 'relates-to').map(one => one.issue === id ? one.on : one.issue))],
  ]
  const parent = links.find(one => one.type === 'parent-child' && one.issue === id)?.on
  const children = unique(links.filter(one => one.type === 'parent-child' && one.on === id).map(one => one.issue))
  const labels = (Array.isArray(raw.labels) ? raw.labels : []).map(str).filter(label => label !== '')
  const comments = typeof raw.comment_count === 'number' ? raw.comment_count : 0
  const counted = (label: string, ids: string[]): string[] => ids.length > 0 ? [`${label} ${ids.length}`] : []
  const facts = [
    str(raw.issue_type), ...(typeof raw.priority === 'number' ? [`p${raw.priority}`] : []),
    ...(str(raw.assignee) === '' ? [] : [`held by ${str(raw.assignee)}`]),
    ...(labels.length > 0 ? [labels.join(', ')] : []),
    ...(parent === undefined || parent === '' ? [] : [`parent ${parent}`]),
    ...groups.flatMap(([label, ids]) => counted(label, ids)), ...counted('children', children),
    ...(comments > 0 ? [`${comments} ${comments === 1 ? 'comment' : 'comments'}`] : []),
    `/console-item ${id}`,
  ].filter(part => part !== '').join(' · ')
  const linked = [...groups, ['parent', parent === undefined || parent === '' ? [] : [parent]] as [string, string[]], ['children', children] as [string, string[]]]
    .filter(([, ids]) => ids.length > 0).map(([label, ids]) => `${label} ${ids.join(', ')}`).join(' · ')
  return { lines: slotLines(str(raw.description)), facts, linked }
}

/** At most three ids, then a count: `tstdl-a, tstdl-b, pt1 +2`. */
const someIds = (ids: readonly string[]): string => ids.slice(0, 3).join(', ') + (ids.length > 3 ? ` +${ids.length - 3}` : '')

const inSet = (round: ConsoleRound): number => round.records.filter(one => one.state === 'set' || one.state === 'revised' || one.state === 'released').length

function stepWords(round: ConsoleRound): string {
  const p = round.progress
  const count = (status: string) => round.questions.filter(one => one.status === status).length
  switch (round.step) {
    case 'collect': return p === null ? 'collecting' : `collecting · ${p.classified}/${p.items + p.points} classified`
    case 'select': return p === null || p.candidates === null ? 'selecting' : `selecting from ${plural(p.candidates, 'candidate')}`
    case 'stage': return p === null || p.selected.length === 0 ? 'staging' : `staging questions for ${someIds(p.selected)}`
    case 'related': return 'resolving related items'
    case 'ask': return round.protocol === 'release' ? (count('asked') > 0 ? 'asking your approval' : 'approval to ask again')
      : `asking · ${count('asked')} in the dialog${count('ready') > 0 ? ` · ${count('ready')} to come` : ''}`
    case 'record': return `recording ${plural(count('answered'), 'answer')}`
    case 'recheck': return `re-checking ${plural(inSet(round), 'record')}`
    case 'board-check': return `board check of ${plural(inSet(round), 'record')}`
    case 'own-rulings': return 'listing own rulings'
    case 'scoped': return 'checking the revised records'
    case 'approval': return 'approval'
    case 'owners': return 'checking owner writes'
    case 'release': return 'releasing; rerun waits'
    default: return String(round.step)
  }
}

/** The round's state in words: step, convergence, what waits. */
export function roundWords(round: ConsoleRound): string {
  if (!isRoundOpen(round)) return 'no round open'
  const parts: string[] = []
  if (round.step === 'check' && round.check !== null) {
    parts.push(`checking ${round.check.cycle}/${round.check.cap}`)
    const last = Object.entries(round.check.last)
    if (last.length > 0) {
      parts.push(last.every(([, one]) => one.changes === 0)
        ? 'no changes, converged'
        : last.map(([pass, one]) => `${pass} ${one.changes === 0 ? 'none' : `changed ${one.changes}`}`).join(', '))
    }
  } else {
    parts.push(stepWords(round))
  }
  if (round.pending !== null) parts.push(`next /${round.pending.command}`)
  const unresolved = round.questions.reduce((sum, one) => sum + one.overlaps.filter(overlap => overlap.outcome === null).length, 0)
  if (unresolved > 0) parts.push(`${plural(unresolved, 'overlap')} to resolve`)
  const held = round.questions.filter(one => one.status === 'held').length
  if (held > 0) parts.push(`${held} held`)
  return parts.join(' · ')
}

/** The message the console sends when it could not open a batch's dialog itself: the model opens it. */
export const openDialogText = (marker: string): string =>
  `Open the dialog for batch ${marker}: call protocol with ["show"] (not --json) and pass the AskUserQuestion input it prints unchanged, metadata included.`

/** What /console-continue (r7-q24) sends the model with nothing pending or out: the engine's status line. */
export const continueText = (line: string): string => `Continue the round: ${line}`
/** /console-continue's notices when it starts nothing. */
export const CONTINUE_NO_ROUND = 'nothing to continue: no round is open'
export const continueInHandText = (command: string, id: string): string => `nothing to continue: /${command} (${id}) is already queued or running`

/** The console asks the model once for a report it did not give. */
export const missingReportText = (command: string, id: string, args: string): string =>
  `The /${command} pass (${id}) ended without its report. Report its per-question updates through the protocol tool; if it did not run, run /${[command, args].filter(part => part !== '').join(' ')} with the Skill tool first.`

/** Why the console drops a stale queued prompt: the host hands this back to the console's own send, which expects it. */
export const STALE_DROP = 'stale console action'

/** Replaces the skill text of a queued pass run the round has left. */
export const STALE_PASS_TEXT = "This pass is no longer pending; reply 'stale' and end your turn."

/** A pass that still has no report: the round stopped, and what the person can type. */
export const stuckPassText = (command: string, args: string): string => `The round stopped: the /${command} pass has no report. Type /${[command, args].filter(part => part !== '').join(' ')} to run it again.`

export const PROTOCOL_TOOL_DESCRIPTION = [
  "Runs the protocol engine for this session's round (`protocol <args>`): one call per step, per-question updates as JSON on stdin; the output is the next step.",
  'Read: ["show","--json"], ["show"], ["show","q3"] (that question whole), ["status","--line"], ["history"], ["next"].',
  'Record an answer the user typed in chat: ["answer"] with stdin {"question","answer","quote"}, the quote being the user\'s exact words.',
  'Apply a change the user asked for to the questions: ["edit"] with stdin {"updates","quote"}, the quote being the user\'s exact words.',
  'Leave --session, --origin and recording dialog answers, declines and pass runs to the console.',
].join(' ')
export const PROTOCOL_ARGS_DESCRIPTION = 'The verb and its arguments, e.g. ["start","round"], ["step"] or ["show","--json"]'
export const PROTOCOL_STDIN_DESCRIPTION = 'JSON text for the verb (per-question updates), when it reads stdin'

/** The tool's results when the console does not run the engine. */
export const TOOL_IDLE_TEXT = 'The console is idle in this session (no lead, solo or autopilot role, or the console is not drawn); run `protocol` through Bash.'
export const toolFailedText = (reason: string | undefined): string =>
  `The console's protocol call failed${reason === undefined || reason === '' ? '' : `: ${reason}`}. It may have run in part: read the round with \`protocol show\` (through Bash if this tool fails again) before you run it again. A Record step runs again safely.`

/** The dialog gate's refusals and notes. */
export const unprintedBatchText = (marker: string): string =>
  `${marker}: the console has not printed this batch's question text yet. Write one short line that questions are coming, nothing about their content, and end your turn: the console prints them at the turn's end and opens the dialog.`
export const differingDialogNote = (marker: string, round: string): string =>
  `This dialog (${marker}) differs from the batch round ${round} issued; its answers were not recorded in the round.`
export const noBatchText = (marker: string, round: string): string =>
  `${marker}: round ${round} has no batch issued. Run the round's next step through the protocol tool; it issues the batch.`
export const otherBatchText = (marker: string, round: string, issued: string, questions: unknown): string =>
  `${marker}: round ${round} issued ${issued}. Ask exactly that batch: ${JSON.stringify(questions)}`
export const differingBatchText = (marker: string, round: string, questions: unknown): string =>
  `${marker} differs from the batch round ${round} issued. Ask it exactly as issued: ${JSON.stringify(questions)}`
export const stagedText = (repeated: readonly string[], round: string): string =>
  `${repeated.join(', ')} ${repeated.length === 1 ? 'is' : 'are'} staged in round ${round}; the round asks ${repeated.length === 1 ? 'it' : 'them'} in its own batch. Run the round's next step through the protocol tool instead of asking directly.`
export const foreignDialogNote = (round: string): string => `This dialog was not from round ${round}; its answers were not recorded in the round.`

/** Notes on a dialog's result: the line a decline sends, and those that did not reach the round. */
export const DECLINED_TEXT = 'The dialog was declined.'
export const declinedNote = (marker: string): string => `The dialog was declined; batch ${marker} stays out.`
export const declineFailedNote = (marker: string, error: string): string => `Recording the decline of ${marker} failed: ${error}. The batch stays out.`
export const NO_QUESTION_TEXT = 'No question text to print.'

/** What the model reads of a batch the person has in the chat as a placed row: the dialog's numbering, titles, recommendations and what changed. */
export function questionListText(marker: string, lines: readonly string[]): string {
  return `\nBatch ${marker}: the user has the full questions in the chat. Their dialog opens next.\n${lines.join('\n')}\n(\`protocol show <id>\` shows one question whole.)`
}

/** One question of that list; `number` is null for a one-question dialog, which the dialog does not number. */
export function questionListLine(number: number | null, question: ConsoleQuestion | undefined, header: string): string {
  const mark = question === undefined || question.recommendation === null ? 'none' : `${question.recommendation}${question.strength === null ? '' : ` (${question.strength})`}`
  const changed = question === undefined || question.changedBy === null ? '' : `; changed by the ${question.changedBy} pass`
  return `${number === null ? '-' : `${number}.`} ${question === undefined ? header : `${question.title} (${question.id})`}: recommended ${mark}${changed}`
}

type RoundSuggestion = Extract<ConsoleSuggestion, { kind: 'round' }>

const approx = (n: number, word: string): string => `~${n} ${n === 1 ? word : `${word}s`}`

/** A proposed round on one line: the title, the model's estimates, and that Start compacts first. A row stored before the estimates shows its title alone. */
export const suggestionText = (suggestion: RoundSuggestion): string =>
  [
    suggestion.title,
    ...(suggestion.estimate === null ? [] : [approx(suggestion.estimate.questions, 'question'), `unblocks ${approx(suggestion.estimate.unblocks, 'item')}`]),
    ...(suggestion.isCompacting ? ['compacts first'] : []),
  ].join(' · ')

/** The proposed round's hover hint: the model's reason for its rank, and what its Start runs. */
export const startHint = (suggestion: RoundSuggestion): string =>
  [
    suggestion.why,
    `Start runs /${START_COMMAND} ${suggestion.number}${suggestion.isCompacting ? ' after /compact' : ''}${suggestion.ids.length > 0 ? '; click the row to list the leading questions' : ''}`,
  ].filter(part => part !== '').join(' · ')
export const unsavedNote = (marker: string, error: string): string => `Your answers to ${marker} were not saved (${error}), so the questions come again.`

/** What compaction keeps, and the round line it adds after. */
export const keepRoundText = (round: string, step: string | null): string =>
  `Keep the protocol round state: round ${round}, step ${step}, each question's id, status and open overlap, the pending pass, and that the round runs through the protocol tool (mcp__console__protocol).`
export const keepStartText = (title: string | undefined): string => `Keep the proposed next round, which starts right after this compaction: ${title}.`
export const startAbandonedText = (why: string, start: { command: string; args: string; title: string }): string =>
  `the next round was not started (${why}): ${start.title}; type /${start.command} ${start.args} to start it`
export const compactedNote = (line: string): string => `<console-note>Protocol state after compaction: ${line}</console-note>`

/** `Round`, or `Release` for a release run (the same slot, r4-q17). */
export const runNoun = (round: ConsoleRound): string => round.protocol === 'release' ? 'Release' : 'Round'

export const COUNT_LABELS: readonly [keyof NonNullable<ConsoleBoard['counts']>, string][] = [
  ['questions', 'questions'], ['decided', 'decided'], ['toPlan', 'to plan'], ['toReview', 'to review'], ['toAccept', 'to accept'], ['toRatify', 'to ratify'], ['forUser', 'for you'],
]

/** `<ready>` plus ` (k wait)` when items of that step wait (r21-q141). */
export function countText(count: ConsoleCount | undefined): string {
  const rest = count === undefined ? [] : ([[count.held, 'held'], [count.waiting, 'wait']] as const).filter(([n]) => n > 0).map(([n, word]) => `${n} ${word}`)
  return `${count?.ready ?? 0}${rest.length > 0 ? ` (${rest.join(', ')})` : ''}`
}

// Change requests (r25): the queue the board prints, in words. The presses put these requests in the prompt; the console never lands.

const short = (sha: string): string => sha.slice(0, 7)

export function crStageText(cr: ConsoleCr): string {
  if (cr.status === 'needs_acceptance') return cr.checkpoint === 'user' ? 'to accept (design)' : 'to accept'
  if (cr.status === 'in_review') return cr.checkpoint === null ? 'in review' : 'checkpoint review'
  return cr.status === 'in_progress' ? 'in work' : cr.status.replace(/_/g, ' ')
}

const CHECK_WORDS: Record<ConsoleCr['check']['state'], string> = { current: 'checks current', stale: 'stale', conflict: 'conflict', failed: 'checks failed', unchecked: 'unchecked' }

/** The check state as a word; null while the change request has not reached review and nothing ran (nothing to say yet). */
export function crCheckText(cr: ConsoleCr): string | null {
  return cr.status !== 'in_review' && cr.status !== 'needs_acceptance' && cr.check.state === 'unchecked' ? null : CHECK_WORDS[cr.check.state]
}

/** The no-new-failures comparison: `0 new (base 3012, tip 2972)`, or the new ones named (first three); null while none ran. */
export function crFailuresText(cr: ConsoleCr): string | null {
  const { newFailures, baseCount, tipCount } = cr.check
  if (newFailures === null) return null
  const counts = baseCount === null || tipCount === null ? '' : ` (base ${baseCount}, tip ${tipCount})`
  if (newFailures.length === 0) return `0 new${counts}`
  const named = newFailures.slice(0, 3).join(', ')
  return `${newFailures.length} new: ${named}${newFailures.length > 3 ? ', …' : ''}${counts}`
}

/** What holds the request up besides its check, each with its colour: setup failed, review stale (waiting for its Accept), land blocked (paths, first three), returned, lands with its base. */
export function crMarks(cr: ConsoleCr): { text: string; isProblem: boolean }[] {
  const blocked = cr.landBlocked ?? []
  return [
    ...(cr.setupFailed ? [{ text: 'setup failed', isProblem: true }] : []),
    ...(isCrAccepting(cr) && cr.reviewState === 'stale' ? [{ text: 'review stale', isProblem: true }] : []),
    ...(blocked.length > 0 ? [{ text: `land blocked: ${blocked.slice(0, 3).join(', ')}${blocked.length > 3 ? ', …' : ''}`, isProblem: true }] : []),
    ...(cr.returned ? [{ text: 'returned', isProblem: false }] : []),
    ...(cr.after !== null ? [{ text: `lands with ${cr.after}`, isProblem: false }] : []),
  ]
}

/** `look · view` as the board holds them; null when neither is set. */
export const crLookText = (cr: ConsoleCr): string | null => cr.look === null && cr.view === null ? null : [cr.look === null ? null : `look ${cr.look}`, cr.view].filter(part => part !== null).join(' · ')

/** The stack as rows: the queue's order, each child directly under its parent; a child whose parent is not queued stands at the top. */
export function crRows(crs: readonly ConsoleCr[]): { cr: ConsoleCr; depth: number }[] {
  const ids = new Set(crs.map(one => one.id))
  const rows: { cr: ConsoleCr; depth: number }[] = []
  const seen = new Set<string>()
  const add = (cr: ConsoleCr, depth: number) => {
    if (seen.has(cr.id)) return
    seen.add(cr.id)
    rows.push({ cr, depth })
    for (const child of crs.filter(one => one.parent === cr.id)) add(child, depth + 1)
  }
  for (const cr of crs.filter(one => one.parent === null || !ids.has(one.parent))) add(cr, 0)
  for (const cr of crs) add(cr, 0)  // a parent cycle would otherwise hide its members
  return rows
}

/** Whether the person can look at, accept or return it: the board waits for them. */
export const isCrAccepting = (cr: ConsoleCr): boolean => cr.status === 'needs_acceptance'

/** Refreshing is review work: offered only on the request the board marks as refresh work, in a session that pulls reviews. */
export const canRefreshCr = (cr: ConsoleCr, pulls: readonly string[]): boolean => cr.refreshWork && pulls.includes('review')

/** The tip a request names: the one in the review tree for this request when it is open, else the board's current tip. */
export const crTipFor = (cr: ConsoleCr, reviewing: ConsoleReviewing | null): string | null => reviewing?.cr === cr.id ? reviewing.tip : cr.tip

/** The Accept request for the lead (decide.md Accept), naming the tip it was looked at in so a moved branch is refused. */
export function acceptText(cr: ConsoleCr, tip: string): string {
  return cr.checkpoint === 'user'
    ? `Accept the design of ${cr.id} (${cr.title}) at ${short(tip)}: planning continues in the same request, nothing lands.`
    : `Accept ${cr.id} (${cr.title}) at ${short(tip)}: land it.`
}
export const returnText = (cr: ConsoleCr): string => `Return ${cr.id} (${cr.title}): `
export const walkText = (cr: ConsoleCr): string => `Walk me through ${cr.id}'s result (${cr.title}).`
export const refreshText = (cr: ConsoleCr): string => `Refresh ${cr.id} under the review protocol's Refresh.`

/** One change request as a text line: state only, since a text reader presses nothing. */
export function crLine(cr: ConsoleCr, depth: number, reviewing: ConsoleReviewing | null): string {
  const tree = reviewing?.cr === cr.id ? (reviewing.tip === cr.tip ? 'in review tree' : 'review tree behind') : null
  const parts = [crStageText(cr), crCheckText(cr), crFailuresText(cr), crLookText(cr), tree, cr.holder === null ? null : `held by ${cr.holder}`].filter(part => part !== null)
  return `${'  '.repeat(depth + 1)}${cr.id}  ${cr.title} · ${parts.join(' · ')}`
}

/** `/console` as text: what the pane shows, for a bridge client or a narrow terminal. */
export function consoleText(role: ConsoleRole, board: ConsoleBoard | null, round: ConsoleRound | null, isRoundRole: boolean, offered: readonly ConsoleSuggestion[], reviewing: ConsoleReviewing | null = null): string {
  const lines: string[] = [`Board · ${role.role} ${role.actor}`]
  if (board === null) {
    lines.push('  board views not read yet')
  } else {
    if (board.counts !== null) lines.push('  ' + COUNT_LABELS.map(([key, label]) => `${label} ${countText(board.counts?.[key])}`).join(' · '))
    if (board.sync !== null) lines.push(`  ${board.sync}`)
    if (board.queues !== null) lines.push(`  ${board.queues}`)
    for (const item of board.items) lines.push(`  ${item.id}  ${item.status}  ${item.title}`)
    const stale = staleSessions(board)
    for (const session of board.sessions.filter(one => !stale.has(one.actor))) {
      const workers = session.workers === null ? '' : ` · workers ${session.workers.active}/${session.workers.cap}`
      lines.push(`  ${session.role} ${session.tool || '?'} ${session.actor}${session.pulls.length > 0 ? ` (${session.pulls.join(', ')})` : ''} · holds ${session.holds}${workers} · ${session.state || 'unknown'}`)
    }
    const holds = staleHolds(board, stale)
    if (holds.length > 0) lines.push(`  stale holds: ${holds.map(one => `${one.id} (${one.actor})`).join(', ')}`)
    if (board.error !== null) lines.push(`  board error: ${board.error}`)
    if (board.crs.length > 0) {
      lines.push('', 'Change requests')
      for (const { cr, depth } of crRows(board.crs)) lines.push(crLine(cr, depth, reviewing))
    }
    if (board.ratifications.length > 0) {
      lines.push('', 'To ratify')
      for (const one of board.ratifications) lines.push(`  ${one.id}  ${one.title} · landed in ${one.cr}`)
    }
  }
  const proposed = isRoundRole ? offered.flatMap(one => one.kind === 'round' ? [one] : []) : []
  if (proposed.length > 0) {
    lines.push('', 'Suggestions')
    for (const one of proposed) lines.push(`  ${one.number}. ${[suggestionText(one), one.summary, `type /${START_COMMAND} ${one.number}`].filter(part => part !== '').join(' · ')}`)
  }
  if (isRoundRole && round !== null && !isRoundOpen(round) && round.stopped !== null) {
    lines.push('', `Release ${round.stopped.run} stopped: ${round.stopped.reason} · next: a round on ${round.stopped.ids.join(', ')}`)
  }
  if (isRoundRole && round !== null && isRoundOpen(round)) {
    lines.push('', `${runNoun(round)} ${round.round}${round.title ? ` · ${round.title}` : ''} · ${roundWords(round)}`)
    if (round.summary) lines.push(`  ${round.summary}`)
    for (const one of round.records) lines.push(`  ${one.state.padEnd(8)} ${one.id}  ${one.title}${one.reason === null ? '' : ` · ${one.reason}`}`)
    for (const question of round.questions) {
      const overlaps = question.overlaps.filter(one => one.outcome === null).map(one => one.id)
      lines.push(`  ${question.status.padEnd(8)} ${question.id}  ${question.title}${overlaps.length > 0 ? ` · overlaps ${overlaps.join(', ')}` : ''}`)
    }
  }
  return lines.join('\n')
}
