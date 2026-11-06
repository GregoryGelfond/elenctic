"""Invariants on failure messages, and clingo's byte columns versus Unicode scalars."""

import ast
import re
from pathlib import Path

import pytest
from clingo.ast import parse_string

from elenctic import tree
from elenctic.body import span_of
from elenctic.check import check
from elenctic.human import render_run
from elenctic.presentation import PLAIN
from elenctic.program import Fault, Locus, Program
from elenctic.reader import parse_contract
from elenctic.report import Entry, Run
from elenctic.spans import Diagnostic, Position, Severity, Span, char_column
from elenctic.wellformed import wellformed

SRC = Path(__file__).resolve().parents[1] / "src" / "elenctic"
HELPISH = re.compile(r"\b(declare|install|name it)\b", re.IGNORECASE)
BANNED = re.compile(r"did you mean|illegal", re.IGNORECASE)


def _messages(maker: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        module = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            name = (
                callee.attr
                if isinstance(callee, ast.Attribute)
                else callee.id
                if isinstance(callee, ast.Name)
                else None
            )
            if name != maker or len(node.args) < 2:
                continue
            message = node.args[1]
            if isinstance(message, ast.Constant) and isinstance(message.value, str):
                found.append((path.name, message.value))
            elif isinstance(message, ast.JoinedStr):
                literal = "".join(
                    part.value
                    if isinstance(part, ast.Constant) and isinstance(part.value, str)
                    else "x"
                    for part in message.values
                )
                found.append((path.name, literal))
    return found


@pytest.mark.parametrize(("where", "message"), _messages("note"))
def test_no_note_asks_the_reader_a_question(where: str, message: str) -> None:
    assert not BANNED.search(message), (where, message)
    assert "?" not in message, (where, message)


@pytest.mark.parametrize(("where", "message"), _messages("failure"))
def test_every_failure_message_follows_the_rustc_shape(where: str, message: str) -> None:
    assert message, where
    assert not message.endswith("."), (where, message)
    assert ";" not in message, (where, message)
    assert not BANNED.search(message), (where, message)
    head = message.lstrip("`@")
    assert head[:1].islower() or head[:1].isdigit() or head[:1] == "_", (where, message)
    if message.startswith(
        (
            "expected",
            "unknown",
            "missing",
            "unclosed",
            "anonymous",
            "binding",
            "query",
            "assumption",
            "solver",
            "claim",
            "optimal",
            "clingo",
            "theory",
            "cannot",
            "`",
        )
    ):
        assert not HELPISH.search(message), (where, message)


def test_clingo_byte_columns_become_character_columns_on_non_ascii() -> None:
    text = 'p("café").'
    found: list[object] = []
    parse_string(text, found.append)
    function = found[1].head.atom.symbol  # type: ignore[attr-defined]
    argument = function.arguments[0]
    location = tree.location(argument)
    assert location.end.column - location.begin.column == len('"café"'.encode())
    converted = span_of(location, text)
    assert converted.end.column - converted.start.column == len('"café"')
    assert char_column('p("café")', location.end.column) == converted.end.column


def test_carets_match_the_primary_span_width() -> None:
    text = "p.\n% @expect sat\n% @count x\n"
    result = check(Program(text, "t.lp"))
    assert isinstance(result, Fault)
    (diagnostic,) = result.diagnostics
    assert diagnostic.span is not None
    width = diagnostic.span.end.column - diagnostic.span.start.column
    stderr = render_run(Run((Entry("t.lp", result, text),)), PLAIN).stderr
    assert "^" * width in stderr


def test_carets_sit_under_the_token_after_multibyte_text_on_the_same_line() -> None:
    """Reader spans count Unicode scalars: carets must not drift after `é`."""
    line = '% @cautious { p("café") } assuming x'
    text = "p.\n% @expect sat\n" + line + "\n"
    result = check(Program(text, "t.lp"))
    assert isinstance(result, Fault)
    diagnostic = next(d for d in result.diagnostics if d.span is not None)
    assert diagnostic.span is not None
    assert line[diagnostic.span.start.column - 1 : diagnostic.span.end.column - 1] == "assuming x"
    stderr = render_run(Run((Entry("t.lp", result, text),)), PLAIN).stderr
    width = diagnostic.span.end.column - diagnostic.span.start.column
    pad = " " * (diagnostic.span.start.column - 1)
    assert f"| {pad}{'^' * width}" in stderr


def test_clingo_reports_byte_columns_and_we_convert_them_before_carets() -> None:
    """Clingo's Location columns are UTF-8 bytes; span_of maps them to scalars for carets."""
    source = 'p("café").'
    found: list[object] = []
    parse_string(source, found.append)
    function = found[1].head.atom.symbol  # type: ignore[attr-defined]
    argument = function.arguments[0]
    location = tree.location(argument)
    assert location.end.column - location.begin.column == len('"café"'.encode())
    assert char_column(source, location.begin.column) == source.index('"') + 1
    text = 'q.\n% @expect sat\n% @query yes { p("café", 1..2) }\n'
    result = check(Program(text, "t.lp"))
    assert isinstance(result, Fault)
    diagnostic = next(d for d in result.diagnostics if d.span is not None)
    assert diagnostic.span is not None
    src_line = text.split("\n")[2]
    marked = src_line[diagnostic.span.start.column - 1 : diagnostic.span.end.column - 1]
    assert "1..2" in marked
    stderr = render_run(Run((Entry("t.lp", result, text),)), PLAIN).stderr
    width = max(1, diagnostic.span.end.column - diagnostic.span.start.column)
    assert "^" * width in stderr


def test_wellformed_reports_missing_expect_when_none_was_seen() -> None:
    found = wellformed([])
    assert [d.message for d in found] == ["missing `@expect`"]


def test_a_count_with_no_integer_points_at_the_end_of_the_tag() -> None:
    contract = parse_contract("% @expect sat\n% @count\n", "c.lp")
    (found,) = [d for d in contract.diagnostics if d.span is not None]
    assert found.message.startswith("expected a non-negative integer")
    assert found.span is not None
    assert found.span.start == found.span.end == Position(2, 9)


def test_a_zero_width_primary_span_still_draws_one_caret() -> None:
    text = "p.\n% @expect sat\n% @count\n"
    result = check(Program(text, "t.lp"))
    assert isinstance(result, Fault)
    diagnostic = next(d for d in result.diagnostics if d.span is not None)
    assert diagnostic.span is not None
    assert diagnostic.span.start == diagnostic.span.end
    stderr = render_run(Run((Entry("t.lp", result, text),)), PLAIN).stderr
    assert "  |         ^ expected a non-negative integer" in stderr


def test_a_snippet_includes_the_last_line_of_the_source() -> None:
    text = "p.\n% @expect sat\n% @count x\n"
    result = check(Program(text, "t.lp"))
    assert isinstance(result, Fault)
    stderr = render_run(Run((Entry("t.lp", result, text),)), PLAIN).stderr
    assert "3 | % @count x" in stderr
    assert "^" in stderr


def test_a_snippet_is_omitted_when_the_span_line_is_outside_the_source() -> None:
    where = Span("t.lp", Position(99, 1), Position(99, 2))
    result = Fault(Locus.REQUEST, (Diagnostic(where, Severity.ERROR, "gone"),))
    stderr = render_run(Run((Entry("t.lp", result, "one line\n"),)), PLAIN).stderr
    assert "gone" in stderr
    assert "99 |" not in stderr
