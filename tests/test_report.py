from elenctic.report import Exit, Run
from elenctic.search import Limits
from runs import FAILING, FAULTY, PASSING, UNDECIDED_COUNT, entry


def test_a_run_of_passing_sources_holds() -> None:
    assert Run((entry(PASSING, "a.lp"),)).exit_code == Exit.CLAIMS_HOLD


def test_a_run_with_no_source_holds() -> None:
    assert Run(()).exit_code == Exit.CLAIMS_HOLD


def test_a_failing_claim_leaves_the_claim_unmet() -> None:
    assert Run((entry(PASSING, "a.lp"), entry(FAILING, "b.lp"))).exit_code == Exit.CLAIM_UNMET


def test_an_undecided_claim_leaves_the_claim_unmet() -> None:
    assert (
        Run((entry(UNDECIDED_COUNT, "u.lp", Limits(max_answer_sets=1)),)).exit_code
        == Exit.CLAIM_UNMET
    )


def test_a_fault_outranks_a_failure() -> None:
    run = Run((entry(FAILING, "b.lp"), entry(FAULTY, "c.lp")))
    assert run.exit_code == Exit.FAULT


def test_the_exit_codes_are_fixed() -> None:
    assert [(e.name, e.value) for e in Exit] == [
        ("CLAIMS_HOLD", 0),
        ("CLAIM_UNMET", 1),
        ("FAULT", 2),
        ("INTERNAL_ERROR", 3),
    ]
