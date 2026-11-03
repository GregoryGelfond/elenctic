"""`elenctic version`, `--version` and `-V`: one text, three spellings."""

from importlib.metadata import metadata
from pathlib import Path

import clingo
import pytest

from elenctic.about import Package, Solvers, VersionExit
from elenctic.cli import main
from elenctic.glyphs import COPYRIGHT
from elenctic.report import Exit
from test_cli import DRINKS, write
from test_cli_output import on_terminals

SPELLINGS = [["version"], ["--version"], ["-V"]]
PLAIN_TEXT = "elenctic 1.2.3 | \u00a9 2026 Gregory Gelfond | MIT\nclingo 5.8.2 | clingcon 5.2.1\n"
NERD_TEXT = PLAIN_TEXT.replace("\u00a9", "\uf1f9")


@pytest.fixture
def fixed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for the metadata and the solvers, so that the text is a golden."""
    monkeypatch.setattr(
        "elenctic.cli.package", lambda: Package("1.2.3", "MIT", "Gregory Gelfond", 2026)
    )
    monkeypatch.setattr("elenctic.cli.loaded_solvers", lambda: Solvers("5.8.2", "5.2.1"))


def shown(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.mark.usefixtures("fixed")
@pytest.mark.parametrize("spelling", SPELLINGS)
def test_the_golden_text_in_the_plain_form(
    capsys: pytest.CaptureFixture[str], spelling: list[str]
) -> None:
    assert shown(capsys, *spelling) == (VersionExit.REPORTED, PLAIN_TEXT, "")


@pytest.mark.usefixtures("fixed")
@pytest.mark.parametrize("spelling", SPELLINGS)
def test_the_golden_text_in_the_nerd_form_with_icons(
    capsys: pytest.CaptureFixture[str], spelling: list[str]
) -> None:
    assert shown(capsys, *spelling, "--icons=always") == (VersionExit.REPORTED, NERD_TEXT, "")


@pytest.mark.usefixtures("fixed")
def test_an_option_may_come_after_the_flag_or_the_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert shown(capsys, "-V", "--icons") == shown(capsys, "version", "--icons=auto")
    assert shown(capsys, "--version", "--color=always") == (VersionExit.REPORTED, PLAIN_TEXT, "")


def test_the_three_spellings_print_identical_bytes(capsys: pytest.CaptureFixture[str]) -> None:
    results = [shown(capsys, *spelling) for spelling in SPELLINGS]
    assert results[0] == results[1] == results[2]
    assert results[0][0] == VersionExit.REPORTED


def test_the_text_is_what_the_metadata_and_the_loaded_solvers_say(
    capsys: pytest.CaptureFixture[str],
) -> None:
    installed = metadata("elenctic")
    _, out, err = shown(capsys, "version")
    first, second = out.splitlines()
    assert first == f"elenctic {installed['Version']} | \u00a9 2026 Gregory Gelfond | MIT"
    assert second.startswith(f"clingo {clingo.__version__} | clingcon ")
    assert out.endswith("\n")
    assert err == ""


@pytest.mark.usefixtures("fixed")
def test_version_is_a_command_and_not_a_file_to_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path, "version", DRINKS + "% @expect sat\n")
    monkeypatch.chdir(tmp_path)
    assert shown(capsys, "version") == (VersionExit.REPORTED, PLAIN_TEXT, "")
    assert shown(capsys, "./version") == (Exit.CLAIMS_HOLD, "1/1 passed\n", "")


@pytest.mark.usefixtures("fixed")
def test_a_path_after_the_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as usage:
        main(["version", "x.lp"])
    assert usage.value.code == Exit.FAULT
    assert "unrecognized arguments: x.lp" in capsys.readouterr().err


@pytest.mark.usefixtures("fixed")
@pytest.mark.parametrize("flag", ["--version", "-V"])
@pytest.mark.parametrize(
    "placement",
    [
        ["--icons", "{}"],
        ["--color", "always", "{}"],
        ["--color=always", "--icons=always", "{}"],
        ["{}", "--icons"],
        ["{}", "--color", "never"],
        ["{}", "test", "x.lp"],
        ["{}", "x.lp"],
        ["--color", "never", "{}", "test", "x.lp", "--json"],
    ],
    ids=str,
)
def test_the_flag_is_a_top_level_option_and_wins_wherever_it_stands_before_a_command(
    capsys: pytest.CaptureFixture[str], flag: str, placement: list[str]
) -> None:
    argv = [flag if part == "{}" else part for part in placement]
    code, out, err = shown(capsys, *argv)
    assert (code, err) == (VersionExit.REPORTED, "")
    assert out in {PLAIN_TEXT, NERD_TEXT}


@pytest.mark.usefixtures("fixed")
@pytest.mark.parametrize("flag", ["--version", "-V"])
@pytest.mark.parametrize(
    "top",
    [[], ["--icons=always"], ["--color", "always"], ["--icons=always", "--color=never"]],
    ids=str,
)
def test_the_flag_prints_the_bytes_of_the_command_with_the_same_options(
    capsys: pytest.CaptureFixture[str], flag: str, top: list[str]
) -> None:
    assert shown(capsys, *top, flag) == shown(capsys, *top, "version")
    assert shown(capsys, flag, *top) == shown(capsys, "version", *top)


@pytest.mark.usefixtures("fixed")
def test_an_option_of_the_command_overrides_the_same_option_before_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert shown(capsys, "--icons=always", "version") == (VersionExit.REPORTED, NERD_TEXT, "")
    assert shown(capsys, "--icons=always", "version", "--icons=never") == (
        VersionExit.REPORTED,
        PLAIN_TEXT,
        "",
    )


@pytest.mark.usefixtures("fixed")
@pytest.mark.parametrize("flag", ["--version", "-V"])
@pytest.mark.parametrize(
    "argv",
    [
        ["test", "{}"],
        ["test", "x.lp", "{}"],
        ["x.lp", "{}"],
        ["version", "{}"],
        ["repl", "{}"],
        ["--color", "never", "test", "{}", "x.lp"],
    ],
    ids=str,
)
def test_a_command_does_not_take_the_flag(
    capsys: pytest.CaptureFixture[str], flag: str, argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as usage:
        main([flag if part == "{}" else part for part in argv])
    assert usage.value.code == Exit.FAULT
    captured = capsys.readouterr()
    assert captured.out == ""
    assert PLAIN_TEXT.splitlines()[0] not in captured.err


@pytest.mark.parametrize("argv", [[], ["--color", "always"], ["--icons"]], ids=str)
def test_options_alone_name_no_command_and_are_a_usage_error(
    capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as usage:
        main(argv)
    assert usage.value.code == Exit.FAULT
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "required: COMMAND" in captured.err


def test_the_help_names_the_command_the_flags_and_the_output_options(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    text = capsys.readouterr().out
    assert "version" in text
    assert "-V, --version" in text
    assert "--color WHEN" in text


def test_on_a_terminal_icons_alone_shows_the_nerd_glyph_and_a_pipe_never_does() -> None:
    code, out, err = on_terminals(["-V", "--icons"], terminal={"out"})
    assert (code, err) == (VersionExit.REPORTED, "")
    assert COPYRIGHT.nerd in out
    assert COPYRIGHT.plain not in out
    code, out, err = on_terminals(["-V", "--icons"], terminal=set())
    assert (code, err) == (VersionExit.REPORTED, "")
    assert COPYRIGHT.plain in out
    assert COPYRIGHT.nerd not in out


def test_on_a_terminal_a_leading_icons_shows_the_glyph_for_the_flag_too() -> None:
    code, out, err = on_terminals(["--icons", "-V"], terminal={"out"})
    assert (code, err) == (VersionExit.REPORTED, "")
    assert COPYRIGHT.nerd in out


def test_the_version_outcome_is_its_own_type_that_states_its_own_code(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reported = main(["version"])
    assert capsys.readouterr().err == ""
    assert type(reported) is VersionExit
    assert reported is VersionExit.REPORTED
    assert int(reported) == 0
    write(tmp_path, "a.lp", DRINKS + "% @expect sat\n")
    monkeypatch.chdir(tmp_path)
    tested = main(["a.lp"])
    assert type(tested) is Exit
    assert tested is Exit.CLAIMS_HOLD


def test_a_failure_of_its_own_while_reporting_the_version_is_the_versions_own_internal_error(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> Package:
        message = "no metadata"
        raise LookupError(message)

    monkeypatch.setattr("elenctic.cli.package", broken)
    code, out, err = shown(capsys, "version")
    assert code is VersionExit.INTERNAL_ERROR
    assert not isinstance(code, Exit)
    assert (int(code), out) == (3, "")
    assert err == "elenctic: internal error: LookupError: no metadata\n"
    assert shown(capsys, "--version") == (code, out, err)


def test_the_codes_are_the_values_of_the_outcomes_and_nothing_else() -> None:
    assert [(m.name, m.value) for m in VersionExit] == [("REPORTED", 0), ("INTERNAL_ERROR", 3)]
    assert [(m.name, m.value) for m in Exit] == [
        ("CLAIMS_HOLD", 0),
        ("CLAIM_UNMET", 1),
        ("FAULT", 2),
        ("INTERNAL_ERROR", 3),
    ]
