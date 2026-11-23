"""The text view of evidence: a counterexample and its tree, a refutation, a ranking, an answer.

Layout only: every mark, role and word comes from the legend, and every value from the model.
Each step of the tree shows its ground rule instance; `spans` adds the rule as written and its
substitution beneath it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, cast

from elenctic.determination import Range, Refutation
from elenctic.display import legible
from elenctic.explanation import Explanation, Node, Outranked
from elenctic.legend import (
    ASK,
    EVIDENCE,
    EVIDENCE_HEADING,
    EXPECTS_NONE,
    GUARANTEE,
    OUTRANKED,
    WHY,
    Mark,
    answering,
    bindings_of,
    cited,
    counterexample,
    heading,
    helped,
    label,
    mark,
    noted,
    paying,
    ranking,
    said,
    shared,
    shows_why,
    signed,
    stopped,
    taken,
    unfound,
    unreached,
    words,
    written,
)
from elenctic.literals import Literal
from elenctic.paint import Phrase, Role, paint, plain
from elenctic.patterns import Pattern
from elenctic.presentation import Style
from elenctic.query import All, Answer, Answered, Bindings
from elenctic.spans import Span
from elenctic.verdicts import Ended, Finding
from elenctic.writer import queried

_WIDTH: Final = 34
"""The column the words of a short line start at."""

type Lines = Callable[[Span], Sequence[str] | None]
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

    def line(self, phrase: Phrase) -> str:
        """Write a line of the block, beneath its heading."""
        return f"  {self.phrase(phrase)}"

    def answer_set(self, phrase: Phrase) -> str:
        """Write a line naming an answer set, marked as one."""
        return f"  {self.margin('=')} {self.glyph(Mark.COUNTEREXAMPLE)}{self.phrase(phrase)}"

    def heading(self, role: Role, word: str, subject: str, where: str) -> list[str]:
        """Write the opening of a block: what it is about, and where."""
        return [
            self.phrase(heading(role, word, subject)),
            self.margin(f" --> {legible(where)}"),
            self.margin("  |"),
        ]


@dataclass(slots=True)
class _Tree:
    """The lines of an explanation's tree, drawn from its roots; a shared node is drawn once."""

    nodes: dict[str, Node]
    pen: _Pen
    spans: bool
    own: str
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
            self._line(prefix, mark(node), label(node), words(node, self.own))
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
        self.lines.append(f"  {self.pen.margin(guide)}{self.pen.phrase(written(*named))}")


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


def explanation_lines(
    explanation: Explanation,
    style: Style,
    *,
    spans: bool,
    own: str,
    over: Range | None = None,
) -> list[str]:
    """Write the answer set explained, the tree of why each root holds or not, and its guarantee.

    The answer set is one asked for `over` a range, else a counterexample to a failed claim. A
    rule from a file other than the case's `own` is placed by its file as well as its line.
    """
    pen = _Pen(style)
    found = counterexample(explanation.counterexample, over)
    lines = [pen.answer_set(found), pen.margin("  |")]
    if not explanation.roots:
        lines.append(f"  {pen(Role.ASIDE, EXPECTS_NONE)}")
    tree = _Tree({n.handle: n for n in explanation.nodes}, pen, spans, own, set(), [])
    lines += tree.draw(explanation.roots)
    lines += [pen.margin("  |"), pen.line(noted(GUARANTEE[explanation.minimality]))]
    if not explanation.complete:
        lines.append(pen.line(noted(stopped(explanation.max_depth))))
    return lines


def outranked_lines(
    outranked: Outranked, style: Style, lines_of: Lines, *, spans: bool, own: str
) -> list[str]:
    """Write how the objective ranks the literals below the optimum, and why it lacks them."""
    pen = _Pen(style)
    lines = [
        f"  {pen.glyph(Mark.OUTRANKED)}{pen(Role.EMPHASIS, OUTRANKED)}",
        *(pen.line(phrase) for phrase in ranking(outranked)),
    ]
    for payments, more in ((outranked.assuming_only, True), (outranked.optimum_only, False)):
        for payment in payments:
            lines += map(pen.phrase, paying(payment, lines_of(payment.rule.span), more=more))
    lines.append(pen.margin("  |"))
    return lines + explanation_lines(outranked.explanation, style, spans=spans, own=own)


def evidence_lines(finding: Finding, style: Style, lines_of: Lines, *, spans: bool) -> list[str]:
    """Write the block that shows a finding's evidence, or nothing if it has none."""
    evidence = finding.evidence
    if evidence is None:
        return []
    pen = _Pen(style)
    span = finding.claim.span
    where = f"{span.source}:{span.start.line}:{span.start.column}"
    lines = pen.heading(Role.ERROR, EVIDENCE_HEADING, finding.claim_text, where)
    match evidence:
        case Explanation():
            lines += explanation_lines(evidence, style, spans=spans, own=span.source)
        case Outranked():
            lines += outranked_lines(evidence, style, lines_of, spans=spans, own=span.source)
        case _:
            lines.append(pen.line(unfound(evidence)))
    return [*lines, ""]


def why_lines(  # noqa: PLR0913
    source: str,
    atom: Literal,
    result: Explanation | Refutation | Ended,
    style: Style,
    *,
    spans: bool,
    over: Range,
    negated: bool,
) -> list[str]:
    """Write the block that shows why an atom holds, or not, in the answer set asked for.

    It is headed by the atom as it was asked: `negated` when `not` was written before it.
    """
    pen = _Pen(style)
    lines = pen.heading(Role.NOTE, WHY, signed(atom, negated=negated), source)
    if isinstance(result, Explanation):
        lines += explanation_lines(result, style, spans=spans, own=source, over=over)
    else:
        lines.append(pen.line(unfound(result)))
    return [*lines, ""]


def ask_lines(
    source: str, query: All | Pattern, result: Answered | Refutation | Ended, style: Style
) -> list[str]:
    """Write the block that shows a query's answer and the first answer set giving each value.

    A pattern with variables shows its bindings instead: those giving yes, and any others.
    """
    pen = _Pen(style)
    lines = pen.heading(Role.NOTE, ASK, queried(query), source)
    if not isinstance(result, Answered):
        return [*lines, pen.line(unfound(result)), ""]
    if isinstance(result.answer, Bindings):
        found = result.answer
        shown = [each for each in Answer if each is Answer.YES or found.giving(each)]
        pattern = cast("Pattern", query)
        return [*lines, *(pen.line(said(bindings_of(each, pattern, found))) for each in shown), ""]
    conjunction = cast("All", query)
    lines.append(pen.line(said(answering(result.answer))))
    lines += [pen.answer_set(taken(each, conjunction, result)) for each in result.taken]
    lines += [pen.answer_set(unreached(each, conjunction)) for each in result.unreached]
    match conjunction.parts, result.taken:
        case (Literal() as alone,), (first, *_):
            helping = helped(shows_why(source, alone, first, result.over))
            lines += [pen.margin("  |"), pen.line(helping)]
        case _:
            pass
    return [*lines, ""]
