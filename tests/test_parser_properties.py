"""Property-based tests for the parser layer (``terms`` + ``expectation`` + ``query``).

Example-based tests pin specific shapes; these pin *invariants* over generated inputs — the
paren-aware splitter must agree with clingo's own parse (oracle), the brace tracker must agree
with a structural balance, and the dx#1 continuation must be invariant to how a litset is
line-wrapped or what prose surrounds it. A failing property is a real defect, not a flaky test.
"""

from clingo import parse_term
from hypothesis import assume, given
from hypothesis import strategies as st

from elenctic.expectation import Sat, _has_unclosed_brace, parse
from elenctic.query import QueryLiteral, Var, unify
from elenctic.terms import parse_litset

# An ASP identifier (predicate or constant): lower-case initial, short to keep generation cheap.
_IDENT = st.from_regex(r"[a-z][a-z0-9_]{0,5}", fullmatch=True)


def _terms() -> st.SearchStrategy[str]:
    """A ground argument term: a constant or a small non-negative integer (no leading '-', which
    would be arithmetic negation rather than a strong-negation literal)."""
    return st.one_of(_IDENT, st.integers(min_value=0, max_value=20).map(str))


@st.composite
def atoms(draw: st.DrawFn) -> str:
    """A clingo-parseable ground literal as source text: ``[-]name`` or ``[-]name(t1, …, tn)``.

    Generations that clingo rejects (a reserved word, say) are discarded via ``assume`` so the
    strategy yields only well-formed litset elements.
    """
    sign = draw(st.sampled_from(["", "-"]))
    name = draw(_IDENT)
    arity = draw(st.integers(min_value=0, max_value=3))
    args = [draw(_terms()) for _ in range(arity)]
    text = f"{sign}{name}" if not args else f"{sign}{name}({', '.join(args)})"
    try:
        parse_term(text)
    except RuntimeError:
        assume(False)
    return text


@given(st.lists(atoms(), min_size=1, max_size=6))
def test_parse_litset_agrees_with_clingo_atom_parse(atom_texts: list[str]) -> None:
    # The paren-aware splitter must recover exactly the atoms clingo parses standalone — never
    # splitting an atom's internal comma, never merging two atoms.
    body = ", ".join(atom_texts)
    assert parse_litset(body) == tuple(parse_term(text) for text in atom_texts)


@given(st.lists(atoms(), min_size=1, max_size=5))
def test_has_unclosed_brace_tracks_structural_balance(atom_texts: list[str]) -> None:
    body = ", ".join(atom_texts)
    assert _has_unclosed_brace(f"{{ {body} }}") is False  # balanced
    assert _has_unclosed_brace(f"{{ {body}") is True  # the closer removed


def test_has_unclosed_brace_ignores_braces_inside_quoted_strings() -> None:
    # The one place brace-counting must defer to quoting: a '{' inside a string term is not a real
    # open brace (this is what lets a litset hold a string atom containing a brace).
    assert _has_unclosed_brace('{ p("{") }') is False
    assert _has_unclosed_brace('p("}")') is False
    assert _has_unclosed_brace('{ p("}")') is True


@given(st.lists(atoms(), min_size=1, max_size=5))
def test_continuation_is_invariant_to_litset_line_wrapping(atom_texts: list[str]) -> None:
    # dx#1: breaking a litset across continuation '%' lines at its commas must not change the parse.
    body = ", ".join(atom_texts)
    single = parse(f"% @expect sat\n% @model {{ {body} }}\n")
    wrapped = parse("% @expect sat\n% @model { " + ",\n%   ".join(atom_texts) + " }\n")
    assert isinstance(single, Sat) and isinstance(wrapped, Sat)
    assert single.model == wrapped.model


# Prose that can surround a contract block: no '@' (would be a tag) and no braces (would re-open a
# litset); ':' and '/' included so realistic '% Run: clingo foo/bar.lp' headers are exercised.
_PROSE = st.from_regex(r"[A-Za-z0-9 .:/_-]{0,30}", fullmatch=True)


@given(st.lists(atoms(), min_size=1, max_size=4), st.lists(_PROSE, max_size=4))
def test_parse_is_robust_to_prose_around_a_closed_litset(
    atom_texts: list[str], prose: list[str]
) -> None:
    # dx#1: once a litset's brace closes, surrounding prose '%' lines are inert.
    body = ", ".join(atom_texts)
    base = f"% @expect sat\n% @model {{ {body} }}\n"
    with_prose = base + "".join(f"% {line}\n" for line in prose)
    bare, surrounded = parse(base), parse(with_prose)
    assert isinstance(bare, Sat) and isinstance(surrounded, Sat)
    assert bare.model == surrounded.model


@given(st.lists(atoms(), min_size=1, max_size=5))
def test_cautious_accumulation_is_order_independent(atom_texts: list[str]) -> None:
    # Accumulating tags (spec §2.2 rule 2) form the union of their litsets, independent of order.
    lines = [f"% @cautious {{ {text} }}\n" for text in atom_texts]
    forward = parse("% @expect sat\n" + "".join(lines))
    backward = parse("% @expect sat\n" + "".join(reversed(lines)))
    assert isinstance(forward, Sat) and isinstance(backward, Sat)
    assert forward.cautious == backward.cautious
    assert forward.cautious == frozenset(parse_term(text) for text in atom_texts)


@given(st.lists(_terms(), min_size=1, max_size=3), _IDENT)
def test_unify_recovers_the_binding_that_built_the_atom(arg_values: list[str], pred: str) -> None:
    # Soundness of the unifier: build q(t1, …, tn) from an all-variable goal q(X1, …, Xn); unify
    # must return exactly the substitution Xi ↦ ti that produced it.
    variables = [f"X{index}" for index in range(len(arg_values))]
    goal = QueryLiteral(pred, True, tuple(Var(name) for name in variables))
    try:
        atom = parse_term(f"{pred}({', '.join(arg_values)})")
    except RuntimeError:
        assume(False)
    subst = unify(goal, atom)
    expected = {name: parse_term(value) for name, value in zip(variables, arg_values, strict=True)}
    assert subst == expected
