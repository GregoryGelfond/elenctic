"""Reading clingo's syntax trees with their types known: the one place its loose attributes end."""

from collections.abc import Callable, Iterator
from typing import TypeGuard

from clingo import Symbol
from clingo.ast import AST, ASTSequence, ASTType, Location

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


def location(node: AST) -> Location:
    """Return where `node` was written."""
    return _field(node, "location", Location)


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
