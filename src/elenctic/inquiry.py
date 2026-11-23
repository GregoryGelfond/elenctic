"""Questions asked of one program: why an atom holds or not, and what a query comes to.

`why` explains an atom in one answer set, picked by its index; `ask` answers a query over every
answer set. Each opens the program as `check` does: contained under its root, and run by the
solver its contract names, if it has one.
"""

from enum import IntEnum
from pathlib import Path

from elenctic.contract import Solver
from elenctic.determination import Range, Refutation
from elenctic.engine import containment
from elenctic.explanation import Counterexample, Explanation
from elenctic.literals import Literal, Scenario
from elenctic.program import Fault, Locus, Program
from elenctic.query import Answered, Query
from elenctic.reader import parse_contract
from elenctic.report import Internal
from elenctic.search import Interrupt, Limit, Limits
from elenctic.session import Session, session
from elenctic.spans import failure
from elenctic.tags import is_case
from elenctic.verdicts import Ended

type Why = Explanation | Refutation | Ended | Fault
"""What `why` comes to: the explanation, or why there is none."""
type Ask = Answered | Refutation | Ended | Fault
"""What `ask` comes to: the answer, or why there is none."""


class WhyExit(IntEnum):
    """The status `elenctic why` exits with; the values are fixed."""

    EXPLAINED = 0
    """The atom was explained."""
    ENDED = 1
    """The search ended before it reached the answer set."""
    FAULT = 2
    """The program, the atom or the index was refused, or there is no answer set to explain."""
    INTERNAL_ERROR = 3
    """elenctic itself failed."""

    @classmethod
    def of(cls, result: Why | Internal) -> WhyExit:
        """Name the status a result exits with."""
        match result:
            case Explanation():
                return cls.EXPLAINED
            case Ended():
                return cls.ENDED
            case Internal():
                return cls.INTERNAL_ERROR
            case _:
                return cls.FAULT


class AskExit(IntEnum):
    """The status `elenctic ask` exits with, whatever the answer is; the values are fixed."""

    ANSWERED = 0
    """The query was answered."""
    ENDED = 1
    """The search ended before it read every answer set."""
    FAULT = 2
    """The program or the query was refused, or there is no answer set to answer over."""
    INTERNAL_ERROR = 3
    """elenctic itself failed."""

    @classmethod
    def of(cls, result: Ask | Internal) -> AskExit:
        """Name the status a result exits with: `why`'s, with an answer for the explanation."""
        return cls.ANSWERED if isinstance(result, Answered) else cls(WhyExit.of(result))


def _opened(
    program: Program,
    *,
    limits: Limits = Limits(),
    interrupt: Interrupt | None = None,
    root: Path | None = None,
) -> Session | Fault:
    """Open `program` as `check` would: contained under `root`, by its contract's solver."""
    if (refused := containment(program, root)) is not None:
        return refused
    solver = Solver.CLINGO
    if is_case(program.text):
        contract = parse_contract(program.text, program.source)
        if contract.diagnostics:
            return Fault(Locus.REQUEST, contract.diagnostics)
        solver = contract.solver
    return session(program, solver, limits=limits, interrupt=interrupt)


def why(  # noqa: PLR0913
    program: Program,
    atom: Literal,
    *,
    index: int = 1,
    scenario: Scenario = frozenset(),
    over: Range = Range.ALL,
    limits: Limits = Limits(),
    interrupt: Interrupt | None = None,
    max_depth: int | Limit = Limit.UNBOUNDED,
    root: Path | None = None,
) -> Why:
    """Explain why `atom` holds, or not, in the `index`-th answer set of `scenario`.

    `over` counts all the answer sets or only the optima. Past the last one is a fault.
    """
    session_ = _opened(program, limits=limits, interrupt=interrupt, root=root)
    if isinstance(session_, Fault):
        return session_
    found = session_.counterexample(index, scenario, over=over)
    if found is None:
        return _past(session_, index, scenario, over)
    if not isinstance(found, Counterexample):
        return found
    return session_.explain((atom,), found, max_depth=max_depth)


def _past(session_: Session, index: int, scenario: Scenario, over: Range) -> Fault:
    """Refuse an index past the last answer set, naming how many the search read."""
    last = session_.counterexample(1, scenario, over=over)
    read = last.read if isinstance(last, Counterexample) else 0
    kind = "optimal answer set" if over is Range.OPTIMAL else "answer set"
    problem = failure(
        None,
        f"there is no {kind} {index}: the search read {read}",
        help=(f"`--answer-set` counts from 1 to {read}",),
    )
    return Fault(Locus.REQUEST, (problem,))


def ask(  # noqa: PLR0913
    program: Program,
    query: Query,
    *,
    scenario: Scenario = frozenset(),
    over: Range = Range.ALL,
    limits: Limits = Limits(),
    interrupt: Interrupt | None = None,
    root: Path | None = None,
) -> Ask:
    """Answer `query` over every answer set of `scenario`, or only the optima, as `@query` does."""
    session_ = _opened(program, limits=limits, interrupt=interrupt, root=root)
    if isinstance(session_, Fault):
        return session_
    return session_.answer(query, scenario, over=over)
