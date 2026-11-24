"""Pin that a file refused before clingo reads it is named as clingo names it, not resolved."""

from pathlib import Path

import pytest

from conftest import Link
from elenctic.check import check
from elenctic.cli import main
from elenctic.program import Fault, Program
from elenctic.report import Exit

CASE = "% @expect sat\n"
BAD = {"not UTF-8": b"p(\xe9).\n", "not ASCII": "p(é).\n".encode()}
"""Files clingo must not read: one it cannot decode, one whose lexer error aborts the logger."""


def refused_under(result: object, name: str, why: str) -> None:
    assert isinstance(result, Fault)
    refusal = result.diagnostics[0]
    if why == "not UTF-8":
        assert refusal.message == f"cannot read `{name}`"
    else:
        assert refusal.message == "expected an ASCII character, found `é`"
        assert refusal.span is not None
        assert refusal.span.source == name


@pytest.fixture
def tree(tmp_path: Path, link: Link, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Work from `tmp_path`, which holds `real/`, a link `alias` to it, and an empty `sub/`."""
    (tmp_path / "real").mkdir()
    (tmp_path / "sub").mkdir()
    link(tmp_path / "alias", tmp_path / "real")
    monkeypatch.chdir(tmp_path)
    return tmp_path


WHYS = pytest.mark.parametrize("why", list(BAD))


@WHYS
@pytest.mark.parametrize("target", ["./real/bad.lp", "sub//../real/bad.lp", "alias/bad.lp"])
def test_an_include_is_refused_under_the_name_clingo_joins(
    tree: Path, why: str, target: str
) -> None:
    (tree / "real" / "bad.lp").write_bytes(BAD[why])
    Path("case.lp").write_text(f'#include "{target}".\n{CASE}')
    refused_under(check(Program.read("case.lp")), target, why)


@WHYS
def test_an_include_beside_a_file_named_through_a_link_is_refused_under_that_name(
    tree: Path, why: str
) -> None:
    (tree / "real" / "bad.lp").write_bytes(BAD[why])
    (tree / "real" / "case.lp").write_text(f'#include "bad.lp".\n{CASE}')
    refused_under(check(Program.read("alias/case.lp"), root=tree), "alias/bad.lp", why)


@WHYS
def test_a_library_is_refused_under_the_name_it_is_given_by(tree: Path, why: str) -> None:
    (tree / "real" / "bad.lp").write_bytes(BAD[why])
    Path("case.lp").write_text(CASE)
    refused_under(check(Program.read("case.lp", ["alias/bad.lp"])), "alias/bad.lp", why)


@WHYS
def test_an_include_of_a_library_is_refused_under_the_name_clingo_joins(
    tree: Path, why: str
) -> None:
    (tree / "real" / "bad.lp").write_bytes(BAD[why])
    (tree / "real" / "base.lp").write_text('#include "bad.lp".\n')
    Path("case.lp").write_text(CASE)
    refused_under(check(Program.read("case.lp", ["alias/base.lp"])), "alias/bad.lp", why)


@WHYS
def test_a_library_of_a_text_found_on_clingopath_is_refused_under_the_name_joined(
    tree: Path, why: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tree / "real" / "bad.lp").write_bytes(BAD[why])
    monkeypatch.setenv("CLINGOPATH", f"{tree}/alias/")
    program = Program(CASE, libraries=(Path("bad.lp"),))
    refused_under(check(program, root=tree), f"{tree}/alias//bad.lp", why)


@WHYS
@pytest.mark.parametrize("given", ["main", "--with", "included", "walked"])
def test_the_command_line_names_a_refused_file_as_clingo_does(
    tree: Path, capsys: pytest.CaptureFixture[str], why: str, given: str
) -> None:
    (tree / "real" / "bad.lp").write_bytes(BAD[why] + CASE.encode())
    (tree / "real" / "case.lp").write_text(f'#include "bad.lp".\n{CASE}')
    (tree / "real" / "lib.lp").write_bytes(BAD[why])
    argv, name = {
        "main": (["alias/bad.lp"], "alias/bad.lp"),
        "--with": (["alias/case.lp", "--with", "alias/lib.lp"], "alias/lib.lp"),
        "included": (["alias/case.lp"], "alias/bad.lp"),
        "walked": (["alias"], "alias/bad.lp"),
    }[given]
    code = main(argv)
    err = capsys.readouterr().err
    assert code == Exit.FAULT
    shown = f"cannot read `{name}`" if why == "not UTF-8" else f"--> {name}:1:3"
    assert shown in err
    assert str(tree / "real") not in err
