"""Literals, the sets of them that answer sets are, and the assumptions over them."""

from dataclasses import dataclass
from typing import NamedTuple, override

from clingo import Function, Symbol, SymbolType, parse_term

__all__ = [  # `Symbol` is re-exported: the kernel meets clingo's terms only through this module
    "Assumption",
    "Atoms",
    "Literal",
    "Scenario",
    "Signature",
    "Symbol",
]  # fmt: skip


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
        if symbol.type is not SymbolType.Function or not symbol.name:
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


@dataclass(frozen=True, slots=True)
class Assumption:
    """A literal taken to hold, or, when not `holds`, taken not to."""

    literal: Literal
    holds: bool = True


type Scenario = frozenset[Assumption]
