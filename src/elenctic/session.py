"""A program grounded once with what explaining it needs: the session `explain` reads evidence from.

The program is grounded with rules that record, in each answer set, the weak-constraint instances it
pays and the truth of each theory atom of a body. A positive relaxation of it, grounded apart, names
every rule instance that could derive each atom. Neither changes the answer sets.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import override

from clingo import Model as ClingoModel
from clingo.ast import AST

from elenctic import failures
from elenctic.clauses import Kind
from elenctic.contract import Asks, Claim, Entails, Satisfiable, Solver
from elenctic.determination import (
    AnswerSet,
    AnswerSets,
    Conclusion,
    Consistent,
    Determination,
    Exhausted,
    Inconclusive,
    Inconsistent,
    Optimized,
    Optimum,
    Range,
    Refutation,
    Truncation,
)
from elenctic.engine import controlled, parsed, possible_atoms, source_texts
from elenctic.explanation import Counterexample, Evidence, Explanation, Outranked, Paid
from elenctic.grounded import Grounded
from elenctic.instances import Instances, Payment, instances
from elenctic.literals import Assumption, Atoms, Literal, Scenario, Symbol, is_function
from elenctic.program import Fault, Program
from elenctic.query import Answer, Answered, Query, Truth, answered, evaluate
from elenctic.relaxation import Reading, Source, read
from elenctic.search import KEEP_ALL, Interrupt, Keep, Limit, Limits, Seen, seen
from elenctic.substitution import Substitution
from elenctic.support import explain
from elenctic.terms import Variable
from elenctic.verdicts import Ended, Finding, Report, Verdict


@dataclass(slots=True)
class _Prepared:
    """What reading the program found, kept from grounding for the session to explain with."""

    reading: Reading | None = None
    instances: Instances | None = None


class Session(Grounded):
    """A program grounded once to be searched and explained: the session 1.0 reserves.

    Each answer set it finds is remembered with the atoms it records, so `explain` can read them.
    Each search it ends is kept too, so a counterexample keeps its number from call to call: clingo
    enumerates in another order once it has solved, as when `explain` is asked to go deeper.
    """

    def __init__(
        self,
        grounded: Grounded,
        instances: Instances,
        priorities: tuple[int, ...],
        *,
        limits: Limits,
        interrupt: Interrupt | None,
    ) -> None:
        super().__init__(grounded._control, grounded.facts, grounded._theory)  # noqa: SLF001
        self._instances = instances
        self._prefix = instances.reading.prefix
        self.priorities = priorities
        self.limits = limits
        self.interrupt = interrupt
        self._recorded: dict[AnswerSet, frozenset[Symbol]] = {}
        self._enumerated: dict[Scenario, Determination[AnswerSets]] = {}
        self._optimized: dict[Scenario, Determination[Optimized]] = {}

    def _enumerate(self, scenario: Scenario) -> Determination[AnswerSets]:
        """Enumerate the answer sets of `scenario` in the session's limits, once it has ended."""
        found = self._enumerated.get(scenario)
        if found is None:
            found = self.solve(scenario, limits=self.limits, interrupt=self.interrupt)
            if not isinstance(found, Inconclusive):
                self._enumerated[scenario] = found
        return found

    def _optimize(self, scenario: Scenario) -> Determination[Optimized]:
        """Find the optimum of `scenario` within the session's limits, once it has ended."""
        found = self._optimized.get(scenario)
        if found is None:
            found = self.optimize(scenario, limits=self.limits, interrupt=self.interrupt)
            if not isinstance(found, Inconclusive):
                self._optimized[scenario] = found
        return found

    @override
    def _seen(self, answer_set: ClingoModel, keep: Keep) -> Seen:
        noted = seen(answer_set, self._theory, KEEP_ALL)
        mine = tuple(s for s in noted.atoms if not self._added(s))
        shown = tuple(s for s in noted.shown if not self._added(s))
        kept = replace(noted, atoms=mine if keep.atoms else (), shown=shown if keep.shown else ())
        full = replace(noted, atoms=mine, shown=shown)
        recorded = frozenset(noted.atoms)
        self._recorded[full.answer_set] = self._recorded[kept.answer_set] = recorded
        return kept

    def _added(self, symbol: Symbol) -> bool:
        return is_function(symbol) and symbol.name.startswith(self._prefix)

    def _atoms(self, answer_set: AnswerSet) -> frozenset[Symbol]:
        """Return the atoms an answer set holds, with those the session records in it."""
        if (recorded := self._recorded.get(answer_set)) is not None:
            return recorded
        if any(p.kind is Kind.THEORY for c in self._instances.reading.clauses for p in c.body):
            message = (
                "this answer set was not found by this session, which must read its theory atoms"
            )
            raise ValueError(message)
        return frozenset(literal.symbol for literal in answer_set.atoms)

    def explain(
        self,
        literals: Iterable[Literal],
        counterexample: Counterexample,
        *,
        max_depth: int | Limit = Limit.UNBOUNDED,
    ) -> Explanation:
        """Explain why each literal holds in the counterexample, or why it does not.

        `max_depth` bounds how many absences deep the explanation goes; raises `ValueError` if it
        is negative, or if the answer set was not found by this session and the program has
        theory atoms in a body.
        """
        if not isinstance(max_depth, Limit) and max_depth < 0:
            message = "a depth is never negative"
            raise ValueError(message)
        roots = [literal.symbol for literal in dict.fromkeys(literals)]
        atoms = self._atoms(counterexample.answer_set)
        return explain(self._instances, atoms, counterexample, roots, max_depth)

    def outrank(
        self,
        literals: Atoms,
        scenario: Scenario = frozenset(),
        *,
        max_depth: int | Limit = Limit.UNBOUNDED,
    ) -> Outranked | Ended | None:
        """Say how the objective ranks the literals below the optimum, under `scenario`.

        `None` when no answer set holds them all, or when the best that does is optimal. The
        optimum's lack of them is explained `max_depth` absences deep.
        """
        optima = self._optima(literals, scenario)
        if not isinstance(optima, tuple):
            return optima
        optimum, assuming = optima
        if optimum.cost == assuming.cost:
            return None
        priority = next(
            self.priorities[at]
            for at, (a, b) in enumerate(zip(optimum.cost, assuming.cost, strict=True))
            if a != b
        )
        first, other = optimum.answer_sets.first, assuming.answer_sets.first
        paid_first = self._instances.paid(self._atoms(first))
        paid_other = self._instances.paid(self._atoms(other))
        counterexample = Counterexample(first, 1, None)
        absent = [literal for literal in sorted(literals) if literal not in first.atoms]
        return Outranked(
            literals,
            self.priorities,
            optimum.cost,
            assuming.cost,
            priority,
            _paid(paid_first - paid_other),
            _paid(paid_other - paid_first),
            self.explain(absent, counterexample, max_depth=max_depth),
        )

    def _optima(
        self, literals: Atoms, scenario: Scenario
    ) -> tuple[Optimum, Optimum] | Ended | None:
        """Find the optimum under `scenario`, then the best answer set that holds `literals` too."""
        assumed = scenario | {Assumption(literal) for literal in literals}
        optima: list[Optimum] = []
        for assumptions in (scenario, assumed):
            match self._optimize(assumptions):
                case Inconclusive(cut):
                    return Ended(cut)
                case Consistent(Optimum() as optimum, _):
                    optima.append(optimum)
                case Consistent(_, conclusion):
                    return Ended(Truncation(conclusion), optimum_unproven=True)
                case _:
                    pass
        match optima:
            case [best, held]:
                return best, held
            case _:
                return None

    def evidence(
        self, finding: Finding, *, max_depth: int | Limit = Limit.UNBOUNDED
    ) -> Evidence | Ended | None:
        """Find why a failed claim fails: a counterexample explained, a refutation, or a ranking.

        `None` for a claim that did not fail, or one whose kind has no evidence yet.
        """
        if finding.verdict is not Verdict.FAIL:
            return None
        claim = finding.claim
        match claim.reading:
            case Satisfiable(expected=True):
                found = self.solve(
                    claim.scenario,
                    limits=replace(self.limits, max_answer_sets=1),
                    interrupt=self.interrupt,
                )
                return found.refutation if isinstance(found, Inconsistent) else None
            case Satisfiable():
                return self._first(claim, max_depth)
            case Entails() as entails:
                return self._entails(claim, entails, max_depth)
            case Asks() as asks:
                return self._asks(claim, asks, max_depth)
            case _:
                return None

    def counterexample(
        self, index: int = 1, scenario: Scenario = frozenset(), *, over: Range = Range.ALL
    ) -> Counterexample | Refutation | Ended | None:
        """Find the `index`-th answer set the search reads under `scenario`, of all or the optima.

        `None` when there are fewer; the refutation when there is none; `Ended` when the search
        stopped before reaching it. Raises `ValueError` for an index below 1.
        """
        if index < 1:
            message = "an answer set's index counts from 1"
            raise ValueError(message)
        members = self._members(scenario, over)
        if not isinstance(members, tuple):
            return members
        sets, conclusion = members
        read = len(sets) if conclusion is Exhausted.EXHAUSTED else None
        if index <= len(sets):
            return Counterexample(sets[index - 1], index, read)
        return None if read is not None else Ended(Truncation(conclusion))

    def answer(
        self, query: Query, scenario: Scenario = frozenset(), *, over: Range = Range.ALL
    ) -> Answered | Refutation | Ended:
        """Answer `query` over the answer sets of `scenario`, all or the optima, as `@query` does.

        The refutation when there is none; `Ended` when the search stopped before reading them all.
        """
        members = self._members(scenario, over)
        if not isinstance(members, tuple):
            return members
        sets, conclusion = members
        if conclusion is not Exhausted.EXHAUSTED:
            return Ended(Truncation(conclusion))
        return answered(query, sets, over)

    def _members(
        self, scenario: Scenario, over: Range
    ) -> tuple[tuple[AnswerSet, ...], Conclusion] | Ended | Refutation:
        """Search for the answer sets of `scenario`, all or the optima, and say how it ended."""
        if over is Range.OPTIMAL:
            return self._optimal(scenario)
        found = self._enumerate(scenario)
        match found:
            case Inconclusive(cut):
                return Ended(cut)
            case Consistent(AnswerSets() as sets, conclusion):
                return sets.all, conclusion
            case Inconsistent(refutation):
                return refutation

    def _optimal(
        self, scenario: Scenario
    ) -> tuple[tuple[AnswerSet, ...], Conclusion] | Ended | Refutation:
        """Search for the optimal answer sets of `scenario`, and say how it ended."""
        optimized = self._optimize(scenario)
        match optimized:
            case Inconclusive(cut):
                return Ended(cut)
            case Consistent(Optimum(_, sets), conclusion):
                return sets.all, conclusion
            case Consistent(_, conclusion):
                return Ended(Truncation(conclusion), optimum_unproven=True)
            case Inconsistent(refutation):
                return refutation

    def _first(self, claim: Claim, max_depth: int | Limit) -> Explanation | Ended | None:
        found = self.counterexample(1, claim.scenario)
        if not isinstance(found, Counterexample):
            return found if isinstance(found, Ended) else None
        return self.explain((), found, max_depth=max_depth)

    def _entails(
        self, claim: Claim, entails: Entails, max_depth: int | Limit
    ) -> Evidence | Ended | None:
        members = self._members(claim.scenario, entails.over)
        if not isinstance(members, tuple):
            return members if isinstance(members, Ended) else None
        sets, conclusion = members
        closed = conclusion is Exhausted.EXHAUSTED
        if not sets:
            return None
        found = failures.missing(entails, sets, closed=closed)
        if not isinstance(found, tuple):
            return found
        at, answer_set, missing = found
        if entails.over is Range.OPTIMAL:
            ranked = self.outrank(frozenset(missing), claim.scenario, max_depth=max_depth)
            if ranked is not None:
                return ranked
        read = len(sets) if closed else None
        return self.explain(missing, Counterexample(answer_set, at, read), max_depth=max_depth)

    def _asks(self, claim: Claim, asks: Asks, max_depth: int | Limit) -> Evidence | Ended | None:
        members = self._members(claim.scenario, asks.over)
        if not isinstance(members, tuple):
            return members if isinstance(members, Ended) else None
        sets, conclusion = members
        closed = conclusion is Exhausted.EXHAUSTED
        if not sets:
            return None
        read = len(sets) if closed else None
        contrary = Truth.FALSE if asks.answer is Answer.YES else Truth.TRUE
        if asks.answer is Answer.UNKNOWN:
            return None
        truths = [evaluate(asks.query, s.atoms) for s in sets]
        for wanted in (contrary, Truth.UNKNOWN):
            if wanted in truths:
                at = truths.index(wanted) + 1
                answer_set = sets[at - 1]
                roots = failures.roots(asks.query, answer_set.atoms, asks.answer)
                return self.explain(
                    roots, Counterexample(answer_set, at, read), max_depth=max_depth
                )
        return None


def _paid(payments: frozenset[Payment]) -> tuple[Paid, ...]:
    return tuple(
        Paid(
            p.weak.rule,
            p.weight,
            p.priority,
            p.terms,
            Substitution({Variable(n): v for n, v in zip(p.weak.variables, p.values, strict=True)}),
        )
        for p in sorted(payments, key=lambda p: (-p.priority, p.weak.rule.statement, str(p.values)))
    )


def session(
    program: Program,
    solver: Solver = Solver.CLINGO,
    *,
    limits: Limits = Limits(),
    interrupt: Interrupt | None = None,
) -> Session | Fault:
    """Ground `program` for `solver` into a session that can explain it, or say why it cannot be."""
    prepared = _Prepared()
    source = Source(program.source, source_texts(program))

    def extend(statements: Sequence[AST]) -> Sequence[AST]:
        reading = read(statements, source)
        found = instances(reading, possible_atoms("\n".join(reading.relaxation)))
        prepared.reading, prepared.instances = reading, found
        return parsed("\n".join([*reading.solving, *found.binding()]))

    grounded = controlled(program, solver, extend)
    if isinstance(grounded, Fault):
        return grounded
    if prepared.instances is None:
        message = "the program was grounded without being read"
        raise AssertionError(message)
    plain = Grounded(grounded.control, grounded.facts, grounded.theory)
    return Session(
        plain, prepared.instances, grounded.priorities, limits=limits, interrupt=interrupt
    )


def evidenced(
    report: Report,
    program: Program,
    *,
    limits: Limits = Limits(),
    interrupt: Interrupt | None = None,
    max_depth: int | Limit = Limit.UNBOUNDED,
) -> Report | Fault:
    """Give each failed finding of a report on `program` its evidence."""
    if not any(f.verdict is Verdict.FAIL for f in report.findings):
        return report
    opened = session(program, report.solver, limits=limits, interrupt=interrupt)
    if isinstance(opened, Fault):
        return opened
    findings = tuple(
        replace(f, evidence=opened.evidence(f, max_depth=max_depth))
        if f.verdict is Verdict.FAIL
        else f
        for f in report.findings
    )
    return replace(report, findings=findings)
