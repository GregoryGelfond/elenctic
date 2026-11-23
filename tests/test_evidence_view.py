import re
from dataclasses import replace
from pathlib import Path

import pytest

from elenctic.check import check
from elenctic.determination import AnswerSet, NoAssumptions, NotThese, These, Truncation
from elenctic.evidence_view import explanation_lines, outranked_lines
from elenctic.explanation import (
    Counterexample,
    Explanation,
    Minimality,
    Node,
    Outranked,
    Unexplained,
)
from elenctic.glyphs import Glyphs
from elenctic.human import render_run
from elenctic.legend import EVIDENCE, Mark
from elenctic.literals import Assumption, Literal
from elenctic.paint import Color, Role
from elenctic.presentation import PLAIN, Presentation, Style
from elenctic.program import Program
from elenctic.report import Entry, Run
from elenctic.search import Limit
from elenctic.session import evidenced
from elenctic.verdicts import Ended, Report, Verdict

EXAMPLES = Path(__file__).parent.parent / "docs" / "examples"
COLORED = Presentation(Style(Color.ON, Glyphs.PLAIN), Style(Color.ON, Glyphs.PLAIN))
GLYPHED = Presentation(Style(Color.OFF, Glyphs.NERD), Style(Color.OFF, Glyphs.NERD))
PLAIN_STYLE = Style(Color.OFF, Glyphs.PLAIN)
SEQUENCE = re.compile(r"\x1b\[[0-9;]*m")


def explained_entry(program: Program, max_depth: int | Limit = 3) -> Entry:
    report = check(program)
    assert isinstance(report, Report)
    found = evidenced(report, program, max_depth=max_depth)
    assert isinstance(found, Report)
    return Entry(program.source, found, program.text)


def shown(
    program: Program,
    presentation: Presentation = PLAIN,
    *,
    spans: bool = False,
    max_depth: int | Limit = 3,
) -> str:
    entry = explained_entry(program, max_depth)
    return render_run(Run((entry,)), presentation, spans=spans).stdout


def example(name: str) -> Program:
    return Program.read(EXAMPLES / name)


def test_each_step_shows_its_ground_rule_instance_and_its_line() -> None:
    text = shown(example("absent.lp"))
    assert (
        "  └── access(ann,db) :- role(ann,admin), permits(admin,db), not suspended(ann)."
        "  line 6: blocked by not suspended(ann)\n"
    ) in text
    assert "      suspended(ann) :- flagged(ann), not cleared(ann).  line 5\n" in text
    assert "      flagged(ann)                  fact, line 4\n" in text


def chain(steps: int) -> Program:
    return Program(
        f"p(0).\np(X+1) :- p(X), X < {steps}.\ngoal :- p({steps}).\n"
        "% @expect sat\n% @query no { goal }\n",
        "t.lp",
    )


def tree_of(text: str) -> list[str]:
    """Take the lines of the one tree in `text`, between the margins around it."""
    lines = text.splitlines()
    start = lines.index("  |", lines.index("  |") + 1) + 1
    return lines[start : len(lines) - lines[::-1].index("  |") - 1]


def test_a_chain_of_single_reasons_is_drawn_at_one_indent() -> None:
    lines = tree_of(shown(chain(40), max_depth=Limit.UNBOUNDED))
    assert lines[0].startswith("  goal :- p(40).")
    assert lines[1].startswith("  └── p(40) :- p(39), 39 < 40.")
    assert lines[2].startswith("      p(39) :- p(38), 38 < 40.")
    assert lines[-1].startswith("      p(0)")
    assert len(lines) == 42
    assert all(line.startswith("      p(") for line in lines[2:])


def test_a_long_chain_is_no_wider_than_a_short_one() -> None:
    def widest(steps: int) -> int:
        return max(map(len, tree_of(shown(chain(steps), max_depth=Limit.UNBOUNDED))))

    assert widest(400) <= widest(40) + 4


BRANCHED = "a. b :- a. c :- b. d. x :- c, d.\n% @expect sat\n% @query no { x }\n"
"""A program whose support branches, with a chain under the first branch."""


def test_a_chain_under_a_branch_stays_beside_its_branch() -> None:
    lines = tree_of(shown(Program(BRANCHED, "t.lp")))
    expected = ["x :- c, d.  ", "├── c :- b.  ", "│   b :- a.  ", "│   a  ", "└── d  "]
    assert len(lines) == len(expected)
    assert all(line[2:].startswith(start) for line, start in zip(lines, expected, strict=True))


def test_the_block_names_the_claim_its_place_and_the_counterexample() -> None:
    lines = shown(example("absent.lp")).splitlines()
    at = lines.index("evidence: @cautious { access(ann,db) }")
    assert lines[at + 1 : at + 5] == [
        f" --> {EXAMPLES / 'absent.lp'}:9:3",
        "  |",
        "  = counterexample: answer set 1: { access(bob,wiki) }",
        "  |",
    ]
    assert "  = note: support is sound, not minimal" in lines


def test_spans_add_each_rule_as_written_and_its_substitution() -> None:
    text = shown(example("absent.lp"), spans=True)
    source = EXAMPLES / "absent.lp"
    assert (
        f"          = {source}:6: access(U,R) :- role(U,X), permits(X,R), not suspended(U)."
        " {R=db, U=ann, X=admin}\n"
    ) in text
    assert f"\n          = {source}:4: flagged(ann).\n" in text
    assert f"= {source}:" not in shown(example("absent.lp"))


def test_spans_beside_a_branch_keep_its_guide() -> None:
    lines = tree_of(shown(Program(BRANCHED, "t.lp"), spans=True))
    assert lines[1].startswith("  │   = t.lp:1: x :- c, d.")
    assert lines[3].startswith("  │       = t.lp:1: c :- b.")
    assert lines[5].startswith("  │       = t.lp:1: b :- a.")


def test_a_node_shown_twice_points_back_to_the_first() -> None:
    text = shown(example("chain.lp"))
    assert "  ├── ^ reach(c)                    shown above [1/reach(c)]\n" in text
    assert text.count("reach(c) :- reach(b), open(b,c).") == 1


def test_a_failed_aggregate_says_its_value_and_what_it_needs() -> None:
    text = shown(example("team.lp"))
    assert "aggregate, line 6: is 1, needs = 2" in text
    assert "2 <= { team(ann): cand(ann); … } <= 3.  line 4: not chosen (2 of 2..3 chosen)" in text
    assert "chosen, line 4 (2 of 2..3 chosen)" in text


def test_a_theory_atom_says_the_assignment_it_holds_under() -> None:
    pytest.importorskip("clingcon")
    text = shown(example("late.lp"))
    assert "  = counterexample: answer set 11 of 28: { late } where { s1=1, s2=7 }\n" in text
    assert "  └── &sum { s2 } >= 7              the theory holds under { s2=7 }\n" in text


def test_an_outranked_result_shows_the_costs_and_the_weak_constraints() -> None:
    text = shown(example("laptop.lp"))
    assert "  outranked: the objective ranks it below the optimum\n" in text
    assert "    assuming ram(32)             0         380\n" in text
    assert "    optimum                      0         230  first differs at priority 1\n" in text
    assert "  |                                  ^^^^^^^^^^^^^^^^^^^ +300 at priority 1\n" in text
    assert "  |             ^^^^^^^^^^^^^^^^^^^ -150 at priority 1\n" in text
    assert "  = counterexample: answer set 1: { disk(512), ram(16) }\n" in text


def test_a_branch_cut_at_the_depth_says_so_and_the_note_says_how_to_go_further() -> None:
    program = Program("{ d }. c :- d. b :- c. a :- b.\n% @expect sat\n% @cautious { a }\n", "t.lp")
    text = shown(program, max_depth=1)
    assert (
        "  └── a :- b.                       line 1: blocked by b\n"
        "      ... not b                     not expanded (depth 1); `--max-depth` goes further\n"
        in text
    )
    assert "= note: some branches stop at depth 1; `--max-depth` goes further" in text


def test_icons_mark_each_kind_of_line_and_plain_text_has_none() -> None:
    text = shown(example("absent.lp"), GLYPHED)
    assert f"{EVIDENCE[Mark.ABSENT].nerd} not access(ann,db)" in text
    assert f"{EVIDENCE[Mark.FACT].nerd} flagged(ann)" in text
    assert f"{EVIDENCE[Mark.COUNTEREXAMPLE].nerd} counterexample" in text
    assert all(glyph.nerd not in shown(example("absent.lp")) for glyph in EVIDENCE.values())


def test_color_follows_the_roles_and_stripping_it_leaves_the_plain_text() -> None:
    colored = shown(example("absent.lp"), COLORED)
    assert f"\x1b[{Role.REFERENCE.value}mline 6:\x1b[0m" in colored
    assert f"\x1b[{Role.ERROR.value}mnot suspended(ann)\x1b[0m" in colored
    assert SEQUENCE.sub("", colored) == shown(example("absent.lp"))


def test_substitutions_are_italic_with_spans() -> None:
    colored = shown(example("absent.lp"), COLORED, spans=True)
    assert f"\x1b[{Role.ASIDE.value}m{{R=db, U=ann, X=admin}}\x1b[0m" in colored


@pytest.mark.parametrize(
    ("refutation", "words"),
    [
        (NoAssumptions(), "the program has no answer set, and nothing is assumed"),
        (NotThese(), "the program has no answer set, whatever is assumed"),
        (
            These(frozenset({Assumption(Literal("p"))}), minimal=False),
            (
                "no answer set satisfies the assumptions (p); the search was truncated, "
                "so the core may not be minimal"
            ),
        ),
    ],
)
def test_a_refutation_is_worded_as_one_line(
    refutation: NoAssumptions | NotThese | These, words: str
) -> None:
    entry = explained_entry(Program("p. :- p.\n% @expect sat\n", "t.lp"))
    report = entry.result
    assert isinstance(report, Report)
    findings = tuple(replace(f, evidence=refutation) for f in report.findings)
    text = render_run(Run((replace(entry, result=replace(report, findings=findings)),)), PLAIN)
    assert f"  = refutation: {words}\n" in text.stdout


def test_an_ended_search_is_worded_as_the_test_words_it() -> None:
    entry = explained_entry(Program("{ p }.\n% @expect sat\n% @cautious { p }\n", "t.lp"))
    report = entry.result
    assert isinstance(report, Report)
    findings = tuple(
        replace(f, evidence=Ended(Truncation.INTERRUPTED)) if f.verdict is Verdict.FAIL else f
        for f in report.findings
    )
    text = render_run(Run((replace(entry, result=replace(report, findings=findings)),)), PLAIN)
    assert "  = search ended: interrupted\n" in text.stdout


def test_an_answer_set_the_claim_expects_none_of_says_so() -> None:
    text = shown(Program("p.\n% @expect unsat\n", "t.lp"))
    assert "  the program has this answer set, and the claim expects none\n" in text


def test_text_a_program_writes_is_made_legible() -> None:
    program = Program('p("\x1b[2J").\nq :- r.\n% @expect sat\n% @cautious { q }\n', "t.lp")
    assert "\x1b" not in shown(program)


def test_a_test_run_shows_no_evidence() -> None:
    program = Program("p.\n% @expect sat\n% @cautious { q }\n", "t.lp")
    report = check(program)
    assert isinstance(report, Report)
    text = render_run(Run((Entry("t.lp", report, program.text),)), PLAIN).stdout
    assert "evidence" not in text


def test_a_step_no_reason_covers_names_its_rule_when_there_is_one() -> None:
    program = Program("q(1). r(1). p :- q(X): r(X).\n% @expect sat\n% @query no { p }\n", "t.lp")
    assert "not explained: no reason covers its rule yet, line 1" in shown(program)
    counterexample = Counterexample(AnswerSet(frozenset({Literal("p")}), frozenset()), 1, None)
    alone = Node("1/p", "p", holds=True, reason=Unexplained(None))
    found = Explanation(counterexample, ("1/p",), (alone,), Minimality.NONE, 3, complete=True)
    lines = explanation_lines(found, PLAIN_STYLE, spans=False, own="t.lp")
    assert (
        "  p                                 not explained: no reason covers its rule yet" in lines
    )


def test_a_weak_constraint_whose_source_is_not_at_hand_is_shown_as_written() -> None:
    report = check(example("laptop.lp"))
    assert isinstance(report, Report)
    found = evidenced(report, example("laptop.lp"))
    assert isinstance(found, Report)
    ranked = next(f.evidence for f in found.findings if isinstance(f.evidence, Outranked))
    own = example("laptop.lp").source
    text = "\n".join(
        outranked_lines(ranked, PLAIN_STYLE, lambda _source: None, spans=False, own=own)
    )
    assert "  | 300@1,ram : ram(32) +300 at priority 1" in text
    assert "^" not in text


WEIGHED = "% @expect sat\n% @cautious optimal { a }\n{ a }. :~ a,\n   a. [2@1]\n:~ a. [1@1]"
"""A program whose weak constraints are written over two lines and on the last line."""


def test_a_weak_constraint_on_the_first_line_is_shown_under_its_line() -> None:
    text = shown(Program("{ a }. :~ a. [1@1]\n% @expect sat\n% @cautious optimal { a }\n", "t.lp"))
    assert "1 | { a }. :~ a. [1@1]\n  |        ^^^^^^^^^^^ +1 at priority 1\n" in text


def test_a_weak_constraint_on_the_last_line_or_over_two_is_marked_where_it_starts() -> None:
    text = shown(Program(WEIGHED, "t.lp"))
    assert "5 | :~ a. [1@1]\n  | ^^^^^^^^^^^ +1 at priority 1\n" in text
    assert "3 | { a }. :~ a,\n  |        ^ +2 at priority 1\n" in text


def test_the_marks_and_costs_are_colored_by_which_side_pays_and_where_they_differ() -> None:
    colored = shown(example("laptop.lp"), COLORED)
    assert f"\x1b[{Role.ERROR.value}m{'^' * 19}\x1b[0m +300" in colored
    assert f"\x1b[{Role.NOTE.value}m{'^' * 19}\x1b[0m -150" in colored
    assert f"\x1b[{Role.EMPHASIS.value}m{0:>12}\x1b[0m\x1b[{Role.ERROR.value}m{380:>12}" in colored


def test_a_choice_without_bounds_says_only_how_many_it_chose() -> None:
    program = Program("{ a }.\n% @expect sat\n% @cautious { a }\n", "t.lp")
    assert "line 1: not chosen (0 chosen)" in shown(program)


def test_a_run_rendered_without_asking_for_spans_has_none() -> None:
    entry = explained_entry(example("absent.lp"))
    text = render_run(Run((entry,)), PLAIN).stdout
    assert "line 6: blocked by not suspended(ann)" in text
    assert "access(U,R) :-" not in text


def test_a_choice_bounded_on_one_side_says_the_bound_it_has() -> None:
    program = Program("1 { a; b }.\n% @expect sat\n% @cautious { a, b }\n", "t.lp")
    assert "not chosen (1 of 1.. chosen)" in shown(program)


def test_an_answer_set_is_listed_in_the_order_its_claim_lists_it() -> None:
    program = Program("p(1..10).\n% @expect sat\n% @cautious { p(11) }\n", "t.lp")
    listed = "{ p(1), p(2), p(3), p(4), p(5), p(6), p(7), p(8), p(9), p(10) }"
    text = shown(program)
    assert "= { p(1), p(2)" in text.split("(line 3): ")[1]
    assert f"  = counterexample: answer set 1: {listed}\n" in text


def test_a_rule_instance_a_program_writes_is_made_legible() -> None:
    program = Program(
        'r("\x1b[2J"). s. q :- r("\x1b[2J"), not s.\n% @expect sat\n% @cautious { q }\n', "t.lp"
    )
    text = shown(program)
    assert "\x1b" not in text
    assert 'q :- r("\\x1b[2J"), not s.' in text
