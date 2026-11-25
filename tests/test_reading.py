"""An answer set is read from what its grounding has read, however large it is."""

import pytest

from elenctic.determination import Consistent
from elenctic.engine import solve
from elenctic.literals import Literal, Symbol
from elenctic.program import Program
from elenctic.search import Literals

ATOMS = 70_000
"""More atoms than any fixed memory of symbols read would hold at once."""


def test_each_symbol_of_a_grounding_is_read_once(monkeypatch: pytest.MonkeyPatch) -> None:
    read: list[Symbol] = []
    of = Literal.of

    def counted(symbol: Symbol) -> Literal:
        read.append(symbol)
        return of(symbol)

    monkeypatch.setattr(Literal, "of", counted)
    found = solve(Program(f"p(1..{ATOMS}).\n"))
    assert isinstance(found, Consistent)
    assert [len(each.atoms) for each in found.evidence.all] == [ATOMS]
    assert len(read) == len(set(read)) == ATOMS


def test_literals_keep_only_the_classical_literals() -> None:
    literals = Literals()
    symbols = [Literal.parse("p(1)").symbol, Literal.parse("-q").symbol]
    assert literals(symbols) == frozenset({Literal.parse("p(1)"), Literal.parse("-q")})
    assert literals(symbols) == literals(reversed(symbols))
    assert len(literals.read) == len(symbols)
