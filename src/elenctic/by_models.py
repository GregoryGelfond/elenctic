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
    Consistent,
    Exhausted,
    Mode,
    Model,
    Models,
    Range,
    Truncation,
    WorldView,
    world_view,
)
from elenctic.literals import AnswerSet, Symbol
from elenctic.query import answer, bindings
from elenctic.verdicts import Verdict, existential, universal
from elenctic.writer import bound, braces, where

_INTERSECTION: Final = "\N{N-ARY INTERSECTION}"
_UNION: Final = "\N{UNION}"
_SUBSET: Final = "\N{SUBSET OF OR EQUAL TO}"


def _sets(over: Range) -> str:
    return "optimal answer sets" if over is Range.OPTIMAL else "answer sets"


def _count(claim: Census, models: Iterable[Model], *, closed: bool) -> tuple[Verdict, str]:
    """Count the distinct answers: a model's identity is what it shows and what it assigns."""
    answers = {model.identity for model in models}
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
    claim: Witness | Assigns, models: Iterable[Model], *, closed: bool
) -> tuple[Verdict, str]:
    seen = any(claim.upheld_by(model) for model in models)
    return existential(
        found=seen, closed=closed
    ), f"{_stated(claim)} by an answer set: {'yes' if seen else 'no'}"


def _stated(claim: Witness | Assigns) -> str:
    match claim:
        case Witness(literals, _, assignment):
            return f"{braces(literals)} shown{where(assignment)}"
        case Assigns(assignment):
            return f"{bound(assignment)} assigned"


def entailed(claim: Entails, held: AnswerSet, *, closed: bool) -> tuple[Verdict, str]:
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
        case Asks(expected, query):
            found = answer(query, view)
            return Verdict.when(holds=found is expected), f"{expected} expected, answer is {found}"
        case Binds(expected, pattern, wanted):
            got = bindings(pattern, view).giving(expected)
            detail = f"{expected} bindings expected {_rows(wanted)}, found {_rows(got)}"
            return Verdict.when(holds=got == wanted), detail


def _rows(found: frozenset[tuple[Symbol, ...]]) -> str:
    return "{ " + ", ".join(sorted("(" + ",".join(map(str, row)) + ")" for row in found)) + " }"


def _worldly(reading: Asks | Binds, found: Consistent[Models]) -> tuple[Verdict, str]:
    view = world_view(found)
    if isinstance(view, Truncation):
        return Verdict.UNDECIDED, f"search ended: {view}"
    return _asked(reading, view)


def from_models(reading: Reading, found: Consistent[Models]) -> tuple[Verdict, str]:
    models = found.evidence.all
    closed = found.conclusion is Exhausted.EXHAUSTED
    match reading:
        case Asks() | Binds():
            return _worldly(reading, found)
        case Satisfiable(expected):
            return Verdict.when(holds=expected), "an answer set exists"
        case Census():
            return _count(reading, models, closed=closed)
        case Witness() | Assigns():
            return _witnessed(reading, models, closed=closed)
        case Entails():
            return _entails(reading, WorldView(frozenset(m.shown for m in models)), closed=closed)
        case Costs():
            return Verdict.UNDECIDED, "no optimum was sought"
