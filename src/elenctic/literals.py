"""Literals, the sets of them that answer sets are, and the assumptions over them."""

from dataclasses import dataclass
from typing import NamedTuple, override

from clingo import Function, Number, Symbol, SymbolType, parse_term

# `Function`, `Number` and `Symbol` are re-exported, with `integer` and `is_function` to read a
# symbol: a module that does not parse, ground or solve meets clingo's terms only here. Those that
# do and use them, clauses, engine, instances, normalize, search and tree, import them from
# clingo.
__all__ = [
    "Assumption",
    "Atoms",
    "Function",
    "Literal",
    "Number",
    "Scenario",
    "Signature",
    "Symbol",
    "integer",
    "is_function",
]  # fmt: skip


def integer(symbol: Symbol) -> int | None:
    """Read `symbol` as an integer, or `None` when it is not a number."""
    return symbol.number if symbol.type is SymbolType.Number else None


def is_function(symbol: Symbol) -> bool:
    """Say whether `symbol` is a function symbol: a constant, `f(...)` or a tuple."""
    return symbol.type is SymbolType.Function


class Signature(NamedTuple):
    """A predicate with its arity and sign: `p/1`, or `-p/1` when not `positive`."""

    name: str
    arity: int
    positive: bool = True

    @override
    def __str__(self) -> str:
        return f"{'' if self.positive else '-'}{self.name}/{self.arity}"


@dataclass(frozen=True, slots=True, order=True)
class Literal:
    """A ground classical literal: an atom `p(t, ...)`, or `-p(t, ...)` when not `positive`."""

    name: str
    arguments: tuple[Symbol, ...] = ()
    positive: bool = True

    @classmethod
    def of(cls, symbol: Symbol) -> Literal:
        if not is_function(symbol) or not symbol.name:
            message = f"not a literal: {symbol}"
            raise ValueError(message)
        return cls(symbol.name, tuple(symbol.arguments), symbol.positive)

    @classmethod
    def parse(cls, text: str) -> Literal:
        """Read `p(1,"a")` or `-p`; raises `ValueError` for anything else, as does `of`."""
        try:
            return cls.of(parse_term(text))
        except (RuntimeError, UnicodeDecodeError) as error:
            raise ValueError(str(error)) from error

    @property
    def symbol(self) -> Symbol:
        return Function(self.name, list(self.arguments), self.positive)

    @property
    def contrary(self) -> Literal:
        return Literal(self.name, self.arguments, not self.positive)

    @property
    def signature(self) -> Signature:
        return Signature(self.name, len(self.arguments), self.positive)

    @override
    def __str__(self) -> str:
        return str(self.symbol)


type Atoms = frozenset[Literal]


@dataclass(frozen=True, slots=True, order=True)
class Assumption:
    """A literal taken to hold, or, when not `holds`, taken not to.

    Ordered by literal, then sign, which is the order a claim writes its assumptions in.
    """

    literal: Literal
    holds: bool = True

    @override
    def __str__(self) -> str:
        return str(self.literal) if self.holds else f"not {self.literal}"


type Scenario = frozenset[Assumption]
