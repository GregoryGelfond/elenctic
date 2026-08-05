"""What elenctic reads is the answer set restricted to the shown vocabulary — nothing narrower, and
nothing else.

Two directives can break that, and they break it in opposite directions. A
``#show <term> : <body>.`` directive **adds** to the output a term that need not be an atom of any
answer set, so a reading over the output is not a reading over the answer sets. A ``#project``
directive **removes** members from an enumeration, so a census is a reading over part of AS(P).
Either way a contract can be certified on a false claim, and neither is visible in the verdict.

Both are checked on clingo and on clingcon, because the property belongs to the seam every backend
comes through rather than to one of them.
"""

from pathlib import Path

import pytest

from elenctic.discovery import discover
from elenctic.harness import case_verdict, run_case
from elenctic.program import inspect
from elenctic.result import Consistent, Verdict, observables_of
from elenctic.run import Mode, runs_for, should_project
from elenctic.solvers import solve

SOLVERS = ("clingo", "clingcon")
"""Both backends, for every property here. A theory case declares its solver and carries a theory
atom so the clingcon facade is genuinely the one under test."""


def _case(tmp_path: Path, name: str, contract: str, program: str, solver: str) -> Path:
    """One case file, in the given backend's dialect.

    The theory atom is **single-valued** on purpose. An observable carries its CSP assignment, so
    two answer sets alike in their atoms but differing in that assignment are two observables — a
    two-valued domain would double every census here and make each expected count a statement about
    the fixture rather than about the property. One value keeps the arithmetic the same on both
    backends while still routing the case through clingcon's own facade and propagator.
    """
    preamble = "% @elenctic solver clingcon\n" if solver == "clingcon" else ""
    theory = "&dom { 1..1 } = v.\n" if solver == "clingcon" else ""
    path = tmp_path / f"{name}-{solver}.lp"
    path.write_text(f"{preamble}% @expect sat\n{contract}{theory}{program}", encoding="utf-8")
    return path


def _verdict(path: Path) -> tuple[Verdict, tuple[str, ...]]:
    (case,) = discover(path)
    reports = run_case(case)
    return case_verdict(reports), tuple(report.message for report in reports)


# --- a displayed term is not an atom, and must not enter a reading ---


@pytest.mark.parametrize("solver", SOLVERS)
def test_a_displayed_non_atom_does_not_enter_the_cautious_consequences(
    tmp_path: Path, solver: str
) -> None:
    """`hello` occurs in no answer set, and `#show hello : p(a).` puts it in every model's output.

    Taking the output as the projection puts it in ⋂, so `@cautious { hello }` is certified — a
    silent wrong PASS, measured before the restriction was applied. The query gate does not cover
    this: `@cautious` is not a query, which is the point of holding the property at the seam rather
    than at one tag.
    """
    path = _case(
        tmp_path,
        "phantom-cautious",
        "% @cautious { hello }\n",
        "p(a).\n#show p/1.\n#show hello : p(a).\n",
        solver,
    )
    verdict, messages = _verdict(path)
    assert verdict is Verdict.FAIL, (
        f"`hello` is in no answer set, so a contract claiming it is entailed "
        f"must not pass: {messages}"
    )


@pytest.mark.parametrize("solver", SOLVERS)
def test_a_displayed_non_atom_does_not_enter_the_census(tmp_path: Path, solver: str) -> None:
    # The same symbol reaching `@model`, which compares a whole observable rather than testing
    # membership — so the phantom shows up as an extra element of every model.
    path = _case(
        tmp_path,
        "phantom-model",
        "% @model { p(a), hello }\n",
        "p(a).\n#show p/1.\n#show hello : p(a).\n",
        solver,
    )
    verdict, _ = _verdict(path)
    assert verdict is Verdict.FAIL


@pytest.mark.parametrize("solver", SOLVERS)
def test_every_observable_is_a_subset_of_its_answer_set(tmp_path: Path, solver: str) -> None:
    # The invariant itself, read off the solve rather than inferred from a verdict: whatever the
    # program prints, an observable holds only atoms the model contains.
    path = _case(
        tmp_path,
        "invariant",
        "% @count 2\n",
        "{ pick(a) }.\nseen :- pick(a).\n"
        "#show pick/1.\n#show tag(X) : pick(X).\n#show ghost : #true.\n",
        solver,
    )
    (case,) = discover(path)
    outcome = solve(case.solver, Mode.ENUM_ALL, files=case.files, project=False)
    determination = outcome.determination
    assert isinstance(determination, Consistent), determination
    observables = observables_of(determination)
    assert observables, "the program is satisfiable, so the census is non-empty"
    for observable in observables:
        assert not {str(symbol) for symbol in observable.shown} & {"ghost", "tag(a)"}, (
            f"a displayed term that is no atom reached an observable: {observable.shown}"
        )


# --- a `#project` directive narrows the enumeration below the shown atoms ---


def test_a_project_directive_is_read_off_the_program(tmp_path: Path) -> None:
    # Both spellings clingo accepts, since a signature and an atom are separate AST nodes and a
    # reader that knew only one would leave the other silently unprojected.
    for name, body in (
        ("none", "p(1).\n#show p/1.\n"),
        ("signature", "p(1).\n#project p/1.\n#show p/1.\n"),
        ("atom", "q(a).\n#project q(a).\n#show q/1.\n"),
    ):
        path = tmp_path / f"{name}.lp"
        path.write_text(body, encoding="utf-8")
        assert inspect((path,)).has_projection is (name != "none"), name


def test_a_run_declines_to_project_when_the_program_narrows_it() -> None:
    # The decision, at the one place that makes it. `ENUM_ALL` projects on clingo because doing so
    # is information-preserving onto the shown atoms; a `#project` directive is what makes that
    # premise false, so the run stops asking.
    from elenctic.expectation import parse

    contract = parse("% @expect sat\n% @count 2\n")
    assert should_project(False, Mode.ENUM_ALL, ()) is True
    assert should_project(False, Mode.ENUM_ALL, (), has_projection=True) is False
    ((plain,),) = (runs_for(contract),)
    ((narrowed,),) = (runs_for(contract, has_projection=True),)
    assert plain.project is True
    assert narrowed.project is False


@pytest.mark.parametrize("solver", SOLVERS)
def test_a_project_directive_does_not_shrink_the_census_a_query_reads(
    tmp_path: Path, solver: str
) -> None:
    """`@query no { p(x), q(x) }` over four answer sets, one of which satisfies both conjuncts.

    The true answer is `unknown`. Under a projection onto `p/1` alone, clingo returns one model per
    `p/1` class and the model that satisfies both never arrives — so "false in every answer set"
    holds over what is left and the contract is certified. Measured as a wrong PASS before the run
    stopped projecting.
    """
    program = (
        "{ p(x) }. { q(x) }.\n-p(x) :- not p(x).\n-q(x) :- not q(x).\n"
        "#project p/1.\n#show p/1.\n#show -p/1.\n#show q/1.\n#show -q/1.\n"
    )
    path = _case(tmp_path, "projected-query", "% @query no { p(x), q(x) }\n", program, solver)
    verdict, messages = _verdict(path)
    assert verdict is Verdict.FAIL, (
        f"one answer set satisfies both conjuncts, so the answer is unknown, not no: {messages}"
    )


@pytest.mark.parametrize("solver", SOLVERS)
def test_a_project_directive_does_not_shrink_the_census_a_count_reads(
    tmp_path: Path, solver: str
) -> None:
    # `@count` reads the census directly, so it is the shortest statement of the same property:
    # four answer sets are four observables whatever the program asks the solver to project onto.
    program = (
        "{ p(x) }. { q(x) }.\n-p(x) :- not p(x).\n-q(x) :- not q(x).\n"
        "#project p/1.\n#show p/1.\n#show -p/1.\n#show q/1.\n#show -q/1.\n"
    )
    path = _case(tmp_path, "projected-count", "% @count 4\n", program, solver)
    verdict, messages = _verdict(path)
    assert verdict is Verdict.PASS, messages
