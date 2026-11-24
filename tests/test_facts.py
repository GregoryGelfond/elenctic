from pathlib import Path

from clingo.ast import AST, parse_files, parse_string

from elenctic.facts import Shown, objective_at, shown_by
from elenctic.literals import Signature
from elenctic.program import Program
from elenctic.spans import Position, Span
from nesting import DEEP_NESTING


def shown(text: str) -> Shown:
    statements: list[AST] = []
    parse_string(text, statements.append)
    return shown_by(statements)


def test_each_minus_before_a_shown_predicate_flips_its_sign() -> None:
    assert shown("#show a.").signatures == {Signature("a", 0)}
    assert shown("#show -a.").signatures == {Signature("a", 0, positive=False)}
    assert shown("#show - -a.").signatures == {Signature("a", 0)}
    assert shown("#show -(-(-a(1,2))).").signatures == {Signature("a", 2, positive=False)}


def test_a_shown_term_that_is_no_predicate_selects_none() -> None:
    assert shown("#show -1.") == Shown(restricted=True)


def test_a_chain_of_minus_signs_is_read_to_any_length() -> None:
    even = DEEP_NESTING - DEEP_NESTING % 2
    assert shown(f"#show {'-' * even}a.").signatures == {Signature("a", 0)}
    assert shown(f"#show {'-' * (even + 1)}a.").signatures == {Signature("a", 0, positive=False)}


def test_a_conditional_show_does_not_name_its_predicate() -> None:
    found = shown("#show p : r. #show q.")
    assert found.signatures == {Signature("q", 0)}
    assert found.restricted
    assert not found.covers(Signature("p", 0))
    assert found.covers(Signature("q", 0))


def test_a_variable_show_does_not_cover_every_predicate() -> None:
    found = shown("#show X : q(X). #show b/0.")
    assert found.wild
    assert found.signatures == {Signature("b", 0)}
    assert found.covers(Signature("b", 0))
    assert not found.covers(Signature("b", 0, positive=False))
    assert not found.covers(Signature("q", 1))


def test_an_objective_is_placed_under_the_programs_name_or_its_file_in_clingos_columns(
    tmp_path: Path,
) -> None:
    text = 'p("é"). &minimize { x }.\n'
    statements: list[AST] = []
    parse_string(text, statements.append)
    at = Span("t.lp", Position(1, 10), Position(1, 26))
    assert objective_at(statements, Program(text, "t.lp")) == at
    library = tmp_path / "lib.lp"
    library.write_text(text, encoding="utf-8")
    loaded: list[AST] = []
    parse_files([str(library)], loaded.append)
    assert objective_at(loaded, Program("", "t.lp")) == Span(str(library), at.start, at.end)
