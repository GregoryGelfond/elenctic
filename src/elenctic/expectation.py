"""The contract: in-file ``@``-annotations parsed into an ``Expectation``.

``Expectation`` is a sum of two well-formed shapes (``Unsat`` | ``Sat``) so illegal states
are unrepresentable: a parsed contract is structurally a valid one. ``parse(text)`` is
pure and total in the sense that every input either yields an ``Expectation`` or raises a
``ContractError`` naming what is wrong (and, given a ``source``, where) — it never silently
defaults or discards.

Four responsibilities:

- **One comment reader of record.** ``_comments`` is the only thing here that decides what a
  comment is, and it decides it as clingo's lexer does; both ``_tag_comments`` (behind the
  collection predicate) and ``_blocks`` (behind the parse) read it. The two must come from one
  reading: split them and either a trailing ``% @expect …`` is still never collected, or a file
  is collected and then told it declares no ``@expect`` while its author is looking straight at
  one.
- **Brace-bounded, contiguous continuation.** A litset may span continuation comments *while a
  brace remains unclosed*; once the brace closes, a following comment is prose (e.g. a
  ``% Run: …`` header), not part of the litset. The run must also be unbroken — each
  continuation on the line after the last — so a litset never absorbs a comment written on the
  far side of a rule. ``_blocks`` tracks both.
- **Provenance.** ``parse(text, source=None)`` carries ``source:line`` (or ``line N``)
  into every diagnostic; discovery passes the file path as ``source``.
- **Single source of truth via a typed builder.** Tags accumulate into a typed
  ``_Builder`` rather than an untyped state dict, so the construction of ``Sat`` needs no casts.

Litset tokenization delegates to clingo's term parser via ``terms``. The
*preconditions* (``optimal``/``@cost`` need an optimizing encoding; ``@assign`` needs clingcon;
a ``no``/``unknown`` ``@query`` needs the contrary literal shown) require the encoding/``#show``
set and so are checked at **discovery**, not here.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import Final, Literal, NoReturn, cast

from clingo import Symbol

from elenctic.query import Query, parse_query
from elenctic.registry import SOLVERS, Solver
from elenctic.terms import parse_litset, parse_term

__all__ = [
    "BEHAVIORAL_TAGS",
    "KNOWN_TAGS",
    "Claimed",
    "Contract",
    "ContractError",
    "Expectation",
    "Sat",
    "Unsat",
    "WitnessClaim",
    "has_contract",
    "parse",
    "parse_contract",
    "require_line",
    "require_tag",
]


class ContractError(Exception):
    """An ill-formed or inconsistent contract block. Carries source:line provenance."""


def require_line(line: int) -> None:
    """Reject a line that is not 1-based. The one home for the invariant every carrier of a
    contract coordinate shares — the claim, the two contract shapes, the check and the report it
    produces — so they cannot come to disagree about it. Public because the last two of those live
    in another module: the coordinate is a contract fact, so the predicate stays where the
    tokenizer that computes one does."""
    if line < 1:
        raise ValueError(f"a contract line is 1-based, got {line}")


def require_tag(label: str) -> None:
    """Reject a label that is not a contract tag. The companion of :func:`require_line`, and here
    for the same reason: a check and the report it produces both claim their label is the tag the
    claim was written with, and the report's label is what the published document calls ``tag``.

    The check enforced this and the report did not, which is the wrong way round — the report is the
    shape a consumer constructs when driving a case from a runner of their own, so it is the one
    place the invariant can actually be broken."""
    if not label.startswith("@"):
        raise ValueError(f"a check label must be a contract tag, got {label!r}")


@dataclass(frozen=True, slots=True)
class Claimed[T]:
    """A contract claim together with the 1-based line of the case file it was written on.

    The line is what lets a consumer put a diagnostic where the claim is, rather than against the
    file as a whole. It is required, not optional: a claim exists because someone wrote it
    somewhere, so a claim without a line would be a state the contract cannot be in. A claim
    brace-continued over several lines reports the line its tag opened on — one claim, one
    coordinate, and the tag is where a reader looks for it.

    Lines are counted by newlines alone, which is how clingo, a diff and a reviewer count them.
    That is narrower than Python's own ``str.splitlines``, which also breaks on a vertical tab, a
    form feed and several Unicode separators; resolving this coordinate with ``splitlines`` would
    point at the wrong line in a file containing any of them.

    This wraps a claim; it is not itself one. ``WitnessClaim`` is the other direction — a payload
    shape, the thing a ``@model`` cell holds — so ``Claimed[WitnessClaim]`` is a witness payload
    together with where it was written.
    """

    value: T
    line: int

    def __post_init__(self) -> None:
        require_line(self.line)


@dataclass(frozen=True, slots=True)
class WitnessClaim:
    """A witness cell's claim: the shown model and an optional joint theory binding.

    ``assign`` empty ⇒ a bare witness (``@model { L }``); non-empty ⇒ a ``where``-qualified joint
    witness (``@model { L } where { A }``), binding shown and assignment to one model. The
    expectation-side counterpart of the result-side ``ConsistentWitness`` (hence ``…Claim``). One
    cell holds one ``WitnessClaim``: ``assign`` empty (bare) or the ``where``-binding."""

    shown: frozenset[Symbol]
    assign: frozenset[tuple[Symbol, int]] = frozenset()


def _require_zero(claim: Claimed[int] | None, tag: str) -> None:
    """Reject a non-zero count on an unsat contract. ``@count n`` for ``n ≥ 1`` asserts a model
    exists, which is what ``@expect unsat`` denies; the cross-tag rule refuses the pair, and this is
    the same fact stated where the shape can no longer be built without it — the module's illegal
    states are unrepresentable, not merely rejected on one path in.

    It earns its place because the shape is *exported*: a consumer driving a case from a runner of
    their own constructs it directly, and a non-zero count there would derive a check that reads the
    census onto a witness solve, which is a routing fault reported as an elenctic bug rather than
    the contract error it is. ``ValueError`` for the reason :func:`require_line` gives — this is a
    consumer's bad argument, not a value elenctic built mid-solve."""
    if claim is not None and claim.value != 0:
        raise ValueError(
            f"@expect unsat admits only {tag} 0 (it asserts AS(P) = ∅), got {tag} {claim.value}"
        )


@dataclass(frozen=True, slots=True)
class Unsat:
    """``@expect unsat``: ``AS(P) = ∅``; excludes every model-bearing tag.

    ``expect_line`` is the 1-based line ``@expect`` was written on — the coordinate the check this
    shape's own claim derives carries.

    The two ``@count`` cells are the one thing an unsat contract may say besides ``@expect``, and
    they say it again: ``@count 0`` is ``|AS(P)| = 0`` and ``@count optimal 0`` is ``|Opt(P)| = 0``,
    both of which ``AS(P) = ∅`` already asserts (``_validate`` admits them only at 0, and only
    here). They are carried rather than folded into ``@expect`` because a claim is written on a line
    by an author who expects an answer against it: dropping a restatement would leave that line with
    no check, no report and no entry in the published document — a claim the contract makes and
    nothing answers."""

    expect_line: int
    count: Claimed[int] | None = None
    count_optimal: Claimed[int] | None = None
    notes: tuple[str, ...] = ()  # @note prose: documentation, not a contract term

    def __post_init__(self) -> None:
        require_line(self.expect_line)
        _require_zero(self.count, "@count")
        _require_zero(self.count_optimal, "@count optimal")


@dataclass(frozen=True, slots=True)
class Sat:
    """``@expect sat`` with its base-tagged claims, each carrying the line it was written on.

    ``None`` cells and empty consequence tuples mean "no such claim" — no run is derived and no
    check emitted for them. The ``all`` and ``optimal`` bases occupy distinct fields
    (the ``(mode, base)`` cells), so ``@model`` and ``@model optimal`` coexist.

    The single-valued cells hold one :class:`Claimed` each. The four consequence cells hold a
    *tuple* of claims in surface order rather than one merged set: two ``@cautious`` lines are two
    claims, each decided and reported against its own line. Checking them apart decides the case
    identically — for any set ``S``, ``L₁ ⊆ S`` and ``L₂ ⊆ S`` hold exactly when ``(L₁ ∪ L₂) ⊆ S``
    does, which is a fact about ⊆ and ∪ and so covers the ⋃ and Opt(P) readings as well as ⋂ —
    while letting a failure that turns on which claim was false name that claim's line.

    ``expect_line`` is a bare line rather than a :class:`Claimed` because the ``@expect`` value is
    what this shape *is*; only its coordinate is left to carry.
    """

    expect_line: int
    model: Claimed[WitnessClaim] | None = None
    optimal_model: Claimed[WitnessClaim] | None = None
    cautious: tuple[Claimed[frozenset[Symbol]], ...] = ()
    cautious_optimal: tuple[Claimed[frozenset[Symbol]], ...] = ()
    brave: tuple[Claimed[frozenset[Symbol]], ...] = ()
    brave_optimal: tuple[Claimed[frozenset[Symbol]], ...] = ()
    count: Claimed[int] | None = None
    count_optimal: Claimed[int] | None = None
    cost: Claimed[tuple[int, ...]] | None = None
    assign: Claimed[frozenset[tuple[Symbol, int]]] | None = None
    assign_optimal: Claimed[frozenset[tuple[Symbol, int]]] | None = None
    queries: tuple[Claimed[Query], ...] = ()
    notes: tuple[str, ...] = ()  # @note prose: documentation, not a contract term

    def __post_init__(self) -> None:
        require_line(self.expect_line)

    @property
    def has_optimal_base(self) -> bool:
        """Whether any *optimal*-base tag is present — ``@optimal`` (= ``@model optimal``),
        ``@cautious optimal``, ``@brave optimal``, ``@count optimal`` — the modes that share the one
        ``OPTIMAL_ENUM`` enumeration of ``Opt(P)``. The single home for optimal-base
        membership: ``run`` routes ``@cost``'s shared solve on it, and :attr:`requires_optimization`
        reads it (the relation lifted into the visible language, not two
        copy-pasted disjunctions)."""
        return (
            self.optimal_model is not None
            or bool(self.cautious_optimal)
            or bool(self.brave_optimal)
            or self.count_optimal is not None
            or self.assign_optimal is not None
        )

    @property
    def requires_optimization(self) -> bool:
        """Whether this contract presupposes an optimizing encoding: any optimal-base
        tag (:attr:`has_optimal_base`) or bare ``@cost``. Discovery checks it against
        ``#minimize``/``#maximize``/``:~``. Wider than :attr:`has_optimal_base` by exactly bare
        ``@cost`` — which presupposes optimization but rides the cheap ``OPTIMAL`` solve, not the
        shared ``OPTIMAL_ENUM``, so ``run`` routes on ``has_optimal_base`` while discovery gates on
        this."""
        return self.cost is not None or self.has_optimal_base

    @property
    def reads_all_answer_sets(self) -> bool:
        """Whether any tag here reads AS(P) *as a whole*: the bare-base census and consequence tags
        (``@model``, ``@count``, ``@assign``, ``@cautious``, ``@brave``) and every ``@query``, whose
        three-valued answer reads ⋂ (and ⋃) however it routes. The complement is deliberate:
        ``@expect sat`` reads only that *an* answer set exists, and the ``optimal`` base reads
        Opt(P), so neither is included.

        Discovery gates on this where AS(P) is not computable. The single home for AS(P)-reading
        membership, as :attr:`has_optimal_base` is for the optimal base; a test holds it to the runs
        ``run.runs_for`` actually derives, so the two cannot drift."""
        return (
            self.model is not None
            or self.count is not None
            or self.assign is not None
            or bool(self.cautious)
            or bool(self.brave)
            or bool(self.queries)
        )

    @property
    def requires_theory(self) -> bool:
        """Whether this contract presupposes a *theory* solver: ``@assign`` / ``@assign optimal``
        read the theory half of the observable, and a ``where``-qualified witness binds it jointly —
        all require clingcon. The precondition discovery checks against the case's solver."""
        return (
            self.assign is not None
            or self.assign_optimal is not None
            or (self.model is not None and bool(self.model.value.assign))
            or (self.optimal_model is not None and bool(self.optimal_model.value.assign))
        )


type Expectation = Unsat | Sat


@dataclass(frozen=True, slots=True)
class Contract:
    """A parsed contract: the behavioral ``Expectation`` and the *declared* solver (``None`` =
    undeclared → discovery defaults to ``clingo``). The solver lives here, not in ``Expectation``,
    because it is the case's interpretation/frame declaration, not a behavioral claim."""

    expectation: Expectation
    solver: Solver | None = None


def parse_contract(text: str, source: str | None = None) -> Contract:
    """Parse a ``.lp`` file's contract into a ``Contract``. One ``_blocks`` scan; a
    downstream router partitions the ``@elenctic`` directive namespace from the behavioral tags:
    behavioral tags build the ``Expectation`` via ``_apply``; ``@elenctic`` blocks are
    interpreted into the declared solver (total, loud, provenance-carrying).

    Pure. A malformed behavioral payload (a ``ValueError`` from the term/litset layer, or a
    duplicate-cell ``ValueError`` here) is surfaced as a ``ContractError`` carrying the tag's
    ``source:line``; a malformed directive is a ``ContractError`` from the interpreter. Cross-tag
    well-formedness is checked once the builder is complete.
    """
    builder = _Builder()
    solver_blocks: list[_Block] = []
    for block in _blocks(text, source):
        if block.tag == "elenctic":
            solver_blocks.append(block)  # routed to the directive interpreter, not _apply
            continue
        try:
            _apply(block, builder)
        except (ValueError, RuntimeError) as exc:
            raise ContractError(f"{_location(source, block.line)}: {exc}") from exc
    solver = _interpret_directives(solver_blocks, source)
    return Contract(expectation=_finish(builder, source), solver=solver)


def parse(text: str, source: str | None = None) -> Expectation:
    """Parse a ``.lp`` file's behavioral contract into an ``Expectation``. The
    declared solver is dropped; directive well-formedness is still validated (``parse_contract``
    interprets ``@elenctic`` regardless)."""
    return parse_contract(text, source).expectation


# The one v1 sub-directive: `@elenctic solver <name>`. The keyword `solver` at a word boundary,
# then the rest is the solver name (membership-checked against the registry).
_SOLVER_DIRECTIVE = re.compile(r"^solver\b(?P<rest>.*)$", re.S)


def _interpret_directives(blocks: list[_Block], source: str | None) -> Solver | None:
    """Interpret the ``@elenctic`` directive blocks into the declared solver. Total: every block
    is a known sub-directive or a loud ``ContractError`` with
    provenance. v1 has one sub-directive, ``solver``; an unknown one errors (closed vocabulary)."""
    solver: Solver | None = None
    for block in blocks:
        if (match := _SOLVER_DIRECTIVE.match(block.payload)) is None:
            sub = block.payload.split(maxsplit=1)[0] if block.payload.strip() else "(empty)"
            _fail_at(source, block.line, f"unknown @elenctic directive {sub!r} (known: solver)")
        name = match.group("rest").strip()
        if not name:
            _fail_at(source, block.line, "@elenctic solver needs a solver name (e.g. clingo)")
        if name not in SOLVERS:
            known = ", ".join(sorted(SOLVERS))
            _fail_at(source, block.line, f"unknown solver {name!r} (known: {known})")
        if solver is not None:
            _fail_at(source, block.line, "at most one @elenctic solver per contract")
        solver = cast(Solver, name)  # membership-checked against SOLVERS, which is exactly Solver
    return solver


# --- the comment lexis ---

# The contract channel is comments, so what elenctic reads as an annotation has to be exactly what
# clingo reads as a comment: a divergence is either a contract nobody reading the file believes is
# in force, or one nobody knows is missing. Four constructs decide it, each measured against clingo:
#
#   `%` … end of line    a line comment.
#   `%*` … `*%`          a block comment, and it NESTS. A `%` inside opens a line comment — part of
#                        the block, not a comment of its own — so a `*%` standing after one on the
#                        same line does not close the block. An unterminated block is a lexer error
#                        for which clingo reports no comment at all, so neither does this.
#   `"` … `"`            a string term, in which a `%` is inert. `\` escapes the next character but
#                        cannot carry the string across a newline; where the closing quote is
#                        missing clingo reports the error at the opening quote and resumes right
#                        after it, so the rest of that line is ordinary input.
#   `#script` … `#end`   a script body, opaque — a `%` in it is program text. The opener needs the
#                        parenthesized language name (`#script`, whitespace, `(`); a bare `#script`
#                        opens nothing. The closer is the literal `#end`, with no word boundary and
#                        no dot: `#end % c` with the `.` on the next line lexes cleanly, and `% c`
#                        is a comment.
_SCRIPT_OPEN = "#script"
_SCRIPT_CLOSE = "#end"

# clingo's lexer takes exactly these four as whitespace. `str.isspace` is a different claim — it
# also takes `\v` and `\f`, which clingo rejects between `#script` and its `(`.
_SPACE = " \t\r\n"


@dataclass(frozen=True, slots=True)
class _Comment:
    """One comment as clingo's lexer sees it: the 1-based line it opens on, its text with the
    delimiters removed, which of the two forms it takes, and whether anything but whitespace
    precedes it on its line — which is what separates a comment line from a comment trailing a
    rule, and clingo has no opinion about it because clingo does not read contracts."""

    line: int
    body: str
    block: bool
    starts_line: bool


@dataclass(frozen=True, slots=True)
class _Unterminated:
    """The construct that was left open and so swallowed the rest of the file: which one, and the
    1-based line it opened on."""

    construct: str
    line: int


@dataclass(frozen=True, slots=True)
class _Lexis:
    """A file's comments, and whether the reading ran out before the file did.

    Running out is a fact about the file rather than a limit of this reader — an unterminated
    ``%*`` or ``#script`` swallows everything below it, for clingo exactly as here — and it is
    kept rather than discarded because the two answers differ in kind. *No comments here* and *I
    could not read past line N* both leave the comment list short, and only the second is a reason
    to refuse a file rather than file it away as a library."""

    comments: list[_Comment]
    unterminated: _Unterminated | None


def _lex(text: str) -> _Lexis:
    r"""Every comment in ``text``, in order, read as clingo reads them.

    Total: it cannot raise, does no I/O and does not invoke clingo. That is what lets it serve
    ``has_contract``, which must classify a file that does not parse — and must do so without
    opening whatever path an ``#include`` in that file happens to name.

    Single-pass and per-character, with no per-line rescan and no per-line copy: this runs before
    clingo is invoked and before any budget exists, so nothing else would stop superlinear work.
    Lines are counted on ``\n`` alone, which is where clingo ends one; ``str.splitlines`` would
    also break on ``\v``, ``\f``, the separators and ``\x85``, and a tag beyond one of those is a
    contract nobody reviewing the file can see.
    """
    found: list[_Comment] = []
    unterminated: _Unterminated | None = None
    line, position, end = 1, 0, len(text)
    blank = True  # every character since this line began has been whitespace
    while position < end:
        character = text[position]
        if character == "%":
            read = _read_comment(text, position, line, starts_line=blank)
            if read is None:
                unterminated = _Unterminated("%*", line)
                break
            comment, after = read
            found.append(comment)
            blank = False
        elif character == '"':
            after, blank = _past_string(text, position), False
        elif character == "#" and _opens_script(text, position):
            closed = _past_script(text, position)
            if closed is None:
                unterminated = _Unterminated(_SCRIPT_OPEN, line)
                break
            after, blank = closed, False
        else:
            blank = character == "\n" or (blank and character in _SPACE)
            after = position + 1
        line += text.count("\n", position, after)
        position = after
    return _Lexis(found, unterminated)


def _read_comment(
    text: str, position: int, line: int, *, starts_line: bool
) -> tuple[_Comment, int] | None:
    """The comment opening at ``position`` (a ``%``) and where lexing resumes after it, or ``None``
    for an unterminated ``%*``: that is a lexer error, and clingo reports no comment for it — the
    tail of such a file is not annotation, in either reading."""
    if not text.startswith("%*", position):
        end_of_line = text.find("\n", position)
        end_of_line = len(text) if end_of_line < 0 else end_of_line
        # A lone `\r` neither ends a comment nor a line — only `\n` does, for clingo as here — but
        # a `\r` run at the end of one is the CRLF terminator rather than comment text, and clingo
        # drops it. Interior carriage returns are text to both, and a block comment keeps its own.
        body = text[position + 1 : end_of_line].rstrip("\r")
        return _Comment(line, body, block=False, starts_line=starts_line), end_of_line
    scan = _past_block(text, position)
    if scan is None:
        return None
    body = text[position + 2 : scan - 2]
    return _Comment(line, body, block=True, starts_line=starts_line), scan


def _past_block(text: str, position: int) -> int | None:
    """Where lexing resumes after the block comment opening at ``position`` (a ``%*``), or ``None``
    where it is never closed and so runs to end of input.

    A ``%`` inside a block opens a line comment, exactly as one outside does, so a ``*%`` standing
    after one on the same line does not close the block: ``%* a % b *%`` reaches end of input still
    open, and is no comment at all."""
    depth, scan, end = 1, position + 2, len(text)
    while scan < end and depth > 0:
        if text.startswith("%*", scan):
            depth, scan = depth + 1, scan + 2
        elif text.startswith("*%", scan):
            depth, scan = depth - 1, scan + 2
        elif text[scan] == "%":
            end_of_line = text.find("\n", scan)
            scan = end if end_of_line < 0 else end_of_line
        else:
            scan += 1
    return None if depth > 0 else scan


def _past_string(text: str, position: int) -> int:
    """Where lexing resumes after the string term opening at ``position`` (a ``"``) — past its
    closing quote, or, when it has none before the newline, at the character after the opening one,
    which is where clingo resumes having reported the error there."""
    scan, end = position + 1, len(text)
    while scan < end and text[scan] != "\n":
        if text[scan] == '"':
            return scan + 1
        # A backslash escapes the next character but never the newline: a string may not span one.
        scan += 2 if text[scan] == "\\" and scan + 1 < end and text[scan + 1] != "\n" else 1
    return position + 1


def _opens_script(text: str, position: int) -> bool:
    """Whether a script body opens at ``position``: ``#script``, whitespace, then the parenthesized
    language name. A bare ``#script`` is not an opener, and clingo takes no comment in between."""
    if not text.startswith(_SCRIPT_OPEN, position):
        return False
    scan = position + len(_SCRIPT_OPEN)
    while scan < len(text) and text[scan] in _SPACE:
        scan += 1
    return scan < len(text) and text[scan] == "("


def _past_script(text: str, position: int) -> int | None:
    """Where lexing resumes after the script body ``_opens_script`` found at ``position`` — right
    past its ``#end`` — or ``None`` where it has none and so runs to end of input. The body is
    opaque, so the search runs over its raw text: an ``#end`` inside a string in the script's own
    language still closes it."""
    language = text.index("(", position)  # `_opens_script` has established that this is here
    closed = text.find(_SCRIPT_CLOSE, language)
    return None if closed < 0 else closed + len(_SCRIPT_CLOSE)


# --- block tokenization (brace-bounded, contiguous continuation) ---

# A contract annotation is a comment whose body reads `@<tag> <payload>`; a continuation is the
# comment on the line immediately after, absorbed while the preceding tag's litset brace is still
# open. A tag is tried first, so a comment that reads as one is a tag and not a continuation; a
# litset element that would be captured that way is refused by the term layer in any case, so the
# ordering costs a loud diagnostic and never a silent reading. Both patterns read a comment *body*,
# so neither carries a `%` or a line anchor, and both are applied only to a line comment: a tag
# inside `%* … *%` is one the author has visibly commented out.
_TAG = re.compile(r"^\s*@(?P<tag>\w+)\b(?P<rest>.*)$")

# A comment whose body begins with a `where {` clause (the keyword then a brace) — the dangling-
# witness shape. NOT merely the word "where" (an ordinary `% where the cost is…` prose comment, no
# brace, stays a comment). When such a comment is not absorbed by an open brace it is a loud error.
_DANGLING_WHERE = re.compile(r"^\s*where\s*\{")

# Only these tags carry a brace-delimited litset/tupleset, so only they may span a continuation.
# Gating on the tag keeps the continuation invariant honest ("join an unfinished *litset*", not
# "join while any brace is unbalanced"): a stray '{' in @note/@expect prose stays single-line.
_LITSET_TAGS = frozenset({"model", "optimal", "cautious", "brave", "cost", "assign", "query"})

# The behavioral contract tags (each handled by `_apply`); the `@elenctic` directive namespace is
# routed separately (the single-tokenizer router). KNOWN_TAGS is the closed vocabulary and the
# single source for: collection, the closed-vocab typo check in `_apply`, and the router.
BEHAVIORAL_TAGS: Final[frozenset[str]] = frozenset(
    {"expect", "model", "optimal", "cautious", "brave", "count", "cost", "assign", "query", "note"}
)
KNOWN_TAGS: Final[frozenset[str]] = BEHAVIORAL_TAGS | {"elenctic"}


@dataclass(frozen=True, slots=True)
class _Block:
    """One contract annotation: its tag, its (continuation-joined) payload, and its 1-based line."""

    tag: str
    payload: str
    line: int


def _blocks(text: str, source: str | None = None) -> list[_Block]:
    """Tokenize the contract annotation(s) into ``_Block``s, joining continuation comments into the
    preceding tag's payload *only while its brace is unclosed and the run of comment lines is
    unbroken* (prose after a closed litset is left alone, and so is a comment on the far side of a
    rule). A comment that begins a ``where { … }`` clause but is not absorbed by an open brace is a
    *dangling witness* — a loud ``ContractError`` with provenance, never silently dropped, wherever
    in the file it stands and whatever tag came before it."""
    lexis = _lex(text)
    if lexis.unterminated is not None:
        _refuse_unterminated(lexis.unterminated, source)
    blocks: list[_Block] = []
    fragments: list[str] = []  # the open litset's payload, kept unjoined until its brace closes
    depth = 0
    in_quote = False
    continues_at = 0  # the line the open litset's next continuation must stand on; no line is 0

    def close() -> None:
        """Join the open litset's fragments into its block and forget the open state."""
        nonlocal fragments, depth, in_quote
        if fragments:
            blocks[-1] = replace(blocks[-1], payload=" ".join(fragments).strip())
        fragments, depth, in_quote = [], 0, False

    for comment in lexis.comments:
        if comment.block:
            continue  # `%* … *%` is how an author turns a contract off, not how they write one
        if comment.line != continues_at or not comment.starts_line:
            # A contract annotation is a contiguous run of comment *lines*, so anything else ends
            # one: a comment further down the file, and equally one trailing a rule on the very
            # next line, where the rule stands between the two halves of a litset just as surely
            # as it would on a line of its own.
            #
            # The asymmetry with the tag itself is deliberate. A tag names itself — `@word` — so
            # it is unambiguous wherever it stands, trailing a rule included, which is the whole
            # of the trailing-tag repair. A continuation names nothing: it is ordinary text that
            # means something only because of where it sits. Where the information separating a
            # continuation from a remark is not in the line, the settled principle takes the
            # refusal, and a brace left open fails loudly at `_base_litset`.
            close()
        if (tag := _TAG.match(comment.body)) is not None:
            close()
            payload = tag.group("rest").strip()
            blocks.append(_Block(tag.group("tag"), payload, comment.line))
            if tag.group("tag") in _LITSET_TAGS:
                depth, in_quote = _scan_braces(payload, 0, False)
                if depth > 0:
                    fragments, continues_at = [payload], comment.line + 1
        elif depth > 0:
            # The open brace is tracked as the payload grows rather than re-derived from the whole
            # payload per line, and the pieces are joined once at the end rather than copied per
            # line. Both were quadratic in the continued region, and this scan runs before clingo
            # is invoked and before any budget exists, so nothing else would have stopped it.
            piece = comment.body.strip()
            fragments.append(piece)
            depth, in_quote = _scan_braces(piece, depth, in_quote)
            continues_at = comment.line + 1
            if depth <= 0:
                close()
        elif _DANGLING_WHERE.match(comment.body):
            # Reached once the litset's brace has closed, or once the run of comment lines has
            # been broken — the continuation branch above absorbs a clause written while a brace
            # is open on the next line, which is the placement that works. No condition on what
            # came before: a stranded clause costs the author the same binding whether the tag
            # above it is a witness, a `@note`, or nothing at all.
            #
            # It costs a comment line that opens `where {` and meant nothing by it — set-builder
            # notation in prose. That is the right way round to be wrong: the alternative reads
            # further along the line to guess which was meant, and every such rule is a character
            # away from letting a real clause through. `% where { v=1 }.` — a clause and a full
            # stop — is the shape that decided it, since dropping that one is a wrong answer
            # while refusing a comment is a refusal the author can answer.
            raise ContractError(
                f"{_location(source, comment.line)}: dangling `where`: a `where {{ … }}` clause "
                "qualifies a @model / @optimal witness — write it on that tag's litset-closing "
                "line, or on a continuation line while the litset's brace is still open"
            )
    close()  # a brace still open at end of input keeps whatever was gathered under it
    return blocks


def _refuse_unterminated(unterminated: _Unterminated, source: str | None) -> NoReturn:
    """Refuse a file whose comment structure never closes, naming the construct and where it
    opened. The refusal is the point: everything below the opener is inside it, so a contract there
    is not in force — and clingo cannot read the file either, so nothing is refused here that would
    otherwise have run."""
    remedy = (
        "close it with `*%` — and note that a `%` inside a block opens a line comment, so a `*%` "
        "standing after one on the same line is inside that comment and does not close the block"
        if unterminated.construct == "%*"
        else "close it with `#end.`"
    )
    _fail_at(
        source,
        unterminated.line,
        f"unterminated `{unterminated.construct}`: it runs to the end of the file, so anything "
        f"below it is inside it and no contract there is in force — {remedy}",
    )


def _tag_comments(comments: list[_Comment]) -> Iterator[_Block]:
    """Yield one ``_Block`` per ``@tag`` comment (tag + raw rest + 1-based line), with no
    continuation join and no raises — the lexical tag-recognition (the shared ``_TAG`` pattern)
    that ``has_contract`` reads. Continuation / dangling-``where`` handling lives in ``_blocks``;
    both read ``_lex`` and then ``_TAG``, so there is one comment reader of record and one tag
    recognizer of record."""
    for comment in comments:
        if not comment.block and (tag := _TAG.match(comment.body)) is not None:
            yield _Block(tag.group("tag"), tag.group("rest").strip(), comment.line)


def has_contract(text: str) -> bool:
    """Whether ``text`` carries a contract — the collection predicate: a ``.lp`` file is a
    **case** iff it contains at least one known elenctic tag, else a **library** (an ``#include``
    target, never run directly). Content-keyed, not filename-keyed (the "pytest-shaped" surface is
    the *invocation*, not pytest's filename collection). An unknown ``@word`` in a tag-free file is
    just prose (a library, no error); a known tag with a missing ``@expect`` is still a case (it
    fails loud at ``parse``, never silently reclassified — loud over silent).

    Never raises, and never invokes clingo: it must answer for every ``.lp`` file in the tree,
    libraries included, and a file that cannot be parsed still has a plain answer to *what is
    written in it* — with one exception, which is why the reading reports it. Where an
    unterminated ``%*`` or ``#script`` swallows the rest of the file, there is no such answer:
    everything below the opener is unread. Answering **library** there would file the case away on
    the strength of the part that could not be read, and a library nothing runs is silent — the
    author's contract would never run and the corpus would still come back green. So such a file
    is a case, and ``parse_contract`` says what is wrong with it."""
    lexis = _lex(text)
    return lexis.unterminated is not None or any(
        block.tag in KNOWN_TAGS for block in _tag_comments(lexis.comments)
    )


def _scan_braces(fragment: str, depth: int, in_quote: bool) -> tuple[int, bool]:
    """Carry brace depth and quote state across ``fragment``, continuing from where the previous
    one left off. Braces inside double-quoted string terms do not count.

    Taking the state in and handing it back is what lets a payload gathered over many lines be
    scanned once in total rather than once per line."""
    for char in fragment:
        if char == '"':
            in_quote = not in_quote
        elif not in_quote:
            depth += (char == "{") - (char == "}")
    return depth, in_quote


# --- the typed builder and per-tag dispatch ---


@dataclass(slots=True)
class _Builder:
    """Mutable accumulator for one contract's tags; ``_finish`` freezes it into an ``Expectation``.

    A single-valued ``(mode, base)`` cell is realized as a field that starts ``None``
    and whose second assignment is the violation — the field *is* the record of whether
    the cell is occupied, so no separate bookkeeping is needed. Consequence/query/prose tags
    accumulate. Every cell but the prose one holds its claim wrapped in a :class:`Claimed`, so the
    line a tag was written on survives the freeze into an ``Expectation``.
    """

    expect: Claimed[Literal["sat", "unsat"]] | None = None
    model: Claimed[WitnessClaim] | None = None
    optimal_model: Claimed[WitnessClaim] | None = None
    cautious: list[Claimed[frozenset[Symbol]]] = field(default_factory=list)
    cautious_optimal: list[Claimed[frozenset[Symbol]]] = field(default_factory=list)
    brave: list[Claimed[frozenset[Symbol]]] = field(default_factory=list)
    brave_optimal: list[Claimed[frozenset[Symbol]]] = field(default_factory=list)
    count: Claimed[int] | None = None
    count_optimal: Claimed[int] | None = None
    cost: Claimed[tuple[int, ...]] | None = None
    assign: Claimed[frozenset[tuple[Symbol, int]]] | None = None
    assign_optimal: Claimed[frozenset[tuple[Symbol, int]]] | None = None
    queries: list[Claimed[Query]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _apply(block: _Block, builder: _Builder) -> None:
    """Apply one contract block to the builder, enforcing per-cell single-valuedness.

    Raises ``ValueError`` on a malformed payload or a duplicated single-valued cell; ``parse``
    attaches ``source:line`` provenance.
    """
    rest = block.payload
    match block.tag:
        case "expect":
            if builder.expect is not None:
                raise ValueError("at most one @expect per contract")
            builder.expect = Claimed(_expect_value(rest), block.line)
        case "model":
            litset_text, assign = _split_where(rest)
            is_optimal, litset = _base_litset(litset_text)
            claim = WitnessClaim(shown=litset, assign=assign)
            if is_optimal:
                _set_optimal_model(builder, claim, block.line)
            elif builder.model is not None:
                raise ValueError("at most one @model per contract (the 'all' base)")
            else:
                builder.model = Claimed(claim, block.line)
        case "optimal":  # sugar: @optimal ≡ @model optimal
            litset_text, assign = _split_where(rest)
            _set_optimal_model(
                builder, WitnessClaim(shown=_litset(litset_text), assign=assign), block.line
            )
        case "cautious":
            is_optimal, litset = _base_litset(rest)
            target = builder.cautious_optimal if is_optimal else builder.cautious
            target.append(Claimed(litset, block.line))
        case "brave":
            is_optimal, litset = _base_litset(rest)
            target = builder.brave_optimal if is_optimal else builder.brave
            target.append(Claimed(litset, block.line))
        case "count":
            is_optimal, n = _base_int(rest)
            if is_optimal:
                if builder.count_optimal is not None:
                    raise ValueError("at most one @count optimal per contract")
                builder.count_optimal = Claimed(n, block.line)
            elif builder.count is not None:
                raise ValueError("at most one @count per contract (the 'all' base)")
            else:
                builder.count = Claimed(n, block.line)
        case "cost":
            if builder.cost is not None:
                raise ValueError("at most one @cost per contract")
            builder.cost = Claimed(_cost_vector(rest), block.line)
        case "assign":
            is_optimal, bindings = _base_assign(rest)
            if is_optimal:
                if builder.assign_optimal is not None:
                    raise ValueError("at most one @assign optimal per contract")
                builder.assign_optimal = Claimed(bindings, block.line)
            elif builder.assign is not None:
                raise ValueError("at most one @assign per contract (the 'all' base)")
            else:
                builder.assign = Claimed(bindings, block.line)
        case "query":
            builder.queries.append(Claimed(_query(rest), block.line))
        case "note":
            builder.notes.append(rest)
        case _:
            raise ValueError(f"unknown contract tag: @{block.tag} (known: {sorted(KNOWN_TAGS)})")


def _set_optimal_model(builder: _Builder, claim: WitnessClaim, line: int) -> None:
    """Set the optimal-witness cell, shared by ``@optimal`` and ``@model optimal``."""
    if builder.optimal_model is not None:
        raise ValueError("at most one @optimal / @model optimal per contract (the same cell)")
    builder.optimal_model = Claimed(claim, line)


# --- payload parsers (each raises ValueError; parse wraps with provenance) ---

_BASE_LITSET = re.compile(r"^(?P<base>optimal\s+)?\{(?P<body>.*)\}$", re.S)
_LITSET = re.compile(r"^\{(?P<body>.*)\}$", re.S)
_BASE_INT = re.compile(r"^(?P<base>optimal\s+)?(?P<n>\d+)$")
_COST = re.compile(r"^\{\s*(?P<ints>-?\d+(?:\s+-?\d+)*)\s*\}$")
_BIND = re.compile(r"^(?P<term>.+?)\s*=\s*(?P<value>-?\d+)$")
# A `where { … }` suffix on a witness payload, split BEFORE the litset braces so the greedy litset
# regex never swallows it; the keyword `where` immediately preceding `{` is the marker.
_WHERE_SPLIT = re.compile(r"\bwhere\s*(?P<where>\{.*\})\s*$", re.S)


def _expect_value(rest: str) -> Literal["sat", "unsat"]:
    match rest.strip():
        case "sat":
            return "sat"
        case "unsat":
            return "unsat"
        case other:
            raise ValueError(f"@expect must be sat|unsat, got: {other!r}")


def _base_litset(rest: str) -> tuple[bool, frozenset[Symbol]]:
    """Parse ``[optimal] { litset }`` into ``(is_optimal, literals)``."""
    if (match := _BASE_LITSET.match(rest.strip())) is None:
        raise ValueError(f"expected [optimal] {{ litset }}, got: {rest!r}")
    return bool(match.group("base")), frozenset(parse_litset(match.group("body").strip()))


def _litset(rest: str) -> frozenset[Symbol]:
    """Parse a base-less ``{ litset }`` (for ``@optimal``, which carries no base qualifier)."""
    if (match := _LITSET.match(rest.strip())) is None:
        raise ValueError(f"expected {{ litset }}, got: {rest!r}")
    return frozenset(parse_litset(match.group("body").strip()))


def _base_int(rest: str) -> tuple[bool, int]:
    """Parse ``[optimal] n`` (``n ≥ 0``) into ``(is_optimal, n)`` for ``@count``."""
    if (match := _BASE_INT.match(rest.strip())) is None:
        raise ValueError(f"@count expects [optimal] <non-negative int>, got: {rest!r}")
    return bool(match.group("base")), int(match.group("n"))


def _cost_vector(rest: str) -> tuple[int, ...]:
    """Parse ``{ c1 c2 … }`` into the priority-ordered cost vector (``@cost``)."""
    if (match := _COST.match(rest.strip())) is None:
        raise ValueError(f"@cost expects {{ <int> … }}, got: {rest!r}")
    return tuple(int(component) for component in match.group("ints").split())


def _base_assign(rest: str) -> tuple[bool, frozenset[tuple[Symbol, int]]]:
    """Parse ``[optimal] { term=int, … }`` into ``(is_optimal, bindings)`` for ``@assign``."""
    stripped = rest.strip()
    if (match := re.match(r"^optimal\s+", stripped)) is not None:
        return True, _assign_body(stripped[match.end() :])
    return False, _assign_body(stripped)


def _split_where(rest: str) -> tuple[str, frozenset[tuple[Symbol, int]]]:
    """Split an optional ``where { binds }`` suffix off a witness payload, before the litset braces.
    Returns ``(litset_text, assign)``; ``assign`` is empty when there is no ``where`` (a bare
    witness). An empty ``where { }`` is rejected with a where-specific diagnostic; ``parse`` adds
    the ``source:line`` provenance."""
    stripped = rest.strip()
    if (match := _WHERE_SPLIT.search(stripped)) is None:
        return stripped, frozenset()
    if not match.group("where")[1:-1].strip():
        raise ValueError("empty where { }: a where-clause needs at least one term=int binding")
    return stripped[: match.start()].strip(), _assign_body(match.group("where"))


def _assign_body(rest: str) -> frozenset[tuple[Symbol, int]]:
    """Parse ``{ term=int, … }`` into theory bindings for ``@assign``.

    Rejects an empty set: the grammar requires ≥1 binding, and an empty ``@assign`` would be a
    silent vacuous claim (``frozenset() ⊆ assign`` holds for every model) — the empty-litset
    false-PASS, here in the one payload parser that does not route through ``parse_litset``.
    """
    bindings = [_one_bind(piece.strip()) for piece in _split_top(_braced(rest)) if piece.strip()]
    if not bindings:
        raise ValueError("empty @assign set: needs at least one term=int binding")
    return frozenset(bindings)


def _one_bind(piece: str) -> tuple[Symbol, int]:
    if (match := _BIND.match(piece)) is None:
        raise ValueError(f"bad @assign binding (expected term=int): {piece!r}")
    return parse_term(match.group("term").strip()), int(match.group("value"))


def _query(rest: str) -> Query:
    """Split ``<answer> <payload>`` and delegate to ``query.parse_query``."""
    answer, _, payload = rest.strip().partition(" ")
    if not payload.strip():
        raise ValueError(f"@query needs an answer and a payload: {rest!r}")
    return parse_query(answer.strip(), payload.strip())


def _braced(rest: str) -> str:
    stripped = rest.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        raise ValueError(f"expected a brace set, got: {rest!r}")
    return stripped[1:-1].strip()


def _split_top(body: str) -> list[str]:
    """Split on top-level commas, paren-aware so a comma inside a term is not a separator."""
    pieces: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(body):
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == "," and depth == 0:
            pieces.append(body[start:index])
            start = index + 1
    pieces.append(body[start:])
    return pieces


# --- cross-tag well-formedness and the freeze ---


def _finish(builder: _Builder, source: str | None) -> Expectation:
    """Validate the cross-tag rules and freeze the builder into an ``Expectation``."""
    expect = _validate(builder, source)
    if expect.value == "unsat":
        # `_validate` has already established that the only cells an unsat contract can carry
        # besides the prose are these two, and that each is 0 where it is present.
        return Unsat(
            expect_line=expect.line,
            count=builder.count,
            count_optimal=builder.count_optimal,
            notes=tuple(builder.notes),
        )
    return Sat(
        expect_line=expect.line,
        model=builder.model,
        optimal_model=builder.optimal_model,
        cautious=tuple(builder.cautious),
        cautious_optimal=tuple(builder.cautious_optimal),
        brave=tuple(builder.brave),
        brave_optimal=tuple(builder.brave_optimal),
        count=builder.count,
        count_optimal=builder.count_optimal,
        cost=builder.cost,
        assign=builder.assign,
        assign_optimal=builder.assign_optimal,
        queries=tuple(builder.queries),
        notes=tuple(builder.notes),
    )


def _validate(builder: _Builder, source: str | None) -> Claimed[Literal["sat", "unsat"]]:
    """The cross-tag static semantics, returning the validated ``@expect`` and its line.
    Per-cell single-valuedness is enforced during parsing; the precondition rules
    (optimization, clingcon, contrary-shown) need the encoding and are checked at discovery."""
    expect = builder.expect
    if expect is None:  # rule 1
        _fail_contract(source, "a contract must declare exactly one @expect (sat|unsat)")

    if expect.value == "unsat":  # rule 3: unsat excludes every model-bearing tag
        if tags := _model_bearing_tags(builder):
            _fail_contract(
                source,
                f"@expect unsat excludes the model-bearing tag(s) {', '.join(tags)} "
                "(only @count 0 / @count optimal 0 is consistent with it)",
            )
    elif (builder.count is not None and builder.count.value == 0) or (
        builder.count_optimal is not None and builder.count_optimal.value == 0
    ):  # rule 3: @count 0 ⟺ unsat
        _fail_contract(source, "@count 0 ⟺ @expect unsat; it contradicts @expect sat")

    if (  # rule 3: Opt(P) ⊆ AS(P) requires m ≤ n
        builder.count is not None
        and builder.count_optimal is not None
        and builder.count_optimal.value > builder.count.value
    ):
        _fail_contract(
            source,
            f"@count optimal {builder.count_optimal.value} > @count {builder.count.value}: "
            "Opt(P) ⊆ AS(P) requires m ≤ n",
        )
    return expect


def _model_bearing_tags(builder: _Builder) -> list[str]:
    """The model-bearing tags actually present: each asserts something requiring an answer
    set. Returned in surface order so the unsat diagnostic can point at the specific offenders."""
    present: list[str] = []
    if builder.model is not None:
        present.append("@model")
    if builder.optimal_model is not None:
        present.append("@optimal")
    if builder.cautious:
        present.append("@cautious")
    if builder.cautious_optimal:
        present.append("@cautious optimal")
    if builder.brave:
        present.append("@brave")
    if builder.brave_optimal:
        present.append("@brave optimal")
    if builder.cost is not None:
        present.append("@cost")
    if builder.assign is not None:
        present.append("@assign")
    if builder.assign_optimal is not None:
        present.append("@assign optimal")
    if builder.queries:
        present.append("@query")
    if builder.count is not None and builder.count.value >= 1:
        present.append("@count")
    if builder.count_optimal is not None and builder.count_optimal.value >= 1:
        present.append("@count optimal")
    return present


def _location(source: str | None, line: int) -> str:
    return f"{source}:{line}" if source is not None else f"line {line}"


def _fail_contract(source: str | None, message: str) -> NoReturn:
    """Raise a contract-level ``ContractError`` (whole-contract inconsistency, no single line)."""
    raise ContractError(f"{source}: {message}" if source is not None else message)


def _fail_at(source: str | None, line: int, message: str) -> NoReturn:
    """Raise a ``ContractError`` for a single offending directive line, with ``source:line``."""
    raise ContractError(f"{_location(source, line)}: {message}")


def _main() -> None:
    """Inspect a contract: parse a ``.lp`` file's ``@``-annotations, print the ``Expectation``."""
    import sys
    from pathlib import Path

    arguments = sys.argv[1:]
    if len(arguments) != 1:
        print("usage: python -m elenctic.expectation <file.lp>", file=sys.stderr)
        raise SystemExit(2)
    path = Path(arguments[0])
    print(parse(path.read_text(encoding="utf-8"), source=str(path)))


if __name__ == "__main__":
    _main()
