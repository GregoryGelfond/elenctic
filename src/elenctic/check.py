"""Judge the claims of a contract against what a search found."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from enum import StrEnum

from clingo import Symbol

from elenctic.contract import (
    Asks,
    Binds,
    Census,
    Claim,
    Costs,
    Entails,
    Reading,
    Satisfiable,
    Witness,
    braces,
    is_case,
    parse_contract,
    render,
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
from elenctic.engine import Fault, Grounded, Interrupt, Limits, Locus, Program, ground
from elenctic.literals import AnswerSet, Literal, Scenario, Signature
from elenctic.query import Answer, answer, bindings
from elenctic.spans import Diagnostic, Position, Severity, Span

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


def _sets(over: Range) -> str:
    return "optimal answer sets" if over is Range.OPTIMAL else "answer sets"


def _count(claim: Census, shown: frozenset[AnswerSet], *, closed: bool) -> tuple[Verdict, str]:
    seen = len(shown)
    verdict = _universal(
        refuted=seen > claim.count or (closed and seen < claim.count), closed=closed
    )
    return verdict, f"{claim.count} expected, {seen} distinct shown {_sets(claim.over)}"


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
    shown = frozenset(model.shown for model in found.evidence.all)
    closed = found.conclusion is Exhausted.EXHAUSTED
    if isinstance(reading, Asks | Binds):
        return _worldly(reading, found)
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


def _inconsistent(reading: Reading, refutation: Refutation) -> tuple[Verdict, str]:
    why = (
        "no answer set satisfies the assumptions ("
        + ", ".join(sorted(str(a.literal) for a in refutation.core))
        + ")"
        if isinstance(refutation, These)
        else "AS(P) = ∅"
    )
    return _agree(reading == Satisfiable(expected=False) or _none(reading)), why


def _none(reading: Reading) -> bool:
    return isinstance(reading, Census) and reading.count == 0


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


def _over(reading: Reading) -> Range:
    """Name the model set a claim is about: only the optimal-set claims say otherwise."""
    if isinstance(reading, Census | Witness | Entails | Costs):
        return reading.over
    return Range.ALL


def _by_search(claims: Iterable[Claim]) -> dict[tuple[Scenario, Range], list[Claim]]:
    groups: dict[tuple[Scenario, Range], list[Claim]] = {}
    for claim in claims:
        groups.setdefault((claim.scenario, _over(claim.reading)), []).append(claim)
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


def _judge_group(
    grounded: Grounded,
    key: tuple[Scenario, Range],
    group: list[Claim],
    limits: Limits,
    interrupt: Interrupt | None,
) -> list[Finding]:
    scenario, over = key
    found: Found
    if over is Range.OPTIMAL:
        found = grounded.optimize(scenario, limits=_limits(group, limits), interrupt=interrupt)
    elif _closes(group):
        return _entailing(
            group, lambda m: grounded.consequences(m, scenario, limits=limits, interrupt=interrupt)
        )
    else:
        found = grounded.solve(scenario, limits=_limits(group, limits), interrupt=interrupt)
    return [judge(claim, found) for claim in group]


def _at(source: str) -> Span:
    return Span(source, Position(1, 1), Position(1, 1))


def _contraries(reading: Reading) -> frozenset[Signature]:
    """Name the predicates a `no` or `unknown` query reads as contraries off the shown atoms."""
    match reading:
        case Asks(Answer.NO | Answer.UNKNOWN, query):
            return frozenset(
                part.contrary.signature for part in query.parts if isinstance(part, Literal)
            )
        case Binds(Answer.UNKNOWN, pattern, _):
            return frozenset({pattern.contrary.signature})
        case Binds(Answer.NO, pattern, found) if found:
            return frozenset({pattern.contrary.signature})
        case _:
            return frozenset()


def _unsound(claims: Iterable[Claim], grounded: Grounded, source: str) -> list[Diagnostic]:
    """Find what would make a verdict untrustworthy: a claim asks what the program lacks."""
    theory = [
        Diagnostic(
            _at(source),
            Severity.ERROR,
            "the program has theory atoms, which this checker does not interpret: "
            "clingo would ground them and ignore their constraints",
        )
    ] * grounded.facts.theory
    return theory + [
        Diagnostic(claim.span, Severity.ERROR, message)
        for claim in claims
        for message in _lacks(claim.reading, grounded)
    ]


def _lacks(reading: Reading, grounded: Grounded) -> list[str]:
    objective = [
        (
            "needs an objective, but the ground program has none: it declares no `#minimize`, "
            "`#maximize` or `:~`, or its elements ground away"
        )
    ] * (_over(reading) is Range.OPTIMAL and not grounded.facts.optimizes)
    unshown = [
        f"reads the contrary `{signature}` off the shown atoms, "
        "but the program can derive it and does not `#show` it"
        for signature in sorted(_contraries(reading))
        if signature in grounded.signatures and not grounded.facts.shown.covers(signature)
    ]
    return objective + unshown


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
    if unsound := _unsound(contract.claims, grounded, program.source):
        return Fault(Locus.REQUEST, tuple(unsound))
    judged = {
        claim: finding
        for key, group in _by_search(contract.claims).items()
        for claim, finding in zip(
            group, _judge_group(grounded, key, group, limits, interrupt), strict=True
        )
    }
    return Report(program.source, tuple(judged[claim] for claim in contract.claims))
