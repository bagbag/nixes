// Lens names and the words the pane, the band and /console print. Lens names and focus follow
// skills/step-back/SKILL.md and skills/ground/SKILL.md, which own them: typed name = label in
// lowercase with hyphens.
import type { ConsoleBoard, ConsoleItemSlot, ConsoleQuestion, ConsoleRole, ConsoleRound } from '../types'

import { isRoundOpen } from './engine'

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

/** The step in words, with what it works on. */
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
export const openDialogText = (marker: string): string => `Open the dialog for batch ${marker}: call AskUserQuestion with the input protocol show gives`

/** The visible text after a dialog: what was answered, one line per question, without the dialog's recommended mark. */
export const answeredText = (questions: readonly { question: string }[], answers: Readonly<Record<string, string>>): string => {
  const picked = questions.filter(one => answers[one.question] !== undefined)
    .map((one, index) => `${index + 1}. ${cutAnswer((answers[one.question] ?? '').replace(/ \(recommended, (lean|strong)\)$/, ''))}`)
  return picked.length > 0 ? `Answered:\n${picked.join('\n')}` : 'The dialog was declined.'
}

const cutAnswer = (text: string): string => text.length > 80 ? `${text.slice(0, 79)}…` : text

/** `Round`, or `Release` for a release run (the same slot, r4-q17). */
export const runNoun = (round: ConsoleRound): string => round.protocol === 'release' ? 'Release' : 'Round'

export const COUNT_LABELS: readonly [keyof NonNullable<ConsoleBoard['counts']>, string][] = [
  ['questions', 'questions'], ['decided', 'decided'], ['toPlan', 'to plan'], ['inReview', 'in review'], ['forUser', 'for you'],
]

/** `/console` as text: what the pane shows, for a bridge client or a narrow terminal. */
export function consoleText(role: ConsoleRole, board: ConsoleBoard | null, round: ConsoleRound | null, isRoundRole: boolean): string {
  const lines: string[] = [`Board · ${role.role} ${role.actor}`]
  if (board === null) {
    lines.push('  board views not read yet')
  } else {
    if (board.counts !== null) lines.push('  ' + COUNT_LABELS.map(([key, label]) => `${label} ${board.counts?.[key] ?? 0}`).join(' · '))
    for (const item of board.items) lines.push(`  ${item.id}  ${item.status}  ${item.title}`)
    const stale = staleSessions(board)
    for (const session of board.sessions.filter(one => !stale.has(one.actor))) {
      const workers = session.workers === null ? '' : ` · workers ${session.workers.active}/${session.workers.cap}`
      lines.push(`  ${session.role} ${session.tool || '?'} ${session.actor}${session.pulls.length > 0 ? ` (${session.pulls.join(', ')})` : ''} · holds ${session.holds}${workers} · ${session.state || 'unknown'}`)
    }
    const holds = staleHolds(board, stale)
    if (holds.length > 0) lines.push(`  stale holds: ${holds.map(one => `${one.id} (${one.actor})`).join(', ')}`)
    if (board.error !== null) lines.push(`  board error: ${board.error}`)
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
