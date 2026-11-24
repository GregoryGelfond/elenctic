import importlib
from dataclasses import replace
from pathlib import Path

import pytest
from clingo import Number, Symbol
from hypothesis import given, settings
from hypothesis import strategies as st

from elenctic import engine, failures
from elenctic.check import check
from elenctic.contract import Solver
from elenctic.determination import (
    AnswerSet,
    Consequences,
    Consistent,
    Inconclusive,
    Incumbent,
    Mode,
    NoAssumptions,
    Range,
    These,
    Truncation,
)
from elenctic.engine import ground
from elenctic.explanation import (
    Aggregate,
    Blocked,
    Chosen,
    Counterexample,
    Derived,
    Explanation,
    Fact,
    Minimality,
    Node,
    NoRule,
    NotChosen,
    Outranked,
    TheoryAtom,
    Unexpanded,
    Unexplained,
    Unsupported,
)
from elenctic.literals import Assumption, Literal
from elenctic.patterns import Pattern
from elenctic.program import Fault, Program
from elenctic.query import All, Answer, Answered, Any, Bindings, Not, Truth, Unreached, evaluate
from elenctic.search import KEEP_SHOWN, Interrupt, Limit, Limits
from elenctic.session import Session, evidenced, session
from elenctic.terms import Variable
from elenctic.verdicts import Ended, Finding, Report, Verdict

EXAMPLES = Path(__file__).parent.parent / "docs" / "examples"


def explained(
    text: str, *, limits: Limits = Limits(), max_depth: int | Limit = Limit.UNBOUNDED
) -> Report:
    program = Program(text, "t.lp")
    report = check(program, limits=limits)
    assert isinstance(report, Report), report
    found = evidenced(report, program, limits=limits, max_depth=max_depth)
    assert isinstance(found, Report), found
    return found


def example(name: str, *, max_depth: int | Limit = Limit.UNBOUNDED) -> Report:
    program = Program.read(EXAMPLES / name)
    report = check(program)
    assert isinstance(report, Report), report
    found = evidenced(report, program, max_depth=max_depth)
    assert isinstance(found, Report), found
    return found


def failed(report: Report) -> Finding:
    (only,) = [f for f in report.findings if f.verdict is Verdict.FAIL]
    return only


def explanation(report: Report) -> Explanation:
    evidence = failed(report).evidence
    assert isinstance(evidence, Explanation), evidence
    return evidence


def nodes(found: Explanation) -> dict[str, Node]:
    return {node.handle: node for node in found.nodes}


def opened(text: str, solver: Solver = Solver.CLINGO) -> Session:
    made = session(Program(text, "t.lp"), solver)
    assert isinstance(made, Session), made
    return made


# The five examples, as the proposal measured them.


def test_chain_explains_each_root_by_a_well_founded_support_that_shares_a_node() -> None:
    found = explanation(example("chain.lp"))
    assert found.roots == ("1/reach(c)", "1/reach(d)")
    assert found.counterexample.read == 1
    by = nodes(found)
    assert by["1/reach(c)"].children == ("1/reach(b)", "1/open(b,c)")
    assert by["1/reach(d)"].children == ("1/reach(c)", "1/open(c,d)")
    derived = by["1/open(a,b)"].reason
    assert isinstance(derived, Derived)
    assert derived.instance == "open(a,b) :- edge(a,b), not closed(a,b)."
    assert derived.conditions == ("not closed(a,b)",)
    assert str(derived.substitution) == "{X=a, Y=b}"
    assert isinstance(by["1/reach(a)"].reason, Fact)
    assert [n.handle for n in found.nodes].count("1/reach(c)") == 1
    assert found.complete
    assert found.minimality is Minimality.NONE


def test_absent_explains_an_absence_by_the_literal_that_blocks_its_one_candidate() -> None:
    found = explanation(example("absent.lp"))
    by = nodes(found)
    assert found.roots == ("1/not access(ann,db)",)
    assert by["1/not access(ann,db)"].reason == Unsupported(1)
    (branch,) = by["1/not access(ann,db)"].children
    assert branch == "1/not access(ann,db)#r8(ann,db,admin)"
    blocked = by[branch].reason
    assert isinstance(blocked, Blocked)
    assert blocked.literal == "not suspended(ann)"
    assert blocked.instance == (
        "access(ann,db) :- role(ann,admin), permits(admin,db), not suspended(ann)."
    )
    assert blocked.rule.text == "access(U,R) :- role(U,X), permits(X,R), not suspended(U)."
    assert blocked.rule.span.start.line == 6
    assert by[branch].children == ("1/suspended(ann)",)


def test_team_explains_a_failed_aggregate_down_to_a_choice_not_made() -> None:
    found = explanation(example("team.lp"))
    by = nodes(found)
    assert found.counterexample.index == 1
    assert found.counterexample.read is None
    aggregate = by["1/not 2 = #count { P: team(P), senior(P) }"]
    assert isinstance(aggregate.reason, Aggregate)
    assert (aggregate.reason.value, aggregate.reason.guard) == (1, "= 2")
    assert aggregate.children == ("1/team(dee)", "1/senior(dee)", "1/not team(ann)")
    chosen = by["1/team(dee)"].reason
    assert isinstance(chosen, Chosen)
    assert (chosen.lower, chosen.upper, chosen.chosen) == (2, 3, 2)
    (branch,) = by["1/not team(ann)"].children
    not_chosen = by[branch].reason
    assert isinstance(not_chosen, NotChosen)
    assert not_chosen.instance == "2 <= { team(ann): cand(ann); … } <= 3."


def test_late_explains_a_presence_through_a_theory_atom_and_its_assignment() -> None:
    pytest.importorskip("clingcon")
    found = explanation(example("late.lp"))
    by = nodes(found)
    assert found.counterexample.index == 11
    assert found.counterexample.read == 28
    assert found.roots == ("11/late",)
    theory = by["11/&sum { s2 } >= 7"]
    assert theory.holds
    assert isinstance(theory.reason, TheoryAtom)
    assert {(str(v.variable), v.value) for v in theory.reason.assignment} == {("s2", 7)}


def test_laptop_is_outranked_with_the_costs_and_the_weak_constraints_paid_differently() -> None:
    evidence = failed(example("laptop.lp")).evidence
    assert isinstance(evidence, Outranked)
    assert evidence.priorities == (2, 1)
    assert (evidence.optimum, evidence.assuming, evidence.priority) == ((0, 230), (0, 380), 1)
    (only_optimum,) = evidence.optimum_only
    (only_assuming,) = evidence.assuming_only
    assert (only_optimum.weight, only_optimum.priority) == (150, 1)
    assert only_optimum.rule.text == "150@1,ram : ram(16)"
    assert (only_optimum.rule.span.start.line, only_optimum.rule.span.start.column) == (7, 13)
    assert only_assuming.rule.text == "300@1,ram : ram(32)"
    assert (only_assuming.rule.span.start.column, only_assuming.rule.span.end.column) == (34, 53)
    by = nodes(evidence.explanation)
    (branch,) = by["1/not ram(32)"].children
    assert isinstance(by[branch].reason, NotChosen)


def test_each_example_is_explained_the_same_way_twice() -> None:
    first = example("team.lp")
    assert example("team.lp") == first


# The claims and their counterexamples.


def test_a_claim_that_holds_has_no_evidence() -> None:
    report = explained("p.\n% @expect sat\n% @cautious { p }\n")
    assert all(f.evidence is None for f in report.findings)


def test_a_failed_expect_sat_has_the_refutation_as_evidence() -> None:
    report = explained("p. :- p.\n% @expect sat\n")
    assert failed(report).evidence == NoAssumptions()


def test_a_failed_expect_sat_under_assumptions_has_the_clashing_ones() -> None:
    report = explained("{ p; q }. :- p, q.\n% @expect sat assuming { p, q }\n")
    evidence = failed(report).evidence
    assert isinstance(evidence, These)
    assert evidence.core == {Assumption(Literal("p")), Assumption(Literal("q"))}


def test_a_failed_expect_unsat_has_an_answer_set_and_nothing_to_explain() -> None:
    found = explanation(explained("p.\n% @expect unsat\n"))
    assert found.roots == ()
    assert found.nodes == ()
    assert found.counterexample.answer_set.atoms == {Literal("p")}


def test_a_failed_brave_claim_explains_the_absence_in_the_first_answer_set() -> None:
    found = explanation(explained("{ p }. q :- p, r.\n% @expect sat\n% @brave { q }\n"))
    assert found.roots == ("1/not q",)
    assert found.counterexample.read is None
    first = opened("{ p }. q :- p, r.").solve(frozenset())
    assert isinstance(first, Consistent)
    assert found.counterexample.answer_set == first.evidence.first


def test_a_failed_query_yes_prefers_an_answer_set_where_the_contrary_holds() -> None:
    text = "{ a }. -p :- a. p :- not a.\n% @expect sat\n% @query yes { p }\n"
    found = explanation(explained(text))
    (root,) = found.roots
    assert root.endswith("/-p")
    assert nodes(found)[root].holds


def test_a_failed_query_yes_with_no_contrary_explains_the_absence() -> None:
    found = explanation(explained("{ p }.\n% @expect sat\n% @query yes { p }\n"))
    (root,) = found.roots
    assert root.endswith("/not p")


def test_a_failed_query_no_unknown_explains_where_the_literal_holds() -> None:
    found = explanation(explained("{ p }.\n% @expect sat\n% @query no { p }\n"))
    (root,) = found.roots
    assert root.endswith("/p")


def test_a_claim_whose_kind_has_no_evidence_yet_has_none() -> None:
    report = explained("{ p }.\n% @expect sat\n% @count 3\n")
    assert failed(report).evidence is None


def test_an_interrupted_explanation_says_the_search_ended() -> None:
    program = Program("{ p }.\n% @expect sat\n% @cautious { p }\n", "t.lp")
    report = check(program)
    assert isinstance(report, Report)
    interrupt = Interrupt()
    interrupt.pull()
    found = evidenced(report, program, interrupt=interrupt)
    assert isinstance(found, Report)
    assert failed(found).evidence == Ended(Truncation.INTERRUPTED)


def test_a_report_without_a_failure_is_returned_as_it_is() -> None:
    program = Program("p.\n% @expect sat\n", "t.lp")
    report = check(program)
    assert isinstance(report, Report)
    assert evidenced(report, program) is report


def test_a_program_that_cannot_be_grounded_is_a_fault() -> None:
    assert isinstance(session(Program("p(X) :- q.", "t.lp")), Fault)


# Absence and presence.


def test_an_atom_no_rule_can_derive_has_no_rule() -> None:
    found = explanation(explained("p :- q.\n% @expect sat\n% @cautious { r }\n"))
    assert nodes(found)["1/not r"].reason == NoRule()


def test_an_instance_whose_body_can_never_hold_is_no_candidate() -> None:
    found = explanation(explained("p :- q.\n% @expect sat\n% @cautious { p }\n"))
    assert nodes(found)["1/not p"].reason == NoRule()


def test_an_unfounded_loop_is_explained_through_its_absences_once_each() -> None:
    text = "{ c }. a :- b. b :- a. b :- c.\n% @expect sat\n% @cautious { a }\n"
    found = explanation(explained(text))
    by = nodes(found)
    assert by["1/not a"].children == ("1/not a#r2",)
    assert by["1/not a#r2"].children == ("1/not b",)
    assert by["1/not b"].children == ("1/not b#r3", "1/not b#r4")
    assert by["1/not b#r3"].children == ("1/not a",)
    assert isinstance(by["1/not c#r1"].reason, NotChosen)
    assert [n.handle for n in found.nodes].count("1/not a") == 1


def test_max_depth_bounds_the_absences_and_makes_the_explanation_incomplete() -> None:
    text = "{ d }. c :- d. b :- c. a :- b.\n% @expect sat\n% @cautious { a }\n"
    found = explanation(explained(text, max_depth=2))
    assert not found.complete
    assert nodes(found)["1/not c"].reason == Unexpanded(2)
    assert explanation(explained(text, max_depth=Limit.UNBOUNDED)).complete


def test_a_negative_depth_is_refused() -> None:
    opening = opened("p.")
    answer_set = AnswerSet(frozenset({Literal("p")}), frozenset({Literal("p")}))
    with pytest.raises(ValueError, match="never negative"):
        opening.explain([Literal("p")], Counterexample(answer_set, 1, 1), max_depth=-1)


def test_an_answer_set_from_elsewhere_is_explained_from_its_atoms() -> None:
    opening = opened("q. p :- q.")
    answer_set = AnswerSet(frozenset({Literal("p"), Literal("q")}), frozenset())
    found = opening.explain([Literal("p")], Counterexample(answer_set, 1, None))
    assert [n.handle for n in found.nodes] == ["1/p", "1/q"]


def test_an_answer_set_from_elsewhere_is_refused_when_theory_atoms_must_be_read() -> None:
    pytest.importorskip("clingcon")
    opening = opened("&dom { 0..1 } = x. p :- &sum { x } >= 1.", Solver.CLINGCON)
    answer_set = AnswerSet(frozenset(), frozenset())
    with pytest.raises(ValueError, match="theory atoms"):
        opening.explain([Literal("p")], Counterexample(answer_set, 1, None))


def test_a_rule_with_a_construct_no_reason_covers_is_unexplained() -> None:
    opening = opened("q(1). q(2). p :- #min { X: q(X) } = 1.")
    answer_set = AnswerSet(
        frozenset({Literal("p"), Literal("q", (_n(1),)), Literal("q", (_n(2),))}), frozenset()
    )
    found = opening.explain([Literal("p")], Counterexample(answer_set, 1, None))
    (only,) = found.nodes
    assert isinstance(only.reason, Unexplained)
    assert only.reason.rule is not None


def test_two_instances_of_one_rule_are_two_branches() -> None:
    text = "q(1). r(2). { q(2); r(1) } 0. p :- q(X), r(X).\n% @expect sat\n% @cautious { p }\n"
    found = explanation(explained(text))
    by = nodes(found)
    assert by["1/not p"].reason == Unsupported(2)
    assert by["1/not p"].children == ("1/not p#r4(1)", "1/not p#r4(2)")
    literals = [by[h].reason for h in by["1/not p"].children]
    assert [b.literal for b in literals if isinstance(b, Blocked)] == ["r(1)", "q(2)"]


def test_a_pool_is_read_as_one_rule_per_piece() -> None:
    text = "{ q(1..2) } 0. p :- q(1;2).\n% @expect sat\n% @cautious { p }\n"
    found = explanation(explained(text))
    assert nodes(found)["1/not p"].reason == Unsupported(2)


def test_the_names_the_explanation_adds_are_kept_apart_from_the_program_s() -> None:
    text = "{ _elenctic_rule(2) } 0. p :- _elenctic_rule(2).\n% @expect sat\n% @cautious { p }\n"
    found = explanation(explained(text))
    by = nodes(found)
    (branch,) = by["1/not p"].children
    blocked = by[branch].reason
    assert isinstance(blocked, Blocked)
    assert blocked.literal == "_elenctic_rule(2)"
    assert all("__elenctic" not in str(a) for a in found.counterexample.answer_set.atoms)


def test_the_session_does_not_change_the_answer_sets() -> None:
    text = "{ a; b; c }. :- a, b. d :- c, not a. #minimize { 1,x: a }."
    opening = opened(text)
    grounded_alone = opened("{ a; b; c }. :- a, b. d :- c, not a.")
    assert len(opening.solve().evidence.all) == len(grounded_alone.solve().evidence.all) == 6  # type: ignore[union-attr]


def test_clingcon_answer_sets_are_not_split_by_the_atoms_the_session_records() -> None:
    pytest.importorskip("clingcon")
    late = (EXAMPLES / "late.lp").read_text()
    plain = ground(Program(late, "late.lp"), Solver.CLINGCON)
    assert not isinstance(plain, Fault)
    opening = opened(late, Solver.CLINGCON)
    assert len(opening.solve().evidence.all) == len(plain.solve().evidence.all)  # type: ignore[union-attr]


def _n(value: int) -> Symbol:
    return Number(value)


# Outranked.


def test_outrank_is_none_when_no_answer_set_holds_the_literals() -> None:
    opening = opened("{ a; b }. :- a. #minimize { 1: b }.")
    assert opening.outrank(frozenset({Literal("a")})) is None


def test_outrank_is_none_when_the_best_answer_set_holding_them_is_optimal() -> None:
    opening = opened("{ a; b }. #minimize { 1: b }.")
    assert opening.outrank(frozenset({Literal("a")})) is None


def test_outrank_names_the_weak_constraint_instances_and_their_substitution() -> None:
    opening = opened("{ p(1..2) }. :~ p(X). [X@3,X]")
    ranked = opening.outrank(frozenset({Literal("p", (_n(2),))}))
    assert isinstance(ranked, Outranked)
    assert (ranked.priorities, ranked.optimum, ranked.assuming, ranked.priority) == (
        (3,),
        (0,),
        (2,),
        3,
    )
    assert ranked.optimum_only == ()
    (paid,) = ranked.assuming_only
    assert (paid.weight, str(paid.substitution), paid.rule.text) == (2, "{X=2}", ":~ p(X). [X@3,X]")


def test_outrank_under_an_interrupt_says_the_search_ended() -> None:
    made = session(Program("{ a }. #minimize { 1: a }.", "t.lp"), interrupt=Interrupt())
    assert isinstance(made, Session)
    assert made.interrupt is not None
    made.interrupt.pull()
    assert made.outrank(frozenset({Literal("a")})) == Ended(Truncation.INTERRUPTED)


def test_a_cautious_optimal_claim_the_optimum_ties_is_explained_in_the_optimum() -> None:
    text = "1 { a; b } 1. #minimize { 0: a }.\n% @expect sat\n% @cautious optimal { a }\n"
    evidence = failed(explained(text)).evidence
    assert isinstance(evidence, Explanation)
    assert evidence.roots == (f"{evidence.counterexample.index}/not a",)


def test_an_outranked_claim_is_explained_no_deeper_than_asked() -> None:
    made, findings = judged(
        "{ a }. #minimize { 1: a }.\n% @expect sat\n% @cautious optimal { a }\n"
    )
    evidence = made.evidence(findings[1], max_depth=0)
    assert isinstance(evidence, Outranked)
    assert evidence.explanation.max_depth == 0
    assert not evidence.explanation.complete


def test_each_fact_an_interval_writes_is_supported_by_it() -> None:
    by = why("p(1..3). q :- p(X).", [Literal("p", (_n(2),)), Literal("q")])
    fact = by["1/p(2)"].reason
    assert isinstance(fact, Fact)
    assert fact.rule.text == "p(1..3)."
    assert by["1/q"].children == ("1/p(1)",)


def test_a_variable_with_leading_underscores_is_one_of_the_rule_s_own() -> None:
    derived = why("q(1). p(__X) :- q(__X).", [Literal("p", (_n(1),))])["1/p(1)"].reason
    assert isinstance(derived, Derived)
    assert str(derived.substitution) == "{__X=1}"


def test_an_anonymous_variable_is_named_apart_from_every_variable_written() -> None:
    derived = why("q(1,2). p(__A1) :- q(__A1, _).", [Literal("p", (_n(1),))])["1/p(1)"].reason
    assert isinstance(derived, Derived)
    assert derived.instance == "p(1) :- q(1,2)."


def test_an_element_s_variables_are_named_apart_from_every_variable_written() -> None:
    text = "q(1). r(1). r(2). t(__LX) :- q(__LX), #count { X : r(X), X != __LX } = 1."
    by = why(text, [Literal("t", (_n(1),))])
    assert isinstance(by["1/t(1)"].reason, Derived)
    counted = by["1/1 = #count { X: r(X), X != 1 }"].reason
    assert isinstance(counted, Aggregate)
    assert counted.value == 1


def test_each_anonymous_variable_is_named_apart_from_the_others() -> None:
    derived = why("q(1,2). p :- q(_, _).", [Literal("p")])["1/p"].reason
    assert isinstance(derived, Derived)
    assert derived.instance == "p :- q(1,2)."


def test_a_negated_literal_no_reason_covers_is_left_out_of_the_relaxation() -> None:
    by = why("q(1). p :- not #min { X: q(X) } = 1.", [Literal("p")])
    assert by["1/not p"].reason == Unsupported(1)
    assert isinstance(by["1/not p#r2"].reason, Unexplained)
    assert not by["1/not p#r2"].holds


def test_a_negated_aggregate_holds_where_the_aggregate_does_not() -> None:
    by = why("q(1). p :- not #count { X: q(X) } > 1.", [Literal("p")])
    assert isinstance(by["1/p"].reason, Derived)
    assert by["1/p"].children == ("1/not 1 < #count { X: q(X) }",)


def test_a_negated_theory_atom_holds_where_the_atom_does_not() -> None:
    pytest.importorskip("clingcon")
    text = "&dom { 0..0 } = x. p :- not &sum { x } >= 1."
    by = why(text, [Literal("p")], solver=Solver.CLINGCON)
    assert isinstance(by["1/p"].reason, Derived)
    assert not by["1/not &sum { x } >= 1"].holds


def test_an_element_counts_where_its_negated_condition_holds() -> None:
    by = why("q(1..3). r(3). p :- #count { X: q(X), not r(X) } = 2.", [Literal("p")])
    counted = by["1/2 = #count { X: q(X), not r(X) }"]
    assert isinstance(counted.reason, Aggregate)
    assert counted.reason.value == 2
    assert counted.children == ("1/q(1)", "1/q(2)")


def test_a_sum_leaves_out_the_elements_whose_weight_is_not_a_number() -> None:
    by = why("q. p :- #sum { 1: q; a: q } = 1.", [Literal("p")])
    counted = by["1/1 = #sum { 1: q; a: q }"].reason
    assert isinstance(counted, Aggregate)
    assert counted.value == 1


def test_an_atom_no_reason_covers_still_holds() -> None:
    node = why("q(1). r(1). p :- q(X): r(X).", [Literal("p")])["1/p"]
    assert node.holds
    assert isinstance(node.reason, Unexplained)


def test_a_negated_head_literal_derives_nothing() -> None:
    assert why("r. p ; not q :- r.", [Literal("q")])["1/not q"].reason == NoRule()
    assert why("{ a; not b }.", [Literal("b")])["1/not b"].reason == NoRule()


def test_instances_of_one_rule_with_the_same_values_are_told_apart() -> None:
    by = why("{ q(1..2) }. p :- q(1;2).", [Literal("p")])
    assert by["1/not p"].reason == Unsupported(2)
    assert by["1/not p"].children == ("1/not p#r2", "1/not p#r2.1")


def test_the_instances_of_a_rule_are_ordered_as_the_text_of_their_values() -> None:
    """Spelled a symbol at a time, a rule's values still order as their tuple's text."""
    values = '1;10;12;-3;"a";"a)";"x\\"";a;ab;a(1);-a;(1,b);();#inf;#sup'
    text = f"v({values}). {{ q(X): v(X) }}. :- q(X). p :- v(X), v(Y), q(X), q(Y). r :- v(X), q(X)."
    by = why(text, [Literal("p"), Literal("r")])
    for root, count in (("1/not p", 15 * 15), ("1/not r", 15)):
        found = []
        for child in by[root].children:
            reason = by[child].reason
            assert isinstance(reason, Blocked)
            found.append(tuple(reason.substitution.bindings.values()))
        assert len(found) == count
        assert found == sorted(found, key=str)


def test_reading_instances_spells_each_value_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A symbol is spelled in Python, a part at a time: 900 instances of 30 values spell 30."""
    spelled: list[Symbol] = []
    plain = Symbol.__repr__

    def spelling(symbol: Symbol) -> str:
        spelled.append(symbol)
        return plain(symbol)

    monkeypatch.setattr(Symbol, "__repr__", spelling)
    opened("n(101..130). p(X,Y) :- n(X), n(Y).")
    assert len(spelled) == len(set(spelled)) <= 30


def test_a_rule_written_over_lines_keeps_its_text_up_to_its_end() -> None:
    derived = why("q. p :-\n  q. r.", [Literal("p")])["1/p"].reason
    assert isinstance(derived, Derived)
    assert derived.rule.text == "p :-\n  q."


def test_an_aggregate_s_missing_atoms_are_one_absence_below_its_rule() -> None:
    text = "r(1). { s(1) }. q(X) :- r(X), s(X). p :- #count { X: q(X) } >= 1."
    assert why(text, [Literal("p")], max_depth=1)["1/not q(1)"].reason == Unexpanded(1)
    assert why(text, [Literal("p")], max_depth=2)["1/not s(1)"].reason == Unexpanded(2)


def test_a_weak_constraint_whose_weight_is_not_a_number_is_paid_by_no_answer_set() -> None:
    ranked = opened("{ p }. :~ p. [a@1] :~ p. [1@1]").outrank(frozenset({Literal("p")}))
    assert isinstance(ranked, Outranked)
    assert [paid.rule.text for paid in ranked.assuming_only] == [":~ p. [1@1]"]


def test_the_weak_constraints_paid_differently_are_listed_highest_priority_first() -> None:
    text = "{ p }. :~ p. [1@1] :~ p. [1@3]"
    ranked = opened(text).outrank(frozenset({Literal("p")}))
    assert isinstance(ranked, Outranked)
    assert [paid.priority for paid in ranked.assuming_only] == [3, 1]


def test_each_minimize_element_starts_where_it_is_written_to_the_last_line() -> None:
    text = "1 { a; b } 1.\n#minimize { 1@1 : a;\n  2@1 : b }."
    ranked = opened(text).outrank(frozenset({Literal("b")}))
    assert isinstance(ranked, Outranked)
    ((only_optimum,), (only_assuming,)) = ranked.optimum_only, ranked.assuming_only
    assert (only_optimum.rule.span.start.line, only_optimum.rule.span.start.column) == (2, 13)
    assert (only_assuming.rule.span.start.line, only_assuming.rule.span.start.column) == (3, 3)
    assert only_assuming.rule.text == "2@1 : b"


def test_an_answer_set_found_keeping_only_its_shown_atoms_is_explained_from_all_of_them() -> None:
    opening = opened("q. p :- q. #show p/0.")
    found = opening.solve(frozenset(), keep=KEEP_SHOWN)
    assert isinstance(found, Consistent)
    first = found.evidence.first
    assert first.atoms == frozenset()
    by = nodes(opening.explain([Literal("p")], Counterexample(first, 1, None)))
    assert by["1/p"].children == ("1/q",)


def test_a_failed_expect_unsat_is_explained_in_the_first_answer_set() -> None:
    found = explanation(explained("{ p }.\n% @expect unsat\n"))
    assert found.counterexample.index == 1
    assert found.roots == ()


session_module = importlib.import_module("elenctic.session")
"""The module, which the package's `session` function hides."""


# Findings the session did not judge, and searches cut short: `evidence` takes any finding.


def judged(
    text: str,
    *,
    on: str | None = None,
    limits: Limits = Limits(),
    interrupt: Interrupt | None = None,
) -> tuple[Session, list[Finding]]:
    """Open a session on `on` (or `text`), with every finding of a check on `text` marked failed."""
    report = check(Program(text, "t.lp"))
    assert isinstance(report, Report), report
    program = Program(text if on is None else on, "t.lp")
    made = session(program, limits=limits, interrupt=interrupt)
    assert isinstance(made, Session), made
    return made, [replace(f, verdict=Verdict.FAIL) for f in report.findings]


def test_a_finding_that_did_not_fail_has_no_evidence() -> None:
    made, findings = judged("p.\n% @expect sat\n% @cautious { p }\n")
    assert all(made.evidence(replace(f, verdict=Verdict.PASS)) is None for f in findings)


def test_a_claim_with_no_answer_set_to_show_has_no_evidence() -> None:
    text = (
        "{ p }.\n#minimize { 1: p }.\n% @expect sat\n"
        "% @brave { p }\n% @cautious optimal { p }\n% @query yes { p }\n"
    )
    made, findings = judged(text, on="{ p }. :- p. :- not p. #minimize { 1: p }.")
    assert [made.evidence(f) for f in findings[1:]] == [None, None, None]
    made, findings = judged("p. :- p.\n% @expect unsat\n")
    assert made.evidence(findings[0]) is None


def test_a_claim_that_holds_after_all_has_no_evidence() -> None:
    text = (
        "{ p }. q.\n% @expect sat\n% @cautious { q }\n% @query yes { q }\n% @query unknown { p }\n"
    )
    made, findings = judged(text)
    assert [made.evidence(f) for f in findings[1:]] == [None, None, None]


def test_a_brave_claim_is_explained_without_reading_every_answer_set() -> None:
    """The brave consequences name what no answer set has; one answer set shows it absent."""
    made, findings = judged(
        "{ p; q }.\n% @expect sat\n% @brave { r }\n", limits=Limits(max_answer_sets=1)
    )
    evidence = made.evidence(findings[1])
    assert isinstance(evidence, Explanation)
    assert evidence.roots == ("1/not r",)


@pytest.mark.parametrize(
    "cut",
    [
        Consistent(Consequences(Mode.BRAVE, frozenset()), Truncation.MAX_SECONDS),
        Inconclusive(Truncation.MAX_SECONDS),
    ],
)
def test_a_brave_claim_whose_consequences_the_search_did_not_finish_ends_the_search(
    monkeypatch: pytest.MonkeyPatch, cut: object
) -> None:
    made, findings = judged("{ p }.\n% @expect sat\n% @brave { r }\n")
    monkeypatch.setattr(Session, "consequences", lambda *_args, **_kwargs: cut)
    assert made.evidence(findings[1]) == Ended(Truncation.MAX_SECONDS)


def test_an_interrupt_ends_the_search_for_each_kind_of_claim() -> None:
    text = "{ p }.\n#minimize { 1: p }.\n% @expect sat\n"
    text += "% @cautious optimal { p }\n% @query yes { p }\n"
    interrupt = Interrupt()
    made, findings = judged(text, interrupt=interrupt)
    unsat, unsat_findings = judged("{ p }.\n% @expect unsat\n", interrupt=interrupt)
    interrupt.pull()
    ended = Ended(Truncation.INTERRUPTED)
    assert [made.evidence(f) for f in findings[1:]] == [ended, ended]
    assert unsat.evidence(unsat_findings[0]) == ended


def test_an_optimum_the_search_did_not_prove_ends_the_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made, findings = judged(
        "{ p }.\n#minimize { 1: p }.\n% @expect sat\n% @cautious optimal { p }\n"
    )
    incumbent = AnswerSet(frozenset(), frozenset(), cost=(0,))
    cut = Consistent(Incumbent(incumbent), Truncation.MAX_SECONDS)
    monkeypatch.setattr(Session, "optimize", lambda *_args, **_kwargs: cut)
    unproven = Ended(Truncation.MAX_SECONDS, optimum_unproven=True)
    assert made.evidence(findings[1]) == unproven
    assert made.outrank(frozenset({Literal("p")})) == unproven


def test_a_query_is_kept_from_its_answer_by_its_closed_patterns_and_not_its_open_ones() -> None:
    closed = Pattern("p", (_n(1),))
    query = All((closed, Pattern("q", (Variable("X"),)), Not(closed)))
    assert failures.roots(query, frozenset(), Answer.YES) == [Literal("p", (_n(1),))]


def test_not_is_kept_from_yes_by_its_literal_holding_and_from_no_by_its_absence() -> None:
    p, q = Literal("p"), Literal("q")
    assert failures.roots(All((Not(p), Not(q))), frozenset({p}), Answer.YES) == [p]
    assert failures.roots(All((Not(p), Not(q))), frozenset({p}), Answer.NO) == [q]


def test_a_no_query_is_not_kept_from_its_answer_by_a_literal_whose_contrary_holds() -> None:
    p = Literal("p")
    assert failures.roots(All((p,)), frozenset({p.contrary}), Answer.NO) == []
    assert failures.roots(All((p,)), frozenset({p}), Answer.NO) == [p]


def test_a_session_on_a_program_read_by_no_one_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    unread = engine.controlled
    monkeypatch.setattr(
        session_module, "controlled", lambda program, solver, _extend: unread(program, solver)
    )
    with pytest.raises(AssertionError, match="without being read"):
        session(Program("p.", "t.lp"))


def test_a_report_whose_program_cannot_be_opened_is_a_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = Program("p.\n% @expect unsat\n", "t.lp")
    report = check(program)
    assert isinstance(report, Report)
    refused = session(Program("p(X) :- q.", "t.lp"))
    assert isinstance(refused, Fault)
    monkeypatch.setattr(session_module, "session", lambda *_args, **_kwargs: refused)
    assert evidenced(report, program) is refused


# Each kind of literal, in the answer set the scenario picks.


def why(
    text: str,
    roots: list[Literal],
    scenario: frozenset[Assumption] = frozenset(),
    solver: Solver = Solver.CLINGO,
    max_depth: int | Limit = Limit.UNBOUNDED,
) -> dict[str, Node]:
    """Explain `roots` in the first answer set of `text` under `scenario`."""
    opening = opened(text, solver)
    found = opening.solve(scenario)
    assert isinstance(found, Consistent), found
    first = found.evidence.first
    return nodes(opening.explain(roots, Counterexample(first, 1, None), max_depth=max_depth))


def q(value: int) -> Literal:
    return Literal("q", (_n(value),))


def test_a_comparison_in_a_body_is_a_condition_of_the_derivation() -> None:
    by = why("q(1..3). p(X) :- q(X), X < 3.", [Literal("p", (_n(1),))])
    derived = by["1/p(1)"].reason
    assert isinstance(derived, Derived)
    assert derived.conditions == ("1 < 3",)


def test_a_comparison_in_a_choice_element_is_part_of_its_instance() -> None:
    p1 = Literal("p", (_n(1),))
    by = why("q(1..2). { p(X): q(X), X < 2 }.", [p1], frozenset({Assumption(p1)}))
    chosen = by["1/p(1)"].reason
    assert isinstance(chosen, Chosen)
    assert chosen.instance == "{ p(1): q(1), 1 < 2 }."
    assert by["1/p(1)"].children == ("1/q(1)",)


def test_an_atom_is_supported_by_a_rule_whose_body_holds_not_one_whose_condition_fails() -> None:
    no_q = frozenset({Assumption(Literal("p")), Assumption(Literal("q"), holds=False)})
    by = why("{ q }. r. { p: q }. p :- r.", [Literal("p")], no_q)
    derived = by["1/p"].reason
    assert isinstance(derived, Derived)
    assert derived.instance == "p :- r."


def test_an_aggregate_that_holds_is_supported_by_the_atoms_it_counts() -> None:
    by = why("q(1..2). p :- #count { X: q(X) } >= 1.", [Literal("p")])
    node = by["1/1 <= #count { X: q(X) }"]
    assert node.holds
    assert node.children == ("1/q(1)", "1/q(2)")


@pytest.mark.parametrize(
    ("body", "value", "guard"),
    [
        ("#sum { X: q(X) } = 6", 6, "= 6"),
        ("#sum+ { X: q(X) } > 5", 6, "> 5"),
        ("#count { X: q(X) } != 2", 3, "!= 2"),
        ("#count { X: q(X) } < 4", 3, "< 4"),
        ("#count { X: q(X) } <= 3", 3, "<= 3"),
        ("#sum { -X: q(X) } >= -6", -6, ">= -6"),
    ],
)
def test_an_aggregate_is_valued_and_compared_as_written(body: str, value: int, guard: str) -> None:
    by = why(f"q(1..3). p :- {body}.", [Literal("p")])
    (aggregate,) = [n.reason for n in by.values() if isinstance(n.reason, Aggregate)]
    assert (aggregate.value, aggregate.guard) == (value, guard)


def test_an_absent_atom_whose_rule_no_reason_covers_is_unexplained() -> None:
    by = why(
        "{ q(1..2) }. p :- #min { X: q(X) } = 1.",
        [Literal("p")],
        frozenset({Assumption(q(1), holds=False)}),
    )
    assert isinstance(by["1/not p#r2"].reason, Unexplained)
    assert not by["1/not p#r2"].holds


def test_an_absent_atom_whose_body_holds_in_an_answer_set_from_elsewhere_is_unexplained() -> None:
    opening = opened("q. p :- q.")
    answer_set = AnswerSet(frozenset({Literal("q")}), frozenset())
    found = opening.explain([Literal("p")], Counterexample(answer_set, 1, None))
    assert isinstance(nodes(found)["1/not p#r2"].reason, Unexplained)


def test_an_absent_choice_element_is_blocked_by_its_condition() -> None:
    p1 = Literal("p", (_n(1),))
    by = why("{ q(1) }. r. { p(X): q(X) } :- r.", [p1], frozenset({Assumption(q(1), holds=False)}))
    blocked = by["1/not p(1)#r3(1)"].reason
    assert isinstance(blocked, Blocked)
    assert blocked.literal == "q(1)"


def test_a_missing_element_is_explained_by_the_first_condition_that_fails() -> None:
    none = frozenset({Assumption(q(i), holds=False) for i in (1, 2, 3)})
    by = why("{ q(1..3) }. r(1..3). s :- #count { X: r(X), q(X) } >= 1.", [Literal("s")], none)
    assert by["1/not 1 <= #count { X: r(X), q(X) }"].children == (
        "1/not q(1)",
        "1/not q(2)",
        "1/not q(3)",
    )


def test_a_disjunction_is_written_with_its_other_elements_elided() -> None:
    by = why("p ; q.", [Literal("p"), Literal("q")], frozenset({Assumption(Literal("p"))}))
    chosen = by["1/p"].reason
    assert isinstance(chosen, Chosen)
    assert chosen.instance == "p; …."
    assert isinstance(by["1/not q#r1"].reason, NotChosen)


def test_a_choice_is_counted_against_its_bounds() -> None:
    by = why(
        "1 < { p(1..3) } < 3.",
        [Literal("p", (_n(1),))],
        frozenset({Assumption(Literal("p", (_n(2),))), Assumption(Literal("p", (_n(3),)))}),
    )
    not_chosen = by["1/not p(1)#r1"].reason
    assert isinstance(not_chosen, NotChosen)
    assert (not_chosen.lower, not_chosen.upper, not_chosen.chosen) == (2, 2, 2)


def test_a_bound_that_is_no_number_bounds_nothing() -> None:
    by = why("{ p } a.", [Literal("p")])
    not_chosen = by["1/not p#r1"].reason
    assert isinstance(not_chosen, NotChosen)
    assert (not_chosen.lower, not_chosen.upper) == (None, None)


def test_an_absence_blocked_by_a_theory_atom_ends_at_the_theory_atom() -> None:
    pytest.importorskip("clingcon")
    by = why("&dom { 0..1 } = x. p :- &sum { x } >= 2.", [Literal("p")], solver=Solver.CLINGCON)
    blocked = by["1/not p#r2"].reason
    assert isinstance(blocked, Blocked)
    assert blocked.literal == "&sum { x } >= 2"
    theory = by["1/not &sum { x } >= 2"]
    assert isinstance(theory.reason, TheoryAtom)
    assert not theory.holds


# Constructs as the rules are read.


def test_an_anonymous_variable_grounds_to_the_term_it_stands_in_for() -> None:
    derived = why("q(1). p :- q(_).", [Literal("p")])["1/p"].reason
    assert isinstance(derived, Derived)
    assert derived.instance == "p :- q(1)."


def test_a_conditional_literal_in_a_body_is_no_reason_yet() -> None:
    by = why("q(1). r(1). p :- q(X): r(X).", [Literal("p")])
    assert isinstance(by["1/p"].reason, Unexplained)


def test_a_head_aggregate_is_no_reason_yet() -> None:
    by = why(
        "q(1..2). #count { X: s(X) : q(X) } = 1.",
        [Literal("s", (_n(1),)), Literal("s", (_n(2),))],
        frozenset({Assumption(Literal("s", (_n(2),)))}),
    )
    assert isinstance(by["1/s(2)"].reason, Unexplained)
    assert isinstance(by["1/not s(1)#r2"].reason, Unexplained)


def test_a_rule_written_over_lines_keeps_its_text() -> None:
    derived = why("q(1).\np :-\n  q(1).", [Literal("p")])["1/p"].reason
    assert isinstance(derived, Derived)
    assert (derived.rule.text, derived.instance) == ("p :-\n  q(1).", "p :- q(1).")


def test_a_disjunction_whose_other_elements_cannot_apply_is_written_alone() -> None:
    by = why("r. p ; q : s :- r.", [Literal("p")], frozenset({Assumption(Literal("p"))}))
    chosen = by["1/p"].reason
    assert isinstance(chosen, Chosen)
    assert chosen.instance == "p :- r."


# The answer set an explanation is about, by its index in the search.


def test_the_answer_set_at_an_index_is_the_one_the_search_reads_there() -> None:
    made = opened("{ a; b }.")
    found = made.solve(frozenset())
    assert isinstance(found, Consistent)
    third = made.counterexample(3)
    assert isinstance(third, Counterexample)
    assert third.answer_set == found.evidence.all[2]
    assert (third.index, third.read) == (3, None)


def test_there_is_no_answer_set_past_the_last() -> None:
    assert opened("{ a; b }.").counterexample(5) is None


def test_with_no_answer_set_at_all_the_refutation_says_why() -> None:
    assert opened("a. :- a.").counterexample() == NoAssumptions()
    clash = frozenset({Assumption(Literal("a")), Assumption(Literal("a"), holds=False)})
    refuted = opened("{ a }.").counterexample(1, clash, over=Range.OPTIMAL)
    assert isinstance(refuted, These)


def test_the_index_counts_the_answer_sets_of_the_scenario() -> None:
    made = opened("{ a; b }.")
    only = made.counterexample(
        1, frozenset({Assumption(Literal("a")), Assumption(Literal("b"), holds=False)})
    )
    assert isinstance(only, Counterexample)
    assert {str(s) for s in only.answer_set.atoms} == {"a"}
    assumed = frozenset({Assumption(Literal("a"))})
    assert made.counterexample(2, assumed) is not None
    assert made.counterexample(3, assumed) is None
    first = made.counterexample(1, assumed)
    assert isinstance(first, Counterexample)
    assert first.read == 2


def test_the_index_counts_the_optima_when_the_range_is_optimal() -> None:
    made = opened("1 { a; b; c } 1. #minimize { 1 : a; 1 : b; 2 : c }.")
    second = made.counterexample(2, over=Range.OPTIMAL)
    assert isinstance(second, Counterexample)
    assert second.read == 2
    assert {str(s) for s in second.answer_set.atoms} <= {"a", "b"}
    assert made.counterexample(3, over=Range.OPTIMAL) is None


def test_an_answer_set_beyond_a_truncated_search_is_not_known() -> None:
    made = session(Program("{ a; b; c }.", "t.lp"), limits=Limits(max_answer_sets=2))
    assert isinstance(made, Session)
    second = made.counterexample(2)
    assert isinstance(second, Counterexample)
    assert second.read is None
    assert made.counterexample(3) == Ended(Truncation.MAX_ANSWER_SETS)


def test_an_index_counts_from_one() -> None:
    with pytest.raises(ValueError, match="counts from 1"):
        opened("a.").counterexample(0)


# A query answered over the answer sets, and the first answer set giving each answer.


def _indices(made: Session, query: Literal) -> dict[Answer, int]:
    found = made.solve(frozenset())
    assert isinstance(found, Consistent)
    first: dict[Answer, int] = {}
    for at, answer_set in enumerate(found.evidence.all, 1):
        truth = evaluate(query, answer_set.atoms)
        first.setdefault(
            {Truth.TRUE: Answer.YES, Truth.FALSE: Answer.NO}.get(truth, Answer.UNKNOWN), at
        )
    return first


def test_a_query_is_answered_with_the_first_answer_set_taking_each_value() -> None:
    made = opened("{ a; b }.")
    answered = made.answer(All((Literal("a"),)))
    assert isinstance(answered, Answered)
    assert answered.answer is Answer.UNKNOWN
    assert answered.read is None
    expected = sorted(_indices(made, Literal("a")).items(), key=lambda pair: pair[1])
    assert [(t.answer, t.index) for t in answered.taken] == expected
    assert all(Literal("a") in t.answer_set.atoms for t in answered.taken if t.answer is Answer.YES)
    assert {t.answer for t in answered.taken} == {Answer.YES, Answer.UNKNOWN}


def test_a_contrary_in_every_answer_set_answers_no() -> None:
    answered = opened("-b.").answer(All((Literal("b"),)))
    assert isinstance(answered, Answered)
    assert answered.answer is Answer.NO
    assert [(t.answer, t.index) for t in answered.taken] == [(Answer.NO, 1)]


def test_a_conjunction_is_answered_as_the_query_tag_answers_it() -> None:
    answered = opened("a. { b }.").answer(All((Literal("a"), Literal("b"))))
    assert isinstance(answered, Answered)
    assert answered.answer is Answer.UNKNOWN
    assert len(answered.taken) == 2


def test_a_pattern_with_variables_is_answered_by_its_bindings() -> None:
    pattern = Pattern("p", (Variable("X"),))
    answered = opened("p(1). { p(2) }. -p(3).").answer(pattern)
    assert isinstance(answered, Answered)
    assert answered.answer == Bindings(
        frozenset({(Number(1),)}), frozenset({(Number(3),)}), frozenset({(Number(2),)})
    )
    assert answered.taken == ()


def test_a_query_over_the_optima_reads_only_them() -> None:
    made = opened("1 { a; b; c } 1. #minimize { 1 : a; 1 : b; 2 : c }.")
    answered = made.answer(All((Literal("c"),)), over=Range.OPTIMAL)
    assert isinstance(answered, Answered)
    assert (answered.answer, answered.read, answered.over) == (Answer.UNKNOWN, 2, Range.OPTIMAL)
    assert {t.answer for t in answered.taken} == {Answer.UNKNOWN}


def test_a_query_under_a_scenario_reads_its_answer_sets() -> None:
    scenario = frozenset({Assumption(Literal("a"))})
    answered = opened("{ a; b }.").answer(All((Literal("a"),)), scenario)
    assert isinstance(answered, Answered)
    assert (answered.answer, answered.read) == (Answer.YES, None)


def test_a_query_without_answer_sets_gets_the_refutation() -> None:
    assert opened("a. :- a.").answer(All((Literal("a"),))) == NoAssumptions()


def test_a_query_whose_search_is_truncated_is_not_answered() -> None:
    made = session(Program("{ a; b }.", "t.lp"), limits=Limits(max_answer_sets=1))
    assert isinstance(made, Session)
    assert made.answer(All((Literal("a"), Literal("b")))) == Ended(Truncation.MAX_ANSWER_SETS)


def test_a_literal_truncated_is_answered_with_the_answers_it_did_not_reach() -> None:
    """Its answer is known before the search reads; the answer sets it did not reach go unnamed."""
    made = session(Program("{ a; b }.", "t.lp"), limits=Limits(max_answer_sets=1))
    assert isinstance(made, Session)
    answered = made.answer(All((Literal("a"),)))
    assert isinstance(answered, Answered)
    assert (answered.answer, answered.read) == (Answer.UNKNOWN, None)
    ((first,),) = (answered.taken,)
    assert answered.unreached == (
        Unreached(
            ({Answer.YES, Answer.UNKNOWN} - {first.answer}).pop(), 1, Truncation.MAX_ANSWER_SETS
        ),
    )


def test_a_query_whose_search_is_cut_is_not_answered() -> None:
    interrupt = Interrupt()
    interrupt.pull()
    made = session(Program("{ a }.", "t.lp"), interrupt=interrupt)
    assert isinstance(made, Session)
    assert made.answer(Literal("a")) == Ended(Truncation.INTERRUPTED)


def test_a_literal_is_answered_without_reading_every_answer_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whether each truth is taken is asked apart; the search stops at the first to take each.

    Asked again, it reads on from the answer set it read first, once more at most.
    """
    made = opened(_MANY)
    read = _reads(monkeypatch)
    answered = made.answer(Pattern("q", ()))
    assert isinstance(answered, Answered)
    assert (answered.answer, answered.read) == (Answer.YES, None)
    assert [(t.answer, t.index) for t in answered.taken] == [(Answer.YES, 1)]
    unknown = made.answer(Any((Literal.parse("p(3)"),)))
    assert isinstance(unknown, Answered)
    assert unknown.answer is Answer.UNKNOWN
    assert len(unknown.taken) == 2
    assert len(read) <= 1 + max(t.index for t in unknown.taken)


@pytest.mark.parametrize("query", ["team(ann)", "team(bob)", "balanced", "-team(cy)"])
def test_a_literal_takes_each_answer_where_a_fresh_session_numbers_it(query: str) -> None:
    """The answer sets an answer names are those `why --answer-set` explains in a new session.

    clingo enumerates in another order once it has solved, as it does team.lp; the session asks
    whether each truth is taken on a grounding apart, so it reads as a fresh session does.
    """
    path = EXAMPLES / "team.lp"

    def fresh() -> Session:
        made = session(Program(path.read_text(), "team.lp", path))
        assert isinstance(made, Session)
        return made

    literal = Literal.parse(query)
    answered = fresh().answer(literal)
    assert isinstance(answered, Answered)
    assert answered.read is None
    assert {t.answer: t.index for t in answered.taken} == _indices(fresh(), literal)
    for each in answered.taken:
        found = fresh().counterexample(each.index)
        assert isinstance(found, Counterexample)
        assert found.answer_set == each.answer_set
    whole = fresh().answer(All((literal, literal)))
    assert isinstance(whole, Answered)
    assert (whole.answer, whole.taken, whole.read) == (answered.answer, answered.taken, 7)


def test_an_answer_set_at_an_index_is_found_without_reading_those_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unbounded, the search stops at the index asked for, so it does not say how many follow."""
    made = opened(_MANY)
    read = _reads(monkeypatch)
    fifth = made.counterexample(5)
    assert isinstance(fifth, Counterexample)
    assert (fifth.index, fifth.read, len(read)) == (5, None, 5)


def test_reading_on_keeps_the_numbers_of_the_answer_sets_read_before() -> None:
    """Asked past what it has read, the session reads on, numbering only answer sets it lacks."""
    path = EXAMPLES / "team.lp"
    made = session(Program(path.read_text(), "team.lp", path))
    assert isinstance(made, Session)
    second = made.counterexample(2)
    assert isinstance(made.counterexample(5), Counterexample)
    assert made.counterexample(2) == second
    every = [made.counterexample(index) for index in range(1, 8)]
    assert len({c.answer_set for c in every if isinstance(c, Counterexample)}) == 7
    assert made.counterexample(8) is None
    first = made.counterexample(1)
    assert isinstance(first, Counterexample)
    assert first.read == 7


def _failed(name: str) -> tuple[Program, Report, list[Finding]]:
    path = EXAMPLES / name
    program = Program(path.read_text(), name, path)
    report = check(program)
    assert isinstance(report, Report), report
    return program, report, [f for f in report.findings if f.verdict is Verdict.FAIL]


def _deepened(path: Path) -> bool:
    """Whether an example checks to a report with a failed claim."""
    report = check(Program(path.read_text(), path.name, path))
    return isinstance(report, Report) and any(f.verdict is Verdict.FAIL for f in report.findings)


DEEPENED = sorted(path.name for path in EXAMPLES.glob("*.lp") if _deepened(path))


@pytest.mark.parametrize("name", DEEPENED)
def test_going_deeper_in_one_session_finds_what_a_fresh_one_finds_at_that_depth(name: str) -> None:
    """`+` asks one session for a claim's evidence again, deeper; the counterexample stays."""
    program, report, failed = _failed(name)
    kept = session(program, report.solver)
    assert isinstance(kept, Session)
    for finding in failed:
        for depth in (1, 2, 3):
            fresh = session(program, report.solver)
            assert isinstance(fresh, Session)
            assert kept.evidence(finding, max_depth=depth) == fresh.evidence(
                finding, max_depth=depth
            )


_DEPTHS = (1, 2, 3, Limit.UNBOUNDED)


@settings(max_examples=30, deadline=None)
@given(
    name=st.sampled_from(["team.lp", "laptop.lp", "absent.lp"]),
    depths=st.lists(st.sampled_from(_DEPTHS), min_size=1, max_size=5),
)
def test_evidence_asked_at_any_depths_in_turn_is_what_a_fresh_session_finds(
    name: str, depths: list[int | Limit]
) -> None:
    program, report, failed = _failed(name)
    kept = session(program, report.solver)
    assert isinstance(kept, Session)
    for depth in depths:
        fresh = session(program, report.solver)
        assert isinstance(fresh, Session)
        for finding in failed:
            assert kept.evidence(finding, max_depth=depth) == fresh.evidence(
                finding, max_depth=depth
            )


_MANY = "{ p(1..40) }. q.\n"
"""A program with 2^40 answer sets, more than any search reads."""


def _reads(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Note each answer set a session reads from clingo."""
    read: list[object] = []
    real = session_module.seen

    def noted(*args: object) -> object:
        read.append(args)
        return real(*args)

    monkeypatch.setattr(session_module, "seen", noted)
    return read


@pytest.mark.parametrize(
    ("claim", "most"),
    [
        ("@expect sat\n% @cautious { p(1) }", 1),
        ("@expect unsat", 1),
        ("@expect sat\n% @brave { r }", 1 + 41),
    ],
)
def test_a_counterexample_is_found_without_reading_every_answer_set(
    monkeypatch: pytest.MonkeyPatch, claim: str, most: int
) -> None:
    """Unbounded, the search stops at the counterexample.

    Brave consequences read an answer set for each shown atom they gain, at most: 41 here.
    """
    made, findings = judged(f"{_MANY}% {claim}\n")
    read = _reads(monkeypatch)
    evidence = made.evidence(findings[-1])
    assert isinstance(evidence, Explanation)
    assert (evidence.counterexample.index, evidence.counterexample.read) == (1, None)
    assert len(read) <= most


def test_a_cautious_counterexample_is_the_first_answer_set_without_a_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The answer sets before it hold the literals: the search reads them, and stops at it."""
    program = "{ p(1..3) }. a(X) :- X = 1..3, not p(X).\n"
    every = opened(program).solve(frozenset())
    assert isinstance(every, Consistent)
    wanted = Literal.parse("a(1)")
    at = next(at for at, each in enumerate(every.evidence.all, 1) if wanted not in each.shown)
    made, findings = judged(f"{program}% @expect sat\n% @cautious {{ a(1) }}\n")
    read = _reads(monkeypatch)
    found = made.evidence(findings[1])
    assert isinstance(found, Explanation)
    assert found.counterexample.index == at > 1
    assert len(read) == at < len(every.evidence.all)


def test_a_counterexample_is_kept_across_other_searches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Asked again after another search, a claim's counterexample is read from what was kept."""
    made, findings = judged(f"{_MANY}% @expect sat\n% @cautious {{ p(1) }}\n% @brave {{ r }}\n")
    first = made.evidence(findings[1])
    made.evidence(findings[2])
    read = _reads(monkeypatch)
    assert made.evidence(findings[1]) == first
    assert read == []


def test_a_session_numbers_an_answer_set_the_same_each_time_it_is_asked() -> None:
    """Once it has solved, clingo enumerates in another order; the session keeps its first."""
    path = EXAMPLES / "team.lp"
    opened = session(Program(path.read_text(), "team.lp", path))
    assert isinstance(opened, Session)
    first = [opened.counterexample(index) for index in range(1, 8)]
    assert [opened.counterexample(index) for index in range(1, 8)] == first
    assert opened.answer(All(())) == opened.answer(All(()))


def test_a_search_the_limits_cut_is_asked_again() -> None:
    """Only a search that ended is kept: one cut short, as by `esc`, runs again when asked again."""
    interrupt = Interrupt()
    interrupt.pull()
    opened = session(Program("{ p }.", "t.lp"), interrupt=interrupt)
    assert isinstance(opened, Session)
    assert isinstance(opened.counterexample(1), Ended)
    opened.interrupt = Interrupt()
    assert isinstance(opened.counterexample(1), Counterexample)


def test_a_session_searches_once_for_each_scenario_it_is_asked_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asked again, an ended search is read from what the session kept, not run on clingo again."""
    path = EXAMPLES / "laptop.lp"
    opened = session(Program(path.read_text(), "laptop.lp", path))
    assert isinstance(opened, Session)
    calls: list[str] = []
    solve, optimize = opened.solve, opened.optimize

    def solving(*args: object, **kwargs: object) -> object:
        calls.append("solve")
        return solve(*args, **kwargs)  # type: ignore[arg-type]

    def optimizing(*args: object, **kwargs: object) -> object:
        calls.append("optimize")
        return optimize(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(opened, "solve", solving)
    monkeypatch.setattr(opened, "optimize", optimizing)
    ram = frozenset({Literal.parse("ram(32)")})
    for _ in range(2):
        opened.counterexample(1)
        opened.counterexample(1, over=Range.OPTIMAL)
        opened.outrank(ram)
    assert calls == ["solve", "optimize", "optimize"]


def test_an_optimization_the_limits_cut_is_asked_again() -> None:
    interrupt = Interrupt()
    interrupt.pull()
    opened = session(Program("{ p }. #minimize { 1 : p }.", "t.lp"), interrupt=interrupt)
    assert isinstance(opened, Session)
    assert isinstance(opened.counterexample(1, over=Range.OPTIMAL), Ended)
    opened.interrupt = Interrupt()
    assert isinstance(opened.counterexample(1, over=Range.OPTIMAL), Counterexample)
