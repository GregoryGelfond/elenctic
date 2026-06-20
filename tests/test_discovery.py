"""``discovery.discover`` — the pure, total corpus walk parameterized by a ``Layout`` (spec §5).

Discovery pairs each instance with its applicable encoding(s) (clingo baseline + ``-clingcon``
variant), treats a self-contained encoding as its own case, detects flatness vs ``variant-NN``
*structurally*, and is where the §2.2-rule-4 preconditions that need the encoding are checked as
loud errors: optimization (``#minimize``/``#maximize``/``:~``), a theory solver (``@assign`` →
clingcon), and the contrary literal in the shown vocabulary (``@query no``/``unknown``). A ``.lp``
file matching no convention is handled per ``Layout.on_unmatched`` — ``discover`` defines its
behaviour on every input (that is what "total" means).
"""

import logging
from pathlib import Path

import pytest

from elenctic.discovery import Case, DiscoveryError, Layout, discover
from elenctic.expectation import ContractError, Sat


def write(path: Path, text: str) -> Path:
    """Write ``text`` to ``path`` (creating parents) and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def make_layout(root: Path) -> Layout:
    """A ``Layout`` over the conventional ``encodings/`` + ``tests/cases/`` roots under ``root``."""
    return Layout(encodings_root=root / "encodings", cases_root=root / "tests" / "cases")


def solvers_of(cases: tuple[Case, ...]) -> list[str]:
    return sorted(case.solver for case in cases)


# --- pairing & corpus structure (spec §5) ---


def test_pairs_instance_with_baseline_and_clingcon(tmp_path: Path) -> None:
    write(tmp_path / "encodings/graph/reach.lp", "#show reachable/1.\n")
    write(tmp_path / "encodings/graph/reach-clingcon.lp", "#show reachable/1.\n")
    write(
        tmp_path / "tests/cases/graph/inst-01.lp",
        "% @expect sat\n% @cautious { reachable(s) }\n",
    )
    cases = discover(make_layout(tmp_path))
    assert solvers_of(cases) == ["clingcon", "clingo"]  # one case per applicable encoding
    assert all(case.instance is not None and case.instance.name == "inst-01.lp" for case in cases)


def test_self_contained_encoding_is_its_own_case(tmp_path: Path) -> None:
    write(
        tmp_path / "encodings/sendmoney/send.lp",
        "#show assign/2.\n% @expect sat\n% @count 1\n",
    )
    layout = Layout(encodings_root=tmp_path / "encodings", cases_root=tmp_path / "no-instances")
    cases = discover(layout)
    assert len(cases) == 1
    assert cases[0].instance is None
    assert cases[0].solver == "clingo"


def test_flat_domain_pairs_each_instance_with_the_sole_encoding(tmp_path: Path) -> None:
    write(tmp_path / "encodings/tsp/tour.lp", "#show tour/2.\n")
    write(tmp_path / "tests/cases/tsp/inst-a.lp", "% @expect sat\n")
    write(tmp_path / "tests/cases/tsp/inst-b.lp", "% @expect sat\n")
    cases = discover(make_layout(tmp_path))
    assert len(cases) == 2
    names = sorted(case.instance.name for case in cases if case.instance)
    assert names == ["inst-a.lp", "inst-b.lp"]


def test_variant_dir_pairs_with_its_matching_variant_encoding(tmp_path: Path) -> None:
    write(tmp_path / "encodings/tsp/tsp-variant-01.lp", "#show tour/2.\n")
    write(tmp_path / "encodings/tsp/tsp-variant-02.lp", "#show tour/2.\n")
    write(tmp_path / "tests/cases/tsp/variant-01/test-01.lp", "% @expect sat\n")
    cases = discover(make_layout(tmp_path))
    assert len(cases) == 1
    assert cases[0].encoding.stem == "tsp-variant-01"  # only variant-01, not variant-02


def test_variant_match_is_boundary_not_substring(tmp_path: Path) -> None:
    # dx#7: variant-1 must NOT pick the variant-10 encoding (substring) — only the boundary match.
    write(tmp_path / "encodings/g/g-variant-1.lp", "#show p/0.\n")
    write(tmp_path / "encodings/g/g-variant-10.lp", "#show p/0.\n")
    write(tmp_path / "tests/cases/g/variant-1/t.lp", "% @expect sat\n")
    cases = discover(make_layout(tmp_path))
    assert len(cases) == 1
    assert cases[0].encoding.stem == "g-variant-1"


def test_variant_pairs_baseline_and_clingcon_variants(tmp_path: Path) -> None:
    write(tmp_path / "encodings/tsp/tsp-variant-01.lp", "#show tour/2.\n")
    write(tmp_path / "encodings/tsp/tsp-variant-01-clingcon.lp", "#show tour/2.\n")
    write(tmp_path / "tests/cases/tsp/variant-01/test-01.lp", "% @expect sat\n")
    cases = discover(make_layout(tmp_path))
    assert solvers_of(cases) == ["clingcon", "clingo"]


def test_discovery_output_is_deterministic_and_sorted(tmp_path: Path) -> None:
    write(tmp_path / "encodings/b/e.lp", "#show p/0.\n% @expect sat\n")  # self-contained
    write(tmp_path / "encodings/a/e.lp", "#show p/0.\n")
    write(tmp_path / "tests/cases/a/i2.lp", "% @expect sat\n")
    write(tmp_path / "tests/cases/a/i1.lp", "% @expect sat\n")
    layout = make_layout(tmp_path)
    order = [c.instance.name if c.instance else c.encoding.parent.name for c in discover(layout)]
    assert order == ["i1.lp", "i2.lp", "b"]  # domain a's instances (sorted), then domain b
    assert order == [  # idempotent across calls
        c.instance.name if c.instance else c.encoding.parent.name for c in discover(layout)
    ]


def test_case_files_is_the_grounding_load_order(tmp_path: Path) -> None:
    encoding = write(tmp_path / "encodings/g/e.lp", "#show p/0.\n")
    instance = write(tmp_path / "tests/cases/g/i.lp", "% @expect sat\n")
    (paired,) = discover(make_layout(tmp_path))
    assert paired.files == (encoding, instance)  # encoding first, then instance
    standalone = write(tmp_path / "encodings/s/e.lp", "#show p/0.\n% @expect sat\n")
    cases = discover(Layout(encodings_root=tmp_path / "encodings/s", cases_root=tmp_path / "none"))
    assert cases[0].files == (standalone,)


# --- comment robustness: a directive in prose must not satisfy a gate (B1) ---


def test_minimize_in_a_comment_does_not_satisfy_optimization(tmp_path: Path) -> None:
    # A `#minimize` mentioned only in a comment is NOT an optimizing directive — the gate must hold.
    write(tmp_path / "encodings/x/e.lp", "% TODO: maybe add a #minimize here\n#show p/0.\n")
    write(tmp_path / "tests/cases/x/i.lp", "% @expect sat\n% @cost { 1 }\n")
    with pytest.raises(DiscoveryError, match=r"minimize|maximize|optimi"):
        discover(make_layout(tmp_path))


def test_real_minimize_with_a_trailing_comment_satisfies_optimization(tmp_path: Path) -> None:
    write(tmp_path / "encodings/x/e.lp", "#show a/0.\n#minimize { 1,a : a }.  % the objective\n")
    write(tmp_path / "tests/cases/x/i.lp", "% @expect sat\n% @cost { 1 }\n")
    cases = discover(make_layout(tmp_path))
    assert len(cases) == 1


@pytest.mark.parametrize(
    "encoding_text",
    [
        pytest.param("% #show -reachable/1.\n#show reachable/1.\n", id="line-comment"),
        pytest.param("%* #show -reachable/1. *%\n#show reachable/1.\n", id="block-comment"),
    ],
)
def test_commented_show_does_not_pollute_the_shown_vocabulary(
    tmp_path: Path, encoding_text: str
) -> None:
    # The commented `-reachable` must not count as shown, so the `@query no` over it still fails.
    write(tmp_path / "encodings/g/e.lp", encoding_text)
    write(tmp_path / "tests/cases/g/i.lp", "% @expect sat\n% @query no { reachable(x) }\n")
    with pytest.raises(DiscoveryError, match=r"-reachable"):
        discover(make_layout(tmp_path))


def test_percent_inside_a_string_term_is_not_a_comment(tmp_path: Path) -> None:
    # The comment stripper is quote-aware: a `%` inside a string must not blank the line's rest.
    write(tmp_path / "encodings/g/e.lp", 'label("50% done").\n#show label/1.\n')
    write(tmp_path / "tests/cases/g/i.lp", "% @expect sat\n")
    (case,) = discover(make_layout(tmp_path))
    assert case.shown == frozenset({"label"})


# --- provenance (dx#2 / the docs-substrate ledger): the case is provenance-rich ---


def test_contract_source_is_the_instance_when_paired(tmp_path: Path) -> None:
    write(tmp_path / "encodings/g/e.lp", "#show p/0.\n")
    instance = write(tmp_path / "tests/cases/g/i.lp", "% @expect sat\n")
    (case,) = discover(make_layout(tmp_path))
    assert case.contract_source == instance


def test_contract_source_is_the_encoding_when_self_contained(tmp_path: Path) -> None:
    encoding = write(tmp_path / "encodings/s/e.lp", "#show p/0.\n% @expect sat\n")
    cases = discover(Layout(encodings_root=tmp_path / "encodings", cases_root=tmp_path / "none"))
    assert cases[0].contract_source == encoding


def test_notes_survive_discovery_for_the_docs_substrate(tmp_path: Path) -> None:
    # The case must not lossily flatten the contract: @note prose reaches the Case via expectation.
    write(tmp_path / "encodings/g/e.lp", "#show p/0.\n")
    write(tmp_path / "tests/cases/g/i.lp", "% @expect sat\n% @note the budget forces a detour\n")
    (case,) = discover(make_layout(tmp_path))
    assert case.expectation.notes == ("the budget forces a detour",)


def test_malformed_contract_propagates_a_sourced_error(tmp_path: Path) -> None:
    # A parse error during discovery is already provenance-rich (parse(source=path)); it propagates
    # naming the offending file, rather than being swallowed.
    write(tmp_path / "encodings/g/e.lp", "#show p/0.\n")
    write(tmp_path / "tests/cases/g/bad.lp", "% @model { a }\n")  # no @expect — rule 1
    with pytest.raises(ContractError, match=r"bad\.lp"):
        discover(make_layout(tmp_path))


# --- the §2.2-rule-4 preconditions, checked at discovery (spec §5) ---


def test_assign_precondition_requires_clingcon(tmp_path: Path) -> None:
    write(tmp_path / "encodings/x/e.lp", "#show.\n")  # baseline (clingo), no theory
    write(tmp_path / "tests/cases/x/i.lp", "% @expect sat\n% @assign { v=1 }\n")
    with pytest.raises(DiscoveryError, match=r"clingcon"):
        discover(make_layout(tmp_path))


def test_assign_on_a_clingcon_encoding_is_accepted(tmp_path: Path) -> None:
    write(tmp_path / "encodings/x/e-clingcon.lp", "#show.\n")
    write(tmp_path / "tests/cases/x/i.lp", "% @expect sat\n% @assign { v=1 }\n")
    (case,) = discover(make_layout(tmp_path))
    assert case.solver == "clingcon"


@pytest.mark.parametrize(
    "contract",
    [
        pytest.param("% @expect sat\n% @cost { 1 }\n", id="cost"),
        pytest.param("% @expect sat\n% @optimal { p }\n", id="optimal-witness"),
        pytest.param("% @expect sat\n% @cautious optimal { p }\n", id="cautious-optimal"),
        pytest.param("% @expect sat\n% @count optimal 1\n", id="count-optimal"),
    ],
)
def test_optimization_precondition_requires_minimize(tmp_path: Path, contract: str) -> None:
    write(tmp_path / "encodings/x/e.lp", "#show p/0.\n")  # no #minimize/#maximize/:~
    write(tmp_path / "tests/cases/x/i.lp", contract)
    with pytest.raises(DiscoveryError, match=r"minimize|maximize|optimi"):
        discover(make_layout(tmp_path))


@pytest.mark.parametrize(
    "encoding_body",
    [
        pytest.param("#minimize { 1,a : a }.\n", id="minimize"),
        pytest.param("#maximize { 1,a : a }.\n", id="maximize"),
        pytest.param(":~ a. [1@1]\n", id="weak-constraint"),
    ],
)
def test_optimization_precondition_satisfied_by_an_optimizing_construct(
    tmp_path: Path, encoding_body: str
) -> None:
    write(tmp_path / "encodings/x/e.lp", f"#show a/0.\n{encoding_body}")
    write(tmp_path / "tests/cases/x/i.lp", "% @expect sat\n% @cost { 1 }\n")
    (case,) = discover(make_layout(tmp_path))
    assert isinstance(case.expectation, Sat)
    assert case.expectation.cost == (1,)


@pytest.mark.parametrize(
    "contract",
    [
        pytest.param("% @expect sat\n% @query no { reachable(x) }\n", id="ground-no"),
        pytest.param("% @expect sat\n% @query unknown { reachable(x) }\n", id="ground-unknown"),
        pytest.param("% @expect sat\n% @query no { reachable(X) } = { a }\n", id="binding-no"),
        # an unknown binding reads -q off ⋃ too, so it needs the contrary shown (sounder than the
        # spec letter, which omits the unknown-binding form — reconciliation ledgered).
        pytest.param(
            "% @expect sat\n% @query unknown { reachable(X) } = { a }\n", id="binding-unknown"
        ),
        # a strong-negation conjunct's contrary is the positive literal.
        pytest.param("% @expect sat\n% @query no { -reachable(x) }\n", id="ground-no-strong-neg"),
    ],
)
def test_query_no_or_unknown_requires_contrary_in_shown_vocabulary(
    tmp_path: Path, contract: str
) -> None:
    # The encoding shows neither `reachable` nor `-reachable`, so every needed contrary is absent —
    # each query (ground no/unknown, non-empty/unknown binding, strong-neg conjunct) is rejected.
    write(tmp_path / "encodings/g/e.lp", "#show maybe/1.\n")
    write(tmp_path / "tests/cases/g/i.lp", contract)
    with pytest.raises(DiscoveryError, match=r"shown|contrary|reachable"):
        discover(make_layout(tmp_path))


def test_query_no_accepted_when_the_contrary_is_shown(tmp_path: Path) -> None:
    write(tmp_path / "encodings/g/e.lp", "#show reachable/1.\n#show -reachable/1.\n")
    write(tmp_path / "tests/cases/g/i.lp", "% @expect sat\n% @query no { reachable(x) }\n")
    (case,) = discover(make_layout(tmp_path))
    assert "-reachable" in case.shown


def test_empty_no_binding_does_not_require_a_contrary(tmp_path: Path) -> None:
    # §2.2 rule 4's "non-empty no binding" carve-out: an empty no-set is vacuously satisfiable
    # without the contrary shown, so it must NOT be rejected (the M1 spec-letter fix).
    write(tmp_path / "encodings/g/e.lp", "#show reachable/1.\n")  # -reachable NOT shown
    write(tmp_path / "tests/cases/g/i.lp", "% @expect sat\n% @query no { reachable(X) } = { }\n")
    cases = discover(make_layout(tmp_path))
    assert len(cases) == 1


def test_negative_goal_binding_needs_the_positive_contrary(tmp_path: Path) -> None:
    # The contrary of the goal `-blocked` is `blocked`; shown → accepted, unshown → rejected.
    write(tmp_path / "encodings/g/ok.lp", "#show blocked/1.\n#show -blocked/1.\n")
    write(tmp_path / "tests/cases/g/i.lp", "% @expect sat\n% @query no { -blocked(X) } = { a }\n")
    (case,) = discover(make_layout(tmp_path))
    assert "blocked" in case.shown
    write(tmp_path / "encodings/h/no-pos.lp", "#show -blocked/1.\n")  # positive `blocked` NOT shown
    write(tmp_path / "tests/cases/h/i.lp", "% @expect sat\n% @query no { -blocked(X) } = { a }\n")
    with pytest.raises(DiscoveryError, match=r"blocked"):
        discover(make_layout(tmp_path))


def test_query_yes_does_not_require_a_contrary(tmp_path: Path) -> None:
    # A yes-query reads the positive literal off ⋂; only no/unknown read the contrary (§2.2 rule 4).
    write(tmp_path / "encodings/g/e.lp", "#show reachable/1.\n")
    write(tmp_path / "tests/cases/g/i.lp", "% @expect sat\n% @query yes { reachable(x) }\n")
    cases = discover(make_layout(tmp_path))
    assert len(cases) == 1


# --- the shown vocabulary: signature, strong-negation, conditional, and bare #show (dx#5) ---


def test_show_signature_and_strong_negation_forms_are_parsed(tmp_path: Path) -> None:
    write(tmp_path / "encodings/g/e.lp", "#show reachable/1.\n#show -reachable/1.\n")
    write(tmp_path / "tests/cases/g/i.lp", "% @expect sat\n")
    (case,) = discover(make_layout(tmp_path))
    assert case.shown == frozenset({"reachable", "-reachable"})


def test_show_conditional_term_form_is_parsed(tmp_path: Path) -> None:
    # dx#5: `#show t : body.` shows a term; the shown vocabulary records the term's functor.
    write(tmp_path / "encodings/g/e.lp", "#show reachable(X) : edge(X, Y).\n")
    write(tmp_path / "tests/cases/g/i.lp", "% @expect sat\n")
    (case,) = discover(make_layout(tmp_path))
    assert case.shown == frozenset({"reachable"})


def test_bare_show_shows_nothing(tmp_path: Path) -> None:
    # send-money-clingcon ends in `#show.` — shown atoms empty; the answer lives in the assignment.
    write(tmp_path / "encodings/s/e.lp", "#show.\n")
    write(tmp_path / "tests/cases/s/i.lp", "% @expect sat\n")
    (case,) = discover(make_layout(tmp_path))
    assert case.shown == frozenset()


# --- totality: on_unmatched policy, and non-.lp files ignored (spec §5) ---


def test_non_lp_files_are_ignored(tmp_path: Path) -> None:
    write(tmp_path / "encodings/g/e.lp", "#show p/0.\n")
    write(tmp_path / "tests/cases/g/stray.txt", "not a case")  # only .lp participates
    write(tmp_path / "tests/cases/g/i.lp", "% @expect sat\n")
    cases = discover(make_layout(tmp_path))
    assert len(cases) == 1


def test_unmatched_instance_domain_errors_by_default(tmp_path: Path) -> None:
    # An instance whose domain has no encoding matches no convention → loud error by default.
    write(tmp_path / "encodings/g/e.lp", "#show p/0.\n")
    write(tmp_path / "tests/cases/g/ok.lp", "% @expect sat\n")  # domain g is matched
    write(tmp_path / "tests/cases/orphan/i.lp", "% @expect sat\n")  # domain orphan has no encoding
    with pytest.raises(DiscoveryError, match=r"orphan|no encoding|matches no"):
        discover(make_layout(tmp_path))


def test_unmatched_instance_is_skipped_with_log_when_configured(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    write(tmp_path / "encodings/g/e.lp", "#show p/0.\n")
    write(tmp_path / "tests/cases/g/i.lp", "% @expect sat\n")
    write(tmp_path / "tests/cases/orphan/i.lp", "% @expect sat\n")
    layout = Layout(
        encodings_root=tmp_path / "encodings",
        cases_root=tmp_path / "tests" / "cases",
        on_unmatched="skip-with-log",
    )
    with caplog.at_level(logging.WARNING, logger="elenctic.discovery"):
        cases = discover(layout)
    assert len(cases) == 1  # the matched case survives; the orphan is skipped, not raised
    assert any("orphan" in record.getMessage() for record in caplog.records)


def test_variant_instance_without_a_matching_encoding_is_unmatched(tmp_path: Path) -> None:
    write(tmp_path / "encodings/tsp/tsp-variant-01.lp", "#show tour/2.\n")
    write(tmp_path / "tests/cases/tsp/variant-99/t.lp", "% @expect sat\n")  # no variant-99 encoding
    with pytest.raises(DiscoveryError, match=r"variant-99|matches no|no encoding"):
        discover(make_layout(tmp_path))
