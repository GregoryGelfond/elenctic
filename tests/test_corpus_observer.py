"""The corpus layer writes to no stream, and tells a caller who asks the same records it returns.

Running a corpus used to print as it went, which meant an embedder could not have the results
without also having the prose — the only way to suppress it was to divert a file descriptor, and a
library that requires that of its caller is not one you can embed. It is silent now, and a caller
who wants to watch a long run happen hands in an observer.

Two things have to hold together for that to be a fair trade. The run must actually be silent, or
the old problem is still there for whichever path was missed. And what a caller is *told* must be
what it is *handed back*, or a report rendered as the run goes and a report rendered from the return
value can describe the same run differently — which is the failure the streaming was worth keeping
in the first place.
"""

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
        self.unusable_records: list[ErrorRecord] = []
        self.undecided_records: list[ErrorRecord] = []
        self.decided_cases: list[CaseOutcome] = []
        self.began_cases: list[Case] = []
        self.planned_cases: list[CasePlan] = []
        self.order: list[str] = []

    def unusable(self, record: ErrorRecord) -> None:
        self.unusable_records.append(record)
        self.order.append("unusable")

    def undecided(self, record: ErrorRecord) -> None:
        self.undecided_records.append(record)
        self.order.append("undecided")

    def decided(self, outcome: CaseOutcome) -> None:
        self.decided_cases.append(outcome)
        self.order.append("decided")

    def began(self, case: Case) -> None:
        self.began_cases.append(case)
        self.order.append("began")

    def planned(self, case_plan: CasePlan) -> None:
        self.planned_cases.append(case_plan)
        self.order.append("planned")


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

    assert outcome.cases and outcome.errors and outcome.hygiene, (
        "the corpus must reach all three registers, or this says nothing about the paths that print"
    )
    assert capsys.readouterr() == ("", "")


def test_a_dry_run_writes_to_no_stream(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = _corpus(tmp_path, good=_PASSES, broken=_MALFORMED)
    (target / "lib.lp").write_text("helper(1).\n", encoding="utf-8")

    outcome = explain_corpus(_asked(target))

    assert outcome.plans and outcome.errors and outcome.hygiene
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

    assert [id(record) for record in heard.unusable_records + heard.undecided_records] == [
        id(record) for record in outcome.errors
    ], "every error announced is one filed, in the register's own order"
    assert [id(case) for case in heard.decided_cases] == [id(case) for case in outcome.cases]


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

    (unusable,) = heard.unusable_records
    (undecided,) = heard.undecided_records
    assert unusable.source == target / "broken.lp", "discovery could not turn it into a case"
    assert undecided.source == target / "wrong.lp", "it became a case, and then would not run"
    assert unusable.scope is undecided.scope, "the records cannot tell them apart; the channel does"


def test_a_corpus_that_could_not_be_read_at_all_is_announced_as_the_corpus_s(
    tmp_path: Path,
) -> None:
    heard = _Heard()

    run_corpus(_asked(tmp_path / "nowhere.lp"), observer=heard)

    (fault,) = heard.unusable_records
    assert fault.kind is ErrorKind.DISCOVERY
    assert heard.order == ["unusable"], "nothing was discovered, so nothing else can be announced"


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

    assert heard.order == ["began", "undecided"], "announced, then found to have no plan"
    assert heard.began_cases[0].contract_source == target / "good.lp"
    assert heard.undecided_records[0].kind is ErrorKind.HARNESS, (
        "a plan that cannot be built is ours"
    )
    assert outcome.plans == (), "and it reached no plan register"


def test_a_dry_run_announces_every_case_it_planned(tmp_path: Path) -> None:
    target = _corpus(tmp_path, good=_PASSES)
    heard = _Heard()

    outcome = explain_corpus(_asked(target), observer=heard)

    assert heard.order == ["began", "planned"]
    assert [id(plan) for plan in heard.planned_cases] == [id(plan) for plan in outcome.plans]
    assert heard.planned_cases[0].runs, "a case that planned successfully planned to something"


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

    assert heard.order == ["undecided", "undecided"], "one announcement per case, as filed"
    assert {record.source for record in heard.undecided_records} == {
        target / "first.lp",
        target / "second.lp",
    }
    assert [id(record) for record in heard.undecided_records] == [
        id(record) for record in outcome.errors
    ]
