"""What a run records about a fault it met — the register a reader and a machine both read.

Every other test of the command line asserts a process status and some prose on standard error. The
status reads one closed bit off a record (is this ours or theirs), and each line of prose is written
where the fault is met, so between them they leave the rest of a record — the locus it was filed
under, what it stopped, the file it belongs to — with nothing observing it. A record's locus is what
a machine-readable report is mostly made of, so it is asserted here directly, against the value the
run produces rather than against the sentence it happened to print.
"""

from dataclasses import fields
from pathlib import Path

import pytest

from elenctic import cli, discovery
from elenctic.cli import exit_status, explain_corpus, main, run_corpus
from elenctic.outcome import (
    ErrorKind,
    Grade,
    HygieneKind,
    Invocation,
    RunOutcome,
    Scope,
)
from elenctic.result import Verdict
from elenctic.run import RoutingError
from elenctic.run import runs_for as real_runs_for
from elenctic.solvers import TIME_BUDGET

_PASSES = "% @expect sat\n% @count 2\n\n1 { tea; coffee } 1.\n#show tea/0.\n#show coffee/0.\n"
_WILL_NOT_GROUND = "% @expect sat\n% @count 1\n\nq(1).\np(X) :- q(Y).\n"
_UNRESOLVABLE_INCLUDE = '% @expect sat\n% @count 1\n\n#include "no_such_library.lp".\n'
_MALFORMED_CONTRACT = "% @expect banana\n\nb.\n"
_NAMES_A_SOLVER_THAT_DOES_NOT_EXIST = (
    "% @elenctic solver nosuchsolver\n% @expect sat\n\nb.\n#show b/0.\n"
)
_DECLARES_THE_THEORY_SOLVER = (
    "% @elenctic solver clingcon\n% @expect sat\n% @assign { x=1 }\n\n&sum { x } = 1.\n"
)


def _asked(target: Path, *, strict: bool = False, deadline: float | None = None) -> Invocation:
    return Invocation(target=target, strict=strict, budget=TIME_BUDGET, deadline=deadline)


def _corpus(root: Path, **cases: str) -> Path:
    for name, text in cases.items():
        (root / f"{name}.lp").write_text(text, encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("contract", "kind", "scope"),
    [
        (_WILL_NOT_GROUND, ErrorKind.PROGRAM, Scope.CASE),
        (_UNRESOLVABLE_INCLUDE, ErrorKind.PROGRAM, Scope.CASE),
        (_MALFORMED_CONTRACT, ErrorKind.CONTRACT, Scope.CASE),
        # Naming a solver that does not exist is a fault in the contract line, not in the
        # environment: no installation would make it right.
        (_NAMES_A_SOLVER_THAT_DOES_NOT_EXIST, ErrorKind.CONTRACT, Scope.CASE),
    ],
    ids=["will-not-ground", "unresolvable-include", "malformed-contract", "no-such-solver"],
)
def test_a_case_that_produces_no_verdict_is_filed_under_its_own_locus(
    tmp_path: Path, contract: str, kind: ErrorKind, scope: Scope
) -> None:
    target = _corpus(tmp_path, broken=contract)
    outcome = run_corpus(_asked(target))
    (record,) = outcome.errors
    assert record.kind is kind
    assert record.scope is scope
    assert record.source == target / "broken.lp", "the file the reader has to open"
    assert record.message, "an error whose reason was dropped is not a report"


def test_a_declared_solver_this_environment_lacks_is_filed_against_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other half of the pair above: the contract is well-formed and the solver is real, so the
    # fault is that this machine does not have it — which a different machine would not have.
    monkeypatch.setattr(discovery, "_installed", lambda module: module != "clingcon")
    target = _corpus(tmp_path, theory=_DECLARES_THE_THEORY_SOLVER)
    (record,) = run_corpus(_asked(target)).errors
    assert record.kind is ErrorKind.DISCOVERY
    assert record.scope is Scope.CASE
    assert record.source == target / "theory.lp"


def test_a_case_that_exhausts_a_resource_is_filed_apart_from_a_broken_program(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Raised where the solver raises it. Its own locus rather than the program's: nothing about the
    # encoding is wrong, and the machine that ran it is the one able to bound what it consumed.
    def out_of_memory(*_args: object, **_kwargs: object) -> None:
        raise MemoryError("std::bad_alloc")

    monkeypatch.setattr(cli, "run_case", out_of_memory)
    target = _corpus(tmp_path, greedy=_PASSES)
    (record,) = run_corpus(_asked(target)).errors
    assert record.kind is ErrorKind.RESOURCE
    assert record.scope is Scope.CASE
    assert record.source == target / "greedy.lp"


def test_a_corpus_that_cannot_be_discovered_produces_no_cases_and_one_error(
    tmp_path: Path,
) -> None:
    outcome = run_corpus(_asked(tmp_path / "nowhere.lp"))
    (record,) = outcome.errors
    assert outcome.cases == ()
    assert record.kind is ErrorKind.DISCOVERY
    assert record.scope is Scope.CORPUS, "nothing was discovered, so this belongs to no case"
    assert record.source is None, "and a target that is not one file names no one file"


def test_a_corpus_fault_on_a_named_file_names_that_file(tmp_path: Path) -> None:
    # A target that is one file is the only file a corpus-level fault can belong to, so dropping it
    # would leave a reader a fault with nowhere to look. A directory names no one file, and the
    # diagnostic's own provenance is what the reader follows there instead.
    named = tmp_path / "malformed.lp"
    named.write_text(_MALFORMED_CONTRACT, encoding="utf-8")
    (from_the_file,) = run_corpus(_asked(named)).errors
    assert from_the_file.scope is Scope.CORPUS
    assert from_the_file.source == named

    (from_the_directory,) = run_corpus(_asked(tmp_path)).errors
    assert from_the_directory.scope is Scope.CASE, "inside a corpus it is one file among others"


def test_a_case_the_deadline_did_not_reach_is_filed_against_that_case(tmp_path: Path) -> None:
    target = _corpus(tmp_path, first=_PASSES, second=_PASSES)
    outcome = run_corpus(_asked(target, deadline=0.0))
    assert outcome.cases == (), "a deadline of zero is past before the first case is dispatched"
    assert len(outcome.errors) == 2, "one record per case, so a case cannot be filed twice"
    assert {record.kind for record in outcome.errors} == {ErrorKind.DEADLINE}
    assert {record.scope for record in outcome.errors} == {Scope.CASE}
    assert {record.source for record in outcome.errors} == {
        target / "first.lp",
        target / "second.lp",
    }, "a count cannot say which case is missing"


def test_a_case_that_passes_is_recorded_in_no_error_register(tmp_path: Path) -> None:
    outcome = run_corpus(_asked(_corpus(tmp_path, good=_PASSES)))
    assert outcome.errors == ()
    (only,) = outcome.cases
    assert only.verdict is Verdict.PASS


def test_the_status_a_process_returns_is_read_off_the_run_it_produced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Composition rather than coincidence: the console entry must hand the run's outcome to the one
    # status function, not reach the same numbers a second way. Comparing two executions could not
    # tell those apart, and on a corpus near a time bound it would compare two different runs.
    seen: list[RunOutcome] = []

    def only_status(outcome: RunOutcome) -> int:
        seen.append(outcome)
        return 99

    monkeypatch.setattr(cli, "exit_status", only_status)
    target = _corpus(tmp_path, good=_PASSES, broken=_WILL_NOT_GROUND)
    assert main([str(target)]) == 99, "the status is whatever reading the outcome returned"
    (outcome,) = seen
    assert len(outcome.cases) == 1, "and the outcome read is the one the run produced"
    assert len(outcome.errors) == 1


def test_a_dry_run_cannot_be_asked_for_as_a_run() -> None:
    # The mode that produces no run is not an invocation with a flag set but a different thing to
    # do, so the runner has nothing to refuse: it is unrepresentable rather than guarded.
    assert {field.name for field in fields(Invocation)} == {
        "target",
        "strict",
        "budget",
        "deadline",
    }


def test_every_discovered_case_reaches_exactly_one_register(tmp_path: Path) -> None:
    target = _corpus(
        tmp_path,
        good=_PASSES,
        will_not_ground=_WILL_NOT_GROUND,
        malformed=_MALFORMED_CONTRACT,
    )
    outcome = run_corpus(_asked(target))
    assert isinstance(outcome, RunOutcome)
    filed = [outcome_of_case.case.contract_source for outcome_of_case in outcome.cases]
    for record in outcome.errors:
        assert record.source is not None, "a fault that stopped one case names the file"
        filed.append(record.source)
    assert sorted(filed) == sorted(target.glob("*.lp"))


def _mixed_hygiene(root: Path) -> Path:
    """A corpus with one of each observation: a case that names no solver, and a contract-free
    file nothing includes."""
    target = _corpus(root, case=_PASSES)
    (target / "lib.lp").write_text("helper(1).\n", encoding="utf-8")
    return target


def test_an_observation_the_run_stayed_silent_about_is_still_recorded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The dial decides what is printed and what fails the run; it does not decide what was seen. A
    # consumer applies its own policy to the observations, which it cannot do if the run has
    # already dropped the ones this invocation chose to stay quiet about.
    target = _mixed_hygiene(tmp_path)
    graded = {record.kind: record for record in run_corpus(_asked(target)).hygiene}
    assert graded[HygieneKind.UNDECLARED_SOLVER].grade is Grade.SILENT
    assert graded[HygieneKind.UNDECLARED_SOLVER].source == target / "case.lp"
    assert graded[HygieneKind.ORPHAN_LIBRARY].grade is Grade.WARNING
    assert graded[HygieneKind.ORPHAN_LIBRARY].source == target / "lib.lp"
    reported = capsys.readouterr().err
    assert "lib.lp" in reported, "the warned one is said once"
    assert "case.lp" not in reported, "and the silent one is recorded without being said"


def test_the_strictness_dial_regrades_the_same_observations(tmp_path: Path) -> None:
    target = _mixed_hygiene(tmp_path)
    strictly = run_corpus(_asked(target, strict=True)).hygiene
    assert {record.grade for record in strictly} == {Grade.ERROR}
    assert {record.kind for record in strictly} == {
        HygieneKind.ORPHAN_LIBRARY,
        HygieneKind.UNDECLARED_SOLVER,
    }, "the same two observations, on a different footing"


def test_the_dry_run_records_the_plan_it_could_not_build(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Surfacing a plan that cannot be built is what the dry run is for, and such a plan is
    # elenctic's own fault rather than the corpus's — so it must reach the status the same way a
    # misroute met while solving does.
    def misroute(expectation: object, theory_in_force: bool = False) -> object:
        raise RoutingError("a stale route")

    monkeypatch.setattr(cli, "runs_for", misroute)
    target = _corpus(tmp_path, bad=_PASSES)
    outcome = explain_corpus(_asked(target))
    capsys.readouterr()
    assert outcome.plans == (), "a plan that could not be built is not a plan"
    (record,) = outcome.errors
    assert record.kind is ErrorKind.HARNESS
    assert record.scope is Scope.CASE
    assert record.source == target / "bad.lp"
    assert exit_status(outcome) == 3, "and one status function ranks it, in either mode"


def test_a_dry_run_on_an_undiscoverable_corpus_records_the_fault_too(tmp_path: Path) -> None:
    # A corpus that cannot be read stops the dry run exactly as it stops a real one, and for the
    # same reason: there is nothing to plan. The fault belongs to no case because there are none.
    outcome = explain_corpus(_asked(tmp_path / "nowhere.lp"))
    assert outcome.plans == ()
    (record,) = outcome.errors
    assert record.kind is ErrorKind.DISCOVERY
    assert record.scope is Scope.CORPUS
    assert exit_status(outcome) == 2, "a corpus to fix, in either mode"


def test_the_dry_run_hands_back_the_plans_it_derived(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The plan is the answer to the question this mode asks, so it is carried rather than only
    # narrated: a mode that establishes something about every case and returns a number leaves
    # what it established with nothing to check it.
    target = _corpus(tmp_path, good=_PASSES)
    outcome = explain_corpus(_asked(target))
    capsys.readouterr()
    (plan,) = outcome.plans
    assert plan.case.contract_source == target / "good.lp"
    assert plan.runs, "a case that planned successfully planned to something"
    assert exit_status(outcome) == 0, "a dry run decides nothing, so nothing can be decided wrong"


def test_every_case_a_dry_run_meets_reaches_exactly_one_register(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same accounting a real run keeps. A case is planned, or the reason it was not is
    # recorded; a corpus of three cannot come back as a corpus of two.
    def misroute_the_marked_one(expectation: object, theory_in_force: bool = False) -> object:
        if "BOOM" in getattr(expectation, "notes", ()):
            raise RoutingError("a stale route")
        return real_runs_for(expectation, theory_in_force)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "runs_for", misroute_the_marked_one)
    target = _corpus(
        tmp_path,
        good=_PASSES,
        marked=f"% @note BOOM\n{_PASSES}",
        unusable=_MALFORMED_CONTRACT,
    )
    outcome = explain_corpus(_asked(target))
    capsys.readouterr()
    filed = [plan.case.contract_source for plan in outcome.plans]
    for record in outcome.errors:
        assert record.source is not None
        filed.append(record.source)
    assert sorted(filed) == sorted(target.glob("*.lp"))
