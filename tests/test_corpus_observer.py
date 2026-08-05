"""The corpus layer writes to no stream, and tells a caller who asks the same records it returns.

Running a corpus used to print as it went, which meant an embedder could not have the results
without also having the prose: the only way to quieten it was to take over their own process's
streams, which costs them their own output and still leaves the records reachable only by reading
the prose back. It is silent now, and a caller who wants to watch a long run happen hands in an
observer.

Two things have to hold together for that to be a fair trade. The run must actually be silent, or
the old problem is still there for whichever path was missed. And every error and verdict a caller
is *told* must be what it is *handed back*, or a report rendered as the run goes and a report
rendered from the return value can describe the same run differently — which is the failure the
streaming was worth keeping in the first place. Corpus hygiene is outside that: it is settled before
the first case is reached, so it is returned and not announced, and the test below says so rather
than leaving it to be inferred from the absence of a method.
"""

import logging
from pathlib import Path
from typing import NoReturn

import pytest

from elenctic import corpus
from elenctic.corpus import explain_corpus, run_corpus
from elenctic.discovery import Case
from elenctic.outcome import CaseOutcome, CasePlan, ErrorKind, ErrorRecord, Invocation
from elenctic.run import RoutingError
from elenctic.solvers import TIME_BUDGET
from support import a_clock_the_deadline_has_already_passed_on

_PASSES = "% @expect sat\n% @count 2\n\n1 { tea; coffee } 1.\n#show tea/0.\n#show coffee/0.\n"
_FAILS = "% @expect sat\n% @cautious { tea }\n\nbiscuit.\n#show biscuit/0.\n"
_MALFORMED = "% @expect banana\n\nb.\n"
_WILL_NOT_GROUND = "% @expect sat\n% @count 1\n\nq(1).\np(X) :- q(Y).\n"


class _Heard:
    """Everything a run announced, kept by kind and in the order it was announced.

    ``order`` is half of what is under test and not a nicety: a case is announced before its plan is
    derived, and a caller narrating a corpus depends on that to have something to narrate against.

    It implements both observers at once, which the protocols permit because they are structural —
    nothing here inherits from them, and mypy still checks the shape at each call.
    """

    def __init__(self) -> None:
        self.corpus_faults: list[ErrorRecord] = []
        self.unusable_files: list[ErrorRecord] = []
        self.unjudged: list[ErrorRecord] = []
        self.judged: list[CaseOutcome] = []
        self.started: list[Case] = []
        self.plans: list[CasePlan] = []
        self.order: list[str] = []

    def corpus_unreadable(self, record: ErrorRecord) -> None:
        self.corpus_faults.append(record)
        self.order.append("corpus_unreadable")

    def case_unusable(self, record: ErrorRecord) -> None:
        self.unusable_files.append(record)
        self.order.append("case_unusable")

    def case_started(self, case: Case) -> None:
        self.started.append(case)
        self.order.append("case_started")

    def case_unjudged(self, record: ErrorRecord) -> None:
        self.unjudged.append(record)
        self.order.append("case_unjudged")

    def case_judged(self, outcome: CaseOutcome) -> None:
        self.judged.append(outcome)
        self.order.append("case_judged")

    def case_planned(self, case_plan: CasePlan) -> None:
        self.plans.append(case_plan)
        self.order.append("case_planned")


def _asked(target: Path) -> Invocation:
    return Invocation(target=target, strict=False, budget=TIME_BUDGET, deadline=None)


def _corpus(root: Path, **cases: str) -> Path:
    for name, text in cases.items():
        (root / f"{name}.lp").write_text(text, encoding="utf-8")
    return root


def test_a_run_writes_to_no_stream(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # The corpus deliberately spans every register a run can fill — a case that passes, one that
    # fails, one discovery cannot use, and a library nothing includes — because the paths that used
    # to print are exactly the paths a fault or an observation reaches. A corpus of one passing case
    # would be silent under a library that still printed everything else.
    target = _corpus(tmp_path, good=_PASSES, bad=_FAILS, broken=_MALFORMED)
    (target / "lib.lp").write_text("helper(1).\n", encoding="utf-8")

    outcome = run_corpus(_asked(target))

    # All three registers, or this says nothing about the paths that print: a corpus that reached
    # only one of them would leave the other two announcements untested and still look green.
    assert outcome.cases, "the corpus must decide at least one case"
    assert outcome.errors, "and hold at least one file it could not"
    assert outcome.hygiene, "and observe something about its own health"
    assert capsys.readouterr() == ("", "")


def test_a_dry_run_writes_to_no_stream(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = _corpus(tmp_path, good=_PASSES, broken=_MALFORMED)
    (target / "lib.lp").write_text("helper(1).\n", encoding="utf-8")

    outcome = explain_corpus(_asked(target))

    assert outcome.plans
    assert outcome.errors
    assert outcome.hygiene
    assert capsys.readouterr() == ("", "")


def test_a_run_stays_silent_even_while_telling_an_observer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Supplying an observer must not turn the printing back on. Worth its own test because the
    # silence and the announcing were added together, and a run that quietly printed *as well* as
    # announcing would pass every test that only looks at what was heard.
    target = _corpus(tmp_path, good=_PASSES, bad=_FAILS, broken=_MALFORMED)
    heard = _Heard()

    run_corpus(_asked(target), observer=heard)

    assert heard.order, "the observer was told nothing, so silence here proves nothing"
    assert capsys.readouterr() == ("", "")


def test_what_a_run_announces_is_what_it_hands_back(tmp_path: Path) -> None:
    # The reason an observer receives records rather than sentences: a caller rendering as the run
    # goes and a caller rendering from the return value are looking at the same values, so the two
    # renderings cannot come to describe the same run differently. Asserted as identity, not as
    # equality — the announced record *is* the filed one, so there is no second copy to drift.
    target = _corpus(tmp_path, good=_PASSES, bad=_FAILS, broken=_MALFORMED, wrong=_WILL_NOT_GROUND)
    heard = _Heard()

    outcome = run_corpus(_asked(target), observer=heard)

    assert [
        id(record) for record in heard.corpus_faults + heard.unusable_files + heard.unjudged
    ] == [id(record) for record in outcome.errors], (
        "every error announced is one filed, in the register's own order"
    )
    assert [id(case) for case in heard.judged] == [id(case) for case in outcome.cases]
    # The register that is deliberately outside the agreement, asserted rather than left to be
    # inferred from there being no method for it. Hygiene is settled before the first case is
    # reached, so it has no as-it-happens character; a caller reads it off the returned outcome,
    # which is what the console entry does. Said here because the claim above would otherwise read
    # as covering all three registers, and this corpus produces hygiene records for every case.
    assert outcome.hygiene, "or this says nothing about the register it is about"
    assert not hasattr(heard, "observed_records"), "hygiene has no announcement, by design"


def test_a_file_discovery_could_not_use_is_told_apart_from_a_case_that_would_not_run(
    tmp_path: Path,
) -> None:
    # The distinction the method name carries and the record cannot: both of these are a
    # case-scoped error record, and one of them is even the same locus as the other could be. A
    # caller that heard them through one channel would have to tell them apart by reading the
    # message, which is the prose-parsing this design exists to avoid.
    target = _corpus(tmp_path, broken=_MALFORMED, wrong=_WILL_NOT_GROUND)
    heard = _Heard()

    run_corpus(_asked(target), observer=heard)

    (unusable,) = heard.unusable_files
    (undecided,) = heard.unjudged
    assert unusable.source == target / "broken.lp", "discovery could not turn it into a case"
    assert undecided.source == target / "wrong.lp", "it became a case, and then would not run"
    assert unusable.scope is undecided.scope, "the records cannot tell them apart; the channel does"


def test_a_corpus_that_could_not_be_read_at_all_is_announced_as_the_corpus_s(
    tmp_path: Path,
) -> None:
    heard = _Heard()

    run_corpus(_asked(tmp_path / "nowhere.lp"), observer=heard)

    (fault,) = heard.corpus_faults
    assert fault.kind is ErrorKind.DISCOVERY
    assert heard.order == ["corpus_unreadable"], (
        "nothing was discovered, so nothing else can be announced — and it is announced as the "
        "corpus's, not as one file's, because it ends the invocation rather than costing one result"
    )


def test_a_dry_run_announces_a_case_before_the_plan_that_might_not_be_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Why `began` exists at all. Deriving the plan is the step that can fail, so a case announced
    # only once it has a plan is a case a caller cannot name when it turns out to have none — and
    # naming it is the whole point of the mode.
    def misroute(*_args: object, **_kwargs: object) -> NoReturn:
        raise RoutingError("no run serves this contract")

    monkeypatch.setattr(corpus, "runs_for", misroute)
    target = _corpus(tmp_path, good=_PASSES)
    heard = _Heard()

    outcome = explain_corpus(_asked(target), observer=heard)

    assert heard.order == ["case_started", "case_unjudged"], "announced, then found to have no plan"
    assert heard.started[0].contract_source == target / "good.lp"
    assert heard.unjudged[0].kind is ErrorKind.HARNESS, "a plan that cannot be built is ours"
    assert outcome.plans == (), "and it reached no plan register"


def test_a_dry_run_announces_every_case_it_planned(tmp_path: Path) -> None:
    target = _corpus(tmp_path, good=_PASSES)
    heard = _Heard()

    outcome = explain_corpus(_asked(target), observer=heard)

    assert heard.order == ["case_started", "case_planned"]
    assert [id(plan) for plan in heard.plans] == [id(plan) for plan in outcome.plans]
    assert heard.plans[0].runs, "a case that planned successfully planned to something"


def test_a_deadline_costs_every_case_it_did_not_reach_a_record_and_an_announcement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One passed deadline is a single event, and the human report says it once — but it costs each
    # unreached case its result separately, so each is filed and each is announced. Collapsing them
    # is a rendering decision and belongs to whoever renders; a run that announced the event once
    # would have decided for every caller that the individual cases do not matter.
    monkeypatch.setattr(corpus, "monotonic", a_clock_the_deadline_has_already_passed_on(600.0))
    target = _corpus(tmp_path, first=_PASSES, second=_PASSES)
    heard = _Heard()

    outcome = run_corpus(
        Invocation(target=target, strict=False, budget=TIME_BUDGET, deadline=600.0),
        observer=heard,
    )

    assert heard.order == ["case_unjudged", "case_unjudged"], (
        "one announcement per case, as filed — and no case_started, because the deadline is "
        "checked before a case is taken up, so these were never started"
    )
    assert {record.source for record in heard.unjudged} == {
        target / "first.lp",
        target / "second.lp",
    }
    assert [id(record) for record in heard.unjudged] == [id(record) for record in outcome.errors]


class _Rude:
    """An observer whose rendering is broken — the shape a caller's own bug takes.

    Not contrived: an editor's observer publishes over a channel that fails for ordinary reasons,
    and a CI reporter writes to a file or a socket. What matters is that the run's records survive
    what the watching does.
    """

    def __init__(self) -> None:
        self.heard = 0

    def _raise(self, _value: object) -> NoReturn:
        self.heard += 1
        raise RuntimeError("the caller's renderer is broken")

    corpus_unreadable = _raise
    case_unusable = _raise
    case_started = _raise
    case_unjudged = _raise
    case_judged = _raise
    case_planned = _raise


def test_an_observer_that_raises_costs_the_run_nothing(tmp_path: Path) -> None:
    # Announcing is a courtesy; establishing is the work. Every announcement site sits outside the
    # per-case handlers, so without isolation an observer that raised on one case discarded every
    # record the run had already established — and the console entry then reported the caller's own
    # bug as elenctic's. That is the wrong trade wherever elenctic is used: under CI the records are
    # the deliverable, and in an editor the channel an observer writes to fails for ordinary
    # reasons. It is also the guarantee the rest of this module already gives about a bad file.
    target = _corpus(tmp_path, good=_PASSES, bad=_FAILS, broken=_MALFORMED, wrong=_WILL_NOT_GROUND)
    rude = _Rude()

    outcome = run_corpus(_asked(target), observer=rude)

    assert rude.heard > 1, "it kept being told, rather than being given up on after the first fault"
    assert len(outcome.cases) == 2, "every case that reached a verdict still has one"
    assert len(outcome.errors) == 2, "and every case that reached none still has its reason"
    assert outcome.hygiene, "and the observations are still there to read"


class _Unreachable:
    """An observer whose announcements cannot be *reached*, rather than one whose announcements
    raise when called.

    Two ways a caller gets here and both are shapes the surface invites. An implementation checked
    structurally rather than by inheritance has to supply every member — a protocol's default bodies
    are inherited, never conjured — so one that misses a member fails at the lookup. And an
    announcement exposed as a computed attribute fails where it is read. Either way the fault is in
    the observer, which is the whole of what decides who pays for it.
    """

    def __getattr__(self, name: str) -> object:
        raise ConnectionError(f"the caller cannot supply {name!r}")


def test_an_observer_whose_announcements_cannot_be_reached_costs_the_run_nothing(
    tmp_path: Path,
) -> None:
    # The other half of the guarantee above, and the half that was not held: reaching for the
    # announcement is itself something that can fail, and while the *call* was inside the isolation
    # the *lookup* was at the call site, outside it. So the guarantee held for an observer that
    # raised and not for one that could not be asked — and the second is the likelier mistake, since
    # it is what a structural implementation that misses a member does.
    target = _corpus(tmp_path, good=_PASSES, bad=_FAILS, broken=_MALFORMED)

    outcome = run_corpus(_asked(target), observer=_Unreachable())  # type: ignore[arg-type]

    assert len(outcome.cases) == 2, "every case that reached a verdict still has one"
    assert len(outcome.errors) == 1, "and every case that reached none still has its reason"


def test_a_dry_run_survives_an_observer_that_raises_too(tmp_path: Path) -> None:
    # The same guarantee on the other mode, because the announcement sites are different code.
    target = _corpus(tmp_path, good=_PASSES, broken=_MALFORMED)

    outcome = explain_corpus(_asked(target), observer=_Rude())

    assert len(outcome.plans) == 1
    assert len(outcome.errors) == 1


def test_an_observer_fault_is_reported_where_a_developer_can_see_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Swallowed is not the same as hidden. A caller whose observer silently does nothing has no way
    # to find out, so the fault goes to the one channel that says something only a developer can act
    # on — silent until they ask for it, which is why the library can carry it without writing to a
    # stream. The traceback is kept, because the caller's own frame is the whole of what they need.
    target = _corpus(tmp_path, good=_PASSES)

    with caplog.at_level(logging.ERROR, logger="elenctic.corpus"):
        run_corpus(_asked(target), observer=_Rude())

    assert caplog.records, "an observer fault nothing reports is one nobody can fix"
    assert "observer" in caplog.text
    assert "RuntimeError" in caplog.text, "the caller's own traceback, not a summary of it"
