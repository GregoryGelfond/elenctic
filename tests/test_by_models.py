import pytest

from elenctic.by_models import from_models
from elenctic.contract import Claim, Entails
from elenctic.determination import Consequences, Consistent, Mode, Model, Models, Truncation
from elenctic.engine import solve
from elenctic.judge import judge
from elenctic.literals import AnswerSet, Literal
from elenctic.program import Program
from elenctic.search import Limits
from elenctic.spans import Position, Span
from elenctic.verdicts import Verdict

P, Q = Literal("p"), Literal("q")
CUT = (Truncation.TARGET, Truncation.BUDGET)
NOTHING: AnswerSet = frozenset()


def entails(mode: Mode, *literals: Literal) -> Entails:
    return Entails(mode, frozenset(literals))


def stopped(cut: Truncation, *shown: Literal) -> Consistent[Models]:
    atoms = frozenset(shown)
    return Consistent(Models(Model(atoms, atoms)), cut)


@pytest.mark.parametrize("cut", CUT)
@pytest.mark.parametrize(
    ("mode", "literals", "verdict"),
    [
        (Mode.CAUTIOUS, (P,), Verdict.FAIL),
        (Mode.CAUTIOUS, (P, Q), Verdict.FAIL),
        (Mode.BRAVE, (P,), Verdict.UNDECIDED),
        (Mode.BRAVE, (P, Q), Verdict.UNDECIDED),
        (Mode.CAUTIOUS, (), Verdict.PASS),
        (Mode.BRAVE, (), Verdict.PASS),
    ],
)
def test_a_cut_search_that_showed_nothing_settles_only_what_more_models_cannot_change(
    cut: Truncation, mode: Mode, literals: tuple[Literal, ...], verdict: Verdict
) -> None:
    assert from_models(entails(mode, *literals), stopped(cut))[0] is verdict


@pytest.mark.parametrize("cut", CUT)
@pytest.mark.parametrize(
    ("mode", "verdict"), [(Mode.CAUTIOUS, Verdict.UNDECIDED), (Mode.BRAVE, Verdict.PASS)]
)
def test_a_cut_search_that_showed_a_literal_upholds_only_what_more_models_cannot_undo(
    cut: Truncation, mode: Mode, verdict: Verdict
) -> None:
    assert from_models(entails(mode, P), stopped(cut, P))[0] is verdict


def test_a_search_cut_by_the_model_cap_settles_the_same_way() -> None:
    found = solve(Program("{p;q}."), limits=Limits(models=1))
    assert isinstance(found, Consistent)
    assert found.conclusion is Truncation.TARGET
    verdicts = [from_models(entails(Mode.CAUTIOUS, *lits), found)[0] for lits in ((P,), ())]
    assert verdicts == [Verdict.FAIL, Verdict.PASS]


@pytest.mark.parametrize("mode", Mode)
def test_an_empty_claim_holds_of_a_cut_native_search_too(mode: Mode) -> None:
    found = Consistent(Consequences(mode, NOTHING), Truncation.BUDGET)
    claim = Claim(entails(mode), frozenset(), Span("t.lp", Position(1, 1), Position(1, 2)))
    assert judge(claim, found).verdict is Verdict.PASS
