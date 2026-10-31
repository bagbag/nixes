// The console's state contract, and the engine/board JSON it reads (console-spec 1a,
// contract-rulings R-B2..R-B5). The engine owns those shapes; this file mirrors them.

export type ConsoleStep = 'collect' | 'select' | 'stage' | 'related' | 'check' | 'ask' | 'record' | 'closed'
  | 'recheck' | 'board-check' | 'own-rulings' | 'approval' | 'owners' | 'release'
export type ConsolePassOrigin = 'plugin' | 'composer' | 'bridge' | 'press' | 'model'

export type ConsolePending = { id: string; command: string; args: string }

export type ConsoleOverlap = { id: string; title: string; outcome: string | null }

export type ConsoleQuestion = {
  id: string
  board: string | null
  text: string
  title: string
  kind: 'decision' | 'confirm-own-rulings'
  status: 'draft' | 'ready' | 'asked' | 'answered' | 'held'
  waitsOn: string[]
  overlaps: ConsoleOverlap[]
  answer: string | null
  answeredAt: string | null
  recommendation: string | null
  strength: 'lean' | 'strong' | null
  leanBecause: { cause: string; detail: string } | null
  strongBecause: Record<string, string> | null
}

export type ConsoleDialogQuestion = {
  question: string
  header: string
  multiSelect: boolean
  options: { label: string; description?: string; preview?: string }[]
}

export type ConsoleBatch = { marker: string; questions: ConsoleDialogQuestion[] }

export type ConsoleCounts = { questions: number; decided: number; toPlan: number; inReview: number; forUser: number }

/** Where the round stands inside its step: Collect's items, points and classes, Select's candidates, the selection. */
export type ConsoleProgress = { items: number; points: number; classified: number; candidates: number | null; selected: string[] }

/** A release run's record: still in the set, dropped (it left the set for a round), changed (it stopped the run) or released. */
export type ConsoleRecord = { id: string; title: string; state: 'set' | 'dropped' | 'changed' | 'released'; reason: string | null }

/** One line of the round's recent history, in plain words; `at` is local HH:MM. */
export type ConsoleLogLine = { at: string; text: string }

/** `protocol show --json`; `round` null while no run is open (R-B3). A release run (`protocol` release) fills `records`. */
export type ConsoleRound = {
  version: number
  session: string
  protocol: string | null
  round: string | null
  title: string | null
  summary: string | null
  step: ConsoleStep | null
  check: {
    cycle: number
    cap: number
    last: Record<string, { changes: number; origin: string }>
  } | null
  pending: ConsolePending | null
  questions: ConsoleQuestion[]
  batch: ConsoleBatch | null
  counts: ConsoleCounts | null
  progress: ConsoleProgress | null
  log: ConsoleLogLine[]
  records: ConsoleRecord[]
  /** The last release, when it stopped: shown while no run is open, its records wait for a round. */
  stopped: { run: string; reason: string; ids: string[] } | null
  note: string | null
}

export type ConsoleItem = { id: string; type: string; status: string; title: string; holder: string | null }

export type ConsoleSession = {
  session: string
  role: string
  actor: string
  tool: string
  pulls: string[]
  holds: number
  workers: { active: number; cap: number } | null
  state: string
  idleSince: string | null
  claimable: number
}

export type ConsoleAgent = { id: string; description: string; type: string; status: string }

/** A hold on the board: its holder (actor, or actor/worker) and the board's idle or gone mark. */
export type ConsoleHeld = { id: string; holder: string; mark: 'idle' | 'gone' | null }

/** `board console` and this session's workers. */
export type ConsoleBoard = {
  counts: ConsoleCounts | null
  items: ConsoleItem[]
  sessions: ConsoleSession[]
  held: ConsoleHeld[]
  agents: ConsoleAgent[]
  error: string | null
}

/** The registry entry (`session-lead-mode show`). */
export type ConsoleRole = { session: string; role: string; actor: string; tool: string }

/** The machine-run pass this console started, by pending id (R-B4). */
export type ConsolePassRun = { id: string; command: string; phase: 'queued' | 'started' | 'noted' }

/** Runs a press queued that have not started yet (repeat-press guard). */
export type ConsoleQueued = { key: string; at: number }[]

export type ConsoleLenses = { 'step-back': string[]; ground: string[]; focus: string }

/** The running refresh (single flight): when it started, and whether a request arrived meanwhile. */
export type ConsoleRefresh = { since: number | null; again: boolean }

/** Pane lists the person expanded past their cap. */
export type ConsoleSection = 'questions' | 'held' | 'items' | 'sessions'

declare module 'claude-code' {
  interface PluginState {
    console: {
      role: Shaped<ConsoleRole | null>
      isDrawn: boolean
      round: Shaped<ConsoleRound | null>
      roundError: string | null
      board: Shaped<ConsoleBoard | null>
      pass: Shaped<ConsolePassRun | null>
      queued: Shaped<ConsoleQueued>
      gate: Shaped<string[]>
      lenses: Shaped<ConsoleLenses>
      expanded: Shaped<ConsoleSection[]>
      refresh: Shaped<ConsoleRefresh>
      isPaneDismissed: boolean
    }
  }
}
