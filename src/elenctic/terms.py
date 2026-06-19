"""clingo term-parsing helpers shared by ``expectation.py`` and ``query.py``.

Litsets/tuplesets are delegated to clingo's term parser (spec §4): the brace body
is wrapped in parentheses and parsed as one term, so commas inside atoms
(``included(s,a,2,1)``) and quotes are handled by the grounder's own parser rather
than a hand-rolled splitter (Knuth). A strong-negation literal ``-a`` parses to a
``Symbol`` with ``positive == False``.
"""

from clingo import Function, Symbol, SymbolType, parse_term


def _is_tuple_symbol(s: Symbol) -> bool:
    """True iff ``s`` is a clingo tuple term ``(t1, …, tn)`` (an anonymous Function)."""
    return s.type is SymbolType.Function and s.name == ""


def parse_litset(body: str) -> tuple[Symbol, ...]:
    """Parse a brace body ``l1, …, ln`` into its literal Symbols, paren-aware (spec §2.1).

    Wrapping in parens and parsing one term: a multi-element body yields an anonymous
    tuple Symbol whose ``.arguments`` are the literals; a single element yields that
    element directly (the parens are grouping). Litset elements are atoms or
    strong-negation literals — never bare tuples — so an anonymous-tuple result
    unambiguously means "the wrapping tuple".
    """
    term = parse_term(f"({body})")
    return tuple(term.arguments) if _is_tuple_symbol(term) else (term,)


def parse_tupleset(body: str, arity: int) -> tuple[tuple[Symbol, ...], ...]:
    """Parse a binding set body into argument tuples of the given ``arity`` (spec §2.1).

    A 1-argument query lists bare terms (``s, a, t``); an n-argument query lists
    ``(t1, …, tn)`` tuples. The lone n-tuple case (``(s,1)``) collapses under the
    grouping parens, so it is disambiguated by ``arity``.
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
    """The contrary ``l̄`` of a literal: flip strong negation (spec §2.1). ``a`` ↔ ``-a``."""
    if literal.type is not SymbolType.Function:
        raise ValueError(f"not a literal (no contrary): {literal}")
    return Function(literal.name, list(literal.arguments), not literal.positive)
