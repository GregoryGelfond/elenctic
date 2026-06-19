"""Unit tests for ``runs_for``: the pure derivation of solver runs and their checks (spec §3, §4).

A contract's tags coalesce onto the fixed run-configuration taxonomy (Global Constraints): tags
that can share one solve land on one :class:`Run`; the genuinely different searches (brave vs
cautious vs optimization vs full enumeration) do not. Each run carries its checks as self-describing
:class:`~elenctic.checks.Check`s, so a test reads ``check.label`` with no solve (dx#9 / option C).

The subtleties under test: ``@expect sat`` rides an existing full enumeration (which populates
``observables``) else a cheap ``DEFAULT`` solve, never a cautious/brave/optimisation run; an
``unknown``-*binding* ``@query`` escalates to one full ``ENUM_ALL`` enumeration that yields both ⋂
and ⋃ (ground and yes/no queries read ⋂ alone); and ``@cost`` rides the shared ``OPT_ENUM`` when an
optimal-base mode is present, else a cheap single-optimum ``OPT``.
"""

import pytest
from clingo import Function
from hypothesis import given
from hypothesis import strategies as st

from elenctic.expectation import Sat, parse
from elenctic.query import Answer, BindingQuery, GroundQuery, QueryLiteral, Var
from elenctic.run import (
    BRAVE_ALL,
    CAUTIOUS_ALL,
    DEFAULT,
    ENUM_ALL,
    OPT,
    OPT_ENUM,
    Run,
    runs_for,
)

TAXONOMY = frozenset({DEFAULT, ENUM_ALL, BRAVE_ALL, CAUTIOUS_ALL, OPT_ENUM, OPT})


def runs(contract: str) -> tuple[Run, ...]:
    return runs_for(parse(contract))


def labels(run: Run) -> set[str]:
    return {check.label for check in run.checks}  # static — no solve (option C)


def configs(contract: str) -> set[tuple[str, ...]]:
    return {run.args for run in runs(contract)}


def run_at(contract: str, args: tuple[str, ...]) -> Run:
    return next(run for run in runs(contract) if run.args == args)


# --- the core routing: each model-bearing tag rides its taxonomy cell ---


@pytest.mark.parametrize(
    ("contract", "config", "label"),
    [
        pytest.param("% @expect sat\n% @model { a }\n", ENUM_ALL, "@model", id="model"),
        pytest.param("% @expect sat\n% @count 2\n", ENUM_ALL, "@count", id="count"),
        pytest.param("% @expect sat\n% @assign { x=1 }\n", ENUM_ALL, "@assign", id="assign"),
        pytest.param(
            "% @expect sat\n% @cautious { a }\n", CAUTIOUS_ALL, "@cautious", id="cautious"
        ),
        pytest.param("% @expect sat\n% @brave { a }\n", BRAVE_ALL, "@brave", id="brave"),
        pytest.param("% @expect sat\n% @optimal { a }\n", OPT_ENUM, "@optimal", id="optimal"),
        pytest.param(
            "% @expect sat\n% @cautious optimal { a }\n",
            OPT_ENUM,
            "@cautious optimal",
            id="cautious-optimal",
        ),
        pytest.param(
            "% @expect sat\n% @brave optimal { a }\n",
            OPT_ENUM,
            "@brave optimal",
            id="brave-optimal",
        ),
        pytest.param(
            "% @expect sat\n% @count optimal 1\n", OPT_ENUM, "@count optimal", id="count-optimal"
        ),
    ],
)
def test_model_bearing_tag_rides_its_taxonomy_config(
    contract: str, config: tuple[str, ...], label: str
) -> None:
    assert label in labels(run_at(contract, config))


# --- @expect sat: ride a full enumeration if one exists, else a cheap DEFAULT solve ---


def test_expect_sat_alone_is_one_default_run() -> None:
    derived = runs("% @expect sat\n")
    assert len(derived) == 1
    assert derived[0].args == DEFAULT
    assert labels(derived[0]) == {"@expect sat"}


def test_expect_sat_rides_an_existing_full_enumeration() -> None:
    # @model already forces ENUM_ALL (which populates `observables`), so @expect sat coalesces
    # onto it — one solve, not two.
    derived = runs("% @expect sat\n% @model { a }\n")
    assert len(derived) == 1
    assert derived[0].args == ENUM_ALL
    assert labels(derived[0]) == {"@model", "@expect sat"}


def test_expect_sat_takes_default_alongside_a_cautious_run() -> None:
    # A cautious run reports only ⋂, not `observables`, so @expect sat cannot ride it; it gets its
    # own cheap DEFAULT solve.
    assert configs("% @expect sat\n% @cautious { a }\n") == {CAUTIOUS_ALL, DEFAULT}
    assert labels(run_at("% @expect sat\n% @cautious { a }\n", DEFAULT)) == {"@expect sat"}


def test_expect_sat_takes_default_under_optimisation_only() -> None:
    # OPT_ENUM populates optimal_observables, not observables, so @expect sat still needs DEFAULT.
    contract = "% @expect sat\n% @optimal { a }\n"
    assert configs(contract) == {OPT_ENUM, DEFAULT}
    assert labels(run_at(contract, DEFAULT)) == {"@expect sat"}


# --- @expect unsat: a single default run, nothing else ---


def test_unsat_is_one_default_run_with_only_expect_unsat() -> None:
    derived = runs("% @expect unsat\n")
    assert len(derived) == 1
    assert derived[0].args == DEFAULT
    assert labels(derived[0]) == {"@expect unsat"}


# --- @query routing (the bridge theorem and the unknown-binding escalation) ---


def test_ground_query_shares_the_cautious_run() -> None:
    # The bridge theorem (spec §2.4): a positive ground @query yes { L } reads ⋂, the same run a
    # @cautious { L } needs — so they coalesce onto the one cautious solve.
    contract = "% @expect sat\n% @cautious { a }\n% @query yes { a }\n"
    assert {"@cautious", "@query"} <= labels(run_at(contract, CAUTIOUS_ALL))


def test_unknown_binding_query_rides_one_full_enumeration() -> None:
    # An unknown-binding query needs both ⋂ and ⋃; one ENUM_ALL solve yields both (reconciling the
    # spec's "two runs" wording with the one-enumeration realisation). @expect sat rides it too.
    contract = "% @expect sat\n% @query unknown { p(X) } = { a }\n"
    assert configs(contract) == {ENUM_ALL}
    assert labels(run_at(contract, ENUM_ALL)) == {"@query", "@expect sat"}


def test_ground_unknown_query_uses_cautious_not_enum_all() -> None:
    # A *ground* query reads ⋂ for every answer (yes/no/unknown), so it stays on CAUTIOUS_ALL; only
    # an unknown *binding* query needs ⋃.
    contract = "% @expect sat\n% @query unknown { a }\n"
    assert "@query" in labels(run_at(contract, CAUTIOUS_ALL))
    assert ENUM_ALL not in configs(contract)


def test_yes_binding_query_uses_cautious() -> None:
    # A yes-binding query reads ⋂ alone, so it does not escalate to a full enumeration.
    contract = "% @expect sat\n% @query yes { p(X) } = { a }\n"
    assert "@query" in labels(run_at(contract, CAUTIOUS_ALL))
    assert ENUM_ALL not in configs(contract)


# --- @cost: cheap single optimum, unless an optimal-base mode forces the shared enumeration ---


def test_cost_alone_uses_the_cheap_single_optimum() -> None:
    contract = "% @expect sat\n% @cost { 8 }\n"
    assert "@cost" in labels(run_at(contract, OPT))
    assert OPT_ENUM not in configs(contract)
    assert ENUM_ALL not in configs(contract)


def test_cost_with_an_optimal_base_rides_the_shared_opt_enum() -> None:
    contract = "% @expect sat\n% @cost { 8 }\n% @count optimal 2\n"
    assert {"@cost", "@count optimal"} <= labels(run_at(contract, OPT_ENUM))
    assert OPT not in configs(contract)


# --- coalescing: shared solves merge, and no tag is dropped or invented ---


def test_optimal_modes_coalesce_onto_one_opt_enum_solve() -> None:
    contract = (
        "% @expect sat\n"
        "% @optimal { a }\n"
        "% @cautious optimal { a }\n"
        "% @brave optimal { a }\n"
        "% @count optimal 1\n"
    )
    opt_enum_runs = [run for run in runs(contract) if run.args == OPT_ENUM]
    assert len(opt_enum_runs) == 1  # one shared enumeration of Opt(P), not four
    assert {
        "@optimal",
        "@cautious optimal",
        "@brave optimal",
        "@count optimal",
    } <= labels(opt_enum_runs[0])


def test_every_tag_becomes_exactly_one_check_no_drop_no_duplicate() -> None:
    contract = (
        "% @expect sat\n% @model { a }\n% @cautious { a }\n% @brave { a }\n% @query yes { a }\n"
    )
    derived = runs(contract)
    all_labels = [check.label for run in derived for check in run.checks]
    assert sorted(all_labels) == ["@brave", "@cautious", "@expect sat", "@model", "@query"]
    assert len(all_labels) == len(set(all_labels))  # each tag yields exactly one check


def test_runs_for_is_deterministic() -> None:
    contract = "% @expect sat\n% @model { a }\n% @cautious { a }\n% @query yes { a }\n"
    first = sorted((run.args, tuple(sorted(labels(run)))) for run in runs(contract))
    second = sorted((run.args, tuple(sorted(labels(run)))) for run in runs(contract))
    assert first == second


# --- a Hypothesis property: runs_for is total, onto the taxonomy, and always carries @expect ---

_GROUND = GroundQuery(Answer.yes, (Function("a"),))
_BIND_YES = BindingQuery(
    Answer.yes, QueryLiteral("p", True, (Var("X"),)), frozenset({(Function("a"),)})
)
_BIND_UNKNOWN = BindingQuery(
    Answer.unknown, QueryLiteral("p", True, (Var("X"),)), frozenset({(Function("a"),)})
)
_LIT = frozenset({Function("a")})


@st.composite
def _sats(draw: st.DrawFn) -> Sat:
    """An arbitrary structurally-valid ``Sat`` (runs_for derives runs from any Sat; cross-tag
    well-formedness is ``parse``'s concern, not runs_for's)."""
    optional_lit = st.sampled_from([_LIT, frozenset()])
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
        assign=draw(st.sampled_from([frozenset({(Function("x"), 1)}), None])),
        queries=tuple(
            draw(st.lists(st.sampled_from([_GROUND, _BIND_YES, _BIND_UNKNOWN]), max_size=3))
        ),
    )


@given(_sats())
def test_runs_for_is_total_onto_the_taxonomy_and_always_expects(sat: Sat) -> None:
    derived = runs_for(sat)  # total: never raises on any structurally-valid Sat
    assert all(run.args in TAXONOMY for run in derived)  # onto the fixed taxonomy
    assert all(check.label for run in derived for check in run.checks)  # every check is labelled
    expects = [
        check.label for run in derived for check in run.checks if check.label.startswith("@expect")
    ]
    assert expects == ["@expect sat"]  # exactly one @expect sat, always present
