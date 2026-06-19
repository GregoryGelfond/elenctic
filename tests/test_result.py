from clingo import Function

from elenctic.result import Observable, SolveResult, Verdict


def test_observable_is_hashable_and_value_equal() -> None:
    a, b = Function("a"), Function("b")
    o1 = Observable(frozenset({a, b}))
    o2 = Observable(frozenset({b, a}))
    assert o1 == o2
    assert hash(o1) == hash(o2)
    assert len({o1, o2}) == 1  # dedups in a set


def test_observable_distinct_by_assignment() -> None:
    a = Function("a")
    o1 = Observable(frozenset({a}), frozenset({(Function("x"), 1)}))
    o2 = Observable(frozenset({a}), frozenset({(Function("x"), 2)}))
    assert o1 != o2  # spec §2.0: equal shown, different assign ⇒ distinct observables


def test_solveresult_defaults() -> None:
    r = SolveResult(completed=True)
    assert r.observables == ()
    assert r.optimal_observables == ()
    assert r.union is None
    assert r.intersection is None
    assert r.optimum_cost is None


def test_verdict_three_valued() -> None:
    assert len({Verdict.PASS, Verdict.FAIL, Verdict.UNDECIDED}) == 3
