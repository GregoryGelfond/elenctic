import pytest
from clingo.ast import AST, ASTType, parse_string

from elenctic import tree


def statement(text: str) -> AST:
    found: list[AST] = []
    parse_string(text, found.append)
    return found[-1]


def test_a_node_is_read_by_its_kind_and_its_parts() -> None:
    rule = statement("p(X) :- q(X), not r(X).")
    assert tree.kind(rule) is ASTType.Rule
    assert [tree.kind(literal) for literal in tree.children(rule, "body")] == [ASTType.Literal] * 2
    head = tree.child(tree.child(rule, "head"), "atom")
    assert tree.name(tree.child(head, "symbol")) == "p"


def test_numbers_and_flags_are_read_as_what_they_are() -> None:
    shown = statement("#show p/2.")
    assert tree.number(shown, "arity") == 2
    assert tree.flag(shown, "positive")
    assert tree.location(shown).begin.line == 1
    atom = tree.child(tree.child(statement("p(1)."), "head"), "atom")
    (argument,) = tree.children(tree.child(atom, "symbol"), "arguments")
    assert tree.symbol(argument).number == 1


def test_the_subtrees_of_a_node_are_those_directly_beneath_it() -> None:
    rule = statement("p :- q, r.")
    assert [tree.kind(each) for each in tree.subtrees(rule)] == [
        ASTType.Literal,
        ASTType.Literal,
        ASTType.Literal,
    ]


def test_a_part_that_is_not_what_it_was_asked_for_is_refused() -> None:
    with pytest.raises(TypeError, match="Rule holds its `body` as a"):
        tree.child(statement("p :- q."), "body")
