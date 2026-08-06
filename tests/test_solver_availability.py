"""A declared solver has to be installed, and discovery is where that is found out.

The theory backend is an optional dependency. A case declaring a solver the environment does not
have cannot be run at all, so there is no verdict to report about it — saying so during discovery,
with the command that fixes it, is both earlier and more useful than an import traceback raised
from inside the solver facade on the first case that needs it.
"""

from pathlib import Path

import pytest

from elenctic import discovery
from elenctic.discovery import DiscoveryError, SolverUnavailableError, check_solver_available
from elenctic.registry import BACKING_MODULES, SOLVERS, THEORY_EXTRA_ADVICE

WHERE = Path("case.lp")


def test_every_registered_solver_names_a_backing_module() -> None:
    # The registry is the single source for solver names; a name with no module would leave the
    # availability check silently unable to say anything about it.
    assert frozenset(BACKING_MODULES) == SOLVERS


def test_an_installed_solver_passes() -> None:
    check_solver_available("clingo", WHERE)  # clingo is a hard dependency, always present


def test_a_missing_solver_is_a_loud_discovery_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulated rather than uninstalled, so this runs in an environment that does have clingcon.
    monkeypatch.setattr(discovery, "_installed", lambda module: module != "clingcon")
    with pytest.raises(DiscoveryError, match=r"clingcon.*not installed") as caught:
        check_solver_available("clingcon", WHERE)
    # The remedy belongs in the message: an environment problem should not need a search. Asked of
    # the one home rather than quoted — a copy agrees with the advice however wrong it is, which is
    # how this went on naming a `pip install` that resolves nothing for as long as it did.
    assert THEORY_EXTRA_ADVICE in str(caught.value)
    assert str(WHERE) in str(caught.value)


def test_a_missing_solver_answers_to_both_idioms(monkeypatch: pytest.MonkeyPatch) -> None:
    # A caller following elenctic's error families and a caller following Python's convention for
    # a missing optional dependency should both catch this without knowing about the other.
    monkeypatch.setattr(discovery, "_installed", lambda module: module != "clingcon")
    with pytest.raises(ImportError):
        check_solver_available("clingcon", WHERE)
    with pytest.raises(DiscoveryError):
        check_solver_available("clingcon", WHERE)
    assert issubclass(SolverUnavailableError, ImportError)
    assert issubclass(SolverUnavailableError, DiscoveryError)
