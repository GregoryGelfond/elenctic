"""Whether clingo's term reader can evaluate a term's arithmetic without trapping the process."""

import re
from typing import Final

from clingo import MessageCode, Symbol, SymbolType, parse_term
from clingo.ast import AST, ASTType, BinaryOperator, parse_string

from elenctic import tree
from elenctic.spans import in_code
from elenctic.traversal import fold

_INCLUDE: Final = re.compile(r"#include\b")
_DIVISIONS: Final = frozenset({BinaryOperator.Division, BinaryOperator.Modulo})
_LEAST: Final = -(2**31)


def _silent(_code: MessageCode, _message: str) -> None:
    """Swallow clingo's report; a text it cannot read is left to the reader that reads it."""


def _value(term: AST) -> int | None:
    """Return the integer `term` evaluates to, if it is one; its divisions are known safe."""
    try:
        value: Symbol = parse_term(str(term), _silent)
    except RuntimeError:
        return None
    return value.number if value.type is SymbolType.Number else None


def _traps(term: AST) -> bool:
    """Say whether `term` divides by zero, or divides the least integer by -1, both undefined.

    clingo's grounder gives such a term no value; its term reader traps on it instead.
    """
    if tree.kind(term) is not ASTType.BinaryOperation:
        return False
    if tree.number(term, "operator_type") not in _DIVISIONS:
        return False
    left, right = _value(tree.child(term, "left")), _value(tree.child(term, "right"))
    return right == 0 or (left, right) == (_LEAST, -1)


def evaluable(text: str) -> bool:
    """Say whether clingo's term reader may be given `text`, which it would not trap on.

    The reader evaluates as it reads, so it traps on an undefined division even in a text it then
    refuses. Only a text clingo's syntax reader reads, none of whose divisions is undefined, may be
    given; the terms beneath a division are checked before it, so no operand evaluated here traps.
    An `#include` is no term and is not opened.
    """
    code = in_code(text)
    if any(code[found.start()] for found in _INCLUDE.finditer(text)):
        return False
    statements: list[AST] = []
    try:
        parse_string(f":- t({text}\n)\n.", statements.append, logger=_silent)
    except RuntimeError, UnicodeError:
        return False
    return not any(
        fold(
            statement,
            lambda node: tuple(tree.subtrees(node)),
            lambda node, below: any(below) or _traps(node),
        )
        for statement in statements
    )
