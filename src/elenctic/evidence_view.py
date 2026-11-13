"""The text view of a finding's evidence: a counterexample and its tree, a refutation, a ranking.

Layout only: every mark, role and word comes from the legend, and every value from the model.
Each step of the tree shows its ground rule instance; `spans` adds the rule as written and its
substitution beneath it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from elenctic.display import legible
from elenctic.explanation import Explanation, Node, Outranked, Paid
from elenctic.legend import (
    COST,
    EVIDENCE,
    EVIDENCE_HEADING,
    EXPECTS_NONE,
    GUARANTEE,
    OPTIMUM,
    OUTRANKED,
    PAID,
    REFUTATION,
    Mark,
    assuming,
    cited,
    counterexample,
    differs,
    ended,
    label,
    listed,
    mark,
    paid,
    possible,
    priority,
    refuted,
    shared,
    stopped,
    words,
)
from elenctic.paint import Phrase, Role, paint, plain
from elenctic.presentation import Style
from elenctic.spans import Span
from elenctic.verdicts import Ended, Finding

_WIDTH: Final = 34
"""The column the words of a short line start at."""

type Lines = Callable[[Span], list[str] | None]
"""The lines of the source a span is in, or `None` if it cannot be read."""


@dataclass(frozen=True, slots=True)
class _Pen:
    style: Style

    def __call__(self, role: Role, text: str) -> str:
        """Make untrusted `text` legible, then style it."""
        return paint(self.style.color, role, legible(text)) if text else ""

    def phrase(self, phrase: Phrase) -> str:
        return self.style.text(phrase)

    def glyph(self, kind: Mark) -> str:
        shown = EVIDENCE[kind].shown(self.style.glyphs)
        return f"{shown} " if shown else ""

    def margin(self, text: str) -> str:
        return paint(self.style.color, Role.MARGIN, text)

    def note(self, words: str) -> str:
        return f"  {paint(self.style.color, Role.NOTE, '= note:')} {words}"


@dataclass(slots=True)
class _Tree:
    """The lines of an explanation's tree, drawn from its roots; a shared node is drawn once."""

    nodes: dict[str, Node]
    pen: _Pen
    spans: bool
    drawn: set[str]
    lines: list[str]

    def draw(self, roots: tuple[str, ...]) -> list[str]:
        """Draw each root and what lies beneath it.

        The only child of a step that is not a root is drawn at that step's indent, with no
        branch: a chain of single reasons keeps one indent however long it is.
        """
        pending: list[tuple[str, str, str, bool]] = [
            (root, "", "", True) for root in reversed(roots)
        ]
        while pending:
            handle, prefix, below, root = pending.pop()
            node = self.nodes[handle]
            if handle in self.drawn and node.children:
                self._line(prefix, Mark.SHARED, *shared(node))
                continue
            self.drawn.add(handle)
            chained = len(node.children) == 1 and not root
            self._line(prefix, mark(node), label(node), words(node))
            self._spans(node, below + ("│   " if node.children and not chained else "    "))
            pending.extend(_beneath(node, below, chained=chained))
        return self.lines

    def _line(self, prefix: str, kind: Mark, head: Phrase, said: Phrase) -> None:
        """Add a step's line, its words starting at `_WIDTH` if its head is short."""
        pen = self.pen
        glyph = pen.glyph(kind)
        gap = " " * max(2, _WIDTH - len(prefix) - len(glyph) - len(legible(plain(head))))
        self.lines.append(f"  {pen.margin(prefix)}{glyph}{pen.phrase(head)}{gap}{pen.phrase(said)}")

    def _spans(self, node: Node, guide: str) -> None:
        """Add the rule a step cites as written, and its substitution, if `spans` asks for it."""
        named = cited(node.reason)
        if not self.spans or named is None:
            return
        pen = self.pen
        rule, substitution = named
        written = " ".join(rule.text.split())
        given = f" {pen(Role.ASIDE, substitution)}" if substitution else ""
        where = f"= {rule.span.source}:{rule.span.start.line}:"
        self.lines.append(
            f"  {pen.margin(guide)}{pen(Role.REFERENCE, where)} {legible(written)}{given}"
        )


def _beneath(node: Node, below: str, *, chained: bool) -> list[tuple[str, str, str, bool]]:
    """Name the children of a step to draw next, last first, each with its prefix and guide."""
    if chained:
        return [(node.children[0], below, below, False)]
    last = len(node.children) - 1
    return [
        (
            child,
            below + ("└── " if at == last else "├── "),
            below + ("    " if at == last else "│   "),
            False,
        )
        for at, child in reversed(list(enumerate(node.children)))
    ]


def explanation_lines(explanation: Explanation, style: Style, *, spans: bool) -> list[str]:
    """Write the counterexample, the tree of why each root holds or not, and its guarantee."""
    pen = _Pen(style)
    lines = [
        (
            f"  {pen.margin('=')} {pen.glyph(Mark.COUNTEREXAMPLE)}"
            f"{pen.phrase(counterexample(explanation.counterexample))}"
        ),
        pen.margin("  |"),
    ]
    if not explanation.roots:
        lines.append(f"  {pen(Role.ASIDE, EXPECTS_NONE)}")
    tree = _Tree({n.handle: n for n in explanation.nodes}, pen, spans, set(), [])
    lines += tree.draw(explanation.roots)
    lines += [pen.margin("  |"), pen.note(GUARANTEE[explanation.minimality])]
    if not explanation.complete:
        lines.append(pen.note(stopped(explanation.max_depth)))
    return lines


def _paid(payment: Paid, lines_of: Lines, pen: _Pen, *, more: bool) -> list[str]:
    span = payment.rule.span
    source = lines_of(span)
    arrow = pen.margin(f" --> {legible(span.source)}:{span.start.line}:{span.start.column}")
    said = pen.phrase(paid(payment, more=more))
    if source is None or not 1 <= span.start.line <= len(source):
        return [arrow, f"  {pen.margin('|')} {legible(payment.rule.text)} {said}"]
    width = max(1, span.end.column - span.start.column) if span.end.line == span.start.line else 1
    carets = pen(Role.ERROR if more else Role.NOTE, "^" * width)
    number = str(span.start.line)
    pad = " " * len(number)
    return [
        arrow,
        pen.margin(f"{pad} |"),
        f"{pen.margin(f'{number} |')} {legible(source[span.start.line - 1])}",
        f"{pen.margin(f'{pad} |')} {' ' * (span.start.column - 1)}{carets} {said}",
    ]


def outranked_lines(
    outranked: Outranked, style: Style, lines_of: Lines, *, spans: bool
) -> list[str]:
    """Write how the objective ranks the literals below the optimum, and why it lacks them."""
    pen = _Pen(style)
    literals = ", ".join(map(str, listed(outranked.literals) or ()))
    pad = len(assuming(literals)) + 2
    cells = "".join(f"{priority(p):>12}" for p in outranked.priorities)

    def row(name: str, cost: tuple[int, ...], role: Role) -> str:
        return f"    {legible(name):<{pad}}" + "".join(
            pen(role if p == outranked.priority else Role.EMPHASIS, f"{v:>12}")
            for p, v in zip(outranked.priorities, cost, strict=False)
        )

    lines = [
        f"  {pen.glyph(Mark.OUTRANKED)}{pen(Role.EMPHASIS, OUTRANKED)}",
        f"  {pen.margin('1')} {legible(possible(literals))}",
        f"  {pen.margin('2')} {COST:<{pad}}{cells}",
        row(assuming(literals), outranked.assuming, Role.ERROR),
        row(OPTIMUM, outranked.optimum, Role.NOTE)
        + f"  {pen(Role.ASIDE, differs(outranked.priority))}",
        f"  {pen.margin('3')} {PAID}",
    ]
    for payment in outranked.assuming_only:
        lines += _paid(payment, lines_of, pen, more=True)
    for payment in outranked.optimum_only:
        lines += _paid(payment, lines_of, pen, more=False)
    lines.append(pen.margin("  |"))
    return lines + explanation_lines(outranked.explanation, style, spans=spans)


def evidence_lines(finding: Finding, style: Style, lines_of: Lines, *, spans: bool) -> list[str]:
    """Write the block that shows a finding's evidence, or nothing if it has none."""
    evidence = finding.evidence
    if evidence is None:
        return []
    pen = _Pen(style)
    span = finding.claim.span
    lines = [
        f"{pen(Role.ERROR, EVIDENCE_HEADING)}: {pen(Role.EMPHASIS, finding.claim_text)}",
        pen.margin(f" --> {legible(span.source)}:{span.start.line}:{span.start.column}"),
        pen.margin("  |"),
    ]
    match evidence:
        case Explanation():
            lines += explanation_lines(evidence, style, spans=spans)
        case Outranked():
            lines += outranked_lines(evidence, style, lines_of, spans=spans)
        case Ended():
            lines.append(f"  {pen.margin('=')} {pen(Role.WARNING, ended(evidence))}")
        case _:
            said = legible(refuted(evidence))
            lines.append(f"  {pen.margin('=')} {pen(Role.EMPHASIS, REFUTATION)}: {said}")
    return [*lines, ""]
