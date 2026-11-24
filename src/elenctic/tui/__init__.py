"""The interactive view of `explain`, `why`, `ask` and `test`: the optional `elenctic[tui]` extra.

The one package that imports Textual and Rich. It shows what the library returned and asks the
library, through the callables it is given, for anything more.
"""

from collections.abc import Callable
from itertools import count

from elenctic.determination import Range
from elenctic.explanation import Explanation
from elenctic.legend import signed, tally, titled
from elenctic.literals import Literal
from elenctic.patterns import Pattern
from elenctic.presentation import Style
from elenctic.program import Fault
from elenctic.query import All
from elenctic.report import Entry, Internal, Run
from elenctic.search import Limit
from elenctic.tui import outline
from elenctic.tui.app import View, Viewer
from elenctic.tui.outline import Asking, Diagnosed, Lines, Row
from elenctic.verdicts import Finding

type Depth = int | Limit
type Evidenced = Callable[[Entry, Finding, Depth], Finding | Fault | Internal]
"""Find a failed claim's evidence at a depth, or say why it cannot be found."""
type Explained = Callable[[Depth], Explanation | outline.Unfound | Fault | Internal]
"""Explain an atom at a depth, or say why there is nothing to explain."""


def _refused(
    diagnosed: Diagnosed, refusal: Fault | Internal, text: str | None, source: str
) -> list[Row]:
    return outline.refused(diagnosed(refusal, text, source))


def run_view(  # noqa: PLR0913
    run: Run,
    style: Style,
    *,
    command: str,
    subject: str,
    lines_of: Lines,
    diagnosed: Diagnosed,
    evidence: Evidenced,
    max_depth: Depth,
    every: bool,
    opened: bool,
) -> View:
    """Make the view of a run: each source, its claims, and each failed claim's evidence.

    A claim's evidence is found when it is opened, and `opened` opens each failed claim at the
    start; `every` lists the claims that passed too.
    """
    glyphs = style.glyphs
    claims: dict[int, tuple[Entry, Finding]] = {}
    numbers = count()

    def numbered(entry: Entry) -> Callable[[Finding], int]:
        def block(finding: Finding) -> int:
            number = next(numbers)
            claims[number] = (entry, finding)
            return number

        return block

    rows = [
        outline.entry(
            entry, glyphs, lines_of, diagnosed, numbered(entry), every=every, opened=opened
        )
        for entry in run.entries
    ]

    def found(block: int, depth: Depth) -> list[Row]:
        entry, finding = claims[block]
        result = evidence(entry, finding, depth)
        if isinstance(result, Finding):
            return outline.evidence(result, glyphs, lines_of, block)
        return _refused(diagnosed, result, entry.text, entry.source)

    return View(titled(command, subject), tally(run), rows, lines_of, max_depth, found, claims=True)


def why_view(  # noqa: PLR0913
    source: str,
    atom: Literal,
    result: Explanation | outline.Unfound,
    style: Style,
    *,
    over: Range,
    negated: bool,
    lines_of: Lines,
    diagnosed: Diagnosed,
    explained: Explained,
    max_depth: Depth,
    text: str | None,
) -> View:
    """Make the view of what `why` found; going deeper explains the atom again, deeper."""
    glyphs = style.glyphs

    def found(_block: int, depth: Depth) -> list[Row]:
        again = explained(depth)
        if isinstance(again, Fault | Internal):
            return _refused(diagnosed, again, text, source)
        return outline.explaining(again, glyphs, own=source, over=over)

    asked = signed(atom, negated=negated)
    rows = outline.why(asked, result, glyphs, own=source, over=over)
    return View(titled("why", source), (), rows, lines_of, max_depth, found)


def ask_view(  # noqa: PLR0913
    source: str,
    query: All | Pattern,
    result: outline.Answering,
    style: Style,
    *,
    over: Range,
    lines_of: Lines,
    diagnosed: Diagnosed,
    why_of: Callable[[Literal, int, Depth], Explanation | outline.Unfound | Fault | Internal],
    max_depth: Depth,
    text: str | None,
    unknown: bool = False,
) -> View:
    """Make the view of what `ask` found; an answer set it names opens `why` on its literal."""

    def why(asking: Asking) -> View:
        first = why_of(asking.literal, asking.index, max_depth)
        if isinstance(first, Fault | Internal):
            rows = _refused(diagnosed, first, text, source)
            return View(titled("why", source), (), rows, lines_of, max_depth, lambda _b, _d: rows)
        return why_view(
            source,
            asking.literal,
            first,
            style,
            over=over,
            negated=False,
            lines_of=lines_of,
            diagnosed=diagnosed,
            explained=lambda depth: why_of(asking.literal, asking.index, depth),
            max_depth=max_depth,
            text=text,
        )

    rows = outline.ask(source, query, result, style.glyphs, unknown=unknown)
    return View(
        titled("ask", source), (), rows, lines_of, max_depth, lambda _b, _d: [], why, steps=False
    )


def show(view: View, style: Style) -> None:
    """Run the app on a view until the user quits it."""
    Viewer(view, style).run()


__all__ = ["View", "ask_view", "run_view", "show", "why_view"]
