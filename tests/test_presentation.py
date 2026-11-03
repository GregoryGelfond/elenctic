import ast
import os
from pathlib import Path

import pytest

import elenctic
from elenctic.glyphs import Glyphs
from elenctic.paint import Color
from elenctic.presentation import (
    PLAIN,
    Environment,
    Presentation,
    Stream,
    Style,
    When,
    resolve,
)

T, R = Stream.TERMINAL, Stream.REDIRECTED
ON, OFF = Color.ON, Color.OFF
QUIET = Environment(no_color=False, dumb=False, forced=False)


@pytest.mark.parametrize(
    ("variables", "expected"),
    [
        ({}, QUIET),
        ({"NO_COLOR": "1"}, Environment(no_color=True, dumb=False, forced=False)),
        ({"NO_COLOR": "0"}, Environment(no_color=True, dumb=False, forced=False)),
        ({"NO_COLOR": ""}, QUIET),
        ({"TERM": "dumb"}, Environment(no_color=False, dumb=True, forced=False)),
        ({"TERM": "xterm-256color"}, QUIET),
        ({"CLICOLOR_FORCE": "1"}, Environment(no_color=False, dumb=False, forced=True)),
        ({"CLICOLOR_FORCE": "yes"}, Environment(no_color=False, dumb=False, forced=True)),
        ({"CLICOLOR_FORCE": "0"}, QUIET),
        ({"CLICOLOR_FORCE": ""}, QUIET),
        ({"FORCE_COLOR": "1"}, QUIET),
        ({"CLICOLOR": "1"}, QUIET),
    ],
)
def test_the_environment_is_read_for_the_four_variables_that_count(
    variables: dict[str, str], expected: Environment
) -> None:
    assert Environment.of(variables) == expected


def colors_of(
    choice: When, environment: Environment, *, stdout: Stream, stderr: Stream
) -> tuple[Color, Color]:
    presentation = resolve(choice, When.NEVER, environment, stdout=stdout, stderr=stderr)
    return presentation.stdout.color, presentation.stderr.color


NO_COLOR = Environment(no_color=True, dumb=False, forced=False)
DUMB = Environment(no_color=False, dumb=True, forced=False)
FORCED = Environment(no_color=False, dumb=False, forced=True)
EVERYTHING = Environment(no_color=True, dumb=True, forced=True)
FORCED_DUMB = Environment(no_color=False, dumb=True, forced=True)

# (choice, environment, stdout stream, stderr stream) -> (stdout colour, stderr colour)
PRECEDENCE = [
    # an explicit flag wins over everything, per stream or not
    (When.ALWAYS, EVERYTHING, (R, R), (ON, ON)),
    (When.ALWAYS, QUIET, (R, R), (ON, ON)),
    (When.NEVER, FORCED, (T, T), (OFF, OFF)),
    (When.NEVER, QUIET, (T, T), (OFF, OFF)),
    # auto: NO_COLOR beats TERM=dumb beats CLICOLOR_FORCE beats the stream
    (When.AUTO, NO_COLOR, (T, T), (OFF, OFF)),
    (When.AUTO, Environment(no_color=True, dumb=False, forced=True), (T, T), (OFF, OFF)),
    (When.AUTO, DUMB, (T, T), (OFF, OFF)),
    (When.AUTO, FORCED_DUMB, (T, T), (OFF, OFF)),
    (When.AUTO, FORCED, (R, R), (ON, ON)),
    (When.AUTO, FORCED, (T, R), (ON, ON)),
    # auto with nothing set: each stream by its own terminal
    (When.AUTO, QUIET, (T, T), (ON, ON)),
    (When.AUTO, QUIET, (T, R), (ON, OFF)),
    (When.AUTO, QUIET, (R, T), (OFF, ON)),
    (When.AUTO, QUIET, (R, R), (OFF, OFF)),
]


@pytest.mark.parametrize(
    ("choice", "environment", "streams", "colors"),
    PRECEDENCE,
)
def test_colour_is_decided_per_stream_by_the_precedence_table(
    choice: When,
    environment: Environment,
    streams: tuple[Stream, Stream],
    colors: tuple[Color, Color],
) -> None:
    stdout, stderr = streams
    assert colors_of(choice, environment, stdout=stdout, stderr=stderr) == colors


GLYPHS = [
    (When.NEVER, T, Glyphs.PLAIN),
    (When.NEVER, R, Glyphs.PLAIN),
    (When.ALWAYS, T, Glyphs.NERD),
    (When.ALWAYS, R, Glyphs.NERD),
    (When.AUTO, T, Glyphs.NERD),
    (When.AUTO, R, Glyphs.PLAIN),
]


@pytest.mark.parametrize("environment", [QUIET, NO_COLOR, DUMB, FORCED, EVERYTHING])
@pytest.mark.parametrize("color", list(When))
@pytest.mark.parametrize(("icons", "stream", "expected"), GLYPHS)
def test_glyphs_follow_icons_and_the_stream_alone(
    icons: When, stream: Stream, expected: Glyphs, color: When, environment: Environment
) -> None:
    presentation = resolve(color, icons, environment, stdout=stream, stderr=stream)
    assert (presentation.stdout.glyphs, presentation.stderr.glyphs) == (expected, expected)


def test_each_stream_has_its_own_glyphs() -> None:
    presentation = resolve(When.NEVER, When.AUTO, QUIET, stdout=T, stderr=R)
    assert presentation == Presentation(Style(OFF, Glyphs.NERD), Style(OFF, Glyphs.PLAIN))


def test_the_plain_presentation_is_no_colour_and_no_glyph() -> None:
    assert resolve(When.NEVER, When.NEVER, QUIET, stdout=T, stderr=T) == PLAIN


def test_the_stream_of_a_file_is_redirected(tmp_path: Path) -> None:
    with (tmp_path / "out").open("w") as file:
        assert Stream.of(file) is Stream.REDIRECTED


def test_a_pseudo_terminal_is_a_terminal() -> None:
    master, slave = os.openpty()
    try:
        with os.fdopen(slave, "w", closefd=False) as terminal:
            assert Stream.of(terminal) is Stream.TERMINAL
    finally:
        os.close(master)
        os.close(slave)


def test_only_the_adapters_ask_the_environment_or_a_stream() -> None:
    package = Path(elenctic.__file__).parent
    asked = {"environ", "environb", "getenv", "isatty"}
    users = {
        path.name: {
            node.attr
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.Attribute) and node.attr in asked
        }
        for path in package.glob("*.py")
    }
    assert {name: found for name, found in users.items() if found} == {
        "cli.py": {"environ"},
        "presentation.py": {"isatty"},
    }
