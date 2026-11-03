"""Judge one claim against what a search found, whatever sort of search it was."""

from elenctic.by_models import entailed, from_models
from elenctic.contract import Claim, Costs, Entails, Reading, Satisfiable, denies_answer_sets
from elenctic.determination import (
    Consequences,
    Consistent,
    Cost,
    Determination,
    Exhausted,
    Inconclusive,
    Inconsistent,
    Incumbent,
    Models,
    Optimized,
    Optimum,
    Refutation,
    These,
    Truncation,
)
from elenctic.verdicts import Finding, Verdict


def _consequent(
    reading: Reading, found: Consequences, conclusion: Exhausted | Truncation
) -> tuple[Verdict, str]:
    """Judge from native consequences, which settle a claim about them only once exhausted.

    An empty claim is the exception: it holds of whatever was found.
    """
    if isinstance(reading, Entails):
        closed = conclusion is Exhausted.EXHAUSTED
        if reading.literals and not closed:
            return Verdict.UNDECIDED, f"search ended: {conclusion}"
        return entailed(reading, found.literals, closed=closed)
    return Verdict.when(holds=reading == Satisfiable(expected=True)), "an answer set exists"


def _cost(claim: Costs, cost: Cost) -> tuple[Verdict, str]:
    detail = f"{_levels(claim.cost)} expected, optimum is {_levels(cost)}"
    return Verdict.when(holds=claim.cost == cost), detail


def _levels(cost: Cost) -> str:
    return "(" + ", ".join(map(str, cost)) + ")"


def _optimal(
    reading: Reading, found: Optimum, conclusion: Exhausted | Truncation
) -> tuple[Verdict, str]:
    """Judge from a proven optimum and the optimal models found, all of them if exhausted."""
    if isinstance(reading, Costs):
        return _cost(reading, found.cost)
    return from_models(reading, Consistent(found.models, conclusion))


def _core_text(refutation: These) -> str:
    core = ", ".join(sorted(str(a.literal) for a in refutation.core))
    caveat = (
        "" if refutation.minimal else "; the search was cut short, so the core may not be minimal"
    )
    return f"no answer set satisfies the assumptions ({core}){caveat}"


def _inconsistent(reading: Reading, refutation: Refutation) -> tuple[Verdict, str]:
    why = _core_text(refutation) if isinstance(refutation, These) else "AS(P) = ∅"
    refuted = reading == Satisfiable(expected=False) or denies_answer_sets(reading)
    return Verdict.when(holds=refuted), why


type Found = Determination[Models] | Determination[Consequences] | Determination[Optimized]


def judge(claim: Claim, found: Found) -> Finding:
    """Judge one claim against the search over its scenario."""
    return Finding(claim, *_verdict(claim.reading, found))


def _verdict(reading: Reading, found: Found) -> tuple[Verdict, str]:
    match found:
        case Inconclusive(cut):
            return Verdict.UNDECIDED, f"search ended: {cut}"
        case Inconsistent(refutation):
            return _inconsistent(reading, refutation)
        case Consistent(evidence, conclusion):
            return _evidence(reading, evidence, conclusion)


def _evidence(
    reading: Reading,
    evidence: Models | Consequences | Optimized,
    conclusion: Exhausted | Truncation,
) -> tuple[Verdict, str]:
    match evidence:
        case Models():
            return from_models(reading, Consistent(evidence, conclusion))
        case Consequences():
            return _consequent(reading, evidence, conclusion)
        case Optimum():
            return _optimal(reading, evidence, conclusion)
        case Incumbent():
            return Verdict.UNDECIDED, f"no optimum proven: search ended: {conclusion}"
