"""Where the cursor goes when only failures are shown and its own source is left out."""

import pytest
from textual.widgets import Tree

from elenctic.tui.outline import Row, Source
from elenctic.tui.places import Node, instead


def _sources(passes: str) -> tuple[list[Node], list[Node]]:
    """Rows for sources that failed, `F`, or passed, `P`, each with a row beneath it.

    Returns the sources' rows, and the rows beneath them.
    """
    tree: Tree[Row] = Tree("sources")
    tops = [
        tree.root.add(f"{n}", Row((), (), about=Source(failed=p == "F")))
        for n, p in enumerate(passes)
    ]
    return tops, [top.add_leaf("beneath", Row((), ())) for top in tops]


def test_no_cursor_goes_nowhere() -> None:
    tops, _ = _sources("FP")
    assert instead(tops, None) is None


@pytest.mark.parametrize("deep", [False, True])
def test_a_cursor_in_a_source_that_failed_stays(*, deep: bool) -> None:
    tops, beneath = _sources("PFP")
    assert instead(tops, (beneath if deep else tops)[1]) is None


@pytest.mark.parametrize(
    ("passes", "at", "then"),
    [("FPFF", 1, 2), ("FFFP", 3, 2), ("FFPP", 2, 1), ("PP", 0, None)],
)
def test_a_cursor_in_a_source_that_passed_goes_to_the_next_that_failed_else_the_last_before(
    passes: str, at: int, then: int | None
) -> None:
    tops, beneath = _sources(passes)
    for each in (tops[at], beneath[at]):
        assert instead(tops, each) is (None if then is None else tops[then])
