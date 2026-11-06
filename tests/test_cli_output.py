"""How the command line writes: color, glyphs and streams, as the controller resolves them."""

import json
import os
import select
import sys
from pathlib import Path

import pytest

from elenctic.cli import main
from elenctic.glyphs import MARKS
from elenctic.report import Exit
from elenctic.verdicts import Verdict
from test_cli import DRINKS, write

FAIL_NERD = MARKS[Verdict.FAIL].nerd
UNMET = DRINKS + "% @expect sat\n% @cautious { tea }\n"


class Written:
    def __init__(self, code: int, out: str, err: str) -> None:
        self.code, self.out, self.err = code, out, err


def written(capsys: pytest.CaptureFixture[str], *argv: object) -> Written:
    code = main([str(a) for a in argv])
    captured = capsys.readouterr()
    return Written(code, captured.out, captured.err)


@pytest.fixture
def unmet(tmp_path: Path) -> Path:
    """Write a program with one claim that fails."""
    return write(tmp_path, "drinks.lp", UNMET)


@pytest.fixture
def missing(tmp_path: Path) -> Path:
    """Name a path that holds no file, so a fault."""
    return tmp_path / "absent.lp"


def test_by_default_a_redirected_stream_is_plain(unmet: Path, missing: Path) -> None:
    code, out, err = on_terminals([str(unmet), str(missing)], terminal=set())
    assert code == Exit.FAULT
    assert "\x1b" not in out + err
    assert "[FAIL]" in out
    assert "cannot read" in err
    assert "absent.lp" in err


def test_always_colors_both_streams_by_their_roles(
    capsys: pytest.CaptureFixture[str], unmet: Path, missing: Path
) -> None:
    shown = written(capsys, "--color", "always", unmet, missing)
    assert shown.code == Exit.FAULT
    assert "\x1b[1;31m[FAIL]\x1b[0m" in shown.out
    assert shown.out.endswith(
        "\x1b[1m0/2 passed\x1b[0m, \x1b[1;31m1 fail\x1b[0m, \x1b[1;31m1 error\x1b[0m\n"
    )
    assert "\x1b[1;31merror\x1b[0m: " in shown.err
    assert "cannot read" in shown.err


# (environment, arguments) -> colored? Every stream here is redirected, so only an explicit
# choice can color: the environment never does.
COLORED_BY = [
    (({}, []), False),
    (({"CLICOLOR_FORCE": "1"}, []), False),
    (({"CLICOLOR_FORCE": "1", "NO_COLOR": ""}, []), False),
    (({"CLICOLOR_FORCE": "1", "TERM": "xterm"}, []), False),
    (({"CLICOLOR_FORCE": "1"}, ["--color", "auto"]), False),
    (({"FORCE_COLOR": "1"}, []), False),
    (({"CLICOLOR": "1"}, []), False),
    (({"TERM": "xterm"}, []), False),
    (({}, ["--color", "always"]), True),
    (({"NO_COLOR": "1"}, ["--color", "always"]), True),
    (({"TERM": "dumb"}, ["--color", "always"]), True),
    (({"CLICOLOR_FORCE": "1", "NO_COLOR": "1"}, ["--color=never"]), False),
    (({"CLICOLOR_FORCE": "1"}, ["--color=never"]), False),
]


@pytest.mark.parametrize(("setting", "colored"), COLORED_BY)
def test_a_redirected_stream_is_colored_only_by_an_explicit_choice(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    unmet: Path,
    setting: tuple[dict[str, str], list[str]],
    colored: bool,
) -> None:
    environment, arguments = setting
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    shown = written(capsys, *arguments, unmet, unmet.with_name("absent.lp"))
    assert ("\x1b[" in shown.out, "\x1b[" in shown.err) == (colored, colored)


def test_a_bad_choice_is_a_usage_error(capsys: pytest.CaptureFixture[str], unmet: Path) -> None:
    with pytest.raises(SystemExit) as usage:
        main(["--color", "sometimes", str(unmet)])
    assert usage.value.code == Exit.FAULT
    err = capsys.readouterr().err
    assert err.startswith("usage: elenctic ")
    assert "invalid choice: 'sometimes'" in err


def test_no_glyph_without_icons(capsys: pytest.CaptureFixture[str], unmet: Path) -> None:
    shown = written(capsys, unmet)
    assert "[FAIL]" in shown.out
    assert FAIL_NERD not in shown.out


@pytest.mark.parametrize(
    ("icons", "glyphed"),
    [
        (["--icons=always"], True),
        (["--icons=never"], False),
        (["--icons=auto"], False),
        (["--icons"], False),
        (["--ic"], False),
        (["--icons", "--icons=always"], True),
    ],
)
def test_icons_take_a_value_only_with_an_equals_sign_and_bare_means_auto(
    capsys: pytest.CaptureFixture[str],
    unmet: Path,
    icons: list[str],
    glyphed: bool,
) -> None:
    shown = written(capsys, *icons, unmet)
    assert shown.code == Exit.CLAIM_UNMET
    assert (FAIL_NERD in shown.out, "[FAIL]" in shown.out) == (glyphed, not glyphed)


def test_a_bare_icons_does_not_take_the_next_path_as_its_value(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    always = write(tmp_path, "always", DRINKS + "% @expect sat\n")
    shown = written(capsys, "--icons", always)
    assert (shown.code, shown.out) == (Exit.CLAIMS_HOLD, "1/1 passed\n")


def test_a_value_after_a_space_is_a_path(capsys: pytest.CaptureFixture[str], unmet: Path) -> None:
    shown = written(capsys, "--icons", "always", unmet)
    assert shown.code == Exit.FAULT
    assert "cannot read `always`" in shown.err


def test_after_the_double_dash_icons_is_a_path(capsys: pytest.CaptureFixture[str]) -> None:
    shown = written(capsys, "test", "--", "--icons")
    assert shown.code == Exit.FAULT
    assert "cannot read `--icons`" in shown.err


def test_a_bad_icons_value_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], unmet: Path
) -> None:
    with pytest.raises(SystemExit) as usage:
        main(["--icons=sometimes", str(unmet)])
    assert usage.value.code == Exit.FAULT
    assert "invalid choice: 'sometimes'" in capsys.readouterr().err


def test_icons_and_color_are_independent(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, unmet: Path
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    glyphed = written(capsys, "--icons=always", unmet)
    assert FAIL_NERD in glyphed.out
    assert "\x1b" not in glyphed.out
    monkeypatch.delenv("NO_COLOR")
    colored = written(capsys, "--color=always", unmet)
    assert "\x1b[1;31m[FAIL]\x1b[0m" in colored.out
    assert FAIL_NERD not in colored.out


def test_icons_and_color_apply_to_every_command(capsys: pytest.CaptureFixture[str]) -> None:
    shown = written(capsys, "why", "--color=always", "--icons=always", "x.lp")
    assert shown.code == Exit.FAULT
    assert shown.out == ""
    assert shown.err == "\x1b[1;36melenctic: `why` is reserved and not yet built\x1b[0m\n"


def test_verdicts_and_summary_are_on_stdout_and_diagnostics_on_stderr(
    capsys: pytest.CaptureFixture[str], unmet: Path, missing: Path
) -> None:
    shown = written(capsys, unmet, missing)
    assert shown.out.splitlines()[0] == f"{unmet} — FAIL"
    assert shown.out.splitlines()[-1] == "0/2 passed, 1 fail, 1 error"
    assert "absent.lp" not in shown.out
    assert shown.err.startswith("error: cannot read")
    assert "absent.lp" in shown.err


def test_json_keeps_the_whole_document_on_stdout_and_never_colors_it(
    capsys: pytest.CaptureFixture[str], unmet: Path, missing: Path
) -> None:
    shown = written(capsys, "--json", "--color=always", "--icons=always", unmet, missing)
    assert shown.code == Exit.FAULT
    assert shown.err == ""
    assert "\x1b" not in shown.out
    assert FAIL_NERD not in shown.out
    document = json.loads(shown.out)
    assert document["exit_code"] == Exit.FAULT
    results = [entry["result"]["kind"] for entry in document["run"]["entries"]]
    assert results == ["report", "fault"]


def test_an_internal_error_is_painted_by_the_style_of_stderr(
    capsys: pytest.CaptureFixture[str], unmet: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object, **__: object) -> None:
        message = "no \x1b[2J"
        raise RecursionError(message)

    monkeypatch.setattr("elenctic.cli.check", broken)
    shown = written(capsys, "--color=always", unmet)
    assert shown.code == Exit.INTERNAL_ERROR
    assert shown.out == ""
    assert shown.err == ("\x1b[1;31melenctic: internal error: RecursionError: no \\x1b[2J\x1b[0m\n")


def test_the_help_names_the_output_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["test", "--help"])
    text = capsys.readouterr().out
    assert "--color WHEN" in text
    assert "--icons [WHEN]" in text
    assert "--icons=WHEN" in text


def on_terminals(
    argv: list[str], *, terminal: set[str], environment: dict[str, str] | None = None
) -> tuple[int, str, str]:
    """Run the command line with the named streams (`out`, `err`) on a pseudo-terminal."""
    return spawned(
        [sys.executable, "-m", "elenctic.cli", *argv], terminal=terminal, environment=environment
    )


def _read_ready(chunks: dict[int, list[bytes]], timeout: float) -> bool:
    """Read what each descriptor holds within `timeout` seconds; whether any held something."""
    ready = select.select(list(chunks), [], [], timeout)[0]
    for read_end in ready:
        chunks[read_end].append(os.read(read_end, 65536))
    return bool(ready)


def spawned(
    command: list[str], *, terminal: set[str], environment: dict[str, str] | None = None
) -> tuple[int, str, str]:
    """Run a command with the named streams on a pseudo-terminal: its exit code, out and err.

    Output is read while the command runs, or a full terminal would stop it, and the write ends
    stay open until it is read, because closing the last one discards what a terminal holds on
    macOS (Linux keeps it).
    """
    reads: dict[str, int] = {}
    writes: dict[str, int] = {}
    for name in ("out", "err"):
        reads[name], writes[name] = os.openpty() if name in terminal else os.pipe()
    env = {"PATH": os.environ["PATH"], "TERM": "xterm-256color", **(environment or {})}
    pid = os.posix_spawn(
        command[0],
        command,
        env,
        file_actions=[
            (os.POSIX_SPAWN_DUP2, writes["out"], 1),
            (os.POSIX_SPAWN_DUP2, writes["err"], 2),
        ],
    )
    chunks: dict[int, list[bytes]] = {read_end: [] for read_end in reads.values()}
    done, status = 0, 0
    while not done:
        _read_ready(chunks, 0.05)
        done, status = os.waitpid(pid, os.WNOHANG)
    while _read_ready(chunks, 0):
        pass
    for end in (*reads.values(), *writes.values()):
        os.close(end)
    out, err = (
        b"".join(chunks[reads[name]]).decode().replace("\r\n", "\n") for name in ("out", "err")
    )
    return os.waitstatus_to_exitcode(status), out, err


def test_a_terminal_shows_all_that_a_command_writes_however_much_it_writes() -> None:
    much = 1 << 20
    code, out, err = spawned(
        [sys.executable, "-c", f"import sys; sys.stdout.write('x' * {much})"],
        terminal={"out", "err"},
    )
    assert (code, len(out), err) == (0, much, "")


def test_each_stream_is_colored_by_its_own_terminal(unmet: Path, missing: Path) -> None:
    code, out, err = on_terminals([str(unmet), str(missing)], terminal={"err"})
    assert code == Exit.FAULT
    assert "\x1b" not in out
    assert "\x1b[1;31merror\x1b[0m: " in err
    assert "cannot read" in err
    code, out, err = on_terminals([str(unmet), str(missing)], terminal={"out"})
    assert code == Exit.FAULT
    assert "\x1b[1;31m[FAIL]\x1b[0m" in out
    assert "\x1b" not in err


def test_on_terminals_color_and_glyphs_follow_the_flags_and_the_environment(
    unmet: Path,
) -> None:
    _, out, _ = on_terminals([str(unmet)], terminal={"out", "err"})
    assert "\x1b[1;31m[FAIL]\x1b[0m" in out
    assert FAIL_NERD not in out
    _, out, _ = on_terminals(["--icons", str(unmet)], terminal={"out", "err"})
    assert f"\x1b[1;31m{FAIL_NERD}\x1b[0m" in out
    _, out, _ = on_terminals(
        ["--icons", str(unmet)], terminal={"out", "err"}, environment={"NO_COLOR": "1"}
    )
    assert FAIL_NERD in out
    assert "\x1b" not in out
    _, out, _ = on_terminals(["--icons", str(unmet)], terminal={"err"})
    assert FAIL_NERD not in out


@pytest.mark.parametrize("environment", [{"NO_COLOR": "1"}, {"TERM": "dumb"}])
def test_a_terminal_is_plain_when_the_environment_says_so(
    unmet: Path, environment: dict[str, str]
) -> None:
    _, out, err = on_terminals([str(unmet)], terminal={"out", "err"}, environment=environment)
    assert "\x1b" not in out + err
    _, out, _ = on_terminals(
        ["--color=always", str(unmet)], terminal={"out"}, environment=environment
    )
    assert "\x1b[1;31m[FAIL]\x1b[0m" in out


def test_an_empty_no_color_says_nothing_to_a_terminal(unmet: Path) -> None:
    _, out, _ = on_terminals([str(unmet)], terminal={"out"}, environment={"NO_COLOR": ""})
    assert "\x1b[1;31m[FAIL]\x1b[0m" in out


@pytest.mark.parametrize("terminal", [{"out", "err"}, set()], ids=["terminals", "redirected"])
def test_an_explicit_choice_wins_over_the_environment_on_either_stream(
    unmet: Path, terminal: set[str]
) -> None:
    hostile = {"NO_COLOR": "1", "TERM": "dumb"}
    _, out, _ = on_terminals(["--color=always", str(unmet)], terminal=terminal, environment=hostile)
    assert "\x1b[1;31m[FAIL]\x1b[0m" in out
    _, out, _ = on_terminals(
        ["--color=never", str(unmet)], terminal=terminal, environment={"TERM": "xterm"}
    )
    assert "\x1b" not in out


@pytest.mark.parametrize("variables", [{"CLICOLOR_FORCE": "1"}, {"CLICOLOR": "1"}, {}])
def test_a_redirected_stream_stays_plain_whatever_the_environment_asks(
    unmet: Path, variables: dict[str, str]
) -> None:
    _, out, err = on_terminals([str(unmet)], terminal=set(), environment=variables)
    assert "\x1b" not in out + err
