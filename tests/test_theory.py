import sys
from pathlib import Path
from typing import get_type_hints

import clingo
import pytest
from clingo.ast import AST, parse_string

from elenctic.about import Solvers
from elenctic.check import check
from elenctic.cli import main
from elenctic.contract import Solver
from elenctic.engine import ground
from elenctic.program import Fault, Program
from elenctic.report import Exit
from elenctic.theory import Clingcon, Plain, loaded_solvers

CLINGCON = "% @elenctic solver clingcon\n"
ABSENT = "solver `clingcon` is not installed"
ABSENT_HELP = "install `elenctic[theory]`, or use the pixi `theory` environment"


@pytest.fixture
def without_clingcon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "clingcon", None)


def test_no_theory_adds_a_statement_as_written_and_assigns_nothing() -> None:
    statements: list[AST] = []
    parse_string("p.", statements.append)
    added: list[AST] = []
    Plain().rewrite(statements[1], added.append)
    assert added == statements[1:]


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
    assert diagnostic.children[-1].message == ABSENT_HELP
    assert diagnostic.span is None
    found = check(Program(CLINGCON + "p.\n% @expect sat\n", "t.lp"))
    assert isinstance(found, Fault)
    assert found.diagnostics[0].message == ABSENT


@pytest.mark.usefixtures("without_clingcon")
def test_a_clingcon_contract_without_clingcon_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "case.lp").write_text(CLINGCON + "p.\n% @expect sat\n")
    assert main([str(tmp_path)]) == Exit.FAULT
    assert ABSENT in capsys.readouterr().err


def test_the_solvers_are_the_versions_of_the_modules_loaded() -> None:
    clingcon = pytest.importorskip("clingcon")
    assert loaded_solvers() == Solvers(
        clingo.__version__, ".".join(str(part) for part in clingcon.ClingconTheory().version())
    )


@pytest.mark.usefixtures("without_clingcon")
def test_solvers_without_clingcon_name_clingo_alone() -> None:
    assert loaded_solvers() == Solvers(clingo.__version__, None)


def test_what_clingcon_is_asked_for_is_what_the_real_theory_offers() -> None:
    clingcon = pytest.importorskip("clingcon")
    asked = get_type_hints(Clingcon.__init__)["theory"]
    assert isinstance(clingcon.ClingconTheory(), asked)
    assert not isinstance(object(), asked)
