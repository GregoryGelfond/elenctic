"""Check the contract written in a program: ground it, search each scenario, judge each claim."""

from collections.abc import Callable, Iterable
from dataclasses import replace

from elenctic.contract import Claim, Costs, Entails, Satisfiable, over
from elenctic.determination import Consequences, Consistent, Determination, Mode, Range, Truncation
from elenctic.engine import ground
from elenctic.gates import hidden_reads, unsound
from elenctic.grounded import Grounded
from elenctic.judge import Found, judge
from elenctic.literals import Scenario
from elenctic.program import Fault, Locus, Program
from elenctic.reader import parse_contract
from elenctic.search import Interrupt, Limits
from elenctic.tags import is_case
from elenctic.verdicts import Finding, Report


def _by_search(claims: Iterable[Claim]) -> dict[tuple[Scenario, Range], list[Claim]]:
    groups: dict[tuple[Scenario, Range], list[Claim]] = {}
    for claim in claims:
        groups.setdefault((claim.scenario, over(claim.reading)), []).append(claim)
    return groups


def _limits(group: list[Claim], limits: Limits) -> Limits:
    """Limit the search to one answer set for a group that reads no collection of them."""
    return (
        replace(limits, max_answer_sets=1)
        if all(isinstance(c.reading, Satisfiable | Costs) for c in group)
        else limits
    )


def _closes(group: list[Claim]) -> bool:
    """Say whether consequences settle a group: it asks only for them and for an answer set."""
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


def _cut_by_count(found: Found) -> bool:
    """Say whether a search was truncated only by the answer-set limit."""
    return isinstance(found, Consistent) and found.conclusion is Truncation.MAX_ANSWER_SETS


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
    if over is Range.ALL and _cut_by_count(found):
        return _natively(group, findings, native)
    return findings


def _natively(
    group: list[Claim],
    findings: list[Finding],
    native: Callable[[Mode], Determination[Consequences]],
) -> list[Finding]:
    """Replace the verdicts on consequence claims by native ones, which the limit cannot cut."""
    entailing = [c for c in group if isinstance(c.reading, Entails)]
    decided = dict(zip(entailing, _entailing(entailing, native), strict=True)) if entailing else {}
    return [decided.get(claim, finding) for claim, finding in zip(group, findings, strict=True)]


def check(
    program: Program,
    *,
    limits: Limits = Limits(),
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
    return Report(
        program.source,
        tuple(judged[claim] for claim in contract.claims),
        tuple(hidden_reads(contract.claims, grounded)),
    )
