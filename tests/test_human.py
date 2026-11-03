import re

from elenctic.about import Package, Solvers
from elenctic.glyphs import MARKS, Glyphs
from elenctic.human import (
    SEVERITY_ROLES,
    VERDICT_ROLES,
    internal_error,
    render,
    reserved,
    version,
)
from elenctic.paint import Color
from elenctic.presentation import PLAIN, Presentation, Style
from elenctic.report import Run
from elenctic.search import Limits
from elenctic.spans import Severity
from elenctic.verdicts import Verdict
from runs import FAILING, FAULTY, PASSING, PROGRAM_WITH_ESCAPE_CODES, UNDECIDED_COUNT, entry

COLORED = Presentation(Style(Color.ON, Glyphs.PLAIN), Style(Color.ON, Glyphs.PLAIN))
GLYPHED = Presentation(Style(Color.OFF, Glyphs.NERD), Style(Color.OFF, Glyphs.NERD))
SEQUENCE = re.compile(r"\x1b\[[0-9;]*m")
FAILED_CLAIM = "  [FAIL] @cautious { q } (line 3): { q } ⊆ ⋂ AS(P) = { p } (missing: { q })"


def test_a_run_of_passing_sources_says_so_on_stdout() -> None:
    rendered = render(Run((entry(PASSING, "a.lp"),)), PLAIN)
    assert (rendered.stdout, rendered.stderr) == ("1/1 passed\n", "")


def test_a_failing_claim_is_named_with_its_line_and_what_was_found() -> None:
    rendered = render(Run((entry(PASSING, "a.lp"), entry(FAILING, "b.lp"))), PLAIN)
    assert rendered.stdout.splitlines() == [
        "b.lp — FAIL",
        FAILED_CLAIM,
        "",
        "1/2 passed, 1 fail",
    ]
    assert rendered.stderr == ""


def test_an_undecided_claim_is_counted_apart() -> None:
    run = Run((entry(UNDECIDED_COUNT, "u.lp", Limits(models=1)),))
    stdout = render(run, PLAIN).stdout
    assert "  [UNDECIDED] @count 4 (line 4)" in stdout
    assert stdout.endswith("0/1 passed, 1 undecided\n")


def test_a_fault_is_a_diagnostic_on_stderr_and_a_count_on_stdout() -> None:
    rendered = render(Run((entry(PASSING, "a.lp"), entry(FAULTY, "c.lp"))), PLAIN)
    assert rendered.stdout == "1/2 passed, 1 error\n"
    assert rendered.stderr.startswith("c.lp:2:")
    assert ": error: " in rendered.stderr
    assert rendered.stderr.endswith("\n")


def test_verbose_lists_the_claims_that_passed() -> None:
    run = Run((entry(PASSING, "a.lp"),))
    assert "  [PASS] @expect sat" in render(run, PLAIN, verbose=True).stdout
    assert "[PASS]" not in render(run, PLAIN).stdout


def test_verbose_lists_a_passed_claim_beside_the_failed_one_only_when_asked() -> None:
    run = Run((entry(FAILING, "b.lp"),))
    assert "[PASS]" not in render(run, PLAIN).stdout
    assert "  [PASS] @expect sat" in render(run, PLAIN, verbose=True).stdout


def test_every_verdict_and_severity_has_a_role() -> None:
    assert set(VERDICT_ROLES) == set(Verdict)
    assert set(SEVERITY_ROLES) == set(Severity)


def test_with_colour_on_each_piece_is_painted_by_its_role() -> None:
    rendered = render(Run((entry(PASSING, "a.lp"), entry(FAILING, "b.lp"))), COLORED)
    assert rendered.stdout == (
        "\x1b[1mb.lp\x1b[0m — \x1b[1;31mFAIL\x1b[0m\n"
        "  \x1b[1;31m[FAIL]\x1b[0m @cautious { q } \x1b[1;34m(line 3)\x1b[0m: "
        "{ q } ⊆ ⋂ AS(P) = { p } (missing: { q })\n"
        "\n"
        "\x1b[1m1/2 passed\x1b[0m, \x1b[1;31m1 fail\x1b[0m\n"
    )


def test_a_passed_claim_is_a_note_and_an_undecided_one_a_warning() -> None:
    passed = render(Run((entry(PASSING, "a.lp"),)), COLORED, verbose=True).stdout
    assert "\x1b[1;32m[PASS]\x1b[0m" in passed
    run = Run((entry(UNDECIDED_COUNT, "u.lp", Limits(models=1)),))
    undecided = render(run, COLORED).stdout
    assert "\x1b[1;33m[UNDECIDED]\x1b[0m" in undecided
    assert undecided.endswith("\x1b[1;33m1 undecided\x1b[0m\n")


def test_a_fault_is_painted_on_stderr_by_the_style_of_stderr() -> None:
    presentation = Presentation(PLAIN.stdout, COLORED.stderr)
    rendered = render(Run((entry(FAULTY, "c.lp"),)), presentation)
    assert rendered.stdout == "0/1 passed, 1 error\n"
    assert rendered.stderr.startswith("\x1b[1mc.lp:2:")
    assert "\x1b[0m: \x1b[1;31merror\x1b[0m: " in rendered.stderr
    presentation = Presentation(COLORED.stdout, PLAIN.stderr)
    rendered = render(Run((entry(FAULTY, "c.lp"),)), presentation)
    assert rendered.stdout == "\x1b[1m0/1 passed\x1b[0m, \x1b[1;31m1 error\x1b[0m\n"
    assert "\x1b" not in rendered.stderr


def test_with_glyphs_on_a_verdict_is_marked_by_its_glyph_not_its_bracketed_name() -> None:
    run = Run((entry(PASSING, "a.lp"), entry(FAILING, "b.lp")))
    stdout = render(run, GLYPHED, verbose=True).stdout
    assert f"  {MARKS[Verdict.FAIL].nerd} @cautious {{ q }} (line 3)" in stdout
    assert f"  {MARKS[Verdict.PASS].nerd} @expect sat (line 2)" in stdout
    assert "[FAIL]" not in stdout
    assert "b.lp — FAIL" in stdout


def test_the_existing_symbols_stay_with_glyphs_on() -> None:
    stdout = render(Run((entry(FAILING, "b.lp"),)), GLYPHED).stdout
    assert " — " in stdout
    assert "⊆ ⋂" in stdout


def test_glyphs_and_colour_are_independent_and_both_survive() -> None:
    both = Presentation(Style(Color.ON, Glyphs.NERD), PLAIN.stderr)
    stdout = render(Run((entry(FAILING, "b.lp"),)), both).stdout
    assert f"\x1b[1;31m{MARKS[Verdict.FAIL].nerd}\x1b[0m" in stdout


def test_text_from_a_program_cannot_steer_the_terminal() -> None:
    stdout = render(Run((entry(PROGRAM_WITH_ESCAPE_CODES, "a\x1b[2J.lp"),)), PLAIN).stdout
    assert all(each.isprintable() or each == "\n" for each in stdout)
    assert r'p("\x1b[2J\x1b[31mRED\r")' in stdout
    assert stdout.startswith("a\\x1b[2J.lp — FAIL\n")


def test_a_diagnostic_is_as_legible_as_a_verdict() -> None:
    run = Run((entry('p :- "\x1b[2J\x07". q(.\n% @expect sat\n', "c.lp"),))
    stderr = render(run, PLAIN).stderr
    assert stderr.startswith("c.lp:1:")
    assert "\x1b" not in stderr
    assert "\x07" not in stderr


def test_text_is_made_legible_before_it_is_painted() -> None:
    run = Run((entry(PROGRAM_WITH_ESCAPE_CODES, "a\x1b[2J.lp"),))
    stdout = render(run, COLORED).stdout
    assert stdout.startswith("\x1b[1ma\\x1b[2J.lp\x1b[0m — ")
    assert r'p("\x1b[2J\x1b[31mRED\r")' in stdout
    assert stdout.count("\x1b") == len(SEQUENCE.findall(stdout))
    assert all(each.isprintable() or each in "\n\x1b" for each in stdout)


def test_a_diagnostic_is_made_legible_before_it_is_painted() -> None:
    run = Run((entry('p :- "\x1b[2J\x07". q(.\n% @expect sat\n', "c\x1b[2J.lp"),))
    stderr = render(run, COLORED).stderr
    assert stderr.startswith("\x1b[1mc\\x1b[2J.lp:1:")
    assert stderr.count("\x1b") == len(SEQUENCE.findall(stderr))
    assert "\x07" not in stderr


def test_a_glyph_is_added_after_legible_so_it_is_not_escaped() -> None:
    run = Run((entry(PROGRAM_WITH_ESCAPE_CODES, "a\x1b[2J.lp"),))
    stdout = render(run, GLYPHED).stdout
    assert MARKS[Verdict.FAIL].nerd in stdout
    assert "\\uf057" not in stdout


def test_the_reserved_note_is_help_and_plain_without_colour() -> None:
    assert reserved("why", PLAIN.stderr) == "elenctic: `why` is reserved and not yet built"
    assert reserved("why", COLORED.stderr) == (
        "\x1b[1;36melenctic: `why` is reserved and not yet built\x1b[0m"
    )


def test_the_internal_error_is_one_legible_line_painted_as_an_error() -> None:
    error = RecursionError("no \x1b[2J")
    assert (
        internal_error(error, PLAIN.stderr)
        == "elenctic: internal error: RecursionError: no \\x1b[2J"
    )
    assert internal_error(error, COLORED.stderr) == (
        "\x1b[1;31melenctic: internal error: RecursionError: no \\x1b[2J\x1b[0m"
    )


PACKAGE = Package("1.2.3", "MIT", "Gregory Gelfond", 2026)
SOLVERS = Solvers("5.8.2", "5.2.1")
NOT_INSTALLED = Solvers("5.8.2", None)


def test_the_version_text_is_two_lines_with_the_plain_copyright_sign() -> None:
    assert version(PACKAGE, SOLVERS, PLAIN.stdout) == (
        "elenctic 1.2.3 | \u00a9 2026 Gregory Gelfond | MIT\nclingo 5.8.2 | clingcon 5.2.1\n"
    )


def test_the_version_text_has_the_nerd_copyright_glyph_with_icons() -> None:
    assert version(PACKAGE, SOLVERS, GLYPHED.stdout) == (
        "elenctic 1.2.3 | \uf1f9 2026 Gregory Gelfond | MIT\nclingo 5.8.2 | clingcon 5.2.1\n"
    )


def test_a_clingcon_that_is_not_installed_is_said_so() -> None:
    assert version(PACKAGE, NOT_INSTALLED, PLAIN.stdout).splitlines()[1] == (
        "clingo 5.8.2 | clingcon not installed"
    )


def test_the_version_text_is_never_coloured() -> None:
    assert version(PACKAGE, SOLVERS, COLORED.stdout) == version(PACKAGE, SOLVERS, PLAIN.stdout)


def test_what_the_metadata_says_is_made_legible_and_the_glyph_is_not() -> None:
    hostile = Package("1\x1b[2J", "MIT\x07", "G\x1b]0;x", 2026)
    text = version(hostile, Solvers("5\x1b", "5\x1b"), GLYPHED.stdout)
    assert text.splitlines() == [
        "elenctic 1\\x1b[2J | \uf1f9 2026 G\\x1b]0;x | MIT\\x07",
        "clingo 5\\x1b | clingcon 5\\x1b",
    ]
