"""What the collector does with a model type clingo did not have when this was written.

``ModelType`` is clingo's enumeration, not elenctic's, and the dependency has no upper bound. So
the arm that catches an unknown one is unlike every other exhaustiveness arm in this package: those
guard a taxonomy elenctic owns and are unreachable while it stays complete, and this one is
reachable by installing a newer clingo.

Two ways a later clingo could reach it, and only the second gets here. A new value from the C
library alone raises inside ``clingo.solving.Model.type``, which builds the member with
``ModelType(...)``. A new value *and* a matching Python member arrives intact, matches none of the
three arms, and would otherwise be counted as neither a consequence nor an answer set — leaving a
census quietly short, which is a wrong verdict rather than a crash.

The refusal is a ``HarnessError`` because that is a family the runner isolates per case. An
``AssertionError`` is not: it would escape the per-case handler and end the whole run, discarding
every verdict already reached — the shape this project already moved three of its own invariants
away from.
"""

import pytest
from clingo import Symbol

from elenctic.result import HarnessError
from elenctic.solvers import _Collector


class _ModelFromALaterClingo:
    """A model whose ``type`` is none of the three members clingo has today.

    Only what the collector reads before and at the dispatch: the shown projection is taken first,
    so a stub that omitted it would fail there and never reach the arm this is about.
    """

    def __init__(self, model_type: object) -> None:
        self.type = model_type

    def symbols(self, *, shown: bool = False) -> list[Symbol]:
        return []

    def contains(self, symbol: Symbol) -> bool:
        return False


class _ModelClingoWillNotName:
    """A model whose ``type`` clingo's own enumeration refuses to build.

    The other way in, and it never reaches the dispatch: ``Model.type`` is
    ``ModelType(_c_call(...))``, so a value the C library reports and the Python enumeration lacks
    raises ``ValueError`` at the attribute read. Left alone that is not one of the families the
    runner isolates, so it would end the run — which is the whole thing the sibling refusal exists
    to prevent, arriving one line earlier.
    """

    @property
    def type(self) -> object:
        raise ValueError("99 is not a valid ModelType")

    def symbols(self, *, shown: bool = False) -> list[Symbol]:
        return []

    def contains(self, symbol: Symbol) -> bool:
        return False


def test_a_model_type_this_clingo_did_not_have_is_refused_rather_than_miscounted() -> None:
    # The value is named, because whoever meets this needs to know which member is new, and the
    # remedy is stated, because it is not their corpus that is wrong.
    unknown = _ModelFromALaterClingo("SomethingLater")
    with pytest.raises(HarnessError, match="'SomethingLater'"):
        _Collector().on_model(unknown)  # type: ignore[arg-type]


def test_the_refusal_survives_a_member_that_is_not_a_string() -> None:
    # The other shape the same rule is stated over. A future member arrives as whatever clingo
    # makes it, and the value is interpolated into the message — so a member with no useful text of
    # its own must still leave a reader with a diagnostic rather than an error raised while
    # building one.
    with pytest.raises(HarnessError, match="model type this elenctic cannot read"):
        _Collector().on_model(_ModelFromALaterClingo(object()))  # type: ignore[arg-type]


def test_a_model_type_clingo_itself_cannot_name_is_refused_the_same_way() -> None:
    # The second of the two ways this module's docstring names, and it arrives as a `ValueError`
    # from clingo's enumeration rather than as a value that falls through the dispatch. Both are
    # the same version skew and both have to leave as the same family: a `ValueError` here reaches
    # no per-case handler — `_program_faults` translates `RuntimeError`, `UnicodeDecodeError` and
    # `OSError`, and the runner isolates the four error families — so it would end the run.
    with pytest.raises(HarnessError, match="model type this elenctic cannot read"):
        _Collector().on_model(_ModelClingoWillNotName())  # type: ignore[arg-type]
