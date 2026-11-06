"""Sets of bindings as a tag writes them: bare terms for one variable, tuples for several."""

from clingo import Symbol, SymbolType

from elenctic.normalize import evaluate
from elenctic.spans import Parsed, Span, failure, one_line


def read_bindings(text: str, arity: int, where: Span) -> Parsed[tuple[tuple[Symbol, ...], ...]]:
    """Read a set of binding tuples; one variable lists bare terms, several list tuples."""
    if not text.strip():
        return ()
    term = evaluate(f"({text})")
    if term is None:
        return failure(
            where,
            f"expected a set of terms, found `{one_line(text)}`",
            label="expected a set of terms",
        )
    return _bindings(tuple(term.arguments) if _is_tuple(term) else (term,), arity, where)


def _bindings(
    raw: tuple[Symbol, ...], arity: int, where: Span
) -> Parsed[tuple[tuple[Symbol, ...], ...]]:
    shaped = _shaped(raw, arity)
    if shaped is not None:
        return shaped
    return failure(
        where,
        f"expected {arity} terms in each binding",
        label=f"this binding has {len(raw)}",
    )


def _shaped(raw: tuple[Symbol, ...], arity: int) -> tuple[tuple[Symbol, ...], ...] | None:
    """Return the terms as rows of `arity` terms, or `None` if they are not written as such."""
    if arity == 1:
        return tuple((element,) for element in raw)
    if all(_is_tuple(element) and len(element.arguments) == arity for element in raw):
        return tuple(tuple(element.arguments) for element in raw)
    return (raw,) if len(raw) == arity and not any(map(_is_tuple, raw)) else None


def _is_tuple(term: Symbol) -> bool:
    return term.type is SymbolType.Function and term.name == "" and bool(term.arguments)
