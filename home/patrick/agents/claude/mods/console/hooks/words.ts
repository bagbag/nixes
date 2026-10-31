// Lens names and the words the pane, the band and /console print. Lens names and focus follow
// skills/step-back/SKILL.md and skills/ground/SKILL.md, which own them: typed name = label in
// lowercase with hyphens.
import type { ConsoleBoard, ConsoleQuestion, ConsoleRole, ConsoleRound } from '../types'

import { isRoundOpen } from './engine'

export type Lens = { name: string; label: string; hint: string }
export type LensCommand = 'step-back' | 'ground'

export const STEP_BACK_BASE = 'Stance on the current focus (greenfield, cleanest end state with DX, whole picture), judged by Consumer, Root Fix, Bloat and Gaps.'
export const GROUND_BASE = 'Ground every open recommendation until it is strong; re-verify the premises of every reversed one.'

export const WHERE: readonly Lens[] = [
  { name: 'goal', label: 'Goal', hint: 'Where: one level up; judge the design against the goal behind it.' },
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
]

export const GROUND: readonly Lens[] = [
  { name: 'assumptions', label: 'Assumptions', hint: 'Re-verify every premise in current source, decided items and prior rulings included.' },
  { name: 'board', label: 'Board', hint: 'Open items the result makes moot, duplicates, answers or contradicts; act on each.' },
  { name: 'sources', label: 'Sources', hint: 'Read the owning docs, READMEs, sibling modules and transcripts not yet read.' },
  { name: 'probe', label: 'Probe', hint: 'Settle facts by running something: a probe, a test, a count over real data.' },
]

/** Lens names first, then the free focus: the typed form both skills read. */
export const lensArgs = (lenses: readonly string[], focus: string): string =>
  [...lenses, focus.trim()].filter(part => part !== '').join(' ')

const PULLS: readonly string[] = ['plan', 'design', 'implement', 'review']

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

const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`

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

/** At most three ids, then a count: `tstdl-a, tstdl-b, pt1 +2`. */
const someIds = (ids: readonly string[]): string => ids.slice(0, 3).join(', ') + (ids.length > 3 ? ` +${ids.length - 3}` : '')

const inSet = (round: ConsoleRound): number => round.records.filter(one => one.state === 'set' || one.state === 'released').length

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
