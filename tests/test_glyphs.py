import unicodedata

import pytest

from elenctic.display import legible
from elenctic.glyphs import COPYRIGHT, MARKS, Glyphs
from elenctic.verdicts import Verdict

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
    for mark in MARKS.values():
        assert legible(mark.nerd) != mark.nerd
        assert legible(mark.plain) == mark.plain


def test_the_copyright_glyph_is_fa_copyright_and_the_plain_form_is_the_sign() -> None:
    assert (COPYRIGHT.shown(Glyphs.NERD), COPYRIGHT.shown(Glyphs.PLAIN)) == ("\uf1f9", "\u00a9")


def test_the_nerd_copyright_would_be_mangled_by_legible_and_the_plain_sign_would_not() -> None:
    assert legible(COPYRIGHT.nerd) != COPYRIGHT.nerd
    assert legible(COPYRIGHT.plain) == COPYRIGHT.plain
    assert unicodedata.category(COPYRIGHT.nerd) == "Co"
    assert unicodedata.category(COPYRIGHT.plain) == "So"
