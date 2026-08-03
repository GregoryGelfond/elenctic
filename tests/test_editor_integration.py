"""What an editor needs in order to show a result where the claim is.

The document exists for a consumer that turns each non-passing check into a diagnostic on the line
that made the claim. These build that mapping over real single-file runs, so a field the mapping
needs cannot go missing without a test saying so — and so that a field being present is checked
against the use it was added for rather than against its own description.

The mapping is written out rather than imported, because there is nothing to import: it is what a
consumer outside this project writes, and the point of the exercise is that it can be written at
all from what the document carries.
"""

from pathlib import Path
from typing import Any

from elenctic.result import Verdict
from support import document_of, run_cli

# What the editor draws for a check it has to draw something for. `pass` is deliberately absent:
# nothing is drawn for it, and its absence is what the filter below relies on. Only one of the
# remaining two is a failure — `undecided` is an absence of knowledge rather than a wrong answer, so
# a consumer that drew it as an error would report a program as broken on the strength of a search
# that ran out of time.
_INDICATOR = {"fail": "error", "undecided": "hint"}


def _reported(case: Path, *flags: str) -> dict[str, Any]:
    return document_of(run_cli(case, "--format", "json", *flags))


def _diagnostics(case: dict[str, Any]) -> list[dict[str, Any]]:
    """Every non-passing check of one case, as an editor would place it."""
    return [
        {
            "uri": case["source"],
            # An editor counts lines from zero; a contract line is written from one. The
            # contract tokenizer records no column, so the range is the whole line.
            "line": check["line"] - 1,
            "severity": _INDICATOR[check["status"]],
            "message": check["message"],
            "source": f"elenctic ({case['solver']})",
        }
        for check in case["checks"]
        if check["status"] != "pass"
    ]


def test_a_single_file_run_yields_a_placeable_diagnostic_per_failing_check(
    tmp_path: Path,
) -> None:
    case = tmp_path / "drinks.lp"
    case.write_text(
        "% @expect sat\n% @cautious { tea }\nbiscuit.\n#show biscuit/0.\n",
        encoding="utf-8",
    )

    (result,) = _reported(case)["cases"]
    diagnostics = _diagnostics(result)

    assert len(diagnostics) == 1
    # The claim is on line 2 of the file; an editor counts lines from zero.
    assert diagnostics[0]["line"] == 1
    assert diagnostics[0]["severity"] == "error"
    assert diagnostics[0]["uri"] == str(case), "the whole path, which is what an editor opens"
    assert "tea" in diagnostics[0]["message"]
    assert diagnostics[0]["source"] == "elenctic (clingo)"


def test_two_claims_written_with_the_same_tag_are_two_diagnostics_on_two_lines(
    tmp_path: Path,
) -> None:
    # The reason a check carries a line at all. A consequence tag may be written more than once, and
    # each writing is an independent claim; a consumer that had only the tag to go on would place
    # both diagnostics in one spot, or collapse them into one and lose the claim that was true.
    #
    # Both claims fail here, so the mapping has to produce two diagnostics rather than one, in the
    # order the document gave them. A single-diagnostic case cannot show either: it is satisfied by
    # a mapping that drops everything after the first.
    case = tmp_path / "twice.lp"
    case.write_text(
        "% @expect sat\n"
        "% @cautious { tea }\n"
        "% @cautious { coffee }\n"
        "biscuit.\n"
        "#show biscuit/0.\n"
        "#show tea/0.\n"
        "#show coffee/0.\n",
        encoding="utf-8",
    )

    (result,) = _reported(case)["cases"]
    diagnostics = _diagnostics(result)

    assert [diagnostic["line"] for diagnostic in diagnostics] == [1, 2], (
        "one diagnostic per failing claim, each on the line that claim was written on"
    )
    assert [diagnostic["severity"] for diagnostic in diagnostics] == ["error", "error"]
    claims = {check["subject"]: check["status"] for check in result["checks"]}
    assert claims["{ tea }"] == "fail"
    assert claims["{ coffee }"] == "fail"
    lines = {check["subject"]: check["line"] for check in result["checks"]}
    assert lines["{ tea }"] == 2
    assert lines["{ coffee }"] == 3


def test_a_check_that_could_not_be_decided_says_why(tmp_path: Path) -> None:
    # The one thing a reader most wants from an undecided result is which kind of not-knowing it
    # was, so that they can tell "raise the budget" from "the solver gave up".
    case = tmp_path / "wide.lp"
    case.write_text(
        "% @expect sat\n% @count 1048576\n{ p(1..20) }.\n#show p/1.\n", encoding="utf-8"
    )

    (result,) = _reported(case, "--budget", "0.05")["cases"]

    by_tag = {check["tag"]: check for check in result["checks"]}
    assert by_tag["@expect sat"]["status"] == "pass", (
        "the search found models, so satisfiability was settled"
    )
    assert by_tag["@count"]["status"] == "undecided"
    assert by_tag["@count"]["conclusion"] == "interrupted"
    assert _diagnostics(result)[0]["severity"] == "hint", (
        "an absence of knowledge is not drawn as a wrong answer"
    )


def test_a_broken_program_is_never_drawn_as_a_failing_contract(tmp_path: Path) -> None:
    # An editor must not put a "this test failed" squiggle on a contract when nothing was tested.
    # A program that cannot be run produced no verdict, so it appears in a different register, and
    # the exit status says which kind of fault it was.
    case = tmp_path / "broken.lp"
    case.write_text('% @expect sat\n% @cautious { a }\n#include "nowhere.lp".\n', encoding="utf-8")

    streams = run_cli(case, "--format", "json")
    document = document_of(streams)

    assert document["cases"] == [], "no verdict was produced, so nothing belongs in that register"
    assert [d for case in document["cases"] for d in _diagnostics(case)] == [], (
        "so the mapping draws nothing at all, which is the claim this test's name makes"
    )
    (error,) = document["errors"]
    assert error["kind"] == "program", "the program under test is broken, not elenctic"
    assert error["is_elenctic_bug"] is False, "and the document says so without it being derived"
    assert error["source"].endswith("broken.lp")
    # The whole run was this one file, so the fault stopped everything rather than one case among
    # others: `scope` says what an error stopped, not what kind of thing it is. The same file met
    # while walking a directory is `case`, because its siblings still produce verdicts. `source`
    # names the file either way, which is what an editor needs in order to place anything at all.
    assert error["scope"] == "corpus"
    assert document["summary"]["total"] == 0
    assert streams.status == 2, "a fault its author can fix, distinct from an elenctic bug at 3"


def test_the_mapping_is_total_over_the_verdicts_it_must_draw() -> None:
    # The consumer model's own soundness. `pass` is drawn as nothing, and every other verdict has to
    # have an indicator — otherwise the vocabulary gaining a member turns into a KeyError inside a
    # consumer's own code, at whatever moment the first such check appears in a real corpus.
    assert set(_INDICATOR) == {verdict.value for verdict in Verdict} - {"pass"}
    assert "error" not in {_INDICATOR["undecided"]}, (
        "an absence of knowledge must not share an indicator with a wrong answer"
    )
