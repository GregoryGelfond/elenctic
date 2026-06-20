"""The contract: in-file ``@``-annotations parsed into an ``Expectation`` (spec §2.1, §2.2).

``Expectation`` is a sum of two well-formed shapes (``Unsat`` | ``Sat``) so illegal states
are unrepresentable (RR3): a parsed contract is structurally a valid one. ``parse(text)`` is
pure and total in the sense that every input either yields an ``Expectation`` or raises a
``ContractError`` naming what is wrong (and, given a ``source``, where) — it never silently
defaults or discards (spec §2.2).

Three responsibilities the spec calls out:

- **Brace-bounded continuation (§2.1).** A litset may span continuation ``%`` lines *while a
  brace remains unclosed*; once the brace closes, a following ``%`` line is prose (e.g. a
  ``% Run: …`` header), not part of the litset. ``_blocks`` tracks the open brace so a
  continuation absorbs only the unfinished litset.
- **Provenance (dx#2).** ``parse(text, source=None)`` carries ``source:line`` (or ``line N``)
  into every diagnostic; discovery passes the file path as ``source`` (spec §5).
- **Single source of truth via a typed builder (dx#18).** Tags accumulate into a typed
  ``_Builder`` rather than an untyped state dict, so the construction of ``Sat`` needs no casts.

Litset tokenization delegates to clingo's term parser via ``terms`` (Knuth). The §2.2 rule-4
*preconditions* (``optimal``/``@cost`` need an optimizing encoding; ``@assign`` needs clingcon;
a ``no``/``unknown`` ``@query`` needs the contrary literal shown) require the encoding/``#show``
set and so are checked at **discovery** (spec §5), not here.
"""

import re
from dataclasses import dataclass, field, replace
from typing import Literal, NoReturn

from clingo import Symbol, parse_term

from elenctic.query import Query, parse_query
from elenctic.terms import parse_litset


class ContractError(Exception):
    """An ill-formed or inconsistent contract block (spec §2.2). Carries source:line provenance."""


@dataclass(frozen=True, slots=True)
class Unsat:
    """``@expect unsat``: ``AS(P) = ∅`` (spec §2.1); excludes every model-bearing tag (§2.2)."""

    notes: tuple[str, ...] = ()  # @note prose: documentation, not a contract term


@dataclass(frozen=True, slots=True)
class Sat:
    """``@expect sat`` with its base-tagged claims (spec §2.1).

    ``None`` scalars and empty consequence sets mean "no such claim" — no run is derived and no
    check emitted for them (spec §3, §4). The ``all`` and ``optimal`` bases occupy distinct fields
    (the ``(mode, base)`` cells of §2.2 rule 2), so ``@model`` and ``@model optimal`` coexist.
    """

    model: frozenset[Symbol] | None = None
    optimal_model: frozenset[Symbol] | None = None
    cautious: frozenset[Symbol] = frozenset()
    cautious_optimal: frozenset[Symbol] = frozenset()
    brave: frozenset[Symbol] = frozenset()
    brave_optimal: frozenset[Symbol] = frozenset()
    count: int | None = None
    count_optimal: int | None = None
    cost: tuple[int, ...] | None = None
    assign: frozenset[tuple[Symbol, int]] = frozenset()
    queries: tuple[Query, ...] = ()
    notes: tuple[str, ...] = ()  # @note prose: documentation, not a contract term


type Expectation = Unsat | Sat


def parse(text: str, source: str | None = None) -> Expectation:
    """Parse a ``.lp`` file's contract block(s) into an ``Expectation`` (spec §2.1, §2.2).

    Pure. Each tag is applied to a typed builder; a malformed payload (raised as ``ValueError``
    by the term/litset layer, or as a duplicate-cell ``ValueError`` here) is surfaced as a
    ``ContractError`` carrying the offending tag's ``source:line``. Cross-tag well-formedness
    (rules 1 and 3 of §2.2) is checked once the builder is complete.
    """
    builder = _Builder()
    for block in _blocks(text):
        try:
            _apply(block, builder)
        except (ValueError, RuntimeError) as exc:
            raise ContractError(f"{_location(source, block.line)}: {exc}") from exc
    return _finish(builder, source)


# --- block tokenization (brace-bounded continuation, dx#1 / spec §2.1) ---

# A contract line is `% @<tag> <payload>`; a continuation is any later `%` line absorbed while the
# preceding tag's litset brace is still open. A tag line is tried first, so a continuation never
# starts a new tag (litset elements are ASP literals, which never begin with `@`).
_TAG = re.compile(r"^\s*%\s*@(?P<tag>\w+)\b(?P<rest>.*)$")
_CONT = re.compile(r"^\s*%\s*(?P<rest>.*)$")

# Only these tags carry a brace-delimited litset/tupleset, so only they may span a continuation.
# Gating on the tag keeps the continuation invariant honest ("join an unfinished *litset*", not
# "join while any brace is unbalanced"): a stray '{' in @note/@expect prose stays single-line.
_LITSET_TAGS = frozenset({"model", "optimal", "cautious", "brave", "cost", "assign", "query"})


@dataclass(frozen=True, slots=True)
class _Block:
    """One contract annotation: its tag, its (continuation-joined) payload, and its 1-based line."""

    tag: str
    payload: str
    line: int


def _blocks(text: str) -> list[_Block]:
    """Tokenize the contract line(s) into ``_Block``s, joining continuation ``%`` lines into the
    preceding tag's payload *only while its brace is unclosed* (spec §2.1; prose lines after a
    closed litset are left alone)."""
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
    return blocks


def _has_unclosed_brace(payload: str) -> bool:
    """Whether ``payload`` has a ``{`` with no matching ``}`` — a litset continued on the next
    ``%`` line (spec §2.1). Brace counting ignores braces inside double-quoted string terms."""
    depth = 0
    in_quote = False
    for char in payload:
        if char == '"':
            in_quote = not in_quote
        elif not in_quote:
            depth += (char == "{") - (char == "}")
    return depth > 0


# --- the typed builder (dx#18) and per-tag dispatch ---


@dataclass(slots=True)
class _Builder:
    """Mutable accumulator for one contract's tags; ``_finish`` freezes it into an ``Expectation``.

    A single-valued ``(mode, base)`` cell (§2.2 rule 2) is realized as a field that starts ``None``
    (or empty) and whose second assignment is the violation — the field *is* the record of whether
    the cell is occupied, so no separate bookkeeping is needed. Consequence/query/prose tags
    accumulate.
    """

    expect: Literal["sat", "unsat"] | None = None
    model: frozenset[Symbol] | None = None
    optimal_model: frozenset[Symbol] | None = None
    cautious: frozenset[Symbol] = frozenset()
    cautious_optimal: frozenset[Symbol] = frozenset()
    brave: frozenset[Symbol] = frozenset()
    brave_optimal: frozenset[Symbol] = frozenset()
    count: int | None = None
    count_optimal: int | None = None
    cost: tuple[int, ...] | None = None
    assign: frozenset[tuple[Symbol, int]] = frozenset()
    queries: list[Query] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _apply(block: _Block, builder: _Builder) -> None:
    """Apply one contract block to the builder, enforcing per-cell single-valuedness (§2.2 rule 2).

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
            is_optimal, litset = _base_litset(rest)
            if is_optimal:
                _set_optimal_model(builder, litset)
            elif builder.model is not None:
                raise ValueError("at most one @model per contract (the 'all' base)")
            else:
                builder.model = litset
        case "optimal":  # sugar: @optimal ≡ @model optimal (spec §2.1)
            _set_optimal_model(builder, _litset(rest))
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
            if builder.assign:
                raise ValueError("at most one @assign per contract")
            builder.assign = _assign_body(rest)
        case "query":
            builder.queries.append(_query(rest))
        case "note":
            builder.notes.append(rest)
        case _:
            raise ValueError(f"unknown contract tag: @{block.tag}")


def _set_optimal_model(builder: _Builder, litset: frozenset[Symbol]) -> None:
    """Set the optimal-witness cell, shared by ``@optimal`` and ``@model optimal`` (§2.2)."""
    if builder.optimal_model is not None:
        raise ValueError("at most one @optimal / @model optimal per contract (the same cell)")
    builder.optimal_model = litset


# --- payload parsers (each raises ValueError; parse wraps with provenance) ---

_BASE_LITSET = re.compile(r"^(?P<base>optimal\s+)?\{(?P<body>.*)\}$", re.S)
_LITSET = re.compile(r"^\{(?P<body>.*)\}$", re.S)
_BASE_INT = re.compile(r"^(?P<base>optimal\s+)?(?P<n>\d+)$")
_COST = re.compile(r"^\{\s*(?P<ints>-?\d+(?:\s+-?\d+)*)\s*\}$")
_BIND = re.compile(r"^(?P<term>.+?)\s*=\s*(?P<value>-?\d+)$")


def _expect_value(rest: str) -> Literal["sat", "unsat"]:
    match rest.strip():
        case "sat":
            return "sat"
        case "unsat":
            return "unsat"
        case other:
            raise ValueError(f"@expect must be sat|unsat, got: {other!r}")


def _base_litset(rest: str) -> tuple[bool, frozenset[Symbol]]:
    """Parse ``[optimal] { litset }`` into ``(is_optimal, literals)`` (spec §2.1)."""
    if (match := _BASE_LITSET.match(rest.strip())) is None:
        raise ValueError(f"expected [optimal] {{ litset }}, got: {rest!r}")
    return bool(match.group("base")), frozenset(parse_litset(match.group("body").strip()))


def _litset(rest: str) -> frozenset[Symbol]:
    """Parse a base-less ``{ litset }`` (for ``@optimal``, which carries no base qualifier)."""
    if (match := _LITSET.match(rest.strip())) is None:
        raise ValueError(f"expected {{ litset }}, got: {rest!r}")
    return frozenset(parse_litset(match.group("body").strip()))


def _base_int(rest: str) -> tuple[bool, int]:
    """Parse ``[optimal] n`` (``n ≥ 0``) into ``(is_optimal, n)`` for ``@count`` (spec §2.1)."""
    if (match := _BASE_INT.match(rest.strip())) is None:
        raise ValueError(f"@count expects [optimal] <non-negative int>, got: {rest!r}")
    return bool(match.group("base")), int(match.group("n"))


def _cost_vector(rest: str) -> tuple[int, ...]:
    """Parse ``{ c1 c2 … }`` into the priority-ordered cost vector (``@cost``, spec §2.0)."""
    if (match := _COST.match(rest.strip())) is None:
        raise ValueError(f"@cost expects {{ <int> … }}, got: {rest!r}")
    return tuple(int(component) for component in match.group("ints").split())


def _assign_body(rest: str) -> frozenset[tuple[Symbol, int]]:
    """Parse ``{ term=int, … }`` into theory bindings for ``@assign`` (spec §2.0/§2.1).

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
    """Split ``<answer> <payload>`` and delegate to ``query.parse_query`` (spec §2.1, §2.4)."""
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


# --- cross-tag well-formedness (§2.2 rules 1 & 3) and the freeze ---


def _finish(builder: _Builder, source: str | None) -> Expectation:
    """Validate the cross-tag rules and freeze the builder into an ``Expectation`` (spec §2.2)."""
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
        queries=tuple(builder.queries),
        notes=tuple(builder.notes),
    )


def _validate(builder: _Builder, source: str | None) -> Literal["sat", "unsat"]:
    """The cross-tag static semantics of §2.2 (rules 1 and 3), returning the validated ``@expect``.
    Per-cell single-valuedness (rule 2) is enforced during parsing; the precondition rules (rule 4:
    optimization, clingcon, contrary-shown) need the encoding and are checked at discovery (§5)."""
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
    """The model-bearing tags actually present (§2.2): each asserts something requiring an answer
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
