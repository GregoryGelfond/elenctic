"""The `@elenctic` directives of a contract: which solver it asks for."""

from elenctic.contract import Solver
from elenctic.spans import Diagnostic, Parsed, failure
from elenctic.tags import Block, elements


def _words(block: Block) -> list[str]:
    """Return the unbraced words of a directive."""
    return [e.text for e in elements(block.payload) or [] if not e.braced]


def _solver(block: Block) -> Parsed[Solver]:
    """Read `@elenctic solver NAME`, the one directive."""
    known = ", ".join(Solver)
    match _words(block):
        case ["solver", name] if name in Solver:
            return Solver(name)
        case ["solver", _]:
            return failure(block.covering(), f"unknown solver; known: {known}")
        case ["solver"]:
            return failure(
                block.covering(), f"`@elenctic solver` needs a solver name; known: {known}"
            )
        case _:
            return failure(block.covering(), "unknown `@elenctic` directive; known: `solver`")


def _read(blocks: list[Block]) -> list[tuple[Block, Parsed[Solver]]]:
    """Read every `@elenctic` block."""
    return [(block, _solver(block)) for block in blocks if block.tag == "elenctic"]


def _surplus(solvers: list[Block]) -> list[Diagnostic]:
    """Fault every declaration after the first."""
    return [failure(block.covering(), "at most one `@elenctic solver`") for block in solvers[1:]]


def declared(blocks: list[Block]) -> tuple[Solver, list[Diagnostic]]:
    """Find the solver a contract declares (clingo if none) and what is wrong with the declaring."""
    read = _read(blocks)
    solvers = [(block, r) for block, r in read if isinstance(r, Solver)]
    refused = [r for _, r in read if isinstance(r, Diagnostic)]
    surplus = _surplus([block for block, _ in solvers])
    return next((r for _, r in solvers), Solver.CLINGO), refused + surplus
