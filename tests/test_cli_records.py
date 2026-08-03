"""What a run records about a fault it met — the register a reader and a machine both read.

Every other test of the command line asserts a process status and some prose on standard error. The
status reads one closed bit off a record (is this ours or theirs), and each line of prose is written
where the fault is met, so between them they leave the rest of a record — the locus it was filed
under, what it stopped, the file it belongs to — with nothing observing it. A record's locus is what
a machine-readable report is mostly made of, so it is asserted here directly, against the value the
run produces rather than against the sentence it happened to print.
"""

from pathlib import Path

import pytest

from elenctic import cli, discovery
from elenctic.cli import exit_status, main, run
from elenctic.outcome import ErrorKind, RunOutcome, Scope

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
    outcome = run([str(target)])
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
    (record,) = run([str(target)]).errors
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
    (record,) = run([str(target)]).errors
    assert record.kind is ErrorKind.RESOURCE
    assert record.scope is Scope.CASE
    assert record.source == target / "greedy.lp"


def test_a_corpus_that_cannot_be_discovered_produces_no_cases_and_one_error(
    tmp_path: Path,
) -> None:
    outcome = run([str(tmp_path / "nowhere.lp")])
    (record,) = outcome.errors
    assert outcome.cases == ()
    assert record.kind is ErrorKind.DISCOVERY
    assert record.scope is Scope.CORPUS, "nothing was discovered, so this belongs to no case"


def test_a_corpus_fault_on_a_named_file_names_that_file(tmp_path: Path) -> None:
    # A target that is one file is the only file a corpus-level fault can belong to, so dropping it
    # would leave a reader a fault with nowhere to look. A directory names no one file, and the
    # diagnostic's own provenance is what the reader follows there instead.
    named = tmp_path / "malformed.lp"
    named.write_text(_MALFORMED_CONTRACT, encoding="utf-8")
    (from_the_file,) = run([str(named)]).errors
    assert from_the_file.scope is Scope.CORPUS
    assert from_the_file.source == named

    (from_the_directory,) = run([str(tmp_path)]).errors
    assert from_the_directory.scope is Scope.CASE, "inside a corpus it is one file among others"


def test_a_case_the_deadline_did_not_reach_is_filed_against_that_case(tmp_path: Path) -> None:
    target = _corpus(tmp_path, first=_PASSES, second=_PASSES)
    outcome = run([str(target), "--deadline", "0"])
    assert outcome.cases == (), "a deadline of zero is past before the first case is dispatched"
    assert {record.kind for record in outcome.errors} == {ErrorKind.DEADLINE}
    assert {record.scope for record in outcome.errors} == {Scope.CASE}
    assert {record.source for record in outcome.errors} == {
        target / "first.lp",
        target / "second.lp",
    }, "a count cannot say which case is missing"


def test_a_case_that_passes_is_recorded_in_no_error_register(tmp_path: Path) -> None:
    outcome = run([str(_corpus(tmp_path, good=_PASSES))])
    assert outcome.errors == ()
    assert len(outcome.cases) == 1


@pytest.mark.parametrize(
    "flags",
    [[], ["--strict"], ["--deadline", "0"]],
    ids=["plain", "strict", "deadline"],
)
def test_the_status_a_process_returns_is_the_status_of_the_run_it_produced(
    tmp_path: Path, flags: list[str]
) -> None:
    # The document a consumer stores and the number the shell sees come from one value, so they
    # cannot come to disagree about the same run.
    target = str(_corpus(tmp_path, good=_PASSES, broken=_WILL_NOT_GROUND))
    assert main([target, *flags]) == exit_status(run([target, *flags]))


def test_the_dry_run_is_not_a_run(tmp_path: Path) -> None:
    # It decides nothing, so there is no outcome to hand back: an outcome built from it would
    # report a corpus of cases as a run of none.
    with pytest.raises(ValueError, match="dry run"):
        run([str(_corpus(tmp_path, good=_PASSES)), "--explain"])


def test_every_discovered_case_reaches_exactly_one_register(tmp_path: Path) -> None:
    target = _corpus(
        tmp_path,
        good=_PASSES,
        will_not_ground=_WILL_NOT_GROUND,
        malformed=_MALFORMED_CONTRACT,
    )
    outcome = run([str(target)])
    assert isinstance(outcome, RunOutcome)
    filed = [case.case.path for case in outcome.cases]
    for record in outcome.errors:
        assert record.source is not None, "a fault that stopped one case names the file"
        filed.append(record.source)
    assert sorted(filed) == sorted(target.glob("*.lp"))
