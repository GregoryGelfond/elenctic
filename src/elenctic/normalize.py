"""Normalizing the terms of a pattern as written: what each stands for, or why it is no pattern."""

from dataclasses import dataclass
from typing import Final, override

from clingo import MessageCode, parse_term
from clingo.ast import AST, ASTType, UnaryOperator

from elenctic.terms import Term, Variable, build
from elenctic.traversal import fold


@dataclass(frozen=True, slots=True)
class NotAPattern:
    """A term that cannot be matched, for it does not stand for one term.

    This is not a failure to match: matching fails when a pattern differs from what it faces, and
    this is a pattern that could never have been read, so the two are never taken for each other.
    """

    term: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"`{self.term}` is not a pattern: {self.reason}"


def _silent(_code: MessageCode, _message: str) -> None:
    """Swallow clingo's report; the failure itself raises."""


def function_of(term: AST) -> tuple[AST, bool] | None:
    """Return the ordinary function `term` is, or negates, and whether it does not negate it."""
    negated = term.ast_type is ASTType.UnaryOperation and term.operator_type == UnaryOperator.Minus
    function = term.argument if negated else term
    plain = function.ast_type is ASTType.Function and not function.external
    return (function, not negated) if plain else None


def _arguments(term: AST) -> tuple[AST, ...]:
    found = function_of(term)
    return () if found is None else tuple(found[0].arguments)


_REFUSALS: Final = {
    ASTType.Interval: "an interval stands for several terms",
    ASTType.Pool: "a pool stands for several terms",
    ASTType.Function: "a call to an external function is not made",
}


def _ground(term: AST) -> Term | NotAPattern:
    """Return the one ground term that arithmetic or a constant stands for, or why it has none."""
    try:
        return parse_term(str(term), _silent)
    except RuntimeError:
        return NotAPattern(str(term), "arithmetic over a variable or undefined has no value")


def _evaluated(term: AST) -> Term | NotAPattern:
    """Return the one term that `term`, a leaf of the pattern, stands for, or why it has none."""
    if (reason := _REFUSALS.get(term.ast_type)) is not None:
        return NotAPattern(str(term), reason)
    return Variable(term.name) if term.ast_type is ASTType.Variable else _ground(term)


def _assembled(term: AST, parts: list[Term | NotAPattern]) -> Term | NotAPattern:
    refused = next((part for part in parts if isinstance(part, NotAPattern)), None)
    found = function_of(term)
    if refused is not None or found is None:
        return refused or _evaluated(term)
    function, positive = found
    terms = [part for part in parts if not isinstance(part, NotAPattern)]
    return build(function.name, terms, positive=positive)


def normalize(term: AST) -> Term | NotAPattern:
    """Return what the argument `term` of a pattern stands for, nested to any depth, or why not.

    A function is read by its arguments; arithmetic over ground terms is evaluated; a variable
    stays. An interval, a pool, a call to an external function, and arithmetic that has a
    variable in it have no one value, and are refused.
    """
    return fold(term, _arguments, _assembled)
