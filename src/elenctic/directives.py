"""The `@elenctic` directives of a contract: which solver it asks for."""

from elenctic.contract import Solver
from elenctic.spans import Diagnostic, Parsed, failure
from elenctic.tags import Block, elements

_KNOWN = " and ".join(f"`{name}`" for name in Solver)
_HELP = (f"known solvers: {_KNOWN}",)


def _words(block: Block) -> list[str]:
    """Return the unbraced words of a directive."""
    return [e.text for e in elements(block.payload) or [] if not e.braced]


def _solver(block: Block) -> Parsed[Solver]:
    """Read `@elenctic solver NAME`, the one directive."""
    match _words(block):
        case ["solver", name] if name in Solver:
            return Solver(name)
        case ["solver", name]:
            return failure(
                block.covering(),
                f"unknown solver `{name}`",
                label="not a known solver",
                help=_HELP,
            )
        case ["solver"]:
            return failure(
                block.covering(),
                "missing solver name",
                label="expected a solver name",
                help=_HELP,
            )
        case [name, *_] | [name]:
            return failure(
                block.covering(),
                f"unknown `@elenctic` directive `{name}`",
                label="not a directive",
                help=("the only directive is `solver`",),
            )
        case _:
            return failure(
                block.covering(),
                "unknown `@elenctic` directive",
                label="not a directive",
                help=("the only directive is `solver`",),
            )


def _read(blocks: list[Block]) -> list[tuple[Block, Parsed[Solver]]]:
    """Read every `@elenctic` block."""
    return [(block, _solver(block)) for block in blocks if block.tag == "elenctic"]


def _surplus(solvers: list[Block]) -> list[Diagnostic]:
    """Fault every declaration after the first."""
    return [
        failure(block.covering(), "solver declared more than once", label="declared again here")
        for block in solvers[1:]
    ]


def declared(blocks: list[Block]) -> tuple[Solver, list[Diagnostic]]:
    """Find the solver a contract declares (clingo if none) and what is wrong with the declaring."""
    read = _read(blocks)
    solvers = [(block, r) for block, r in read if isinstance(r, Solver)]
    refused = [r for _, r in read if isinstance(r, Diagnostic)]
    surplus = _surplus([block for block, _ in solvers])
    return next((r for _, r in solvers), Solver.CLINGO), refused + surplus
