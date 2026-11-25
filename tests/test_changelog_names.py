"""Every name the library exports beyond 1.0.0's is named where 1.1.0's changes are."""

import re
from pathlib import Path

import elenctic

EXPORTED_BY_1_0 = frozenset(
    [
        "All",
        "Answer",
        "AnswerSet",
        "AnswerSets",
        "Any",
        "Asks",
        "Assignment",
        "Assigns",
        "Assumption",
        "Atoms",
        "Bindings",
        "Binds",
        "Census",
        "Child",
        "Claim",
        "Compound",
        "Conclusion",
        "Consequences",
        "Consistent",
        "Contract",
        "Cost",
        "Costs",
        "Cut",
        "Detail",
        "Determination",
        "Diagnostic",
        "Ended",
        "Entails",
        "Exhausted",
        "Extension",
        "Facts",
        "Fault",
        "Finding",
        "Found",
        "Grounded",
        "Inconclusive",
        "Inconsistent",
        "Incumbent",
        "Interrupt",
        "Keep",
        "Limit",
        "Limits",
        "Literal",
        "Locus",
        "Mode",
        "NoAssumptions",
        "NotThese",
        "Optimized",
        "Optimum",
        "Pattern",
        "Position",
        "Program",
        "Query",
        "Range",
        "Reading",
        "Refutation",
        "Report",
        "Request",
        "Satisfiable",
        "Scenario",
        "Severity",
        "Shown",
        "Signature",
        "Solver",
        "Span",
        "Substitution",
        "Term",
        "These",
        "Truncation",
        "Truth",
        "Unifier",
        "Valuation",
        "Variable",
        "Verdict",
        "Witness",
        "WorldView",
        "answer",
        "bindings",
        "check",
        "evaluate",
        "ground",
        "judge",
        "mgu",
        "optimal_view",
        "parse_contract",
        "render",
        "solve",
        "unify",
        "world_view",
    ]
)

CHANGELOG = Path(__file__).parent.parent / "CHANGELOG.md"


def _section(version: str) -> str:
    text = CHANGELOG.read_text()
    start = text.index(f"## [{version}]")
    return text[start : text.index("\n## [", start + 1)]


def test_each_name_exported_since_1_0_is_in_the_1_1_changes() -> None:
    section = _section("1.1.0")
    unnamed = [
        name
        for name in sorted(set(elenctic.__all__) - EXPORTED_BY_1_0)
        if re.search(rf"`{re.escape(name)}[`(.]", section) is None
    ]
    assert unnamed == []
