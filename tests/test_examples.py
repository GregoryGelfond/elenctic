import pytest
from capture_examples import EXAMPLES, TARGET, capture, render

EXIT_CODES = {
    "consequences.lp": 1,
    "hidden-contrary.lp": 2,
    "no-objective.lp": 2,
    "optimum-wrong.lp": 1,
    "optimum.lp": 0,
    "theory-atoms.lp": 2,
    "why-not.lp": 1,
}


@pytest.mark.parametrize("name", sorted(EXIT_CODES))
def test_an_example_exits_as_the_documentation_says(name: str) -> None:
    code, _ = capture(EXAMPLES / name)
    assert code == EXIT_CODES[name]


def test_every_example_is_listed() -> None:
    assert {path.name for path in EXAMPLES.glob("*.lp")} == set(EXIT_CODES)


def test_the_examples_page_is_what_the_examples_print() -> None:
    assert TARGET.read_text() == render()
