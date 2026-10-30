import pytest

from elenctic.check import NO_LIMITS, Finding, Report, Verdict, check
from elenctic.determination import Truncation
from elenctic.engine import Fault, Limits, Locus, Program

DRINKS = """
1 { tea; coffee } 1.
biscuit.
#show tea/0. #show coffee/0. #show biscuit/0.
"""


def run(text: str, *, limits: Limits = NO_LIMITS) -> Report:
    found = check(Program(text, "t.lp"), limits=limits)
    assert isinstance(found, Report), found
    return found


def verdicts(text: str, *, limits: Limits = NO_LIMITS) -> list[Verdict]:
    return [f.verdict for f in run(text, limits=limits).findings]


P, F, U = Verdict.PASS, Verdict.FAIL, Verdict.UNDECIDED


def test_the_drinks_contract_holds() -> None:
    report = run(
        DRINKS
        + "% @expect sat\n% @count 2\n% @cautious { biscuit }\n% @brave { tea, coffee }\n"
        + "% @model { tea, biscuit }\n"
    )
    assert report.verdict is P
    assert [f.verdict for f in report.findings] == [P] * 5


def test_a_wrong_claim_fails_and_says_what_the_program_does() -> None:
    (finding,) = run(DRINKS + "% @expect sat\n% @cautious { tea }\n").findings[1:]
    assert finding.verdict is F
    assert finding.claim.span.start.line == 6
    assert "missing: { tea }" in finding.detail
    assert "{ biscuit }" in finding.detail


def test_the_count_is_of_distinct_shown_answer_sets() -> None:
    assert verdicts("{a}. #show b/0. b.\n% @expect sat\n% @count 1") == [P, P]
    assert verdicts("{a}. b.\n% @expect sat\n% @count 2") == [P, P]


def test_expecting_unsat_passes_only_without_an_answer_set() -> None:
    assert verdicts("p. :- p.\n% @expect unsat\n% @count 0") == [P, P]
    assert verdicts("p.\n% @expect unsat") == [F]
    assert verdicts("p. :- p.\n% @expect sat") == [F]


def test_every_model_claim_fails_when_there_is_no_answer_set() -> None:
    text = "p. :- p.\n% @expect sat\n% @model { p }\n% @brave { p }\n% @query yes { p }\n"
    assert verdicts(text) == [F, F, F, F]


def test_a_scenario_is_judged_apart_from_the_program() -> None:
    text = (
        DRINKS
        + "% @expect sat\n% @cautious { tea } assuming { tea }\n"
        + "% @expect unsat assuming { tea, coffee }\n"
    )
    assert verdicts(text) == [P, P, P]


def test_a_refuted_scenario_names_the_assumptions_at_fault() -> None:
    report = run(DRINKS + "% @expect sat\n% @brave { tea } assuming { tea, coffee }\n")
    assert "tea" in report.findings[1].detail
    assert "coffee" in report.findings[1].detail


def test_queries_are_answered_over_every_answer_set() -> None:
    text = DRINKS + (
        "% @expect sat\n"
        "% @query yes { biscuit }\n"
        "% @query unknown { tea }\n"
        "% @query unknown { tea, coffee }\n"
        "% @query no { tea, coffee }\n"
    )
    assert verdicts(text) == [P, P, P, P, F]


def test_binding_queries_are_checked_against_the_partition_of_instances() -> None:
    program = "p(1). -p(2). {p(3)}. #show p/1. #show -p/1.\n% @expect sat\n"
    ok = (
        "% @query yes { p(X) } = { 1 }\n% @query no { p(X) } = { 2 }\n"
        "% @query unknown { p(X) } = { 3 }\n"
    )
    assert verdicts(program + ok) == [P, P, P, P]
    assert verdicts(program + "% @query yes { p(X) } = { 1, 3 }") == [P, F]


def test_a_search_that_did_not_finish_leaves_the_universal_claims_open() -> None:
    text = "{p(1..40)}. q.\n% @expect sat\n% @count 5\n% @cautious { p(1) }\n% @brave { q }\n"
    report = run(text, limits=Limits(models=100))
    assert [f.verdict for f in report.findings] == [P, F, F, P]


def test_a_search_cut_short_is_undecided_not_failed() -> None:
    text = "{p(1..40)}.\n% @expect sat\n% @model { p(1), p(40) }\n% @query yes { p(1), p(2) }\n"
    report = run(text, limits=Limits(seconds=0))
    assert [f.verdict for f in report.findings] == [U, U, U]
    assert report.verdict is U
    assert str(Truncation.BUDGET) in report.findings[0].detail


def test_a_satisfiability_claim_alone_asks_the_solver_for_one_model() -> None:
    assert verdicts("{p(1..40)}.\n% @expect sat", limits=Limits(seconds=5)) == [P]


def test_the_verdict_of_a_report_is_its_worst_finding() -> None:
    assert run("{a}.\n% @expect sat\n% @count 3").verdict is F
    assert run("{a}.\n% @expect sat").verdict is P


def test_a_malformed_contract_is_a_fault_of_the_request_with_every_diagnostic() -> None:
    found = check(Program("p.\n% @count x\n% @cautious { }\n", "t.lp"))
    assert isinstance(found, Fault)
    assert found.locus is Locus.REQUEST
    assert len(found.diagnostics) >= 2


def test_a_program_that_does_not_ground_is_a_fault_of_the_program() -> None:
    found = check(Program("p(X) :- q(Y).\n% @expect sat\n", "t.lp"))
    assert isinstance(found, Fault)
    assert found.locus is Locus.PROGRAM


def test_a_file_without_a_contract_has_nothing_to_check() -> None:
    assert check(Program("p.\n", "t.lp")) is None


@pytest.mark.parametrize("claim", ["% @cautious { p }", "% @count 1", "% @query yes { p }"])
def test_a_finding_prints_the_claim_it_judged(claim: str) -> None:
    (_, finding) = run(f"p.\n% @expect sat\n{claim}\n").findings
    assert isinstance(finding, Finding)
    assert finding.claim_text == claim.removeprefix("% ")
