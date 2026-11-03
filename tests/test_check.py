import pytest

from elenctic.check import check
from elenctic.contract import Claim, Costs, Witness
from elenctic.determination import AnswerSet, Consistent, Inconsistent, Incumbent, These, Truncation
from elenctic.engine import ground
from elenctic.judge import judge
from elenctic.literals import Assumption, Literal
from elenctic.program import Fault, Locus, Program
from elenctic.search import Interrupt, Limits
from elenctic.spans import Position, Span
from elenctic.verdicts import Ended, Finding, Report, Verdict
from interrupting import at_first_answer_set
from nesting import DEEP_NESTING, nested

DRINKS = """
1 { tea; coffee } 1.
biscuit.
#show tea/0. #show coffee/0. #show biscuit/0.
"""


def run(text: str, *, limits: Limits = Limits()) -> Report:
    found = check(Program(text, "t.lp"), limits=limits)
    assert isinstance(found, Report), found
    return found


def verdicts(text: str, *, limits: Limits = Limits()) -> list[Verdict]:
    return [f.verdict for f in run(text, limits=limits).findings]


P, F, U = Verdict.PASS, Verdict.FAIL, Verdict.UNDECIDED


def test_the_drinks_contract_holds() -> None:
    report = run(
        DRINKS
        + "% @expect sat\n% @count 2\n% @cautious { biscuit }\n% @brave { tea, coffee }\n"
        + "% @answer-set { tea, biscuit }\n"
    )
    assert report.verdict is P
    assert [f.verdict for f in report.findings] == [P] * 5


def test_a_wrong_claim_fails_and_says_what_the_program_does() -> None:
    (finding,) = run(DRINKS + "% @expect sat\n% @cautious { tea }\n").findings[1:]
    assert finding.verdict is F
    assert finding.claim.span.start.line == 6
    assert "missing: { tea }" in str(finding.detail)
    assert "{ biscuit }" in str(finding.detail)


def test_the_count_is_of_distinct_shown_answer_sets() -> None:
    assert verdicts("{a}. #show b/0. b.\n% @expect sat\n% @count 1") == [P, P]
    assert verdicts("{a}. b.\n% @expect sat\n% @count 2") == [P, P]


def test_expecting_unsat_passes_only_without_an_answer_set() -> None:
    assert verdicts("p. :- p.\n% @expect unsat\n% @count 0") == [P, P]
    assert verdicts("p.\n% @expect unsat") == [F]
    assert verdicts("p. :- p.\n% @expect sat") == [F]


def test_every_answer_set_claim_fails_when_there_is_no_answer_set() -> None:
    text = "p. :- p.\n% @expect sat\n% @answer-set { p }\n% @brave { p }\n% @query yes { p }\n"
    assert verdicts(text) == [F, F, F, F]


def test_a_scenario_is_judged_apart_from_the_program() -> None:
    text = (
        DRINKS
        + "% @expect sat\n% @cautious { tea } assuming { tea }\n"
        + "% @expect unsat assuming { tea, coffee }\n"
    )
    assert verdicts(text) == [P, P, P]


def test_a_refuted_scenario_names_the_assumptions_at_fault() -> None:
    report = run(DRINKS + "% @expect sat\n% @brave { tea } assuming { tea, coffee }\n")
    assert "tea" in str(report.findings[1].detail)
    assert "coffee" in str(report.findings[1].detail)


def test_queries_are_answered_over_every_answer_set() -> None:
    text = DRINKS + (
        "% @expect sat\n"
        "% @query yes { biscuit }\n"
        "% @query unknown { tea }\n"
        "% @query unknown { tea, coffee }\n"
        "% @query no { tea, coffee }\n"
    )
    assert verdicts(text) == [P, P, P, P, F]


def test_binding_queries_are_checked_against_the_partition_of_instances() -> None:
    program = "p(1). -p(2). {p(3)}. #show p/1. #show -p/1.\n% @expect sat\n"
    ok = (
        "% @query yes { p(X) } = { 1 }\n% @query no { p(X) } = { 2 }\n"
        "% @query unknown { p(X) } = { 3 }\n"
    )
    assert verdicts(program + ok) == [P, P, P, P]
    assert verdicts(program + "% @query yes { p(X) } = { 1, 3 }") == [P, F]


def test_a_search_that_did_not_finish_leaves_the_universal_claims_open() -> None:
    text = "{p(1..40)}. q.\n% @expect sat\n% @count 5\n% @cautious { p(1) }\n% @brave { q }\n"
    report = run(text, limits=Limits(max_answer_sets=100))
    assert [f.verdict for f in report.findings] == [P, F, F, P]


def test_a_search_cut_short_is_undecided_not_failed() -> None:
    text = (
        "{p(1..40)}.\n% @expect sat\n% @answer-set { p(1), p(40) }\n% @query yes { p(1), p(2) }\n"
    )
    report = run(text, limits=Limits(max_seconds=0))
    assert [f.verdict for f in report.findings] == [U, U, U]
    assert report.verdict is U
    assert report.findings[0].detail == Ended(Truncation.MAX_SECONDS)


def test_a_satisfiability_claim_alone_asks_the_solver_for_one_answer_set() -> None:
    assert verdicts("{p(1..40)}.\n% @expect sat", limits=Limits(max_seconds=5)) == [P]


def test_the_verdict_of_a_report_is_its_worst_finding() -> None:
    assert run("{a}.\n% @expect sat\n% @count 3").verdict is F
    assert run("{a}.\n% @expect sat").verdict is P


def test_a_malformed_contract_is_a_fault_of_the_request_with_every_diagnostic() -> None:
    found = check(Program("p.\n% @count x\n% @cautious { }\n", "t.lp"))
    assert isinstance(found, Fault)
    assert found.locus is Locus.REQUEST
    assert len(found.diagnostics) >= 2


def test_a_program_that_does_not_ground_is_a_fault_of_the_program() -> None:
    found = check(Program("p(X) :- q(Y).\n% @expect sat\n", "t.lp"))
    assert isinstance(found, Fault)
    assert found.locus is Locus.PROGRAM


def test_a_file_without_a_contract_has_nothing_to_check() -> None:
    assert check(Program("p.\n", "t.lp")) is None


@pytest.mark.parametrize("claim", ["% @cautious { p }", "% @count 1", "% @query yes { p }"])
def test_a_finding_prints_the_claim_it_judged(claim: str) -> None:
    (_, finding) = run(f"p.\n% @expect sat\n{claim}\n").findings
    assert isinstance(finding, Finding)
    assert finding.claim_text == claim.removeprefix("% ")


KNAPSACK = """
{ a; b; c }.
:- a, b.
#maximize { 3,a : a; 2,b : b; 2,c : c }.
#show a/0. #show b/0. #show c/0.
"""


def test_a_claim_about_the_optimal_answer_sets_reads_those_and_only_those() -> None:
    text = KNAPSACK + (
        "% @expect sat\n"
        "% @count optimal 1\n"
        "% @answer-set optimal { a, c }\n"
        "% @optimal { a, c }\n"
        "% @cautious optimal { a, c }\n"
        "% @brave optimal { a, c }\n"
        "% @cost { -5 }\n"
    )
    assert verdicts(text) == [P] * 7


def test_a_claim_true_of_an_answer_set_but_not_an_optimal_one_fails_when_about_the_optimal() -> (
    None
):
    text = (
        KNAPSACK + "% @expect sat\n% @answer-set optimal { b }\n% @answer-set { b }\n% @count 6\n"
    )
    assert verdicts(text) == [P, F, P, P]


def test_the_wrong_cost_fails_and_says_what_the_optimum_is() -> None:
    (finding,) = run(KNAPSACK + "% @expect sat\n% @cost { 5 }\n").findings[1:]
    assert finding.verdict is F
    assert finding.detail == "(5) expected, optimum is (-5)"


def test_a_maximized_cost_is_stated_as_the_minimized_sum() -> None:
    assert verdicts(KNAPSACK + "% @expect sat\n% @cost { -5 }\n") == [P, P]


def test_an_optimal_claim_over_an_inconsistent_program_fails_but_zero_optima_hold() -> None:
    text = "p. :- p. #minimize { 1 : p }.\n% @expect unsat\n% @count optimal 0\n"
    assert verdicts(text) == [P, P]


def test_a_tie_for_the_optimum_is_a_census_of_the_ties() -> None:
    text = "{ p; q }. :- not p, not q. #minimize { 1,p : p; 1,q : q }.\n"
    assert verdicts(text + "% @expect sat\n% @count optimal 3\n") == [P, F]
    assert verdicts(text + "% @expect sat\n% @count optimal 2\n") == [P, P]


def test_the_optimum_is_claimed_without_the_ties_all_found() -> None:
    text = (
        "{ p; q }. :- not p, not q. #minimize { 1,p : p; 1,q : q }.\n"
        "% @expect sat\n% @cost { 1 }\n% @count optimal 2\n"
    )
    assert verdicts(text, limits=Limits(max_answer_sets=1)) == [P, P, U]


def test_native_consequences_decide_a_search_the_answer_set_limit_would_cut() -> None:
    text = (
        "{p(1..40)}. q.\n"
        "% @expect sat\n% @cautious { q }\n% @brave { p(7) }\n% @cautious { p(1) }\n"
    )
    assert verdicts(text, limits=Limits(max_answer_sets=3)) == [P, P, P, F]


def test_the_optimal_consequences_are_not_decided_by_those_of_all_answer_sets() -> None:
    text = (
        "1 { a; b } 1. { z }. #minimize { 1,z : z }. #show a/0. #show b/0.\n"
        "% @expect sat\n% @cautious optimal { a }\n% @brave optimal { a }\n"
    )
    assert verdicts(text, limits=Limits(max_answer_sets=1)) == [P, U, P]
    assert verdicts(text, limits=Limits(max_answer_sets=2)) == [P, F, P]


def test_consequences_beside_a_census_are_still_decided_when_the_answer_set_limit_cuts_it() -> None:
    text = (
        "{p(1..40)}. q.\n% @expect sat\n% @count 5\n"
        "% @cautious { q }\n% @cautious { p(1) }\n% @brave { p(7) }\n"
    )
    assert verdicts(text, limits=Limits(max_answer_sets=3)) == [P, U, P, F, P]
    assert verdicts(text, limits=Limits(max_seconds=0)) == [U] * 5


def test_consequence_claims_agree_with_those_read_from_the_enumeration() -> None:
    claims = (
        "% @expect sat\n% @cautious { biscuit }\n% @brave { tea, coffee }\n% @cautious { tea }\n"
    )
    native = verdicts(DRINKS + claims)
    enumerated = verdicts(DRINKS + claims + "% @count 2\n")
    assert native == enumerated[:-1] == [P, P, P, F]


def test_a_refutation_names_a_minimal_set_of_assumptions() -> None:
    text = "{ p; q; r }. :- p, q.\n% @expect sat\n% @answer-set { p } assuming { p, q, r }\n"
    (finding,) = run(text).findings[1:]
    assert finding.detail == "no answer set satisfies the assumptions (p, q)"


def faults(text: str) -> list[str]:
    found = check(Program(text, "t.lp"))
    assert isinstance(found, Fault), found
    assert found.locus is Locus.REQUEST
    return [f"{d.span.start.line}: {d.message}" for d in found.diagnostics]


def test_an_optimal_claim_needs_an_objective_in_the_program() -> None:
    (message,) = faults("{p}.\n% @expect sat\n% @cost { 0 }\n")
    assert message.startswith("3: needs an objective")
    assert len(faults("{p}.\n% @expect sat\n% @optimal { p }\n% @count optimal 1\n")) == 2


def test_a_no_query_needs_the_contrary_shown_when_the_program_can_derive_it() -> None:
    program = "{p}. {-p}. :- p, -p. #show p/0.\n% @expect sat\n"
    (message,) = faults(program + "% @query no { p }\n")
    assert message == (
        "3: reads the contrary `-p/0` off the shown atoms, but the program can derive it "
        "and does not `#show` it"
    )
    assert faults(program + "% @query unknown { p }\n")
    assert verdicts(program + "% @query yes { p }\n") == [P, F]


def test_a_contrary_the_program_cannot_derive_needs_no_show() -> None:
    assert verdicts("{p}. #show p/0.\n% @expect sat\n% @query unknown { p }\n") == [P, P]


def test_a_shown_contrary_or_a_program_that_shows_everything_is_fine() -> None:
    shown = "{p}. {-p}. #show p/0. #show -p/0.\n% @expect sat\n% @query no { p }\n"
    assert verdicts(shown) == [P, F]
    everything = "{p}. {-p}.\n% @expect sat\n% @query unknown { p }\n"
    assert verdicts(everything) == [P, P]


def test_a_binding_query_that_reads_its_contrary_needs_it_shown_too() -> None:
    program = "{p(1)}. {-p(1)}. :- p(1), -p(1). #show p/1.\n% @expect sat\n"
    assert faults(program + "% @query unknown { p(X) } = { 1 }\n")
    assert faults(program + "% @query no { p(X) } = { 1 }\n")
    assert verdicts(program + "% @query no { p(X) } = { }\n") == [P, P]
    assert verdicts(program + "% @query yes { p(X) } = { }\n") == [P, P]


HIDDEN_LITERAL = "-b.\n#show b/0.\n% @expect sat\n"
HIDDEN_LITERAL_FAULT = (
    "4: reads `-b/0` off the shown atoms, but the program can derive it and does not `#show` it"
)


@pytest.mark.parametrize("answer", ["yes", "no", "unknown"])
def test_a_query_needs_the_literal_it_reads_shown_when_the_program_can_derive_it(
    answer: str,
) -> None:
    assert faults(HIDDEN_LITERAL + f"% @query {answer} {{ -b }}\n") == [HIDDEN_LITERAL_FAULT]


def test_a_hidden_literal_is_found_inside_a_conjunction_or_a_disjunction() -> None:
    for query in ["{ -b, b }", "{ b | -b }", "{ b, { -b | b } }"]:
        assert faults(HIDDEN_LITERAL + f"% @query yes {query}\n")


def test_a_binding_query_needs_the_pattern_it_reads_shown_when_the_program_can_derive_it() -> None:
    program = "-p(1). #show p/1.\n% @expect sat\n"
    for answer in ["yes", "no", "unknown"]:
        assert faults(program + f"% @query {answer} {{ -p(X) }} = {{ 1 }}\n")


def test_a_literal_the_program_cannot_derive_needs_no_show() -> None:
    program = "b. #show b/0.\n% @expect sat\n"
    assert verdicts(program + "% @query yes { b }\n% @query no { -b }\n") == [P, P, P]
    assert verdicts(program + "% @query unknown { -b }\n") == [P, F]


def test_a_theory_atom_is_not_checked_as_though_it_were_interpreted() -> None:
    text = "#theory t { c { }; &k/0 : c, any }.\n{p}. &k { 1 }.\n% @expect sat\n"
    (message,) = faults(text)
    assert message.startswith(
        "2: the program has theory atoms, which clingo would ground and ignore"
    )
    assert "`% @elenctic solver clingcon`" in message
    found = check(Program(text, "t.lp"))
    assert isinstance(found, Fault)
    assert found.diagnostics[0].span == Span("t.lp", Position(2, 6), Position(2, 15))


def test_an_objective_that_grounds_away_is_no_objective() -> None:
    (message,) = faults("#minimize { 1,a : a }.\n% @expect sat\n% @cost { 0 }\n")
    assert "its elements ground away" in message
    assert verdicts("{a}. #minimize { 1,a : a }.\n% @expect sat\n% @cost { 0 }\n") == [P, P]


def test_a_query_over_a_search_that_did_not_finish_is_undecided() -> None:
    text = "{p(1..40)}.\n% @expect sat\n% @query yes { p(1) }\n"
    assert verdicts(text, limits=Limits(max_answer_sets=2)) == [P, U]


def test_a_cost_claim_judged_without_an_optimization_is_never_a_pass() -> None:
    claim = Claim(Costs((0,)), frozenset(), Span("t.lp", Position(1, 1), Position(1, 2)))
    grounded = ground(Program("{p}."))
    assert not isinstance(grounded, Fault)
    finding = judge(claim, grounded.solve())
    assert (finding.verdict, finding.detail) == (U, "no optimum was sought")


def test_an_incumbent_is_never_a_pass_for_a_cost_claim() -> None:
    claim = Claim(Costs((0,)), frozenset(), Span("t.lp", Position(1, 1), Position(1, 2)))
    found = Consistent(
        Incumbent(AnswerSet(frozenset(), frozenset(), cost=(0,))), Truncation.MAX_SECONDS
    )
    finding = judge(claim, found)
    assert finding.verdict is U
    assert finding.detail == Ended(Truncation.MAX_SECONDS, optimum_unproven=True)


def test_a_core_that_may_not_be_minimal_says_so() -> None:
    claim = Claim(Witness(frozenset()), frozenset(), Span("t.lp", Position(1, 1), Position(1, 2)))
    core = frozenset({Assumption(Literal("p"), holds=True)})
    exact = judge(claim, Inconsistent(These(core)))
    cut = judge(claim, Inconsistent(These(core, minimal=False)))
    assert exact.detail == "no answer set satisfies the assumptions (p)"
    assert str(cut.detail).startswith(str(exact.detail))
    assert "may not be minimal" in str(cut.detail)


NESTED_PROGRAM = (
    "p(f(1),a). p(f(2),b). -p(f(3),a). {p(f(4),a)}. p(g(5),a). q((1,x)). q((2,y)). {q((3,z))}.\n"
    "#show p/2. #show -p/2. #show q/1.\n% @expect sat\n"
)


def test_a_binding_query_may_nest_its_variables_beneath_a_function() -> None:
    claims = (
        "% @query yes { p(f(X), a) } = { 1 }\n"
        "% @query no { p(f(X), a) } = { 3 }\n"
        "% @query unknown { p(f(X), a) } = { 4 }\n"
    )
    assert verdicts(NESTED_PROGRAM + claims) == [P, P, P, P]


def test_a_nested_binding_query_that_is_wrong_fails_and_says_what_was_found() -> None:
    (finding,) = run(NESTED_PROGRAM + "% @query yes { p(f(X), a) } = { 2 }\n").findings[1:]
    assert finding.verdict is F
    assert "yes bindings expected { (2) }, found { (1) }" in str(finding.detail)


def test_a_binding_query_may_name_a_tuple_and_its_ground_part() -> None:
    claims = "% @query yes { q((X, x)) } = { 1 }\n% @query yes { q((X, Y)) } = { (1, x), (2, y) }\n"
    assert verdicts(NESTED_PROGRAM + claims) == [P, P, P]


def test_arithmetic_in_a_query_is_evaluated_before_it_is_matched() -> None:
    assert verdicts(NESTED_PROGRAM + "% @query yes { p(f(1+1), X) } = { b }\n") == [P, P]


def test_a_term_that_stands_for_no_one_term_is_a_fault_not_a_query_with_no_match() -> None:
    (message,) = faults(NESTED_PROGRAM + "% @query yes { p(f(1..2), a) } = { }\n")
    assert message.endswith("is not a pattern: an interval stands for several terms")
    (message,) = faults(NESTED_PROGRAM + "% @query yes { p(f(X+1), a) } = { }\n")
    assert "is not a pattern" in message


def test_a_nested_binding_query_that_reads_its_contrary_needs_it_shown_too() -> None:
    program = "{p(f(1))}. {-p(f(1))}. :- p(f(1)), -p(f(1)). #show p/1.\n% @expect sat\n"
    assert faults(program + "% @query unknown { p(f(X)) } = { 1 }\n")


def test_a_ground_query_may_nest_functions_to_any_depth() -> None:
    nested = "f(" * 200 + "a" + ")" * 200
    program = f"p({nested}). #show p/1.\n% @expect sat\n% @query yes {{ p({nested}) }}\n"
    assert verdicts(program) == [P, P]


CHOICES = 8
ALTERNATIVES = f"1 {{ c(1..{CHOICES}) }} 1.\n% @expect sat\n"
EVERY_CHOICE = ", ".join(f"c({each})" for each in range(1, CHOICES + 1))


@pytest.mark.parametrize(
    ("claim", "settled"),
    [("@cautious { c(1) }", F), (f"@brave {{ {EVERY_CHOICE} }}", P)],
    ids=["cautious", "brave"],
)
def test_a_consequence_claim_is_open_when_the_search_is_cut_after_its_first_answer_set(
    claim: str, settled: Verdict, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = ALTERNATIVES + f"% {claim}\n"
    assert verdicts(text) == [P, settled]
    interrupt = Interrupt()
    at_first_answer_set(monkeypatch, interrupt.pull)
    found = check(Program(text, "t.lp"), interrupt=interrupt)
    assert isinstance(found, Report)
    assert [f.verdict for f in found.findings] == [P, U]
    assert found.findings[1].detail == Ended(Truncation.INTERRUPTED)


def test_native_consequences_settle_a_claim_that_an_answer_set_limit_leaves_open() -> None:
    text = ALTERNATIVES + f"% @cautious {{ c(1) }}\n% @count {CHOICES}\n"
    assert verdicts(text, limits=Limits(max_answer_sets=1)) == [P, F, U]


def test_a_deeply_nested_term_beside_a_theory_atom_is_a_fault_not_an_exception() -> None:
    theory = "#theory t { c { }; &k/0 : c, any }.\n"
    (message,) = faults(theory + f"p({nested()}) :- &k {{ 1 }}.\n% @expect sat\n")
    assert message.startswith("2: the program has theory atoms")


def test_a_deeply_nested_term_in_a_show_is_read() -> None:
    assert verdicts(f"a.\n#show {'-' * DEEP_NESTING}a.\n% @expect sat\n") == [P]
