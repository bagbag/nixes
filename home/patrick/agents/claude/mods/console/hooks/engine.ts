// The one owner of every call to the protocol engine and the board: argv, stdin, the session
// flag and parsing (console-spec 1a, contract-rulings R-B1..R-B5). The mod never reads the
// engine's state files.
import type { EngineInterface } from 'claude-code'

import type {
  ConsoleAction, ConsoleAgent, ConsoleBoard, ConsoleCounts, ConsoleDialogQuestion, ConsoleHeld, ConsoleItem, ConsolePassOrigin, ConsolePending, ConsoleProgress, ConsoleProposal, ConsoleQuestion,
  ConsoleRecord, ConsoleRole, ConsoleRound, ConsoleSession,
} from '../types'

type $ = EngineInterface

export const CONTRACT_VERSION = 1
export const ROUND_ROLES: readonly string[] = ['lead', 'solo', 'autopilot']
export const PASS_COMMANDS: readonly string[] = ['step-back', 'ground', 'challenge-rulings']

export class EngineError extends Error {}

export async function home($: $): Promise<string> {
  const value = await $.env.get('HOME')
  if (value === undefined || value === '') throw new EngineError('HOME is unset')
  return value
}

/** session-lead-mode is a bash script without the execute bit, run through bash as every caller does. */
async function registry($: $, args: readonly string[]): Promise<Ran> {
  const ran = await $.process.run(['bash', binary(await home($), 'session-lead-mode'), ...args], { timeoutMs: 10_000 })
  return { exitCode: ran.exitCode, stdout: ran.stdout, stderr: ran.stderr }
}

/** The registry's state dir (`session-lead-mode state-dir`, its owner); console-notified markers live there. */
export async function stateDir($: $): Promise<string> {
  const ran = await registry($, ['state-dir'])
  if (ran.exitCode !== 0 || ran.stdout.trim() === '') throw new EngineError(`session-lead-mode state-dir: exit ${ran.exitCode}: ${ran.stderr.trim()}`)
  return ran.stdout.trim()
}
const binary = (homeDir: string, name: string): string => `${homeDir}/.agents/bin/${name}`

export type Ran = { exitCode: number; stdout: string; stderr: string }

/** $.process.run's maximum: a Record of a large round runs for minutes (r4-q12). */
const PROTOCOL_TIMEOUT_MS = 600_000

/** Runs `protocol --session <id> <args>`; the tool relays this raw result. */
export async function protocol($: $, session: string, args: readonly string[], stdin?: string): Promise<Ran> {
  const homeDir = await home($)
  const ran = await $.process.run([binary(homeDir, 'protocol'), '--session', session, ...args],
    { timeoutMs: PROTOCOL_TIMEOUT_MS, ...(stdin === undefined ? {} : { stdin }) })
  return { exitCode: ran.exitCode, stdout: ran.stdout, stderr: ran.stderr }
}

async function protocolJson($: $, session: string, args: readonly string[], stdin?: unknown): Promise<unknown> {
  const ran = await protocol($, session, args, stdin === undefined ? undefined : JSON.stringify(stdin))
  if (ran.exitCode !== 0) throw new EngineError(`protocol ${args.join(' ')}: exit ${ran.exitCode}: ${ran.stderr.trim() || ran.stdout.trim()}`)
  try {
    return JSON.parse(ran.stdout)
  } catch {
    throw new EngineError(`protocol ${args.join(' ')}: output is not JSON`)
  }
}

export async function show($: $, session: string): Promise<ConsoleRound> {
  return parseRound(await protocolJson($, session, ['show', '--json']))
}

export async function pending($: $, session: string): Promise<ConsolePending | null> {
  return parsePending(await protocolJson($, session, ['pending']))
}

export type Answer = { marker: string; answers: Record<string, string>; annotations: Record<string, unknown>; response: string | null; followUp?: true }

export async function answer($: $, session: string, input: Answer): Promise<ConsoleRound> {
  return parseRound(await protocolJson($, session, ['answer', '--origin', 'dialog'], input))
}

export async function decline($: $, session: string, input: { marker: string; partial: Record<string, string> | null }): Promise<ConsoleRound> {
  return parseRound(await protocolJson($, session, ['decline', '--origin', 'dialog'], input))
}

export async function pass($: $, session: string, origin: ConsolePassOrigin, input: { command: string; args: string; pending: string | null }): Promise<ConsoleRound> {
  return parseRound(await protocolJson($, session, ['pass', '--origin', origin], input))
}

/** Tells the engine the console dropped a stale action (logged in the round's history). */
export async function dropped($: $, session: string, action: ConsoleAction): Promise<void> {
  const report = action.kind === 'pass' ? { kind: action.kind, id: action.id } : { kind: action.kind, marker: action.marker }
  const ran = await protocol($, session, ['dropped', '--origin', 'plugin'], JSON.stringify(report))
  if (ran.exitCode !== 0) throw new EngineError(`protocol dropped: exit ${ran.exitCode}: ${ran.stderr.trim()}`)
}

/** The skill a typed or pressed command runs as the person's conditional approval of the release (r4-q16). */
export const RELEASE_COMMAND = 'release-round'

/** A Start press on a proposed round: the skill starts the stored proposal's row (`/start-round <row>`); the press is the go-ahead, so no stamp (unlike /release-round, which is the approval). */
export const START_COMMAND = 'start-round'

/** A typed or pressed /release-round: the engine starts the release (typed ids, else the default set) or stamps the open one. */
export async function stampRelease($: $, session: string, origin: 'composer' | 'bridge' | 'press', args: string): Promise<ConsoleRound> {
  return parseRound(await protocolJson($, session, ['pass', '--origin', origin], { command: RELEASE_COMMAND, args, pending: null }))
}

/** Relays a person's chat message while a round is open (R-B9: the engine's quote check reads it). */
export async function say($: $, session: string, origin: 'composer' | 'bridge', said: string): Promise<void> {
  const ran = await protocol($, session, ['say', '--origin', origin], JSON.stringify({ text: said }))
  if (ran.exitCode !== 0) throw new EngineError(`protocol say: exit ${ran.exitCode}: ${ran.stderr.trim()}`)
}

/** `--origin`/`--session` or any prefix of them, bare or `=value`: the engine's argparse takes abbreviations, the last value winning. */
function isStampedFlag(arg: string): boolean {
  const name = arg.split('=')[0] ?? ''
  return name.length > 2 && name.startsWith('--') && (STAMPED_FLAGS.some(flag => flag.startsWith(name)))
}

const STAMPED_FLAGS: readonly string[] = ['--origin', '--session']

/** Verbs only the mod relays from person-origin events or its own observation. */
const MOD_ONLY_VERBS: readonly string[] = ['decline', 'say', 'pass', 'dropped']

/**
 * The argv the model's tool may run, or why not. The tool stamps origins itself: `answer` is
 * the chat route (`--origin chat`, checked by the engine's quote check); every other verb runs
 * `--origin model`. A caller's `--origin`/`--session` is refused (R-B11).
 */
export function toolArgv(args: readonly string[]): { argv: string[] } | { refusal: string } {
  const verb = args[0]
  if (verb === undefined || verb === '') return { refusal: 'name a verb, e.g. ["show"] or ["step"]' }
  if (args.some(isStampedFlag)) {
    return { refusal: 'the console stamps --origin and --session itself; leave them out' }
  }
  if (MOD_ONLY_VERBS.includes(verb)) return { refusal: `\`${verb}\` is relayed by the console from the person's own actions, never called by the model` }
  return { argv: [verb, '--origin', verb === 'answer' ? 'chat' : 'model', ...args.slice(1)] }
}

export async function statusLine($: $, session: string): Promise<string> {
  const ran = await protocol($, session, ['status', '--line'])
  if (ran.exitCode !== 0) throw new EngineError(`protocol status --line: exit ${ran.exitCode}: ${ran.stderr.trim()}`)
  return ran.stdout.trim()
}

// The board resolves the caller's actor from CLAUDE_CODE_SESSION_ID (board derived_actor).
async function board($: $, session: string, args: readonly string[]): Promise<Ran> {
  const homeDir = await home($)
  const ran = await $.process.run([binary(homeDir, 'board'), ...args],
    { timeoutMs: 60_000, env: { CLAUDE_CODE_SESSION_ID: session } })
  return { exitCode: ran.exitCode, stdout: ran.stdout, stderr: ran.stderr }
}

async function boardJson($: $, session: string, args: readonly string[]): Promise<unknown> {
  const ran = await board($, session, args)
  if (ran.exitCode !== 0) throw new EngineError(`board ${args.join(' ')}: exit ${ran.exitCode}: ${ran.stderr.trim()}`)
  try {
    return JSON.parse(ran.stdout)
  } catch {
    throw new EngineError(`board ${args.join(' ')}: output is not JSON`)
  }
}

/** One board item's fields for the pane's slot (`board show <id> --json`, one call); a failing or unreadable call throws. */
export async function boardItem($: $, session: string, id: string): Promise<Record<string, unknown>> {
  const fields = ['description', 'dependencies', 'issue_type', 'priority', 'assignee', 'labels', 'comment_count']
  const found = record(await boardJson($, session, ['show', id, '--json', ...fields.flatMap(field => ['--field', field])]))
  if (!(id in found)) throw new EngineError(`board show ${id}: no such item`)
  return record(found[id])
}

/** `board show <id>`: its summary, or on failure the error line (`isFailed`). */
export async function boardRead($: $, session: string, id: string): Promise<{ text: string; isFailed: boolean }> {
  const ran = await board($, session, ['show', id])
  return ran.exitCode === 0 ? { text: ran.stdout.trim(), isFailed: false } : { text: `board show ${id}: exit ${ran.exitCode}: ${ran.stderr.trim()}`, isFailed: true }
}

export async function boardShow($: $, session: string, id: string): Promise<string> {
  return (await boardRead($, session, id)).text
}

/** `board console` (counts, this session's holds, sessions from one snapshot) and this session's workers; a failing read leaves its part empty and names the error. */
export async function boardViews($: $, session: string): Promise<ConsoleBoard> {
  const errors: string[] = []
  const attempt = async <T>(read: () => Promise<T>, empty: T): Promise<T> => {
    try {
      return await read()
    } catch (error) {
      errors.push(error instanceof Error ? error.message : String(error))
      return empty
    }
  }
  const [view, agents] = await Promise.all([
    attempt(async () => record(await boardJson($, session, ['console'])), null),
    attempt(async () => (await $.agent.list()).filter(agent => agent.parentId === undefined).map(parseAgent), [] as ConsoleAgent[]),
  ])
  return {
    counts: view === null ? null : parseCounts(view.counts),
    items: view === null ? [] : list(view.items).map(parseItem),
    sessions: view === null ? [] : list(view.sessions).map(parseSession),
    held: view === null ? [] : list(view.held).map(parseHeld),
    sync: view === null ? null : nullableText(view.sync),
    queues: view === null ? null : nullableText(view.queueLine),
    agents,
    error: errors.length === 0 ? null : errors.join('; '),
  }
}

/** The registry entry (`session-lead-mode show`, its owner), or null while the session has no registered role. */
export async function readRole($: $, session: string): Promise<ConsoleRole | null> {
  const ran = await registry($, ['show', session])
  if (ran.exitCode !== 0) throw new EngineError(`session-lead-mode show: exit ${ran.exitCode}: ${ran.stderr.trim()}`)
  const raw = record(JSON.parse(ran.stdout))
  const role = text(raw.role)
  return role === '' ? null : { session, role, actor: text(raw.actor), tool: text(raw.tool) }
}

/** Sets a named session's worker count, this session's or another's (`session-lead-mode set-workers`). */
export async function setWorkers($: $, session: string, workers: string): Promise<void> {
  const ran = await registry($, ['set-workers', session, '--workers', workers])
  if (ran.exitCode !== 0) throw new EngineError(`session-lead-mode set-workers: exit ${ran.exitCode}: ${ran.stderr.trim()}`)
}

// Parsing: the engine owns the shape; a missing field reads as empty, a wrong version fails.

const record = (value: unknown): Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}
const list = (value: unknown): unknown[] => Array.isArray(value) ? value : []
const text = (value: unknown): string => typeof value === 'string' ? value : ''
const count = (value: unknown): number => typeof value === 'number' && Number.isFinite(value) ? value : 0
const nullableText = (value: unknown): string | null => typeof value === 'string' ? value : null

export function parsePending(value: unknown): ConsolePending | null {
  if (value === null || value === undefined) return null
  const raw = record(value)
  const id = text(raw.id)
  const command = text(raw.command)
  if (id === '' || command === '') throw new EngineError('pending without id or command')
  return { id, command, args: text(raw.args) }
}

function parseCounts(value: unknown): ConsoleCounts | null {
  if (value === null || value === undefined) return null
  const raw = record(value)
  return { questions: count(raw.questions), decided: count(raw.decided), toPlan: count(raw.toPlan), inReview: count(raw.inReview), forUser: count(raw.forUser) }
}

const STATUSES: readonly string[] = ['draft', 'ready', 'asked', 'answered', 'held', 'parked']

function parseQuestion(value: unknown): ConsoleQuestion {
  const raw = record(value)
  const status = text(raw.status)
  return {
    id: text(raw.id),
    board: nullableText(raw.board),
    text: text(raw.text),
    title: text(raw.title) || text(raw.text),
    kind: raw.kind === 'confirm-own-rulings' ? 'confirm-own-rulings' : 'decision',
    status: (STATUSES.includes(status) ? status : 'draft') as ConsoleQuestion['status'],
    waitsOn: list(raw.waitsOn).map(text).filter(id => id !== ''),
    settles: list(raw.settles).map(text).filter(id => id !== ''),
    overlaps: list(raw.overlaps).map(one => ({ id: text(record(one).id), title: text(record(one).title), outcome: nullableText(record(one).outcome) })).filter(one => one.id !== ''),
    answer: nullableText(raw.answer),
    answeredAt: nullableText(raw.answeredAt),
    changedBy: nullableText(raw.changedBy),
    recommendation: nullableText(raw.recommendation),
    strength: raw.strength === 'lean' || raw.strength === 'strong' ? raw.strength : null,
    leanBecause: raw.leanBecause === null || raw.leanBecause === undefined ? null
      : { cause: text(record(raw.leanBecause).cause), detail: text(record(raw.leanBecause).detail), ...(record(raw.leanBecause).flipsIf === undefined ? {} : { flipsIf: text(record(raw.leanBecause).flipsIf) }) },
    strongBecause: raw.strongBecause === null || raw.strongBecause === undefined ? null
      : Object.fromEntries(Object.entries(record(raw.strongBecause)).map(([key, value]) => [key, text(value)])),
  }
}

const RECORD_STATES: readonly string[] = ['set', 'revised', 'dropped', 'changed', 'released']

function parseRecord(value: unknown): ConsoleRecord {
  const raw = record(value)
  const state = text(raw.state)
  return { id: text(raw.id), title: text(raw.title), state: (RECORD_STATES.includes(state) ? state : 'set') as ConsoleRecord['state'], reason: nullableText(raw.reason) }
}

function parseProgress(value: unknown): ConsoleProgress | null {
  if (value === null || value === undefined) return null
  const raw = record(value)
  return {
    items: count(raw.items), points: count(raw.points), classified: count(raw.classified),
    candidates: typeof raw.candidates === 'number' ? raw.candidates : null,
    selected: list(raw.selected).map(text).filter(id => id !== ''),
  }
}

function parseNext(value: unknown): ConsoleRound['next'] {
  const raw = record(value)
  const release = record(raw.release)
  const rounds = list(raw.rounds).map((one): ConsoleProposal => {
    const proposed = record(one)
    const estimate = record(proposed.estimate)
    const titles = record(proposed.idTitles)
    const ids = list(proposed.ids).map(text).filter(id => id !== '')
    return {
      ids, idTitles: Object.fromEntries(ids.map(id => [id, text(titles[id])])), title: text(proposed.title), summary: text(proposed.summary),
      estimate: typeof estimate.questions === 'number' && typeof estimate.unblocks === 'number' ? { questions: estimate.questions, unblocks: estimate.unblocks } : null,
      why: text(proposed.why), fresh: proposed.fresh === true,
    }
  }).filter(one => one.title !== '')
  const next: NonNullable<ConsoleRound['next']> = {
    ...(count(release.count) === 0 ? {} : { release: { count: count(release.count) } }),
    ...(Array.isArray(raw.rounds) ? { rounds } : {}),
  }
  return Object.keys(next).length === 0 ? null : next
}

export function parseRound(value: unknown): ConsoleRound {
  const raw = record(value)
  if (raw.version !== CONTRACT_VERSION) throw new EngineError(`protocol show --json: version ${String(raw.version)}, the console reads ${CONTRACT_VERSION}`)
  const check = raw.check === null || raw.check === undefined ? null : record(raw.check)
  const batch = raw.batch === null || raw.batch === undefined ? null : record(raw.batch)
  return {
    version: CONTRACT_VERSION,
    session: text(raw.session),
    protocol: nullableText(raw.protocol),
    round: nullableText(raw.round),
    title: nullableText(raw.title),
    summary: nullableText(raw.summary),
    step: (nullableText(raw.step) as ConsoleRound['step']) ?? null,
    check: check === null ? null : {
      cycle: count(check.cycle),
      cap: count(check.cap),
      last: Object.fromEntries(Object.entries(record(check.last)).map(([pass, one]) => [pass, { changes: count(record(one).changes), origin: text(record(one).origin) }])),
    },
    pending: parsePending(raw.pending),
    questions: list(raw.questions).map(parseQuestion),
    batch: batch === null ? null : { marker: text(batch.marker), questions: list(batch.questions) as ConsoleDialogQuestion[], notice: text(batch.notice) },
    counts: parseCounts(raw.counts),
    progress: parseProgress(raw.progress),
    log: list(raw.log).map(one => ({ at: text(record(one).at), text: text(record(one).text) })).filter(one => one.text !== ''),
    records: list(raw.records).map(parseRecord).filter(one => one.id !== ''),
    stopped: raw.stopped === null || raw.stopped === undefined ? null
      : { run: text(record(raw.stopped).run), reason: text(record(raw.stopped).reason), ids: list(record(raw.stopped).ids).map(text).filter(id => id !== '') },
    next: parseNext(raw.next),
    isContextLarge: false,
    note: nullableText(raw.note),
    echo: nullableText(raw.echo),
  }
}

function parseItem(value: unknown): ConsoleItem {
  const raw = record(value)
  return { id: text(raw.id), type: text(raw.type), status: text(raw.status), title: text(raw.title), holder: nullableText(raw.holder) }
}

function parseHeld(value: unknown): ConsoleHeld {
  const raw = record(value)
  return { id: text(raw.id), holder: text(raw.holder), mark: raw.mark === 'idle' || raw.mark === 'gone' ? raw.mark : null }
}

function parseSession(value: unknown): ConsoleSession {
  const raw = record(value)
  const workers = raw.workers === null || raw.workers === undefined ? null : record(raw.workers)
  return {
    session: text(raw.session),
    role: text(raw.role),
    actor: text(raw.actor),
    tool: text(raw.tool),
    pulls: list(raw.pulls).map(text).filter(pull => pull !== ''),
    holds: count(raw.holds),
    workers: workers === null ? null : { active: count(workers.active), cap: count(workers.cap) },
    state: text(raw.state),
    idleSince: nullableText(raw.idleSince),
    claimable: count(raw.claimable),
  }
}

function parseAgent(value: { id: string; description: string; type: string; status: string }): ConsoleAgent {
  return { id: value.id, description: value.description, type: value.type, status: value.status }
}

/** True while a round is open: the console's round features act only then. */
export const isRoundOpen = (round: ConsoleRound | null): round is ConsoleRound & { round: string } =>
  round !== null && round.round !== null && round.step !== null && round.step !== 'closed'
