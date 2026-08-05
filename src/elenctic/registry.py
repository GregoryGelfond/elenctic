"""The solver registry — the single source of truth for valid solver names.

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

__all__ = ["BACKING_MODULES", "SOLVERS", "THEORY_SOLVERS", "Solver", "provides_theory"]

type Solver = Literal["clingo", "clingcon"]

SOLVERS: Final[frozenset[str]] = frozenset({"clingo", "clingcon"})

# The registered solvers that interpret theory (`&`) atoms — the v1 conservative set (`clingcon`
# only; `clingo` grounds and silently ignores them, a wrong PASS). The single source for theory
# *capability*, the companion to SOLVERS (the *names*): `provides_theory` reads it so the
# `theory_in_force` sites (discovery's theory gates, the run-plan derivations in `cli`/`harness`)
# cannot drift. Adding a Potassco theory-solver = one entry here as well.
THEORY_SOLVERS: Final[frozenset[str]] = frozenset({"clingcon"})
if not THEORY_SOLVERS <= SOLVERS:  # raised, not asserted, so it survives `python -O`
    raise AssertionError("every theory solver must be a registered solver")

# The Python module each registered solver is provided by — what has to be importable for a case to
# run under it. clingo is a hard dependency; a theory solver may be an optional extra, so discovery
# checks that a declared solver is actually present before a run reaches its facade. Adding a
# Potassco theory-solver = one entry here as well.
BACKING_MODULES: Final[dict[str, str]] = {"clingo": "clingo", "clingcon": "clingcon"}
if frozenset(BACKING_MODULES) != SOLVERS:  # raised, not asserted, so it survives `python -O`
    raise AssertionError("every registered solver names a backing module")


def provides_theory(solver: str) -> bool:
    """Whether ``solver`` interprets theory (``&``) atoms — the v1 ``clingcon``-only predicate
    lifted into the registry. The presence/identity boundary: theory
    *presence* in a program is derived (and gated), but which solver *provides* a theory is
    declared, so this reads the declared name against ``THEORY_SOLVERS``."""
    return solver in THEORY_SOLVERS
