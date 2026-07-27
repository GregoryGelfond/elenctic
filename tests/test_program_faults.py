"""The program-fault register: a program that cannot be run is not an elenctic bug.

``ProgramError`` says the program under test cannot be run — a fault its author fixes in the
``.lp``. ``HarnessError`` says elenctic violated one of its own invariants — a fault its author
reports. The two are disjoint roots, so neither can be caught as the other, and neither is ever a
verdict about the program's answer-set behaviour.
"""

from elenctic.program import ProgramError
from elenctic.result import HarnessError


def test_a_program_fault_is_not_a_harness_bug() -> None:
    # The subtype relation would be a false claim: a program that will not ground is its author's
    # to fix, not evidence that elenctic is broken.
    assert not issubclass(ProgramError, HarnessError)
    assert not isinstance(ProgramError("cannot ground"), HarnessError)


def test_a_harness_bug_is_not_a_program_fault() -> None:
    # The other direction of the same disjointness.
    assert not issubclass(HarnessError, ProgramError)
    assert not isinstance(HarnessError("seam breach"), ProgramError)
