// The world beneath the console in tests: a stub `protocol` and `board` behind $.process.run
// (the kit has no processes), the registry behind $.fs, and the session's nouns. Shapes follow
// console-spec 1a and contract-rulings R-B2..R-B5; the registry answers as `session-lead-mode show`.
import { mock } from 'claude-code/testing'
import type { On } from 'claude-code'

export const SESSION = 's-1'
export const HOME = '/home/test'
export const PROTOCOL = `${HOME}/.agents/bin/protocol`
export const BOARD = `${HOME}/.agents/bin/board`
export const REGISTRY = `${HOME}/.agents/bin/session-lead-mode`

export const BATCH = {
  marker: 'round:r4:2',
  questions: [
    { question: 'Which engine name?', header: 'Engine', multiSelect: false, options: [{ label: 'protocol', description: 'The engine CLI' }, { label: 'flow', description: 'Shorter' }] },
  ],
}

export type Question = { id: string; text: string; title: string; status: string; waitsOn?: string[]; overlaps?: { id: string; outcome: string | null }[] }

export function roundJson(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    version: 1, session: SESSION, protocol: 'round', round: 'r4', step: 'check',
    check: { cycle: 2, cap: 3, last: { 'step-back': { changes: 2, origin: 'plugin' }, ground: { changes: 0, origin: 'plugin' } } },
    pending: null,
    questions: [
      { id: 'q1', board: null, text: 'Pass cap per round?', title: 'Pass cap', kind: 'decision', status: 'answered', waitsOn: [], overlaps: [], answer: '3 cycles' },
      { id: 'q2', board: 'tstdl-x1', text: 'Which engine name?', title: 'Engine name', kind: 'decision', status: 'asked', waitsOn: [], overlaps: [{ id: 'tstdl-ab12', outcome: null }], answer: null },
      { id: 'q3', board: null, text: 'Which pane layout?', title: 'Pane layout', kind: 'decision', status: 'ready', waitsOn: [], overlaps: [], answer: null },
    ],
    batch: BATCH, next: null,
    counts: { questions: 188, decided: 0, toPlan: 82, inReview: 14, forUser: 3 },
    note: null,
    ...overrides,
  }
}

export const NO_ROUND = roundJson({ round: null, step: null, check: null, pending: null, batch: null, questions: [] })

export type World = {
  round: Record<string, unknown>
  role: Record<string, unknown> | null
  surfaces: string[]
  calls: { argv: string[]; stdin: string | undefined; env: Record<string, string> | undefined }[]
  commands: { command: string; args: string }[]
  prompts: string[]
  opened: string[]
  tools: { name: string; isDeferred: unknown }[]
  toasts: string[]
  notified: string[]
  views: unknown[]
  files: Map<string, string>
  sessions: unknown[]
  activateError: string | undefined
  items: unknown[]
  held: unknown[]
  agents: { id: string; description: string; type: string; status: string }[]
  protocolExit: number
  /** The reason `$.prompt.submit` drops a prompt with (the console's sends fail); null: it goes through. */
  promptError: string | null
  /** The size $.session.usage() reports; undefined until a response, 'fails' for a read that throws. */
  tokens: number | undefined | 'fails'
  /** `board show --json`'s fields for any id, or an exit code to fail with (`bad`: print text that is no JSON). */
  show: { record: Record<string, unknown>; exit: number; bad: boolean }
  verbs: () => string[]
}

/** Registers the world's hooks beneath the console; returns it, the clock and the session record. */
export function world(on: On, init: Partial<Pick<World, 'round' | 'role' | 'surfaces' | 'sessions' | 'items' | 'held' | 'agents' | 'activateError'>> = {}) {
  const w: World = {
    round: init.round ?? roundJson(),
    role: init.role === undefined ? { session: SESSION, role: 'lead', actor: '617adf08', tool: 'claude' } : init.role,
    surfaces: init.surfaces ?? ['terminal'],
    activateError: init.activateError,
    calls: [], commands: [], prompts: [], opened: [], tools: [], toasts: [], notified: [], views: [],
    files: new Map(),
    sessions: init.sessions ?? [
      { session: SESSION, role: 'lead', actor: '617adf08', pulls: [], holds: 2, workers: null, state: 'active', idleSince: null, claimable: 0 },
    ],
    items: init.items ?? [{ id: 'tstdl-x1', type: 'decision', status: 'in_progress', title: 'Which engine name?', holder: '617adf08' }],
    held: init.held ?? [],
    agents: init.agents ?? [],
    protocolExit: 0,
    promptError: null,
    tokens: 500_000,
    show: { record: { description: '## Decision\nKeep it.', dependencies: [], issue_type: 'decision', priority: 1, assignee: null, labels: [], comment_count: 0 }, exit: 0, bad: false },
    verbs: () => w.calls.filter(one => one.argv[0] === PROTOCOL).map(one => one.argv.slice(3).join(' ')),
  }
  const clock = mock.clock(on, { now: 1_000_000 })
  const session = mock.session(on)
  mock.env(on, { HOME })

  on('session.id', () => ({ value: SESSION }))
  on('session.usage', () => {
    if (w.tokens === 'fails') throw new Error('no usage')
    return { value: { startedAt: 0, context: { ...(w.tokens === undefined ? {} : { tokens: w.tokens }), window: 1_000_000 }, rateLimits: {}, cost: { usd: 0 } } as never }
  })
  on('session.surfaces', () => ({ value: w.surfaces as never }))
  on('fs.exists', (_, e) => ({ value: w.files.has(e.path) }))
  on('fs.read', (_, e) => ({ value: w.files.get(e.path) ?? '' }))
  on('fs.write', (_, e) => { w.files.set(e.path, e.text); return { value: undefined } })
  on('agent.list', () => ({ value: w.agents as never }))
  on('command.register', (_, e) => ({ value: { command: e.name } }))
  on('tool.register', (_, e) => { w.tools.push({ name: e.name, isDeferred: e.isDeferred }); return { value: { tool: `mcp__console__${e.name}` } } })
  on('ui.open', (_, e) => { w.opened.push(e.id); return { value: { isPlaced: true } } })
  on('ui.toast', (_, e) => { w.toasts.push(e.text); return { value: undefined } })
  on('ui.notify', (_, e) => { w.notified.push(e.text); return { value: { isSent: true, channel: 'iterm2' } } })
  on('ui.view', (_, e) => { w.views.push(e); return { value: {} } })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.attach', () => ({ clientId: 'c1' }))
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', (_, e) => ({ text: e.answer }))
  on('skill.prompt', (_, e) => ({ text: e.text }))
  on('command.run', (_, e) => { w.commands.push({ command: e.command, args: e.args }); return { text: '' } })
  on('prompt.submit', (_, e) => {
    if (w.promptError !== null) return { drop: w.promptError } as never
    w.prompts.push(e.text)
    return { text: e.text } as never
  })

  on('process.run', (_, e) => {
    const argv = [...e.argv]
    w.calls.push({ argv, stdin: e.init?.stdin, env: e.init?.env })
    const ok = (out: unknown) => ({ value: { exitCode: 0, stdout: typeof out === 'string' ? out : JSON.stringify(out), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
    // The registry script has no execute bit: only `bash <script>` runs it, as on the machine.
    if (argv[0] === REGISTRY) return { value: { exitCode: 126, stdout: '', stderr: 'Permission denied', isStdoutTruncated: false, isStderrTruncated: false } }
    if (argv[0] === 'bash' && argv[1] === REGISTRY && argv[2] === 'set-workers' && w.activateError !== undefined) return { value: { exitCode: 2, stdout: '', stderr: w.activateError, isStdoutTruncated: false, isStderrTruncated: false } }
    if (argv[0] === 'bash' && argv[1] === REGISTRY && argv[2] === 'state-dir') return ok(`${HOME}/.local/state/agent-sessions\n`)
    if (argv[0] === 'bash' && argv[1] === REGISTRY) return ok({ role: null, ...(w.role ?? {}), session: argv[3] })
    if (argv[0] === PROTOCOL) {
      if (w.protocolExit !== 0) return { value: { exitCode: w.protocolExit, stdout: '', stderr: 'engine down', isStdoutTruncated: false, isStderrTruncated: false } }
      const verb = argv[3]
      if (verb === 'pending') return ok(w.round.pending ?? null)
      if (verb === 'status') return ok('round r4 · check 2/3 · next ground')
      if (verb === 'show' && argv[4] !== '--json') return ok('# round r4')
      if (verb === 'say') return ok('')
      return ok(w.round)
    }
    if (argv[0] === BOARD) {
      if (argv[1] === 'console') return ok({ counts: { questions: 188, decided: 0, toPlan: 82, inReview: 14, forUser: 3 }, items: w.items, sessions: w.sessions, held: w.held })
      if (argv[1] === 'show' && w.show.exit !== 0) return { value: { exitCode: w.show.exit, stdout: '', stderr: 'no such item', isStdoutTruncated: false, isStderrTruncated: false } }
      if (argv[1] === 'show' && argv.includes('--json')) return ok(w.show.bad ? 'not json' : { [argv[2] as string]: w.show.record })
      if (argv[1] === 'show') return ok(`${argv[2]}: Which engine name?\nstatus: in_progress`)
    }
    return { value: { exitCode: 127, stdout: '', stderr: `unknown ${argv[0]}`, isStdoutTruncated: false, isStderrTruncated: false } }
  })

  return { w, clock, session }
}

/** Notices the console appended (the person sees them; the model does not). */
export const notices = (session: ReturnType<typeof mock.session>): string[] =>
  session.appended().filter(row => row.message.type === 'system').map(row => JSON.stringify(row.message.content))

/** Notes the model reads (user rows the console appended). */
export const notes = (session: ReturnType<typeof mock.session>): string[] =>
  session.appended().filter(row => row.message.type === 'user').map(row => JSON.stringify(row.message.content))

export const PANE_PROPS = {
  title: 'Console', isFocused: false, bodyColumns: 90, placement: 'dock' as const,
  scroll: { offset: 0, bodyRows: 60 }, view: {},
}
