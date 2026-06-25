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
