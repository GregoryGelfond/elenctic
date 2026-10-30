"""Literals, the sets of them that answer sets are, and the patterns and assumptions over them."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, NamedTuple, override

from clingo import Function, Symbol, SymbolType, parse_term

ANONYMOUS: Final = "_"


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
        except RuntimeError as error:
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


type AnswerSet = frozenset[Literal]


@dataclass(frozen=True, slots=True)
class Variable:
    name: str


@dataclass(frozen=True, slots=True)
class Pattern:
    """A literal whose arguments may be variables; it stands for the literals it matches."""

    name: str
    arguments: tuple[Variable | Symbol, ...]
    positive: bool = True

    @property
    def variables(self) -> tuple[Variable, ...]:
        """The distinct named variables, in order of first occurrence."""
        named = (a for a in self.arguments if isinstance(a, Variable) and a.name != ANONYMOUS)
        return tuple(dict.fromkeys(named))

    @property
    def contrary(self) -> Pattern:
        return Pattern(self.name, self.arguments, not self.positive)

    @property
    def signature(self) -> Signature:
        return Signature(self.name, len(self.arguments), self.positive)

    @override
    def __str__(self) -> str:
        sign = "" if self.positive else "-"
        arguments = ",".join(a.name if isinstance(a, Variable) else str(a) for a in self.arguments)
        return f"{sign}{self.name}({arguments})" if arguments else f"{sign}{self.name}"

    def as_literal(self) -> Literal | None:
        """Return the literal this pattern is, if it has no variables."""
        symbols = tuple(a for a in self.arguments if isinstance(a, Symbol))
        return (
            Literal(self.name, symbols, self.positive)
            if len(symbols) == len(self.arguments)
            else None
        )

    def match(self, literal: Literal) -> tuple[Symbol, ...] | None:
        """Return the values of `variables` that make this pattern the literal, if any."""
        if (literal.name, len(literal.arguments), literal.positive) != (
            self.name,
            len(self.arguments),
            self.positive,
        ):
            return None
        bound = _bind(self.arguments, literal.arguments)
        return None if bound is None else tuple(bound[v.name] for v in self.variables)

    def bindings_in(self, literals: Iterable[Literal]) -> frozenset[tuple[Symbol, ...]]:
        """Return the values of `variables` over the literals this pattern matches."""
        return frozenset(
            found for literal in literals if (found := self.match(literal)) is not None
        )


def _bind(
    arguments: tuple[Variable | Symbol, ...], values: tuple[Symbol, ...]
) -> dict[str, Symbol] | None:
    bound: dict[str, Symbol] = {}
    agrees = all(
        a == v if isinstance(a, Symbol) else a.name == ANONYMOUS or bound.setdefault(a.name, v) == v
        for a, v in zip(arguments, values, strict=True)
    )
    return bound if agrees else None


@dataclass(frozen=True, slots=True)
class Assumption:
    """A literal taken to hold, or, when not `holds`, taken not to."""

    literal: Literal
    holds: bool = True


type Scenario = frozenset[Assumption]
