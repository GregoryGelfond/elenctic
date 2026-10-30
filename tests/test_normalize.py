import pytest
from clingo import Function, Number, parse_term
from clingo.ast import AST, ASTType, parse_string

from elenctic.normalize import NotAPattern, normalize
from elenctic.terms import Compound, Term, Variable

X = Variable("X")


def argument(text: str) -> AST:
    """Return the only argument of the atom `p(text)`, as clingo read it."""
    statements: list[AST] = []
    parse_string(f":- p({text}).", statements.append)
    (rule,) = (s for s in statements if s.ast_type is ASTType.Rule)
    (term,) = rule.body[0].atom.symbol.arguments
    assert isinstance(term, AST)
    return term


def normalized(text: str) -> Term | NotAPattern:
    return normalize(argument(text))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a", parse_term("a")),
        ("7", Number(7)),
        ('"s"', parse_term('"s"')),
        ("X", X),
        ("_", Variable("_")),
        ("f(a)", parse_term("f(a)")),
        ("-f(a)", parse_term("-f(a)")),
        ("(1,2)", parse_term("(1,2)")),
        ("1+2", Number(3)),
        ("2*(3+4)", Number(14)),
        ("f(1+1,b)", parse_term("f(2,b)")),
        ("|-3|", Number(3)),
        ("f(X)", Compound("f", (X,))),
        ("-f(X,a)", Compound("f", (X, parse_term("a")), positive=False)),
        ("(X,1+1)", Compound("", (X, Number(2)))),
        (
            "f(g(X),h(Y,a))",
            Compound("f", (Compound("g", (X,)), Compound("h", (Variable("Y"), parse_term("a"))))),
        ),
        ("f(g(1))", parse_term("f(g(1))")),
    ],
)
def test_a_term_is_read_as_what_it_stands_for(text: str, expected: Term) -> None:
    assert normalized(text) == expected


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("1..3", "interval"),
        ("X..3", "interval"),
        ("(a;b)", "pool"),
        ("@g(1)", "external"),
        ("f(X+1)", "arithmetic"),
        ("-X", "arithmetic"),
        ("1/0", "arithmetic"),
        ('"a"+1', "arithmetic"),
        ("f(g(1..2))", "interval"),
        ("f(g(X),(a;b))", "pool"),
    ],
)
def test_a_term_that_stands_for_no_one_term_is_not_a_pattern(text: str, reason: str) -> None:
    found = normalized(text)
    assert isinstance(found, NotAPattern)
    assert reason in found.reason
    assert str(found) == f"`{found.term}` is not a pattern: {found.reason}"


def test_a_refusal_is_not_a_term_and_so_never_equal_to_one() -> None:
    assert normalized("1..3") != Function("a")


def test_the_first_refusal_in_a_function_is_the_one_reported() -> None:
    found = normalized("f(1..2,(a;b))")
    assert isinstance(found, NotAPattern)
    assert "interval" in found.reason


def test_a_term_nested_deeper_than_the_interpreter_allows_is_read_without_recursion() -> None:
    depth = 5_000
    text = "f(" * depth + "X" + ")" * depth
    found = normalized(text)
    assert isinstance(found, Compound)
    assert found.shape == ("f", True, 1)
