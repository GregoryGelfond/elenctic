"""The budget bounds time; it does not bound memory.

A solve accumulates every model it is shown, and the time budget says nothing about how fast they
arrive — a program controls that. So a corpus can exhaust memory inside a budget that never
expires, which makes the advertised hang protection something other than what a reader takes it
for.

clingo offers the throttle: a model callback returning ``False`` stops the search. A capped search
reports itself as not exhausted, and a reading over a whole collection already treats an unfinished
search as undecided — so the cap needs no new verdict vocabulary. "We stopped at the cap" and "we
ran out of time" are the same fact about knowledge.
"""

from clingo import Control

from elenctic.result import Consistent, Inconclusive
from elenctic.run import Mode
from elenctic.solvers import MODEL_CAP, _Collector, _drive

# 2^16 answer sets: far past any sane cap, cheap to enumerate, and every model has a distinct shown
# projection so --project cannot collapse the stream.
_MANY = "{ bit(1..16) }.\n#show bit/1.\n"
# Two answer sets, so an ordinary run finishes well inside the cap.
_FEW = "1 { a; b } 1.\n#show a/0.\n#show b/0.\n"


def _quiet(_code: object, _message: str) -> None:
    """Keep clingo's own diagnostics out of the test output."""


def _drive_over(program: str, cap: int | None = None) -> tuple[object, _Collector]:
    control = Control(list(Mode.ENUM_ALL.args), logger=_quiet)
    control.add("base", [], program)
    control.ground([("base", [])])
    collector = _Collector() if cap is None else _Collector(cap)
    return _drive(control, Mode.ENUM_ALL, collector, collector.on_model, 30.0), collector


def test_a_cap_is_in_force_by_default() -> None:
    # The bound has to be the default, not an opt-in: the run that needs it is the one nobody
    # anticipated.
    assert MODEL_CAP > 0
    _determination, collector = _drive_over(_MANY)
    assert collector.models_seen <= MODEL_CAP


def test_an_enumeration_past_the_cap_is_undecided_not_a_partial_census() -> None:
    # The whole point: a census cut short must not be reported as the census. It reaches the same
    # arm a hit budget does, through the same route — a search that did not finish.
    determination, collector = _drive_over(_MANY, cap=8)
    assert collector.models_seen == 8, "the search stops at the cap, it does not merely truncate"
    assert isinstance(determination, Inconclusive)


def test_an_ordinary_run_never_meets_the_cap() -> None:
    # The other side: the cap must be invisible to every run that does not need it, or it would
    # turn working corpora undecided.
    determination, collector = _drive_over(_FEW, cap=8)
    assert collector.models_seen < 8
    assert isinstance(determination, Consistent)
