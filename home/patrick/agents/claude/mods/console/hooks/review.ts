// The review tree's git (r25): sets a worktree beside main to a change request's (base tip, tip) so its diff shows as unstaged
// edits. Reading and landing are the board's (`board land`); this module only moves the review tree. Git is the only store; the
// console keeps just the selection. No runtime imports: the module takes a `Run`, so a probe can drive it with real git (the mod's
// tests drive it with a stand-in).

export type Ran = { exitCode: number; stdout: string; stderr: string }
export type Run = (argv: readonly string[]) => Promise<Ran>

/** The review tree's own ref: the tip its working tree was set to. HEAD moves to the base (reset -N), so the tip is kept here. */
export const REVIEW_END_REF = 'refs/worktree/console-review-end'

export type Outcome = { ok: true } | { ok: false; why: string }
const refused = (why: string): Outcome => ({ ok: false, why })
const first = (ran: Ran): string => ran.stdout.trim()
const failure = (ran: Ran): string => ran.stderr.trim() || ran.stdout.trim() || `exit ${ran.exitCode}`

/** The review tree sits beside the main worktree. */
export const reviewTreeOf = (main: string): string => `${main}-review`

/** One block per worktree, the main one first: path and the branch checked out there (null when detached). */
export function parseWorktrees(porcelain: string): { path: string; branch: string | null }[] {
  return porcelain.split(/\n\n+/).flatMap(block => {
    const lines = block.split('\n')
    const path = lines.find(line => line.startsWith('worktree '))?.slice('worktree '.length)
    if (path === undefined) return []
    const branch = lines.find(line => line.startsWith('branch '))?.slice('branch '.length) ?? null
    return [{ path, branch }]
  })
}

/** What to set the tree to: the change request's branch tip and its base tip. */
export type ReviewTarget = { tip: string; baseTip: string }

/**
 * Sets the review tree to `tip`, the change unstaged against the fork point of `tip` and `baseTip`; returns the tree to open. The
 * fork point (not `baseTip` itself) keeps a stale base's own commits out of the diff. Never over edits of yours in the tree.
 */
export async function pickRange(run: Run, cwd: string, target: ReviewTarget): Promise<Outcome & { tree?: string; open?: string }> {
  const listed = await run(['git', '-C', cwd, 'worktree', 'list', '--porcelain'])
  if (listed.exitCode !== 0) return refused(`git worktree list: ${failure(listed)}`)
  const trees = parseWorktrees(listed.stdout)
  const main = trees[0]?.path
  if (main === undefined) return refused('git lists no worktree')
  const tree = reviewTreeOf(main)
  for (const sha of [target.tip, target.baseTip]) {
    const known = await run(['git', '-C', main, 'rev-parse', '--verify', '-q', `${sha}^{commit}`])
    if (known.exitCode !== 0) return refused(`${sha.slice(0, 7)} is not a commit here`)
  }
  const fork = await run(['git', '-C', main, 'merge-base', target.baseTip, target.tip])
  if (fork.exitCode !== 0 || first(fork) === '') return refused(`no common base for ${target.baseTip.slice(0, 7)} and ${target.tip.slice(0, 7)}`)
  const git = (...args: string[]) => run(['git', '-C', tree, ...args])
  if (!trees.some(one => one.path === tree)) {
    const added = await run(['git', '-C', main, 'worktree', 'add', '--detach', tree, target.tip])
    if (added.exitCode !== 0) return refused(`git worktree add: ${failure(added)}`)
  } else {
    // What you typed in the review tree shows against the tip it was set to; never overwrite it.
    const set = first(await git('rev-parse', '-q', '--verify', REVIEW_END_REF)) || 'HEAD'
    const [diff, untracked] = await Promise.all([git('diff', '--quiet', set), git('ls-files', '--others', '--exclude-standard')])
    if (diff.exitCode !== 0 || first(untracked) !== '') return refused(`the review tree has edits of yours: ${tree}`)
  }
  const reset = await git('reset', '--hard', target.tip)
  if (reset.exitCode !== 0) return refused(`git reset --hard: ${failure(reset)}`)
  const unstaged = await git('reset', '-N', first(fork))
  if (unstaged.exitCode !== 0) return refused(`git reset -N: ${failure(unstaged)}`)
  const marked = await git('update-ref', REVIEW_END_REF, target.tip)
  if (marked.exitCode !== 0) return refused(`git update-ref: ${failure(marked)}`)
  // The tree's own workspace file when exactly one sits at its root, else the folder.
  const files = (await git('ls-files', '--', ':(glob)*.code-workspace')).stdout.split('\n').filter(file => file !== '')
  return { ok: true, tree, open: files.length === 1 ? `${tree}/${files[0]}` : tree }
}
