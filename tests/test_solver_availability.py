"""A declared solver has to be installed, and discovery is where that is found out.

The theory backend is an optional dependency. A case declaring a solver the environment does not
have cannot be run at all, so there is no verdict to report about it — saying so during discovery,
with the command that fixes it, is both earlier and more useful than an import traceback raised
from inside the solver facade on the first case that needs it.
"""

import sys
from pathlib import Path

import pytest

from elenctic import discovery
from elenctic.discovery import DiscoveryError, SolverUnavailableError, check_solver_available
from elenctic.registry import BACKING_MODULES, SOLVERS, THEORY_EXTRA_ADVICE
from elenctic.run import Mode
from elenctic.solvers import run_clingcon


def test_every_registered_solver_names_a_backing_module() -> None:
    # The registry is the single source for solver names; a name with no module would leave the
    # availability check silently unable to say anything about it.
    assert frozenset(BACKING_MODULES) == SOLVERS


def test_an_installed_solver_passes() -> None:
    check_solver_available("clingo")  # clingo is a hard dependency, always present


def test_a_missing_solver_is_a_loud_discovery_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulated rather than uninstalled, so this runs in an environment that does have clingcon.
    monkeypatch.setattr(discovery, "_installed", lambda module: module != "clingcon")
    with pytest.raises(DiscoveryError, match=r"clingcon.*not installed") as caught:
        check_solver_available("clingcon")
    # The remedy belongs in the message: an environment problem should not need a search. Asked of
    # the one home rather than quoted — a copy agrees with the advice however wrong it is, which is
    # how this went on naming a `pip install` that resolves nothing for as long as it did.
    assert THEORY_EXTRA_ADVICE in str(caught.value)
    # What it does NOT say is which case. A caller asks this question about a case it is holding, so
    # the refusal would be repeating back what was handed in — and the record that files the fault
    # carries the file as a field, where a consumer reads it without parsing prose.
    assert caught.value.line is None


def test_a_missing_solver_answers_to_both_idioms(monkeypatch: pytest.MonkeyPatch) -> None:
    # A caller following elenctic's error families and a caller following Python's convention for
    # a missing optional dependency should both catch this without knowing about the other.
    monkeypatch.setattr(discovery, "_installed", lambda module: module != "clingcon")
    # Written by hand, because the lint cannot ask for it here and this is the one place that
    # matters: the class raised is elenctic's own, caught through the built-in arm it also inherits,
    # so it is outside both the families ruff asks about by default and the ones the setting names.
    # The spelling is the subject of the test and stays; the assertion is what closes the gap.
    with pytest.raises(ImportError, match="clingcon is not installed"):
        check_solver_available("clingcon")
    with pytest.raises(DiscoveryError, match="clingcon is not installed"):
        check_solver_available("clingcon")
    assert issubclass(SolverUnavailableError, ImportError)
    assert issubclass(SolverUnavailableError, DiscoveryError)


def test_an_installation_too_broken_to_answer_counts_as_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `find_spec` is documented to raise rather than return None for some broken installations, and
    # a case declaring that solver must then be refused with the remedy — not crash the run with an
    # exception from the import system that names neither the case nor what to do about it.
    def broken(_name: str) -> None:
        raise ValueError("a broken installation")

    monkeypatch.setattr(discovery, "find_spec", broken)
    assert discovery._installed("clingcon") is False


def test_the_theory_facade_called_directly_reports_a_missing_solver_itself(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Discovery checks a declared solver before any run reaches its facade, so a case never gets
    # here — but a caller driving the facade themselves bypasses that check entirely, and must meet
    # the same condition with the same type and the same remedy rather than an ImportError from
    # somewhere inside. The comment at that arm says it exists for exactly this caller; nothing had
    # ever been that caller.
    case = tmp_path / "case.lp"
    case.write_text("% @expect sat\na.\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "clingcon", None)

    with pytest.raises(SolverUnavailableError, match="clingcon is not installed"):
        run_clingcon(Mode.ENUM_ALL, files=(case,))
