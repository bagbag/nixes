"""Shared constants, the refusal error, the per-call process context and small text helpers."""
from __future__ import annotations

import contextvars
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path


VERSION = 1  # the show --json contract and the state file schema
BIN = Path(__file__).resolve().parent.parent  # the bin folder: this package's parent
REGISTRY = BIN / 'session-lead-mode'
BOARD = BIN / 'board'
CHECK_CAP = 5  # check cycles before the machine asks the user how to go on
BATCH = 4  # AskUserQuestion takes 1-4 questions
HEADER_MAX = 12  # AskUserQuestion's header chip
# Lengths: the Stage text states the targets; a report is refused only above the limit, since a model cannot count exactly and
# a few characters over cost nothing to read (r23-q95). The pane truncates titles.
TITLE_MAX, TITLE_LIMIT = 60, 75  # question and round titles: one pane row
SUMMARY_MAX = 240  # the round summary: about two pane rows
TEXT_MAX, TEXT_LIMIT = 160, 240  # a question's text: the dialog question
DESCRIPTION_MAX, DESCRIPTION_LIMIT = 150, 200  # an option's model-written description (the engine's "Unverified: …" prefix is not counted)
OVERLAP_LIMIT = 5  # related hits per new draft
SEEDS = 5  # `protocol next` lists this many seed questions
PROPOSAL_ROUNDS = 3  # rounds in a stored proposal
PRUNE_DAYS = 30  # a session's protocol folder without an open round goes after this much inactivity
CLASSES = ('ruled', 'planning', 'own', 'user')  # decide.md Collect
KINDS = ('decision', 'confirm-own-rulings')
OUTCOMES = ('duplicate', 'extend', 'relate', 'supersedes', 'unrelated')
REVISES, REVISES_RULE = 'tracks', 'board.revises_rule'  # bin/board: the pending-revision link and its partial rule (the validator compares them)
PASSES = ('step-back', 'ground', 'challenge-rulings')
# Origins (contract rulings R-B2, R-B9-R-B11): the console stamps them; the model's tool stamps chat on answer and
# model on every other verb.
PASS_ORIGINS = ('composer', 'bridge', 'press', 'plugin', 'model')
AWAY = 'away'  # the origin of an answer an away round took from the recommendation: no verb accepts it, so no person origin passes as it (r28-q128)
SETTLES = ('act', 'park')
EXPLORED_VERDICTS = ('kept', 'dropped')
VERB_ORIGINS = {
    'answer': ('dialog', 'chat', 'model-reported'),  # model-reported: Codex sessions only
    'decline': ('dialog', 'model-reported'),
    'pass': PASS_ORIGINS,
    'say': ('composer', 'bridge'),  # the person's own messages, stored for the chat quote check
}
COLLECT_VIEWS = 'decided,questions,ratification,review,user'
LIST_COMMAND = f'board health --items {COLLECT_VIEWS}'  # lists the open items Collect offers, but for the ready milestones and finished epics `board position` lists
# Question fields a pass can change; a change to any of them counts (asking.md Check: premise, ruling, option or
# question set).
CONTENT = ('text', 'title', 'header', 'options', 'multiSelect', 'kind', 'board', 'waitsOn', 'for', 'settles', 'premises',
           'problem', 'cases', 'rulings', 'note', 'recommendation', 'strength', 'leanBecause', 'strongBecause', 'priorRulings')
# How a question is shown and backed, not what it asks (asking.md Check counts premise, ruling, option and question
# set): an edit to these alone re-issues the batch without rerunning the check loop.
PRESENTATION = ('title', 'header', 'note', 'strength', 'leanBecause', 'strongBecause')  # plus an option's `preview` (see substantive)
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
    'alternativesFail': 'each other realistic option, listed or not, fails a named criterion (cleanliness test, goal, correctness, consumer need); name the strongest unlisted one and why it fails or was added',
    'notPreference': 'the choice does not depend on what the user values',
    'consumerWalk': 'a realistic consumer walk supports it (does-not-apply for internal choices)',
    'rulingsChallenged': 'judged as if no released ruling existed; each related ruling challenged in `priorRulings`, and each that fails raised as a revision',
}
MAY_NOT_APPLY = ('consumerWalk', 'rulingsChallenged')
MERGE_TEST = ('Merge questions only when no sensible answer would treat them differently: an option that splits them means separate '
              'questions, and a shared premise puts them in one round, not one question.')  # skills/shared/question-format.md owns the test
# The lean pass aims for strong (r38-q213): decision-protocol.md#recommendation-strength owns the rule; the validator keeps both in step.
LEAN_JOB = (' (the lean pass, aiming each lean named in the argument at strong: redo the question from scratch, walk a realistic consumer '
            'through it (a caller read from the code, or what the person would see), and probe or count the deciding fact where one run settles '
            'it. A lean still resting on what the person values comes back as the value question in its `text`, options unchanged, still '
            'recommending on merits with `flipsIf`; an unchecked fact stays an evidence lean naming the check).')
HAND_OVER = 'End your turn with one short line: what changed, or "No change."'
NO_RUN = ('no /{command} ran since its last report: end your turn (the console runs a pass it has not run yet, and tells the person what to '
          'type for one it has), or call the skill yourself; a model Skill call counts once it ran')
PICK_DETAIL = ('Count a pick as the answer when the rest of the reply or note questions only a detail the pick doesn\'t hinge on; '
               'leave the question open only when the doubt could change the pick. Record the pick (typed: the ["answer"] call with '
               'the option\'s label), then add the detail as a new question through `protocol edit` instead of folding it into the '
               'picked one; the pick\'s record names that question.')  # answer first: an edit sends a typed question out again
THINK_MORE = 'Think more'  # a lean question's extra dialog choice: no answer, its checks rerun (r34-q171)
THINK_MORE_LINE = ('No answer yet: its checks redo it aiming for a strong recommendation, with a consumer walk and a probe, '
                   'then it comes back.')  # the consumer walk and the probe are the lean pass's (r38-q213)


def recommended_suffix(q: dict) -> str:
    """The mark on the recommended option's label in the dialog: ` (recommended, lean)`. A release approval has none: the
    engine asks it on every release, so a mark would say nothing about this one (r15 q58)."""
    return f" (recommended, {q['strength']})" if q.get('strength') else ''


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
