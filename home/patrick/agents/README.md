# Shared agent definitions

`definitions/` is the source of truth for custom agent roles. Its Markdown
files use Claude Code-compatible agent frontmatter as a practical superset;
the prompt body and canonical lowercase role name are shared by both tools.
Keep prompt wording provider-neutral; tool-specific settings belong in
frontmatter adapter fields.

`skills/` is the source and template tree for shared skills. Markdown files may
include another skills-root-relative Markdown file with a marker on its own
line:

```md
<!-- @include shared/decision-protocol.md -->
```

The build expands includes recursively into complete standalone skill files.
Agent definitions take the same markers, resolved against `skills/`
(`review` and `deep-review` share `shared/review-method.md`; `verify` takes
`shared/reuse-check.md`; every file-writing agent takes the report cap in
`shared/report.md`; worker limits come from one of `shared/limits-assessor.md`,
`limits-implementer.md` or `limits-readonly.md`).
Missing targets, escaping paths, cycles, frontmatter markers, and malformed or
unresolved markers fail validation.

Keep role and authority limits before each skill's workflow; place whole-file
shared references after them and link
them from the relevant phases. Includes
retain their heading levels; use one H1 and flat reference sections.

The global instructions describe capabilities and responsibilities rather than
a particular tool's command syntax.

Load shared content per reader; every file in `skills/shared/` stays readable
on its own:

- Include content a skill acts on in every run; the rendered skill carries it,
  so reloading the skill after compaction restores it.
- Reference `$HOME/.agents/skills/shared/<file>` by path for readers without
  includes (agent definitions, `AGENTS.md`), for conditional or
  single-section needs, and for files role sessions already load (board-core,
  decision-protocol, reviewers): the skill reads them "unless its text is
  already in your context".
- Links only navigate loaded content: in-file anchors for included files,
  `../shared/` links for files the skill reads by path. Validation rejects
  other links and unresolved anchors.
- Role protocol files (`skills/role/protocols/`) are read by
  `$HOME/.agents/skills/role/protocols/<name>.md` path; they read shared
  files by path and link them as `../../shared/`. Skills name protocol paths
  in code spans instead of linking them.

Nix generates the Claude Code and Codex representations into the store, and
Home Manager links them at activation. It also renders the shared skill tree
into the store; generated files do not live in Git. Skill changes therefore
require `darwin-rebuild switch` before they become active.
Hooks, the `bin/` scripts (`board`, `session`), the hook
registrations and the global instructions (`AGENTS.md`) are linked out of
store to the working tree, so their edits are live at once; rendered skills,
agent definitions and newly added links change only at the switch.
After a switch that changes Codex hook entries, re-trust the changed hooks in
Codex; untrusted hooks do not run.

To inspect generated output manually:

```sh
output_dir=$(mktemp -d)
python3 home/patrick/agents/bin/generate-agent-configs.py \
  --target codex \
  --output "$output_dir"

python3 home/patrick/agents/bin/expand-skills.py \
  --source home/patrick/agents/skills \
  --output "$output_dir/skills"
```

To validate skills, generated formats, policies and hooks, use Python with
PyYAML (the Nix build provides it):

```sh
python3 home/patrick/agents/bin/test-agent-configs.py \
  home/patrick/agents
```

The generator translates portable fields to both formats. Each definition
declares its Codex model and sandbox; Claude-specific models, tools, and hooks
remain optional adapter fields. New roles therefore cannot accidentally
inherit write access or an unintended Codex model.

`effort` is the shared reasoning level; optional `claude-effort` and
`codex-effort` override it for one tool. The resolved value is validated per
tool, since only Codex accepts `ultra`.

Validation covers source instruction/description preservation, per-tool effort
resolution, generated permissions, and local hooks. Live runtime enforcement requires separate checks.

Each role's `codex-model` field owns its model selection; validation requires
an explicit, nonempty model without pinning a particular selection.

Scout and explore return discovery results in their responses. Other specialists
can write assigned artifacts directly. Native configurations provide file-write
tools and workspace access; role instructions confine edits to assigned
artifacts and temporary probes. Implementation changes belong to implementation
roles, except reported fixes an assessor is certain are the only realistic,
clean option. Claude's investigation shell guard is a deny-list; Codex uses its
native sandbox setting. Role instructions define assigned write zones.

Workflow owners:

- [Role](skills/role/SKILL.md): the user-invoked session entry. It registers
  the session's role (lead, agent with pulls, solo, autopilot) through
  `bin/session` and owns the role-to-protocol mapping.
- [Protocols](skills/role/protocols/): [decide](skills/role/protocols/decide.md)
  (rounds, release, acceptance of designs and user-judged outcomes),
  [plan](skills/role/protocols/plan.md) (released rulings into work, framing,
  cutting, briefing, dispatch, integration),
  [work](skills/role/protocols/work.md) (one design or implementation item),
  [review](skills/role/protocols/review.md) (independent review, review policy,
  evidence and gates) and
  [unattended](skills/role/protocols/unattended.md) (autopilot authority and
  parking); [accept](skills/role/protocols/accept.md) (user acceptance, user
  review and ratification), read only at decide's Accept. Sessions read them by path; compaction recovery names them again.
- [Board core](skills/shared/board-core.md) and
  [board coordination](skills/shared/board-coordination.md): board model, holds,
  routing, record shapes, epics, milestones and rulings; [board-migrate](skills/board-migrate/SKILL.md)
  moves a project from any starting state onto it, deriving the work from the gap to the target.
- Challenge skills: [step-back](skills/step-back/SKILL.md),
  [challenge-rulings](skills/challenge-rulings/SKILL.md) and
  [ground](skills/ground/SKILL.md) are model-invocable; round checks use the
  full step-back protocol, a confirming pass in a fresh turn, then
  challenge-rulings (the engine sequences a `protocol` round; Ground remains
  separately invocable and is used by release checks);
  [ask-advisor](skills/ask-advisor/SKILL.md),
  [question-me](skills/question-me/SKILL.md),
  [release-round](skills/release-round/SKILL.md),
  [start-round](skills/start-round/SKILL.md),
  [round-intake](skills/round-intake/SKILL.md) (a list you hand over) and
  [explain](skills/explain/SKILL.md) are user-invoked only. Their
  argument names the focus and follow-ups.
- [Retro](skills/retro/SKILL.md): rule proposals and regression cases.
- [Skill authoring](skills/skill-authoring/SKILL.md): invocation policy,
  trigger descriptions, frontmatter and style for skills, definitions and
  instructions; loaded while writing, user-invoked to review.
Component references (behavior, verbs and rulings of each tool):

- [Board and sessions](docs/board.md): `bin/board` (`board setup` owns a board's
  settings), shared boards, change-request review, `bin/session`.
- [Scratch](docs/scratch.md): `bin/scratch`, working files outside the repositories.
- [Protocol engine](docs/protocol-engine.md): `bin/protocol`, rounds, releases,
  `bin/round-report`.
- [Console mod](docs/console.md): `claude/mods/console/`, the Claude Code pane
  and hooks.

The validator runs its groups (core, hooks, board, contract and the protocol
engine's parts `engine-<part>`, `PROTOCOL_PARTS`) as parallel child processes
(`--group <name>` runs one). The switch's build runs only `--group core` (what
it generates: skills, definitions, rendered sizes) from a source without the
test-only files; the full validator is `nix flake check` (`checks.agent-configs`),
the gate to run before staging. The nix sandbox has no `bd`: in-process test
boards carry empty settings (`bare_deck`) instead of reading them through bd. Each engine part starts on a fresh fixture;
sections within a part share state in order, so a section that needs an earlier
one's rounds stays in its part.

The `explore-options` skill coordinates `option-explorer` to develop a broad
solution space into realistic alternatives. It progressively screens and deepens
approaches, reports material exclusions, and leaves decisions to the invoker.
Sessions name triggers in their protocols; the skill owns how its result is
reused.

The `architect` skill coordinates the architecture specialist without
requiring a role. The agent owns design, `review` assesses it; `second-opinion` independently
challenges decisions. The lead selects each for a concrete question. `plan`
decomposes an agreed design into implementation work when decomposition or
integration needs specialist judgment; leads can write pattern-determined plans
and continuation deltas directly.

The [review protocol](skills/role/protocols/review.md) owns review gates and
acceptance evidence. The [decision protocol](skills/shared/decision-protocol.md)
owns default decision authority, end-state criteria and concern classes; agent
definitions read it at runtime. Shared files:
[reviewers](skills/shared/reviewers.md) (selection, briefing, independence,
disagreement), [asking](skills/shared/asking.md) (how deciding sessions
walk the user through a round) and
[upstream waits](skills/shared/upstream-waits.md) (read on demand from
board-coordination).
[Question format](skills/shared/question-format.md) is tool-neutral; asking, role, question-me and retro include it.

Tool-specific names are optional and default to the canonical `name`. Shared
`explore` overrides that default as Claude Code's `Explore` and Codex's
`explorer`; shared `plan` becomes Claude Code's `Plan` and remains lowercase
in Codex.

## Sharing the setup

`./build-agent-setup.sh [folder]` (flake root; default folder: home) runs
`nix build .#agent-setup` and copies out `claude-codex-setup-<date>-<rev>.tar.gz`
for someone without this nix config: new files must be tracked first, and a
`-dirty` version names a build with uncommitted changes. `../agents-package.nix` owns what ships and builds this
machine's links from the same lists, so a shipped hook or tool is added in one
place; hook registrations come from `../claude/settings.json` and
`../codex/hooks.json`, so only this setup's hooks belong in them.

`setup/install.py` (its use: `setup/README.md`) is stdlib-only Python that stays parseable
by macOS's 3.9, so its version message (or its re-run under a newer `python3.N`) reaches the user;
the validator's hooks group runs it in a fake home. It refuses symlinked targets, so it never runs
over this machine's home-manager links. The `~/.agents/setup-state.json` it writes lists what it
installed, which is how an upgrade or `--uninstall` finds what to remove.

The installer pins each top-level Python tool in `~/.agents/bin` to the `python3` it ran under; the
nix build pins this machine's copies (`pinnedBin`, linked by `../agents.nix`) to `agentPackage.python` and the bundle ships
`#!/usr/bin/env python3`. It also grants the write roots listed in `GRANT_ROOTS` in `install.py`
(the folders `bin/scratch` and `protocol_engine/cli.py` write; the validator checks them against
those tools): an `Edit(<root>/**)` rule per root in Claude's `permissions.allow` (tracked in the
state file) and a marked block in `~/.codex/config.toml` (found again by its marker). This machine's
`../claude/settings.json` and `../codex/config.toml` carry their own copies, not generated from the list.
