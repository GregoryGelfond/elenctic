"""A program grounded once, searched under any number of scenarios."""

from collections.abc import Callable, Iterable
from dataclasses import replace

from clingo import Control
from clingo import Model as ClingoModel
from clingo.configuration import Configuration

from elenctic.determination import (
    AnswerSets,
    Consequences,
    Determination,
    Exhausted,
    Inconclusive,
    Mode,
    NoAssumptions,
    NotThese,
    Optimized,
    Refutation,
    These,
    Truncation,
)
from elenctic.facts import Facts
from elenctic.literals import Assumption, Literal, Scenario, Signature
from elenctic.search import (
    ENUMERATION,
    KEEP_ALL,
    KEEP_NONE,
    KEEP_SHOWN,
    OPTIMIZATION,
    Cut,
    Interrupt,
    Keep,
    Limit,
    Limits,
    Plan,
    Request,
    Run,
    Seen,
    answer_sets,
    decide,
    drain,
    optimized,
    proven,
    seen,
)
from elenctic.theory import Theory

_PROBE = Plan(ENUMERATION, max_answer_sets=0, keep=KEEP_NONE)


def _key(assumption: Assumption) -> tuple[Literal, bool]:
    return assumption.literal, assumption.holds


def _solve_section(ctl: Control) -> Configuration:
    section = ctl.configuration.solve
    if isinstance(section, Configuration):
        return section
    message = "clingo has no solve configuration"
    raise TypeError(message)


class Grounded:
    """A program grounded once, to be searched under any number of scenarios."""

    def __init__(self, control: Control, facts: Facts, theory: Theory) -> None:
        self._control = control
        self._theory = theory
        self.facts = facts
        # Signatures from clingo; atom→literal looked up on demand so a sat-only case
        # never walks the whole symbolic atom table.
        self.signatures: frozenset[Signature] = frozenset(
            Signature(name, arity, positive)
            for name, arity, positive in control.symbolic_atoms.signatures
        )

    def _derivable(self, literal: Literal) -> bool:
        return literal.symbol in self._control.symbolic_atoms

    def _assumed(self, scenario: Iterable[Assumption]) -> dict[int, Assumption]:
        """Map the clingo literal of each assumption that says something about the grounding."""
        atoms = self._control.symbolic_atoms
        assumed: dict[int, Assumption] = {}
        for a in scenario:
            symbol = a.literal.symbol
            if symbol not in atoms:
                continue
            lit = atoms[symbol].literal
            assumed[lit if a.holds else -lit] = a
        return assumed

    def _impossible(self, scenario: Iterable[Assumption]) -> frozenset[Assumption]:
        return frozenset(a for a in scenario if a.holds and not self._derivable(a.literal))

    def _run(self, scenario: Scenario, plan: Plan, cut: Cut) -> Run:
        assumed = self._assumed(scenario)
        if impossible := self._impossible(scenario):
            return Run((), Exhausted.EXHAUSTED, impossible)
        section = _solve_section(self._control)
        section.models = "0"
        section.enum_mode, section.opt_mode = plan.modes
        section.project = "auto" if plan.project else "no"

        def read(answer_set: ClingoModel) -> Seen:
            return seen(answer_set, self._theory, plan.keep)

        with self._control.solve(assumptions=list(assumed), yield_=True, async_=True) as handle:
            found, conclusion = drain(handle, plan, cut, read)
            run = Run(tuple(found), conclusion, frozenset())
            core = (
                frozenset(assumed[lit] for lit in handle.core())
                if run.refuted
                else frozenset[Assumption]()
            )
        return replace(run, core=core)

    def _contradicts(
        self, scenario: frozenset[Assumption], cut: Cut
    ) -> frozenset[Assumption] | Truncation | None:
        """Return a core of `scenario`, a truncation, or `None` if some answer set satisfies it."""
        if impossible := self._impossible(scenario):
            return impossible
        run = self._run(scenario, _PROBE, cut)
        match run.conclusion:
            case Exhausted.EXHAUSTED:
                return run.core
            case Truncation.MAX_ANSWER_SETS:
                return None
            case Truncation() as truncation:
                return truncation

    def refute(self, core: frozenset[Assumption], request: Request) -> Refutation:
        """Say why no answer set satisfies the scenario: a clashing subset, shrunk from `core`."""
        return self._shrunk(request.scenario, core, request.cutter())

    def _shrunk(self, scenario: Scenario, core: frozenset[Assumption], cut: Cut) -> Refutation:
        if not scenario:
            return NoAssumptions()
        kept = core
        for assumption in sorted(kept, key=_key):
            if assumption not in kept:
                continue
            match self._contradicts(kept - {assumption}, cut):
                case frozenset() as smaller:
                    kept = smaller
                case Truncation():
                    return These(kept, minimal=False)
                case None:
                    pass
        return These(kept) if kept else NotThese()

    def _search[E](
        self, request: Request, plan: Plan, evidence: Callable[[list[Seen]], E]
    ) -> Determination[E]:
        cut = request.cutter()
        run = self._run(request.scenario, plan, cut)
        refutation = self._shrunk(request.scenario, run.core, cut) if run.refuted else None
        return decide(run, refutation, evidence)

    def solve(  # noqa: PLR0913
        self,
        scenario: Scenario = frozenset(),
        *,
        limits: Limits = Limits(),
        interrupt: Interrupt | None = None,
        project: bool = False,
        enough: Callable[[list[Seen]], bool] | None = None,
        keep: Keep = KEEP_ALL,
    ) -> Determination[AnswerSets]:
        """Enumerate the answer sets satisfying `scenario`, whatever the program optimizes."""
        return self._search(
            Request(scenario, limits, interrupt),
            Plan(
                ENUMERATION,
                max_answer_sets=limits.max_answer_sets,
                project=project,
                enough=enough,
                keep=keep,
            ),
            answer_sets,
        )

    def consequences(
        self,
        mode: Mode,
        scenario: Scenario = frozenset(),
        *,
        limits: Limits = Limits(),
        interrupt: Interrupt | None = None,
    ) -> Determination[Consequences]:
        """Compute the cautious or brave consequences among the shown atoms, natively.

        They are those of all the answer sets, whatever the program optimizes.
        """
        return self._search(
            Request(scenario, limits, interrupt),
            Plan((mode.value, "ignore"), keep=KEEP_SHOWN),
            lambda found: Consequences(mode, found[-1].answer_set.shown),
        )

    def optimize(
        self,
        scenario: Scenario = frozenset(),
        *,
        limits: Limits = Limits(),
        interrupt: Interrupt | None = None,
        project: bool = False,
        keep: Keep = KEEP_ALL,
    ) -> Determination[Optimized]:
        """Find the optimum under `scenario` and the answer sets that attain it.

        `limits.max_answer_sets` bounds the optimal answer sets, not the improving ones on the way.
        When `project` is set, prove the optimum first, then enumerate at that cost with projection
        (clingo's optN interacts badly with `--project` across improving levels).
        """
        request = Request(scenario, limits, interrupt)
        if not project:
            return self._search(
                request,
                Plan(OPTIMIZATION, proven, limits.max_answer_sets, keep=keep),
                optimized,
            )
        return self._optimize_projected(request, keep=keep)

    def _optimize_projected(
        self, request: Request, *, keep: Keep = KEEP_ALL
    ) -> Determination[Optimized]:
        """Prove the optimum, then enumerate at that cost with `#show` projection."""
        cut = request.cutter()
        prove = self._run(
            request.scenario,
            Plan(("auto", "opt"), max_answer_sets=Limit.UNBOUNDED, keep=keep),
            cut,
        )
        if prove.refuted:
            return decide(prove, self._shrunk(request.scenario, prove.core, cut), optimized)
        if not prove.found:
            return decide(prove, None, optimized)
        if isinstance(prove.conclusion, Truncation):
            return Inconclusive(prove.conclusion)
        bound = ",".join(str(level) for level in prove.found[-1].cost)
        enumerated = self._run(
            request.scenario,
            Plan(
                ("auto", f"enum,{bound}"),
                max_answer_sets=request.limits.max_answer_sets,
                project=True,
                keep=keep,
            ),
            cut,
        )
        # enum-at-cost yields only optimal answer sets; clingo may not set optimality_proven.
        marked = replace(
            enumerated,
            found=tuple(replace(seen, proven=True) for seen in enumerated.found),
        )
        return decide(marked, None, optimized)
