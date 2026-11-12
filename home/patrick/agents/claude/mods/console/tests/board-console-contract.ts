// `board console` `crs` / `ratifications` / `toRatify`, to the spec of build-r24-r25-plan.md Front B ("JSON for the console").
// Each key here must exist in the board's real row (bin/test-agent-configs.py checks it); the contract test pins
// every field the console reads.
export const sha = (n: number): string => String(n).padStart(2, '0').repeat(20)

type CrInit = Partial<Record<string, unknown>> & { id: string }

/** One `crs` entry in the spec's shape; `over` replaces fields. */
export function cr(over: CrInit): Record<string, unknown> {
  return {
    title: `Title of ${over.id}`, status: 'needs_acceptance', holder: null, look: 'before', view: 'code', checkpoint: null,
    base: 'main', branch: `cr/${over.id}`, worktree: `/main/.worktrees/${over.id}`, tip: sha(2), baseTip: sha(1),
    check: { state: 'current', tip: sha(2), baseTip: sha(1), at: '2026-11-11T09:00:00Z', result: 'pass', newFailures: [], baseCount: 3012, tipCount: 2972 },
    parent: null, children: [], unblocks: 0, unblocksDirect: 0, milestone: null,
    reviewState: 'current', refreshWork: false, landBlocked: null, after: null, returned: false, setupFailed: false,
    ...over,
  }
}

export const BOARD_CONSOLE_CONTRACT = {
  counts: {
    questions: { ready: 0, held: 0, waiting: 0 }, decided: { ready: 0, held: 0, waiting: 0 }, toPlan: { ready: 0, held: 0, waiting: 0 },
    toReview: { ready: 2, held: 0, waiting: 0 }, toAccept: { ready: 1, held: 0, waiting: 1 }, toRatify: { ready: 1, held: 0, waiting: 0 }, forUser: { ready: 0, held: 0, waiting: 0 },
  },
  crs: [
    cr({ id: 'p-cr1', title: 'Remove the legacy cache', children: ['p-cr2'], unblocks: 14, unblocksDirect: 7, milestone: '1.0-beta scope' }),
    cr({
      id: 'p-cr2', title: 'Drop the cache config', status: 'in_review', holder: 'a1b2', base: 'p-cr1', parent: 'p-cr1', branch: 'cr/p-cr2', tip: sha(4), baseTip: sha(2),
      look: 'after', view: 'result', checkpoint: 'agent', check: { state: 'stale', tip: sha(4), baseTip: sha(1), at: '2026-11-11T09:30:00Z', result: 'fail', newFailures: ['src/a.ts TS2322', 'src/b.ts TS2345'], baseCount: 3012, tipCount: 3014 },
    }),
  ],
  ratifications: [{ id: 'p-rat1', cr: 'p-cr0', title: 'Ratify: Move the clock' }],
} as const
