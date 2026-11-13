import unicodedata

import pytest
from clingo import parse_term

from elenctic.determination import NoAssumptions, NotThese, These, Truncation, Valuation
from elenctic.display import legible
from elenctic.explanation import (
    Aggregate,
    Blocked,
    Chosen,
    Derived,
    Fact,
    Minimality,
    Node,
    NoRule,
    NotChosen,
    Reason,
    Rule,
    TheoryAtom,
    Unexpanded,
    Unexplained,
    Unsupported,
)
from elenctic.glyphs import Glyphs
from elenctic.legend import (
    COPYRIGHT,
    CUT_WORDS,
    EVIDENCE,
    GUARANTEE,
    MARKS,
    Mark,
    ended,
    label,
    listed,
    mark,
    refuted,
    words,
)
from elenctic.literals import Assumption, Literal
from elenctic.paint import Piece, Role, plain
from elenctic.spans import Position, Span
from elenctic.substitution import Substitution
from elenctic.verdicts import Ended, Verdict

PAIRS = [
    (Verdict.PASS, "\uf058", "[PASS]"),
    (Verdict.FAIL, "\uf057", "[FAIL]"),
    (Verdict.UNDECIDED, "\uf059", "[UNDECIDED]"),
]


def test_every_verdict_has_a_mark_and_no_other_exists() -> None:
    assert list(MARKS) == [verdict for verdict, _, _ in PAIRS]


@pytest.mark.parametrize(("verdict", "nerd", "plain"), PAIRS)
def test_a_mark_pairs_its_nerd_glyph_with_the_text_it_replaces(
    verdict: Verdict, nerd: str, plain: str
) -> None:
    mark = MARKS[verdict]
    assert (mark.shown(Glyphs.NERD), mark.shown(Glyphs.PLAIN)) == (nerd, plain)


@pytest.mark.parametrize("verdict", list(Verdict))
def test_a_nerd_glyph_is_private_use_and_its_plain_form_is_not(verdict: Verdict) -> None:
    mark = MARKS[verdict]
    assert all(unicodedata.category(c) == "Co" for c in mark.nerd)
    assert not any(unicodedata.category(c) == "Co" for c in mark.plain)


def test_legible_would_mangle_a_nerd_glyph_so_it_is_added_after_legible() -> None:
    for glyph in MARKS.values():
        assert legible(glyph.nerd) != glyph.nerd
        assert legible(glyph.plain) == glyph.plain


def test_the_copyright_glyph_is_fa_copyright_and_the_plain_form_is_the_sign() -> None:
    assert (COPYRIGHT.shown(Glyphs.NERD), COPYRIGHT.shown(Glyphs.PLAIN)) == ("\uf1f9", "\u00a9")


def test_the_nerd_copyright_would_be_mangled_by_legible_and_the_plain_sign_would_not() -> None:
    assert legible(COPYRIGHT.nerd) != COPYRIGHT.nerd
    assert legible(COPYRIGHT.plain) == COPYRIGHT.plain
    assert unicodedata.category(COPYRIGHT.nerd) == "Co"
    assert unicodedata.category(COPYRIGHT.plain) == "So"


RULE = Rule(0, Span("t.lp", Position(2, 1), Position(2, 9)), "p :- q.")
NONE = Substitution({})
REASONS: list[tuple[Reason, Mark]] = [
    (Fact(RULE), Mark.FACT),
    (Derived(RULE, NONE, "p :- q."), Mark.DERIVED),
    (Chosen(RULE, NONE, "{ p }.", None, None, 1), Mark.CHOSEN),
    (NotChosen(RULE, NONE, "{ p }.", 1, 1, 0), Mark.CHOSEN),
    (Aggregate(RULE, NONE, "p :- 2 = #count { q }.", "2 = #count { q }", 1, "= 2"), Mark.AGGREGATE),
    (TheoryAtom("&sum { s } >= 7", frozenset()), Mark.THEORY_ATOM),
    (Unexpanded(3), Mark.UNEXPANDED),
    (Blocked(RULE, NONE, "p :- q.", "q"), Mark.ABSENT),
    (Unsupported(1), Mark.ABSENT),
    (NoRule(), Mark.ABSENT),
    (Unexplained(None), Mark.ABSENT),
]


def test_every_mark_of_evidence_has_a_glyph() -> None:
    assert set(EVIDENCE) == set(Mark)


def test_every_kind_of_reason_has_one_mark_and_is_worded() -> None:
    assert len(REASONS) == len(Reason.__value__.__args__)
    for reason, expected in REASONS:
        node = Node("1/p", "p", holds=not isinstance(reason, Blocked), reason=reason)
        assert mark(node) is expected
        assert plain(label(node))
        assert plain(words(node))


def test_a_phrase_is_its_pieces_one_after_another() -> None:
    assert plain((Piece("line 2:", Role.REFERENCE), Piece(" blocked by "), Piece("q"))) == (
        "line 2: blocked by q"
    )


def test_every_guarantee_and_every_cut_is_worded() -> None:
    assert set(GUARANTEE) == set(Minimality)
    assert set(CUT_WORDS) == set(Truncation)
    assert ended(Ended(Truncation.INTERRUPTED, optimum_unproven=True)) == (
        "no optimum proven: search ended: interrupted"
    )


def test_a_refutation_is_worded_once_for_every_view() -> None:
    core = frozenset({Assumption(Literal("q")), Assumption(Literal("p"), holds=False)})
    assert refuted(These(core, minimal=True)) == (
        "no answer set satisfies the assumptions (not p, q)"
    )
    assert refuted(NotThese()) == "the program has no answer set, whatever is assumed"
    assert refuted(NoAssumptions()) == "the program has no answer set, and nothing is assumed"


def test_literals_and_valuations_are_listed_in_their_own_order_and_nothing_else_is() -> None:
    literals = [Literal.parse(f"p({n})") for n in (10, 2, 1)]
    assert listed(frozenset(literals)) == sorted(literals)
    assert [str(each) for each in listed(frozenset(literals)) or ()] == ["p(1)", "p(2)", "p(10)"]
    valuations = frozenset({Valuation(parse_term("x(10)"), 1), Valuation(parse_term("x(2)"), 1)})
    assert [str(each.variable) for each in listed(valuations) or ()] == ["x(2)", "x(10)"]
    assumptions = frozenset({Assumption(Literal("q")), Assumption(Literal("p"), holds=False)})
    assert [str(each) for each in listed(assumptions) or ()] == ["not p", "q"]
    assert listed(frozenset({Literal("p"), Valuation(parse_term("x"), 1)})) is None
    assert listed(frozenset({(Literal("p"),)})) is None
    rows = frozenset({(parse_term("b"), parse_term("10")), (parse_term("b"), parse_term("2"))})
    assert [",".join(map(str, row)) for row in listed(rows) or ()] == ["b,2", "b,10"]
