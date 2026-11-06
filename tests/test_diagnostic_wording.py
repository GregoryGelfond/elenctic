"""Invariants on failure messages, and clingo's byte columns versus Unicode scalars."""

import ast
import re
from pathlib import Path

import pytest
from clingo.ast import parse_string

from elenctic import tree
from elenctic.body import span_of
from elenctic.check import check
from elenctic.human import render
from elenctic.presentation import PLAIN
from elenctic.program import Fault, Program
from elenctic.report import Entry, Run
from elenctic.spans import char_column

SRC = Path(__file__).resolve().parents[1] / "src" / "elenctic"
HELPISH = re.compile(r"\b(declare|install|name it)\b", re.IGNORECASE)
BANNED = re.compile(r"did you mean|illegal", re.IGNORECASE)


def _failure_messages() -> list[tuple[str, str]]:
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
            if name != "failure" or len(node.args) < 2:
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


@pytest.mark.parametrize(("where", "message"), _failure_messages())
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
    stderr = render(Run((Entry("t.lp", result, text),)), PLAIN).stderr
    assert "^" * width in stderr
