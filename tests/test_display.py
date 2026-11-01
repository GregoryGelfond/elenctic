import pytest

from elenctic.display import legible


def test_printable_text_spaces_and_newlines_are_kept() -> None:
    assert legible('p("é") — ⊆ ⋂\n  q') == 'p("é") — ⊆ ⋂\n  q'


@pytest.mark.parametrize(
    ("hidden", "shown"),
    [
        ("\x1b", r"\x1b"),
        ("\r", r"\r"),
        ("\t", r"\t"),
        ("\x85", r"\x85"),
        ("\u202e", r"\u202e"),
        ("\U000e0001", r"\U000e0001"),
    ],
)
def test_a_character_a_terminal_would_act_on_is_shown_as_an_escape(hidden: str, shown: str) -> None:
    assert legible(f"a{hidden}b") == f"a{shown}b"
