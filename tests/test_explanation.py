import pytest

from elenctic.determination import AnswerSet
from elenctic.explanation import (
    Counterexample,
    Explanation,
    Minimality,
    Node,
    NoRule,
    Unexpanded,
)
from elenctic.search import Limit

COUNTEREXAMPLE = Counterexample(AnswerSet(frozenset(), frozenset()), 1, 1)


def test_an_explanation_with_an_unexpanded_node_is_incomplete() -> None:
    node = Node("1/not p", "p", holds=False, reason=Unexpanded(2))
    found = Explanation(COUNTEREXAMPLE, ("1/not p",), (node,), Minimality.NONE, 2, complete=False)
    assert not found.complete


@pytest.mark.parametrize(("reason", "complete"), [(Unexpanded(2), True), (NoRule(), False)])
def test_complete_says_exactly_whether_no_node_is_unexpanded(
    reason: Unexpanded | NoRule, complete: bool
) -> None:
    node = Node("1/not p", "p", holds=False, reason=reason)
    with pytest.raises(ValueError, match="complete exactly when"):
        Explanation(
            COUNTEREXAMPLE,
            ("1/not p",),
            (node,),
            Minimality.NONE,
            Limit.UNBOUNDED,
            complete=complete,
        )
