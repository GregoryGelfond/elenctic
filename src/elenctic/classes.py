"""Equivalence classes of terms, which unification merges and from which a unifier is read."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum, auto

from clingo import Symbol, SymbolType

from elenctic.partition import Partition
from elenctic.substitution import Substitution
from elenctic.terms import Compound, Term, Variable, build
from elenctic.traversal import fold


@dataclass(frozen=True, slots=True)
class Bare:
    """A variable, and so far nothing else."""

    variable: Variable


@dataclass(frozen=True, slots=True)
class Atom:
    """A number, a string, `#inf` or `#sup`: ground, with nothing beneath it."""

    symbol: Symbol


@dataclass(frozen=True, slots=True)
class Shape:
    """A function or tuple over the classes of its arguments, `-f` when not `positive`."""

    name: str
    positive: bool
    arguments: tuple[int, ...]

    @property
    def kind(self) -> tuple[str, bool, int]:
        """What must agree for two shapes to merge: functor, sign and arity."""
        return self.name, self.positive, len(self.arguments)


type Cell = Bare | Atom | Shape
"""What is known of the terms in one class of the unification graph."""


class Shade(Enum):
    """How far the occurs check has got with a class: not reached, on the path, or finished."""

    WHITE = auto()
    GRAY = auto()
    BLACK = auto()


def _below(term: Term) -> tuple[Term, ...] | list[Symbol]:
    """Return the arguments of a term or ground function, and none for anything else."""
    match term:
        case Compound(_, arguments, _):
            return arguments
        case Variable():
            return ()
        case _:
            return term.arguments if term.type is SymbolType.Function else ()


class Classes:
    """The terms of a unification, one node each, in classes the unifier merges.

    A class is represented by one node, which carries the class's `Cell`: a bare variable merges
    into whatever it meets, two shapes merge into one and their arguments are unified in turn.
    Ground symbols are taken apart into shapes as they are added, exactly as the terms they are
    unified with, so a deep ground symbol is walked once, never copied level by level. Every named
    variable has a single node, however often it occurs.
    """

    def __init__(self) -> None:
        self._classes = Partition()
        self._cells: list[Cell] = []
        self._named: dict[Variable, int] = {}

    def _node(self, cell: Cell) -> int:
        self._cells.append(cell)
        return self._classes.add()

    def _variable(self, variable: Variable) -> int:
        if variable.anonymous:
            return self._node(Bare(variable))
        if variable not in self._named:
            self._named[variable] = self._node(Bare(variable))
        return self._named[variable]

    def add(self, term: Term) -> int:
        """Add `term` as nodes, and return its node; the depth of `term` is not limited."""

        def assemble(node: Term, arguments: list[int]) -> int:
            match node:
                case Variable():
                    return self._variable(node)
                case Compound(name, _, positive):
                    return self._node(Shape(name, positive, tuple(arguments)))
                case _ if node.type is SymbolType.Function:
                    return self._node(Shape(node.name, node.positive, tuple(arguments)))
                case _:
                    return self._node(Atom(node))

        return fold(term, _below, assemble)

    def _link_or_merge(self, left: int, right: int) -> tuple[tuple[int, int], ...] | None:
        """Merge two distinct classes; return the argument pairs still to unify, `None` on a clash.

        A bare variable joins the other class, which keeps its cell as the class's own.
        """
        match self._cells[left], self._cells[right]:
            case Bare(), Bare():
                self._classes.union(left, right)
                return ()
            case Bare(), _:
                self._classes.link(left, right)
                return ()
            case _, Bare():
                self._classes.link(right, left)
                return ()
            case Atom(first), Atom(second):
                return () if first == second else None
            case Shape() as first, Shape() as second if first.kind == second.kind:
                self._classes.union(left, right)
                return tuple(zip(first.arguments, second.arguments, strict=True))
            case _:
                return None

    def unify(self, first: int, second: int) -> bool:
        """Unify two nodes, and say whether their classes could be merged.

        Each pair of classes is merged once however many times it is met, and the pairs wait in a
        list, so sharing costs nothing and depth is no limit.
        """
        pending = [(first, second)]
        while pending:
            left, right = (self._classes.find(node) for node in pending.pop())
            if left != right:
                below = self._link_or_merge(left, right)
                if below is None:
                    return False
                pending.extend(below)
        return True

    def _arguments_of(self, node: int) -> Iterable[int]:
        cell = self._cells[self._classes.find(node)]
        return cell.arguments if isinstance(cell, Shape) else ()

    def acyclic(self) -> bool:
        """Say whether no class has itself beneath it: the occurs check, once, after unifying.

        A depth-first search that colors a class gray while its arguments are searched and black
        after; reaching a gray class closes a cycle. Checking once at the end, not at each binding,
        is what keeps unification near-linear.
        """
        shade = [Shade.WHITE] * len(self._cells)
        roots = (node for node in range(len(self._cells)) if self._classes.find(node) == node)
        return all(shade[r] is not Shade.WHITE or self._search(r, shade) for r in roots)

    def _search(self, start: int, shade: list[Shade]) -> bool:
        pending = [(start, True)]
        while pending:
            node, entering = pending.pop()
            if not entering:
                shade[node] = Shade.BLACK
            elif shade[node] is Shade.WHITE:
                shade[node] = Shade.GRAY
                pending.append((node, False))
                reached = {self._classes.find(child) for child in self._arguments_of(node)}
                if any(shade[r] is Shade.GRAY for r in reached):
                    return False
                pending.extend((r, True) for r in reached if shade[r] is Shade.WHITE)
        return True

    def solution(self) -> Substitution:
        """Read the unifier out of the merged classes, triangular.

        Each class with a named variable is called by its least one, which stands for the class
        wherever another term mentions it; a class with a shape binds that name to the shape. A
        class without a named variable is written out where it is met.
        """
        names: dict[int, Variable] = {}
        for variable, node in sorted(self._named.items(), reverse=True):
            names[self._classes.find(node)] = variable
        bindings: dict[Variable, Term] = {}
        for variable, node in self._named.items():
            root = self._classes.find(node)
            if names[root] != variable:
                bindings[variable] = names[root]
            elif not isinstance(self._cells[root], Bare):
                bindings[variable] = self._term_of(root, names)
        return Substitution(bindings)

    def _term_of(self, root: int, names: dict[int, Variable]) -> Term:
        """Write the class `root` as a term, its arguments by their names where they have one."""

        def called(node: int) -> bool:
            return (rep := self._classes.find(node)) != root and rep in names

        def below(node: int) -> tuple[int, ...] | list[int]:
            return () if called(node) else tuple(self._arguments_of(node))

        def assemble(node: int, arguments: list[Term]) -> Term:
            rep = self._classes.find(node)
            if called(node):
                return names[rep]
            match self._cells[rep]:
                case Bare(variable):
                    return variable
                case Atom(symbol):
                    return symbol
                case Shape(name, positive, _):
                    return build(name, arguments, positive=positive)

        return fold(root, below, assemble)
