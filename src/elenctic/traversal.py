"""Folding a tree of any depth without recursion."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _Assemble[N]:
    """A node waiting for the results of its `arity` children."""

    node: N
    arity: int


def fold[N, R](
    root: N,
    children: Callable[[N], Sequence[N]],
    assemble: Callable[[N, list[R]], R],
) -> R:
    """Reduce the tree under `root` bottom-up: each node from the results of its children, in order.

    The depth is bounded by memory, not by the interpreter's stack, because the pending nodes live
    in a list; the cost is the number of nodes visited.
    """
    pending: list[N | _Assemble[N]] = [root]
    done: list[R] = []
    while pending:
        match pending.pop():
            case _Assemble(node, arity):
                results = done[len(done) - arity :]
                del done[len(done) - arity :]
                done.append(assemble(node, results))
            case node:
                below = children(node)
                pending.append(_Assemble(node, len(below)))
                pending.extend(reversed(below))
    return done[0]
