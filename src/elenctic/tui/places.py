"""Where a row of the interactive view is in its tree, so the cursor can be kept on it.

The view shows its rows again when it goes deeper, and leaves out or brings back sources; these
find, in the rows shown then, the one the cursor was on.
"""

from collections.abc import Iterator

from textual.widgets.tree import TreeNode

from elenctic.explanation import Handle, Unexpanded
from elenctic.tui.outline import Again, Block, Row, Source, Step

type Node = TreeNode[Row]


def walk(node: Node) -> Iterator[Node]:
    """Walk the nodes beneath `node`, each before its children, in the order they are shown."""
    pending = list(reversed(node.children))
    while pending:
        each = pending.pop()
        yield each
        pending.extend(reversed(each.children))


def holding(node: Node | None, block: int) -> Node | None:
    """Find the nearest row, `node` or above it, whose children are the evidence block `block`."""
    while node is not None and not (node.data is not None and node.data.about == Block(block)):
        node = node.parent
    return node


def stopping(holder: Node) -> bool:
    """Whether some branch beneath `holder` stops at its depth."""
    return any(
        isinstance(each.data.about, Step) and isinstance(each.data.about.node.reason, Unexpanded)
        for each in walk(holder)
        if each.data is not None
    )


def handle_of(row: Row | None) -> Handle | None:
    """Name the step a row shows, as its first row or again; `None` for a row of no step."""
    about = None if row is None else row.about
    if isinstance(about, Step):
        return about.node.handle
    if isinstance(about, Again):
        return about.handle
    return None


def place_of(holder: Node, node: Node) -> tuple[Handle, ...] | None:
    """Say where `node` is beneath `holder`: the steps its row and the rows before it show."""
    if handle_of(node.data) is None:
        return None
    steps: list[Handle] = []
    for each in walk(holder):
        handle = handle_of(each.data)
        if handle is not None:
            steps.append(handle)
        if each is node:
            return tuple(steps)
    return None


def found_at(holder: Node, place: tuple[Handle, ...]) -> Node | None:
    """Find the row at `place` in the rows beneath `holder` shown again, a step deeper.

    Going deeper adds rows and keeps those there were, in their order: so the steps of `place`
    are found in turn, and the row that shows the last of them is the one `place` was.
    """
    wanted = iter(place)
    step: Handle | None = next(wanted)
    for each in walk(holder):
        if handle_of(each.data) != step:
            continue
        step = next(wanted, None)
        if step is None:
            return each
    return None


def is_beneath(node: Node, holder: Node) -> bool:
    """Whether `node` is `holder` or is shown beneath it."""
    above: Node | None = node
    while above is not None and above is not holder:
        above = above.parent
    return above is holder


def top_of(node: Node) -> Node:
    """Find the row at the top of the tree that `node` is, or is beneath."""
    while node.parent is not None and node.parent.parent is not None:
        node = node.parent
    return node


def has_failed(row: Row | None) -> bool:
    return row is not None and isinstance(row.about, Source) and row.about.failed


def instead(tops: list[Node], at: Node | None) -> Node | None:
    """Find the source the cursor goes to when only failures are shown, if its own is left out.

    It is the next source that failed after the cursor's, else the last before it; `None` if the
    cursor stays, or no source failed.
    """
    if at is None or has_failed(top_of(at).data):
        return None
    left = tops.index(top_of(at))
    after = [node for node in tops[left:] if has_failed(node.data)]
    before = [node for node in tops[:left] if has_failed(node.data)]
    return next(iter(after or before[-1:]), None)
