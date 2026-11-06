"""Pin source masks, nested include boundaries and located refusals."""

from pathlib import Path

import pytest

from elenctic.check import check
from elenctic.engine import ground, included_sources
from elenctic.human import render_run
from elenctic.presentation import PLAIN
from elenctic.program import Fault, Locus, Program
from elenctic.report import Entry, Run
from elenctic.spans import (
    Position,
    Span,
    failure,
    first_unlexable,
    in_characters,
    in_code,
)


@pytest.mark.parametrize(
    "segments",
    [
        [],
        [("a.", True)],
        [("%", False)],
        [("% comment", False)],
        [("% é", False), ("\na.", True)],
        [("a. ", True), ("% tail", False)],
        [("%**%", False), ("a.", True)],
        [("a.", True), ("%* ignored ** text % end *%", False), ("b.", True)],
        [("%* é", False)],
        [("%* trailing *", False)],
        [("a.", True), ("%* *%", False), ("%* *%", False), ("b.", True)],
        [('""', False), ("a", True)],
        [('"é"', False), ("b", True)],
        [('"unterminated', False)],
        [('"backslash' + "\\", False)],
        [('"escaped \\" quote"', False), ("p.", True)],
        [('"escaped \\\\"', False), ("p.", True)],
        [('"%* not a comment *%"', False), ("a.", True)],
        [('% " not a string', False), ("\np.", True)],
    ],
)
def test_the_source_mask_marks_exactly_the_code(segments: list[tuple[str, bool]]) -> None:
    text = "".join(fragment for fragment, _ in segments)
    expected = [code for fragment, code in segments for _ in fragment]
    assert in_code(text) == expected


@pytest.mark.parametrize(
    ("text", "line", "column", "message"),
    [
        ("é", 1, 1, "é"),
        ("a.\n  é", 2, 3, "é"),
        ("% é\n\n é", 3, 2, "é"),
        ('p("é").\n é', 2, 2, "é"),
        ("\x80", 1, 1, "U+0080"),
        ("\ufeff", 1, 1, "byte order mark"),
    ],
)
def test_a_refusal_locates_both_ends_of_the_first_character(
    text: str, line: int, column: int, message: str
) -> None:
    refused = first_unlexable(text, "case.lp")
    assert refused is not None
    assert refused.span == Span("case.lp", Position(line, column), Position(line, column + 1))
    assert message in refused.message


def test_the_ascii_boundary_is_not_a_non_ascii_character() -> None:
    assert first_unlexable("\x7f", "case.lp") is None


def test_a_missing_line_does_not_borrow_the_last_lines_characters() -> None:
    where = Span("case.lp", Position(0, 4), Position(0, 6))
    assert in_characters(where, "a\nlong last line") == Span(
        "case.lp", Position(0, 1), Position(0, 1)
    )


def test_a_missing_snippet_line_does_not_print_the_last_line() -> None:
    where = Span("missing-case.lp", Position(0, 4), Position(0, 6))
    fault = Fault(Locus.PROGRAM, (failure(where, "invalid source location"),))
    rendered = render_run(Run((Entry("missing-case.lp", fault, "a\nlast line"),)), PLAIN)
    assert "last line" not in rendered.stderr
    assert "missing-case.lp:0:4" in rendered.stderr


def nested_program(directory: Path, leaf: str) -> Program:
    (directory / "main.lp").write_text('#include "lib.lp".\n% @expect sat\n')
    (directory / "lib.lp").write_text('#include "leaf.lp".\n')
    (directory / "leaf.lp").write_text(leaf)
    return Program.read(directory / "main.lp")


def test_include_discovery_follows_more_than_one_edge(tmp_path: Path) -> None:
    program = nested_program(tmp_path, "a.")
    assert included_sources(program) == frozenset(
        tmp_path / name for name in ("main.lp", "lib.lp", "leaf.lp")
    )


def test_the_lexer_guard_reaches_nested_includes(tmp_path: Path) -> None:
    program = nested_program(tmp_path, "a.\né.\n")
    refused = ground(program)
    assert isinstance(refused, Fault)
    assert refused.diagnostics[0].span == Span(
        str(tmp_path / "leaf.lp"), Position(2, 1), Position(2, 2)
    )


def test_a_nested_include_fault_uses_that_files_own_source(tmp_path: Path) -> None:
    program = nested_program(tmp_path, "% é\nq2 :- q. p(X) :- q.\n")
    refused = check(program, root=tmp_path)
    assert isinstance(refused, Fault)
    spans = [diagnostic.span for diagnostic in refused.diagnostics]
    assert any(span is not None and span.start == Position(2, 10) for span in spans)
    rendered = render_run(Run((Entry(program.source, refused, program.text),)), PLAIN)
    assert "q2 :- q. p(X) :- q." in rendered.stderr


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        (Position(5, 7), Span("case.lp", Position(5, 8), Position(7, 4))),
        (Position(1, 1), Span("case.lp", Position(1, 2), Position(3, 4))),
    ],
)
def test_relative_spans_shift_columns_only_on_their_first_line(
    origin: Position, expected: Span
) -> None:
    assert Span("case.lp", Position(1, 2), Position(3, 4)).shifted(origin) == expected


def test_byte_columns_use_both_the_first_and_the_last_lines() -> None:
    where = Span("case.lp", Position(1, 3), Position(2, 3))
    assert in_characters(where, "éx\néy") == Span("case.lp", Position(1, 2), Position(2, 2))
