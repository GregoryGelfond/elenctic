"""Run a whole corpus of ``@``-contracts, or derive the plan a run would follow.

The corpus layer, sitting above the per-case one in ``harness``: which cases exist, what to do with
a file that could not become one, and what the whole run produced. A case is the unit ``harness``
knows about; a corpus is the unit anyone actually runs, and this is where the two meet.

:func:`run_corpus` and :func:`explain_corpus` each take an :class:`~elenctic.outcome.Invocation` and
return everything they produced — verdicts or plans, the reasons some case produced neither, and
what was observed about the corpus's health. Both are **total over their argument**: every
invocation that can be written is one they can carry out, because the modes that produce no run
cannot be expressed as an ``Invocation`` at all. Faults the run anticipates are recorded rather than
raised, which is what the error register is for; what still escapes is what no register anticipated,
and backstopping that belongs to whoever is running this rather than to the run.

This is what ``elenctic.cli`` is built out of. The console entry parses a command line into an
invocation, calls in here, renders what comes back and reads a status off it — so the program is a
derivation of the library rather than the place the library's work is done, and an embedder driving
these directly gets the same values the shipped runner does.
"""

from pathlib import Path
from time import monotonic
from typing import Protocol, assert_never

from elenctic.discovery import (
    ORPHAN_LIBRARY,
    UNDECLARED_SOLVER,
    Case,
    Corpus,
    DiscoveryError,
    HygieneReport,
    check_solver_available,
    inspect_corpus,
)
from elenctic.expectation import ContractError
from elenctic.harness import run_case
from elenctic.outcome import (
    CaseOutcome,
    CasePlan,
    ErrorKind,
    ErrorRecord,
    HygieneKind,
    HygieneRecord,
    Invocation,
    PlanOutcome,
    RunOutcome,
    Scope,
    error_kind,
)
from elenctic.program import ProgramError
from elenctic.registry import provides_theory
from elenctic.result import HarnessError
from elenctic.run import runs_for

__all__ = ["Observer", "PlanObserver", "RunObserver", "explain_corpus", "run_corpus"]


class Observer(Protocol):
    """What both modes tell a caller as they go — the announcements a run and a dry run share.

    A run holds everything it produced until it returns, which is the right shape for a caller that
    wants the result and the wrong one for a caller watching a hundred and thirty-five cases go by.
    So a caller may hand in an observer, and the run announces each thing as it establishes it. The
    default is to announce nothing at all: what this replaced wrote its prose unasked, and an
    embedder could only silence it by taking over their own process's streams — which costs them
    their own output to buy quiet, and still leaves the run's records reachable only by reading the
    prose back.

    **What is announced is a record, never a sentence.** A caller rendering prose already has
    everything the run knows, in the shape the run knows it in, and nothing has to be recovered by
    reading a string that was written to be read by a person. What the *record* cannot carry is
    where in the run it was met — the same ``ErrorRecord`` describes a file discovery could not use
    and a case whose program would not ground — so that is what the method name carries. Two
    announcements rather than one field: a field would have to be published in the machine-readable
    document, where it would say something about elenctic's own phases rather than about the fault.

    Every error and every verdict announced is the same object the run files, so a report rendered
    as the run goes and one rendered from the return value cannot describe it differently. Corpus
    hygiene is the exception and deliberately so: it is established before the first case is
    reached, it has no as-it-happens character, and it is read off the returned outcome — which is
    what the console entry does with it.

    Every method has a body that does nothing, and an implementation that **inherits** one of these
    gets those bodies, so it overrides only what it wants to hear about. An implementation that does
    not inherit is checked structurally and must supply every member: these are protocols, and a
    default body is inherited, never conjured. That is the one way this differs from the standard
    library's observers — a test result, a markup parser, a stream protocol — which are ordinary
    base classes and so offer only the first of the two.
    """

    def unusable(self, record: ErrorRecord) -> None:
        """Discovery could not use something: a corpus it could not read at all (the record is
        corpus-scoped), or one contract-bearing file it could not turn into a case (case-scoped).

        Announced before any solving, and the corpus-scoped one is the whole of what the invocation
        will produce."""
        return None

    def undecided(self, record: ErrorRecord) -> None:
        """A case that reached the run produced no verdict, and this is why.

        Distinct from :meth:`unusable` because the two are met at different points and mean
        different things to a reader: one is a file that never became a case, this is a case that
        did and then could not be carried out."""
        return None


class RunObserver(Observer, Protocol):
    """What a run announces: the two above, and a verdict per case that reached one."""

    def decided(self, outcome: CaseOutcome) -> None:
        """A case reached a verdict, with the reports it was folded from."""
        return None


class PlanObserver(Observer, Protocol):
    """What a dry run announces: the two shared ones, and the plan-shaped pair.

    A dry run decides nothing, so it has no verdict to announce; separating the two observers is
    what makes announcing one from the other mode not merely wrong but unwritable.
    """

    def began(self, case: Case) -> None:
        """A case is about to have its run plan derived.

        Announced before the derivation rather than after it, because the derivation is what can
        fail: a case whose plan cannot be built is announced here and then to :meth:`undecided`, and
        a caller narrating the corpus still has the case to narrate it against."""
        return None

    def planned(self, case_plan: CasePlan) -> None:
        """A case derived to a run plan, with the runs it derived to."""
        return None


class _Silent(RunObserver, PlanObserver):
    """What a caller who supplied no observer is given: told everything, says nothing.

    A stand-in rather than a test against ``None`` at each of the eight places a run announces
    something. Those tests would all read the same and any one of them could be forgotten, which is
    the shape where a mode goes quiet for one kind of thing and nobody notices.

    It inherits every method, and inherits them as the do-nothing bodies the protocols declare — so
    an announcement added later is silent here without this class being touched, which is the one
    behaviour a silent observer should never have to be reminded of.
    """


_SILENT = _Silent()


# What an allocation failure has to say about the case that met it — shared by the diagnostic the
# reader sees and the record a consumer reads, so those two cannot come to differ. The backstop in
# ``main`` says the same thing about a whole corpus and says it separately, because a frame with no
# case to name cannot claim which one was running. Where the memory went is not knowable from either
# frame: grounding is the usual answer, and a solve holds every model it is shown, so both are named
# rather than the likelier one asserted.
_OUT_OF_MEMORY = (
    "elenctic ran out of memory running this case. Grounding has no size limit available to it, "
    "and a solve holds every model it is shown — reduce what this case grounds or enumerates, or "
    "run the corpus under a memory limit. No verdict was produced for it."
)


def run_corpus(invocation: Invocation, *, observer: RunObserver | None = None) -> RunOutcome:
    """Run the corpus an invocation names, and return everything the run produced.

    The seam the process status is read off and the machine-readable report is built from, so that
    the number a shell sees and the document a consumer stores are two readings of one value and
    cannot come to disagree about the same run. It is also what makes a record observable at all: a
    status carries one closed bit of one, so without this the locus a fault was filed under would
    be asserted nowhere.

    Total over its argument: every invocation this can be given is one it can run, because the
    modes that produce no run cannot be written as an :class:`Invocation`. Faults the run
    anticipates are recorded rather than raised — that is what the error register is — and what
    still escapes is what no register anticipated, which the console entry backstops.

    **Silent.** It writes to no stream. A caller who wants to see the run happen as it happens
    hands in an ``observer`` and is told each thing as it is established; a caller who only wants
    the result passes nothing and gets it back whole. Every error and every verdict announced is
    the same object this returns, so the two readings cannot come to describe the run differently;
    corpus hygiene is read off the returned outcome, being settled before the first case is reached.

    Named apart from the module ``elenctic.run``, which a package attribute of the same name would
    resolve to instead.
    """
    told: RunObserver = _SILENT if observer is None else observer
    match _discover(invocation.target, told):
        case ErrorRecord() as fault:
            return RunOutcome(cases=(), errors=(fault,), hygiene=())
        case Corpus() as corpus:
            unrunnable, hygiene = _record_discovered(corpus, strict=invocation.strict, told=told)
            return _run(
                corpus.cases,
                invocation.budget,
                unrunnable=unrunnable,
                hygiene=hygiene,
                deadline=invocation.deadline,
                told=told,
            )
        case unreachable:
            assert_never(unreachable)


def explain_corpus(invocation: Invocation, *, observer: PlanObserver | None = None) -> PlanOutcome:
    """Derive the run plan this invocation would follow, and return everything the dry run
    produced.

    The sibling of :func:`run_corpus`, and the same shape for the same reason: a dry run decides
    nothing, but it still establishes something about every case it meets — a plan, or the reason
    there is none — and a mode that hands back only a number leaves that unobserved. What it must
    not do is report those plans as verdicts, which is why they are their own register rather than
    an empty one.

    A plan that cannot be built is elenctic's own fault, and surfacing one before any solving is
    the whole purpose of this mode.

    Silent, and told through an ``observer``, exactly as :func:`run_corpus` is. Its observer is the
    other one: this mode announces a plan where that one announces a verdict.
    """
    told: PlanObserver = _SILENT if observer is None else observer
    match _discover(invocation.target, told):
        case ErrorRecord() as fault:
            return PlanOutcome(plans=(), errors=(fault,), hygiene=())
        case Corpus() as corpus:
            unrunnable, hygiene = _record_discovered(corpus, strict=invocation.strict, told=told)
            plans, misroutes = _explain(corpus.cases, told=told)
            return PlanOutcome(plans=plans, errors=(*unrunnable, *misroutes), hygiene=hygiene)
        case unreachable:
            assert_never(unreachable)


def _discover(target: Path, told: Observer) -> Corpus | ErrorRecord:
    """The corpus a target holds, or — when discovery could not read one — the fault that is the
    whole of what the invocation produced.

    A fault here belongs to no case, because there are none: it is the corpus's. It is handed back
    as a record rather than as an outcome because which outcome holds it is the caller's question,
    and the two modes answer it differently."""
    try:
        return inspect_corpus(target)
    except (DiscoveryError, ContractError, ProgramError) as exc:
        fault = _corpus_fault(
            error_kind(exc), str(exc), source=target if target.is_file() else None
        )
        told.unusable(fault)
        return fault


def _record_discovered(
    corpus: Corpus, *, strict: bool, told: Observer
) -> tuple[tuple[ErrorRecord, ...], tuple[HygieneRecord, ...]]:
    """The contract-bearing files discovery could not use, announced and recorded, together with
    what it observed about the corpus around them — the two things every mode starts from."""
    unrunnable = _unrunnable_records(corpus.unrunnable)
    for record in unrunnable:
        # Discovered but unusable — an unresolvable #include, an undecodable byte, a malformed
        # contract. Filed against the file it belongs to, in the same register as a case the runner
        # could not run, so one bad file never costs the corpus its other results.
        told.unusable(record)
    return unrunnable, _hygiene_records(corpus.hygiene, strict=strict)


def _corpus_fault(kind: ErrorKind, message: str, *, source: Path | None = None) -> ErrorRecord:
    """One fault belonging to no single case, and therefore to the corpus: nothing was discovered,
    or the frame that met the fault had no case to name.

    ``source`` is the file when exactly one was involved — a target named on the command line is
    the only file the fault can belong to, while a directory names no one file and the diagnostic's
    own provenance is where the reader looks."""
    return ErrorRecord(kind=kind, scope=Scope.CORPUS, source=source, message=message)


def _hygiene_records(hygiene: HygieneReport, *, strict: bool) -> tuple[HygieneRecord, ...]:
    """Every corpus-health observation, whatever the strictness dial says about reporting it, each
    carrying the footing that dial put it on.

    The dial decides what is *printed* and what fails the run; it does not decide what was
    *observed*. A consumer reading the run's output is owed the observations themselves and applies
    its own policy to them, which it cannot do if the run has already dropped the ones this
    invocation chose to stay silent about. Grading them here is what leaves one collection to read
    for both — and one place where the dial is consulted at all."""
    return (
        *(
            HygieneRecord(
                kind=HygieneKind.ORPHAN_LIBRARY,
                grade=HygieneKind.ORPHAN_LIBRARY.grade_under(strict=strict),
                source=path,
                message=ORPHAN_LIBRARY,
            )
            for path in hygiene.orphan_libraries
        ),
        *(
            HygieneRecord(
                kind=HygieneKind.UNDECLARED_SOLVER,
                grade=HygieneKind.UNDECLARED_SOLVER.grade_under(strict=strict),
                source=path,
                message=UNDECLARED_SOLVER,
            )
            for path in hygiene.undeclared_solvers
        ),
    )


def _unrunnable_records(unrunnable: tuple[tuple[Path, Exception], ...]) -> tuple[ErrorRecord, ...]:
    """The contract-bearing files discovery could not turn into cases, in the same register as a
    case the runner could not run: both are a file that will produce no verdict, and the reader
    does not care which side of discovery it failed on."""
    return tuple(
        ErrorRecord(kind=error_kind(fault), scope=Scope.CASE, source=path, message=str(fault))
        for path, fault in unrunnable
    )


def _explain(
    cases: tuple[Case, ...], *, told: PlanObserver
) -> tuple[tuple[CasePlan, ...], tuple[ErrorRecord, ...]]:
    """Derive the run plan per case without solving (the dry-run): each run's mode and the
    projection decision (which the contract's reads induce), and each check with the fields it
    reads.

    Every case leaves here in exactly one register — the plan it derived to, or the reason it
    derived to none — which is the same accounting a real run keeps, for the same reason: a mode
    that establishes a plan and then hands back nothing but a number has established something
    about each case that nothing can afterwards check. A plan that cannot be built is a harness
    fault, and this is the mode whose whole purpose is to surface one before any solving.

    Each case is announced before its plan is derived, because deriving is the step that can fail:
    a caller narrating the corpus has the case in hand either way, and so can say which one it was
    that had no plan."""
    plans: list[CasePlan] = []
    misroutes: list[ErrorRecord] = []
    for case in cases:
        told.began(case)
        try:
            derived = runs_for(case.expectation, provides_theory(case.solver))
        except HarnessError as exc:
            misroutes.append(_case_error(ErrorKind.HARNESS, case, str(exc)))
            told.undecided(misroutes[-1])
            continue
        case_plan = CasePlan(case=case, runs=tuple(derived))
        plans.append(case_plan)
        told.planned(case_plan)
    return tuple(plans), tuple(misroutes)


def _run(
    cases: tuple[Case, ...],
    budget: float,
    *,
    unrunnable: tuple[ErrorRecord, ...],
    hygiene: tuple[HygieneRecord, ...],
    deadline: float | None = None,
    told: RunObserver,
) -> RunOutcome:
    """Validate every plan up front, then solve + check each case, announcing each as it lands.

    Every discovered case leaves here in exactly one register: a verdict it produced, or the reason
    it produced none. Nothing is counted by subtracting one register from another, so there is no
    arrangement in which a case is accounted for by being left out.

    ``unrunnable`` carries the contract-bearing files discovery could not turn into cases, and
    ``hygiene`` what discovery observed about the corpus around them. Both are passed through rather
    than recomputed: they were established before the run began, and the outcome is the whole of
    what the invocation produced. Neither has a default, because a caller who omitted one would get
    an outcome that accounts for fewer files than were discovered — which is the one thing the
    registers exist to make impossible.

    ``deadline`` bounds the run rather than a solve. ``budget`` bounds one solve, and a case can
    route to several, so a corpus costs a product of three numbers of which only one was bounded.
    It is off unless asked for: unlike a model cap there is no run duration obviously beyond
    legitimate use, and a default low enough to bound a hostile corpus would turn a large honest
    one into cases that could not be run — a worse failure than the one it prevents."""
    valid, misroutes = _validate_plans(cases, told=told)
    errors = [*unrunnable, *misroutes]
    outcomes: list[CaseOutcome] = []
    started = monotonic()
    for reached, case in enumerate(valid):
        if deadline is not None and monotonic() - started >= deadline:
            # Stop dispatching, and account for every case that will not run. Each gets its own
            # record, because a count cannot say which case is missing — and each is announced,
            # because a caller is owed the same records whether it waited for the return or not.
            # That one passed deadline is a single event costing many cases their result is a fact
            # about these records that a caller rendering them can see; it is not a reason for the
            # run to have kept some of them back.
            passed = f"the run passed its {deadline}s deadline before reaching this case"
            for unreached in valid[reached:]:
                errors.append(
                    ErrorRecord(
                        kind=ErrorKind.DEADLINE,
                        scope=Scope.CASE,
                        source=unreached.contract_source,
                        message=passed,
                    )
                )
                told.undecided(errors[-1])
            break
        try:
            # The declared solver is checked here, per case, so an absent optional backend costs
            # only the cases that declare it rather than the whole run.
            check_solver_available(case.solver, case.contract_source)
            reports = run_case(case, budget=budget)  # plan validated above
        except DiscoveryError as exc:
            # the environment cannot run this case (its declared solver is not installed). The
            # message carries its own provenance, as every discovery diagnostic does.
            errors.append(_case_error(ErrorKind.DISCOVERY, case, str(exc)))
            told.undecided(errors[-1])
            continue
        except ProgramError as exc:
            # the program under test cannot be run (it will not ground, an #include is unresolvable)
            # — its author fixes the .lp. Not a verdict, and not elenctic's fault either, so it is
            # filed apart from both and the remaining cases still run.
            errors.append(_case_error(ErrorKind.PROGRAM, case, str(exc)))
            told.undecided(errors[-1])
            continue
        except MemoryError:
            # Filed against the case that ran out of it, and with the other cases that could not be
            # run, so the corpus keeps every result it had already earned. Nothing is bounded by
            # this — the grounder offers no size limit and so neither can elenctic — but what it
            # costs is one case's result rather than the whole run's. A resource the caller is the
            # one able to bound, so not elenctic's own fault to report.
            errors.append(_case_error(ErrorKind.RESOURCE, case, _OUT_OF_MEMORY))
            told.undecided(errors[-1])
            continue
        except HarnessError as exc:
            # a solve-time invariant breach (a seam, a missing cost) is a harness bug too, never a
            # verdict — filed like a misroute, and the other cases still run.
            errors.append(_case_error(ErrorKind.HARNESS, case, str(exc)))
            told.undecided(errors[-1])
            continue
        outcome = CaseOutcome(case=case, reports=reports)
        outcomes.append(outcome)
        # Announced whatever the verdict is. Which verdicts are worth a reader's attention is a
        # rendering policy and the caller's to set; a run that announced only the ones it judged
        # interesting would be deciding that for every caller at once.
        told.decided(outcome)
    return RunOutcome(cases=tuple(outcomes), errors=tuple(errors), hygiene=hygiene)


def _case_error(kind: ErrorKind, case: Case, message: str) -> ErrorRecord:
    """One case's reason for producing no verdict, against the file it belongs to."""
    return ErrorRecord(kind=kind, scope=Scope.CASE, source=case.contract_source, message=message)


def _validate_plans(
    cases: tuple[Case, ...], *, told: RunObserver
) -> tuple[list[Case], list[ErrorRecord]]:
    """Build every case's run plan up front (pure ``runs_for``), so all wiring errors surface before
    any solving. Returns the well-routed cases and a record per misrouted one (a harness error —
    never a verdict)."""
    valid: list[Case] = []
    misroutes: list[ErrorRecord] = []
    for case in cases:
        try:
            runs_for(case.expectation, provides_theory(case.solver))
        except HarnessError as exc:
            misroutes.append(_case_error(ErrorKind.HARNESS, case, str(exc)))
            told.undecided(misroutes[-1])
        else:
            valid.append(case)
    return valid, misroutes
