"""clingo term and literal helpers shared by ``expectation.py``, ``query.py`` and ``program.py``.

Litsets/tuplesets are delegated to clingo's term parser: the brace body
is wrapped in parentheses and parsed as one term, so commas inside atoms
(``included(s,a,2,1)``) and quotes are handled by the grounder's own parser rather
than a hand-rolled splitter. A strong-negation literal ``-a`` parses to a
``Symbol`` with ``positive == False``.

A :data:`Signature` is the predicate-level name of a literal — the granularity ``#show`` speaks in,
and so the granularity at which a program's observable vocabulary can be stated at all.
"""

from clingo import Function, Symbol, SymbolType, parse_term as _clingo_parse_term

__all__ = [
    "Signature",
    "contrary",
    "intersect_all",
    "parse_litset",
    "parse_term",
    "parse_tupleset",
    "signature_of",
    "union_all",
]


type Signature = tuple[str, int]
"""A sign-aware predicate signature ``(name, arity)`` — ``("p", 1)`` for ``p(x)``, ``("-p", 1)`` for
``-p(x)``. The sign belongs in the name because ``#show p/1.`` and ``#show -p/1.`` are two separate
declarations and a program may make either observable without the other."""


def parse_term(text: str) -> Symbol:
    """Parse one term through clingo, capturing its diagnostics instead of letting them reach
    standard error.

    Given no logger, clingo reports a parse failure on standard error itself — text elenctic did
    not frame, arriving on a stream it did not choose, interleaved with whatever else is there.
    The contract being parsed comes from a ``.lp`` file, so that text is influenced by the file.
    Capturing it and folding it into the raised error keeps every diagnostic on one channel, with
    the provenance the caller adds; the failure type is unchanged, so the callers that already
    translate it keep working.
    """
    messages: list[str] = []
    try:
        return _clingo_parse_term(text, logger=lambda _code, message: messages.append(message))
    except RuntimeError as exc:
        raise RuntimeError("; ".join(messages) or str(exc)) from exc


def _is_tuple_symbol(s: Symbol) -> bool:
    """True iff ``s`` is a clingo tuple term ``(t1, …, tn)`` (an anonymous Function)."""
    return s.type is SymbolType.Function and s.name == ""


def parse_litset(body: str) -> tuple[Symbol, ...]:
    """Parse a brace body ``l1, …, ln`` into its literal Symbols, paren-aware.

    Wrapping in parens and parsing one term: a multi-element body yields an anonymous
    tuple Symbol whose ``.arguments`` are the literals; a single element yields that
    element directly (the parens are grouping). The grammar needs ≥1 literal, and litset
    elements are literals (atoms or strong-negation literals) only, so this rejects an
    empty *result* and any non-``Function`` element — a parsed litset is non-empty and
    literal-shaped by construction. (A bare tuple ``(a,b)`` — not a valid literal — flattens
    indistinguishably from ``a, b`` and is the one malformed shape not detected here.)

    An empty body and a body that *parses* to nothing are two different inputs and both are
    rejected here. ``{ () }`` is the second: the body is not blank, so a blank-text guard alone
    lets it through, and the empty tuple then flattens to no literals at all. Everything
    downstream — the containment builders' vacuous-claim guard, the witness comparison — is
    entitled to assume a litset has a literal in it, and this is the boundary that owes them that.
    """
    if not body.strip():
        raise ValueError("empty literal set: a litset needs at least one literal (atom or -atom)")
    try:
        term = parse_term(f"({body})")
    except RuntimeError as exc:
        raise ValueError(
            f"malformed literal set {{{body}}} (a ground litset is variable-free): {exc}"
        ) from exc
    literals = tuple(term.arguments) if _is_tuple_symbol(term) else (term,)
    if not literals:
        raise ValueError(
            f"empty literal set {{{body}}}: it parses to no literals at all, and a litset needs at "
            "least one (an atom or -atom)"
        )
    for literal in literals:
        if literal.type is not SymbolType.Function:
            raise ValueError(f"litset elements must be literals (atoms or -atoms); got {literal}")
    return literals


def parse_tupleset(body: str, arity: int) -> tuple[tuple[Symbol, ...], ...]:
    """Parse a binding set body into argument tuples of the given ``arity``.

    A 1-argument query lists bare terms (``s, a, t``); an n-argument query lists
    ``(t1, …, tn)`` tuples. The lone n-tuple case (``(s,1)``) collapses under the
    grouping parens, so it is disambiguated by ``arity``. Binding components are
    expected to be non-tuple terms (constants/numbers/functions); a tuple-valued
    component would be ambiguous with the several-tuples reading (reserved).
    """
    if not body.strip():
        return ()
    term = parse_term(f"({body})")
    raw = tuple(term.arguments) if _is_tuple_symbol(term) else (term,)
    if arity == 1:
        return tuple((element,) for element in raw)
    if all(_is_tuple_symbol(element) and len(element.arguments) == arity for element in raw):
        return tuple(tuple(element.arguments) for element in raw)  # several n-tuples
    if len(raw) == arity and not any(_is_tuple_symbol(element) for element in raw):
        return (raw,)  # a single n-tuple, collapsed by the grouping parens
    raise ValueError(f"binding tuples do not match arity {arity}: {{{body}}}")


def contrary(literal: Symbol) -> Symbol:
    """The contrary ``l̄`` of a literal: flip strong negation. ``a`` ↔ ``-a``."""
    if literal.type is not SymbolType.Function:
        raise ValueError(f"not a literal (no contrary): {literal}")
    return Function(literal.name, list(literal.arguments), not literal.positive)


def signature_of(literal: Symbol) -> Signature:
    """The :data:`Signature` of a ground literal — what a ``#show`` declaration would have to name
    for that literal to be observable."""
    if literal.type is not SymbolType.Function:
        raise ValueError(f"not a literal (no signature): {literal}")
    return (literal.name if literal.positive else f"-{literal.name}", len(literal.arguments))


def intersect_all(family: tuple[frozenset[Symbol], ...]) -> frozenset[Symbol]:
    """⋂ of a non-empty family of atom sets — the cautious fold (the caller guarantees non-empty).

    The single home for the meet-over-a-non-empty-family idiom and its precondition, shared by the
    consequence views (``result``) and the optimal-base aggregation (``checks``)."""
    return family[0].intersection(*family[1:])


def union_all(family: tuple[frozenset[Symbol], ...]) -> frozenset[Symbol]:
    """⋃ of a non-empty family of atom sets — the brave fold (the caller guarantees non-empty)."""
    return family[0].union(*family[1:])
