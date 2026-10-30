"""A program grounded once, searched under any number of scenarios."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace

from clingo import Control, Symbol, SymbolType
from clingo import Model as ClingoModel
from clingo.configuration import Configuration

from elenctic.determination import (
    Consequences,
    Determination,
    Exhausted,
    Mode,
    Models,
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
    OPTIMIZATION,
    UNLIMITED,
    Cut,
    Interrupt,
    Limits,
    Plan,
    Request,
    Run,
    Seen,
    decide,
    drain,
    models,
    optimized,
    proven,
    seen,
)
from elenctic.theory import Theory

_PROBE = Plan(ENUMERATION, cap=0)


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
        # Read before any search: clingo later drops atoms that assumptions have made false.
        self._literals: Mapping[Symbol, int] = {
            atom.symbol: atom.literal for atom in control.symbolic_atoms
        }
        self.signatures: frozenset[Signature] = frozenset(
            Signature(symbol.name, len(symbol.arguments), symbol.positive)
            for symbol in self._literals
            if symbol.type is SymbolType.Function
        )

    def _derivable(self, literal: Literal) -> bool:
        return bool(self._literals.get(literal.symbol))

    def _assumed(self, scenario: Iterable[Assumption]) -> dict[int, Assumption]:
        """Map the clingo literal of each assumption that says something about the grounding."""
        return {
            (lit if a.holds else -lit): a
            for a in scenario
            if (lit := self._literals.get(a.literal.symbol))
        }

    def _impossible(self, scenario: Iterable[Assumption]) -> frozenset[Assumption]:
        return frozenset(a for a in scenario if a.holds and not self._derivable(a.literal))

    def _read(self, model: ClingoModel) -> Seen:
        return seen(model, self._theory)

    def _run(self, scenario: Scenario, plan: Plan, cut: Cut) -> Run:
        assumed = self._assumed(scenario)
        if impossible := self._impossible(scenario):
            return Run((), Exhausted.EXHAUSTED, impossible)
        section = _solve_section(self._control)
        section.models = "0"
        section.enum_mode, section.opt_mode = plan.modes
        with self._control.solve(assumptions=list(assumed), yield_=True, async_=True) as handle:
            found, conclusion = drain(handle, plan, cut, self._read)
            run = Run(tuple(found), conclusion, frozenset())
            core = frozenset(assumed[lit] for lit in handle.core()) if run.refuted else frozenset()
        return replace(run, core=core)

    def _contradicts(
        self, scenario: frozenset[Assumption], cut: Cut
    ) -> frozenset[Assumption] | Truncation | None:
        """Return a core of `scenario`, a truncation, or `None` if some model satisfies it."""
        if impossible := self._impossible(scenario):
            return impossible
        run = self._run(scenario, _PROBE, cut)
        match run.conclusion:
            case Exhausted.EXHAUSTED:
                return run.core
            case Truncation.TARGET:
                return None
            case Truncation() as truncation:
                return truncation

    def refute(self, core: frozenset[Assumption], request: Request) -> Refutation:
        """Say why no model satisfies the scenario: a clashing subset, shrunk from `core`."""
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

    def solve(
        self,
        scenario: Scenario = frozenset(),
        *,
        limits: Limits = UNLIMITED,
        interrupt: Interrupt | None = None,
    ) -> Determination[Models]:
        """Enumerate the stable models satisfying `scenario`, whatever the program optimizes."""
        plan = Plan(ENUMERATION, cap=limits.models)
        return self._search(Request(scenario, limits, interrupt), plan, models)

    def consequences(
        self,
        mode: Mode,
        scenario: Scenario = frozenset(),
        *,
        limits: Limits = UNLIMITED,
        interrupt: Interrupt | None = None,
    ) -> Determination[Consequences]:
        """Compute the cautious or brave consequences among the shown atoms, natively."""
        plan = Plan((mode.value, "ignore"))
        return self._search(
            Request(scenario, limits, interrupt),
            plan,
            lambda found: Consequences(mode, found[-1].model.shown),
        )

    def optimize(
        self,
        scenario: Scenario = frozenset(),
        *,
        limits: Limits = UNLIMITED,
        interrupt: Interrupt | None = None,
    ) -> Determination[Optimized]:
        """Find the optimum under `scenario` and the models that attain it.

        `limits.models` bounds the optimal models, not the improving ones found on the way.
        """
        plan = Plan(OPTIMIZATION, proven, limits.models)
        return self._search(Request(scenario, limits, interrupt), plan, optimized)
