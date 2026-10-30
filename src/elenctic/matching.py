"""One-sided matching: a pattern, with variables, against ground symbols."""

from collections.abc import Sequence

from clingo import Symbol, SymbolType

from elenctic.terms import Compound, Term, Variable


def _shape_agrees(pattern: Compound, symbol: Symbol) -> bool:
    return (
        symbol.type is SymbolType.Function
        and (symbol.name, symbol.positive, len(symbol.arguments)) == pattern.shape
    )


type Pairs = list[tuple[Term, Symbol]]


def _below(pattern: Compound, symbol: Symbol) -> Pairs | None:
    """Return the pairs of arguments to match next, or `None` if the shapes already differ."""
    if not _shape_agrees(pattern, symbol):
        return None
    return list(zip(reversed(pattern.arguments), reversed(symbol.arguments), strict=True))


def _step(pattern: Term, symbol: Symbol, bound: dict[Variable, Symbol]) -> Pairs | None:
    """Match one pattern against one symbol: what is left to match, or `None` if they differ."""
    match pattern:
        case Variable():
            return [] if pattern.anonymous or bound.setdefault(pattern, symbol) == symbol else None
        case Compound():
            return _below(pattern, symbol)
        case _:
            return [] if pattern == symbol else None


def match(patterns: Sequence[Term], symbols: Sequence[Symbol]) -> dict[Variable, Symbol] | None:
    """Find what the variables of `patterns` must be for them to be exactly `symbols`, if anything.

    A variable stands for one ground symbol everywhere it occurs, an anonymous one for any, each
    time. Nothing is renamed or unified, so there is no occurs check to make: the one side is
    ground, and the work is a single walk of the pattern, in a list not by recursion, so it is
    linear in the size of the pattern and the depth is no limit.
    """
    bound: dict[Variable, Symbol] = {}
    pending = list(zip(reversed(patterns), reversed(symbols), strict=True))
    while pending:
        rest = _step(*pending.pop(), bound)
        if rest is None:
            return None
        pending.extend(rest)
    return bound
