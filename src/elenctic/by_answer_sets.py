"""Judge a claim from the answer sets a search enumerated."""

from collections.abc import Iterable
from typing import Final

from elenctic.contract import (
    Asks,
    Assigns,
    Binds,
    Census,
    Costs,
    Entails,
    Reading,
    Satisfiable,
    Witness,
)
from elenctic.determination import (
    AnswerSet,
    AnswerSets,
    Consistent,
    Exhausted,
    Mode,
    Range,
    Truncation,
    WorldView,
    world_view,
)
from elenctic.literals import Atoms, Symbol
from elenctic.query import answer, bindings
from elenctic.verdicts import Detail, Ended, Verdict, existential, universal
from elenctic.writer import bound, braces, where

_INTERSECTION: Final = "\N{N-ARY INTERSECTION}"
_UNION: Final = "\N{UNION}"
_SUBSET: Final = "\N{SUBSET OF OR EQUAL TO}"


def _sets(over: Range) -> str:
    return "optimal answer sets" if over is Range.OPTIMAL else "answer sets"


def _count(claim: Census, answer_sets: Iterable[AnswerSet], *, closed: bool) -> tuple[Verdict, str]:
    """Count the distinct answers: an answer set's identity is what it shows and what it assigns."""
    answers = {answer_set.identity for answer_set in answer_sets}
    seen = len(answers)
    verdict = universal(
        refuted=seen > claim.count or (closed and seen < claim.count), closed=closed
    )
    noun = "with their assignments" if any(assignment for _, assignment in answers) else ""
    return (
        verdict,
        f"{claim.count} expected, {seen} distinct shown {_sets(claim.over)} {noun}".rstrip(),
    )


def _witnessed(
    claim: Witness | Assigns, answer_sets: Iterable[AnswerSet], *, closed: bool
) -> tuple[Verdict, str]:
    seen = any(claim.upheld_by(answer_set) for answer_set in answer_sets)
    return existential(
        found=seen, closed=closed
    ), f"{_stated(claim)} by an answer set: {'yes' if seen else 'no'}"


def _stated(claim: Witness | Assigns) -> str:
    match claim:
        case Witness(literals, _, assignment):
            return f"{braces(literals)} shown{where(assignment)}"
        case Assigns(assignment):
            return f"{bound(assignment)} assigned"


def entailed(claim: Entails, held: Atoms, *, closed: bool) -> tuple[Verdict, str]:
    cautious = claim.mode is Mode.CAUTIOUS
    missing = claim.literals - held
    vacuous = not claim.literals
    verdict = (
        universal(refuted=bool(missing), closed=closed or vacuous)
        if cautious
        else existential(found=not missing, closed=closed)
    )
    space = "Opt(P)" if claim.over is Range.OPTIMAL else "AS(P)"
    meet = _INTERSECTION if cautious else _UNION
    detail = f"{braces(claim.literals)} {_SUBSET} {meet} {space} = {braces(held)}"
    return verdict, detail + (f" (missing: {braces(missing)})" if missing else "")


def _entails(claim: Entails, view: WorldView, *, closed: bool) -> tuple[Verdict, str]:
    held = view.cautious if claim.mode is Mode.CAUTIOUS else view.brave
    return entailed(claim, held, closed=closed)


def _asked(claim: Asks | Binds, view: WorldView) -> tuple[Verdict, str]:
    match claim:
        case Asks():
            found = answer(claim.query, view)
            return (
                Verdict.when(holds=found is claim.answer),
                f"{claim.answer} expected, answer is {found}",
            )
        case Binds():
            got = bindings(claim.pattern, view).giving(claim.answer)
            detail = f"{claim.answer} bindings expected {_rows(claim.bindings)}, found {_rows(got)}"
            return Verdict.when(holds=got == claim.bindings), detail


def _rows(found: frozenset[tuple[Symbol, ...]]) -> str:
    return "{ " + ", ".join(sorted("(" + ",".join(map(str, row)) + ")" for row in found)) + " }"


def _worldly(reading: Asks | Binds, found: Consistent[AnswerSets]) -> tuple[Verdict, Detail]:
    view = world_view(found, shown=False)
    if isinstance(view, Truncation):
        return Verdict.UNDECIDED, Ended(view)
    return _asked(reading, view)


def from_answer_sets(reading: Reading, found: Consistent[AnswerSets]) -> tuple[Verdict, Detail]:
    answer_sets = found.evidence.all
    closed = found.conclusion is Exhausted.EXHAUSTED
    match reading:
        case Asks() | Binds():
            return _worldly(reading, found)
        case Satisfiable(expected):
            return Verdict.when(holds=expected), "an answer set exists"
        case Census():
            return _count(reading, answer_sets, closed=closed)
        case Witness() | Assigns():
            return _witnessed(reading, answer_sets, closed=closed)
        case Entails():
            return _entails(
                reading, WorldView(frozenset(m.shown for m in answer_sets)), closed=closed
            )
        case Costs():
            return Verdict.UNDECIDED, "no optimum was sought"
