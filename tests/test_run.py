"""Unit tests for ``runs_for``: the pure derivation of solver runs and their checks.

A contract's tags coalesce onto the fixed run-configuration taxonomy (the :class:`Mode` enum): tags
that can share one solve land on one :class:`Run`; the genuinely different searches (brave vs
cautious vs optimization vs full enumeration) do not. Each run carries its checks as self-describing
:class:`~elenctic.checks.Check`s, so a test reads ``check.label`` with no solve.

The wiring rule is enforced in ``Run.__post_init__``: ``reads ⊆ populates(mode)`` for every
check, so ``runs_for`` returning at all already proves every derived run is well-routed.

The subtleties under test: ``@expect sat`` (which reads ∅) rides an existing full enumeration else a
cheap ``DEFAULT`` solve, never an expensive cautious/brave/opt run. A conjunctive ground ``@query``
rides ``ENUM_ALL`` (the census); a singleton ground or yes/no binding rides ``CAUTIOUS_ALL`` (⋂); an
unknown binding rides ``ENUM_ALL``; and ``@cost`` rides ``OPTIMAL_ENUM`` with an optimal base, else
``OPTIMAL``.
"""

from typing import assert_never

import pytest
from clingo import Function
from hypothesis import given
from hypothesis import strategies as st

from elenctic import checks
from elenctic.expectation import Expectation, Sat, Unsat, WitnessClaim, parse
from elenctic.query import Answer, BindingQuery, GroundQuery, Query, QueryLiteral, Var
from elenctic.result import (
    Consistent,
    ConsistentShownCensus,
    ConsistentShownOptimalCensus,
    Field,
)
from elenctic.run import (
    Collection,
    Mode,
    RoutingError,
    Run,
    populates,
    reads_full_census,
    runs_for,
    shape_for,
    should_project,
)


def runs(contract: str) -> tuple[Run, ...]:
    return runs_for(parse(contract))


def labels(run: Run) -> set[str]:
    return {check.label for check in run.checks}  # static — no solve


def configs(contract: str) -> set[Mode]:
    return {run.mode for run in runs(contract)}


def run_at(contract: str, mode: Mode) -> Run:
    return next(run for run in runs(contract) if run.mode == mode)


# --- the Mode taxonomy: the lowering and the populates map ---


def test_mode_lowers_to_its_solver_args() -> None:
    assert Mode.DEFAULT.args == ()
    assert Mode.ENUM_ALL.args == ("--models=0", "--opt-mode=ignore")
    assert Mode.CAUTIOUS_ALL.args == ("--enum-mode=cautious", "--models=0", "--opt-mode=ignore")
    assert Mode.BRAVE_ALL.args == ("--enum-mode=brave", "--models=0", "--opt-mode=ignore")
    assert Mode.OPTIMAL_ENUM.args == ("--opt-mode=optN", "--models=0")
    assert Mode.OPTIMAL.args == ("--opt-mode=opt",)


def test_every_mode_states_the_optimization_its_collection_requires() -> None:
    # The invariant the lowering table exists to keep: a mode's optimization flag is fixed by the
    # collection its reading ranges over, and no mode may leave it to clingo's default. clingo
    # defaults to --opt-mode=opt, which prunes an enumerating solve to the branch-and-bound
    # improving sequence -- neither AS(P) nor Opt(P), and dependent on the search heuristic. Pinning
    # the arg tuples (above) records what each mode lowers to; this pins *why*, so a mode added
    # without an opt-mode fails here rather than answering a question nobody asked.
    for mode in Mode:
        stated = tuple(arg for arg in mode.args if arg.startswith("--opt-mode="))
        match mode.asks:
            case Collection.ALL:
                assert stated == ("--opt-mode=ignore",), (
                    f"{mode.name} reads AS(P), so it must switch the objective off"
                )
            case Collection.OPTIMAL:
                assert stated in (("--opt-mode=opt",), ("--opt-mode=optN",)), (
                    f"{mode.name} reads Opt(P), so it must switch the objective on"
                )
            case Collection.WITNESS:
                assert stated == (), (
                    f"{mode.name} reads satisfiability and one arbitrary witness, both invariant "
                    "under an objective, so it states no opt-mode"
                )
            case _:
                assert_never(mode.asks)


def test_every_mode_declares_the_collection_it_reads() -> None:
    # Totality: a Mode added without an `asks` entry KeyErrors here, before it can reach a solver.
    for mode in Mode:
        assert isinstance(mode.asks, Collection)


def test_mode_keyed_structures_agree_over_both_projection_coordinates() -> None:
    # The Mode-keyed structures (.args, populates, shape_for) stay total over Mode × the projection
    # coordinate: a Mode added without an entry KeyErrors here.
    for mode in Mode:
        assert isinstance(mode.args, tuple)
        for projects in (False, True):
            assert isinstance(populates(mode, projects), frozenset)
            assert issubclass(shape_for(mode, projects), Consistent)


def test_populates_maps_each_mode_full_shape() -> None:
    assert populates(Mode.DEFAULT) == frozenset({Field.WITNESS})
    assert populates(Mode.ENUM_ALL) == frozenset(
        {Field.SHOWN_CENSUS, Field.FULL_CENSUS, Field.CAUTIOUS, Field.BRAVE}
    )
    assert populates(Mode.CAUTIOUS_ALL) == frozenset({Field.CAUTIOUS})
    assert populates(Mode.BRAVE_ALL) == frozenset({Field.BRAVE})
    assert populates(Mode.OPTIMAL_ENUM) == frozenset(
        {Field.SHOWN_OPTIMAL_CENSUS, Field.FULL_OPTIMAL_CENSUS, Field.OPTIMUM}
    )
    assert populates(Mode.OPTIMAL) == frozenset({Field.OPTIMUM})


def test_projection_sheds_exactly_the_full_token() -> None:
    # The uniform law: populates(m, True) = populates(m, False) \ {full token of m}.
    assert populates(Mode.ENUM_ALL, True) == populates(Mode.ENUM_ALL, False) - {Field.FULL_CENSUS}
    assert populates(Mode.OPTIMAL_ENUM, True) == (
        populates(Mode.OPTIMAL_ENUM, False) - {Field.FULL_OPTIMAL_CENSUS}
    )
    # Non-projecting modes have no full token, so the coordinate is a no-op.
    for mode in (Mode.DEFAULT, Mode.CAUTIOUS_ALL, Mode.BRAVE_ALL, Mode.OPTIMAL):
        assert populates(mode, True) == populates(mode, False)


def test_shape_for_selects_the_projected_shape_only_for_projecting_modes() -> None:
    assert shape_for(Mode.ENUM_ALL, True) is ConsistentShownCensus
    assert shape_for(Mode.OPTIMAL_ENUM, True) is ConsistentShownOptimalCensus
    assert shape_for(Mode.ENUM_ALL, False) is not ConsistentShownCensus
    for mode in (Mode.DEFAULT, Mode.CAUTIOUS_ALL, Mode.BRAVE_ALL, Mode.OPTIMAL):
        assert shape_for(mode, True) is shape_for(mode, False)


# --- the wiring rule: reads ⊆ populates, enforced at construction ---


def test_run_rejects_a_misrouted_check_at_construction() -> None:
    # @count reads the full census; CAUTIOUS_ALL does not populate it — rejected before any solve,
    # as a RoutingError (a harness bug), never a verdict; the message names the field, check, mode.
    with pytest.raises(RoutingError) as exc:
        Run(Mode.CAUTIOUS_ALL, (checks.count_is(2),))
    message = str(exc.value)
    assert "full census" in message  # the missing field
    assert "@count" in message  # the offending check
    assert "CAUTIOUS_ALL" in message  # the mode


def test_wiring_rule_catches_a_bad_projection_at_construction() -> None:
    # A Run whose projection state is on, carrying a full-view reader (@count reads the full
    # census), is rejected at construction: populates(ENUM_ALL, projects_to_shown=True) sheds the
    # full-census token, so the wiring rule fires before any solve — no should_project mis-derive
    # can reach one.
    with pytest.raises(RoutingError) as exc:
        Run(Mode.ENUM_ALL, (checks.count_is(2),), project=True, theory_in_force=True)
    message = str(exc.value)
    assert "full census" in message  # the missing token
    assert "@count" in message  # the offending check
    assert "projects_to_shown=True" in message


# --- should_project: the contract-induced projection decision, derived and backstopped ---


def test_reads_full_census_is_a_vocabulary_membership_test() -> None:
    assert reads_full_census(checks.count_is(2))  # @count reads the full census
    assert reads_full_census(checks.assign_contains(frozenset({(Function("x"), 1)})))
    assert reads_full_census(checks.count_optimal_is(1))  # reads the full optimal census
    bare_model = checks.has_model(WitnessClaim(shown=frozenset({Function("a")})))
    assert not reads_full_census(bare_model)  # @model reads the shown census, not full
    assert not reads_full_census(checks.cautious_contains(frozenset({Function("a")})))


@pytest.mark.parametrize(
    ("theory", "mode", "carried", "expected"),
    [
        pytest.param(True, Mode.DEFAULT, (), False, id="default-never"),
        pytest.param(True, Mode.CAUTIOUS_ALL, (), False, id="cautious-never"),
        pytest.param(True, Mode.OPTIMAL, (), False, id="opt-single-never"),
        pytest.param(False, Mode.ENUM_ALL, (), True, id="clingo-enum-projects"),
        pytest.param(False, Mode.OPTIMAL_ENUM, (), True, id="clingo-optenum-projects"),
        pytest.param(True, Mode.ENUM_ALL, ("model",), True, id="theory-shown-only-projects"),
        pytest.param(True, Mode.ENUM_ALL, ("count",), False, id="theory-count-suppresses"),
        pytest.param(True, Mode.ENUM_ALL, ("assign",), False, id="theory-assign-suppresses"),
        pytest.param(True, Mode.ENUM_ALL, ("model", "count"), False, id="theory-mixed-suppresses"),
    ],
)
def test_should_project_decision_matrix(
    theory: bool, mode: Mode, carried: tuple[str, ...], expected: bool
) -> None:
    factory = {
        "model": lambda: checks.has_model(WitnessClaim(shown=frozenset({Function("a")}))),
        "count": lambda: checks.count_is(2),
        "assign": lambda: checks.assign_contains(frozenset({(Function("x"), 1)})),
    }
    built = tuple(factory[name]() for name in carried)
    assert should_project(theory, mode, built) is expected


def test_count_diverges_requires_theory_from_reads_full_census() -> None:
    # @count reads the full census (so it suppresses projection under a theory) yet does NOT itself
    # require a theory solver (@count is meaningful on pure clingo) — the two properties diverge.
    assert reads_full_census(checks.count_is(2))
    exp = parse("% @expect sat\n% @count 2\n")
    assert isinstance(exp, Sat) and not exp.requires_theory


def test_run_accepts_a_well_routed_check() -> None:
    run = Run(Mode.CAUTIOUS_ALL, (checks.cautious_contains(frozenset({Function("a")})),))
    assert labels(run) == {"@cautious"}


def test_run_equality_is_by_identity() -> None:
    one = Run(Mode.DEFAULT, (checks.expect_unsat(),))
    assert one == one
    assert one != Run(Mode.DEFAULT, (checks.expect_unsat(),))  # eq=False: distinct objects


# --- the core routing: each model-bearing tag rides its taxonomy cell ---


@pytest.mark.parametrize(
    ("contract", "mode", "label"),
    [
        pytest.param("% @expect sat\n% @model { a }\n", Mode.ENUM_ALL, "@model", id="model"),
        pytest.param("% @expect sat\n% @count 2\n", Mode.ENUM_ALL, "@count", id="count"),
        pytest.param("% @expect sat\n% @assign { x=1 }\n", Mode.ENUM_ALL, "@assign", id="assign"),
        pytest.param(
            "% @expect sat\n% @cautious { a }\n", Mode.CAUTIOUS_ALL, "@cautious", id="cautious"
        ),
        pytest.param("% @expect sat\n% @brave { a }\n", Mode.BRAVE_ALL, "@brave", id="brave"),
        pytest.param(
            "% @expect sat\n% @optimal { a }\n", Mode.OPTIMAL_ENUM, "@optimal", id="optimal"
        ),
        pytest.param(
            "% @expect sat\n% @cautious optimal { a }\n",
            Mode.OPTIMAL_ENUM,
            "@cautious optimal",
            id="cautious-optimal",
        ),
        pytest.param(
            "% @expect sat\n% @brave optimal { a }\n",
            Mode.OPTIMAL_ENUM,
            "@brave optimal",
            id="brave-optimal",
        ),
        pytest.param(
            "% @expect sat\n% @count optimal 1\n",
            Mode.OPTIMAL_ENUM,
            "@count optimal",
            id="count-optimal",
        ),
    ],
)
def test_model_bearing_tag_rides_its_mode(contract: str, mode: Mode, label: str) -> None:
    assert label in labels(run_at(contract, mode))


# --- @expect sat: ride a full enumeration if one exists, else a cheap DEFAULT solve ---


def test_expect_sat_alone_is_one_default_run() -> None:
    derived = runs("% @expect sat\n")
    assert len(derived) == 1
    assert derived[0].mode == Mode.DEFAULT
    assert labels(derived[0]) == {"@expect sat"}


def test_expect_sat_rides_an_existing_full_enumeration() -> None:
    # @model already forces ENUM_ALL, so @expect sat coalesces onto it — one solve, not two.
    derived = runs("% @expect sat\n% @model { a }\n")
    assert len(derived) == 1
    assert derived[0].mode == Mode.ENUM_ALL
    assert labels(derived[0]) == {"@model", "@expect sat"}


def test_expect_sat_takes_default_alongside_a_cautious_run() -> None:
    # @expect sat reads ∅ (it could ride any run), but takes a cheap DEFAULT solve rather than the
    # expensive cautious run — the cautious solve is likelier to time out and report UNDECIDED where
    # the 1-model DEFAULT solve would decide satisfiability.
    assert configs("% @expect sat\n% @cautious { a }\n") == {Mode.CAUTIOUS_ALL, Mode.DEFAULT}
    assert labels(run_at("% @expect sat\n% @cautious { a }\n", Mode.DEFAULT)) == {"@expect sat"}


def test_expect_sat_takes_default_under_optimisation_only() -> None:
    contract = "% @expect sat\n% @optimal { a }\n"
    assert configs(contract) == {Mode.OPTIMAL_ENUM, Mode.DEFAULT}
    assert labels(run_at(contract, Mode.DEFAULT)) == {"@expect sat"}


# --- @expect unsat: a single default run, nothing else ---


def test_unsat_is_one_default_run_with_only_expect_unsat() -> None:
    derived = runs("% @expect unsat\n")
    assert len(derived) == 1
    assert derived[0].mode == Mode.DEFAULT
    assert labels(derived[0]) == {"@expect unsat"}


# --- @query routing (bridge theorem, conjunctive-census escalation, unknown-binding escalation) ---


def test_singleton_ground_query_shares_the_cautious_run() -> None:
    # The bridge theorem: a singleton ground @query yes { L } reads ⋂, the same run a
    # @cautious { L } needs — so they coalesce onto the one cautious solve.
    contract = "% @expect sat\n% @cautious { a }\n% @query yes { a }\n"
    assert {"@cautious", "@query"} <= labels(run_at(contract, Mode.CAUTIOUS_ALL))


def test_conjunctive_ground_query_rides_a_full_enumeration() -> None:
    # corrected Def 2.2.2: a conjunctive ground @query's "no" is a per-model property (the census),
    # not a ⋂ property — so it rides ENUM_ALL, not CAUTIOUS_ALL.
    contract = "% @expect sat\n% @query no { a, b }\n"
    assert configs(contract) == {Mode.ENUM_ALL}
    assert "@query" in labels(run_at(contract, Mode.ENUM_ALL))


def test_unknown_binding_query_rides_one_full_enumeration() -> None:
    # An unknown-binding query needs both ⋂ and ⋃; one ENUM_ALL solve yields both. @expect sat too.
    contract = "% @expect sat\n% @query unknown { p(X) } = { a }\n"
    assert configs(contract) == {Mode.ENUM_ALL}
    assert labels(run_at(contract, Mode.ENUM_ALL)) == {"@query", "@expect sat"}


def test_singleton_ground_query_uses_cautious_even_when_unknown() -> None:
    # A *singleton* ground query reads ⋂ for every answer (yes/no/unknown) — only an unknown
    # *binding* needs ⋃, and only a *conjunctive* ground query needs the census.
    contract = "% @expect sat\n% @query unknown { a }\n"
    assert "@query" in labels(run_at(contract, Mode.CAUTIOUS_ALL))
    assert Mode.ENUM_ALL not in configs(contract)


def test_yes_binding_query_uses_cautious() -> None:
    contract = "% @expect sat\n% @query yes { p(X) } = { a }\n"
    assert "@query" in labels(run_at(contract, Mode.CAUTIOUS_ALL))
    assert Mode.ENUM_ALL not in configs(contract)


# --- @cost: cheap single optimum, unless an optimal-base mode forces the shared enumeration ---


def test_cost_alone_uses_the_cheap_single_optimum() -> None:
    contract = "% @expect sat\n% @cost { 8 }\n"
    assert "@cost" in labels(run_at(contract, Mode.OPTIMAL))
    assert Mode.OPTIMAL_ENUM not in configs(contract)


def test_cost_with_an_optimal_base_rides_the_shared_opt_enum() -> None:
    contract = "% @expect sat\n% @cost { 8 }\n% @count optimal 2\n"
    assert {"@cost", "@count optimal"} <= labels(run_at(contract, Mode.OPTIMAL_ENUM))
    assert Mode.OPTIMAL not in configs(contract)


# --- coalescing: shared solves merge, and no tag is dropped or invented ---


def test_optimal_modes_coalesce_onto_one_opt_enum_solve() -> None:
    contract = (
        "% @expect sat\n"
        "% @optimal { a }\n"
        "% @cautious optimal { a }\n"
        "% @brave optimal { a }\n"
        "% @count optimal 1\n"
    )
    opt_enum_runs = [run for run in runs(contract) if run.mode == Mode.OPTIMAL_ENUM]
    assert len(opt_enum_runs) == 1  # one shared enumeration of Opt(P), not four
    assert {
        "@optimal",
        "@cautious optimal",
        "@brave optimal",
        "@count optimal",
    } <= labels(opt_enum_runs[0])


def test_enumeration_tags_coalesce_onto_one_enum_all_solve() -> None:
    contract = "% @expect sat\n% @model { a }\n% @count 2\n% @assign { x=1 }\n"
    derived = runs(contract)
    assert len(derived) == 1
    assert derived[0].mode == Mode.ENUM_ALL
    assert labels(derived[0]) == {"@model", "@count", "@assign", "@expect sat"}


def test_every_tag_becomes_exactly_one_check_no_drop_no_duplicate() -> None:
    contract = (
        "% @expect sat\n% @model { a }\n% @cautious { a }\n% @brave { a }\n% @query yes { a }\n"
    )
    derived = runs(contract)
    all_labels = [check.label for run in derived for check in run.checks]
    assert sorted(all_labels) == ["@brave", "@cautious", "@expect sat", "@model", "@query"]
    assert len(all_labels) == len(set(all_labels))  # each tag yields exactly one check


def test_runs_for_is_deterministic_in_order() -> None:
    contract = "% @expect sat\n% @model { a }\n% @cautious { a }\n% @query yes { a }\n"
    first = [(run.mode, tuple(check.label for check in run.checks)) for run in runs(contract)]
    second = [(run.mode, tuple(check.label for check in run.checks)) for run in runs(contract)]
    assert first == second


# --- a Hypothesis property: runs_for is total, well-routed, coalesced, carries one @expect ---

_GROUND = GroundQuery(Answer.yes, (Function("a"),))
_GROUND_CONJ = GroundQuery(Answer.no, (Function("a"), Function("b")))
_BIND_YES = BindingQuery(
    Answer.yes, QueryLiteral("p", True, (Var("X"),)), frozenset({(Function("a"),)})
)
_BIND_UNKNOWN = BindingQuery(
    Answer.unknown, QueryLiteral("p", True, (Var("X"),)), frozenset({(Function("a"),)})
)
_BIND_NO = BindingQuery(
    Answer.no, QueryLiteral("p", True, (Var("X"),)), frozenset({(Function("a"),)})
)
_LIT = frozenset({Function("a")})


@st.composite
def _sats(draw: st.DrawFn) -> Sat:
    """An arbitrary structurally-valid ``Sat`` (runs_for derives runs from any Sat; cross-tag
    well-formedness is ``parse``'s concern, not runs_for's)."""
    optional_lit = st.sampled_from([_LIT, frozenset()])
    queries: st.SearchStrategy[Query] = st.sampled_from(
        [_GROUND, _GROUND_CONJ, _BIND_YES, _BIND_NO, _BIND_UNKNOWN]
    )
    return Sat(
        model=draw(st.sampled_from([WitnessClaim(shown=_LIT), None])),
        optimal_model=draw(st.sampled_from([WitnessClaim(shown=_LIT), None])),
        cautious=draw(optional_lit),
        cautious_optimal=draw(optional_lit),
        brave=draw(optional_lit),
        brave_optimal=draw(optional_lit),
        count=draw(st.sampled_from([2, None])),
        count_optimal=draw(st.sampled_from([1, None])),
        cost=draw(st.sampled_from([(8,), None])),
        assign=draw(st.sampled_from([frozenset({(Function("x"), 1)}), frozenset()])),
        queries=tuple(draw(st.lists(queries, max_size=3))),
    )


def _expectations() -> st.SearchStrategy[Expectation]:
    """The whole Expectation sum (Unsat | Sat); runs_for is total over it."""
    return st.one_of(st.just(Unsat()), _sats())


@given(_expectations())
def test_runs_for_builds_only_well_routed_coalesced_runs(exp: Expectation) -> None:
    derived = runs_for(exp)  # total; well-routed by construction (else __post_init__ raised)
    # THE Half-B property: every check reads a subset of what its run's mode populates.
    assert all(check.reads <= populates(run.mode) for run in derived for check in run.checks)
    assert len({run.mode for run in derived}) == len(derived)  # mode-distinct ⟺ fully coalesced
    assert all(check.label for run in derived for check in run.checks)  # every check is labelled
    expects = [
        check.label for run in derived for check in run.checks if check.label.startswith("@expect")
    ]
    assert len(expects) == 1  # exactly one @expect (sat|unsat), always present


def test_assign_optimal_rides_the_optimal_enum_run() -> None:
    contract = "% @expect sat\n% @assign optimal { w=2 }\n"
    assert "@assign optimal" in labels(run_at(contract, Mode.OPTIMAL_ENUM))


def test_where_witness_reads_full_token_and_suppresses_projection() -> None:
    where_check = checks.has_model(
        WitnessClaim(shown=frozenset({Function("a")}), assign=frozenset({(Function("v"), 1)}))
    )
    assert reads_full_census(where_check)  # the where-clause makes it read the full census
    assert should_project(True, Mode.ENUM_ALL, (where_check,)) is False  # suppressed
