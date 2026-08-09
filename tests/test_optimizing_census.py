"""The AS(P) modes mean AS(P) even when the encoding carries an objective.

clingo applies ``--opt-mode=opt`` by default, so on a program with a ``#minimize``/``#maximize``/
``:~`` an enumerating solve reports only the branch-and-bound *improving sequence* — the models the
search passed through on its way to the optimum. That sequence is neither AS(P) nor Opt(P) and it
shifts with the search heuristic. Every mode whose reading ranges over AS(P) must therefore switch
the objective off, or its tags quietly answer a question nobody asked.

Each program below is stated with its AS(P) worked out by hand, and each case pins the verdict the
*semantics* demands — not the verdict a particular clingo search order happens to produce. An
objective ranks answer sets; it never removes any, so ``@count``, ``@model``, ``@cautious``,
``@brave`` and ``@query`` must read exactly as they would with the objective deleted.

The last section is the other side of the same coin, and it is here because it is the case where
``Opt(P)`` could mean two things: what the *optimal*-base tags read when the encoding carries a
**theory** objective as well as an ASP one. They read the optimum the solver proves, which accounts
for both — pinned by cases whose two readings disagree, so a change of mind cannot pass quietly.
"""

from pathlib import Path

from elenctic.discovery import Case, discover
from elenctic.harness import case_verdict, run_case
from elenctic.result import Verdict

# AS(P) = three answer sets, one per chosen value; Opt(P) = { chosen(1) } alone (cost 1).
# The objective ranks them 1 < 2 < 3 but removes none, so |AS(P)| = 3 whatever the search does.
_LADDER = "value(1..3).\n1 { chosen(V) : value(V) } 1.\n#minimize { V : chosen(V) }.\n"

# The same ladder with a flag the *skipped* models carry. `flag` holds in the chosen(2) and
# chosen(3) answer sets and not in chosen(1), so:
#   ⋂ AS(P) = { value(1), value(2), value(3) }   -- chosen(1) is NOT a cautious consequence
#   ⋃ AS(P) = every chosen(V), plus flag
_LADDER_FLAG = (
    "value(1..3).\n"
    "1 { chosen(V) : value(V) } 1.\n"
    "flag :- chosen(2).\n"
    "flag :- chosen(3).\n"
    "#minimize { V : chosen(V) }.\n"
)


def case_of(tmp_path: Path, contract: str, program: str) -> Case:
    """Discover a single self-contained case: the contract comment lines plus the encoding."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "case.lp"
    path.write_text(contract + program)
    (case,) = discover(path)
    return case


def verdict_of(tmp_path: Path, contract: str, program: str) -> Verdict:
    case = case_of(tmp_path, contract, program)
    return case_verdict(run_case(case))


# --- ENUM_ALL: the census tags count AS(P), not the improving sequence ---


def test_count_counts_every_answer_set_of_an_optimizing_program(tmp_path: Path) -> None:
    # |AS(P)| = 3. Under an active objective the improving sequence is shorter, so a search-order
    # artefact reports a smaller number for a claim that is simply true.
    assert verdict_of(tmp_path, "% @expect sat\n% @count 3\n", _LADDER) is Verdict.PASS


def test_model_accepts_an_answer_set_the_improving_sequence_skips(tmp_path: Path) -> None:
    # chosen(2) is a genuine answer set, but it is neither the first model found nor the optimum,
    # so an objective-pruned enumeration can step straight over it. Rejecting it tells the user a
    # correct encoding is broken.
    contract = "% @expect sat\n% @model { chosen(2), value(1), value(2), value(3) }\n"
    assert verdict_of(tmp_path, contract, _LADDER) is Verdict.PASS


# --- CAUTIOUS_ALL: ⋂ over AS(P), so a non-consequence is rejected ---


def test_cautious_rejects_an_atom_that_is_not_in_every_answer_set(tmp_path: Path) -> None:
    # chosen(1) holds in exactly one of the three answer sets, so `@cautious { chosen(1) }` is
    # false. An objective-pruned ⋂ is computed over too few models and so comes back too *large* —
    # which certifies the false claim rather than rejecting it.
    contract = "% @expect sat\n% @cautious { chosen(1) }\n"
    assert verdict_of(tmp_path, contract, _LADDER_FLAG) is Verdict.FAIL


def test_cautious_accepts_a_genuine_consequence_of_an_optimizing_program(tmp_path: Path) -> None:
    # value(1) is a fact, hence in every answer set: true under any search order. Pins the fix to
    # rejecting *false* claims only, rather than failing cautious across the board.
    contract = "% @expect sat\n% @cautious { value(1) }\n"
    assert verdict_of(tmp_path, contract, _LADDER_FLAG) is Verdict.PASS


# --- BRAVE_ALL: ⋃ over AS(P), so every answer set's atoms are reachable ---


def test_brave_accepts_an_atom_of_an_answer_set_the_search_skips(tmp_path: Path) -> None:
    # chosen(2) is in ⋃ AS(P) because the chosen(2) answer set exists. An objective-pruned ⋃ is
    # accumulated over too few models and so comes back too *small*, denying a real answer set.
    contract = "% @expect sat\n% @brave { chosen(2) }\n"
    assert verdict_of(tmp_path, contract, _LADDER_FLAG) is Verdict.PASS


def test_brave_rejects_an_atom_no_answer_set_carries(tmp_path: Path) -> None:
    # chosen(4) is outside the value range, so it is in no answer set at all.
    contract = "% @expect sat\n% @brave { chosen(4) }\n"
    assert verdict_of(tmp_path, contract, _LADDER_FLAG) is Verdict.FAIL


# --- @query: the three-valued answer reads the same consequence sets ---


def test_query_does_not_entail_an_atom_that_only_some_answer_sets_carry(tmp_path: Path) -> None:
    # chosen(1) holds in one of three answer sets: the program's answer is `unknown`, not `yes`.
    # @query rides ⋂ here, so an objective-pruned ⋂ makes a `yes` claim pass — the framework
    # answering a question the program does not.
    contract = "% @expect sat\n% @query yes { chosen(1) }\n"
    assert verdict_of(tmp_path, contract, _LADDER_FLAG) is Verdict.FAIL


def test_conjunctive_query_reads_the_full_census_of_an_optimizing_program(tmp_path: Path) -> None:
    # A conjunctive ground query rides the census rather than ⋂. value(1), value(2) are facts, so
    # the program entails the conjunction: `yes` under any search order.
    contract = "% @expect sat\n% @query yes { value(1), value(2) }\n"
    assert verdict_of(tmp_path, contract, _LADDER_FLAG) is Verdict.PASS


# --- the objective is a ranking, not a filter: every reading is invariant under deleting it ---


def test_as_p_readings_are_invariant_under_deleting_the_objective(tmp_path: Path) -> None:
    # The load-bearing semantic fact, stated directly: #minimize ranks answer sets without removing
    # any, so every AS(P) tag reads identically with and without it. This is the invariant the
    # per-tag cases above each witness at one point.
    contract = "% @expect sat\n% @count 3\n% @cautious { value(1) }\n% @brave { chosen(2) }\n"
    without = _LADDER_FLAG.replace("#minimize { V : chosen(V) }.\n", "")
    assert verdict_of(tmp_path / "with", contract, _LADDER_FLAG) is Verdict.PASS
    assert verdict_of(tmp_path / "without", contract, without) is Verdict.PASS


# --- Opt(P) under a THEORY objective: the optimum the solver proves, and all four tags agree ---

# Both answer sets cost 0 under the ASP objective, so an ASP-only reading of Opt(P) would hold two
# members and neither `p(1)` nor `p(2)` would be a consequence of it. The theory objective breaks
# the tie: `p(2)` forces x >= 5, so minimizing x proves the `p(1)` answer set optimal and the other
# not. What elenctic reports is that optimum.
#
# This is pinned rather than left to be rediscovered, because it is the one place `Opt(P)` could
# mean two things and the difference is invisible in the verdict. It reads the solver's proven
# optimum, and for a program that declares `&minimize` that objective is part of the program — the
# optimum of the program includes it, so an "ASP-optimal class" that ignores a declared objective is
# the optimum of a different program. Every optimal-base tag agrees with every other on which set
# that is, which is what makes the reading coherent rather than merely defensible; a change of mind
# here has to break these three together, not one quietly.
_THEORY_TIEBREAK = (
    "1 { p(1); p(2) } 1.\n"
    "&sum { x } >= 1.\n"
    "&sum { x } <= 9.\n"
    "&sum { x } >= 5 :- p(2).\n"
    "&minimize { x }.\n"
    "#minimize{ 0 : p(2) }.\n"
    "#show p/1.\n"
)
_THEORY = "% @elenctic solver clingcon\n% @expect sat\n"


def test_the_optimal_base_reads_the_optimum_the_solver_proves(tmp_path: Path) -> None:
    # One optimal answer set, not the two an ASP-only reading of the objective would count.
    assert verdict_of(tmp_path, f"{_THEORY}% @count optimal 1\n", _THEORY_TIEBREAK) is Verdict.PASS


def test_an_optimal_consequence_reads_that_same_optimum(tmp_path: Path) -> None:
    # `p(1)` holds in every member of that optimum, so it is an optimal cautious consequence. Under
    # an ASP-only reading the optimum would hold both answer sets and this would be false.
    assert (
        verdict_of(tmp_path, f"{_THEORY}% @cautious optimal {{ p(1) }}\n", _THEORY_TIEBREAK)
        is Verdict.PASS
    )


def test_the_cost_reported_beside_it_is_the_asp_cost_of_that_optimum(tmp_path: Path) -> None:
    # The half that makes the reading coherent instead of two readings in one contract: `@cost`
    # states the ASP cost vector OF the set the tags above range over, which is 0 here.
    assert verdict_of(tmp_path, f"{_THEORY}% @cost {{ 0 }}\n", _THEORY_TIEBREAK) is Verdict.PASS


def test_the_asp_only_reading_of_that_optimum_is_refuted_not_merely_unasserted(
    tmp_path: Path,
) -> None:
    """The three above pass; this is what establishes they are measuring the distinction.

    An ASP-only reading of `Opt(P)` — the objective's optimal class with the theory objective
    ignored — holds BOTH answer sets, so it would count two and would not carry `p(1)`. Both claims
    are stated here and both must FAIL. Without this, the three guards above pass just as well
    against a build that had quietly adopted the other reading and happened to agree on the cases
    they assert.
    """
    assert verdict_of(tmp_path, f"{_THEORY}% @count optimal 2\n", _THEORY_TIEBREAK) is Verdict.FAIL
    assert (
        verdict_of(tmp_path, f"{_THEORY}% @cautious optimal {{ p(2) }}\n", _THEORY_TIEBREAK)
        is Verdict.FAIL
    )
