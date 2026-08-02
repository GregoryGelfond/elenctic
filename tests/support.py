"""Shared test scaffolding.

Importable from any test module because ``pythonpath`` puts this directory on the path; ``conftest``
itself is not importable under pytest's importlib mode, so shared helpers live here instead.
"""

from elenctic.result import Conclusion, Determination, SolveOutcome

__all__ = ["decided"]


def decided(determination: Determination) -> SolveOutcome:
    """A determination as a *finished* search reported it.

    The frame a check test is written in unless the test is about a search that stopped early —
    those state the conclusion they mean, in ``test_partial_search_verdicts.py``. It applies to the
    undecided arm too: a search can close the space and still leave the mode nothing to build from,
    and that pairing is the one whose diagnostic has no remedy to offer.
    """
    return SolveOutcome(determination, Conclusion.EXHAUSTED)
