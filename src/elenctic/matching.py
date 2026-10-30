"""One-sided matching: a pattern, with variables, against ground symbols."""

from collections.abc import Sequence

from clingo import Symbol, SymbolType

from elenctic.terms import Compound, Term, Variable


def _shape_agrees(pattern: Compound, symbol: Symbol) -> bool:
    return (
        symbol.type is SymbolType.Function
        and (symbol.name, symbol.positive, len(symbol.arguments)) == pattern.shape
    )


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
        pattern, symbol = pending.pop()
        match pattern:
            case Variable() if pattern.anonymous:
                continue
            case Variable():
                if bound.setdefault(pattern, symbol) != symbol:
                    return None
            case Compound() if _shape_agrees(pattern, symbol):
                pending.extend(
                    zip(reversed(pattern.arguments), reversed(symbol.arguments), strict=True)
                )
            case Compound():
                return None
            case _:
                if pattern != symbol:
                    return None
    return bound
