"""Property-based tests for the parser layer (``terms`` + ``expectation`` + ``query``).

Example-based tests pin specific shapes; these pin *invariants* over generated inputs — the
paren-aware splitter must agree with clingo's own parse (oracle), the brace tracker must agree
with a structural balance, and the continuation must be invariant to how a litset is
line-wrapped or what prose surrounds it. A failing property is a real defect, not a flaky test.
"""

from contextlib import suppress
from functools import reduce
from operator import and_, or_

from clingo import Symbol, parse_term
from hypothesis import assume, given, strategies as st

# `_scan_braces` is past `expectation.__all__` and is what the property below is about: it carries
# brace depth and quote state across a fragment, and the invariant is stated over *that pair*,
# which `parse` neither takes nor returns.
from elenctic.expectation import ContractError, Sat, Unsat, _scan_braces, parse
from elenctic.query import (
    Answer,
    BindingQuery,
    GroundQuery,
    QueryForm,
    QueryLiteral,
    Var,
    classify,
    contrary_literal,
    parse_query,
    unify,
)
from elenctic.terms import (
    contrary,
    intersect_all,
    parse_litset,
    parse_tupleset,
    signature_of,
    union_all,
)

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


# The brace tracker is asked for the pair it carries — depth AND quote state — because the pair is
# what the tokenizer threads from one continuation line to the next. Asserting only "is a brace
# open" would leave the quote half free, and that half is the whole reason a caller cannot ask this
# question one line at a time.
@given(st.lists(atoms(), min_size=1, max_size=5))
def test_the_brace_tracker_agrees_with_structural_balance(atom_texts: list[str]) -> None:
    body = ", ".join(atom_texts)
    assert _scan_braces(f"{{ {body} }}", 0, False) == (0, False)  # balanced
    assert _scan_braces(f"{{ {body}", 0, False) == (1, False)  # the closer removed


def test_the_brace_tracker_ignores_braces_inside_quoted_strings() -> None:
    # The one place brace-counting must defer to quoting: a '{' inside a string term is not a real
    # open brace (this is what lets a litset hold a string atom containing a brace).
    assert _scan_braces('{ p("{") }', 0, False) == (0, False)
    assert _scan_braces('p("}")', 0, False) == (0, False)
    assert _scan_braces('{ p("}")', 0, False) == (1, False)


def test_the_brace_tracker_carries_an_unclosed_quote_across_the_call() -> None:
    # A string term split across continuation lines leaves the quote open, and the next fragment
    # must be scanned inside it — otherwise a '}' in the tail of that string closes a real brace.
    opened = _scan_braces('{ p("a}b', 0, False)
    assert opened == (1, True)
    assert _scan_braces('c") }', *opened) == (0, False)


@given(st.lists(atoms(), min_size=1, max_size=5))
def test_continuation_is_invariant_to_litset_line_wrapping(atom_texts: list[str]) -> None:
    # breaking a litset across continuation '%' lines at its commas must not change the parse.
    body = ", ".join(atom_texts)
    single = parse(f"% @expect sat\n% @model {{ {body} }}\n")
    wrapped = parse("% @expect sat\n% @model { " + ",\n%   ".join(atom_texts) + " }\n")
    assert isinstance(single, Sat)
    assert isinstance(wrapped, Sat)
    assert single.model == wrapped.model


# Prose that can surround a contract block: no '@' (would be a tag) and no braces (would re-open a
# litset); ':' and '/' included so realistic '% Run: clingo foo/bar.lp' headers are exercised.
_PROSE = st.from_regex(r"[A-Za-z0-9 .:/_-]{0,30}", fullmatch=True)


@given(st.lists(atoms(), min_size=1, max_size=4), st.lists(_PROSE, max_size=4))
def test_parse_is_robust_to_prose_around_a_closed_litset(
    atom_texts: list[str], prose: list[str]
) -> None:
    # once a litset's brace closes, surrounding prose '%' lines are inert.
    body = ", ".join(atom_texts)
    base = f"% @expect sat\n% @model {{ {body} }}\n"
    with_prose = base + "".join(f"% {line}\n" for line in prose)
    bare, surrounded = parse(base), parse(with_prose)
    assert isinstance(bare, Sat)
    assert isinstance(surrounded, Sat)
    assert bare.model == surrounded.model


@given(st.lists(atoms(), min_size=1, max_size=5))
def test_cautious_accumulation_is_order_independent(atom_texts: list[str]) -> None:
    # Each @cautious line is its own claim, so the claims themselves come in surface order. What
    # must not depend on that order is what they jointly claim: checking L1 and L2 apart decides
    # exactly what checking L1 ∪ L2 decides, so the atoms covered are the order-independent thing.
    lines = [f"% @cautious {{ {text} }}\n" for text in atom_texts]
    forward = parse("% @expect sat\n" + "".join(lines))
    backward = parse("% @expect sat\n" + "".join(reversed(lines)))
    assert isinstance(forward, Sat)
    assert isinstance(backward, Sat)
    # One claim per line, in surface order. Asserted first because the coverage assertions below
    # cannot see it: they compare flattened unions, which an implementation that re-merged the
    # claims into one cell would satisfy exactly as well.
    assert [claim.value for claim in forward.cautious] == [
        frozenset({parse_term(text)}) for text in atom_texts
    ]
    covered = {atom for claim in forward.cautious for atom in claim.value}
    assert covered == {atom for claim in backward.cautious for atom in claim.value}
    assert covered == {parse_term(text) for text in atom_texts}


@given(
    st.lists(st.tuples(atoms(), st.integers(min_value=-20, max_value=20)), min_size=1, max_size=5)
)
def test_parsed_assign_is_never_empty(bindings: list[tuple[str, int]]) -> None:
    # The check layer assumes a parsed @assign is non-empty: an empty expected assignment would
    # PASS vacuously (∅ ⊆ any). parse must never yield an empty Sat.assign, pinned here as the
    # standing cross-layer invariant.
    body = ", ".join(f"{atom}={value}" for atom, value in bindings)
    exp = parse(f"% @expect sat\n% @assign {{ {body} }}\n")
    assert isinstance(exp, Sat)
    assert exp.assign is not None  # absence is None, so a present cell is never the empty claim
    assert len(exp.assign.value) > 0


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


# --- the terms layer: the siblings of the two functions above, none of which had a property ---


@st.composite
def literals(draw: st.DrawFn) -> Symbol:
    """A ground literal as a clingo ``Symbol``, built through the text strategy above.

    Through ``atoms()`` rather than through ``Function`` directly, so what is generated is what a
    contract can actually be written to say — a Symbol built in Python can carry shapes no source
    text produces, and a property over those would pin behaviour nothing can reach.
    """
    return parse_term(draw(atoms()))


@given(st.lists(_terms(), min_size=1, max_size=4, unique=True))
def test_parse_tupleset_round_trips_a_list_of_bare_terms(term_texts: list[str]) -> None:
    # `parse_litset` is held against clingo's own parser above; `parse_tupleset` solves the same
    # paren-aware splitting problem over a different shape and was held by examples alone. Arity 1
    # is the bare-term listing, which is the form a one-variable binding query writes.
    parsed = parse_tupleset(", ".join(term_texts), 1)
    assert parsed == tuple((parse_term(text),) for text in term_texts)
    assert all(len(row) == 1 for row in parsed), "arity 1 yields one-element rows"


@given(st.integers(min_value=2, max_value=3), st.integers(min_value=1, max_value=3), st.data())
def test_parse_tupleset_round_trips_n_tuples_at_their_declared_arity(
    arity: int, count: int, data: st.DataObject
) -> None:
    # The other arm, and the one carrying the ambiguity the docstring names: a lone n-tuple
    # collapses under the grouping parens and is told apart from several tuples by `arity` alone.
    # Both counts are generated, so the collapsing case is not a shape only an example reaches.
    rows = [tuple(data.draw(_terms()) for _ in range(arity)) for _ in range(count)]
    body = ", ".join(f"({', '.join(row)})" for row in rows)
    parsed = parse_tupleset(body, arity)
    assert parsed == tuple(tuple(parse_term(text) for text in row) for row in rows)
    assert all(len(row) == arity for row in parsed), "every row has the declared arity"


@given(literals())
def test_contrary_is_an_involution_that_always_moves(literal: Symbol) -> None:
    # Flipping strong negation twice is the identity, and flipping it once never is — the second
    # half is what would fail if the flip were ever a no-op for some shape.
    assert contrary(contrary(literal)) == literal
    assert contrary(literal) != literal


@given(literals())
def test_a_signature_carries_the_sign_a_show_declaration_would_have_to_name(
    literal: Symbol,
) -> None:
    # The natural reading is that a signature ignores the sign, because `#show` names a name and an
    # arity. It is the opposite: `#show p/1.` and `#show -p/1.` are two declarations and a program
    # may make either observable without the other, so a signature that dropped the sign would
    # report `-p(1)` observable because `p/1` was shown.
    flipped = contrary(literal)
    assert signature_of(flipped) != signature_of(literal)
    assert signature_of(flipped)[1] == signature_of(literal)[1], "arity is untouched by the sign"
    names = {signature_of(literal)[0], signature_of(flipped)[0]}
    assert names == {literal.name, f"-{literal.name}"}


@given(st.lists(st.frozensets(literals(), max_size=4), min_size=1, max_size=4))
def test_the_cautious_and_brave_folds_bracket_every_member(
    family: list[frozenset[Symbol]],
) -> None:
    # These back the consequence readings, so a defect is a wrong verdict rather than a crash: ⋂ is
    # what a cautious contract is judged against and ⋃ what a brave one is.
    packed = tuple(family)
    meet, join = intersect_all(packed), union_all(packed)

    # Against an independent fold, not merely bracketed by the members. Bracketing bounds the meet
    # from above and the join from below, so `intersect_all` returning nothing at all satisfies
    # every inequality — and an over-small meet is exactly the defect that matters here, because a
    # cautious contract is judged against ⋂ and a missing atom there is a wrong verdict.
    assert meet == reduce(and_, packed)
    assert join == reduce(or_, packed)

    for member in family:
        assert meet <= member <= join
    assert intersect_all(tuple(reversed(packed))) == meet, "the meet does not depend on order"
    assert union_all(tuple(reversed(packed))) == join, "nor does the join"
    assert intersect_all(packed + packed) == meet, "nor on a member appearing twice"
    assert union_all(packed + packed) == join


# --- the query layer: the notation with no property at all until now ---


@st.composite
def _ground_query(draw: st.DrawFn) -> tuple[str, str, tuple[str, ...]]:
    """An ``@query`` ground payload, with the literal texts it was built from."""
    answer = draw(st.sampled_from(["yes", "no", "unknown"]))
    literal_texts = tuple(draw(st.lists(atoms(), min_size=1, max_size=4, unique=True)))
    return answer, "{ " + ", ".join(literal_texts) + " }", literal_texts


@given(_ground_query())
def test_a_ground_query_round_trips_and_classifies_by_how_many_literals_it_holds(
    built: tuple[str, str, tuple[str, ...]],
) -> None:
    # The `@query` notation had no property at all, over the form this project calls its strongest
    # differentiator. Two surfaces held against each other rather than a value written twice: the
    # parse must recover exactly the literals the payload was rendered from, and `classify` — which
    # decides both the run a query rides and the fields a check reads — must agree with the count.
    answer, payload, literal_texts = built
    query = parse_query(answer, payload)
    assert isinstance(query, GroundQuery)
    assert query.answer is Answer(answer)
    assert query.conjuncts == tuple(parse_term(text) for text in literal_texts)
    expected = (
        QueryForm.SINGLETON_GROUND if len(literal_texts) == 1 else QueryForm.CONJUNCTIVE_GROUND
    )
    assert classify(query) is expected


@given(
    st.sampled_from(["yes", "no", "unknown"]),
    _IDENT,
    st.integers(min_value=1, max_value=3),
    st.data(),
)
def test_a_binding_query_round_trips_and_its_form_turns_on_the_answer(
    answer: str, predicate: str, variables: int, data: st.DataObject
) -> None:
    # The other arm of the same routing decision, so the rule is checked on both forms. The
    # settled/unknown split is the one thing that distinguishes these, and it is the answer that
    # decides it — not the goal, and not how many bindings were listed.
    goal_vars = ["X", "Y", "Z"][:variables]
    rows = [
        tuple(data.draw(_terms()) for _ in range(variables))
        for _ in range(data.draw(st.integers(min_value=1, max_value=3)))
    ]
    body = ", ".join(row[0] if variables == 1 else f"({', '.join(row)})" for row in rows)
    payload = f"{{ {predicate}({', '.join(goal_vars)}) }} = {{ {body} }}"
    query = parse_query(answer, payload)
    assert isinstance(query, BindingQuery)
    assert query.goal.name == predicate
    assert query.bindings == frozenset(tuple(parse_term(text) for text in row) for row in rows)
    expected = QueryForm.BINDING_UNKNOWN if answer == "unknown" else QueryForm.BINDING_SETTLED
    assert classify(query) is expected


@given(literals(), st.lists(st.sampled_from(["X", "Y", "Z", "W"]), max_size=3))
def test_the_contrary_of_a_query_literal_is_an_involution_that_keeps_its_arguments(
    literal: Symbol, variables: list[str]
) -> None:
    # The query-side sibling of the `terms.contrary` property above. Stated over both forms because
    # they are two spellings of one rule, and a rule checked on one of its forms is checked on none.
    #
    # The arguments are generated rather than left empty, and that is the whole difference between
    # this and a test that holds nothing: `contrary_literal` flips one field and must carry the
    # other two through, and over an argument-less goal an implementation that dropped the
    # arguments satisfied both assertions. Verified by making one that does.
    goal = QueryLiteral(literal.name, literal.positive, tuple(Var(name) for name in variables))
    flipped = contrary_literal(goal)
    assert contrary_literal(flipped) == goal
    assert flipped != goal
    assert flipped.args == goal.args, "flipping the sign is all it may do"
    assert flipped.name == goal.name


# --- and the guarantee the whole diagnostic discipline rests on ---

# Contracts that parse, used as the seeds a mutation starts from. Pure noise is measurably the
# wrong generator for this: over three thousand random strings not one parsed, because a string
# that carries no `@` tag is refused before any payload is read, so the property would hold
# vacuously over the refusal path alone. Mutating something that works is what reaches the parser.
_SEED_CONTRACTS = (
    "% @expect sat\n% @model { a }\na.\n",
    "% @expect unsat\n:- a.\n",
    "% @expect sat\n% @query yes { p(1) }\n% @model { p(1) }\np(1).\n",
    "% @expect sat\n% @count 2\n% @model { a }\n{a;b}.\n",
    # A tag trailing a rule, and a payload continued across lines — two shapes the four
    # above do not reach. Deliberately NOT a `%* … *%` block: that is how an author turns a
    # contract off, so a tag inside one is refused, and seeding from it would have made this
    # a property about the refusal path wearing the name of a property about parsing.
    "a.  % @expect sat\n% @model { a }\n",
    "% @expect sat\n% @model { p(1),\n%           p(2) }\np(1). p(2).\n",
)


def test_every_seed_contract_parses() -> None:
    # The non-vacuity control for the property below, and it is deliberately not a property itself:
    # if the seeds stopped parsing, the mutation would start from something already refused and the
    # totality claim would be a statement about the refusal path.
    for source in _SEED_CONTRACTS:
        # The type, not `is not None`: `parse` is annotated `-> Expectation` and returns one or
        # raises, so a None check is a sentence that cannot fail and its message cannot print.
        assert isinstance(parse(source), Sat | Unsat), f"a seed no longer parses: {source!r}"


@given(
    st.sampled_from(_SEED_CONTRACTS),
    st.integers(min_value=0, max_value=200),
    st.text(alphabet="abcp-()%*@{},.=1 \n\"'_/", max_size=8),
)
def test_a_contract_either_parses_or_is_refused_and_never_raises_anything_else(
    seed: str, cut: int, inserted: str
) -> None:
    # The friendly-diagnostic rule stated as a property rather than as an aspiration: every
    # user-visible failure is a ContractError carrying what went wrong, so a corpus author is never
    # shown a traceback from elenctic's own parser. An IndexError off a truncated payload is exactly
    # the shape an example-based suite does not reach, and it would surface here as a run that ends
    # with a stack trace instead of a case that is refused with a reason.
    damaged = seed[: cut % (len(seed) + 1)] + inserted
    # No assertion, and that is the shape of the claim rather than an omission: parsing is
    # allowed to succeed and ContractError is allowed to be raised, so what this test holds is
    # that *nothing else* escapes. Any other exception propagates out of here and fails it.
    with suppress(ContractError):
        parse(damaged)
