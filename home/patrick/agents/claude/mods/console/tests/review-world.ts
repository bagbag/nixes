// A stand-in git for the review tree: the main worktree `/main` (and one change-request worktree), answering the commands
// hooks/review.ts issues from mutable state, and recording every one so a test can see what the console never runs. The real git is
// probed separately (the mod's tests spawn no processes; bin/test-agent-configs.py runs review.ts's clean check on real git against
// the board's snapshot).
export const MAIN_TREE = '/main'
export const REVIEW_TREE = '/main-review'
export const CR_TREE = '/main/.worktrees/p-cr1'
export const REVIEW_END_REF = 'refs/worktree/console-review-end'

export type Repo = {
  /** The fork point `git merge-base` answers; null: the commits share no base. */
  fork: string | null
  /** Shas `rev-parse --verify` does not know. */
  unknown: string[]
  hasReviewTree: boolean
  /** The review tree has edits of yours (a modified tracked file) or an untracked file; a `reset --hard` drops them. */
  hasEdits: boolean
  hasUntracked: boolean
  /** The review tree's marker (`update-ref` moves it): the tip it was set to, or the commit the board made of its files. */
  end: string
  /** The commit whose tree is exactly the edited files (`board cr edits --commit` made it); null: none. */
  editsAt: string | null
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
  return { fork: sha(1), unknown: [], hasReviewTree: false, hasEdits: false, hasUntracked: false, end: sha(2), editsAt: null, workspaces: [], all: [], changes: [], opened: [], ...init }
}

const done = (stdout = '') => ({ exitCode: 0, stdout })
const fail = (stderr = 'failed', exitCode = 1) => ({ exitCode, stdout: '', stderr })

/** Where `mktemp -d` puts the clean check's throwaway index. */
export const SNAPSHOT_DIR = '/tmp/console-snapshot'
/** A tree id: the edited files' own, or a commit's. */
const treeOf = (r: Repo, commit: string): string => commit === r.editsAt ? 'tree-edited' : `tree-${commit}`

/** Answers a git, code, mktemp or rm run; the fixture's `git` hook. A snapshot step without the throwaway index counts as a change. */
export function git(r: Repo): (argv: string[], env?: Record<string, string>) => { exitCode: number; stdout?: string; stderr?: string } | undefined {
  let readTree = 'HEAD'
  return (argv, env) => {
    if (argv[0] === 'code') { r.opened.push(argv[1] as string); return done() }
    if (argv[0] === 'mktemp') { r.all.push(argv.join(' ')); return done(`${SNAPSHOT_DIR}\n`) }
    if (argv[0] === 'rm') { r.all.push(argv.join(' ')); return argv.join(' ') === `rm -rf ${SNAPSHOT_DIR}` ? done() : (r.changes.push(argv.join(' ')), done()) }
    if (argv[0] !== 'git' || argv[1] !== '-C') return undefined
    const cwd = argv[2] as string
    const [verb = '', ...args] = argv.slice(3)
    const line = args.join(' ')
    r.all.push(`${cwd} ${verb} ${line}`.trim())
    const mutate = () => r.changes.push(`${cwd} ${verb} ${line}`)
    const isThrowaway = env?.GIT_INDEX_FILE === `${SNAPSHOT_DIR}/index`
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
        if (line === `-q --verify ${REVIEW_END_REF}^{commit}`) return r.hasReviewTree ? done(`${r.end}\n`) : fail()
        if (line === 'HEAD') return done(`${sha(1)}\n`)
        const tree = /^--verify (\w+)\^\{tree\}$/.exec(line)
        if (tree !== null) return done(`${treeOf(r, tree[1] as string)}\n`)
        const verified = /^--verify -q (\w+)\^\{commit\}$/.exec(line)
        if (verified !== null) return r.unknown.includes(verified[1] as string) ? fail('', 1) : done(`${verified[1]}\n`)
        break
      }
      case 'merge-base': return r.fork === null ? fail('', 1) : done(`${r.fork}\n`)
      // The clean check: the tree's files written as a tree in the throwaway index, never the tree's own.
      case 'read-tree': if (!isThrowaway) mutate(); readTree = args[0] as string; return done()
      case 'add': if (!isThrowaway) mutate(); return done()
      case 'write-tree': if (!isThrowaway) mutate(); return done(`${r.hasEdits || r.hasUntracked ? 'tree-edited' : treeOf(r, readTree)}\n`)
      case 'ls-files':
        if (args.includes('--others')) return done(r.hasUntracked ? 'mine.txt\n' : '')
        return done(r.workspaces.map(file => `${file}\n`).join(''))
      case 'reset': mutate(); if (args[0] === '--hard') { r.hasEdits = false; r.hasUntracked = false; r.editsAt = null } return done()
      case 'update-ref': mutate(); r.end = args[1] as string; return done()
      default: mutate()  // anything else would change something: the tests assert nothing else runs
    }
    return undefined
  }
}
