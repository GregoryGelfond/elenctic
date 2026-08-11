"""What a run records about a fault it met — the register a reader and a machine both read.

Every other test of the command line asserts a process status and some prose on standard error. The
status reads one closed bit off a record (is this ours or theirs), and each line of prose is written
where the fault is met, so between them they leave the rest of a record — the locus it was filed
under, what it stopped, the file it belongs to — with nothing observing it. A record's locus is what
a machine-readable report is mostly made of, so it is asserted here directly, against the value the
run produces rather than against the sentence it happened to print.
"""

import re
from collections.abc import Iterable
from dataclasses import fields
from pathlib import Path

import pytest

from elenctic import cli, corpus, discovery
from elenctic.checks import CheckReport
from elenctic.cli import main
from elenctic.corpus import explain_corpus, run_corpus
from elenctic.discovery import Case, DiscoveryError
from elenctic.harness import run_plan as real_run_plan
from elenctic.outcome import (
    ErrorKind,
    ErrorRecord,
    ExitStatus,
    Grade,
    HygieneKind,
    Invocation,
    RunOutcome,
    Scope,
    exit_status,
)
from elenctic.program import ContainmentError
from elenctic.result import Verdict
from elenctic.run import RoutingError, Run, runs_for as real_runs_for
from elenctic.solvers import TIME_BUDGET
from support import a_clock_the_deadline_has_already_passed_on

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


_QUERY_OVER_AN_UNDECLARED_SIGNATURE = (
    "% @expect sat\n% @query yes { p(1) }\n\np(1).\n#show q/0.\nq.\n"
)


def _states_its_own_file(record: ErrorRecord) -> bool:
    """Whether the reason restates the provenance the record already holds.

    **Every** occurrence of the path is judged, not the shapes that were wrong when this was
    written. It was written the other way first — a leading path and a parenthesised ``(path)``,
    which were elenctic's own two spellings — and a third slipped past it in the same session, a
    path quoted inside an ``OSError``'s own text in the middle of a sentence. A guard enumerating
    the spellings it knows about answers for the ones it was told.

    One thing survives: a **solver's** coordinate quoted inside the reason, which is evidence a
    reader acts on rather than a second claim about which case this is. Editing clingo's diagnostic
    to remove it would cost the reader the only part of the sentence saying *where in the file*.

    The exemption is written as the two tools' spellings and not as "a path with a number after it",
    because that shape belongs to both: clingo writes ``file:LINE:COL`` and ``file:LINE:COL-COL``,
    two numbers, while elenctic's own coordinate is ``file:LINE``, one. Read loosely it exempted the
    thing it exists to catch — a corpus-scoped reason restating ``file:1`` beside a record already
    naming that file — and asking the *record* for its own line instead does not close it either,
    since a record that dropped the line to prose has none to compare against.

    A record with no source restates nothing, because there is nothing to restate. Said as its own
    arm rather than left to fall through: `str(None)` is the word ``None``, so the fall-through
    searched every such reason for that word — flagging a reason that happens to mention
    ``'NoneType' object has no attribute`` and, worse, unable to detect a real restatement in the
    one register where it could not compare against a path at all.
    """
    if record.source is None:
        return False
    name = re.escape(str(record.source))
    return re.search(rf"{name}(?!:\d+:\d)", record.message) is not None


def test_the_restatement_guard_can_answer_yes() -> None:
    # The guard is asserted only negatively everywhere else, and a rule asserted in one direction
    # cannot detect its own weakening: widening the exemption can only turn True into False, so a
    # helper that always answered False would satisfy every other call site in this module. These
    # are the two answers it has to be able to give.
    restated = ErrorRecord(
        kind=ErrorKind.CONTRACT,
        scope=Scope.CASE,
        source=Path("menu.lp"),
        message="menu.lp:3: @expect must be sat|unsat",
        line=3,
    )
    assert _states_its_own_file(restated), "elenctic's own coordinate, said twice"

    quoted = ErrorRecord(
        kind=ErrorKind.PROGRAM,
        scope=Scope.CASE,
        source=Path("menu.lp"),
        message="cannot run the program: menu.lp:3:1-14: error: unsafe variables in: p(X)",
        line=None,
    )
    assert not _states_its_own_file(quoted), "the solver's own coordinate is evidence, not a claim"


@pytest.mark.parametrize(
    "contract",
    [
        _WILL_NOT_GROUND,
        _UNRESOLVABLE_INCLUDE,
        _MALFORMED_CONTRACT,
        _NAMES_A_SOLVER_THAT_DOES_NOT_EXIST,
        _QUERY_OVER_AN_UNDECLARED_SIGNATURE,
    ],
    ids=[
        "will-not-ground",
        "unresolvable-include",
        "malformed-contract",
        "no-such-solver",
        "query",
    ],
)
def test_a_reason_never_restates_the_file_the_record_already_names(
    tmp_path: Path, contract: str
) -> None:
    # One fact, one producer. The record carries the file; the reason says what went wrong. Stated
    # in both places it was printed twice on one line and three times on another, in two different
    # spellings, and which of the three a reader met was decided by which frame happened to catch
    # the fault.
    #
    # Over every fault a corpus can actually produce rather than over the two that were worst,
    # because the defect was never in one message: it was that nothing said where the fact lived, so
    # each new raise site answered the question again for itself.
    (record,) = run_corpus(_asked(_corpus(tmp_path, broken=contract))).errors
    assert not _states_its_own_file(record), record.message


def test_a_reason_never_restates_the_file_of_an_entry_that_cannot_be_read(tmp_path: Path) -> None:
    # A directory named `*.lp` — which `rglob` matches and `read_text` refuses. Its own test because
    # the fixture is not a file, and worth one because this is the spelling that escaped the first
    # version of the guard above: the path arrived quoted inside the operating system's own text,
    # in the middle of the sentence rather than opening it.
    (tmp_path / "not-a-file.lp").mkdir()
    (record,) = run_corpus(_asked(tmp_path)).errors
    assert record.kind is ErrorKind.DISCOVERY
    assert not _states_its_own_file(record), record.message
    assert "Is a directory" in record.message, "the reason, which is what the reader acts on"


def test_a_reason_never_restates_the_file_when_the_case_escapes_its_corpus(
    tmp_path: Path,
) -> None:
    # Containment reaches the same register by a different frame — the one that judges a diagnostic
    # rather than a resolved source list — so it is asked separately. What it names is the
    # *escaping* file, which is a different file and the whole point of the sentence; what it must
    # not name twice is the case.
    (tmp_path / "outside.lp").write_text("secret(1).\n", encoding="utf-8")
    (root := tmp_path / "corpus").mkdir()
    target = _corpus(root, escapes='% @expect sat\n#include "../outside.lp".\nq(1).\n')
    (record,) = run_corpus(_asked(target)).errors
    assert record.kind is ErrorKind.CONTAINMENT
    assert not _states_its_own_file(record), record.message
    assert "outside.lp" in record.message, "the escaping file is what the sentence is about"


def test_a_fault_at_a_contract_line_carries_that_line_as_a_field(tmp_path: Path) -> None:
    # The coordinate the record could not hold until this release, and the reason the renderer used
    # to have to keep away from these two loci. A line the reader can act on, read by a machine
    # without parsing prose out of the message it used to be spelled into.
    (record,) = run_corpus(
        _asked(_corpus(tmp_path, broken=_QUERY_OVER_AN_UNDECLARED_SIGNATURE))
    ).errors
    assert record.kind is ErrorKind.DISCOVERY
    assert record.line == 2, "the @query tag's own line in the case file"


def test_a_fault_with_no_line_to_name_carries_none(tmp_path: Path) -> None:
    # The other footing, and it is not the same claim: a program that will not ground has no
    # *contract* line to name — clingo's coordinates are about the program text, and reading them
    # out of a diagnostic would be elenctic parsing text a corpus author chooses.
    (record,) = run_corpus(_asked(_corpus(tmp_path, broken=_WILL_NOT_GROUND))).errors
    assert record.kind is ErrorKind.PROGRAM
    assert record.line is None


def test_a_declared_solver_this_environment_lacks_is_filed_against_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other half of the pair above: the contract is well-formed and the solver is real, so the
    # fault is that this machine does not have it — which a different machine would not have.
    # `_installed` is past `discovery.__all__`; patching it is how the absence is simulated.
    monkeypatch.setattr(discovery, "_installed", lambda module: module != "clingcon")
    target = _corpus(tmp_path, theory=_DECLARES_THE_THEORY_SOLVER)
    (record,) = run_corpus(_asked(target)).errors
    # Not `discovery`, although this is a DiscoveryError by class: the check runs per case at run
    # time, after the corpus walk is over, so discovery never met it. A locus is where the fault
    # lies and not which of elenctic's own exceptions carried it.
    assert record.kind is ErrorKind.ENVIRONMENT
    assert record.scope is Scope.CASE
    assert record.source == target / "theory.lp"


def test_a_discovery_fault_that_is_not_the_missing_solver_still_costs_only_its_own_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `run_case` states that four families reach a caller and that the corpus catches all four per
    # case; the register caught one *subclass* of one of them. A bare DiscoveryError would leave
    # the per-case register and cost every remaining case its result, against the guarantee that a
    # case which cannot be run costs its own verdict and no other's.
    #
    # Forced rather than waited for: no path raises one today, which is what makes it a latent
    # hole rather than a defect — and what makes the guard the only thing that will notice when a
    # precondition added later does raise one.
    def refuses(case: Case, runs: Iterable[Run], budget: float) -> tuple[CheckReport, ...]:
        if case.path.name == "refused.lp":
            raise DiscoveryError("a precondition this case fails")
        return real_run_plan(case, runs, budget=budget)

    monkeypatch.setattr(corpus, "run_plan", refuses)
    # Two cases, and only one of them refused: with a single case there is nothing else for the
    # fault to cost, so an implementation that files the record and then stops passes unchanged —
    # which is the whole of what this name claims.
    target = _corpus(tmp_path, refused=_PASSES, survives=_PASSES)
    outcome = run_corpus(_asked(target))
    (record,) = outcome.errors
    assert [case.case.contract_source.name for case in outcome.cases] == ["survives.lp"]
    # `discovery`, where the missing solver is `environment`: the locus is asked of the one mapping
    # that knows the two apart, rather than named again at the point that files the record.
    assert record.kind is ErrorKind.DISCOVERY
    assert record.scope is Scope.CASE
    assert record.source == target / "refused.lp"
    assert "a precondition this case fails" in record.message


def test_a_containment_breach_the_runner_meets_is_still_a_containment_breach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `ContainmentError` is a `ProgramError`, so the runner's program arm catches it — and that arm
    # named its locus itself rather than asking `error_kind`. One breach was then announced as
    # CONTAINMENT when the walk met it and PROGRAM when the runner did: the exact shape
    # `ContainmentError`'s own docstring exists to prevent, and which the sibling arm four lines
    # above records as already fixed once.
    #
    # Forced rather than waited for, and it stays forced now that the solver facade does carry a
    # boundary: a case only reaches a solve with its sources already judged, so a real breach here
    # needs a tree that changed between the two moments. What is held is the arm, not the route —
    # that this register reads the locus off the class however the breach arrives.
    def escapes(case: Case, runs: Iterable[Run], budget: float) -> tuple[CheckReport, ...]:
        raise ContainmentError("this case loads a file from outside the corpus")

    monkeypatch.setattr(corpus, "run_plan", escapes)
    (record,) = run_corpus(_asked(_corpus(tmp_path, escaping=_PASSES))).errors
    assert record.kind is ErrorKind.CONTAINMENT, "the locus is read off the class, never named here"


def test_a_case_that_runs_out_of_a_resource_is_filed_apart_from_a_broken_program(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Raised where the solver raises it. Its own locus rather than the program's: nothing about the
    # encoding is wrong, and the machine that ran it is the one able to bound what it consumed.
    def out_of_memory(*_args: object, **_kwargs: object) -> None:
        raise MemoryError("std::bad_alloc")

    monkeypatch.setattr(corpus, "run_plan", out_of_memory)
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
    assert record.source == tmp_path / "nowhere.lp", "and the name typed is what it is about"


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


def test_a_named_target_that_does_not_exist_is_still_the_file_the_fault_names(
    tmp_path: Path,
) -> None:
    # The axis every fixture above holds fixed: the named file *exists*. A target that does not is
    # the one a reader most needs named — it is a typo or a moved file, and the whole fault is which
    # path was typed. Deciding this by asking the filesystem whether the target is a file answers no
    # for exactly the case that needs a yes.
    missing = tmp_path / "nowhere.lp"
    (record,) = run_corpus(_asked(missing)).errors
    assert record.scope is Scope.CORPUS
    assert record.source == missing, (
        "a name that resolves to nothing is still the name it was given"
    )


def test_a_corpus_scoped_reason_never_restates_the_file_either(tmp_path: Path) -> None:
    # The same rule as for a case-scoped record, asked of the other frame — which builds its records
    # somewhere else and so gets the question again. It reached this frame in both directions at
    # once: a named file that exists had its path printed twice, and a named file that does not
    # exist had it printed not at all.
    named = tmp_path / "malformed.lp"
    named.write_text(_MALFORMED_CONTRACT, encoding="utf-8")
    for target in (named, tmp_path / "nowhere.lp"):
        (record,) = run_corpus(_asked(target)).errors
        assert record.scope is Scope.CORPUS
        assert not _states_its_own_file(record), record.message


def test_a_case_the_deadline_did_not_reach_is_filed_against_that_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The clock is controlled rather than the number, because a deadline is a duration and every
    # duration elenctic accepts is one that has not elapsed yet: an invocation refuses a zero on
    # the same footing as the published description of the document does. This says the same thing
    # the zero used to say — the deadline is past before the first case is dispatched — without
    # asking for an invocation nothing is allowed to build.
    monkeypatch.setattr(corpus, "monotonic", a_clock_the_deadline_has_already_passed_on(600.0))
    target = _corpus(tmp_path, first=_PASSES, second=_PASSES)
    outcome = run_corpus(_asked(target, deadline=600.0))
    assert outcome.cases == (), "the clock reads the deadline exactly, which is where it is reached"
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
    assert main(["run", str(target)]) == 99, "the status is whatever reading the outcome returned"
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
    # The other half of the same rule, and it belongs to whoever writes the prose — which is the
    # console entry, since the run above recorded both observations and said neither. Driven through
    # it rather than asserted on the run, because a grade that decides what is *printed* can only be
    # checked where something is printed.
    capsys.readouterr()
    main(["run", str(target)])
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
    def misroute(
        expectation: object, theory_in_force: bool = False, *, has_projection: bool = False
    ) -> object:
        raise RoutingError("a stale route")

    monkeypatch.setattr(corpus, "runs_for", misroute)
    target = _corpus(tmp_path, bad=_PASSES)
    outcome = explain_corpus(_asked(target))
    capsys.readouterr()
    assert outcome.plans == (), "a plan that could not be built is not a plan"
    (record,) = outcome.errors
    assert record.kind is ErrorKind.HARNESS
    assert record.scope is Scope.CASE
    assert record.source == target / "bad.lp"
    assert exit_status(outcome) == ExitStatus.HARNESS_FAULT, (
        "and one status function ranks it, in either mode"
    )


def test_a_dry_run_on_an_undiscoverable_corpus_records_the_fault_too(tmp_path: Path) -> None:
    # A corpus that cannot be read stops the dry run exactly as it stops a real one, and for the
    # same reason: there is nothing to plan. The fault belongs to no case because there are none.
    outcome = explain_corpus(_asked(tmp_path / "nowhere.lp"))
    assert outcome.plans == ()
    (record,) = outcome.errors
    assert record.kind is ErrorKind.DISCOVERY
    assert record.scope is Scope.CORPUS
    assert exit_status(outcome) == ExitStatus.USER_FAULT, "a corpus to fix, in either mode"


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
    assert exit_status(outcome) == ExitStatus.OK, (
        "a dry run decides nothing, so nothing can be decided wrong"
    )


def test_every_case_a_dry_run_meets_reaches_exactly_one_register(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same accounting a real run keeps. A case is planned, or the reason it was not is
    # recorded; a corpus of three cannot come back as a corpus of two.
    def misroute_the_marked_one(
        expectation: object, theory_in_force: bool = False, *, has_projection: bool = False
    ) -> object:
        if "BOOM" in getattr(expectation, "notes", ()):
            raise RoutingError("a stale route")
        return real_runs_for(
            expectation,  # type: ignore[arg-type]
            theory_in_force,
            has_projection=has_projection,
        )

    monkeypatch.setattr(corpus, "runs_for", misroute_the_marked_one)
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
