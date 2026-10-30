"""Sets of bindings as a tag writes them: bare terms for one variable, tuples for several."""

from clingo import Symbol, SymbolType

from elenctic.body import failure
from elenctic.normalize import evaluate
from elenctic.spans import Parsed, Span


def read_bindings(text: str, arity: int, where: Span) -> Parsed[tuple[tuple[Symbol, ...], ...]]:
    """Read a set of binding tuples; one variable lists bare terms, several list tuples."""
    if not text.strip():
        return ()
    term = evaluate(f"({text})")
    if term is None:
        return failure(where, "expected a set of terms")
    return _bindings(tuple(term.arguments) if _is_tuple(term) else (term,), arity, where)


def _bindings(
    raw: tuple[Symbol, ...], arity: int, where: Span
) -> Parsed[tuple[tuple[Symbol, ...], ...]]:
    if arity == 1:
        return tuple((element,) for element in raw)
    if all(_is_tuple(element) and len(element.arguments) == arity for element in raw):
        return tuple(tuple(element.arguments) for element in raw)
    if len(raw) == arity and not any(_is_tuple(element) for element in raw):
        return (raw,)
    return failure(where, f"expected bindings of {arity} terms each")


def _is_tuple(term: Symbol) -> bool:
    return term.type is SymbolType.Function and term.name == "" and bool(term.arguments)
