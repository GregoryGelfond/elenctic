import pytest
from clingo import Number

from elenctic.relation import Relation
from elenctic.terms import Variable

X, Y, Z = Variable("X"), Variable("Y"), Variable("Z")


def relation(columns: tuple[Variable, ...], *rows: tuple[int, ...]) -> Relation:
    return Relation(columns, frozenset(tuple(Number(v) for v in row) for row in rows))


def test_a_join_keeps_the_pairs_of_rows_that_agree_on_their_shared_columns() -> None:
    joined = relation((X, Y), (1, 2), (1, 3), (2, 3)).join(relation((Y, Z), (3, 7), (4, 8)))
    assert joined == relation((X, Y, Z), (1, 3, 7), (2, 3, 7))


def test_a_join_without_a_shared_column_pairs_every_row_with_every_row() -> None:
    joined = relation((X,), (1,), (2,)).join(relation((Y,), (3,), (4,)))
    assert joined == relation((X, Y), (1, 3), (1, 4), (2, 3), (2, 4))


def test_a_join_with_the_relation_of_no_columns_and_one_row_changes_nothing() -> None:
    unit = relation((), ())
    assert unit.join(relation((X,), (1,))) == relation((X,), (1,))
    assert relation((X,), (1,)).join(unit) == relation((X,), (1,))


def test_a_join_with_an_empty_relation_is_empty() -> None:
    assert relation((X,), (1,)).join(relation((X,))).rows == frozenset()


def test_a_union_takes_the_rows_of_either_whatever_the_order_of_the_columns() -> None:
    united = relation((X, Y), (1, 2)).union(relation((Y, X), (4, 3), (2, 1)))
    assert united == relation((X, Y), (1, 2), (3, 4))


def test_the_union_of_relations_over_different_variables_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot unite"):
        relation((X,), (1,)).union(relation((Y,), (1,)))


def test_each_row_is_the_values_its_columns_take() -> None:
    assert relation((X, Y), (1, 2)).assignments() == [{X: Number(1), Y: Number(2)}]
