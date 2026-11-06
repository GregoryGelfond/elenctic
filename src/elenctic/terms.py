"""Terms: the ground symbols clingo knows, the variables a pattern adds, and what mixes them."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from itertools import zip_longest
from typing import Final, override

from clingo import Function, Symbol

from elenctic.traversal import fold

ANONYMOUS: Final = "_"


@dataclass(frozen=True, slots=True, order=True)
class Variable:
    """A named variable; `_` is anonymous, and each of its occurrences is a different variable."""

    name: str

    @property
    def anonymous(self) -> bool:
        return self.name == ANONYMOUS


type Term = Symbol | Variable | Compound


@dataclass(frozen=True, slots=True, eq=False)
class Compound:
    """A function term `f(...)`, `-f(...)` when not `positive`, or a tuple (empty `name`).

    It has a variable somewhere beneath it: a term without one is the `Symbol` it denotes. Equality
    and hashing walk the term with a list, so terms nested to any depth can be compared.
    """

    name: str
    arguments: tuple[Term, ...]
    positive: bool = True

    def __post_init__(self) -> None:
        if all(isinstance(argument, Symbol) for argument in self.arguments):
            message = f"`{self.name}` has only ground arguments, so it is a symbol, not a term"
            raise ValueError(message)

    @property
    def shape(self) -> tuple[str, bool, int]:
        """The functor, sign and arity that must agree for two compound terms to be unified."""
        return self.name, self.positive, len(self.arguments)

    @override
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Compound):
            return NotImplemented
        return all(a == b for a, b in zip_longest(_tokens(self), _tokens(other), fillvalue=None))

    @override
    def __hash__(self) -> int:
        return hash(tuple(_tokens(self)))

    @override
    def __str__(self) -> str:
        return render(self)

    @override
    def __repr__(self) -> str:
        return f"Compound({render(self)})"


def _nodes(term: Term) -> Iterator[Term]:
    """Yield every subterm, each before its arguments, left to right."""
    pending = [term]
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, Compound):
            pending.extend(reversed(node.arguments))


def _tokens(term: Term) -> Iterator[object]:
    """Flatten the term to a shape or a leaf per node, from which it can be rebuilt."""
    return (n.shape if isinstance(n, Compound) else n for n in _nodes(term))


def leaves(term: Term) -> Iterator[Symbol | Variable]:
    """Yield the ground symbols and variables of `term`, left to right."""
    return (n for n in _nodes(term) if not isinstance(n, Compound))


def variables(term: Term) -> tuple[Variable, ...]:
    """Return the distinct named variables of `term`, in order of first occurrence."""
    named = (leaf for leaf in leaves(term) if isinstance(leaf, Variable) and not leaf.anonymous)
    return tuple(dict.fromkeys(named))


def build(name: str, arguments: list[Term] | tuple[Term, ...], *, positive: bool = True) -> Term:
    """Build `name(arguments)`: a symbol when every argument is one, otherwise a compound."""
    symbols = [argument for argument in arguments if isinstance(argument, Symbol)]
    if len(symbols) == len(arguments):
        return Function(name, symbols, positive)
    return Compound(name, tuple(arguments), positive)


def _arguments(term: Term) -> tuple[Term, ...]:
    return term.arguments if isinstance(term, Compound) else ()


def substitute_with(term: Term, binding: Callable[[Variable], Term | None]) -> Term:
    """Replace each variable of `term` the binding gives a term for, following the new terms too.

    A binding may mention variables that are themselves bound, so the result is the fixpoint; the
    bindings must not be cyclic. The cost is the size of the result.
    """

    def resolved(node: Term) -> Term:
        while isinstance(node, Variable) and (bound := binding(node)) is not None:
            node = bound
        return node

    def below(node: Term) -> tuple[Term, ...]:
        return _arguments(resolved(node))

    def assemble(node: Term, results: list[Term]) -> Term:
        node = resolved(node)
        if isinstance(node, Compound):
            return build(node.name, results, positive=node.positive)
        return node

    return fold(term, below, assemble)


def rename(term: Term, renaming: Callable[[Variable], Variable]) -> Term:
    """Return `term` with each variable replaced by what `renaming` makes of it, once."""

    def assemble(node: Term, results: list[Term]) -> Term:
        match node:
            case Compound(name, _, positive):
                return build(name, results, positive=positive)
            case Variable():
                return renaming(node)
            case _:
                return node

    return fold(term, _arguments, assemble)


def render(term: Term) -> str:
    """Write `term` as the program would."""

    def assemble(node: Term, results: list[str]) -> str:
        match node:
            case Compound(name, _, positive):
                body = ",".join(results)
                if name == "" and len(results) == 1:
                    body += ","
                return f"{'' if positive else '-'}{name}({body})"
            case Variable(name):
                return name
            case _:
                return str(node)

    return fold(term, _arguments, assemble)
