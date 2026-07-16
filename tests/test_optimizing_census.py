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
