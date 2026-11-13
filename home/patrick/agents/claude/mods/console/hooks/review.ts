// The review tree's git (r25): sets a worktree beside main to a change request's (base tip, tip) so its diff shows as unstaged
// edits. Reading and landing are the board's (`board cr land`); this module only moves the review tree. Git is the only store; the
// console keeps just the selection. No runtime imports: the module takes a `Run`, so a probe can drive it with real git (the mod's
// tests drive it with a stand-in).

export type Ran = { exitCode: number; stdout: string; stderr: string }
export type Run = (argv: readonly string[], env?: Readonly<Record<string, string>>) => Promise<Ran>

/**
 * The review tree's own ref: the tip its working tree was set to, moved by `board cr edits --commit` to the commit it made of the
 * tree's files. HEAD moves to the base (reset -N), so the tip is kept here.
 */
export const REVIEW_END_REF = 'refs/worktree/console-review-end'

export type Outcome = { ok: true } | { ok: false; why: string }
const refused = (why: string): { ok: false; why: string } => ({ ok: false, why })
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

/** The main worktree and the review tree beside it; a failed read is the refusal. */
async function locate(run: Run, cwd: string): Promise<{ ok: true; main: string; tree: string; hasTree: boolean } | { ok: false; why: string }> {
  const listed = await run(['git', '-C', cwd, 'worktree', 'list', '--porcelain'])
  if (listed.exitCode !== 0) return refused(`git worktree list: ${failure(listed)}`)
  const trees = parseWorktrees(listed.stdout)
  const main = trees[0]?.path
  if (main === undefined) return refused('git lists no worktree')
  const tree = reviewTreeOf(main)
  return { ok: true, main, tree, hasTree: trees.some(one => one.path === tree) }
}

/**
 * The tree object holding the review tree's files (tracked and new, not ignored, as on disk), built in a throwaway index from
 * `base`: the review tree's own index and files are never touched. The same recipe as the board's `review_edits_tree`
 * (bin/board), so "clean" here and "no edits" there are one verdict.
 */
export async function snapshotTree(run: Run, tree: string, base: string): Promise<{ ok: true; tree: string } | { ok: false; why: string }> {
  const made = await run(['mktemp', '-d'])  // outside the review tree, so `add -A` never takes the index in
  if (made.exitCode !== 0 || first(made) === '') return refused(`mktemp: ${failure(made)}`)
  const dir = first(made)
  const env = { GIT_INDEX_FILE: `${dir}/index` }
  try {
    for (const args of [['read-tree', base], ['add', '-A']]) {
      const ran = await run(['git', '-C', tree, ...args], env)
      if (ran.exitCode !== 0) return refused(`git ${args[0]}: ${failure(ran)}`)
    }
    const written = await run(['git', '-C', tree, 'write-tree'], env)
    return written.exitCode === 0 && first(written) !== '' ? { ok: true, tree: first(written) } : refused(`git write-tree: ${failure(written)}`)
  } finally {
    await run(['rm', '-rf', dir])
  }
}

/**
 * The review tree as it stands: `end` is its marker (the tip the console set it to, or the commit `board cr edits` made of its
 * files; null when unmarked); `isClean`: its files are exactly `end`'s tree (HEAD's when unmarked), so nothing of yours is
 * uncommitted. Null when there is no review tree.
 */
export type ReviewTree = { tree: string; end: string | null; isClean: boolean }

export async function readReviewTree(run: Run, cwd: string): Promise<{ ok: true; state: ReviewTree | null } | { ok: false; why: string }> {
  const where = await locate(run, cwd)
  if (!where.ok) return where
  if (!where.hasTree) return { ok: true, state: null }
  const git = (...args: string[]) => run(['git', '-C', where.tree, ...args])
  const end = first(await git('rev-parse', '-q', '--verify', `${REVIEW_END_REF}^{commit}`)) || null
  const base = end ?? 'HEAD'
  const want = await git('rev-parse', '--verify', `${base}^{tree}`)
  if (want.exitCode !== 0) return refused(`git rev-parse: ${failure(want)}`)
  const found = await snapshotTree(run, where.tree, base)
  if (!found.ok) return found
  return { ok: true, state: { tree: where.tree, end, isClean: found.tree === first(want) } }
}

/** The review tree's marker alone, for the pane's status: no snapshot. Null when there is no review tree or no marker. */
export async function readReviewEnd(run: Run, cwd: string): Promise<string | null> {
  const where = await locate(run, cwd)
  if (!where.ok || !where.hasTree) return null
  return first(await run(['git', '-C', where.tree, 'rev-parse', '-q', '--verify', `${REVIEW_END_REF}^{commit}`])) || null
}

/**
 * Sets the review tree to `tip`, the change unstaged against the fork point of `tip` and `baseTip`; returns the tree to open. The
 * fork point (not `baseTip` itself) keeps a stale base's own commits out of the diff. Never over edits of yours in the tree: only a
 * clean tree (`readReviewTree`) is reset.
 */
export async function pickRange(run: Run, cwd: string, target: ReviewTarget): Promise<Outcome & { tree?: string; open?: string }> {
  const where = await locate(run, cwd)
  if (!where.ok) return where
  const { main, tree } = where
  for (const sha of [target.tip, target.baseTip]) {
    const known = await run(['git', '-C', main, 'rev-parse', '--verify', '-q', `${sha}^{commit}`])
    if (known.exitCode !== 0) return refused(`${sha.slice(0, 7)} is not a commit here`)
  }
  const fork = await run(['git', '-C', main, 'merge-base', target.baseTip, target.tip])
  if (fork.exitCode !== 0 || first(fork) === '') return refused(`no common base for ${target.baseTip.slice(0, 7)} and ${target.tip.slice(0, 7)}`)
  const git = (...args: string[]) => run(['git', '-C', tree, ...args])
  if (!where.hasTree) {
    const added = await run(['git', '-C', main, 'worktree', 'add', '--detach', tree, target.tip])
    if (added.exitCode !== 0) return refused(`git worktree add: ${failure(added)}`)
  } else {
    // What you typed in the review tree shows against the tip it was set to; never overwrite it.
    const found = await readReviewTree(run, cwd)
    if (!found.ok) return found
    if (found.state !== null && !found.state.isClean) return refused(`the review tree has edits of yours: ${tree}`)
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
