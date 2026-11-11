// A stand-in git for the review tree: the main worktree `/main` (and one change-request worktree), answering the commands
// hooks/review.ts issues from mutable state, and recording every one so a test can see what the console never runs. The real git is
// probed separately (the mod's tests spawn no processes).
export const MAIN_TREE = '/main'
export const REVIEW_TREE = '/main-review'
export const CR_TREE = '/main-worktrees/p-cr1'
export const REVIEW_END_REF = 'refs/worktree/console-review-end'

export type Repo = {
  /** The fork point `git merge-base` answers; null: the commits share no base. */
  fork: string | null
  /** Shas `rev-parse --verify` does not know. */
  unknown: string[]
  hasReviewTree: boolean
  /** The review tree has edits of yours (a modified tracked file) or an untracked file. */
  hasEdits: boolean
  hasUntracked: boolean
  /** Root-level *.code-workspace files of the review tree. */
  workspaces: string[]
  /** Every git argv, as `<cwd> <args>`. */
  all: string[]
  /** The ones that change something. */
  changes: string[]
  /** Opened in VS Code. */
  opened: string[]
}

export const sha = (n: number): string => String(n).padStart(2, '0').repeat(20)

export function repo(init: Partial<Repo> = {}): Repo {
  return { fork: sha(1), unknown: [], hasReviewTree: false, hasEdits: false, hasUntracked: false, workspaces: [], all: [], changes: [], opened: [], ...init }
}

const done = (stdout = '') => ({ exitCode: 0, stdout })
const fail = (stderr = 'failed', exitCode = 1) => ({ exitCode, stdout: '', stderr })

/** Answers a git or code run; the fixture's `git` hook. */
export function git(r: Repo): (argv: string[]) => { exitCode: number; stdout?: string; stderr?: string } | undefined {
  return argv => {
    if (argv[0] === 'code') { r.opened.push(argv[1] as string); return done() }
    if (argv[0] !== 'git' || argv[1] !== '-C') return undefined
    const cwd = argv[2] as string
    const [verb = '', ...args] = argv.slice(3)
    const line = args.join(' ')
    r.all.push(`${cwd} ${verb} ${line}`.trim())
    const mutate = () => r.changes.push(`${cwd} ${verb} ${line}`)
    switch (verb) {
      case 'worktree':
        if (args[0] === 'list') {
          return done([
            `worktree ${MAIN_TREE}\nHEAD ${sha(1)}\nbranch refs/heads/main`,
            `worktree ${CR_TREE}\nHEAD ${sha(2)}\nbranch refs/heads/cr/p-cr1`,
            ...(r.hasReviewTree ? [`worktree ${REVIEW_TREE}\nHEAD ${sha(1)}\ndetached`] : []),
          ].join('\n\n') + '\n')
        }
        if (args[0] === 'add') { mutate(); r.hasReviewTree = true; return done() }
        break
      case 'rev-parse': {
        if (line === `-q --verify ${REVIEW_END_REF}`) return r.hasReviewTree ? done(`${sha(2)}\n`) : fail()
        const verified = /^--verify -q (\w+)\^\{commit\}$/.exec(line)
        if (verified !== null) return r.unknown.includes(verified[1] as string) ? fail('', 1) : done(`${verified[1]}\n`)
        break
      }
      case 'merge-base': return r.fork === null ? fail('', 1) : done(`${r.fork}\n`)
      case 'diff': return r.hasEdits ? fail('', 1) : done()
      case 'ls-files':
        if (args.includes('--others')) return done(r.hasUntracked ? 'mine.txt\n' : '')
        return done(r.workspaces.map(file => `${file}\n`).join(''))
      case 'reset': mutate(); return done()
      case 'update-ref': mutate(); return done()
      default: mutate()  // anything else would change something: the tests assert nothing else runs
    }
    return undefined
  }
}
