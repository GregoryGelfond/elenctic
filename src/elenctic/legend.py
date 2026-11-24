"""The legend of the output: how each thing a view shows is marked, styled, worded and ordered.

One table for every view, as one representation of what elenctic found. The text view paints its
phrases, the JSON view lists sets in its order, and a later view reads the same entries: a view
decides only where things go.
"""

from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum, auto
from shlex import quote
from typing import Final, TypeIs, cast

from elenctic.determination import (
    AnswerSet,
    NotThese,
    Range,
    Refutation,
    These,
    Truncation,
    Valuation,
    option,
)
from elenctic.explanation import (
    Aggregate,
    Blocked,
    Chosen,
    Counterexample,
    Derived,
    Fact,
    Minimality,
    Node,
    NoRule,
    NotChosen,
    Outranked,
    Paid,
    Reason,
    Rule,
    TheoryAtom,
    Unexpanded,
    Unexplained,
    Unsupported,
)
from elenctic.glyphs import Glyph
from elenctic.literals import Assumption, Literal, Symbol
from elenctic.paint import Phrase, Piece, Role
from elenctic.patterns import Pattern
from elenctic.query import All, Answer, Answered, Answers, Taken, Unreached
from elenctic.report import Run
from elenctic.search import Limit
from elenctic.spans import Severity, Span
from elenctic.verdicts import Ended, Finding, Report, Verdict
from elenctic.writer import bound, braces, rows

MARKS: Final[Mapping[Verdict, Glyph]] = {
    verdict: Glyph(nerd, f"[{verdict.name}]")
    for verdict, nerd in (
        (Verdict.PASS, "\uf058"),
        (Verdict.FAIL, "\uf057"),
        (Verdict.UNDECIDED, "\uf059"),
    )
}
"""The mark of a verdict on a claim: Nerd Fonts 3.5.1 `fa-check_circle`, `fa-times_circle`,
`fa-question_circle`."""

COPYRIGHT: Final = Glyph("\uf1f9", "\u00a9")
"""The mark of the copyright line: Nerd Fonts 3.5.1 `fa-copyright`, and the copyright sign."""

VERDICT_ROLES: Final[Mapping[Verdict, Role]] = {
    Verdict.PASS: Role.NOTE,
    Verdict.FAIL: Role.ERROR,
    Verdict.UNDECIDED: Role.WARNING,
}
SEVERITY_ROLES: Final[Mapping[Severity, Role]] = {
    Severity.ERROR: Role.ERROR,
    Severity.WARNING: Role.WARNING,
    Severity.NOTE: Role.NOTE,
    Severity.HELP: Role.HELP,
}
CUT_WORDS: Final[Mapping[Truncation, str]] = {
    Truncation.MAX_ANSWER_SETS: f"answer-set limit reached ({option(Truncation.MAX_ANSWER_SETS)})",
    Truncation.MAX_SECONDS: f"time limit reached ({option(Truncation.MAX_SECONDS)})",
    Truncation.INTERRUPTED: "interrupted",
}


def ended(cut: Ended) -> str:
    """Word what cut a search short."""
    unproven = "no optimum proven: " if cut.optimum_unproven else ""
    return f"{unproven}search ended: {CUT_WORDS[cut.cut]}"


def reported(report: Report) -> Phrase:
    """Word the heading of a source's findings: the source and its verdict."""
    return (
        Piece(report.source, Role.EMPHASIS),
        Piece(" — "),
        Piece(report.verdict.name, VERDICT_ROLES[report.verdict]),
    )


FAULTED: Final = "ERROR"
"""The verdict a source is shown with when it could not be checked."""


def faulted(source: str, diagnostics: int) -> Phrase:
    """Word the heading of a source that could not be checked: the source, and how many reasons."""
    return (
        Piece(source, Role.EMPHASIS),
        Piece(" — "),
        Piece(FAULTED, Role.ERROR),
        Piece(f" ({_plural(diagnostics, 'diagnostic')})", Role.REFERENCE),
    )


def judged(finding: Finding) -> Phrase:
    """Word a finding after its mark: its claim, the claim's line, and what was found."""
    detail = finding.detail
    span = finding.claim.span  # a claim is written in its case's own source
    return (
        Piece(f"{finding.claim_text} "),
        Piece(f"({_line(span, span.source)})", Role.MARGIN),
        Piece(f": {ended(detail) if isinstance(detail, Ended) else detail}"),
    )


def tally(run: Run) -> Phrase:
    """Word the summary of a run: how many sources passed, then how many did not, and why."""
    reports = [entry.result for entry in run.entries if isinstance(entry.result, Report)]
    counts = {v: sum(r.verdict is v for r in reports) for v in Verdict}
    faults = len(run.entries) - len(reports)
    rest = [
        Piece(f"{counts[v]} {v.value}", VERDICT_ROLES[v])
        for v in (Verdict.FAIL, Verdict.UNDECIDED)
        if counts[v]
    ]
    rest += [Piece(f"{faults} error", Role.ERROR)] if faults else []
    passed = Piece(f"{counts[Verdict.PASS]}/{len(run.entries)} passed", Role.EMPHASIS)
    return (passed, *(each for piece in rest for each in (Piece(", "), piece)))


def refuted(refutation: Refutation) -> str:
    """Word which assumptions clash, or that none is to blame."""
    match refutation:
        case These(core, minimal):
            shown = ", ".join(map(str, sorted(core)))
            caveat = "" if minimal else "; the search was truncated, so the core may not be minimal"
            return f"no answer set satisfies the assumptions ({shown}){caveat}"
        case NotThese():
            return "the program has no answer set, whatever is assumed"
        case _:
            return "the program has no answer set, and nothing is assumed"


def _is_row(value: object) -> TypeIs[tuple[Symbol, ...]]:
    """Say whether a value is a row of bindings: a tuple of symbols."""
    return isinstance(value, tuple) and all(
        isinstance(term, Symbol) for term in cast("tuple[object, ...]", value)
    )


def listed[T](items: Iterable[T]) -> list[T] | None:
    """List a set in its elements' own order, which every view lists it in; `None` if it has none.

    Literals and valuations have one: their symbols', so `p(2)` comes before `p(10)`; assumptions
    are ordered by literal, then sign, as a claim writes them; bindings by their symbols, in turn.
    """
    found = list(items)
    if found and all(_is_row(each) for each in found):
        return cast("list[T]", sorted(cast("list[tuple[Symbol, ...]]", found)))
    for kind in (Literal, Valuation, Assumption):
        if all(isinstance(each, kind) for each in found):
            return cast("list[T]", sorted(cast("list[Literal]", found)))
    return None


class Mark(StrEnum):
    """The kind of a line of evidence, which its glyph marks."""

    FACT = auto()
    DERIVED = auto()
    CHOSEN = auto()
    ABSENT = auto()
    AGGREGATE = auto()
    THEORY_ATOM = auto()
    SHARED = auto()
    UNEXPANDED = auto()
    OUTRANKED = auto()
    COUNTEREXAMPLE = auto()


EVIDENCE: Final[Mapping[Mark, Glyph]] = {
    mark: Glyph(nerd, plain)
    for mark, nerd, plain in (
        (Mark.FACT, "\uf1c0", ""),
        (Mark.DERIVED, "\uea8c", ""),
        (Mark.CHOSEN, "\uf074", ""),
        (Mark.ABSENT, "\uf05e", ""),
        (Mark.AGGREGATE, "\U000f04a0", ""),
        (Mark.THEORY_ATOM, "\uf1ec", ""),
        (Mark.SHARED, "\ueb36", "^"),
        (Mark.UNEXPANDED, "\uf141", "..."),
        (Mark.OUTRANKED, "\uf24e", ""),
        (Mark.COUNTEREXAMPLE, "\uf06e", ""),
    )
}
"""The mark of each kind of line of evidence: Nerd Fonts 3.5.1 `fa-database`, `cod-symbol_method`,
`fa-random`, `fa-ban`, `md-sigma`, `fa-calculator`, `cod-references`, `fa-ellipsis_h`,
`fa-balance_scale`, `fa-eye`. Most plain forms are empty: the words say it."""

_MARK_OF: Final[Mapping[type[Reason], Mark]] = {
    Derived: Mark.DERIVED,
    Chosen: Mark.CHOSEN,
    NotChosen: Mark.CHOSEN,
    Fact: Mark.FACT,
    Aggregate: Mark.AGGREGATE,
    TheoryAtom: Mark.THEORY_ATOM,
    Unexpanded: Mark.UNEXPANDED,
}
"""The mark of each kind of reason; every other kind is marked absent."""


def mark(node: Node) -> Mark:
    """Name the mark a node's line starts with."""
    return _MARK_OF.get(type(node.reason), Mark.ABSENT)


def signed(atom: object, *, negated: bool) -> str:
    """Write an atom, or its default negation: as a step writes it, and as `why` was asked it."""
    return f"not {atom}" if negated else str(atom)


def _sign(node: Node) -> str:
    """Write a node's atom, or its negation if it does not hold."""
    return signed(node.atom, negated=not node.holds)


def _signed(node: Node) -> Piece:
    return Piece(_sign(node), Role.EMPHASIS if node.holds else Role.ERROR)


def label(node: Node) -> Phrase:
    """Write what a node's line starts with: its ground rule instance, or its atom."""
    match node.reason:
        case Derived(instance=instance) | Chosen(instance=instance):
            return (Piece(instance, Role.EMPHASIS),)
        case Blocked(instance=instance) | NotChosen(instance=instance):
            return (Piece(instance),)
        case Fact():
            return (Piece(node.atom, Role.EMPHASIS),)
        case Unexpanded():
            return (Piece(_sign(node), Role.ERROR),)
        case _:
            return (_signed(node),)


def shared(node: Node) -> tuple[Phrase, Phrase]:
    """Write the label and the words of a node shown a second time."""
    return (_signed(node),), (Piece(f"shown above [{node.handle}]", Role.HELP),)


def _line(span: Span, own: str) -> str:
    """Name the line a span starts on: `line N` in the case's `own` source, else `file:N`."""
    line = span.start.line
    return f"line {line}" if span.source == own else f"{span.source}:{line}"


def _bounds(lower: int | None, upper: int | None) -> str:
    return f"{'' if lower is None else lower}..{'' if upper is None else upper}"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def words(node: Node, own: str) -> Phrase:  # noqa: PLR0911
    """Word what a node's line says of it, after its label; `own` names the case's source."""
    match node.reason:
        case Fact(rule):
            return (Piece(f"fact, {_line(rule.span, own)}", Role.REFERENCE),)
        case Derived(rule):
            return (Piece(_line(rule.span, own), Role.REFERENCE),)
        case Chosen() | NotChosen():
            return _choice(node.reason, own)
        case Aggregate(rule, _, _, _, value, guard):
            return (
                Piece(f"aggregate, {_line(rule.span, own)}:", Role.REFERENCE),
                Piece(" "),
                Piece(f"is {value}, needs {guard}", Role.ASIDE),
            )
        case TheoryAtom(_, assignment):
            verb = "holds" if node.holds else "fails"
            return (
                Piece(f"the theory {verb} under", Role.REFERENCE),
                Piece(" "),
                Piece(bound(assignment), Role.ASIDE),
            )
        case Blocked(rule, _, _, literal):
            return (
                Piece(f"{_line(rule.span, own)}:", Role.REFERENCE),
                Piece(" blocked by "),
                Piece(literal, Role.ERROR),
            )
        case _:
            return (_unfounded(node.reason, own),)


def _choice(reason: Chosen | NotChosen, own: str) -> Phrase:
    """Word a choice made, or one that could have made the atom and did not."""
    bounded = reason.lower is not None or reason.upper is not None
    of = f" of {_bounds(reason.lower, reason.upper)}" if bounded else ""
    counted = Piece(f"({reason.chosen}{of} chosen)", Role.ASIDE)
    if isinstance(reason, Chosen):
        return (
            Piece(f"chosen, {_line(reason.rule.span, own)}", Role.REFERENCE),
            Piece(" "),
            counted,
        )
    return (
        Piece(f"{_line(reason.rule.span, own)}:", Role.REFERENCE),
        Piece(" "),
        Piece("not chosen", Role.WARNING),
        Piece(" "),
        counted,
    )


def _unfounded(reason: Unsupported | NoRule | Unexpanded | Unexplained, own: str) -> Piece:
    """Word an atom no instance derives, or one the explanation stops at."""
    match reason:
        case Unsupported(candidates):
            return Piece(f"no rule fires ({_plural(candidates, 'candidate')})", Role.REFERENCE)
        case NoRule():
            return Piece("no rule instance can derive it", Role.REFERENCE)
        case Unexpanded(depth):
            return Piece(f"not expanded (depth {depth}); {_FURTHER}", Role.WARNING)
        case Unexplained(rule):
            where = "" if rule is None else f", {_line(rule.span, own)}"
            return Piece(f"not explained: no reason covers its rule yet{where}", Role.WARNING)


_FURTHER: Final = "`--max-depth` goes further"


def cited(reason: Reason) -> tuple[Rule, str] | None:
    """Name the rule a reason cites, and its substitution if it binds anything."""
    match reason:
        case (
            Derived(rule, substitution)
            | Chosen(rule, substitution)
            | NotChosen(rule, substitution)
            | Blocked(rule, substitution)
            | Aggregate(rule, substitution)
        ):
            return rule, "" if not substitution.bindings else str(substitution)
        case Fact(rule):
            return rule, ""
        case _:
            return None


def answer_set(index: int, read: int | None, over: Range = Range.ALL) -> str:
    """Name an answer set by its index among those read, of all or of the optima."""
    of = f" of {read}" if read is not None else ""
    return f"{'optimal ' if over is Range.OPTIMAL else ''}answer set {index}{of}"


def _shown(head: str, found: AnswerSet) -> Phrase:
    """Word an answer set after its name: what it shows, and the assignment it carries."""
    phrase = (Piece(head, Role.EMPHASIS), Piece(f": {braces(found.shown)}"))
    if not found.assignment:
        return phrase
    return (*phrase, Piece(" "), Piece(f"where {bound(found.assignment)}", Role.ASIDE))


def counterexample(found: Counterexample, over: Range | None) -> Phrase:
    """Word the answer set explained: one asked for `over` a range, else one a claim fails in."""
    named = answer_set(found.index, found.read, Range.ALL if over is None else over)
    return _shown(named if over is not None else f"counterexample: {named}", found.answer_set)


WHY: Final = "why"
"""The heading of what `why` explains."""
ASK: Final = "ask"
"""The heading of what `ask` answers."""
ANSWER: Final = "answer"

KEYS: Final[Mapping[str, str]] = {
    "up": "up",
    "down": "down",
    "open": "open",
    "close": "close",
    "go": "go to",
    "spans": "spans",
    "deeper": "deeper",
    "find": "find",
    "next": "next",
    "failures": "failures only",
    "every": "explain all",
    "keys": "keys",
    "back": "back",
    "quit": "quit",
}
"""The words of the interactive view's keys, by the action each one takes."""
PRESSED: Final[Mapping[str, str]] = {
    "up": "↑ k",
    "down": "↓ j",
    "open": "→ l",
    "close": "← h",
    "go": "enter",
    "spans": "s",
    "deeper": "+",
    "find": "/",
    "next": "n",
    "failures": "f",
    "every": "e",
    "keys": "?",
    "back": "esc",
    "quit": "q",
}
"""The keys of the interactive view as they are shown, by the action each one takes."""
CHROME: Final[Mapping[str, Role]] = {
    "frame": Role.MARGIN,
    "key": Role.HELP,
}
"""The roles of the interactive view's own parts: the pane's border, and a key. The guides are
drawn as the text view draws them, plain. The selected row takes no role: it is shown reversed, as
a terminal shows a selection, so each of its pieces reads as well as it does unselected and keeps
its own role's colour. The scrollbars are drawn quietly, in the terminal's grey."""


def titled(command: str, subject: str) -> Phrase:
    """Word the title of the interactive view: the command, and what it was asked of."""
    return (Piece(f"elenctic {command}", Role.EMPHASIS), Piece(f" · {subject}"))


FIND: Final = "find a literal"
"""The prompt of the interactive view's search."""
NOT_FOUND: Final = "not found"
NOTHING_DEEPER: Final = "no branch stops at its depth: there is nothing deeper"
"""What the interactive view says when asked to go deeper than a complete explanation."""
BENEATH: Final = "first step beneath:"
"""What the pane says above a rule cited below the selected row, when that row cites none."""
NO_STEP: Final = "no rule is cited here or beneath"
SEARCHING: Final = "searching"
"""What the interactive view shows while the library looks for more, until it finds it or `esc`."""
CANCELLED: Final = "search cancelled"
PENDING: Final[Phrase] = (
    Piece(SEARCHING, Role.ASIDE),
    Piece(" · "),
    Piece(PRESSED["back"], CHROME["key"]),
    Piece(" cancels"),
)
"""The title's note while the library looks for more: what it does, and the key that stops it."""


def keyed(actions: Sequence[str]) -> tuple[Phrase, ...]:
    """Word the keys of the interactive view, a line for each action: its key, then what it does."""
    width = max((len(PRESSED[action]) for action in actions), default=0)
    return tuple(
        (Piece(f"{PRESSED[action]:<{width}}", CHROME["key"]), Piece(f"  {KEYS[action]}"))
        for action in actions
    )


def answering(answer: Answer) -> Phrase:
    """Word the answer a query comes to over the answer sets."""
    return (Piece(ANSWER, Role.EMPHASIS), Piece(f": {worded(answer)}"))


def worded(answer: Answer) -> str:
    """Word an answer as it is said, `not entailed`, not as JSON names it."""
    return answer.value.replace("_", " ")


def taken(found: Taken, query: All, answered: Answered) -> Phrase:
    """Word an answer a query takes in one answer set alone, and the first that gives it."""
    named = answer_set(found.index, answered.read, answered.over)
    return _shown(f"{_valued(found.answer, query)} in {named}", found.answer_set)


def unreached(found: Unreached, query: All) -> Phrase:
    """Word an answer a query takes in some answer set alone, past those the search read."""
    return (
        Piece(
            f"{_valued(found.answer, query)} in an answer set past the {found.read} read",
            Role.EMPHASIS,
        ),
        Piece(": "),
        Piece(ended(Ended(found.cut)), Role.WARNING),
    )


def _valued(answer: Answer, query: All) -> str:
    """Word the truth that gives `answer` in one answer set: of the query's literal, if alone."""
    match answer, query.parts:
        case Answer.YES, _:
            return "true"
        case Answer.NO, _:
            return "false"
        case _, (Literal() as alone,):
            return f"neither {alone} nor {alone.contrary}"
        case _:
            return "neither true nor false"


def bindings_of(answer: Answer, query: Pattern | All, found: Answers) -> Phrase:
    """Word the bindings of a query that give one answer, as `@query … = { … }` writes them."""
    return (
        Piece(f"{worded(answer)} bindings", Role.EMPHASIS),
        Piece(f": {rows(query, found.giving(answer))}"),
    )


def shows_why(source: str, literal: Literal, found: Taken, over: Range) -> str:
    """Word the help on asking `why` of the answer set a query was answered in, for a shell."""
    optimal = " --over optimal" if over is Range.OPTIMAL else ""
    asked = (
        f"elenctic why {quote(source)} {quote(str(literal))} --answer-set {found.index}{optimal}"
    )
    return f"`{asked}` shows why"


EXPECTS_NONE: Final = "the program has this answer set, and the claim expects none"

GUARANTEE: Final[Mapping[Minimality, str]] = {Minimality.NONE: "support is sound, not minimal"}
"""How an explanation's note words what it guarantees about its size."""


def stopped(max_depth: int | Limit) -> str:
    """Word the note on an explanation whose branches stop at its depth."""
    return f"some branches stop at depth {max_depth}; {_FURTHER}"


def heading(role: Role, word: str, subject: str) -> Phrase:
    """Word the opening of a block: what kind it is, in `role`, and what it is about."""
    return (Piece(word, role), Piece(": "), Piece(subject, Role.EMPHASIS))


def said(phrase: Phrase) -> Phrase:
    """Word a line that says something of the whole block."""
    return (Piece("=", Role.MARGIN), Piece(" "), *phrase)


def noted(words: str) -> Phrase:
    """Word a note on a block."""
    return (Piece(f"= {Severity.NOTE.value}:", Role.NOTE), Piece(f" {words}"))


def helped(words: str) -> Phrase:
    """Word a help on a block: what to run or write next."""
    return (Piece(f"= {Severity.HELP.value}:", Role.HELP), Piece(f" {words}"))


def unfound(result: Refutation | Ended) -> Phrase:
    """Word why there is nothing to show: the search ended, or there is no answer set."""
    if isinstance(result, Ended):
        return said((Piece(ended(result), Role.WARNING),))
    return said((Piece(REFUTATION, Role.EMPHASIS), Piece(f": {refuted(result)}")))


def written(rule: Rule, substitution: str) -> Phrase:
    """Word a rule as written, on one line, after its place, and the substitution of a step."""
    where = Piece(f"= {rule.span.source}:{rule.span.start.line}:", Role.REFERENCE)
    phrase = (where, Piece(f" {' '.join(rule.text.split())}"))
    return (*phrase, Piece(" "), Piece(substitution, Role.ASIDE)) if substitution else phrase


EVIDENCE_HEADING: Final = "evidence"
REFUTATION: Final = "refutation"
OUTRANKED: Final = "outranked: the objective ranks it below the optimum"
COST: Final = "cost"
OPTIMUM: Final = "optimum"


def assuming(literals: str) -> str:
    """Name the row of costs under the literals an objective outranks."""
    return f"assuming {literals}"


def priority(level: int) -> str:
    """Name a priority of an objective."""
    return f"priority {level}"


def possible(literals: str) -> str:
    """Word that some answer set has the literals an objective outranks."""
    return f"{literals} is possible: some answer set has it, the objective aside"


def differs(level: int) -> str:
    """Word the priority at which two costs first differ."""
    return f"first differs at {priority(level)}"


PAID: Final = "weak constraints paid differently:"


def paid(payment: Paid, *, more: bool) -> Phrase:
    """Word a weak-constraint instance paid by one side only: `more` by the outranked one."""
    phrase = (Piece(f"{'+' if more else '-'}{payment.weight} at {priority(payment.priority)}"),)
    if not payment.substitution.bindings:
        return phrase
    return (*phrase, Piece(" "), Piece(str(payment.substitution), Role.ASIDE))


_CELL: Final = 12
"""The width of a column of the table of costs."""


def ranking(outranked: Outranked) -> tuple[Phrase, ...]:
    """Word how the objective ranks the literals: that they are possible, then the costs compared.

    The costs are a table: one column per priority, the one they first differ at in color.
    """
    literals = ", ".join(map(str, listed(outranked.literals) or ()))
    pad = len(assuming(literals)) + 2
    cells = "".join(f"{priority(p):>{_CELL}}" for p in outranked.priorities)

    def row(name: str, cost: tuple[int, ...], role: Role) -> Phrase:
        cost_cells = (
            Piece(f"{v:>{_CELL}}", role if p == outranked.priority else Role.EMPHASIS)
            for p, v in zip(outranked.priorities, cost, strict=False)
        )
        return (Piece(f"  {name:<{pad}}"), *cost_cells)

    return (
        (Piece("1", Role.MARGIN), Piece(f" {possible(literals)}")),
        (Piece("2", Role.MARGIN), Piece(f" {COST:<{pad}}{cells}")),
        row(assuming(literals), outranked.assuming, Role.ERROR),
        (
            *row(OPTIMUM, outranked.optimum, Role.NOTE),
            Piece("  "),
            Piece(differs(outranked.priority), Role.ASIDE),
        ),
        (Piece("3", Role.MARGIN), Piece(f" {PAID}")),
    )


def _located(span: Span) -> Phrase:
    """Word where a span starts, as an arrow to it."""
    return (Piece(f" --> {span.source}:{span.start.line}:{span.start.column}", Role.MARGIN),)


def quoted(span: Span, lines: Sequence[str], role: Role, said: Phrase = ()) -> tuple[Phrase, ...]:
    """Quote the line a span starts on, with carets in `role` under the span, and what is `said`.

    Nothing if the line is not among `lines`.
    """
    if not 1 <= span.start.line <= len(lines):
        return ()
    number = str(span.start.line)
    pad = " " * len(number)
    after = (Piece(" "), *said) if said else ()
    before, carets = underlined(span)
    return (
        (Piece(f"{pad} |", Role.MARGIN),),
        (Piece(f"{number} |", Role.MARGIN), Piece(f" {lines[span.start.line - 1]}")),
        (Piece(f"{pad} |", Role.MARGIN), Piece(f" {before}"), Piece(carets, role), *after),
    )


def underlined(span: Span) -> tuple[str, str]:
    """Underline the line a span starts on: the spaces before its carets, and the carets.

    A span over several lines is marked by one caret where it starts.
    """
    width = max(1, span.end.column - span.start.column) if span.end.line == span.start.line else 1
    return " " * (span.start.column - 1), "^" * width


def paying(payment: Paid, lines: Sequence[str] | None, *, more: bool) -> tuple[Phrase, ...]:
    """Word a weak-constraint instance one side pays: where its rule is, quoted when it can be."""
    span = payment.rule.span
    said = paid(payment, more=more)
    found = quoted(span, lines or (), Role.ERROR if more else Role.NOTE, said)
    if found:
        return (_located(span), *found)
    return (
        _located(span),
        (Piece("  "), Piece("|", Role.MARGIN), Piece(f" {payment.rule.text} "), *said),
    )
