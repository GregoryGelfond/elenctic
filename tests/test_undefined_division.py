"""An undefined division in an argument or a tag is refused, as clingo's grounder leaves it."""

import io
from concurrent.futures import ProcessPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from multiprocessing import get_context
from pathlib import Path

import pytest

from elenctic.arithmetic import evaluable
from elenctic.cli import main
from elenctic.inquiry import AskExit
from elenctic.literals import Literal
from elenctic.report import Exit

PROGRAM = "p(1). p(2).\n"


@pytest.mark.parametrize(
    "text",
    [
        "p(1\\0)",
        "p(1/0)",
        "p(1\\(2-2))",
        "p((1\\0)\\0)",
        "p(-2147483648/-1)",
        "p(-2147483648\\-1)",
        "p(1\\0",
        "(1\\0,",
        "p(1\\0) q",
        'p(1) #include "x.lp"',
        "p(\udcff)",
    ],
)
def test_a_text_clingo_would_trap_on_or_not_read_is_not_evaluable(text: str) -> None:
    assert not evaluable(text)


def test_an_include_that_would_close_the_term_and_be_read_is_not_evaluable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The text is read inside a term, which `1) .` can close; the include would then be read."""
    (tmp_path / "lib.lp").write_text("q.\n")
    monkeypatch.chdir(tmp_path)
    assert not evaluable('1) . #include "lib.lp" . :- t(1')


@pytest.mark.parametrize("text", ["p(4/2)", "p(2\\1)", "p(-2147483648/1)", 'p("1\\\\0")', "p(1)"])
def test_a_term_with_defined_arithmetic_is_evaluable(text: str) -> None:
    assert evaluable(text)


def _main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def _run(*argv: str) -> tuple[int, str, str]:
    """Run the command in a process of its own, which a trap would end, not this one."""
    with ProcessPoolExecutor(1, mp_context=get_context("spawn")) as pool:
        return pool.submit(_main, ["--color", "never", *argv]).result()


@pytest.mark.parametrize(
    ("options", "where"),
    [
        (["ask", "{path}", "p(1\\0)"], "QUERY"),
        (["ask", "{path}", "p(-2147483648/-1)"], "QUERY"),
        (["why", "{path}", "p(X)", "--binding", "X = 1\\0"], "--binding"),
        (["why", "{path}", "p(1)", "--assuming", "p(1\\0)"], "--assuming"),
    ],
)
def test_an_undefined_division_in_an_argument_is_refused_not_trapped_on(
    tmp_path: Path, options: list[str], where: str
) -> None:
    path = tmp_path / "p.lp"
    path.write_text(PROGRAM)
    code, out, err = _run(*(each.format(path=path) for each in options))
    assert (code, out) == (AskExit.FAULT, "")
    assert f" --> {where}:1:1\n" in err


@pytest.mark.parametrize("tag", ["% @query yes { p(1\\0) }", "% @query yes { p(X) } = { 1\\0 }"])
def test_an_undefined_division_in_a_tag_is_refused_not_trapped_on(tmp_path: Path, tag: str) -> None:
    path = tmp_path / "t.lp"
    path.write_text(f"{PROGRAM}% @expect sat\n{tag}\n")
    code, _, err = _run(str(path))
    assert code == Exit.FAULT
    assert f" --> {path}:3:" in err


def _parsed(text: str) -> str:
    try:
        return str(Literal.parse(text))
    except ValueError as error:
        return f"refused: {error}"


def test_literal_parse_refuses_an_undefined_division_not_trapped_on() -> None:
    with ProcessPoolExecutor(1, mp_context=get_context("spawn")) as pool:
        assert pool.submit(_parsed, "p(1\\0)").result() == "refused: not a literal: p(1\\0)"
