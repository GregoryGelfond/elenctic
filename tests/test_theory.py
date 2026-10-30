from pathlib import Path
from typing import NoReturn

import pytest

from elenctic import theory
from elenctic.check import check
from elenctic.cli import main
from elenctic.contract import Solver
from elenctic.engine import Fault, Program, ground
from elenctic.theory import Clingcon, Plain

CLINGCON = "% @elenctic solver clingcon\n"
ABSENT = (
    "the contract declares `% @elenctic solver clingcon`, which is not installed; "
    "install `elenctic[theory]`, or use the pixi `theory` environment"
)


@pytest.fixture
def without_clingcon(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> NoReturn:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(theory, "import_module", missing)


def test_no_theory_adds_a_statement_as_written_and_assigns_nothing() -> None:
    added: list[str] = []
    Plain().rewrite("statement", added.append)  # type: ignore[arg-type]
    assert added == ["statement"]


def test_clingcon_is_made_when_installed() -> None:
    pytest.importorskip("clingcon")
    assert isinstance(Clingcon.load(), Clingcon)


@pytest.mark.usefixtures("without_clingcon")
def test_clingcon_that_is_not_installed_is_no_theory() -> None:
    assert Clingcon.load() is None


@pytest.mark.usefixtures("without_clingcon")
def test_a_program_that_asks_for_clingcon_without_it_is_a_fault_of_the_request() -> None:
    fault = ground(Program("p.", "t.lp"), Solver.CLINGCON)
    assert isinstance(fault, Fault)
    (diagnostic,) = fault.diagnostics
    assert diagnostic.message == ABSENT
    assert (diagnostic.span.source, diagnostic.span.start.line) == ("t.lp", 1)
    found = check(Program(CLINGCON + "p.\n% @expect sat\n", "t.lp"))
    assert isinstance(found, Fault)
    assert found.diagnostics[0].message == ABSENT


@pytest.mark.usefixtures("without_clingcon")
def test_a_clingcon_contract_without_clingcon_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "case.lp").write_text(CLINGCON + "p.\n% @expect sat\n")
    assert main([str(tmp_path)]) == 2
    assert ABSENT in capsys.readouterr().out
