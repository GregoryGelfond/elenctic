"""The curated public API: ``elenctic``'s top-level surface is the documented, ordered one."""

import elenctic


def test_public_api_exports_the_pipeline_and_outcome_surface() -> None:
    expected = {
        # the pipeline
        "Case",
        "discover",
        "parse",
        "Expectation",
        "Sat",
        "Unsat",
        "runs_for",
        "Run",
        "Mode",
        "solve",
        "run_case",
        "case_verdict",
        "render",
        "CheckReport",
        # the outcomes
        "Determination",
        "Verdict",
        "Observable",
        "Optimum",
        # the error taxonomy
        "ContractError",
        "DiscoveryError",
        "HarnessError",
        "RoutingError",
        "SeamError",
        # the solver registry
        "Solver",
        "SOLVERS",
    }
    assert expected <= set(elenctic.__all__)
    for name in elenctic.__all__:
        assert hasattr(elenctic, name), f"__all__ names {name!r} but there is no such attribute"


def test_public_api_is_curated_not_dumped() -> None:
    # __all__ is explicitly sorted (a curated surface, dx#11 — not a dump of every importable name).
    assert elenctic.__all__ == sorted(elenctic.__all__)
    # internals stay internal: the Consistent shapes, accessors, check builders are not exported.
    for internal in ("ConsistentWitness", "witness_of", "has_model", "Field", "_Collector"):
        assert internal not in elenctic.__all__
