"""The legend of the output: how each thing a view shows is marked, styled, worded and ordered.

One table for every view, as one representation of what elenctic found. The text view paints its
phrases, the JSON view lists sets in its order, and a later view reads the same entries: a view
decides only where things go.
"""

from collections.abc import Iterable, Mapping
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
from elenctic.query import All, Answer, Answered, Bindings, Taken
from elenctic.report import Run
from elenctic.search import Limit
from elenctic.spans import Severity
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


def judged(finding: Finding) -> Phrase:
    """Word a finding after its mark: its claim, the claim's line, and what was found."""
    detail = finding.detail
    return (
        Piece(f"{finding.claim_text} "),
        Piece(f"({_line(finding)})", Role.MARGIN),
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


def _sign(node: Node) -> str:
    """Write a node's atom, or its negation if it does not hold."""
    return node.atom if node.holds else f"not {node.atom}"


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


def _line(rule: Rule | Finding) -> str:
    """Name the line a rule, or a finding's claim, starts on."""
    span = rule.span if isinstance(rule, Rule) else rule.claim.span
    return f"line {span.start.line}"


def _bounds(lower: int | None, upper: int | None) -> str:
    return f"{'' if lower is None else lower}..{'' if upper is None else upper}"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def words(node: Node) -> Phrase:  # noqa: PLR0911
    """Word what a node's line says of it, after its label."""
    match node.reason:
        case Fact(rule):
            return (Piece(f"fact, {_line(rule)}", Role.REFERENCE),)
        case Derived(rule):
            return (Piece(_line(rule), Role.REFERENCE),)
        case Chosen() | NotChosen():
            return _choice(node.reason)
        case Aggregate(rule, _, _, _, value, guard):
            return (
                Piece(f"aggregate, {_line(rule)}:", Role.REFERENCE),
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
                Piece(f"{_line(rule)}:", Role.REFERENCE),
                Piece(" blocked by "),
                Piece(literal, Role.ERROR),
            )
        case _:
            return (_unfounded(node.reason),)


def _choice(reason: Chosen | NotChosen) -> Phrase:
    """Word a choice made, or one that could have made the atom and did not."""
    bounded = reason.lower is not None or reason.upper is not None
    of = f" of {_bounds(reason.lower, reason.upper)}" if bounded else ""
    counted = Piece(f"({reason.chosen}{of} chosen)", Role.ASIDE)
    if isinstance(reason, Chosen):
        return (Piece(f"chosen, {_line(reason.rule)}", Role.REFERENCE), Piece(" "), counted)
    return (
        Piece(f"{_line(reason.rule)}:", Role.REFERENCE),
        Piece(" "),
        Piece("not chosen", Role.WARNING),
        Piece(" "),
        counted,
    )


def _unfounded(reason: Unsupported | NoRule | Unexpanded | Unexplained) -> Piece:
    """Word an atom no instance derives, or one the explanation stops at."""
    match reason:
        case Unsupported(candidates):
            return Piece(f"no rule fires ({_plural(candidates, 'candidate')})", Role.REFERENCE)
        case NoRule():
            return Piece("no rule instance can derive it", Role.REFERENCE)
        case Unexpanded(depth):
            return Piece(f"not expanded (depth {depth}); {_FURTHER}", Role.WARNING)
        case Unexplained(rule):
            where = "" if rule is None else f", {_line(rule)}"
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


def counterexample(found: Counterexample, *, failed: bool, over: Range) -> Phrase:
    """Word the answer set explained: the one a claim fails in, or the one asked for by `over`."""
    named = answer_set(found.index, found.read, over)
    return _shown(f"counterexample: {named}" if failed else named, found.answer_set)


WHY: Final = "why"
"""The heading of what `why` explains."""
ASK: Final = "ask"
"""The heading of what `ask` answers."""
ANSWER: Final = "answer"


def taken(found: Taken, query: All, answered: Answered) -> Phrase:
    """Word an answer a query takes in one answer set alone, and the first that gives it."""
    named = answer_set(found.index, answered.read, answered.over)
    match found.answer, query.parts:
        case Answer.YES, _:
            value = "true"
        case Answer.NO, _:
            value = "false"
        case _, (Literal() as alone,):
            value = f"neither {alone} nor {alone.contrary}"
        case _:
            value = "neither true nor false"
    return _shown(f"{value} in {named}", found.answer_set)


def bindings_of(answer: Answer, pattern: Pattern, found: Bindings) -> Phrase:
    """Word the bindings of a pattern that give one answer, as `@query … = { … }` writes them."""
    return (
        Piece(f"{answer.value} bindings", Role.EMPHASIS),
        Piece(f": {rows(pattern, found.giving(answer))}"),
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
