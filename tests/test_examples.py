import pytest
from capture_examples import EXAMPLES, TARGET, asked, capture, command, render

NEEDS_CLINGCON = {"clingcon.lp", "late.lp"}
EXIT_CODES = {
    "absent.lp": 1,
    "chain.lp": 1,
    "clingcon.lp": 0,
    "consequences.lp": 1,
    "hidden-contrary.lp": 0,
    "laptop.lp": 1,
    "late.lp": 1,
    "no-objective.lp": 2,
    "optimum-wrong.lp": 1,
    "optimum.lp": 0,
    "team.lp": 1,
    "theory-atoms.lp": 2,
    "why-not.lp": 1,
}


@pytest.mark.parametrize("name", sorted(EXIT_CODES))
def test_an_example_exits_as_the_documentation_says(name: str) -> None:
    if name in NEEDS_CLINGCON:
        pytest.importorskip("clingcon")
    code, _ = capture(command(EXAMPLES / name))
    assert code == EXIT_CODES[name]


def test_an_example_asked_answers_with_exit_zero() -> None:
    assert [capture(words)[0] for words in asked(EXAMPLES / "absent.lp")] == [0, 0]


def test_every_example_is_listed() -> None:
    assert {path.name for path in EXAMPLES.glob("*.lp")} == set(EXIT_CODES)


def test_the_examples_page_is_what_the_examples_print() -> None:
    pytest.importorskip("clingcon")
    assert TARGET.read_text() == render()
