from pathlib import Path

from clingo.ast import AST, parse_files, parse_string

from elenctic.relaxation import Source, read
from elenctic.spans import Position, Span

TEXT = 'p("é"). q :- p("é").\n'


def placed(statements: list[AST], source: Source) -> set[tuple[Span, str]]:
    return {(clause.rule.span, clause.rule.text) for clause in read(statements, source).clauses}


def parsed() -> list[AST]:
    statements: list[AST] = []
    parse_string(TEXT, statements.append)
    return statements


def in_characters(source: str) -> set[tuple[Span, str]]:
    fact = Span(source, Position(1, 1), Position(1, 8))
    rule = Span(source, Position(1, 9), Position(1, 21))
    return {(fact, 'p("é").'), (rule, 'q :- p("é").')}


def test_a_rule_of_the_text_is_placed_in_characters_under_the_programs_name() -> None:
    assert placed(parsed(), Source("t.lp", {"t.lp": TEXT})) == in_characters("t.lp")


def test_a_rule_is_counted_in_characters_by_the_text_held_under_clingos_name() -> None:
    found = placed(parsed(), Source("t.lp", {"<string>": TEXT}))
    assert found == {(span, "") for span, _ in in_characters("t.lp")}


def test_a_rule_whose_text_is_not_at_hand_keeps_clingos_columns() -> None:
    fact = Span("t.lp", Position(1, 1), Position(1, 9))
    rule = Span("t.lp", Position(1, 10), Position(1, 23))
    assert placed(parsed(), Source("t.lp", {})) == {(fact, ""), (rule, "")}


def test_a_rule_of_a_file_is_placed_under_the_files_name(tmp_path: Path) -> None:
    library = tmp_path / "lib.lp"
    library.write_text(TEXT, encoding="utf-8")
    statements: list[AST] = []
    parse_files([str(library)], statements.append)
    found = placed(statements, Source("t.lp", {str(library): TEXT}))
    assert found == in_characters(str(library))
