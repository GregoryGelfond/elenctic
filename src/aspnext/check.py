"""Judge the claims of a contract against what a search found."""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum

from clingo import Symbol

from aspnext.contract import (
    Asks,
    Binds,
    Census,
    Claim,
    Entails,
    Reading,
    Satisfiable,
    Witness,
    braces,
    is_case,
    parse_contract,
    render,
)
from aspnext.determination import (
    Consistent,
    Determination,
    Exhausted,
    Inconclusive,
    Inconsistent,
    Mode,
    Models,
    Refutation,
    Truncation,
    WorldView,
    world_view,
)
from aspnext.engine import Fault, Grounded, Interrupt, Limits, Locus, Program, ground
from aspnext.literals import AnswerSet, Scenario
from aspnext.query import Answer, answer, bindings

NO_LIMITS = Limits()


class Verdict(StrEnum):
    PASS = "pass"  # noqa: S105
    FAIL = "fail"
    UNDECIDED = "undecided"


@dataclass(frozen=True, slots=True)
class Finding:
    """A claim, the verdict on it, and what was expected against what was found."""

    claim: Claim
    verdict: Verdict
    detail: str

    @property
    def claim_text(self) -> str:
        return render(self.claim)


@dataclass(frozen=True, slots=True)
class Report:
    source: str
    findings: tuple[Finding, ...]

    @property
    def verdict(self) -> Verdict:
        """Fail if any claim fails, else undecided if any is, else pass."""
        verdicts = {f.verdict for f in self.findings}
        return next((v for v in (Verdict.FAIL, Verdict.UNDECIDED) if v in verdicts), Verdict.PASS)


def _existential(*, found: bool, closed: bool) -> Verdict:
    """Settle a claim a model can witness: a model upholds it, only a closed search refutes it."""
    return Verdict.PASS if found else Verdict.FAIL if closed else Verdict.UNDECIDED


def _universal(*, refuted: bool, closed: bool) -> Verdict:
    """Settle a claim a model can refute: a model refutes it, only a closed search upholds it."""
    return Verdict.FAIL if refuted else Verdict.PASS if closed else Verdict.UNDECIDED


def _count(claim: Census, shown: frozenset[AnswerSet], *, closed: bool) -> tuple[Verdict, str]:
    seen = len(shown)
    verdict = _universal(
        refuted=seen > claim.count or (closed and seen < claim.count), closed=closed
    )
    return verdict, f"{claim.count} expected, {seen} distinct shown answer sets"


def _entails(claim: Entails, shown: frozenset[AnswerSet], *, closed: bool) -> tuple[Verdict, str]:
    cautious = claim.mode is Mode.CAUTIOUS
    held = frozenset.intersection(*shown) if cautious else frozenset().union(*shown)
    missing = claim.literals - held
    verdict = (
        _universal(refuted=bool(missing), closed=closed)
        if cautious
        else _existential(found=not missing, closed=closed)
    )
    detail = f"{braces(claim.literals)} ⊆ {'⋂' if cautious else '∪'} AS(P) = {braces(held)}"
    return verdict, detail + (f" (missing: {braces(missing)})" if missing else "")


def _asked(claim: Asks | Binds, view: WorldView) -> tuple[Verdict, str]:
    match claim:
        case Asks(expected, query):
            found = answer(query, view)
            return _agree(found is expected), f"{expected} expected, answer is {found}"
        case Binds(expected, pattern, wanted):
            partition = bindings(pattern, view)
            got = {Answer.YES: partition.yes, Answer.NO: partition.no}.get(
                expected, partition.unknown
            )
            return _agree(
                got == wanted
            ), f"{expected} bindings expected {_rows(wanted)}, found {_rows(got)}"


def _rows(found: frozenset[tuple[Symbol, ...]]) -> str:
    return "{ " + ", ".join(sorted("(" + ",".join(map(str, row)) + ")" for row in found)) + " }"


def _agree(holds: bool) -> Verdict:  # noqa: FBT001
    return Verdict.PASS if holds else Verdict.FAIL


def _consistent(reading: Reading, found: Consistent[Models]) -> tuple[Verdict, str]:
    shown = frozenset(model.shown for model in found.evidence.all)
    closed = found.conclusion is Exhausted.EXHAUSTED
    match reading:
        case Satisfiable(expected):
            return _agree(expected), "an answer set exists"
        case Census():
            return _count(reading, shown, closed=closed)
        case Witness(literals):
            seen = literals in shown
            return _existential(
                found=seen, closed=closed
            ), f"{braces(literals)} shown by an answer set: {'yes' if seen else 'no'}"
        case Entails():
            return _entails(reading, shown, closed=closed)
        case Asks() | Binds():
            view = world_view(found)
            if isinstance(view, Truncation):
                return Verdict.UNDECIDED, f"search ended: {view}"
            return _asked(reading, view)


def _inconsistent(reading: Reading, refutation: Refutation) -> tuple[Verdict, str]:
    blamed = ", ".join(sorted(str(a.literal) for a in refutation.core))
    why = f"no answer set satisfies the assumptions ({blamed})" if blamed else "AS(P) = ∅"
    return _agree(reading in (Satisfiable(expected=False), Census(0))), why


def judge(claim: Claim, found: Determination[Models]) -> Finding:
    """Judge one claim against the search over its scenario."""
    return Finding(claim, *_verdict(claim.reading, found))


def _verdict(reading: Reading, found: Determination[Models]) -> tuple[Verdict, str]:
    match found:
        case Inconclusive(cut):
            return Verdict.UNDECIDED, f"search ended: {cut}"
        case Inconsistent(refutation):
            return _inconsistent(reading, refutation)
        case Consistent():
            return _consistent(reading, found)


def _by_scenario(claims: Iterable[Claim]) -> dict[Scenario, list[Claim]]:
    groups: dict[Scenario, list[Claim]] = {}
    for claim in claims:
        groups.setdefault(claim.scenario, []).append(claim)
    return groups


def _limits(group: list[Claim], limits: Limits) -> Limits:
    """Cap the search at one model for a group that only asks whether an answer set exists."""
    return (
        replace(limits, models=1)
        if all(isinstance(c.reading, Satisfiable) for c in group)
        else limits
    )


def _judge_group(
    grounded: Grounded,
    scenario: Scenario,
    group: list[Claim],
    limits: Limits,
    interrupt: Interrupt | None,
) -> list[Finding]:
    found = grounded.solve(scenario, limits=_limits(group, limits), interrupt=interrupt)
    return [judge(claim, found) for claim in group]


def check(
    program: Program,
    *,
    limits: Limits = NO_LIMITS,
    interrupt: Interrupt | None = None,
) -> Report | Fault | None:
    """Check the contract written in `program`; `None` if it carries none."""
    if not is_case(program.text):
        return None
    contract = parse_contract(program.text, program.source)
    if contract.diagnostics:
        return Fault(Locus.REQUEST, contract.diagnostics)
    grounded = ground(program)
    if isinstance(grounded, Fault):
        return grounded
    judged = {
        claim: finding
        for scenario, group in _by_scenario(contract.claims).items()
        for claim, finding in zip(
            group, _judge_group(grounded, scenario, group, limits, interrupt), strict=True
        )
    }
    return Report(program.source, tuple(judged[claim] for claim in contract.claims))
