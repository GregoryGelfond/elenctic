"""Shared test scaffolding.

Importable from any test module because ``pythonpath`` puts this directory on the path; ``conftest``
itself is not importable under pytest's importlib mode, so shared helpers live here instead.
"""

from elenctic.result import Conclusion, Determination, Inconclusive, SolveOutcome

__all__ = ["decided"]


def decided(determination: Determination) -> SolveOutcome:
    """A determination as a *finished* search reported it.

    The frame a check test is written in unless the test is about a search that stopped early —
    those state the conclusion they mean, in ``test_partial_search_verdicts.py``. An undecided
    determination has no completed search to describe, so it pairs with no conclusion.
    """
    return SolveOutcome(
        determination,
        None if isinstance(determination, Inconclusive) else Conclusion.EXHAUSTED,
    )
