"""Questions asked of one program: why an atom holds or not, and what a query comes to.

`why` explains an atom in one answer set, picked by its index, or, given none, shows what warrants
a query's answer; `ask` answers a query over every answer set. Each opens the program as `check`
does: contained under its root, and run by the solver its contract names, if it has one.
"""

from enum import IntEnum
from pathlib import Path
from typing import TypedDict, Unpack, overload

from elenctic.contract import Solver
from elenctic.determination import Range, Refutation
from elenctic.engine import containment
from elenctic.explanation import Counterexample, Explanation
from elenctic.gates import lacks_objective
from elenctic.literals import Literal, Scenario, Symbol
from elenctic.program import Fault, Locus, Program
from elenctic.query import Answered, AnswerMode, Query, Warrant
from elenctic.reader import parse_contract
from elenctic.report import Internal
from elenctic.search import Interrupt, Limit, Limits
from elenctic.session import Session, session
from elenctic.spans import failure
from elenctic.tags import is_case
from elenctic.verdicts import Ended

type Why = Explanation | Warrant | Refutation | Ended | Fault
"""What `why` comes to: the explanation, or the warrant, or why there is none."""
type Ask = Answered | Refutation | Ended | Fault
"""What `ask` comes to: the answer, or why there is none."""


class WhyExit(IntEnum):
    """The status `elenctic why` exits with; the values are fixed."""

    EXPLAINED = 0
    """The atom was explained, or the answer warranted."""
    ENDED = 1
    """The search ended before it reached the answer set."""
    FAULT = 2
    """The program, the query, the index or the binding was refused, or there is no answer set."""
    INTERNAL_ERROR = 3
    """elenctic itself failed."""

    @classmethod
    def of(cls, result: Why | Internal) -> WhyExit:
        """Name the status a result exits with."""
        match result:
            case Explanation() | Warrant():
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
        if isinstance(result, Answered):
            return cls.ENDED if result.cut is not None else cls.ANSWERED
        return cls(WhyExit.of(result))


def _opened(
    program: Program,
    over: Range,
    *,
    limits: Limits = Limits(),
    interrupt: Interrupt | None = None,
    root: Path | None = None,
) -> Session | Fault:
    """Open `program` as `check` would: contained under `root`, by its contract's solver.

    Its optimal answer sets are refused, as an optimal claim is, when nothing ranks them.
    """
    if (refused := containment(program, root)) is not None:
        return refused
    solver = Solver.CLINGO
    if is_case(program.text):
        contract = parse_contract(program.text, program.source)
        if contract.diagnostics:
            return Fault(Locus.REQUEST, contract.diagnostics)
        solver = contract.solver
    opened = session(program, solver, limits=limits, interrupt=interrupt)
    if isinstance(opened, Session) and over is Range.OPTIMAL and not opened.facts.optimizes:
        return Fault(Locus.REQUEST, (lacks_objective(None, "the optimal answer sets asked for"),))
    return opened


class _Searched(TypedDict, total=False):
    """How either form of `why` searches the program, and how deep it explains an answer set."""

    scenario: Scenario
    over: Range
    limits: Limits
    interrupt: Interrupt | None
    root: Path | None
    max_depth: int | Limit


class _Warranted(_Searched, total=False):
    """The answer, and the binding, that `why` warrants."""

    values: tuple[Symbol, ...]
    mode: AnswerMode


@overload
def why(
    program: Program, asked: Literal, *, index: int, **given: Unpack[_Searched]
) -> Explanation | Refutation | Ended | Fault: ...
@overload
def why(
    program: Program, asked: Query, *, index: None = None, **given: Unpack[_Warranted]
) -> Warrant | Refutation | Ended | Fault: ...
def why(  # noqa: PLR0913
    program: Program,
    asked: Query,
    *,
    index: int | None = None,
    values: tuple[Symbol, ...] = (),
    mode: AnswerMode = AnswerMode.DEFAULT,
    scenario: Scenario = frozenset(),
    over: Range = Range.ALL,
    limits: Limits = Limits(),
    interrupt: Interrupt | None = None,
    max_depth: int | Limit = Limit.UNBOUNDED,
    root: Path | None = None,
) -> Why:
    """Explain why a ground literal holds, or not, in the `index`-th answer set of `scenario`.

    Given no `index`, show what warrants the answer `asked` comes to as `ask` answers it in
    `mode`, or the answer of its binding to `values`, with its derivation in each witness. `over`
    counts all the answer sets or only the optima; `max_depth` bounds how many absences deep an
    answer set is explained. Past the last one is a fault. An index of anything but a literal is
    a `TypeError`.
    """
    if index is not None and not isinstance(asked, Literal):
        message = "an answer set is explained for one ground literal"
        raise TypeError(message)
    session_ = _opened(program, over, limits=limits, interrupt=interrupt, root=root)
    if isinstance(session_, Fault):
        return session_
    if index is None or not isinstance(asked, Literal):
        answered = session_.answer(asked, scenario, over=over, mode=mode)
        return _warranted(session_, answered, values, scenario, max_depth)
    found = session_.counterexample(index, scenario, over=over)
    if found is None:
        return _past(session_, index, scenario, over)
    if not isinstance(found, Counterexample):
        return found
    return session_.explain((asked,), found, max_depth=max_depth)


def _warranted(
    session_: Session,
    answered: Answered | Refutation | Ended,
    values: tuple[Symbol, ...],
    scenario: Scenario,
    max_depth: int | Limit,
) -> Warrant | Refutation | Ended | Fault:
    """Show what warrants an answer, or its binding to `values`; a refused one is a fault."""
    if not isinstance(answered, Answered):
        return answered
    try:
        return session_.warrant(answered, values, scenario, max_depth=max_depth)
    except ValueError as refused:
        return Fault(Locus.REQUEST, (failure(None, str(refused)),))


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
    mode: AnswerMode = AnswerMode.DEFAULT,
) -> Ask:
    """Answer `query` as `mode` does over every answer set of `scenario`, or only the optima.

    By default it is answered as `@query` answers it.
    """
    session_ = _opened(program, over, limits=limits, interrupt=interrupt, root=root)
    if isinstance(session_, Fault):
        return session_
    return session_.answer(query, scenario, over=over, mode=mode)
