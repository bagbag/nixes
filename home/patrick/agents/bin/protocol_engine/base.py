"""Shared constants, the refusal error, the per-call process context and small text helpers."""
from __future__ import annotations

import contextvars
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


VERSION = 1  # the show --json contract and the state file schema
BIN = Path(__file__).resolve().parent.parent  # the bin folder: this package's parent
REGISTRY = BIN / 'session'
BOARD = BIN / 'board'
CHECK_CAP = 10  # check cycles before the machine asks the user how to go on
BATCH = 4  # AskUserQuestion takes 1-4 questions
HEADER_MAX = 12  # AskUserQuestion's header chip
# Lengths: the Stage text states the targets; a report is refused only above the limit, since a model cannot count exactly and
# a few characters over cost nothing to read (r23-q95); above the target and within the limit it is accepted with a warning
# line (`band_warning`). The pane truncates titles.
TITLE_MAX, TITLE_LIMIT = 60, 75  # question and round titles: one pane row
SUMMARY_MAX = 240  # the round summary: about two pane rows
TEXT_MAX, TEXT_LIMIT = 160, 240  # a question's text: the dialog question
DESCRIPTION_MAX, DESCRIPTION_LIMIT = 150, 200  # an option's model-written description (the engine's "Unverified: …" prefix is not counted)
CHECKED_MAX, CHECKED_LIMIT = 120, 250  # a pass report's `checked` line, each entry (r13-q66; warn band: decision 2026-11-12 protocol-refusals)
OVERLAP_LIMIT = 5  # related hits per new draft
SEEDS = 5  # `protocol next` lists this many seed questions
PROPOSAL_ROUNDS = 3  # rounds in a stored proposal
PRUNE_DAYS = 30  # a session's protocol folder without an open round goes after this much inactivity
CLASSES = ('ruled', 'planning', 'own', 'user')  # decide.md Collect
KINDS = ('decision', 'confirm-own-rulings')  # every kind a round question can have; only release approval is `confirm-own-rulings`
STAGED_KINDS = ('decision',)  # what a model stages: a lead's own rulings are ordinary questions (r22-q168), the approval is the engine's
OUTCOMES = ('duplicate', 'extend', 'relate', 'supersedes', 'unrelated')
TAKEOVER = ('duplicate', 'extend')  # the Related outcomes that make the hit the question's `board`
REVISES, REVISES_RULE = 'tracks', 'board.revises_rule'  # bin/board: the pending-revision link and its partial rule (the validator compares them)
PASSES = ('step-back', 'ground', 'challenge-rulings')
# Origins (contract rulings R-B2, R-B9-R-B11): the console stamps them; the model's tool stamps chat on answer and
# model on every other verb.
PASS_ORIGINS = ('composer', 'bridge', 'press', 'plugin', 'model')
AWAY = 'away'  # the origin of an answer an away round took from the recommendation: no verb accepts it, so no person origin passes as it (r28-q128)
SETTLES = ('act', 'park')
DROP_KINDS = ('pass', 'batch')  # what a dropped console action was: a pass run or prompt, a batch's dialog
EXPLORED_VERDICTS = ('kept', 'dropped')


@dataclass(frozen=True, kw_only=True)
class Verb:
    """One protocol verb: the definition `protocol help`, the parser and the origin check read. No field has a default.
    `audience`: `session` (no origin check), `origin` (sessions and the console, the origin saying which), `console` (console only).
    `origins`: the accepted --origin values. `stdin`: names of its stdin forms in schema.py (checked on load)."""
    name: str
    audience: Literal['session', 'origin', 'console']
    origins: tuple[str, ...]
    summary: str
    example: str
    stdin: tuple[str, ...]

    def __post_init__(self):
        if self.audience not in ('session', 'origin', 'console') or not (self.summary and self.example.startswith(f'protocol {self.name}')):
            raise ValueError(f'verb {self.name}: audience, summary or example is not valid')


STEP_FORMS = ('prepass', 'collect', 'select', 'stage', 'related', 'pass-report', 'settle', 'record', 'recheck', 'board-check',
              'own-rulings', 'scoped', 'owners')
VERBS = (
    Verb(name='start', audience='session', origins=(), summary='open a protocol run', example='protocol start round', stdin=('start',)),
    Verb(name='step', audience='session', origins=(), summary="submit the current step's report; prints the next step",
         example='protocol step < report.json', stdin=STEP_FORMS),
    # model-reported: Codex sessions only
    Verb(name='answer', audience='origin', origins=('dialog', 'chat', 'model-reported'), summary='record answers; prints show --json with a note',
         example='protocol answer --origin chat < answer.json', stdin=('answer', 'answer-chat')),
    Verb(name='decline', audience='origin', origins=('dialog', 'model-reported'), summary='a declined batch returns to ready; prints show --json',
         example='protocol decline --origin model-reported < decline.json', stdin=('decline',)),
    Verb(name='pass', audience='origin', origins=PASS_ORIGINS, summary='a pass started, or the person typed or pressed /release-round; prints show --json',
         example='protocol pass --origin model < pass.json', stdin=('pass-run',)),
    Verb(name='edit', audience='session', origins=(), summary="apply the user's requested change to the questions",
         example='protocol edit < edit.json', stdin=('edit',)),
    Verb(name='defer', audience='session', origins=(), summary="defer a question and the questions waiting on it at the user's request",
         example='protocol defer < defer.json', stdin=('defer',)),
    # the person's own messages, stored for the chat quote check
    Verb(name='say', audience='console', origins=('composer', 'bridge'), summary="store the person's message for the chat quote check",
         example='protocol say --origin composer < say.json', stdin=('say',)),
    # a stale console action the console did not deliver (r3-q10)
    Verb(name='dropped', audience='console', origins=('plugin',), summary='the console dropped a stale action',
         example='protocol dropped --origin plugin < dropped.json', stdin=('dropped',)),
    # the person's /console-continue or Continue press, with what the console did (r7-q24)
    Verb(name='nudged', audience='console', origins=('plugin',), summary='the person asked the console to continue',
         example='protocol nudged --origin plugin < nudged.json', stdin=('nudged',)),
    # what the pass the console sees start must cover, named in its expanded text (r9-q36)
    Verb(name='scope', audience='console', origins=('plugin',), summary='what a report of the pass starting now must cover, as JSON; changes nothing',
         example='protocol scope --origin plugin < scope.json', stdin=('scope',)),
    Verb(name='restart', audience='session', origins=(), summary='questions back to draft after a criterion answer; the check loop reruns',
         example='protocol restart q2 --reason "criterion changed"', stdin=()),
    Verb(name='next', audience='session', origins=(), summary='the seed questions, the open questions by topic and the stored proposal',
         example='protocol next', stdin=('proposal',)),
    Verb(name='compacted', audience='session', origins=(), summary="the session's context was compacted: what it was told prints in full again",
         example='protocol compacted', stdin=()),
    Verb(name='resume', audience='session', origins=(), summary='continue a paused check loop', example='protocol resume', stdin=()),
    Verb(name='abandon', audience='session', origins=(), summary='close the open round without records', example='protocol abandon', stdin=()),
    Verb(name='show', audience='session', origins=(), summary='the round as markdown, --json (the console contract), or <ids>: those questions whole',
         example='protocol show --json', stdin=()),
    # the console's read of the pending pass: no origin
    Verb(name='pending', audience='console', origins=(), summary='the pending pass as JSON, or null', example='protocol pending', stdin=()),
    Verb(name='status', audience='session', origins=(), summary='one recovery line', example='protocol status --line', stdin=()),
    Verb(name='records', audience='session', origins=(),
         summary="this repository's records folder for rounds without a board; needs no session",
         example='protocol records', stdin=()),
    Verb(name='help', audience='session', origins=(), summary='every verb with an example, or one verb in full (a call with no arguments prints the list too)',
         example='protocol help step', stdin=()),
)
VERB_ORIGINS = {verb.name: verb.origins for verb in VERBS if verb.origins}
COLLECT_VIEWS = 'decided,questions,ratification,accept,review,user'
LIST_COMMAND = f'board health --items {COLLECT_VIEWS}'  # lists the open items Collect offers, but for the ready milestones and finished epics `board position` lists
SCOPED_PASSES = ('step-back', 'ground')  # once per release on the revised records, before the approval (r8-q36)
REACHES = ('contained', 'spreads')  # no "unsure": unsure is spreads (r4-q14, fails closed)
TOUCHES = ('own', 'decision')  # a contained change: only the model's own parts keeps the record; unsure is decision (r8-q36)
CAP_CHOICES = ('Continue', 'Ask now', 'Pause')
STRENGTHS = ('lean', 'strong')
LEAN_CAUSES = ('preference', 'evidence')  # the user's values decide, or an unchecked fact (the lean pass)
# Lens names: skills/step-back/SKILL.md and skills/ground/SKILL.md own them (the console's hooks/words.ts repeats them);
# the validator keeps the three in step. Base (no lens named) covers consumer, root-fix, bloat and gaps.
ALL_LENSES = {  # the owners' lists (the validator compares them); the check sequence runs the path and refine subsets
    'step-back': ('goal', 'decisions', 'foundations', 'consumer', 'root-fix', 'bloat', 'gaps', 'clean', 'overfit', 'mechanics', 'options'),
    'ground': ('assumptions', 'board', 'sources', 'probe'),
}
# The check sequence per round (user, r5 q26, r6 q28, r30 q142): the path pass (is the goal and what it builds on right?), then
# the options pass (radically different ways, each kept or dropped with its reason), before the Base loop, the refine pair
# after it; Base's own lenses (consumer, root-fix, bloat, gaps) are named in none of them.
PATH_LENSES = ('goal', 'foundations')
OPTIONS_LENSES = ('options',)
REFINE_LENSES = {'step-back': ('decisions', 'clean', 'overfit', 'mechanics'), 'ground': ('assumptions', 'board', 'sources', 'probe')}
LEAN_LENSES = ('assumptions', 'sources', 'probe')  # the targeted lean pass: every way a lean gets decided (r6 q29)
# skills/shared/decision-protocol.md#recommendation-strength owns these rules; the validator keeps the names in step.
# A strong recommendation is a claim: each criterion "true: <evidence>", or "does-not-apply: <reason>" where allowed.
STRONG_CRITERIA = {
    'noAssumptions': 'every premise checked in current source, a run or an item (name where)',
    'alternativesFail': 'each other realistic option, listed or not, fails a named criterion (cleanliness test, goal, correctness, consumer need); name the strongest unlisted one and why it fails or was added; a simpler option fails only on a failure shown by a fact or a consumer case the person or the goal names (r4-q13)',
    'notPreference': 'the choice does not depend on what the user values',
    'consumerWalk': 'a realistic consumer walk supports it (does-not-apply for internal choices)',
    'rulingsChallenged': 'judged as if no released ruling existed; each related ruling challenged in `priorRulings`, and each that fails raised as a revision',
}
MAY_NOT_APPLY = ('consumerWalk', 'rulingsChallenged')
THINK_MORE = 'Think more'  # a lean question's extra dialog choice: no answer, its checks rerun (r34-q171)


def taken_over(q: dict) -> bool:
    """Whether the question's `board` is a hit it took over at Related, not an item it came with."""
    return any(h['id'] == q.get('board') and h['outcome'] in TAKEOVER for h in q.get('overlaps') or [])


def recommended_suffix(q: dict) -> str:
    """The mark on the recommended option's label in the dialog: ` (recommended, lean)`. A release approval has none: the
    engine asks it on every release, so a mark would say nothing about this one (r15 q58)."""
    return f" (recommended, {q['strength']})" if q.get('strength') else ''


def band_warning(what: str, length: int, target: int, limit: int) -> list[str]:
    """One warning line for a field over its target and within its limit (an empty list otherwise; over the limit it is refused)."""
    if not target < length <= limit:
        return []
    return [f'{what} is {length} characters; keep it to about {target} (refused over {limit})']


class ProtocolError(Exception):
    """A refusal. `formats` is the report format a refused report repeats: printed after the message, not logged."""

    def __init__(self, *args, formats: str = ''):
        super().__init__(*args)
        self.formats = formats


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class Call:
    """One `run_cli` invocation: everything the engine reads from its process, so calls with different environments
    can share one interpreter. `state_root` is cached per call (the registry derives it from the environment)."""

    def __init__(self, env: Mapping[str, str], cwd: Path, stdin):
        self.env, self.cwd, self.stdin = dict(env), cwd, stdin
        self.stdout: list[str] = []
        self.stderr: list[str] = []
        self.state_root: Path | None = None


_call: contextvars.ContextVar[Call] = contextvars.ContextVar('protocol_call')


def env() -> dict[str, str]:
    return _call.get().env


def json_block(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def lines(*parts: str) -> str:
    """The step text: its parts, those left empty out."""
    return '\n'.join(part for part in parts if part)


def cut(text: str, limit: int) -> str:
    """At most `limit` characters, cut at a word boundary and ending with `…` when it cut."""
    if len(text) <= limit:
        return text
    head = text[:limit - 1]
    if not text[limit - 1].isspace() and ' ' in head:
        head = head.rsplit(' ', 1)[0]
    return head.rstrip(' ,;:.-') + '…'


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"
