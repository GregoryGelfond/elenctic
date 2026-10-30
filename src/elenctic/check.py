"""Judge the claims of a contract against what a search found."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from enum import StrEnum

from elenctic.contract import (
    Asks,
    Assigns,
    Binds,
    Census,
    Claim,
    Costs,
    Entails,
    Reading,
    Satisfiable,
    Witness,
    denies_answer_sets,
    over,
)
from elenctic.determination import (
    Consequences,
    Consistent,
    Cost,
    Determination,
    Exhausted,
    Inconclusive,
    Inconsistent,
    Incumbent,
    Mode,
    Model,
    Models,
    Optimized,
    Optimum,
    Range,
    Refutation,
    These,
    Truncation,
    WorldView,
    world_view,
)
from elenctic.engine import ground
from elenctic.gates import unsound
from elenctic.grounded import Grounded
from elenctic.literals import AnswerSet, Scenario, Symbol
from elenctic.program import Fault, Locus, Program
from elenctic.query import Answer, answer, bindings
from elenctic.reader import is_case, parse_contract
from elenctic.search import UNLIMITED, Interrupt, Limits
from elenctic.writer import bound, braces, render, where


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


def _sets(over: Range) -> str:
    return "optimal answer sets" if over is Range.OPTIMAL else "answer sets"


def _count(claim: Census, models: Iterable[Model], *, closed: bool) -> tuple[Verdict, str]:
    """Count the distinct answers: a model's identity is what it shows and what it assigns."""
    answers = {model.identity for model in models}
    seen = len(answers)
    verdict = _universal(
        refuted=seen > claim.count or (closed and seen < claim.count), closed=closed
    )
    noun = "with their assignments" if any(assignment for _, assignment in answers) else ""
    return (
        verdict,
        f"{claim.count} expected, {seen} distinct shown {_sets(claim.over)} {noun}".rstrip(),
    )


def _witnessed(
    claim: Witness | Assigns, models: Iterable[Model], *, closed: bool
) -> tuple[Verdict, str]:
    seen = any(claim.upheld_by(model) for model in models)
    return _existential(
        found=seen, closed=closed
    ), f"{_stated(claim)} by an answer set: {'yes' if seen else 'no'}"


def _stated(claim: Witness | Assigns) -> str:
    match claim:
        case Witness(literals, _, assignment):
            return f"{braces(literals)} shown{where(assignment)}"
        case Assigns(assignment):
            return f"{bound(assignment)} assigned"


def _entailed(claim: Entails, held: AnswerSet, *, closed: bool) -> tuple[Verdict, str]:
    cautious = claim.mode is Mode.CAUTIOUS
    missing = claim.literals - held
    verdict = (
        _universal(refuted=bool(missing), closed=closed)
        if cautious
        else _existential(found=not missing, closed=closed)
    )
    space = "Opt(P)" if claim.over is Range.OPTIMAL else "AS(P)"
    detail = f"{braces(claim.literals)} ⊆ {'⋂' if cautious else '∪'} {space} = {braces(held)}"
    return verdict, detail + (f" (missing: {braces(missing)})" if missing else "")


def _entails(claim: Entails, shown: frozenset[AnswerSet], *, closed: bool) -> tuple[Verdict, str]:
    cautious = claim.mode is Mode.CAUTIOUS
    held = frozenset.intersection(*shown) if cautious else frozenset().union(*shown)
    return _entailed(claim, held, closed=closed)


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


def _worldly(reading: Asks | Binds, found: Consistent[Models]) -> tuple[Verdict, str]:
    view = world_view(found)
    if isinstance(view, Truncation):
        return Verdict.UNDECIDED, f"search ended: {view}"
    return _asked(reading, view)


def _consistent(reading: Reading, found: Consistent[Models]) -> tuple[Verdict, str]:
    models = found.evidence.all
    closed = found.conclusion is Exhausted.EXHAUSTED
    match reading:
        case Asks() | Binds():
            return _worldly(reading, found)
        case Satisfiable(expected):
            return _agree(expected), "an answer set exists"
        case Census():
            return _count(reading, models, closed=closed)
        case Witness() | Assigns():
            return _witnessed(reading, models, closed=closed)
        case Entails():
            return _entails(reading, frozenset(m.shown for m in models), closed=closed)
        case Costs():
            return Verdict.UNDECIDED, "no optimum was sought"


def _consequent(reading: Reading, found: Consequences) -> tuple[Verdict, str]:
    """Judge from native consequences, which exist only for a search that closed its space."""
    if isinstance(reading, Entails):
        return _entailed(reading, found.literals, closed=True)
    return _agree(reading == Satisfiable(expected=True)), "an answer set exists"


def _cost(claim: Costs, cost: Cost) -> tuple[Verdict, str]:
    return _agree(claim.cost == cost), f"{_levels(claim.cost)} expected, optimum is {_levels(cost)}"


def _levels(cost: Cost) -> str:
    return "(" + ", ".join(map(str, cost)) + ")"


def _optimal(
    reading: Reading, found: Optimum, conclusion: Exhausted | Truncation
) -> tuple[Verdict, str]:
    """Judge from a proven optimum and the optimal models found, all of them if exhausted."""
    if isinstance(reading, Costs):
        return _cost(reading, found.cost)
    return _consistent(reading, Consistent(found.models, conclusion))


def _core_text(refutation: These) -> str:
    core = ", ".join(sorted(str(a.literal) for a in refutation.core))
    caveat = (
        "" if refutation.minimal else "; the search was cut short, so the core may not be minimal"
    )
    return f"no answer set satisfies the assumptions ({core}){caveat}"


def _inconsistent(reading: Reading, refutation: Refutation) -> tuple[Verdict, str]:
    why = _core_text(refutation) if isinstance(refutation, These) else "AS(P) = ∅"
    return _agree(reading == Satisfiable(expected=False) or denies_answer_sets(reading)), why


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
            return _consistent(reading, Consistent(evidence, conclusion))
        case Consequences():
            return _consequent(reading, evidence)
        case Optimum():
            return _optimal(reading, evidence, conclusion)
        case Incumbent():
            return Verdict.UNDECIDED, f"no optimum proven: search ended: {conclusion}"


def _by_search(claims: Iterable[Claim]) -> dict[tuple[Scenario, Range], list[Claim]]:
    groups: dict[tuple[Scenario, Range], list[Claim]] = {}
    for claim in claims:
        groups.setdefault((claim.scenario, over(claim.reading)), []).append(claim)
    return groups


def _limits(group: list[Claim], limits: Limits) -> Limits:
    """Cap the search at one model for a group that reads no collection of them."""
    return (
        replace(limits, models=1)
        if all(isinstance(c.reading, Satisfiable | Costs) for c in group)
        else limits
    )


def _closes(group: list[Claim]) -> bool:
    """Say whether consequences settle a group: it asks only for them and whether a model exists."""
    readings = [c.reading for c in group]
    return all(isinstance(r, Satisfiable | Entails) for r in readings) and any(
        isinstance(r, Entails) for r in readings
    )


def _entailing(
    group: list[Claim], native: Callable[[Mode], Determination[Consequences]]
) -> list[Finding]:
    """Judge a group of consequence claims, each mode by one native search."""
    modes = {c.reading.mode for c in group if isinstance(c.reading, Entails)}
    searches = {mode: native(mode) for mode in modes}
    first = searches[min(modes)]
    return [
        judge(c, searches[c.reading.mode] if isinstance(c.reading, Entails) else first)
        for c in group
    ]


def _capped(found: Found) -> bool:
    """Say whether a search stopped for want of nothing but the model cap it was given."""
    return isinstance(found, Consistent) and found.conclusion is Truncation.TARGET


def _judge_group(
    grounded: Grounded,
    key: tuple[Scenario, Range],
    group: list[Claim],
    limits: Limits,
    interrupt: Interrupt | None,
) -> list[Finding]:
    scenario, over = key

    def native(mode: Mode) -> Determination[Consequences]:
        return grounded.consequences(mode, scenario, limits=limits, interrupt=interrupt)

    if over is Range.OPTIMAL:
        found: Found = grounded.optimize(
            scenario, limits=_limits(group, limits), interrupt=interrupt
        )
    elif _closes(group):
        return _entailing(group, native)
    else:
        found = grounded.solve(scenario, limits=_limits(group, limits), interrupt=interrupt)
    findings = [judge(claim, found) for claim in group]
    if over is Range.ALL and _capped(found):
        return _natively(group, findings, native)
    return findings


def _natively(
    group: list[Claim],
    findings: list[Finding],
    native: Callable[[Mode], Determination[Consequences]],
) -> list[Finding]:
    """Replace the verdicts on consequence claims by native ones, which the model cap cannot cut."""
    entailing = [c for c in group if isinstance(c.reading, Entails)]
    decided = dict(zip(entailing, _entailing(entailing, native), strict=True)) if entailing else {}
    return [decided.get(claim, finding) for claim, finding in zip(group, findings, strict=True)]


def check(
    program: Program,
    *,
    limits: Limits = UNLIMITED,
    interrupt: Interrupt | None = None,
) -> Report | Fault | None:
    """Check the contract written in `program`; `None` if it carries none."""
    if not is_case(program.text):
        return None
    contract = parse_contract(program.text, program.source)
    if contract.diagnostics:
        return Fault(Locus.REQUEST, contract.diagnostics)
    grounded = ground(program, contract.solver)
    if isinstance(grounded, Fault):
        return grounded
    if unsafe := unsound(contract, grounded):
        return Fault(Locus.REQUEST, tuple(unsafe))
    judged = {
        claim: finding
        for key, group in _by_search(contract.claims).items()
        for claim, finding in zip(
            group, _judge_group(grounded, key, group, limits, interrupt), strict=True
        )
    }
    return Report(program.source, tuple(judged[claim] for claim in contract.claims))
