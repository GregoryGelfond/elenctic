from pathlib import Path

import pytest
from clingo import Function

from elenctic.check import check
from elenctic.cli import main
from elenctic.contract import Solver
from elenctic.determination import Consistent, Exhausted, Optimum, Valuation
from elenctic.engine import ground, solve
from elenctic.program import Fault, Program
from elenctic.report import Exit
from elenctic.verdicts import Report, Verdict
from nesting import nested

pytest.importorskip("clingcon")

SUM = "&dom { 0..3 } = x. &dom { 0..3 } = y. &sum { x ; y } = 3. #show.\n"
CHOICE = "1 { a; b } 1. &dom { 0..3 } = x. &sum { x } >= 2 :- a. &sum { x } <= 1 :- b.\n"
WHICH = CHOICE + "#minimize { 1,a : a }.\n"
CLINGCON = "% @elenctic solver clingcon\n"
P, F, U = Verdict.PASS, Verdict.FAIL, Verdict.UNDECIDED


def assigned(x: int, y: int) -> frozenset[Valuation]:
    return frozenset({Valuation(Function("x"), x), Valuation(Function("y"), y)})


def verdicts(text: str) -> list[Verdict]:
    found = check(Program(text, "t.lp"))
    assert isinstance(found, Report), found
    return [f.verdict for f in found.findings]


def test_every_assignment_of_the_constraints_is_an_answer_set_of_its_own() -> None:
    found = solve(Program(SUM), solver=Solver.CLINGCON)
    assert isinstance(found, Consistent)
    assert found.conclusion is Exhausted.EXHAUSTED
    assert {m.assignment for m in found.evidence.all} == {
        assigned(0, 3),
        assigned(1, 2),
        assigned(2, 1),
        assigned(3, 0),
    }
    assert {m.shown for m in found.evidence.all} == {frozenset()}


def test_a_theory_objective_is_located_where_it_is_written() -> None:
    grounded = ground(Program("&dom { 0..3 } = x.\n&minimize { x }.\n"), Solver.CLINGCON)
    assert not isinstance(grounded, Fault)
    assert grounded.facts.objective is not None
    assert grounded.facts.objective.start.line == 2
    assert ground(Program("&dom { 0..3 } = x."), Solver.CLINGCON).facts.objective is None  # type: ignore[union-attr]


def test_a_program_that_declares_clingcon_without_theory_atoms_is_checked_as_usual() -> None:
    assert verdicts(CLINGCON + "{a}.\n% @expect sat\n% @count 2\n") == [P, P]


def test_the_count_is_of_distinct_answers_a_shown_set_with_its_assignment() -> None:
    assert verdicts(CLINGCON + SUM + "% @expect sat\n% @count 4\n") == [P, P]
    assert verdicts(CLINGCON + SUM + "% @expect sat\n% @count 1\n") == [P, F]
    assert verdicts(CLINGCON + CHOICE + "% @expect sat\n% @count 4\n") == [P, P]


def test_a_count_says_what_it_counted() -> None:
    report = check(Program(CLINGCON + SUM + "% @expect sat\n% @count 1\n"))
    assert isinstance(report, Report)
    assert (
        report.findings[1].detail
        == "1 expected, 4 distinct shown answer sets with their assignments"
    )


def test_assign_holds_when_some_answer_set_gives_each_term_that_integer() -> None:
    text = CLINGCON + SUM + "% @expect sat\n"
    assert verdicts(text + "% @assign { x=1, y=2 }\n") == [P, P]
    assert verdicts(text + "% @assign { x=1, y=1 }\n") == [P, F]
    assert verdicts(text + "% @assign { z=1 }\n") == [P, F]


def test_assign_optimal_ranges_over_the_optimal_answer_sets_only() -> None:
    text = CLINGCON + WHICH + "% @expect sat\n"
    assert verdicts(text + "% @assign { x=2 }\n") == [P, P]
    assert verdicts(text + "% @assign optimal { x=2 }\n") == [P, F]
    assert verdicts(text + "% @assign optimal { x=1 }\n") == [P, P]


def test_where_binds_the_assignment_to_the_same_answer_set_as_the_shown_atoms() -> None:
    text = CLINGCON + CHOICE + "% @expect sat\n"
    assert verdicts(text + "% @assign { x=1 }\n% @brave { a, b }\n") == [P, P, P]
    assert verdicts(text + "% @model { a } where { x=2 }\n") == [P, P]
    assert verdicts(text + "% @model { a } where { x=1 }\n") == [P, F]
    assert verdicts(text + "% @model { b } where { x=1 }\n") == [P, P]


def test_an_optimal_witness_is_over_the_optimal_answer_sets() -> None:
    text = CLINGCON + WHICH + "% @expect sat\n"
    assert verdicts(text + "% @optimal { b } where { x=1 }\n% @optimal { a } where { x=2 }\n") == [
        P,
        P,
        F,
    ]
    report = check(Program(text + "% @cost { 0 }\n% @count optimal 2\n"))
    assert isinstance(report, Report)
    assert [f.verdict for f in report.findings] == [P, P, P]


def test_the_consequences_of_a_theory_program_are_those_of_its_atoms() -> None:
    text = CLINGCON + CHOICE + "% @expect sat\n% @brave { a, b }\n% @cautious { a }\n"
    assert verdicts(text) == [P, P, F]


def test_assumptions_are_refuted_with_a_core_beside_a_theory() -> None:
    text = CLINGCON + CHOICE + "% @expect sat\n% @expect unsat assuming { a, b }\n"
    report = check(Program(text))
    assert isinstance(report, Report)
    assert [f.verdict for f in report.findings] == [P, P]
    assert report.findings[1].detail == "no answer set satisfies the assumptions (a, b)"


def test_a_claim_over_assignments_without_the_solver_says_which_to_declare() -> None:
    found = check(Program("{p}.\n% @expect sat\n% @assign { x=1 }\n", "t.lp"))
    assert isinstance(found, Fault)
    (diagnostic,) = found.diagnostics
    assert diagnostic.span.start.line == 3
    assert diagnostic.message == (
        "reads a theory assignment, but the contract declares no theory solver: "
        "declare `% @elenctic solver clingcon`"
    )


def test_a_theory_objective_is_a_fault_since_no_search_can_switch_it_off() -> None:
    found = check(
        Program(CLINGCON + "&dom { 0..3 } = x.\n&minimize { x }.\n% @expect sat\n", "t.lp")
    )
    assert isinstance(found, Fault)
    (diagnostic,) = found.diagnostics
    assert diagnostic.span.start.line == 3
    assert diagnostic.message.startswith("the program has a theory objective")


def test_the_optimum_found_beside_a_theory_is_proven_and_its_answer_sets_carry_assignments() -> (
    None
):
    grounded = ground(Program(WHICH), Solver.CLINGCON)
    assert not isinstance(grounded, Fault)
    found = grounded.optimize()
    assert isinstance(found, Consistent)
    assert isinstance(found.evidence, Optimum)
    assert found.evidence.cost == (0,)
    x = [frozenset({Valuation(Function("x"), n)}) for n in (0, 1)]
    assert {m.assignment for m in found.evidence.models.all} == set(x)


def test_a_clingcon_contract_runs_from_the_command_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = tmp_path / "sum.lp"
    case.write_text(CLINGCON + SUM + "% @expect sat\n% @count 4\n% @assign { x=1, y=2 }\n")
    assert main([str(tmp_path)]) == Exit.CLAIMS_HOLD
    assert capsys.readouterr().out == "1/1 passed\n"


def test_a_deeply_nested_theory_term_is_checked_not_a_recursion_error() -> None:
    deep = nested()
    text = CLINGCON + f"&dom {{ 0..3 }} = {deep}. &sum {{ {deep} }} >= 0.\n% @expect sat\n"
    assert verdicts(text) == [P]
