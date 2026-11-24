"""The rows of the interactive view, built from what the library returned, as the text view's lines.

Each row is a phrase from the legend, as the text view writes it, beneath the row it belongs to. A
row knows what it shows (a step, a step shown above, an answer set), so the view can act on it; it
knows nothing of Textual.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import cast

from elenctic.determination import Range, Refutation
from elenctic.explanation import Explanation, Handle, Node, Outranked, Paid
from elenctic.glyphs import Glyphs
from elenctic.legend import (
    ASK,
    EVIDENCE,
    EVIDENCE_HEADING,
    EXPECTS_NONE,
    GUARANTEE,
    MARKS,
    OUTRANKED,
    VERDICT_ROLES,
    WHY,
    Mark,
    answering,
    bindings_of,
    counterexample,
    faulted,
    heading,
    helped,
    judged,
    label,
    mark,
    noted,
    paying,
    ranking,
    reported,
    said,
    shared,
    shows_why,
    stopped,
    taken,
    unfound,
    unreached,
    words,
)
from elenctic.literals import Literal
from elenctic.paint import Phrase, Piece, Role
from elenctic.patterns import Pattern
from elenctic.program import Fault
from elenctic.query import ANSWERS, All, Answer, Answered, AnswerMode, Answers
from elenctic.report import Entry, Internal
from elenctic.spans import Span
from elenctic.verdicts import Ended, Finding, Report, Verdict
from elenctic.writer import queried

type Unfound = Refutation | Ended
"""Why there is nothing to explain: no answer set, or a search that ended first."""
type Answering = Answered | Refutation | Ended
"""What `ask` comes to when it was asked."""

type Lines = Callable[[Span], Sequence[str] | None]
"""The lines of the source a span is in, or `None` if it cannot be read."""


@dataclass(frozen=True, slots=True)
class Step:
    """A row that shows a node of an explanation, in the block `block`."""

    node: Node
    block: int


@dataclass(frozen=True, slots=True)
class Again:
    """A row that shows a node a second time; its first row is the one named `handle`."""

    handle: Handle
    block: int


@dataclass(frozen=True, slots=True)
class Block:
    """A row whose children are the evidence block `block`; with none, they are found on opening."""

    block: int


@dataclass(frozen=True, slots=True)
class Asking:
    """A row naming an answer set a query was answered in, which `why` can explain."""

    literal: Literal
    index: int


@dataclass(frozen=True, slots=True)
class Paying:
    """A row of how the objective ranks a claim: the weak-constraint instances it is about.

    Each is paid by one side only, more by the claim's side when `True`.
    """

    payments: tuple[tuple[Paid, bool], ...]


@dataclass(frozen=True, slots=True)
class Source:
    """A row heading what one source came to; `failed` says it did not pass."""

    failed: bool


type About = Step | Again | Block | Asking | Paying | Source
"""What a row shows, when the view can act on it."""


def _none() -> list[Row]:
    return []


@dataclass(slots=True)
class Row:
    """One line of the view: its lead, unescaped (a glyph or a margin), then its phrase.

    A step's `words` follow its label after a gap. A row with `ansi` shows that text as it is: a
    diagnostic the text view already wrote.
    """

    lead: Phrase
    phrase: Phrase
    words: Phrase = ()
    children: list[Row] = field(default_factory=_none)
    opened: bool = True
    about: About | None = None
    ansi: str | None = None


def _glyph(kind: Mark, glyphs: Glyphs) -> Phrase:
    shown = EVIDENCE[kind].shown(glyphs)
    return (Piece(f"{shown} "),) if shown else ()


def _answer_set(phrase: Phrase, glyphs: Glyphs) -> tuple[Phrase, Phrase]:
    """Split a line naming an answer set into its lead, the margin and the glyph, and its phrase."""
    return (Piece("=", Role.MARGIN), Piece(" "), *_glyph(Mark.COUNTEREXAMPLE, glyphs)), phrase


def steps(explanation: Explanation, glyphs: Glyphs, block: int, own: str) -> list[Row]:
    """Build the rows of an explanation's tree, each root first; a shared node is drawn once.

    The text view's shape: the only child of a step that is not a root follows it at its indent,
    so a chain of single reasons keeps one indent however long it is.
    """
    nodes = {node.handle: node for node in explanation.nodes}
    drawn: set[Handle] = set()
    top: list[Row] = []
    pending: list[tuple[Handle, bool, list[Row]]] = [
        (root, True, top) for root in reversed(explanation.roots)
    ]
    while pending:
        handle, root, into = pending.pop()
        node = nodes[handle]
        if handle in drawn and node.children:
            head, said_ = shared(node)
            into.append(Row(_glyph(Mark.SHARED, glyphs), head, said_, about=Again(handle, block)))
            continue
        drawn.add(handle)
        chained = len(node.children) == 1 and not root
        row = Row(
            _glyph(mark(node), glyphs), label(node), words(node, own), about=Step(node, block)
        )
        into.append(row)
        beneath = into if chained else row.children
        pending.extend((child, False, beneath) for child in reversed(node.children))
    return top


def explained(
    explanation: Explanation, glyphs: Glyphs, block: int, *, own: str, over: Range | None
) -> list[Row]:
    """Build the rows of an explanation: the answer set explained, its tree and its notes.

    As the text view's: the answer set is one asked for `over` a range, else a counterexample.
    """
    found = counterexample(explanation.counterexample, over)
    rows = [Row(*_answer_set(found, glyphs))]
    if not explanation.roots:
        rows.append(Row((), (Piece(EXPECTS_NONE, Role.ASIDE),)))
    rows += steps(explanation, glyphs, block, own)
    rows.append(Row((), noted(GUARANTEE[explanation.minimality])))
    if not explanation.complete:
        rows.append(Row((), noted(stopped(explanation.max_depth))))
    return rows


def _paying(outranked: Outranked) -> Paying:
    """Take the instances one side pays and the other does not, the claim's side first."""
    sides = ((outranked.assuming_only, True), (outranked.optimum_only, False))
    return Paying(tuple((payment, more) for payments, more in sides for payment in payments))


def _payments(ranked: Paying, lines_of: Lines) -> list[Row]:
    rows: list[Row] = []
    for payment, more in ranked.payments:
        one = Paying(((payment, more),))
        arrow, *quote = paying(payment, lines_of(payment.rule.span), more=more)
        rows.append(
            Row((), arrow, children=[Row((), each, about=one) for each in quote], about=one)
        )
    return rows


def evidence(finding: Finding, glyphs: Glyphs, lines_of: Lines, block: int) -> list[Row]:
    """Build the rows of a failed claim's evidence, under a heading naming it; none without any."""
    if finding.evidence is None:
        return []
    rows = [Row((), heading(Role.ERROR, EVIDENCE_HEADING, finding.claim_text))]
    own = finding.claim.span.source
    match finding.evidence:
        case Explanation() as explanation:
            rows += explained(explanation, glyphs, block, own=own, over=None)
        case Outranked() as outranked:
            ranked = _paying(outranked)
            mark = _glyph(Mark.OUTRANKED, glyphs)
            rows.append(Row(mark, (Piece(OUTRANKED, Role.EMPHASIS),), about=ranked))
            rows += [Row((), phrase, about=ranked) for phrase in ranking(outranked)]
            rows += _payments(ranked, lines_of)
            rows += explained(outranked.explanation, glyphs, block, own=own, over=None)
        case found:
            rows.append(Row((), unfound(found)))
    return rows


def finding(found: Finding, glyphs: Glyphs, lines_of: Lines, block: int, *, opened: bool) -> Row:
    """Build a claim's row: its mark and what was found; beneath it, its evidence.

    A failed claim with no evidence yet has it found when it is opened, at the start if `opened`.
    """
    verdict = found.verdict
    lead = (Piece(MARKS[verdict].shown(glyphs), VERDICT_ROLES[verdict]), Piece(" "))
    if verdict is not Verdict.FAIL:
        return Row(lead, judged(found))
    below = evidence(found, glyphs, lines_of, block)
    return Row(lead, judged(found), children=below, opened=opened, about=Block(block))


def refused(written: str) -> list[Row]:
    """Show a refusal the text view wrote, a line to a row."""
    return [Row((), (), ansi=line) for line in written.rstrip("\n").split("\n")]


type Diagnosed = Callable[[Fault | Internal, str | None, str], str]
"""Write a refusal as the text view does: the fault or internal error, the text, the source."""


def entry(  # noqa: PLR0913
    found: Entry,
    glyphs: Glyphs,
    lines_of: Lines,
    diagnosed: Diagnosed,
    blocks: Callable[[Finding], int],
    *,
    every: bool,
    opened: bool,
) -> Row:
    """Build a source's row: its verdict, then each claim, or what kept it from being checked.

    `every` lists the claims that passed too, as `--verbose` does; `blocks` numbers each claim's
    evidence block; `opened` opens a source that did not pass, and its failed claims.
    """
    match found.result:
        case Report() as report:
            failed = report.verdict is not Verdict.PASS
            claims = [
                finding(each, glyphs, lines_of, blocks(each), opened=opened)
                for each in report.findings
                if every or each.verdict is not Verdict.PASS
            ]
            return Row(
                (),
                reported(report),
                children=claims,
                opened=failed and opened,
                about=Source(failed),
            )
        case refusal:
            lines = refused(diagnosed(refusal, found.text, found.source))
            count = len(refusal.diagnostics) if isinstance(refusal, Fault) else 1
            return Row(
                (),
                faulted(found.source, count),
                children=lines,
                opened=False,
                about=Source(failed=True),
            )


def explaining(
    result: Explanation | Refutation | Ended, glyphs: Glyphs, *, own: str, over: Range
) -> list[Row]:
    """Build the rows of what `why` found: its explanation, the block numbered 0, or why none."""
    if isinstance(result, Explanation):
        return explained(result, glyphs, 0, own=own, over=over)
    return [Row((), unfound(result))]


def why(
    asked: str,
    result: Explanation | Refutation | Ended,
    glyphs: Glyphs,
    *,
    own: str,
    over: Range,
) -> list[Row]:
    """Build the rows of what `why` found, beneath its heading: the atom `asked`, as written."""
    below = explaining(result, glyphs, own=own, over=over)
    return [Row((), heading(Role.NOTE, WHY, asked), children=below, about=Block(0))]


def ask(
    source: str, query: All | Pattern, result: Answered | Refutation | Ended, glyphs: Glyphs
) -> list[Row]:
    """Build the rows of what `ask` found, beneath its heading.

    Each answer set that gives a value of a one-literal query can be asked `why`.
    """
    top = Row((), heading(Role.NOTE, ASK, queried(query)))
    top.children = _answered(source, query, result, glyphs)
    return [top]


def _bound(found: Answers, query: All | Pattern, mode: AnswerMode) -> list[Row]:
    """Build the rows of a query's bindings: its `yes` bindings, and the others it has."""
    shown = [each for each in ANSWERS[mode] if each is Answer.YES or found.count(each)]
    return [Row((), said(bindings_of(each, query, found))) for each in shown]


def _answered(
    source: str, query: All | Pattern, result: Answered | Refutation | Ended, glyphs: Glyphs
) -> list[Row]:
    if not isinstance(result, Answered):
        return [Row((), unfound(result))]
    if isinstance(result.answer, Answers):
        return _bound(result.answer, query, result.mode)
    conjunction = cast("All", query)
    rows = [Row((), said(answering(result.answer)))]
    alone = conjunction.parts[0] if len(conjunction.parts) == 1 else None
    for each in result.taken:
        about = None if not isinstance(alone, Literal) else Asking(alone, each.index)
        lead, phrase = _answer_set(taken(each, conjunction, result), glyphs)
        rows.append(Row(lead, phrase, about=about))
    for past in result.unreached:
        lead, phrase = _answer_set(unreached(past, conjunction), glyphs)
        rows.append(Row(lead, phrase))
    if isinstance(alone, Literal) and result.taken:
        rows.append(Row((), helped(shows_why(source, alone, result.taken[0], result.over))))
    return rows
