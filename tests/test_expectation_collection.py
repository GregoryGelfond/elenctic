"""The collection predicate (R3 = known-tag membership): a contract makes a file a case."""

from elenctic.expectation import KNOWN_TAGS, has_contract


def test_known_tags_are_the_closed_vocabulary_plus_elenctic() -> None:
    expected = {
        "expect",
        "model",
        "optimal",
        "cautious",
        "brave",
        "count",
        "cost",
        "assign",
        "query",
        "note",
        "elenctic",
    }
    assert expected == KNOWN_TAGS


def test_a_file_with_a_known_tag_is_a_case() -> None:
    assert has_contract("% @expect sat\n% @model { a }\np :- a.\n") is True


def test_a_file_with_only_an_elenctic_directive_is_a_case() -> None:
    assert has_contract("% @elenctic solver clingcon\n&sum { x } >= 1.\n") is True


def test_a_library_with_no_known_tag_is_not_a_case() -> None:
    # plain prose + an UNKNOWN @word are just prose: a library, not collected (no error).
    library = "% lib/scheduling.lp - a library.\n% @param budget 8\ntask(1..3).\n"
    assert has_contract(library) is False


def test_a_half_written_case_with_a_behavioral_tag_is_still_a_case() -> None:
    # @model present but @expect missing: still collected (a known tag), fails loud at parse,
    # NOT silently reclassified a library (loud-over-silent).
    assert has_contract("% @model { ok }\nok.\n") is True


def test_a_litset_element_beginning_a_continuation_line_is_not_a_tag() -> None:
    # A brace-continued litset element is not a `% @tag` line, so it never spuriously collects.
    text = "% @cautious {\n%   a, b\n% }\nc.\n"
    assert has_contract(text) is True  # the @cautious line is the known tag
