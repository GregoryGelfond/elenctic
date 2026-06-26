"""The contract: in-file ``@``-annotations parsed into an ``Expectation``.

``Expectation`` is a sum of two well-formed shapes (``Unsat`` | ``Sat``) so illegal states
are unrepresentable: a parsed contract is structurally a valid one. ``parse(text)`` is
pure and total in the sense that every input either yields an ``Expectation`` or raises a
``ContractError`` naming what is wrong (and, given a ``source``, where) — it never silently
defaults or discards.

Three responsibilities:

- **Brace-bounded continuation.** A litset may span continuation ``%`` lines *while a
  brace remains unclosed*; once the brace closes, a following ``%`` line is prose (e.g. a
  ``% Run: …`` header), not part of the litset. ``_blocks`` tracks the open brace so a
  continuation absorbs only the unfinished litset.
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

from clingo import Symbol, parse_term

from elenctic.query import Query, parse_query
from elenctic.registry import SOLVERS, Solver
from elenctic.terms import parse_litset


class ContractError(Exception):
    """An ill-formed or inconsistent contract block. Carries source:line provenance."""


@dataclass(frozen=True, slots=True)
class WitnessClaim:
    """A witness cell's claim: the shown model and an optional joint theory binding.

    ``assign`` empty ⇒ a bare witness (``@model { L }``); non-empty ⇒ a ``where``-qualified joint
    witness (``@model { L } where { A }``), binding shown and assignment to one model. The
    expectation-side counterpart of the result-side ``ConsistentWitness`` (hence ``…Claim``). One
    cell holds one ``WitnessClaim``: ``assign`` empty (bare) or the ``where``-binding."""

    shown: frozenset[Symbol]
    assign: frozenset[tuple[Symbol, int]] = frozenset()


@dataclass(frozen=True, slots=True)
class Unsat:
    """``@expect unsat``: ``AS(P) = ∅``; excludes every model-bearing tag."""

    notes: tuple[str, ...] = ()  # @note prose: documentation, not a contract term


@dataclass(frozen=True, slots=True)
class Sat:
    """``@expect sat`` with its base-tagged claims.

    ``None`` scalars and empty consequence sets mean "no such claim" — no run is derived and no
    check emitted for them. The ``all`` and ``optimal`` bases occupy distinct fields
    (the ``(mode, base)`` cells), so ``@model`` and ``@model optimal`` coexist.
    """

    model: WitnessClaim | None = None
    optimal_model: WitnessClaim | None = None
    cautious: frozenset[Symbol] = frozenset()
    cautious_optimal: frozenset[Symbol] = frozenset()
    brave: frozenset[Symbol] = frozenset()
    brave_optimal: frozenset[Symbol] = frozenset()
    count: int | None = None
    count_optimal: int | None = None
    cost: tuple[int, ...] | None = None
    assign: frozenset[tuple[Symbol, int]] = frozenset()
    assign_optimal: frozenset[tuple[Symbol, int]] = frozenset()
    queries: tuple[Query, ...] = ()
    notes: tuple[str, ...] = ()  # @note prose: documentation, not a contract term

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
            or bool(self.assign_optimal)
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
    def requires_theory(self) -> bool:
        """Whether this contract presupposes a *theory* solver: ``@assign`` / ``@assign optimal``
        read the theory half of the observable, and a ``where``-qualified witness binds it jointly —
        all require clingcon. The precondition discovery checks against the case's solver."""
        return (
            bool(self.assign)
            or bool(self.assign_optimal)
            or (self.model is not None and bool(self.model.assign))
            or (self.optimal_model is not None and bool(self.optimal_model.assign))
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


# --- block tokenization (brace-bounded continuation) ---

# A contract line is `% @<tag> <payload>`; a continuation is any later `%` line absorbed while the
# preceding tag's litset brace is still open. A tag line is tried first, so a continuation never
# starts a new tag (litset elements are ASP literals, which never begin with `@`).
_TAG = re.compile(r"^\s*%\s*@(?P<tag>\w+)\b(?P<rest>.*)$")
_CONT = re.compile(r"^\s*%\s*(?P<rest>.*)$")

# A `%`-line whose content begins with a `where {` clause (the keyword then a brace) — the dangling-
# witness shape. NOT merely the word "where" (an ordinary `% where the cost is…` prose comment, no
# brace, stays a comment). When such a line is not absorbed by an open brace it is a loud error.
_DANGLING_WHERE = re.compile(r"^\s*%\s*where\s*\{")

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
    """Tokenize the contract line(s) into ``_Block``s, joining continuation ``%`` lines into the
    preceding tag's payload *only while its brace is unclosed* (prose lines after a closed litset
    are left alone). A ``%``-line that begins a ``where { … }`` clause but is not absorbed by an
    open brace is a *dangling witness* — a loud ``ContractError`` with provenance, never silently
    dropped."""
    blocks: list[_Block] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if (tag := _TAG.match(line)) is not None:
            blocks.append(_Block(tag.group("tag"), tag.group("rest").strip(), line_number))
        elif (
            blocks
            and blocks[-1].tag in _LITSET_TAGS
            and _has_unclosed_brace(blocks[-1].payload)
            and (cont := _CONT.match(line)) is not None
        ):
            last = blocks[-1]
            joined = f"{last.payload} {cont.group('rest').strip()}".strip()
            blocks[-1] = replace(last, payload=joined)
        elif blocks and blocks[-1].tag in {"model", "optimal"} and _DANGLING_WHERE.match(line):
            # only `where {` directly after a witness tag (its litset brace already closed, else the
            # continuation branch absorbed it) is a dangling witness; `where {` elsewhere (e.g.
            # set-builder notation in prose) stays an ordinary comment.
            raise ContractError(
                f"{_location(source, line_number)}: dangling `where`: place it on the witness's "
                "brace-closing line (a `where` clause must ride the litset's closing brace, or be "
                "brace-continued while a brace is open)"
            )
    return blocks


def _tag_lines(text: str) -> Iterator[_Block]:
    """Yield one ``_Block`` per ``% @tag`` line (tag + raw rest + 1-based line), with no
    continuation join and no raises — the lexical tag-recognition (the shared ``_TAG`` pattern)
    that ``has_contract`` reads. Continuation / dangling-``where`` handling lives in ``_blocks``;
    both read ``_TAG``, so there is one tag recognizer of record."""
    for line_number, line in enumerate(text.splitlines(), start=1):
        if (tag := _TAG.match(line)) is not None:
            yield _Block(tag.group("tag"), tag.group("rest").strip(), line_number)


def has_contract(text: str) -> bool:
    """Whether ``text`` carries a contract — the collection predicate: a ``.lp`` file is a
    **case** iff it contains at least one known elenctic tag, else a **library** (an ``#include``
    target, never run directly). Content-keyed, not filename-keyed (the "pytest-shaped" surface is
    the *invocation*, not pytest's filename collection). An unknown ``@word`` in a tag-free file is
    just prose (a library, no error); a known tag with a missing ``@expect`` is still a case (it
    fails loud at ``parse``, never silently reclassified — loud over silent). Never raises."""
    return any(block.tag in KNOWN_TAGS for block in _tag_lines(text))


def _has_unclosed_brace(payload: str) -> bool:
    """Whether ``payload`` has a ``{`` with no matching ``}`` — a litset continued on the next
    ``%`` line. Brace counting ignores braces inside double-quoted string terms."""
    depth = 0
    in_quote = False
    for char in payload:
        if char == '"':
            in_quote = not in_quote
        elif not in_quote:
            depth += (char == "{") - (char == "}")
    return depth > 0


# --- the typed builder and per-tag dispatch ---


@dataclass(slots=True)
class _Builder:
    """Mutable accumulator for one contract's tags; ``_finish`` freezes it into an ``Expectation``.

    A single-valued ``(mode, base)`` cell is realized as a field that starts ``None``
    (or empty) and whose second assignment is the violation — the field *is* the record of whether
    the cell is occupied, so no separate bookkeeping is needed. Consequence/query/prose tags
    accumulate.
    """

    expect: Literal["sat", "unsat"] | None = None
    model: WitnessClaim | None = None
    optimal_model: WitnessClaim | None = None
    cautious: frozenset[Symbol] = frozenset()
    cautious_optimal: frozenset[Symbol] = frozenset()
    brave: frozenset[Symbol] = frozenset()
    brave_optimal: frozenset[Symbol] = frozenset()
    count: int | None = None
    count_optimal: int | None = None
    cost: tuple[int, ...] | None = None
    assign: frozenset[tuple[Symbol, int]] = frozenset()
    assign_optimal: frozenset[tuple[Symbol, int]] = frozenset()
    queries: list[Query] = field(default_factory=list)
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
            builder.expect = _expect_value(rest)
        case "model":
            litset_text, assign = _split_where(rest)
            is_optimal, litset = _base_litset(litset_text)
            claim = WitnessClaim(shown=litset, assign=assign)
            if is_optimal:
                _set_optimal_model(builder, claim)
            elif builder.model is not None:
                raise ValueError("at most one @model per contract (the 'all' base)")
            else:
                builder.model = claim
        case "optimal":  # sugar: @optimal ≡ @model optimal
            litset_text, assign = _split_where(rest)
            _set_optimal_model(builder, WitnessClaim(shown=_litset(litset_text), assign=assign))
        case "cautious":
            is_optimal, litset = _base_litset(rest)
            if is_optimal:
                builder.cautious_optimal |= litset
            else:
                builder.cautious |= litset
        case "brave":
            is_optimal, litset = _base_litset(rest)
            if is_optimal:
                builder.brave_optimal |= litset
            else:
                builder.brave |= litset
        case "count":
            is_optimal, n = _base_int(rest)
            if is_optimal:
                if builder.count_optimal is not None:
                    raise ValueError("at most one @count optimal per contract")
                builder.count_optimal = n
            elif builder.count is not None:
                raise ValueError("at most one @count per contract (the 'all' base)")
            else:
                builder.count = n
        case "cost":
            if builder.cost is not None:
                raise ValueError("at most one @cost per contract")
            builder.cost = _cost_vector(rest)
        case "assign":
            is_optimal, bindings = _base_assign(rest)
            if is_optimal:
                if builder.assign_optimal:
                    raise ValueError("at most one @assign optimal per contract")
                builder.assign_optimal = bindings
            elif builder.assign:
                raise ValueError("at most one @assign per contract (the 'all' base)")
            else:
                builder.assign = bindings
        case "query":
            builder.queries.append(_query(rest))
        case "note":
            builder.notes.append(rest)
        case _:
            raise ValueError(f"unknown contract tag: @{block.tag} (known: {sorted(KNOWN_TAGS)})")


def _set_optimal_model(builder: _Builder, claim: WitnessClaim) -> None:
    """Set the optimal-witness cell, shared by ``@optimal`` and ``@model optimal``."""
    if builder.optimal_model is not None:
        raise ValueError("at most one @optimal / @model optimal per contract (the same cell)")
    builder.optimal_model = claim


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
    if _validate(builder, source) == "unsat":
        return Unsat(notes=tuple(builder.notes))
    return Sat(
        model=builder.model,
        optimal_model=builder.optimal_model,
        cautious=builder.cautious,
        cautious_optimal=builder.cautious_optimal,
        brave=builder.brave,
        brave_optimal=builder.brave_optimal,
        count=builder.count,
        count_optimal=builder.count_optimal,
        cost=builder.cost,
        assign=builder.assign,
        assign_optimal=builder.assign_optimal,
        queries=tuple(builder.queries),
        notes=tuple(builder.notes),
    )


def _validate(builder: _Builder, source: str | None) -> Literal["sat", "unsat"]:
    """The cross-tag static semantics, returning the validated ``@expect``.
    Per-cell single-valuedness is enforced during parsing; the precondition rules
    (optimization, clingcon, contrary-shown) need the encoding and are checked at discovery."""
    expect = builder.expect
    if expect is None:  # rule 1
        _fail_contract(source, "a contract must declare exactly one @expect (sat|unsat)")

    if expect == "unsat":  # rule 3: unsat excludes every model-bearing tag
        if tags := _model_bearing_tags(builder):
            _fail_contract(
                source,
                f"@expect unsat excludes the model-bearing tag(s) {', '.join(tags)} "
                "(only @count 0 / @count optimal 0 is consistent with it)",
            )
    elif builder.count == 0 or builder.count_optimal == 0:  # rule 3: @count 0 ⟺ unsat
        _fail_contract(source, "@count 0 ⟺ @expect unsat; it contradicts @expect sat")

    if (  # rule 3: Opt(P) ⊆ AS(P) requires m ≤ n
        builder.count is not None
        and builder.count_optimal is not None
        and builder.count_optimal > builder.count
    ):
        _fail_contract(
            source,
            f"@count optimal {builder.count_optimal} > @count {builder.count}: "
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
    if builder.assign:
        present.append("@assign")
    if builder.assign_optimal:
        present.append("@assign optimal")
    if builder.queries:
        present.append("@query")
    if builder.count is not None and builder.count >= 1:
        present.append("@count")
    if builder.count_optimal is not None and builder.count_optimal >= 1:
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

    if len(sys.argv) != 2:
        print("usage: python -m elenctic.expectation <file.lp>", file=sys.stderr)
        raise SystemExit(2)
    path = Path(sys.argv[1])
    print(parse(path.read_text(encoding="utf-8"), source=str(path)))


if __name__ == "__main__":
    _main()
