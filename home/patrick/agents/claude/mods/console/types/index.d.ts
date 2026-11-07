// The console's state contract, and the engine/board JSON it reads (console-spec 1a,
// contract-rulings R-B2..R-B5). The engine owns those shapes; this file mirrors them.

export type ConsoleStep = 'collect' | 'select' | 'stage' | 'related' | 'check' | 'ask' | 'record' | 'closed'
  | 'recheck' | 'board-check' | 'own-rulings' | 'scoped' | 'approval' | 'owners' | 'release'
export type ConsolePassOrigin = 'plugin' | 'composer' | 'bridge' | 'press' | 'model'

/** The pending pass. */
export type ConsolePending = { id: string; command: string; args: string }

export type ConsoleOverlap = { id: string; title: string; outcome: string | null }

export type ConsoleQuestion = {
  id: string
  board: string | null
  text: string
  title: string
  kind: 'decision' | 'confirm-own-rulings'
  /** `parked`: an away round left it open and unassigned on the board for the person. */
  status: 'draft' | 'ready' | 'asked' | 'answered' | 'held' | 'parked'
  waitsOn: string[]
  /** The selected items (board ids or pasted point ids) this rule question settles with one answer; empty for a plain question. */
  settles: string[]
  overlaps: ConsoleOverlap[]
  answer: string | null
  answeredAt: string | null
  /** The pass whose most recent report changed this question; null for every other question. */
  changedBy: string | null
  recommendation: string | null
  strength: 'lean' | 'strong' | null
  leanBecause: { cause: string; detail: string; flipsIf?: string } | null
  strongBecause: Record<string, string> | null
}

export type ConsoleDialogQuestion = {
  question: string
  header: string
  multiSelect: boolean
  options: { label: string; description?: string; preview?: string }[]
}

/** The issued batch; `notice` is the engine-rendered text of its questions' parts, printed as `/console-questions` output at the lead's turn end; the console then sends the message that makes the model open the dialog (empty: nothing new to print, it sends at once). */
export type ConsoleBatch = { marker: string; questions: ConsoleDialogQuestion[]; notice: string }

export type ConsoleCounts = { questions: number; decided: number; toPlan: number; inReview: number; forUser: number }

/** Where the round stands inside its step: Collect's items, points and classes, Select's candidates, the selection. */
export type ConsoleProgress = { items: number; points: number; classified: number; candidates: number | null; selected: string[] }

/** A release run's record: still in the set, revised (kept with a corrected record text), dropped (it left the set for a round), changed (it stopped the run) or released. */
export type ConsoleRecord = { id: string; title: string; state: 'set' | 'revised' | 'dropped' | 'changed' | 'released'; reason: string | null }

/** One line of the round's recent history, in plain words; `at` is local HH:MM. */
export type ConsoleLogLine = { at: string; text: string }

/**
 * One proposed round, in the model's words: a title, a plain summary of what it decides, its estimates (questions it settles,
 * board items waiting on its answers; null in a row stored before they existed), why it ranks here, whether it reuses nothing
 * read so far (the console compacts first only when the context is large), and the question ids that must lead (often none;
 * Collect selects the rest) with the titles the engine read from the board.
 */
export type ConsoleProposal = {
  ids: string[]; idTitles: Record<string, string>; title: string; summary: string
  estimate: { questions: number; unblocks: number } | null; why: string; fresh: boolean
}

/**
 * A step the pane and the band offer: the engine's pending release, the model's proposed rounds (`isCompacting`: the Start
 * runs /compact first) or a compact-only proposal. The first is the recommended one.
 */
export type ConsoleSuggestion =
  | ({ kind: 'round'; key: string; number: number; isCompacting: boolean; isRecommended: boolean } & ConsoleProposal)  // `number`: its row in the proposal, 1-based: what /start-round takes
  | { kind: 'release'; key: string; count: number; isRecommended: boolean }
  | { kind: 'compact'; key: string; isRecommended: boolean }

/** `protocol show --json`; `round` null while no run is open (R-B3). A release run (`protocol` release) fills `records`. */
export type ConsoleRound = {
  /** The context is at or above the size at which a fresh round compacts first; a missing or failed reading counts as small. */
  isContextLarge: boolean
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
  /** What follows a close, the engine's knowledge: the release of the decided records the session holds (their count, read from the board at the last close or `protocol next`), and the model's stored proposal (`protocol next --set`). Null while a run is open or nothing waits; `rounds` is present, possibly empty, once a proposal is stored: an empty one offers only a compaction. */
  next: { release?: { count: number }; rounds?: ConsoleProposal[] } | null
  note: string | null
  /** The line the person reads after a dialog, from `answer --origin dialog`. */
  echo: string | null
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
  /** A shared board's stopped or failing sync, or its store warning, with the fix; null otherwise. */
  sync: string | null
  /** A shared board's other queues as counts, unrouted items and other people's items blocking yours; null otherwise. */
  queues: string | null
  error: string | null
}

/** The registry entry (`session-lead-mode show`). */
export type ConsoleRole = { session: string; role: string; actor: string; tool: string }

/** The machine-run pass this console started, by pending id (R-B4). `noted`: given up (stuck or stale); `stopped`: an Esc ended its turn, which a compaction may rerun. */
export type ConsolePassRun = { id: string; command: string; args: string; phase: 'queued' | 'started' | 'asked' | 'noted' | 'stopped' }

/** What a queued console action was queued for: the engine's pending pass, or an issued batch (isStale decides whether the round still holds it). */
export type ConsoleAction = { kind: 'pass'; id: string; command: string; args: string } | { kind: 'batch'; marker: string }

/** Runs a press queued that have not started yet (repeat-press guard); a prompt carries its action, re-checked where it is delivered. */
export type ConsoleQueued = { key: string; at: number; action?: ConsoleAction }[]

export type ConsoleLenses = { 'step-back': string[]; ground: string[]; focus: string }

/** The running refresh (single flight): when it started, and whether a request arrived meanwhile. */
export type ConsoleRefresh = { since: number | null; again: boolean }

/** A board item as the pane's slot shows it: the decision or description first, the facts last, the linked ids for the facts' hover. */
export type ConsoleItemSlot = { lines: string[]; facts: string; linked: string }

/** What the pane shows open inline below its row (one at a time): a board item's summary, a question's overlaps, or the items a rule question settles. */
export type ConsoleOpened =
  | { kind: 'item'; id: string; from: string | null; phase: 'reading' | 'read' | 'failed'; text: string; slot: ConsoleItemSlot | null }  // `from`: the question whose overlaps listed it; `text`: the failure
  | { kind: 'overlaps'; question: string; overlaps: { id: string; title: string }[] }
  | { kind: 'settles'; question: string; ids: string[] }
  | { kind: 'suggestion'; key: string; leads: { id: string; title: string }[] }

/** The command a compacting suggestion runs once its compaction succeeded (`title`: the proposal's, for the summary and the notice); it goes with the next compaction, typed prompt or round start. */
export type ConsoleStart = { command: string; args: string; title: string; at: number }

/** A built-in command the person sent during a turn, run when that turn ends. */
export type ConsoleDeferred = { command: string; args: string }

/** Pane lists the person expanded past their cap. */
export type ConsoleSection = 'questions' | 'held' | 'items' | 'sessions' | 'log'

declare module 'claude-code' {
  /** The console's tool, by hand: the generated snapshot (`.claude-plugin/types/claude-code-mcp`) can miss it at a save, while the mod reloads. Keep in step with the inputSchema in hooks/core.ts. */
  interface McpToolInputs {
    mcp__console__protocol: { args: string[]; stdin?: string }
  }

  interface PluginState {
    console: {
      role: Shaped<ConsoleRole | null>
      isDrawn: boolean
      round: Shaped<ConsoleRound | null>
      roundError: string | null
      /** The marker of the last batch whose text the console printed at a turn end (`/console-questions`); null before the first. */
      printed: string | null
      /** The marker of the last batch the console sent the open-the-dialog message for: one message per marker until the person sends a message; null before the first. */
      askSent: string | null
      board: Shaped<ConsoleBoard | null>
      pass: Shaped<ConsolePassRun | null>
      queued: Shaped<ConsoleQueued>
      gate: Shaped<string[]>
      lenses: Shaped<ConsoleLenses>
      expanded: Shaped<ConsoleSection[]>
      opened: Shaped<ConsoleOpened | null>
      start: Shaped<ConsoleStart | null>
      /** Built-in commands the person sent during the running turn, in order: its end runs them, ahead of anything the console starts. */
      deferred: Shaped<ConsoleDeferred[]>
      refresh: Shaped<ConsoleRefresh>
      isPaneDismissed: boolean
      /** A main-agent turn runs (turn.start until turn.complete); false while the session is idle. */
      isTurnRunning: boolean
      /** A /console-continue asked for during the running turn (a press, or typed): its end runs it, unless Esc ended it. */
      isContinueAsked: boolean
    }
  }
}
