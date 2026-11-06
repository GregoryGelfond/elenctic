"""The tags that state facts of the answer sets: expectation, count, cost, each, consequences."""

import re
from collections.abc import Callable
from typing import Final

from elenctic.contract import Assigns, Census, Costs, Entails, Reading, Satisfiable, Witness
from elenctic.determination import Mode, Range, Valuation
from elenctic.literals import Atoms
from elenctic.operands import after, ground, read_range, shown, valuations
from elenctic.spans import Diagnostic, Parsed, failure
from elenctic.tags import Block, Element

_INTEGER: Final = re.compile(r"-?\d+")


def expect(block: Block, head: list[Element]) -> Parsed[Reading]:
    match [e.text for e in head if not e.braced]:
        case ["sat"] if len(head) == 1:
            return Satisfiable(expected=True)
        case ["unsat"] if len(head) == 1:
            return Satisfiable(expected=False)
        case _:
            return failure(
                block.covering(),
                f"expected `sat` or `unsat`, found `{shown(head)}`",
                label="expected `sat` or `unsat`",
            )


def count(block: Block, head: list[Element]) -> Parsed[Reading]:
    over, rest = read_range(head)
    if len(rest) == 1 and not rest[0].braced and rest[0].text.isdecimal():
        return Census(int(rest[0].text), over)
    return failure(
        block.covering(),
        f"expected a non-negative integer, found `{shown(rest)}`",
        label="expected a non-negative integer",
    )


def cost(block: Block, head: list[Element]) -> Parsed[Reading]:
    levels = head[0].text.split() if len(head) == 1 and head[0].braced else []
    if levels and all(_INTEGER.fullmatch(level) for level in levels):
        return Costs(tuple(map(int, levels)))
    return failure(
        block.covering(),
        f"expected `{{ c1 c2 ... }}`, found `{shown(head)}`",
        label="expected one integer per priority level",
    )


def litset(
    make: Callable[[Atoms, Range], Reading], *, over: Range | None = None
) -> Callable[[Block, list[Element]], Parsed[Reading]]:
    """Read `[optimal] { literals }`; with `over` fixed, as for `@optimal`, no `optimal` word."""

    def read(block: Block, head: list[Element]) -> Parsed[Reading]:
        chosen, rest = (over, head) if over is not None else read_range(head)
        if len(rest) != 1 or not rest[0].braced:
            return failure(
                block.covering(),
                f"expected `{{ literals }}`, found `{shown(rest)}`",
                label="expected `{ literals }`",
            )
        literals = ground(block, rest[0])
        return literals if isinstance(literals, Diagnostic) else make(literals, chosen)

    return read


def assign(block: Block, head: list[Element]) -> Parsed[Reading]:
    over, rest = read_range(head)
    if len(rest) != 1 or not rest[0].braced:
        return failure(
            block.covering(),
            f"expected `{{ term = integer, ... }}`, found `{shown(rest)}`",
            label="expected `{ term = integer, ... }`",
        )
    assignment = valuations(block, rest[0])
    return assignment if isinstance(assignment, Diagnostic) else Assigns(assignment, over)


def witness(over: Range | None = None) -> Callable[[Block, list[Element]], Parsed[Reading]]:
    """Read `[optimal] { literals } [where { x=1, ... }]`, as `@answer-set` or `@optimal`."""

    def read(block: Block, head: list[Element]) -> Parsed[Reading]:
        split = after(block, head, "where", "term = integer, ...")
        if isinstance(split, Diagnostic):
            return split
        assignment = frozenset[Valuation]() if split[1] is None else valuations(block, split[1])
        if isinstance(assignment, Diagnostic):
            return assignment
        return litset(lambda lits, chosen: Witness(lits, chosen, assignment), over=over)(
            block, split[0]
        )

    return read


cautious: Final = litset(lambda lits, over: Entails(Mode.CAUTIOUS, lits, over))
brave: Final = litset(lambda lits, over: Entails(Mode.BRAVE, lits, over))
