from clingo import Function, Number, String, Supremum, Tuple_
from clingo.ast import AST, parse_string

from elenctic import tree
from elenctic.clauses import ground_text


def body(text: str) -> tuple[AST, ...]:
    found: list[AST] = []
    parse_string(f":- {text}.", found.append)
    return tree.children(found[-1], "body")


def test_each_variable_with_a_value_is_written_as_that_value() -> None:
    values = {"X": Number(-3), "Y": String('a"b'), "Z": Function("f", [Number(1), Function("g")])}
    written = [
        ground_text(part, values) for part in body("X < 40, X + 1 < Y, (X, Z) != W, |X| > 1")
    ]
    assert written == ["-3 < 40", '(-3+1) < "a\\"b"', "(-3,f(1,g)) != W", "|-3| > 1"]


def test_a_tuple_and_the_greatest_term_are_written_as_clingo_writes_them() -> None:
    (part,) = body("X = Y")
    assert ground_text(part, {"X": Tuple_([Number(1)]), "Y": Supremum}) == "(1,) = #sup"


def test_grounding_a_part_leaves_the_part_as_written() -> None:
    (part,) = body("X < 40")
    ground_text(part, {"X": Number(1)})
    assert str(part) == "X < 40"
