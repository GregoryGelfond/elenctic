"""Reading and renaming clingo's syntax trees, types known: the one place loose attributes end."""

from collections.abc import Callable, Iterator
from copy import copy
from typing import TypeGuard

from clingo import Symbol
from clingo.ast import AST, ASTSequence, ASTType, Location

from elenctic.spans import Position, Span
from elenctic.traversal import fold


def _field[T](node: AST, key: str, expected: type[T]) -> T:
    """Return what `node` holds under `key`, which must be an `expected`."""
    value: object = getattr(node, key)
    if isinstance(value, expected):
        return value
    message = f"a {kind(node).name} holds its `{key}` as a {type(value).__name__}"
    raise TypeError(message)


def kind(node: AST) -> ASTType:
    """Return which sort of node `node` is."""
    return _field(node, "ast_type", ASTType)


def name(node: AST) -> str:
    """Return the name a node carries, of a function, a variable, a program or a signature."""
    return _field(node, "name", str)


def number(node: AST, key: str) -> int:
    """Return the number `node` holds under `key`: an arity, a sign, an operator."""
    return _field(node, key, int)


def child(node: AST, key: str) -> AST:
    """Return the node that `node` holds under `key`."""
    return _field(node, key, AST)


def children(node: AST, key: str) -> tuple[AST, ...]:
    """Return the nodes that `node` holds under `key`, in order."""
    return tuple(_nodes(_field(node, key, ASTSequence)))


def symbol(node: AST) -> Symbol:
    """Return the ground term a symbolic node is."""
    return _field(node, "symbol", Symbol)


def span(node: AST) -> Span:
    """Return where clingo says `node` was written: the name it reports, columns in UTF-8 bytes."""
    location = _field(node, "location", Location)
    begin, end = location.begin, location.end
    return Span(begin.filename, Position(begin.line, begin.column), Position(end.line, end.column))


def holds_flag(node: AST, key: str) -> bool:
    """Say whether `node` holds a set flag under `key`: the `external` of a function."""
    return bool(getattr(node, key))


def is_node(value: object) -> TypeGuard[AST]:
    """Say whether `value` is a node of a tree."""
    return isinstance(value, AST)


def subtrees(node: AST) -> Iterator[AST]:
    """Yield the nodes directly beneath `node`, whether held singly or in sequences."""
    for key in node.child_keys:
        held: object = getattr(node, key)
        if isinstance(held, AST):
            yield held
        elif isinstance(held, ASTSequence):
            yield from _nodes(held)


def _nodes(sequence: ASTSequence) -> Iterator[AST]:
    """Yield the nodes of a sequence of them."""
    for item in sequence:
        if is_node(item):
            yield item


def holds_somewhere(root: AST, holds: Callable[[AST], bool]) -> bool:
    """Say whether `holds` of `root` or of a node beneath it, however deep the tree."""
    return fold(
        root,
        lambda node: tuple(subtrees(node)),
        lambda node, below: holds(node) or any(below),
    )


def renamed(node: AST, rename: Callable[[str], str]) -> AST:
    """Copy `node`, giving each of its variables the name `rename` gives it, in the order written.

    The copy is changed in place, never rebuilt: clingo builds a node through its one variadic C
    function, which conda-forge's cffi on Apple arm64 calls wrongly, crashing the process.
    """
    root = copy(node)
    pending = [root]
    while pending:
        each = pending.pop()
        if kind(each) is ASTType.Variable:
            each.name = rename(name(each))
        pending.extend(reversed(_copied_beneath(each)))
    return root


def _copied_beneath(node: AST) -> list[AST]:
    """Put a copy in place of each node directly beneath `node`, and give the copies in order.

    A copy is of the one node, still holding the nodes beneath it; clingo's deep copy is not
    used, because it leaves a guard shared with the original.
    """
    copies: list[AST] = []
    for key in node.child_keys:
        held: object = getattr(node, key)
        if isinstance(held, AST):
            fresh = copy(held)
            setattr(node, key, fresh)
            copies.append(fresh)
        elif isinstance(held, ASTSequence):
            each = [copy(item) for item in _nodes(held)]
            setattr(node, key, each)
            copies.extend(each)
    return copies
