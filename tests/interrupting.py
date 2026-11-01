"""Pull an interrupt from inside a search, as soon as it reads its first model."""

from collections.abc import Callable

import pytest
from clingo import Model as ClingoModel

from elenctic import grounded
from elenctic.search import Seen, seen
from elenctic.theory import Theory


def at_first_model(monkeypatch: pytest.MonkeyPatch, interrupt: Callable[[], None]) -> None:
    """Make every search call `interrupt` when it reads a model, so it is cut after the first."""

    def read(model: ClingoModel, theory: Theory) -> Seen:
        interrupt()
        return seen(model, theory)

    monkeypatch.setattr(grounded, "seen", read)
