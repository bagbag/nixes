// The dialog gate and answer capture, as pure functions over the round and the dialog
// (console-spec 3 Dialog gate / Answer capture; contract-rulings R-B7).
import type { ConsoleDialogQuestion, ConsoleRound } from '../types'

import type { Answer } from './engine'

export const MARKER_PREFIX = 'round:'

export type DialogInput = {
  questions: readonly ConsoleDialogQuestion[]
  metadata?: { source?: string } | undefined
}

export type GateVerdict =
  | { action: 'pass'; marker: string }
  | { action: 'block'; key: string; reason: string }
  | { action: 'note'; text: string }

const squash = (value: string): string => value.trim().replace(/\s+/g, ' ')

const shape = (questions: readonly ConsoleDialogQuestion[]): string => JSON.stringify(questions.map(one => ({
  question: squash(one.question),
  header: squash(one.header),
  multiSelect: one.multiSelect === true,
  options: (one.options ?? []).map(option => ({ label: squash(option.label), description: squash(option.description ?? '') })),
})))

/** Same key for the same dialog, so a block happens once per dialog, not once per call. */
export function dialogKey(kind: string, input: DialogInput): string {
  return `${kind}:${input.metadata?.source ?? ''}:${shape(input.questions)}`
}

/**
 * Judges a dialog inside an open round: a marked dialog must be the issued batch; an unmarked
 * one must not repeat a staged question; each is blocked once (keys in `blocked`). Other
 * unmarked dialogs pass with a note for the model.
 */
export function judgeDialog(round: ConsoleRound & { round: string }, input: DialogInput, blocked: readonly string[]): GateVerdict {
  const marker = input.metadata?.source
  if (marker !== undefined && marker.startsWith(MARKER_PREFIX)) {
    const issued = round.batch
    if (issued !== null && issued.marker === marker && shape(issued.questions) === shape(input.questions)) return { action: 'pass', marker }
    const key = dialogKey('marked', input)
    if (blocked.includes(key)) return { action: 'note', text: `This dialog (${marker}) differs from the batch round ${round.round} issued; its answers were not recorded in the round.` }
    const reason = issued === null
      ? `${marker}: round ${round.round} has no batch issued. Run the round's next step through the protocol tool; it issues the batch.`
      : issued.marker !== marker
        ? `${marker}: round ${round.round} issued ${issued.marker}. Ask exactly that batch: ${JSON.stringify(issued.questions)}`
        : `${marker} differs from the batch round ${round.round} issued. Ask it exactly as issued: ${JSON.stringify(issued.questions)}`
    return { action: 'block', key, reason }
  }
  const staged = new Map(round.questions.filter(one => one.status !== 'answered').map(one => [squash(one.text), one.id]))
  const repeated = input.questions.map(one => staged.get(squash(one.question))).filter((id): id is string => id !== undefined)
  if (repeated.length > 0) {
    const key = dialogKey('unmarked', input)
    if (!blocked.includes(key)) {
      return {
        action: 'block',
        key,
        reason: `${repeated.join(', ')} ${repeated.length === 1 ? 'is' : 'are'} staged in round ${round.round}; the round asks ${repeated.length === 1 ? 'it' : 'them'} in its own batch. Run the round's next step through the protocol tool instead of asking directly.`,
      }
    }
  }
  return { action: 'note', text: `This dialog was not from round ${round.round}; its answers were not recorded in the round.` }
}

export type DialogResult = {
  isError?: true | undefined
  deny?: string | undefined
  result?: unknown
}

export type Capture =
  | { kind: 'answer'; input: Answer }
  | { kind: 'decline'; partial: Record<string, string> | null }
  | { kind: 'none' }

const strings = (value: unknown): Record<string, string> => {
  if (typeof value !== 'object' || value === null) return {}
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).filter((entry): entry is [string, string] => typeof entry[1] === 'string'))
}

/**
 * What a marked dialog's result records: an error result (any decline kind) or a dialog that
 * resolved itself (`afkTimeoutMs`) declines with nothing; otherwise the answers, annotations
 * and free text are recorded, with `followUp` when the person asked for another round.
 */
export function capture(marker: string, ran: DialogResult): Capture {
  if (ran.deny !== undefined) return { kind: 'none' }
  if (ran.isError === true) return { kind: 'decline', partial: null }
  const result = (typeof ran.result === 'object' && ran.result !== null ? ran.result : {}) as Record<string, unknown>
  if (typeof result.afkTimeoutMs === 'number') return { kind: 'decline', partial: null }
  const answers = strings(result.answers)
  const annotations = typeof result.annotations === 'object' && result.annotations !== null ? result.annotations as Record<string, unknown> : {}
  const response = typeof result.response === 'string' && result.response.trim() !== '' ? result.response : null
  return { kind: 'answer', input: { marker, answers, annotations, response, ...(result.followUp === true ? { followUp: true } : {}) } }
}
