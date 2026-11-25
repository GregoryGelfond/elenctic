"""A program grounded once with what explaining it needs: the session `explain` reads evidence from.

The program is grounded with rules that record, in each answer set, the weak-constraint instances it
pays and the truth of each theory atom of a body. A positive relaxation of it, grounded apart, names
every rule instance that could derive each atom. Neither changes the answer sets.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from functools import cache, partial
from typing import Final, override

from clingo import Model as ClingoModel
from clingo.ast import AST

from elenctic import failures
from elenctic.clauses import Kind
from elenctic.contract import Asks, Claim, Entails, Satisfiable, Solver
from elenctic.determination import (
    AnswerSet,
    AnswerSets,
    Conclusion,
    Consequences,
    Consistent,
    Determination,
    Exhausted,
    Inconclusive,
    Inconsistent,
    Mode,
    Optimized,
    Optimum,
    Range,
    Refutation,
    Truncation,
)
from elenctic.engine import Controlled, controlled, parsed, possible_atoms, sources
from elenctic.explanation import Counterexample, Evidence, Explanation, Outranked, Paid
from elenctic.grounded import Grounded
from elenctic.instances import Instances, Payment, instances
from elenctic.literals import Assumption, Atoms, Literal, Scenario, Symbol, is_function
from elenctic.program import Fault, Program
from elenctic.query import (
    REFUTED,
    Answer,
    Answered,
    AnswerMode,
    Answers,
    Bound,
    Giving,
    Held,
    Query,
    ReadAnswers,
    Taken,
    Truth,
    Warrant,
    answered,
    bodies,
    bravely,
    deciding,
    evaluate,
    giving,
    instance_of,
    settled,
    settles,
    witnessed,
)
from elenctic.relaxation import Reading, read
from elenctic.search import KEEP_ALL, KEEP_NONE, Interrupt, Keep, Limit, Limits, Seen, seen
from elenctic.substitution import Substitution
from elenctic.support import explain
from elenctic.terms import Variable
from elenctic.verdicts import Ended, Finding, Report, Verdict

ONE_BINDING: Final = "a query with variables is warranted one binding at a time"
"""Why a query with variables is not warranted as a whole."""


@dataclass(slots=True)
class _Prepared:
    """What reading the program found, kept from grounding for the session to explain with."""

    reading: Reading | None = None
    instances: Instances | None = None


def _one(_found: list[Seen]) -> bool:
    """Stop at the first answer set: one shows a truth is given, and more say no more of it."""
    return True


@dataclass(frozen=True, slots=True)
class _Reading:
    """The answer sets of a scenario a session has read, in its order, and how the search ended.

    `stopped` when the search stopped on purpose, at an answer set it wanted: more may follow.
    """

    sets: tuple[AnswerSet, ...] = ()
    conclusion: Conclusion = Exhausted.EXHAUSTED
    stopped: bool = True

    @property
    def read(self) -> int | None:
        """How many answer sets there are, once the search has read every one."""
        ended = not self.stopped and self.conclusion is Exhausted.EXHAUSTED
        return len(self.sets) if ended else None


class Session(Grounded):
    """A program grounded once to be searched and explained: the session 1.0 reserves.

    Each answer set it finds is remembered with the atoms it records, so `explain` can read them.
    The answer sets of each scenario are kept in the order it read them, so each keeps its number
    from call to call: clingo enumerates in another order once it has solved, as when `explain` is
    asked to go deeper. A query of one literal asks which answers it is given on a grounding apart,
    so the session goes on to read in the order a fresh one does, and numbers as `why` does.
    """

    def __init__(
        self,
        grounded: Controlled,
        instances: Instances,
        *,
        limits: Limits,
        interrupt: Interrupt | None,
        apart: Callable[[str], Grounded],
    ) -> None:
        super().__init__(grounded.control, grounded.facts, grounded.theory)
        self._instances = instances
        self._prefix = instances.reading.prefix
        self.priorities = grounded.priorities
        self.limits = limits
        self.interrupt = interrupt
        self._apart = cache(apart)
        self._recorded: dict[AnswerSet, frozenset[Symbol]] = {}
        self._readings: dict[Scenario, _Reading | Refutation] = {}
        self._optimized: dict[Scenario, Determination[Optimized]] = {}

    def _reach(
        self, scenario: Scenario, wanted: Callable[[int, AnswerSet], bool]
    ) -> _Reading | Refutation | Ended:
        """Read the answer sets of `scenario` until one is `wanted`, asked of each with its number.

        What is read is kept. A search that must read on starts over, in clingo's new order, and
        numbers only the answer sets not read before, after them.
        """
        known = self._readings.get(scenario, _Reading())
        if not isinstance(known, _Reading) or not known.stopped:
            return known
        if any(wanted(at, answer_set) for at, answer_set in enumerate(known.sets, 1)):
            return known
        before = frozenset(known.sets)
        number = len(known.sets)
        stopped = False

        def enough(read: list[Seen]) -> bool:
            nonlocal number, stopped
            answer_set = read[-1].answer_set
            if answer_set in before:
                return False
            number += 1
            stopped = wanted(number, answer_set)
            return stopped

        found = self.solve(scenario, limits=self.limits, interrupt=self.interrupt, enough=enough)
        match found:
            case Inconclusive(cut):
                return Ended(cut)
            case Inconsistent(refutation):
                self._readings[scenario] = refutation
                return refutation
            case Consistent(AnswerSets() as sets, conclusion):
                new = tuple(answer_set for answer_set in sets.all if answer_set not in before)
                reading = _Reading((*known.sets, *new), conclusion, stopped)
                self._readings[scenario] = reading
                return reading

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
        if over is Range.OPTIMAL:
            found = self._optimal(scenario)
        else:
            found = self._reach(scenario, lambda at, _: at == index)
        if not isinstance(found, _Reading):
            return found
        if index <= len(found.sets):
            return Counterexample(found.sets[index - 1], index, found.read)
        return None if found.read is not None else Ended(Truncation(found.conclusion))

    def answer(
        self,
        query: Query,
        scenario: Scenario = frozenset(),
        *,
        over: Range = Range.ALL,
        mode: AnswerMode = AnswerMode.DEFAULT,
    ) -> Answered | Refutation | Ended:
        """Answer `query` as `mode` does over the answer sets of `scenario`, all or the optima.

        By default it is answered as `@query` answers it. A query of one literal, over all the
        answer sets, is answered once the search has read the first answer set to give each answer
        some answer set gives. The refutation when there is none; `Ended` when the search stopped
        before reading what the answer needs.
        """
        given = giving(query)
        if over is Range.ALL and given is not None:
            return self._settled(query, given, scenario, mode)
        members = self._members(scenario, over)
        if not isinstance(members, _Reading):
            return members
        if members.read is None:
            cut = Truncation(members.conclusion)
            if mode is AnswerMode.BRAVE and (yes := bravely(query, members.sets, over, cut)):
                return yes
            return Ended(cut)
        return answered(query, members.sets, over, mode)

    def _settled(
        self, query: Query, given: Giving, scenario: Scenario, mode: AnswerMode
    ) -> Answered | Refutation | Ended:
        """Answer a query of one literal or its negation from its truths, read until each is taken.

        The answer is known before the search reads: one that stops it first leaves the truths not
        yet taken unreached.
        """
        truths = self._truths(given, scenario, mode)
        if isinstance(truths, Ended):
            return truths
        left = set(truths)

        def wanted(_: int, answer_set: AnswerSet) -> bool:
            left.discard(evaluate(query, answer_set.atoms))
            return not left

        reading = self._reach(scenario, wanted)
        if not isinstance(reading, _Reading):
            return reading
        cut = reading.conclusion if isinstance(reading.conclusion, Truncation) else None
        return settled(query, ReadAnswers(reading.sets, cut, reading.read), truths, mode)

    def _truths(
        self, given: Giving, scenario: Scenario, mode: AnswerMode
    ) -> frozenset[Truth] | Ended:
        """Find the truths some answer set of `scenario` gives a query, on the grounding apart.

        `Ended` only when a truth the search could not settle would change what `mode` answers.
        """
        limits = replace(self.limits, max_answer_sets=1)
        truths: set[Truth] = set()
        unsettled: dict[Truth, Truncation] = {}
        for truth, assumed in given.items():
            match self._apart("").solve(
                scenario | assumed,
                limits=limits,
                interrupt=self.interrupt,
                enough=_one,
                keep=KEEP_NONE,
            ):
                case Inconclusive(cut):
                    unsettled[truth] = cut
                case Consistent():
                    truths.add(truth)
                case Inconsistent():
                    pass
        if unsettled and not settles(truths, set(unsettled), mode):
            return Ended(next(iter(unsettled.values())))
        return frozenset(truths)

    def warrant(
        self,
        answered: Answered,
        values: tuple[Symbol, ...] = (),
        scenario: Scenario = frozenset(),
        *,
        max_depth: int | Limit = Limit.UNBOUNDED,
    ) -> Warrant | Ended:
        """Find what shows an answer this session gave, of the query or of its binding to `values`.

        Its witnesses are answer sets the search read, each with the derivation of what the
        instance's truth there rests on, `max_depth` absences deep. An answer that needs every
        answer set is also shown by the refutation of the program with a constraint that keeps only
        the answer sets that would overturn it; over the optima, the search having read them all
        shows it. `Ended` when that search is cut, or the cut search that answered did not read the
        binding. Raises `ValueError` for values the query has no binding to.
        """
        answer, taken, unreached = answered.answer, answered.taken, answered.unreached
        if isinstance(answer, Answers):
            bound = _bound(answer, values, answered.cut)
            if isinstance(bound, Ended):
                return bound
            taken = answer.taken(bound)
            answer, unreached = bound.answer, ()
        elif values:
            message = "a query without variables has no binding to warrant"
            raise ValueError(message)
        query = instance_of(answered.query, values)
        refuted = REFUTED.get((answered.mode, answer))
        refutation = None
        if refuted is not None and answered.over is Range.ALL:
            overturned = self._overturned(query, *refuted, scenario)
            if isinstance(overturned, Ended):
                return overturned
            refutation = overturned
        witnesses, past = witnessed(answer, taken, unreached)
        over, read, mode = answered.over, answered.read, answered.mode
        derivations = self._derivations(query, witnesses, read, max_depth)
        named = tuple(each.at() for each in witnesses)
        return Warrant(query, answer, named, derivations, refutation, past, over, read, mode)

    def _derivations(
        self, query: Query, witnesses: tuple[Taken, ...], read: int | None, max_depth: int | Limit
    ) -> tuple[Explanation, ...]:
        """Derive in each witness what the query's truth there rests on, part by part."""
        return tuple(
            self.explain(
                deciding(query, each.answer_set.atoms),
                Counterexample(each.answer_set, each.index, read),
                max_depth=max_depth,
            )
            for each in witnesses
        )

    def _overturned(
        self, query: Query, truth: Truth, held: Held, scenario: Scenario
    ) -> Refutation | Ended:
        """Refute the program kept to the answer sets where `query` lacks `truth`, or has it."""
        head = f"{self._prefix}_holds"
        rules = [
            f"{head} :- {', '.join(body)}." if body else f"{head}." for body in bodies(query, truth)
        ]
        rules.append(f":- {head}." if held is Held.EVERYWHERE else f":- not {head}.")
        limits = replace(self.limits, max_answer_sets=1)
        match self._apart("\n".join(rules)).solve(
            scenario, limits=limits, interrupt=self.interrupt
        ):
            case Inconclusive(cut):
                return Ended(cut)
            case Inconsistent(refutation):
                return refutation
            case Consistent():
                message = "an answer every answer set gives is not overturned by one"
                raise AssertionError(message)

    def _members(self, scenario: Scenario, over: Range) -> _Reading | Ended | Refutation:
        """Search for every answer set of `scenario`, of all or the optima."""
        if over is Range.OPTIMAL:
            return self._optimal(scenario)
        return self._reach(scenario, _none)

    def _optimal(self, scenario: Scenario) -> _Reading | Ended | Refutation:
        """Search for the optimal answer sets of `scenario`, and say how it ended."""
        optimized = self._optimize(scenario)
        match optimized:
            case Inconclusive(cut):
                return Ended(cut)
            case Consistent(Optimum(_, sets), conclusion):
                return _Reading(sets.all, conclusion, stopped=False)
            case Consistent(_, conclusion):
                return Ended(Truncation(conclusion), optimum_unproven=True)
            case Inconsistent(refutation):
                return refutation

    def _lacking(
        self, scenario: Scenario, literals: Atoms | None = None
    ) -> Counterexample | Ended | None:
        """Find the first answer set of `scenario` without all of `literals`, or the first of all.

        The search stops there, so how many answer sets there are is not said. What it read is
        kept, so a claim asked again, deeper, is shown the same answer set.
        """

        def lacks(answer_set: AnswerSet) -> bool:
            return literals is None or not literals <= answer_set.shown

        reading = self._reach(scenario, lambda _, answer_set: lacks(answer_set))
        if not isinstance(reading, _Reading):
            return reading if isinstance(reading, Ended) else None
        found = next((at for at, s in enumerate(reading.sets, 1) if lacks(s)), None)
        return None if found is None else Counterexample(reading.sets[found - 1], found, None)

    def _never(self, literals: Atoms, scenario: Scenario) -> list[Literal] | Ended:
        """Name the literals no answer set of `scenario` holds, from its brave consequences."""
        found = self.consequences(
            Mode.BRAVE, scenario, limits=self.limits, interrupt=self.interrupt
        )
        match found:
            case Inconclusive(cut):
                return Ended(cut)
            case Consistent(Consequences(literals=held), Exhausted.EXHAUSTED):
                return sorted(literals - held)
            case Consistent(_, conclusion):
                return Ended(Truncation(conclusion))
            case _:
                return []

    def _first(self, claim: Claim, max_depth: int | Limit) -> Explanation | Ended | None:
        found = self._lacking(claim.scenario)
        if not isinstance(found, Counterexample):
            return found
        return self.explain((), found, max_depth=max_depth)

    def _entails(
        self, claim: Claim, entails: Entails, max_depth: int | Limit
    ) -> Evidence | Ended | None:
        if entails.over is Range.OPTIMAL:
            return self._entails_optimally(claim, entails, max_depth)
        if entails.mode is Mode.CAUTIOUS:
            found = self._lacking(claim.scenario, entails.literals)
            if not isinstance(found, Counterexample):
                return found
            missing = sorted(entails.literals - found.answer_set.shown)
            return self.explain(missing, found, max_depth=max_depth)
        first = self._lacking(claim.scenario)
        if not isinstance(first, Counterexample):
            return first
        never = self._never(entails.literals, claim.scenario)
        if isinstance(never, Ended):
            return never
        return self.explain(never, first, max_depth=max_depth) if never else None

    def _entails_optimally(
        self, claim: Claim, entails: Entails, max_depth: int | Limit
    ) -> Evidence | Ended | None:
        members = self._members(claim.scenario, entails.over)
        if not isinstance(members, _Reading):
            return members if isinstance(members, Ended) else None
        sets, read = members.sets, members.read
        if not sets:
            return None
        found = failures.missing(entails, sets, closed=read is not None)
        if not isinstance(found, tuple):
            return found
        at, answer_set, missing = found
        ranked = self.outrank(frozenset(missing), claim.scenario, max_depth=max_depth)
        if ranked is not None:
            return ranked
        return self.explain(missing, Counterexample(answer_set, at, read), max_depth=max_depth)

    def _asks(self, claim: Claim, asks: Asks, max_depth: int | Limit) -> Evidence | Ended | None:
        members = self._members(claim.scenario, asks.over)
        if not isinstance(members, _Reading):
            return members if isinstance(members, Ended) else None
        sets, read = members.sets, members.read
        if not sets:
            return None
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


def _bound(answers: Answers, values: tuple[Symbol, ...], cut: Truncation | None) -> Bound | Ended:
    """Find the binding of a query's variables to `values`, unless a `cut` search did not read it.

    Raise `ValueError` if the query has no such binding.
    """
    if not values:
        raise ValueError(ONE_BINDING)
    if len(values) != len(answers.variables):
        names = ", ".join(str(each) for each in answers.variables)
        message = f"expected a value for each of {names}, found {len(values)}"
        raise ValueError(message)
    found = next((each for each in answers.bound if each.values == values), None)
    if found is None and cut is not None:
        return Ended(cut)
    if found is None:
        named = zip(answers.variables, values, strict=True)
        message = f"the query has no binding to {', '.join(f'{n} = {v}' for n, v in named)}"
        raise ValueError(message)
    return found


def _none(_at: int, _answer_set: AnswerSet) -> bool:
    """Want no answer set in particular, so the search reads them all."""
    return False


def _apart(program: Program, solver: Solver, rules: str) -> Grounded:
    """Ground `program` again, plainly, with `rules` added, for searches apart from the session.

    The rules are added as statements, as the session's are, so a program clingo is given as files
    keeps them. Its order is left alone. The rules head only names the session's prefix keeps
    apart from the program's, so its answer sets are the program's, each with those heads it
    derives.
    """
    match controlled(program, solver, lambda _statements: parsed(rules)):
        case Fault():
            message = "the program grounded once, so it grounds again"
            raise AssertionError(message)
        case found:
            return Grounded(found.control, found.facts, found.theory)


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
    source = sources(program)

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
    return Session(
        grounded,
        prepared.instances,
        limits=limits,
        interrupt=interrupt,
        apart=partial(_apart, program, solver),
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
