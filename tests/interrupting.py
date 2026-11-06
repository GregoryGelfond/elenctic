"""Pull an interrupt from inside a search, as soon as it reads its first answer set."""

from collections.abc import Callable

import pytest
from clingo import Model as ClingoModel

from elenctic import grounded
from elenctic.search import KEEP_ALL, Keep, Seen, seen
from elenctic.theory import Theory


def at_first_answer_set(monkeypatch: pytest.MonkeyPatch, interrupt: Callable[[], None]) -> None:
    """Make every search call `interrupt` on reading an answer set, so it is cut after the first."""

    def read(model: ClingoModel, theory: Theory, keep: Keep = KEEP_ALL) -> Seen:
        interrupt()
        return seen(model, theory, keep)

    monkeypatch.setattr(grounded, "seen", read)
