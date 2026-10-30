"""Folding a tree of any depth without recursion."""

from collections.abc import Callable, Sequence


def fold[N, R](
    root: N,
    children: Callable[[N], Sequence[N]],
    assemble: Callable[[N, list[R]], R],
) -> R:
    """Reduce the tree under `root` bottom-up: each node from the results of its children, in order.

    The depth is bounded by memory, not by the interpreter's stack, because the pending nodes live
    in a list; the cost is the number of nodes visited.
    """
    pending: list[tuple[N, int | None]] = [(root, None)]
    done: list[R] = []
    while pending:
        match pending.pop():
            case node, int(arity):
                results = done[len(done) - arity :]
                del done[len(done) - arity :]
                done.append(assemble(node, results))
            case node, None:
                below = children(node)
                pending.append((node, len(below)))
                pending.extend((child, None) for child in reversed(below))
    return done[0]
