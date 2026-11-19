"""The report forms: one frozen dataclass per stdin form, the single owner of its field names, types and required/optional.

Validation (`problems`, `needs`), refusal text and `protocol help` (`render`) read these classes. Nested entries are forms too.
Prose (words.py) and rules across fields or against the round's state stay code at the call sites. No `from __future__ import
annotations`: field types are read at run time."""
import contextvars
from dataclasses import MISSING, dataclass, field, fields
from types import NoneType, UnionType
from typing import Literal, Union, get_args, get_origin

from .base import DROP_KINDS, LEAN_CAUSES, PASSES, REACHES, SCOPED_PASSES, STAGED_KINDS, STRENGTHS, TOUCHES, VERBS, ProtocolError


class Text(str):
    """A non-empty string (annotation only)."""


class Rows(list):
    """A non-empty list (annotation only)."""


FORMS: dict[str, type] = {}


def form(name: str, where: str = '', steps: tuple[str, ...] = (), nested: tuple[str, ...] = (), like: tuple[str, ...] = ()):
    """`where` prefixes its refusals; `steps`: the `<protocol> <step>` that take it; `nested`: forms of its entries, printed under it
    in help; `like`: forms whose fields it also carries."""
    def register(cls):
        cls = dataclass(frozen=True, kw_only=True)(cls)
        cls.name, cls.where, cls.steps, cls.nested, cls.like = name, where, steps, nested, like
        FORMS[name] = cls
        return cls
    return register


class Absent:
    """The default of an optional field: the attribute is never read, only whether a default exists."""
    def __repr__(self):
        return '<absent>'


ABSENT = Absent()


def req(note: str = '', key: str = '', group: str = '', of: str = ''):
    """A required field: `note` reads in help, `needs` and every refusal of the field; `key` is the stdin key where the attribute
    name cannot be (`pass`)."""
    return field(metadata={'note': note, 'key': key, 'group': group, 'of': of})


def opt(note: str = '', key: str = '', group: str = '', of: str = ''):
    return field(default=ABSENT, metadata={'note': note, 'key': key, 'group': group, 'of': of})


@dataclass(frozen=True)
class Spec:
    name: str
    type: object
    required: bool
    note: str
    group: str = ''
    of: str = ''  # the form of the entries (list items, or dict values) of a field whose type does not name it


def specs(cls) -> tuple[Spec, ...]:
    return tuple(Spec(f.metadata.get('key') or f.name, f.type, f.default is MISSING and f.default_factory is MISSING, f.metadata.get('note', ''),
                      f.metadata.get('group', ''), f.metadata.get('of', '')) for f in fields(cls))


def names(cls) -> tuple[str, ...]:
    return tuple(spec.name for spec in specs(cls))


def matches(value, tp) -> bool:
    origin = get_origin(tp)
    if isinstance(tp, type) and hasattr(tp, 'name') and tp.name in FORMS:
        return isinstance(value, dict) and not problems(tp, value)
    if tp is Text:
        return isinstance(value, str) and bool(value.strip())
    if tp is Rows or origin is Rows:
        return isinstance(value, list) and bool(value) and all(matches(item, get_args(tp)[0]) for item in value if get_args(tp))
    if origin is Literal:
        return value in get_args(tp)
    if origin in (Union, UnionType):
        return any(matches(value, one) for one in get_args(tp))
    if tp is NoneType:
        return value is None
    if origin is list or tp is list:
        return isinstance(value, list) and all(matches(item, get_args(tp)[0]) for item in value if get_args(tp))
    if origin is dict and get_args(tp):
        return isinstance(value, dict) and all(matches(k, get_args(tp)[0]) and matches(v, get_args(tp)[1]) for k, v in value.items())
    if tp is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if tp is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, origin or tp)


def describe(tp) -> str:
    origin = get_origin(tp)
    if tp is Text:
        return 'a non-empty string'
    if tp is Rows or origin is Rows:
        return 'a non-empty list' + (f' of {describe(get_args(tp)[0]).removeprefix("a ")}s' if get_args(tp) else '')
    if origin is Literal:
        return 'one of ' + ', '.join(get_args(tp))
    if origin in (Union, UnionType):
        parts = [describe(one) for one in get_args(tp) if one is not NoneType]
        return ' or '.join(parts) + (' or null' if NoneType in get_args(tp) else '')
    if origin is list and get_args(tp) == (str,):
        return 'a list of strings'
    if origin is list and get_args(tp):
        return f'a list of {describe(get_args(tp)[0]).removeprefix("a ")}s'
    if isinstance(tp, type) and hasattr(tp, 'name') and tp.name in FORMS:
        return f'a {tp.name} object'
    if origin is dict and get_args(tp):
        return 'an object of ' + describe(get_args(tp)[1]).replace('a ', '', 1) + 's'
    return {str: 'a string', int: 'a whole number', float: 'a number', bool: 'true or false', dict: 'an object', list: 'a list'}[origin or tp]


def fails(spec: Spec, report: dict, due: tuple[str, ...] = ()) -> bool:
    """Missing when required (or due), or of the wrong type. A null on an optional field counts as absent (`without_nulls`)."""
    if spec.name not in report:
        return spec.required or spec.name in due
    if report[spec.name] is None and not spec.required:
        return spec.name in due
    return not matches(report[spec.name], spec.type)


def holds(tp, found: list) -> None:
    """Append the form classes `tp` is made of to `found`."""
    if isinstance(tp, type) and getattr(tp, 'name', None) in FORMS and FORMS[tp.name] is tp:
        found.append(tp)
    for arg in get_args(tp):
        holds(arg, found)


def without_nulls(value, classes):
    """The parse-time null rule (r10-q30), by field type: a `| None` field takes null as a value; a null on any other optional
    field is dropped (absent); a required field keeps it and is refused. Recurses into nested forms; a `dict` field with an entry
    form holds entries keyed by any id. `classes`: the forms the object may be."""
    if isinstance(value, list):
        return [without_nulls(item, classes) for item in value]
    if not isinstance(value, dict):
        return value
    known = {}
    for cls in classes:
        for one in (cls, *(FORMS[n] for n in cls.like)):
            for spec in specs(one):
                known.setdefault(spec.name, []).append(spec)
    kept = {}
    for key, item in value.items():
        found = known.get(key)
        if found and item is None and all(not spec.required and NoneType not in flat(spec.type) for spec in found):
            continue
        entries = []
        for spec in found or ():
            holds(spec.type, entries)
            if spec.of:
                entries.append(FORMS[spec.of])
        if any(spec.of and spec.type is dict for spec in found or ()) and isinstance(item, dict):
            kept[key] = {name: without_nulls(entry, entries) for name, entry in item.items()}
        else:
            kept[key] = without_nulls(item, entries) if entries else item
    return kept


def flat(tp) -> list:
    return [tp, *(inner for arg in get_args(tp) for inner in flat(arg))]


CALLER: contextvars.ContextVar[str] = contextvars.ContextVar('protocol_verb', default='')  # the verb being run: its help is the pointer


def pointer(cls) -> str:
    """The running verb's help when it reaches the form, else the first verb's that does."""
    caller = CALLER.get()
    return f'see `protocol help {caller if cls.name in VERB_REACH.get(caller, ()) else VERB_OF[cls.name]}`'


def message(cls, spec: Spec) -> str:
    text = f'`{spec.name}` must be {describe(spec.type)}' + (f' ({spec.note})' if spec.note else '') + f'; {pointer(cls)}'
    return f'{cls.where}: {text}' if cls.where else text


def detail(spec: Spec, value) -> str:
    """The first problem inside the entries of a present value of a nested-form field."""
    entries = []
    holds(spec.type, entries)
    for index, item in enumerate(value if isinstance(value, list) else []):
        for form in entries:
            if isinstance(item, dict) and (found := problems(form, item)):
                return f' ({spec.name}[{index}]: {found[0]})'
    return ''


def problems(cls, report: dict, *only: str, due: tuple[str, ...] = ()) -> list[str]:
    """One refusal per field (the `only` ones, else all) missing or mistyped, with the first problem in its entries; `due`: optional
    fields the caller's rule makes required."""
    return [message(cls, spec) + (detail(spec, report[spec.name]) if spec.name in report else '')
            for spec in specs(cls) if (not only or spec.name in only) and fails(spec, report, due)]


def text_of(cls, name: str) -> str:
    return message(cls, next(spec for spec in specs(cls) if spec.name == name))


def needs(cls, report: dict, *only: str) -> str | None:
    """The refusal naming the form's whole stdin when any of the `only` fields (else all) fails."""
    if not any(fails(spec, report) for spec in specs(cls) if not only or spec.name in only):
        return None
    if inside := [spec for spec in specs(cls) if (not only or spec.name in only) and spec.name in report and detail(spec, report[spec.name])]:
        return problems(cls, report, inside[0].name)[0]  # an entry is wrong: say which, not that stdin is missing
    def named(spec: Spec) -> str:
        return f'"{spec.name}"' + (f' ({spec.note})' if spec.note else '')
    required = [named(spec) for spec in specs(cls) if spec.required]
    left = [f'"{spec.name}"' for spec in specs(cls) if not spec.required]
    if not required:
        return (f"{cls.where}: " if cls.where else '') + f"stdin takes only {', '.join(left)}; {pointer(cls)}"
    text = (', '.join(required[:-1]) + ' and ' if len(required) > 1 else '') + required[-1]
    return (f"{cls.where}: " if cls.where else '') + f'stdin needs {text}' + (
        f"; {', '.join(left)} {'is' if len(left) == 1 else 'are'} optional" if left else '') + f'; {pointer(cls)}'


def takers(key: str) -> list[str]:
    """The steps whose report names `key` as a field, else the verbs whose stdin does (a verb's own name counts: `defer`)."""
    found = [step for cls in FORMS.values() if key in names(cls) for step in cls.steps]
    if not found:  # a report meant for another step names that step, not the verbs that happen to share a field name
        found = [f'protocol {verb.name}' for verb in VERBS
                 if verb.name == key or any(key in names(FORMS[form]) and not FORMS[form].steps for form in verb.stdin)]
    return list(dict.fromkeys(found))


def unknown_keys(step: str, report: dict) -> tuple[dict[str, list[str]], list[str]]:
    """The keys of `report` the forms of the open `<protocol> <step>` do not name, each with the steps and verbs that take it, and
    the keys the step does take (r7-q26: a report meant for another step fails loudly instead of being dropped)."""
    accepted = list(dict.fromkeys(name for cls in FORMS.values() if step in cls.steps for name in names(cls)))
    return {key: takers(key) for key in report if key not in accepted}, accepted


def require(cls, report: dict, *only: str, due: tuple[str, ...] = ()) -> None:
    if found := problems(cls, report, *only, due=due):
        raise ProtocolError(found[0])


def require_all(cls, report: dict, *only: str) -> None:
    if found := problems(cls, report, *only):
        raise ProtocolError('; '.join(found))


def require_needs(cls, report: dict, *only: str) -> None:
    if found := needs(cls, report, *only):
        raise ProtocolError(found)


def render(cls) -> list[str]:
    head = f'{cls.name}' + (f' (step: {", ".join(cls.steps)})' if cls.steps else '')
    doc = ' '.join((cls.__doc__ or '').split())
    rows = [head, *([f'  {doc}'] if doc else []),
            *[f"    {s.name}: {describe(s.type)}, {'required' if s.required else 'optional'}" + (f'; {s.note}' if s.note else '')
              for s in specs(cls)]]
    return rows + [f'    nested: {line}' if i == 0 else f'    {line}' for name in cls.nested for i, line in enumerate(render(FORMS[name]))]


PASS_RUNS = (*PASSES, 'release-round')


# Verb stdin.

@form('start')
class Start:
    """Points pasted in for a round."""
    points: list = opt('each a string or {"text", "class"?, "owner"?}')


@form('answer')
class Answer:
    """The dialog's result (origin dialog), or the user's quoted words (model-reported)."""
    marker: Text = req('the issued batch')
    answers: dict[str, str] = opt('question text to answer string')
    annotations: dict = opt('question text to {"notes"}')
    response: str | None = opt()
    followUp: bool = opt()


@form('answer-chat', where='answer --origin chat')
class AnswerChat:
    """An answer the user typed in chat to any undecided question of the round; its quote must appear in a message the console relayed
    (after the question went out; for one not asked yet, in any message of the round). The record notes the checks it skipped."""
    question: Text = req('an id')
    answer: Text = req()
    quote: Text = req("the user's exact words")


@form('decline')
class Decline:
    """A batch the person did not answer."""
    marker: Text = req('the issued batch')
    partial: dict | None = opt('question text to answer string, or null')


@form('pass-run')
class PassRun:
    """A pass started, or /release-round typed or pressed."""
    command: Literal[PASS_RUNS] = req()
    args: str = opt('the argument the pass runs with')
    pending: str | None = opt("the pending pass's id, as stamped")


@form('defer', where='defer')
class Defer:
    """A question deferred at the user's request, with the questions waiting on it. Record files each on the board (bd defer);
    a round without a board only notes it."""
    question: Text = req()
    quote: Text = req("the user's exact words asking for it")
    until: str | None = opt('a date, an offset (+36h, +3d, +2w) or tomorrow')


@form('say', where='say')
class Say:
    """The person's message, stored for the chat quote check."""
    text: Text = req()


@form('dropped', where='dropped')
class Dropped:
    """A stale console action the console did not deliver. `id` goes with kind pass, `marker` with kind batch."""
    kind: Literal[DROP_KINDS] = req()
    id: Text = opt('with kind pass')
    marker: Text = opt('with kind batch')


@form('nudged', where='nudged')
class Nudged:
    """What the console did on the person's continue: queued the pending pass (`pass`, its id), reopened the batch (`batch`, its
    marker), or woke the model at the step (`step`, alone); `{}` when it did none of these."""
    pass_: Text = opt(key='pass')
    batch: Text = opt()
    step: Text = opt()


@form('scope', where='scope')
class Scope:
    """What a report of the pass starting now must cover; changes nothing."""
    command: Literal[PASSES] = req()
    pending: str | None = opt("the run's stamp: a pending id, or null")


@form('proposal', where='next --set', nested=('proposal-round',))
class Proposal:
    """The stored proposal of the next rounds."""
    rounds: list = opt('at most three rows, each as the proposal-round form below', of='proposal-round')


@form('proposal-round')
class ProposalRound:
    """One row of a proposal."""
    title: Text = req()
    summary: Text = req()
    estimate: dict = req('your estimate as whole numbers: {"questions": n, "unblocks": n}')
    why: Text = req()
    fresh: bool = req()
    ids: list[Text] = opt('the question ids that must lead')


# Entries nested in the forms above.

@form('option', where='')
class Option:
    """One option of a question. The dialog shows `description`; `example` is code under the option."""
    label: Text = req()
    description: str = opt()
    example: str = opt('code under the option; a preview is refused')
    for_: Text = req("what speaks for it", key='for')
    against: Text = req('what speaks against it')


@form('disclosure')
class Disclosure:
    """One of your own rulings, disclosed: asking.md Walk through; `why`: the ruling meets the goals without a material trade-off."""
    ruling: Text = req()
    why: Text = req()
    alternative: Text = req()
    fails: Text = req()
    evidence: Text = req()


@form('prior-ruling')
class PriorRuling:
    """A released ruling related to a strong question, challenged."""
    ruling: Text = req()
    verdict: Literal['holds', 'fails'] = req()
    why: Text = req()


@form('lean-because')
class LeanBecause:
    """What a lean rests on. A preference lean also says what you would have to value to pick another option."""
    cause: Literal[LEAN_CAUSES] = req()
    detail: Text = req()
    flipsIf: Text | None = opt('a preference lean: what you would have to value to pick another option')


@form('dropped-idea')
class DroppedIdea:
    """A distinct alternative considered and rejected during step-back."""
    idea: Text = req()
    why: Text = req('the constraint or evidence that rules it out')


@form('question', nested=('option', 'disclosure', 'prior-ruling', 'lean-because', 'dropped-idea'))
class Question:
    """A question as staged, or as a pass adds it."""
    text: Text = req('the dialog question; no number')
    title: Text = req('one pane row', group='presentation')
    header: Text = req('the dialog chip', group='presentation')
    options: list[Option] = req('2-4 objects with a label, a description and optionally an example (text)')
    multiSelect: bool = opt()
    kind: Literal[STAGED_KINDS] = opt('a staged question is a decision; the engine alone asks the release approval')
    board: str | None = opt('a board id, or null')
    waitsOn: list[str] | None = opt('the question ids it waits on; null clears them')
    waitsFor: Text | None = opt('the outside result it waits for and where it lands; null frees the question', group='scheduling')
    for_: str | None = opt('the pasted point it answers', key='for')
    settles: list[Text] | None = opt('selected keys: board ids or pasted point ids')
    holds: list[Text] | None = opt('board ids of the items this question holds up (blocks edges on its record); none or empty: it holds nothing up')
    premises: str | None = opt()
    problem: Text = req('what is decided and why now')
    root: Text = req('"<cause>; <end state>", or "does not apply: <why>" (a preference or naming question); record-only', group='presentation')
    cases: str | None = opt()
    rulings: list[Disclosure] | None = opt('your own rulings, each with ruling, why, alternative, fails, evidence')
    note: str | None = opt(group='presentation')
    recommendation: Text = req('an option label')
    strength: Literal[STRENGTHS] = req(group='presentation')
    leanBecause: LeanBecause | None = opt('required with a lean: {"cause": "preference" or "evidence", "detail", "flipsIf"? (a preference lean)}', group='presentation')
    strongBecause: dict | None = opt('required with a strong: each criterion "true: <evidence>"', group='presentation')
    priorRulings: list[PriorRuling] | None = opt('related released rulings, each {"ruling", "verdict": "holds" or "fails", "why"}')
    key: str = opt('a handle later updates of the same report use')
    dropped: list[DroppedIdea] = opt('distinct alternatives considered and rejected during step-back')


CONTENT = tuple(spec.name for spec in specs(Question) if spec.name != 'key')  # a change to any counts (asking.md Check)
# Shown or backed, not asked: an edit to these alone re-issues the batch without the check loop (plus an option's `example`).
PRESENTATION = tuple(spec.name for spec in specs(Question) if spec.group == 'presentation')
# When it goes out (r9-q33): setting a hold reruns no check; freeing one re-checks the question.
SCHEDULING = tuple(spec.name for spec in specs(Question) if spec.group == 'scheduling')


@form('update', nested=('question', 'disclosure'), like=('question',))
class Update:
    """A per-question update: `id` and the changed fields of the question form below (each optional here), or a new question
    (no `id`: its required fields; it goes last, or ahead of the question `before` names), or {"id", "remove": true, "reason"}.
    A removal that leaves a selected point with no question also needs `ruling`: the point is entailed, and your disclosed
    ruling covers it (the record, `show` and the walkthrough carry it)."""
    id: Text = opt()
    remove: bool = opt()
    reason: str = opt()
    ruling: Disclosure = opt('with `remove`: your own ruling that retires a point found entailed, as {"ruling", "why", "alternative", "fails", "evidence"}')
    before: str = opt('a question id')


@form('edit', where='edit', nested=('update',))
class Edit:
    """The user's requested change to the questions. No pass runs for wording, options or a mark lowered to lean; a new question
    or a changed recommendation gets the scoped check, a raise to strong one challenge."""
    updates: Rows[Update] = req('per-question updates as in a pass report')
    quote: Text = req("the user's exact words asking for it")


@form('challenge-ruling')
class ChallengeRuling(Disclosure):
    """An own ruling of the round, for challenge-rulings."""
    question: Text = req()
    sure: bool = req()


@form('own-ruling')
class OwnRuling(Disclosure):
    """An own ruling of the release set."""
    record: Text = req()
    sure: bool = req()


@form('record-entry')
class RecordEntry:
    """The record fields of one answered question."""
    rationale: Text = req('why the answer holds')
    ruleOwner: Text = req('where the rule is owned')
    reversal: str = opt('an away answer needs it')
    decision: str = opt('a revision needs it')


@form('change')
class Change:
    """A record's change: `unchanged`, or this."""
    change: Text = req('what changed')
    reach: Literal[REACHES] = req('unsure is spreads')
    why: Text = opt('contained: what no other ruling of the set or the board moves; otherwise it spreads')
    touches: Literal[TOUCHES] = opt('contained: own or decision')
    file: Text = opt('own: the path of the corrected record text')


@form('hit-row')
class HitRow:
    """A board hit and what to do about it."""
    item: Text = req()
    action: Text = req()


@form('supersede')
class Supersede:
    """A record that supersedes an earlier one."""
    old: Text = req('a `revises` hit')
    new: Text = req('a record of the set')
    partial: str | None = opt('the rule it supersedes in part')


@form('written-owner')
class WrittenOwner:
    """Owner entry {"written": {...}}: the rule is written in a file."""
    path: Text = req()
    anchor: str | None = opt()


@form('none-owner')
class NoOwner:
    """Owner entry {"none": {...}}: no owner."""
    reason: Text = req()


@form('pending-owner')
class PendingOwner:
    """Owner entry {"pending": {...}}: a board item will write it."""
    item: Text = req()


# Step reports.

@form('prepass', steps=('round prepass',))
class Prepass:
    """The pre-pass: a step-back over the whole point set."""
    pass_: str = req(key='pass')
    summary: Text = req('one line on what the pre-pass found')
    verdict: str | None = opt('with a --subject: its verdict')
    points: list = opt('a list of entries')


@form('collect', steps=('round collect',))
class Collect:
    """Classes for the open items and pasted points."""
    points: list = opt()
    classes: dict = opt('id to a class, or {"class", "owner"?}')


@form('select', steps=('round select',))
class Select:
    """The items the round takes up."""
    select: list[str] = req('candidate ids')


@form('stage', steps=('round stage',), nested=('question',))
class Stage:
    """The round's title and summary, and its questions (their fields: the Stage text)."""
    round: dict = opt('{"title", "summary", "overview"?}; required until the round has a title')
    questions: list = req('the questions, as the question form below', of='question')


@form('related', steps=('round related',))
class Related:
    """Each related hit's outcome."""
    outcomes: dict = req('question id to {hit id: outcome}')


@form('pass-report', steps=('round check', 'round ask'), nested=('update', 'challenge-ruling'))
class PassReport:
    """A pass's report. challenge-rulings adds `verdicts` and `rulings`."""
    pass_: Literal[PASSES] = opt('required in Check; in Ask a report with none re-issues the batch', key='pass')
    round: dict = opt()
    updates: list[Update] = opt('per-question updates')
    checked: dict = opt("required with a pass: per question id in this pass's scope what you examined in it this run, plus an optional `round` note")
    summary: str = opt()
    verdicts: dict = opt('challenge-rulings: each strong question in scope to {"strongBecause": {...}}')
    rulings: list = opt('challenge-rulings, required there: your own rulings, each as the challenge-ruling form below', of='challenge-ruling')


@form('settle', steps=('round ask',))
class Settle:
    """An away round's report: per ready question act on the recommendation or park."""
    settle: dict = req('question id to "act" or "park"')


@form('record', steps=('round record',), nested=('record-entry', 'update'))
class Record:
    """The record fields per answered question, or (not both) the held questions whose outside result landed."""
    records: dict = opt('question id to the record entry below', of='record-entry')
    updates: list[Update] = opt('a held question whose outside result landed: {"id", "waitsFor": null, "premises"?}; it is checked again and asked in this round, Record follows')


@form('recheck', steps=('release recheck',), nested=('change',))
class Recheck:
    """Per record in the set, `unchanged` or the change."""
    records: dict = req('record id to `unchanged`, or the change form below', of='change')


@form('board-check', steps=('release board-check',), nested=('hit-row', 'supersede', 'change'))
class BoardCheck:
    """The board hits of each record, and what they supersede and close."""
    checks: dict = req('each record to its hit classes')
    supersedes: list = opt('rows {"old", "new", "partial"?}', of='supersede')
    closes: dict = opt('question to the records answering it')
    changed: dict = opt('per record the change', of='change')


@form('own-rulings', steps=('release own-rulings',), nested=('own-ruling',))
class OwnRulings:
    """The lead's own rulings in the set."""
    rulings: list = req('every ruling you made in the set (an empty list when there is none)', of='own-ruling')


@form('scoped', steps=('release scoped',), nested=('change',))
class Scoped:
    """The scoped step-back, then ground, on the revised records."""
    pass_: Literal[SCOPED_PASSES] = req(key='pass')
    records: dict = req('record id to `unchanged`, or the change form below', of='change')
    summary: str = opt()


@form('owners', steps=('release owners',), nested=('written-owner', 'none-owner', 'pending-owner'))
class Owners:
    """Where each record's rule is owned."""
    owners: dict = req('each record to its owner entries')


VERB_OF: dict[str, str] = {}  # form -> first verb whose stdin reaches it (through `nested`)
VERB_REACH: dict[str, set] = {}  # verb -> forms its help prints


def resolve() -> None:
    for verb in VERBS:
        for name in verb.stdin:
            if name not in FORMS:
                raise ImportError(f'verb {verb.name}: stdin form {name!r} is not declared in schema.py')
        pending = list(verb.stdin)
        while pending:
            name = pending.pop()
            if name not in VERB_REACH.setdefault(verb.name, set()):
                VERB_REACH[verb.name].add(name)
                VERB_OF.setdefault(name, verb.name)
                pending += FORMS[name].nested


def verb_forms(verb: str, step: str = '') -> list:
    """The stdin forms of `verb`; given the open `<protocol> <step>`, only the form that step takes (all when none names it)."""
    forms = [FORMS[name] for name in next(v.stdin for v in VERBS if v.name == verb)]
    return [form for form in forms if step in form.steps] or forms if step else forms


resolve()
