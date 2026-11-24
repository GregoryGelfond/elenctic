import pytest
from clingo import Number
from clingo.ast import AST, ASTType, Location, SymbolicTerm, parse_string
from clingo.ast import Position as At

from elenctic import tree
from elenctic.spans import Position, Span
from nesting import nested


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
    assert tree.holds_flag(shown, "positive")
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


def test_a_node_is_searched_to_any_depth() -> None:
    deep = statement(f"p({nested()}).")
    assert tree.holds_somewhere(deep, lambda node: tree.kind(node) is ASTType.SymbolicTerm)
    assert not tree.holds_somewhere(deep, lambda node: tree.kind(node) is ASTType.TheoryAtom)


def test_a_renamed_copy_renames_each_variable_in_the_order_written() -> None:
    rule = statement("p(X, _) :- q(Y, X), Z = #count { W : r(W, _) }.")
    seen: list[str] = []

    def rename(name: str) -> str:
        seen.append(name)
        return f"{name}{len(seen)}"

    copy = tree.renamed(rule, rename)
    assert seen == ["X", "_", "Y", "X", "Z", "W", "W", "_"]
    assert str(copy) == "p(X1,_2) :- q(Y3,X4); Z5 = #count { W6: r(W7,_8) }."
    assert str(rule) == "p(X,_) :- q(Y,X); Z = #count { W: r(W,_) }."


def test_a_node_is_placed_where_clingo_says_under_its_name_in_utf8_columns() -> None:
    assert tree.span(statement('p("é").')) == Span("<string>", Position(1, 1), Position(1, 9))


def test_a_renamed_copy_reaches_any_depth() -> None:
    deep = statement(f"p({nested()}, X).")
    assert str(tree.renamed(deep, str.lower)).endswith(",x).")


def test_building_a_clingo_node_is_refused_in_every_test() -> None:
    with pytest.raises(AssertionError, match="a clingo node was built"):
        SymbolicTerm(Location(At("<string>", 1, 1), At("<string>", 1, 3)), Number(1))
