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

/** `board console` counts (r21-q141, q146): ready now, and the k waiting. */
export const COUNTS = {
  questions: { ready: 186, held: 2, waiting: 0 }, decided: { ready: 0, held: 0, waiting: 0 }, toPlan: { ready: 0, held: 0, waiting: 57 },
  toReview: { ready: 0, held: 0, waiting: 0 }, toAccept: { ready: 13, held: 0, waiting: 1 }, toRatify: { ready: 1, held: 0, waiting: 0 }, forUser: { ready: 3, held: 0, waiting: 0 },
}

/** `board console` counts: the round's, plus the agent steps the board adds. */
export const BOARD_COUNTS = { ...COUNTS, toDesign: { ready: 6, held: 1, waiting: 0 }, toImplement: { ready: 90, held: 1, waiting: 1 } }

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
    counts: COUNTS,
    note: null,
    ...overrides,
  }
}

/** What the stand-in engine answers as the line after a dialog: the console prints the engine's line, whatever it says. */
export const engineLine = (answers: readonly string[]): string => `Engine line: ${answers.join(', ')}`

export const NO_ROUND = roundJson({ round: null, step: null, check: null, pending: null, batch: null, questions: [] })

export type World = {
  round: Record<string, unknown>
  role: Record<string, unknown> | null
  surfaces: string[]
  calls: { argv: string[]; stdin: string | undefined; env: Record<string, string> | undefined; timeoutMs: number | undefined }[]
  commands: { command: string; args: string }[]
  /** Per prompt: submitted as the person's own words, without the host's plugin frame. */
  asUser: boolean[]
  prompts: string[]
  opened: string[]
  /** Ids of the rows `$.ui.place` was given. */
  placed: string[]
  /** Whether a surface draws a placed row; false answers `isPlaced: false`. */
  isPlacing: boolean
  tools: { name: string; isDeferred: unknown }[]
  /** Command names the console registered. */
  registered: string[]
  toasts: string[]
  notified: string[]
  views: unknown[]
  files: Map<string, string>
  sessions: unknown[]
  activateError: string | undefined
  items: unknown[]
  /** `board console` `forYou`: the ready items assigned to the user. */
  forYou: unknown[]
  held: unknown[]
  /** `board console` `crs` and `ratifications` (Front B's shape, tests/board-console-contract.ts). */
  crs: unknown[]
  /** `board console` `queued`: the requests waiting for an agent, counted not listed. */
  queued: number
  /** `board console` `waitingOnYou`: the queued requests whose unit waits on a decision of the person. */
  waitingOnYou: number
  /** `board console` `prefix`: the board's own id prefix, which the pane leaves off. */
  prefix: string | null
  /** `board console` `noBoard`: the directory has no board. */
  noBoard: boolean
  ratifications: unknown[]
  agents: { id: string; description: string; type: string; status: string }[]
  sync?: string | null
  queueLine?: string | null
  protocolExit: number
  /** A `protocol` run that rejects with this message (the host's time limit); null: it runs. */
  protocolThrows: string | null
  /** `protocol` verbs whose next run fails, one failure per entry (Esc aborting the dialog hook's save). */
  failVerbs: string[]
  /** The reason `$.prompt.submit` drops a prompt with (the console's sends fail); null: it goes through. */
  promptError: string | null
  /** The size $.session.usage() reports; undefined until a response, 'fails' for a read that throws. */
  tokens: number | undefined | 'fails'
  /** `board show --json`'s fields for any id, or an exit code to fail with (`bad`: print text that is no JSON). */
  show: { record: Record<string, unknown>; exit: number; bad: boolean }
  /** Called after the stand-in engine answered each verb: a test moves the round on from here, as a queued action's delay does. */
  onVerb: ((verb: string) => void) | null
  /** A `protocol` verb whose runs answer only once `until` settles: a slow engine call. */
  hold: { verb: string; until: Promise<void> } | null
  /** The line `protocol scope` answers (r9-q36): what a report of the pass starting now must cover; '' names nothing. */
  scope: string
  verbs: () => string[]
  /** The prompt box's draft; `$.prompt.fill` writes into it as `fill` says (`isFilled: false` while `hasBox` is false). */
  box: string
  hasBox: boolean
  /** Answers a `git`, `code`, `sh` or `cat` run (argv as given); null/undefined: not git's concern, exit 127. */
  git: ((argv: string[]) => { exitCode: number; stdout?: string; stderr?: string } | undefined) | null
}

/** Registers the world's hooks beneath the console; returns it, the clock and the session record. */
export function world(on: On, init: Partial<Pick<World, 'round' | 'role' | 'surfaces' | 'sessions' | 'items' | 'forYou' | 'held' | 'crs' | 'queued' | 'waitingOnYou' | 'prefix' | 'noBoard' | 'ratifications' | 'agents' | 'sync' | 'queueLine' | 'activateError'>> = {}) {
  const w: World = {
    round: init.round ?? roundJson(),
    role: init.role === undefined ? { session: SESSION, role: 'lead', actor: '617adf08', tool: 'claude' } : init.role,
    surfaces: init.surfaces ?? ['terminal'],
    activateError: init.activateError,
    calls: [], commands: [], prompts: [], asUser: [], opened: [], placed: [], isPlacing: true, tools: [], registered: [], toasts: [], notified: [], views: [],
    files: new Map(),
    sessions: init.sessions ?? [
      { session: SESSION, role: 'lead', actor: '617adf08', pulls: [], holds: 2, workers: null, state: 'active', idleSince: null, claimable: 0 },
    ],
    items: init.items ?? [{ id: 'tstdl-x1', type: 'decision', status: 'in_progress', title: 'Which engine name?', holder: '617adf08' }],
    forYou: init.forYou ?? [],
    held: init.held ?? [],
    crs: init.crs ?? [],
    queued: init.queued ?? 0,
    waitingOnYou: init.waitingOnYou ?? 0,
    prefix: init.prefix ?? null,
    noBoard: init.noBoard ?? false,
    ratifications: init.ratifications ?? [],
    sync: init.sync,
    queueLine: init.queueLine,
    agents: init.agents ?? [],
    protocolExit: 0,
    protocolThrows: null,
    failVerbs: [],
    promptError: null,
    tokens: 500_000,
    show: { record: { description: '## Decision\nKeep it.', dependencies: [], issue_type: 'decision', priority: 1, assignee: null, labels: [], comment_count: 0 }, exit: 0, bad: false },
    onVerb: null,
    hold: null,
    scope: '',
    box: '',
    hasBox: true,
    git: null,
    verbs: () => w.calls.filter(one => one.argv[0] === PROTOCOL).map(one => one.argv.slice(3).join(' ')),
  }
  const clock = mock.clock(on, { now: 1_000_000 })
  const session = mock.session(on)
  mock.env(on, { HOME })

  on('session.cwd', () => ({ value: '/repo' }))
  on('prompt.read', () => ({ value: { text: w.box, cursor: w.box.length } }))
  on('prompt.fill', (_, e) => {
    if (!w.hasBox) return { isFilled: false, refusal: 'no_composer' as const }
    w.box = e.mode === 'append' ? w.box + e.text : e.text
    return { isFilled: true }
  })
  on('session.id', () => ({ value: SESSION }))
  on('session.usage', () => {
    if (w.tokens === 'fails') throw new Error('no usage')
    return { value: { startedAt: 0, context: { ...(w.tokens === undefined ? {} : { tokens: w.tokens }), window: 1_000_000 }, rateLimits: {}, cost: { usd: 0 } } as never }
  })
  on('session.surfaces', () => ({ value: w.surfaces as never }))
  on('fs.exists', (_, e) => ({ value: w.files.has(e.path) || [...w.files.keys()].some(path => path.startsWith(`${e.path}/`)) }))
  on('fs.list', (_, e) => ({ value: [...w.files.keys()].filter(path => path.startsWith(`${e.path}/`) && !path.slice(e.path.length + 1).includes('/')).map(path => ({ name: path.slice(e.path.length + 1), kind: 'file', size: 0, mtimeMs: 0, isLink: false })) as never }))
  on('fs.read', (_, e) => ({ value: w.files.get(e.path) ?? '' }))
  on('fs.write', (_, e) => { w.files.set(e.path, e.text); return { value: undefined } })
  on('agent.list', () => ({ value: w.agents as never }))
  on('command.register', (_, e) => { w.registered.push(e.name); return { value: { command: e.name } } })
  on('command.list', () => ({ value: [{ name: 'compact', description: '', source: 'builtin' }, { name: 'step-back', description: '', source: 'user' }] as never }))
  on('tool.register', (_, e) => { w.tools.push({ name: e.name, isDeferred: e.isDeferred }); return { value: { tool: `mcp__console__${e.name}` } } })
  on('ui.open', (_, e) => { w.opened.push(e.id); return { value: { isPlaced: true } } })
  on('ui.place', (_, e) => { w.placed.push(e.id); return { value: { isPlaced: w.isPlacing, requestId: 'row' } as never } })
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
    w.asUser.push((e.origin as { asUser?: boolean }).asUser === true)
    return { text: e.text } as never
  })

  on('process.run', (_, e) => {
    const argv = [...e.argv]
    w.calls.push({ argv, stdin: e.init?.stdin, env: e.init?.env, timeoutMs: e.init?.timeoutMs })
    const ok = (out: unknown) => ({ value: { exitCode: 0, stdout: typeof out === 'string' ? out : JSON.stringify(out), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
    // The registry script has no execute bit: only `bash <script>` runs it, as on the machine.
    if (argv[0] === REGISTRY) return { value: { exitCode: 126, stdout: '', stderr: 'Permission denied', isStdoutTruncated: false, isStderrTruncated: false } }
    if (argv[0] === 'bash' && argv[1] === REGISTRY && argv[2] === 'set-workers' && w.activateError !== undefined) return { value: { exitCode: 2, stdout: '', stderr: w.activateError, isStdoutTruncated: false, isStderrTruncated: false } }
    if (argv[0] === 'rm' && argv[1] === '-f') { for (const path of argv.slice(2)) w.files.delete(path); return ok('') }
    if (argv[0] === 'bash' && argv[1] === REGISTRY && argv[2] === 'state-dir') return ok(`${HOME}/.local/state/agent-sessions\n`)
    if (argv[0] === 'bash' && argv[1] === REGISTRY) return ok({ role: null, ...(w.role ?? {}), session: argv[3] })
    if (argv[0] === PROTOCOL) {
      if (w.protocolThrows !== null) return { deny: w.protocolThrows } as never
      const served = (() => {
        if (w.protocolExit !== 0) return { value: { exitCode: w.protocolExit, stdout: '', stderr: 'engine down', isStdoutTruncated: false, isStderrTruncated: false } }
        const verb = argv[3]
        if (w.failVerbs.includes(verb as string)) {
          w.failVerbs.splice(w.failVerbs.indexOf(verb as string), 1)
          return { value: { exitCode: 1, stdout: '', stderr: 'aborted', isStdoutTruncated: false, isStderrTruncated: false } }
        }
        if (verb === 'pending') return ok(w.round.pending ?? null)
        if (verb === 'status') return ok('round r4 · check 2/3 · next ground')
        if (verb === 'show' && argv[4] !== '--json') return ok('# round r4')
        if (verb === 'say' || verb === 'dropped' || verb === 'nudged') return ok('')
        if (verb === 'scope') return ok({ covers: [], explored: null, text: w.scope })
        if (verb === 'answer') return ok({ ...w.round, echo: engineLine(Object.values(JSON.parse(e.init?.stdin ?? '{}').answers ?? {}) as string[]) })
        return ok(w.round)
      })()
      w.onVerb?.(argv[3] as string)
      const hold = w.hold
      return hold !== null && hold.verb === argv[3] ? hold.until.then(() => served) : served
    }
    if (w.git !== null && ['git', 'code', 'sh', 'cat'].includes(argv[0] as string)) {
      const answered = w.git(argv)
      if (answered !== undefined) return { value: { exitCode: answered.exitCode, stdout: answered.stdout ?? '', stderr: answered.stderr ?? '', isStdoutTruncated: false, isStderrTruncated: false } }
    }
    if (argv[0] === BOARD) {
      if (argv[1] === 'console') return ok({ noBoard: w.noBoard, counts: w.noBoard ? null : BOARD_COUNTS, forYou: w.forYou, items: w.items, sessions: w.sessions, held: w.held, crs: w.crs, queued: w.queued, waitingOnYou: w.waitingOnYou, prefix: w.prefix, ratifications: w.ratifications, sync: w.sync, queueLine: w.queueLine })
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
