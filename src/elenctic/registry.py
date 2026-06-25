"""The solver registry — the single source of truth for valid solver names (spec §4, R5).

A *leaf* module (no intra-package imports) so the contract parser (``expectation``), ``discovery``,
and the facades (``solvers``) all read the valid-name set from one place. Putting it in ``solvers``
would force ``expectation -> solvers -> run -> expectation`` (an import cycle), and duplicating the
set across modules is exactly the drift this consolidates away. The ``Solver`` type and ``SOLVERS``
set are two views of the same vocabulary; ``solvers._FACADES`` must implement exactly ``SOLVERS``
(asserted in ``solvers``). Adding a Potassco theory-solver later = one new name here + one new
facade there. The presence/identity boundary: theory *presence* is derived; solver *identity* is
declared (selected from this registry).
"""

from typing import Final, Literal

type Solver = Literal["clingo", "clingcon"]

SOLVERS: Final[frozenset[str]] = frozenset({"clingo", "clingcon"})

# The registered solvers that interpret theory (`&`) atoms — the v1 conservative set (`clingcon`
# only; `clingo` grounds and silently ignores them, a wrong PASS). The single source for theory
# *capability*, the companion to SOLVERS (the *names*): `provides_theory` reads it so the
# `theory_in_force` sites (discovery's R1/R4 gates, the run-plan derivations in `cli` and `harness`)
# cannot drift. Adding a Potassco theory-solver = one entry here as well.
THEORY_SOLVERS: Final[frozenset[str]] = frozenset({"clingcon"})
assert THEORY_SOLVERS <= SOLVERS, "every theory solver must be a registered solver"


def provides_theory(solver: str) -> bool:
    """Whether ``solver`` interprets theory (``&``) atoms — the v1 ``clingcon``-only predicate
    lifted into the registry (adjudicated 2026-06-22). The presence/identity boundary: theory
    *presence* in a program is derived (and gated), but which solver *provides* a theory is
    declared, so this reads the declared name against ``THEORY_SOLVERS``."""
    return solver in THEORY_SOLVERS
