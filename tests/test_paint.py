import ast
from pathlib import Path

import pytest

import elenctic
from elenctic.paint import Color, Role, paint

SGR = [
    (Role.ERROR, "1;31"),
    (Role.WARNING, "1;33"),
    (Role.NOTE, "1;32"),
    (Role.HELP, "1;36"),
    (Role.MARGIN, "1;34"),
    (Role.EMPHASIS, "1"),
]


def test_every_role_has_a_style_and_no_other_exists() -> None:
    assert [role for role, _ in SGR] == list(Role)


@pytest.mark.parametrize(("role", "sgr"), SGR)
def test_a_role_with_color_on_is_wrapped_in_its_sequence_and_a_reset(role: Role, sgr: str) -> None:
    assert paint(Color.ON, role, "text") == f"\x1b[{sgr}mtext\x1b[0m"


@pytest.mark.parametrize("role", list(Role))
def test_with_color_off_the_text_is_unchanged(role: Role) -> None:
    assert paint(Color.OFF, role, "text") == "text"


def test_no_module_but_paint_holds_an_escape_character() -> None:
    package = Path(elenctic.__file__).parent
    writers = {
        path.name
        for path in package.glob("*.py")
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "\x1b" in node.value
    }
    assert writers == {"paint.py"}
