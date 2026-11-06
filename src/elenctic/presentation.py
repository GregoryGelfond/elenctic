"""How output looks: color and glyphs, decided once per stream from flags and environment."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, StrEnum, auto
from typing import Final, Protocol, Self, runtime_checkable

from elenctic.glyphs import Glyphs
from elenctic.paint import Color


class When(StrEnum):
    """The choice `--color` and `--icons` ask for."""

    AUTO = auto()
    """On a terminal, unless `NO_COLOR` or `TERM=dumb` says otherwise."""
    ALWAYS = auto()
    NEVER = auto()


@runtime_checkable
class _Tty(Protocol):
    """The one thing elenctic asks of an output stream: whether it is a terminal."""

    def isatty(self) -> bool: ...


class Stream(Enum):
    """Where output goes."""

    TERMINAL = "terminal"
    REDIRECTED = "redirected"
    """A file or a pipe."""

    @classmethod
    def of(cls, stream: _Tty) -> Stream:
        return Stream.TERMINAL if stream.isatty() else Stream.REDIRECTED


@dataclass(frozen=True, slots=True)
class Environment:
    """Color cues from the environment."""

    no_color: bool
    """`NO_COLOR` is not empty."""
    dumb: bool
    """`TERM` is `dumb`."""

    @classmethod
    def of(cls, variables: Mapping[str, str]) -> Self:
        return cls(
            no_color=bool(variables.get("NO_COLOR")),
            dumb=variables.get("TERM") == "dumb",
        )


@dataclass(frozen=True, slots=True)
class Style:
    """How one stream is written."""

    color: Color
    glyphs: Glyphs


@dataclass(frozen=True, slots=True)
class Presentation:
    """How both streams are written. Resolved once; a renderer reads nothing but this."""

    stdout: Style
    stderr: Style


PLAIN: Final = Presentation(Style(Color.OFF, Glyphs.PLAIN), Style(Color.OFF, Glyphs.PLAIN))


def _color(when: When, stream: Stream, environment: Environment) -> Color:
    """Decide color: the choice, else `NO_COLOR`, `TERM=dumb`, then the stream."""
    if when is not When.AUTO:
        return Color.ON if when is When.ALWAYS else Color.OFF
    if environment.no_color or environment.dumb:
        return Color.OFF
    return Color.ON if stream is Stream.TERMINAL else Color.OFF


def _glyphs(when: When, stream: Stream) -> Glyphs:
    """Glyphs follow `--icons` and the stream alone; the environment does not touch them."""
    shown = when is When.ALWAYS or (when is When.AUTO and stream is Stream.TERMINAL)
    return Glyphs.NERD if shown else Glyphs.PLAIN


def resolve(
    color: When, icons: When, environment: Environment, *, stdout: Stream, stderr: Stream
) -> Presentation:
    """Decide how each stream is written."""

    def style(stream: Stream) -> Style:
        return Style(_color(color, stream, environment), _glyphs(icons, stream))

    return Presentation(style(stdout), style(stderr))
