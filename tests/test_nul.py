"""A NUL is refused where clingo would read the text up to it, and worded where it reads it."""

from pathlib import Path

import pytest

from elenctic.arithmetic import evaluable
from elenctic.cli import main
from elenctic.engine import ground
from elenctic.program import Fault, Program
from elenctic.spans import Position, Span, first_nul


def test_a_nul_in_a_program_file_reads_as_clingo_reads_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "nul.lp"
    path.write_text("p(1).\nq\x00.\n% @expect sat\n")
    main(["--color", "never", str(path)])
    captured = capsys.readouterr()
    assert f"error: unexpected `\\x00`\n --> {path}:2:2\n" in captured.out + captured.err


@pytest.mark.parametrize(
    ("tag", "column"),
    [
        ("% @query yes { p(1)\x00, q }", 20),
        ('% @query yes { p("a\x00b") }', 20),
        ("% @query yes { p(X) } = { 1\x00 }", 28),
    ],
)
def test_a_nul_in_a_tag_is_refused_where_it_stands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], tag: str, column: int
) -> None:
    path = tmp_path / "t.lp"
    path.write_text(f"p(1).\n% @expect sat\n{tag}\n")
    main(["--color", "never", str(path)])
    captured = capsys.readouterr()
    assert f"error: unexpected `\\x00`\n --> {path}:3:{column}\n" in captured.out + captured.err


def test_a_nul_in_a_program_given_as_text_is_refused_not_read_up_to() -> None:
    grounded = ground(Program("p.\n% a\x00b\nq.\n"))
    assert isinstance(grounded, Fault)
    assert grounded.diagnostics[0].message == "unexpected `\x00`"


def test_first_nul_places_the_nul_where_the_text_was_written() -> None:
    found = first_nul("a\nbc\x00", Span("T", Position(3, 5), Position(3, 5)))
    assert found is not None
    assert found.span == Span("T", Position(4, 3), Position(4, 4))
    assert first_nul("abc", Span("T", Position(1, 1), Position(1, 1))) is None


@pytest.mark.parametrize(
    ("text", "at"),
    [("\x00ab", Position(1, 1)), ("\n\x00", Position(2, 1)), ("\nab\x00", Position(2, 3))],
)
def test_first_nul_finds_a_nul_at_the_start_or_after_a_first_empty_line(
    text: str, at: Position
) -> None:
    found = first_nul(text, Span("T", Position(1, 1), Position(1, 1)))
    assert found is not None
    assert found.span == Span("T", at, Position(at.line, at.column + 1))


def test_a_term_with_a_nul_is_not_evaluable() -> None:
    assert not evaluable('p("a\x00b")')
