"""The text view of evidence: a counterexample and its tree, a refutation, a ranking, an answer.

Layout only: every mark, role and word comes from the legend, and every value from the model.
Each step of the tree shows its ground rule instance; `spans` adds the rule as written and its
substitution beneath it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, cast

from elenctic.determination import Range, Refutation
from elenctic.display import legible
from elenctic.explanation import Explanation, Node, Outranked, Paid
from elenctic.legend import (
    ANSWER,
    ASK,
    COST,
    EVIDENCE,
    EVIDENCE_HEADING,
    EXPECTS_NONE,
    GUARANTEE,
    OPTIMUM,
    OUTRANKED,
    PAID,
    REFUTATION,
    WHY,
    Mark,
    assuming,
    bindings_of,
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
    shows_why,
    stopped,
    taken,
    words,
)
from elenctic.literals import Literal
from elenctic.paint import Phrase, Piece, Role, paint, plain
from elenctic.patterns import Pattern
from elenctic.presentation import Style
from elenctic.query import All, Answer, Answered, Bindings
from elenctic.spans import Severity, Span
from elenctic.verdicts import Ended, Finding
from elenctic.writer import queried

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
        return f"  {paint(self.style.color, Role.NOTE, f'= {Severity.NOTE.value}:')} {words}"

    def help(self, words: str) -> str:
        return (
            f"  {paint(self.style.color, Role.HELP, f'= {Severity.HELP.value}:')} {legible(words)}"
        )

    def said(self, phrase: Phrase) -> str:
        """Write a line that says something of the whole block."""
        return f"  {self.margin('=')} {self.phrase(phrase)}"

    def answer_set(self, phrase: Phrase) -> str:
        """Write a line naming an answer set, marked as one."""
        return f"  {self.margin('=')} {self.glyph(Mark.COUNTEREXAMPLE)}{self.phrase(phrase)}"

    def heading(self, role: Role, word: str, subject: str, where: str) -> list[str]:
        """Write the opening of a block: what it is about, and where."""
        return [
            f"{self(role, word)}: {self(Role.EMPHASIS, subject)}",
            self.margin(f" --> {legible(where)}"),
            self.margin("  |"),
        ]

    def unfound(self, result: Refutation | Ended) -> str:
        """Write why there is nothing to show: the search ended, or there is no answer set."""
        if isinstance(result, Ended):
            return f"  {self.margin('=')} {self(Role.WARNING, ended(result))}"
        return f"  {self.margin('=')} {self(Role.EMPHASIS, REFUTATION)}: {legible(refuted(result))}"


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


def explanation_lines(
    explanation: Explanation,
    style: Style,
    *,
    spans: bool,
    failed: bool = True,
    over: Range = Range.ALL,
) -> list[str]:
    """Write the answer set explained, the tree of why each root holds or not, and its guarantee.

    The answer set is a counterexample if a claim `failed` in it, and else one of `over`.
    """
    pen = _Pen(style)
    found = counterexample(explanation.counterexample, failed=failed, over=over)
    lines = [pen.answer_set(found), pen.margin("  |")]
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
    where = f"{span.source}:{span.start.line}:{span.start.column}"
    lines = pen.heading(Role.ERROR, EVIDENCE_HEADING, finding.claim_text, where)
    match evidence:
        case Explanation():
            lines += explanation_lines(evidence, style, spans=spans)
        case Outranked():
            lines += outranked_lines(evidence, style, lines_of, spans=spans)
        case _:
            lines.append(pen.unfound(evidence))
    return [*lines, ""]


def why_lines(  # noqa: PLR0913
    source: str,
    atom: Literal,
    result: Explanation | Refutation | Ended,
    style: Style,
    *,
    spans: bool,
    over: Range,
) -> list[str]:
    """Write the block that shows why an atom holds, or not, in the answer set asked for."""
    pen = _Pen(style)
    lines = pen.heading(Role.NOTE, WHY, str(atom), source)
    if isinstance(result, Explanation):
        lines += explanation_lines(result, style, spans=spans, failed=False, over=over)
    else:
        lines.append(pen.unfound(result))
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
        return [*lines, pen.unfound(result), ""]
    if isinstance(result.answer, Bindings):
        found = result.answer
        shown = [each for each in Answer if each is Answer.YES or found.giving(each)]
        pattern = cast("Pattern", query)
        return [*lines, *(pen.said(bindings_of(each, pattern, found)) for each in shown), ""]
    conjunction = cast("All", query)
    lines.append(pen.said((Piece(ANSWER, Role.EMPHASIS), Piece(f": {result.answer.value}"))))
    lines += [pen.answer_set(taken(each, conjunction, result)) for each in result.taken]
    match conjunction.parts, result.taken:
        case (Literal() as alone,), (first, *_):
            lines += [pen.margin("  |"), pen.help(shows_why(source, alone, first, result.over))]
        case _:
            pass
    return [*lines, ""]
