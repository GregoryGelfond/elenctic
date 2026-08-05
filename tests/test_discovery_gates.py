"""The preconditions + the theory-presence gate, over ProgramFacts.

These check the gates in isolation against constructed ProgramFacts — the pure precondition layer,
independent of the discovery walk that wires them in."""

from pathlib import Path

import pytest

from elenctic.discovery import DiscoveryError, check_program
from elenctic.expectation import parse
from elenctic.program import ProgramFacts, Restricted, ShownVocabulary, Unrestricted
from elenctic.terms import Signature

WHERE = Path("case.lp")

SHOWS_NOTHING = Restricted(signatures=frozenset(), displayed=frozenset())
"""A program whose only declaration is a bare ``#show.``. It is the default below, so a gate test
that names no vocabulary is asking what happens when the program makes nothing observable — which
is a different program from one that restricts nothing, and the reason the two are not one value."""


def _shows(*signatures: Signature, displayed: frozenset[Signature] = frozenset()) -> Restricted:
    """A program restricted to ``signatures``, optionally also carrying ``#show <term> : <body>.``
    directives over ``displayed``."""
    return Restricted(signatures=frozenset(signatures), displayed=displayed)


def _facts(
    *,
    theory: bool = False,
    shown: ShownVocabulary = SHOWS_NOTHING,
    projection: bool = False,
    opt: bool = False,
    maxi: bool = False,
    theory_opt: bool = False,
) -> ProgramFacts:
    return ProgramFacts(
        has_theory_atom=theory,
        shown=shown,
        has_projection=projection,
        has_optimization=opt,
        has_maximize=maxi,
        has_theory_optimization=theory_opt,
        sources=frozenset(),  # check_program does not read sources (hygiene-only); empty is fine
    )


def test_r1_theory_atom_under_clingo_is_loud() -> None:
    # A theory atom in the resolved program under a (default/declared) clingo solver → loud refusal,
    # no verdict. Theory-agnostic (presence, never identity).
    exp = parse("% @expect sat\n")
    with pytest.raises(DiscoveryError, match=r"theory atom.*clingo.*@elenctic solver clingcon"):
        check_program(exp, _facts(theory=True), "clingo", WHERE)


def test_r1_theory_atom_under_clingcon_is_allowed() -> None:
    exp = parse("% @expect sat\n")
    check_program(exp, _facts(theory=True), "clingcon", WHERE)  # no raise


def test_r4_theory_contract_under_clingo_is_loud() -> None:
    # The contract-side dual: @assign reads the theory half, but the program is theory-free and the
    # solver is clingo → an empty assignment would mis-evaluate. Loud.
    exp = parse("% @expect sat\n% @assign { x=1 }\n")
    with pytest.raises(DiscoveryError, match=r"theory binding.*needs a theory solver"):
        check_program(exp, _facts(), "clingo", WHERE)


def test_r2_optimal_base_needs_an_optimizing_encoding() -> None:
    exp = parse("% @expect sat\n% @optimal { a }\n")
    with pytest.raises(DiscoveryError, match=r"optimizing encoding"):
        check_program(exp, _facts(opt=False), "clingo", WHERE)


def test_a_bare_as_p_tag_over_a_theory_objective_is_loud() -> None:
    # The converse of the optimizing-encoding gate, and the reason it needs one: clingo's
    # --opt-mode=ignore switches off *clingo's* optimize statements, but a clingcon &minimize is a
    # theory atom its own propagator drives, so the AS(P) modes cannot switch it off. They would
    # read a pruned model stream and answer a different question, silently. Refuse instead.
    exp = parse("% @expect sat\n% @cautious { a }\n")
    with pytest.raises(DiscoveryError, match=r"&minimize.*AS\(P\)|theory objective"):
        check_program(exp, _facts(theory=True, theory_opt=True), "clingcon", WHERE)


def test_every_bare_as_p_tag_is_caught_over_a_theory_objective() -> None:
    # The gate keys on the contract reading AS(P), not on one tag: every tag that rides an AS(P)
    # run is refused, including @query, which reaches AS(P) by two different routes.
    for contract in (
        "% @expect sat\n% @count 2\n",
        "% @expect sat\n% @model { a }\n",
        "% @expect sat\n% @cautious { a }\n",
        "% @expect sat\n% @brave { a }\n",
        "% @expect sat\n% @query yes { a }\n",
        "% @expect sat\n% @query yes { a, b }\n",
    ):
        with pytest.raises(DiscoveryError, match=r"&minimize"):
            check_program(parse(contract), _facts(theory=True, theory_opt=True), "clingcon", WHERE)


def test_expect_sat_alone_over_a_theory_objective_is_allowed() -> None:
    # @expect sat reads only whether an answer set exists. A theory objective ranks answer sets
    # without removing any, so it cannot change that: there is nothing to refuse.
    exp = parse("% @expect sat\n")
    check_program(exp, _facts(theory=True, theory_opt=True), "clingcon", WHERE)


def test_a_bare_as_p_tag_without_a_theory_objective_is_allowed() -> None:
    # The gate is scoped to the theory objective. A bare AS(P) tag over a clingo #minimize is fine:
    # --opt-mode=ignore does switch that off, which is the whole point of stating it.
    exp = parse("% @expect sat\n% @cautious { a }\n")
    check_program(exp, _facts(theory=True, opt=True), "clingcon", WHERE)


def test_r2_cost_over_maximize_is_loud_the_silent_miscompile_guard() -> None:
    # The GATING case: a #maximize in the (resolved) library would skip this if we scanned the text.
    exp = parse("% @expect sat\n% @cost { 3 }\n")
    with pytest.raises(DiscoveryError, match=r"@cost over a #maximize"):
        check_program(exp, _facts(opt=True, maxi=True), "clingo", WHERE)


def test_r2_no_query_needs_the_contrary_shown() -> None:
    exp = parse("% @expect sat\n% @query no { reachable(a) }\n")
    with pytest.raises(DiscoveryError, match=r"reads -reachable/1"):
        check_program(exp, _facts(shown=_shows(("reachable", 1))), "clingo", WHERE)


def test_a_clean_program_passes_all_gates() -> None:
    # A theory-free Sat contract with an optimizing encoding under clingo: no gate fires.
    exp = parse("% @expect sat\n% @optimal { a }\n")
    check_program(exp, _facts(opt=True), "clingo", WHERE)  # no raise


def test_unsat_contract_skips_the_model_bearing_gates() -> None:
    # @expect unsat carries no model-bearing tag, so only the program-side theory gate fires.
    exp = parse("% @expect unsat\n")
    check_program(exp, _facts(), "clingo", WHERE)  # no raise


# What each @query form reads, and so what a program must show for its answer to be the program's
# rather than the #show directives'. Written out as literals rather than asked of the code, so the
# table can disagree with the implementation; a table computed from `signatures_read` would agree
# with any implementation that is merely self-consistent.
#
# The ground forms read both signs and the binding forms read one. That is not a policy: a ground
# query computes a three-valued answer, which cannot tell `no` from `unknown` without the contrary,
# while a binding query collects the tuples whose answer is the stated one and never looks at the
# other sign.
_R = ("reachable", 1)
_NR = ("-reachable", 1)
_B = ("blocked", 1)
_NB = ("-blocked", 1)

_READS: list[tuple[str, frozenset[Signature]]] = [
    ("@query yes { reachable(x) }", frozenset({_R, _NR})),
    ("@query no { reachable(x) }", frozenset({_R, _NR})),
    ("@query unknown { reachable(x) }", frozenset({_R, _NR})),
    ("@query no { -reachable(x) }", frozenset({_R, _NR})),
    ("@query yes { reachable(x), blocked(y) }", frozenset({_R, _NR, _B, _NB})),
    ("@query unknown { reachable(x), blocked(y) }", frozenset({_R, _NR, _B, _NB})),
    ("@query yes { reachable(X) } = { a }", frozenset({_R})),
    ("@query no { reachable(X) } = { a }", frozenset({_NR})),
    ("@query unknown { reachable(X) } = { a }", frozenset({_R, _NR})),
    # The empty stated set is not a carve-out. With `-reachable` unshown the computed no-set is
    # forced empty, so a contract stating `{ }` cannot fail — vacuously *passable*, which is the
    # opposite of the vacuously-satisfiable reading this once had.
    ("@query no { reachable(X) } = { }", frozenset({_NR})),
    ("@query yes { reachable(X) } = { }", frozenset({_R})),
    # A negative goal reads its own sign for the answer it states, so `no` over `-reachable(X)`
    # collects `reachable` tuples.
    ("@query no { -reachable(X) } = { a }", frozenset({_R})),
    ("@query yes { -reachable(X) } = { a }", frozenset({_NR})),
    # Arity, on both axes that a one-argument goal cannot separate. A binding goal's SIGNATURE
    # carries its argument count, while its binding tuples carry its distinct-variable count, and
    # `q(X, X)` is the program where those two numbers differ — so a signature built from the
    # variables rather than the arguments reads `q/1` here and is caught nowhere else.
    ("@query yes { link(X, X) } = { a }", frozenset({("link", 2)})),
    ("@query no { link(X, Y) } = { (a, b) }", frozenset({("-link", 2)})),
    ("@query unknown { link(X, Y) } = { (a, b) }", frozenset({("link", 2), ("-link", 2)})),
    # 0-arity, which renders as `p/0` and would be lost by any signature reader that keys on the
    # presence of arguments rather than on their number.
    ("@query yes { settled }", frozenset({("settled", 0), ("-settled", 0)})),
    # A conjunction whose conjuncts differ in arity and in sign, so the per-conjunct fold is not
    # exercised only over lookalikes.
    (
        "@query unknown { settled, -link(a, b) }",
        frozenset({("settled", 0), ("-settled", 0), ("link", 2), ("-link", 2)}),
    ),
]


@pytest.mark.parametrize(("query_tag", "reads"), _READS, ids=[row for row, _ in _READS])
def test_a_query_is_admitted_when_the_program_shows_exactly_what_it_reads(
    query_tag: str, reads: frozenset[Signature]
) -> None:
    exp = parse(f"% @expect sat\n% {query_tag}\n")
    check_program(exp, _facts(shown=_shows(*reads)), "clingo", WHERE)  # no raise


@pytest.mark.parametrize(("query_tag", "reads"), _READS, ids=[row for row, _ in _READS])
def test_a_query_is_refused_when_any_one_signature_it_reads_is_unshown(
    query_tag: str, reads: frozenset[Signature]
) -> None:
    # Tightness, one signature at a time: the row above says these are read, and this says each of
    # them is load-bearing. Dropping any one leaves a query whose answer the program does not
    # determine, and the diagnostic must name the one that is missing.
    exp = parse(f"% @expect sat\n% {query_tag}\n")
    for withheld in reads:
        with pytest.raises(DiscoveryError, match=rf"reads {withheld[0]}/{withheld[1]}\b"):
            check_program(exp, _facts(shown=_shows(*(reads - {withheld}))), "clingo", WHERE)


@pytest.mark.parametrize("query_tag", [row for row, _ in _READS], ids=lambda value: value[:44])
def test_a_program_that_restricts_nothing_answers_every_query_form(query_tag: str) -> None:
    # A program with no #show declaration shows every atom, so every literal is observable and no
    # query can read past what the program determines. The vocabulary being an alternative is what
    # tells this apart from the program below, which shows nothing and has the same empty set of
    # signatures.
    exp = parse(f"% @expect sat\n% {query_tag}\n")
    check_program(exp, _facts(shown=Unrestricted()), "clingo", WHERE)  # no raise


@pytest.mark.parametrize("query_tag", [row for row, _ in _READS], ids=lambda value: value[:44])
def test_a_program_that_shows_nothing_answers_no_query_form(query_tag: str) -> None:
    exp = parse(f"% @expect sat\n% {query_tag}\n")
    with pytest.raises(DiscoveryError, match=r"its only `#show` is the bare form"):
        check_program(exp, _facts(shown=SHOWS_NOTHING), "clingo", WHERE)


def test_the_undeclared_refusal_states_what_is_read_what_is_declared_and_what_to_add() -> None:
    # The whole line, because a substring of a diagnostic pins almost nothing: every clause here is
    # a separate claim about the program.
    #
    # It says what the program DECLARES, never what it shows. That is not a nicety: a display
    # directive emits its term whatever the declarations are, so a program declaring nothing can
    # still put something in the output, and a sentence about the output would be false for it —
    # which is exactly the defect this whole refusal was rewritten to stop repeating.
    exp = parse("% @expect sat\n% @query no { reachable(a) }\n")
    with pytest.raises(DiscoveryError) as caught:
        check_program(exp, _facts(shown=_shows(("reachable", 1))), "clingo", WHERE)
    assert str(caught.value) == (
        "case.lp:2: this @query reads -reachable/1, which the program does not declare "
        "observable — it declares {reachable/1} observable. elenctic answers a query from what "
        "the solver puts in the output, so a literal that does not reach it exactly when the "
        "answer set contains it "
        "cannot be told apart from one no answer set contains, and the answer would describe the "
        "#show directives rather than the program. Declare #show -reachable/1., or drop the query"
    )


def test_a_signature_only_ever_displayed_is_refused_as_its_own_fault() -> None:
    # An author who wrote `#show reachable(X) : …` can see the predicate named in their own file, so
    # a message telling them it is absent would be false to them. It is a different fault from an
    # undeclared signature and it gets its own sentence: the predicate is not missing from the
    # output, it arrives there on the directive's terms rather than the answer set's.
    exp = parse("% @expect sat\n% @query yes { reachable(a) }\n")
    shown = _shows(("reachable", 1), ("-reachable", 1), displayed=frozenset({("reachable", 1)}))
    displays = r"displays with a `#show <term> : <body>\.` directive"
    with pytest.raises(DiscoveryError, match=displays):
        check_program(exp, _facts(shown=shown), "clingo", WHERE)


def test_the_displayed_refusal_fires_even_where_nothing_is_restricted() -> None:
    # The half that a `Restricted`-only check would miss, and the one that was measured reporting
    # `1/1 passed` on a false claim: an unrestricted program loses nothing, which says nothing at
    # all about what a display directive may ADD on top of it.
    exp = parse("% @expect sat\n% @query yes { reachable(a) }\n")
    shown = Unrestricted(displayed=frozenset({("reachable", 1)}))
    with pytest.raises(DiscoveryError, match=r"the output can carry a symbol no answer set"):
        check_program(exp, _facts(shown=shown), "clingo", WHERE)


def test_a_displayed_signature_the_query_does_not_read_is_no_obstacle() -> None:
    # The other side of it: a display directive over an unrelated predicate says nothing about the
    # signatures this query consults, so it must not refuse.
    exp = parse("% @expect sat\n% @query yes { reachable(a) }\n")
    shown = _shows(("reachable", 1), ("-reachable", 1), displayed=frozenset({("label", 1)}))
    check_program(exp, _facts(shown=shown), "clingo", WHERE)  # no raise


def test_the_refusal_names_the_line_the_query_was_written_on() -> None:
    # @query is repeatable, so a file carrying several of them has to say which one is unanswerable.
    # The offending one is in the MIDDLE, with an answerable query on either side, so a refusal that
    # reported the first line, the last line, or the largest one would each be caught here.
    exp = parse(
        "% @expect sat\n"
        "% @query yes { reachable(x) }\n"
        "% @query no { blocked(y) }\n"
        "% @query yes { reachable(z) }\n"
    )
    shown = _shows(("reachable", 1), ("-reachable", 1), ("blocked", 1))
    with pytest.raises(DiscoveryError, match=r"^case\.lp:3: this @query reads -blocked/1,"):
        check_program(exp, _facts(shown=shown), "clingo", WHERE)


def test_binding_query_with_a_wrong_arity_contrary_is_loud() -> None:
    # The arity-aware closure on the highest-risk path (binding @query, via goal.arity): a goal
    # whose contrary is shown at the WRONG arity is unobservable, so it must be loud. reachable(X)
    # needs -reachable/1; a -reachable/2 (a typo) does not satisfy it.
    exp = parse("% @expect sat\n% @query unknown { reachable(X) } = { a }\n")
    shown = _shows(("reachable", 1), ("-reachable", 2))
    with pytest.raises(DiscoveryError, match=r"reads -reachable/1\b"):
        check_program(exp, _facts(shown=shown), "clingo", WHERE)
