"""Unit tests for ``runs_for``: the pure derivation of solver runs and their checks (spec §3, §4).

A contract's tags coalesce onto the fixed run-configuration taxonomy (the :class:`Mode` enum): tags
that can share one solve land on one :class:`Run`; the genuinely different searches (brave vs
cautious vs optimization vs full enumeration) do not. Each run carries its checks as self-describing
:class:`~elenctic.checks.Check`s, so a test reads ``check.label`` with no solve (dx#9 / option C).

The wiring rule (Half B) is enforced in ``Run.__post_init__``: ``reads ⊆ populates(mode)`` for every
check, so ``runs_for`` returning at all already proves every derived run is well-routed.

The subtleties under test: ``@expect sat`` (which reads ∅) rides an existing full enumeration else a
cheap ``DEFAULT`` solve, never an expensive cautious/brave/opt run. A conjunctive ground ``@query``
rides ``ENUM_ALL`` (the census); a singleton ground or yes/no binding rides ``CAUTIOUS_ALL`` (⋂); an
unknown binding rides ``ENUM_ALL``; and ``@cost`` rides ``OPT_ENUM`` with an optimal base, else
``OPT``.
"""

import pytest
from clingo import Function
from hypothesis import given
from hypothesis import strategies as st

from elenctic import checks
from elenctic.expectation import Expectation, Sat, Unsat, parse
from elenctic.query import Answer, BindingQuery, GroundQuery, Query, QueryLiteral, Var
from elenctic.result import Field
from elenctic.run import Mode, RoutingError, Run, populates, runs_for


def runs(contract: str) -> tuple[Run, ...]:
    return runs_for(parse(contract))


def labels(run: Run) -> set[str]:
    return {check.label for check in run.checks}  # static — no solve (option C)


def configs(contract: str) -> set[Mode]:
    return {run.mode for run in runs(contract)}


def run_at(contract: str, mode: Mode) -> Run:
    return next(run for run in runs(contract) if run.mode == mode)


# --- the Mode taxonomy: the lowering and the populates map ---


def test_mode_lowers_to_its_solver_args() -> None:
    assert Mode.DEFAULT.args == ()
    assert Mode.ENUM_ALL.args == ("--models=0",)
    assert Mode.CAUTIOUS_ALL.args == ("--enum-mode=cautious", "--models=0")
    assert Mode.BRAVE_ALL.args == ("--enum-mode=brave", "--models=0")
    assert Mode.OPT_ENUM.args == ("--opt-mode=optN", "--models=0")
    assert Mode.OPT.args == ("--opt-mode=opt",)


def test_args_and_populates_are_total_over_mode() -> None:
    # a Mode added without an _ARGS/_POPULATES entry KeyErrors here (the RoutingError scenario)
    for mode in Mode:
        assert isinstance(mode.args, tuple)
        assert isinstance(populates(mode), frozenset)


def test_populates_maps_each_mode() -> None:
    assert populates(Mode.DEFAULT) == frozenset({Field.WITNESS})
    assert populates(Mode.ENUM_ALL) == frozenset({Field.OBSERVABLES, Field.CAUTIOUS, Field.BRAVE})
    assert populates(Mode.CAUTIOUS_ALL) == frozenset({Field.CAUTIOUS})
    assert populates(Mode.BRAVE_ALL) == frozenset({Field.BRAVE})
    assert populates(Mode.OPT_ENUM) == frozenset({Field.OPTIMAL_OBSERVABLES, Field.OPTIMUM})
    assert populates(Mode.OPT) == frozenset({Field.OPTIMUM})


# --- the wiring rule (Half B): reads ⊆ populates, enforced at construction ---


def test_run_rejects_a_misrouted_check_at_construction() -> None:
    # @count reads OBSERVABLES; CAUTIOUS_ALL does not populate it — rejected before any solve, as a
    # RoutingError (a harness bug), never a verdict; the message names the field, check, and mode.
    with pytest.raises(RoutingError) as exc:
        Run(Mode.CAUTIOUS_ALL, (checks.count_is(2),))
    message = str(exc.value)
    assert "observables" in message  # the missing field
    assert "@count" in message  # the offending check
    assert "CAUTIOUS_ALL" in message  # the mode


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
        pytest.param("% @expect sat\n% @optimal { a }\n", Mode.OPT_ENUM, "@optimal", id="optimal"),
        pytest.param(
            "% @expect sat\n% @cautious optimal { a }\n",
            Mode.OPT_ENUM,
            "@cautious optimal",
            id="cautious-optimal",
        ),
        pytest.param(
            "% @expect sat\n% @brave optimal { a }\n",
            Mode.OPT_ENUM,
            "@brave optimal",
            id="brave-optimal",
        ),
        pytest.param(
            "% @expect sat\n% @count optimal 1\n",
            Mode.OPT_ENUM,
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
    assert configs(contract) == {Mode.OPT_ENUM, Mode.DEFAULT}
    assert labels(run_at(contract, Mode.DEFAULT)) == {"@expect sat"}


# --- @expect unsat: a single default run, nothing else ---


def test_unsat_is_one_default_run_with_only_expect_unsat() -> None:
    derived = runs("% @expect unsat\n")
    assert len(derived) == 1
    assert derived[0].mode == Mode.DEFAULT
    assert labels(derived[0]) == {"@expect unsat"}


# --- @query routing (bridge theorem, conjunctive-census escalation, unknown-binding escalation) ---


def test_singleton_ground_query_shares_the_cautious_run() -> None:
    # The bridge theorem (spec §2.4): a singleton ground @query yes { L } reads ⋂, the same run a
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
    assert "@cost" in labels(run_at(contract, Mode.OPT))
    assert Mode.OPT_ENUM not in configs(contract)


def test_cost_with_an_optimal_base_rides_the_shared_opt_enum() -> None:
    contract = "% @expect sat\n% @cost { 8 }\n% @count optimal 2\n"
    assert {"@cost", "@count optimal"} <= labels(run_at(contract, Mode.OPT_ENUM))
    assert Mode.OPT not in configs(contract)


# --- coalescing: shared solves merge, and no tag is dropped or invented ---


def test_optimal_modes_coalesce_onto_one_opt_enum_solve() -> None:
    contract = (
        "% @expect sat\n"
        "% @optimal { a }\n"
        "% @cautious optimal { a }\n"
        "% @brave optimal { a }\n"
        "% @count optimal 1\n"
    )
    opt_enum_runs = [run for run in runs(contract) if run.mode == Mode.OPT_ENUM]
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
        model=draw(st.sampled_from([_LIT, None])),
        optimal_model=draw(st.sampled_from([_LIT, None])),
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
