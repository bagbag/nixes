// A stand-in for what the pane may run beside the board: `code` (opens the folder the board printed) and nothing else. Any git, mktemp,
// rm or cat run is recorded in `all`, so a test can see that the pane never reads or writes git: it reads the board's JSON and presses
// board commands (r3-q14, revised).
export const CR_TREE = '/main/.worktrees/p-cr1'

export type Repo = {
  /** Every run the pane made other than `code` (argv joined); empty when it only presses board commands. */
  all: string[]
  /** Opened in VS Code. */
  opened: string[]
}

export const sha = (n: number): string => String(n).padStart(2, '0').repeat(20)

export function repo(init: Partial<Repo> = {}): Repo {
  return { all: [], opened: [], ...init }
}

/** Answers a `code` run; records every other one the fixture's `git` hook sees. */
export function git(r: Repo): (argv: string[], env?: Record<string, string>) => { exitCode: number; stdout?: string; stderr?: string } | undefined {
  return argv => {
    if (argv[0] === 'code') { r.opened.push(argv[1] as string); return { exitCode: 0, stdout: '' } }
    r.all.push(argv.join(' '))
    return undefined
  }
}
