"""Read a program's statements into clauses, and write the relaxation that finds their instances.

Grounding the relaxation (the program without negative literals, theory atoms and constraints)
finds every ground instance whose body might hold, which the grounder of the program itself may
have simplified away. Each instance is recorded with what its body literals and guards ground to,
so the answer set it is judged in only needs to be looked up.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from clingo.ast import (
    AST,
    ASTType,
    Sign,
)

from elenctic import tree
from elenctic.clauses import (
    Clause,
    Form,
    Guard,
    Head,
    Kind,
    Part,
    Weak,
    anonymous_named,
    global_names_in,
    guard_terms,
    is_positive,
    is_relaxed,
    names_in,
    read_condition,
    read_heads,
    read_part,
    slot_term,
    tuple_text,
)
from elenctic.explanation import Rule
from elenctic.program import named
from elenctic.spans import Position, Span, in_characters, split_lines

_BASE: Final = "_elenctic"
_FRESH: Final = "_E"


@dataclass(frozen=True, slots=True)
class Source:
    """The text of each source a program reads, by the name clingo reports it under."""

    name: str
    texts: Mapping[str, str]

    def span(self, statement: AST) -> Span:
        """Locate a statement, in Unicode columns, under the name the program is known by."""
        reported = tree.span(statement)
        raw = named(reported, self.name)
        text = self.texts.get(reported.source, self.texts.get(raw.source))
        return raw if text is None else in_characters(raw, text)

    def text(self, span: Span) -> str:
        """Return the source text a span covers, or `""` when the source is not at hand."""
        text = self.texts.get(span.source)
        if text is None:
            return ""
        lines = split_lines(text)
        if not 1 <= span.start.line <= span.end.line <= len(lines):
            return ""
        if span.start.line == span.end.line:
            return lines[span.start.line - 1][span.start.column - 1 : span.end.column - 1]
        first = lines[span.start.line - 1][span.start.column - 1 :]
        middle = lines[span.start.line : span.end.line - 1]
        last = lines[span.end.line - 1][: span.end.column - 1]
        return "\n".join([first, *middle, last])


def _apart(written: str, base: str) -> str:
    """Lengthen `base` with leading underscores until the program's text does not contain it."""
    name = base
    while name in written:
        name = "_" + name
    return name


@dataclass(slots=True)
class Reading:
    """A program's statements read into clauses and weak constraints, before grounding."""

    prefix: str
    """What the names of the predicates the relaxation adds begin with."""
    fresh: str
    """What the names of the variables the relaxation adds begin with."""
    clauses: list[Clause] = field(default_factory=list[Clause])
    weak: list[Weak] = field(default_factory=list[Weak])
    relaxation: list[str] = field(default_factory=list[str])
    """The relaxed program and the rules that record each instance, as text."""
    solving: list[str] = field(default_factory=list[str])
    """The rules added to the program itself: the weak-constraint instances each answer set pays."""
    pieces: int = 0

    @property
    def rule(self) -> str:
        return f"{self.prefix}_rule"

    @property
    def element(self) -> str:
        return f"{self.prefix}_element"

    @property
    def paid(self) -> str:
        return f"{self.prefix}_paid"

    @property
    def bind(self) -> str:
        return f"{self.prefix}_bind"

    @property
    def theory(self) -> str:
        return f"{self.prefix}_theory"


_KEPT: Final = frozenset(
    {ASTType.Program, ASTType.Definition, ASTType.Defined, ASTType.External, ASTType.Script}
)


def _minimize_rules(statements: Sequence[AST], source: Source) -> dict[int, Rule]:
    """Locate each element of a `#minimize`: clingo starts every element where the first does."""
    rules: dict[int, Rule] = {}
    previous: dict[tuple[str, int, int], Position] = {}
    for index, statement in enumerate(statements):
        if tree.kind(statement) is not ASTType.Minimize:
            continue
        span = source.span(statement)
        key = (span.source, span.start.line, span.start.column)
        start = previous.get(key, span.start)
        start = _after_separator(source, Span(span.source, start, span.end))
        element = Span(span.source, start, span.end)
        rules[index] = Rule(index, element, source.text(element))
        previous[key] = span.end
    return rules


def _after_separator(source: Source, span: Span) -> Position:
    """Skip the `;` and blanks that separate an element from the one before it."""
    text = source.texts.get(span.source)
    if text is None:
        return span.start
    lines = split_lines(text)
    line, column = span.start.line, span.start.column
    while line <= len(lines):
        rest = lines[line - 1][column - 1 :]
        stripped = rest.lstrip("; \t")
        if stripped:
            return Position(line, column + len(rest) - len(stripped))
        line, column = line + 1, 1
    return span.start


def read(statements: Sequence[AST], source: Source) -> Reading:
    """Read statements into clauses and weak constraints, and the relaxation that grounds them."""
    written = "\n".join(str(statement) for statement in statements)
    reading = Reading(_apart(written, _BASE), _apart(written, _FRESH))
    minimized = _minimize_rules(statements, source)
    for index, statement in enumerate(statements):
        match tree.kind(statement):
            case ASTType.Rule:
                span = source.span(statement)
                rule = Rule(index, span, source.text(span))
                for piece in statement.unpool():
                    _read_rule(reading, rule, anonymous_named(piece, reading.fresh))
            case ASTType.Minimize:
                _read_weak(reading, minimized[index], statement)
            case kind if kind in _KEPT:
                reading.relaxation.append(str(statement))
            case _:
                pass
    return reading


def _read_weak(reading: Reading, rule: Rule, statement: AST) -> None:
    variables = tuple(names_in(statement, reading.fresh))
    number = len(reading.weak)
    reading.weak.append(Weak(rule, variables))
    weight, priority = tree.child(statement, "weight"), tree.child(statement, "priority")
    terms = tuple_text(str(term) for term in tree.children(statement, "terms"))
    body = ", ".join(str(literal) for literal in tree.children(statement, "body"))
    head = f"{reading.paid}({number},{tuple_text(variables)},{weight},{priority},{terms})"
    reading.solving.append(f"{head} :- {body}." if body else f"{head}.")


def _read_rule(reading: Reading, rule: Rule, piece: AST) -> None:
    heads = read_heads(tree.child(piece, "head"))
    if heads is None:
        return
    literals = tree.children(piece, "body")
    body, relaxed, readable = _body(literals)
    form, derived, bounds, clear = heads
    reading.relaxation.append(_relaxed_rule(piece, relaxed))
    read = _Piece(
        reading,
        rule,
        piece,
        reading.pieces,
        Form.FACT if form is Form.RULE and not literals else form,
        body,
        relaxed,
        tuple(global_names_in(piece, reading.fresh)),
        bounds,
        readable=readable and clear,
    )
    reading.pieces += 1
    for each in derived:
        _clause(read, each)
    for at, part in enumerate(body):
        if part.kind is Kind.AGGREGATE:
            _elements(read, at, part)
        elif part.kind is Kind.THEORY:
            reading.solving.append(_theory_rule(read, at, part))


def _body(literals: Sequence[AST]) -> tuple[tuple[Part, ...], list[str], bool]:
    """Read a body into its parts, the literals the relaxation keeps, and whether all were read."""
    parts = [read_part(literal) for literal in literals]
    body = tuple(part for part in parts if part is not None)
    kept = [
        str(literal)
        for literal, part in zip(literals, parts, strict=True)
        if part is None and is_positive(literal)
    ]
    relaxed = [str(part.node) for part in body if is_relaxed(part)] + kept
    return body, relaxed, len(body) == len(parts)


@dataclass(frozen=True, slots=True)
class _Piece:
    """One pool-free piece of a rule as it is read: what each of its clauses shares."""

    reading: Reading
    rule: Rule
    statement: AST
    number: int
    form: Form
    body: tuple[Part, ...]
    relaxed: list[str]
    shared: tuple[str, ...]
    bounds: tuple[Guard, ...]
    readable: bool

    def record(self, head: str, support: Sequence[str]) -> None:
        """Add a rule to the relaxation that records `head` wherever `support` may hold."""
        body = [*self.relaxed, *support]
        self.reading.relaxation.append(f"{head} :- {', '.join(body)}." if body else f"{head}.")


def _relaxed_rule(piece: AST, relaxed: list[str]) -> str:
    """Write the rule as the relaxation has it: the same head, the relaxed body."""
    head = str(tree.child(piece, "head"))
    return f"{head} :- {', '.join(relaxed)}." if relaxed else f"{head}."


def _derives(literal: AST) -> bool:
    """Say whether a head literal derives an atom: a symbolic atom, without a sign."""
    return (
        tree.kind(literal) is ASTType.Literal
        and tree.number(literal, "sign") == Sign.NoSign
        and tree.kind(tree.child(literal, "atom")) is ASTType.SymbolicAtom
    )


def _clause(piece: _Piece, head: Head) -> None:
    """Read the clause for one atom a piece's head derives, and record its instances."""
    if not _derives(head.literal):
        return
    conditions = [read_condition(c) for c in head.condition]
    condition = tuple(c for c in conditions if c is not None)
    reading = piece.reading
    fresh = reading.fresh
    written = names_in(head.literal, fresh) + [
        n for c in head.condition for n in names_in(c, fresh)
    ]
    local = [name for name in written if name not in piece.shared]
    clause = Clause(
        len(reading.clauses),
        piece.number,
        piece.rule,
        piece.form,
        piece.shared + tuple(dict.fromkeys(local)),
        len(piece.shared),
        head.literal,
        condition,
        piece.body,
        piece.readable and len(condition) == len(conditions),
        piece.statement,
        piece.bounds,
    )
    reading.clauses.append(clause)
    _record_clause(piece, clause)


def _record_clause(piece: _Piece, clause: Clause) -> None:
    """Record each instance of a clause; one it cannot read is recorded wherever its atom holds."""
    reading = piece.reading
    atom = str(tree.child(tree.child(clause.head, "atom"), "symbol"))
    if not clause.readable:
        reading.relaxation.append(f"{reading.rule}({clause.number},(),{atom},(),(),()) :- {atom}.")
        return
    guards = guard_terms(tree.child(piece.statement, "head")) if piece.bounds else "()"
    body = tuple_text(slot_term(p) for p in piece.body)
    condition = tuple_text(slot_term(c) for c in clause.condition)
    values = tuple_text(clause.variables)
    recorded = f"{reading.rule}({clause.number},{values},{atom},{body},{condition},{guards})"
    piece.record(recorded, [str(c.node) for c in clause.condition if is_relaxed(c)])


def _named_apart(element: AST, shared: Sequence[str], fresh: str) -> AST:
    """Name an element's own variables apart from the rule's, as clingo does.

    The rule that records an element has them outside the aggregate, where they would be the rule's.
    """
    kept = frozenset(shared)
    return tree.renamed(element, lambda name: name if name in kept else f"{fresh}L{name}")


def _elements(piece: _Piece, at: int, part: Part) -> None:
    """Record each element an instance's aggregate could count, and what its condition grounds to.

    Its own variables are renamed apart, as `_named_apart` says.
    """
    atom = tree.child(part.node, "atom")
    shared = tuple_text(piece.shared)
    for index, element in enumerate(tree.children(atom, "elements")):
        renamed = _named_apart(element, piece.shared, piece.reading.fresh)
        terms = tuple_text(str(term) for term in tree.children(renamed, "terms"))
        condition = [c for c in map(read_condition, tree.children(renamed, "condition")) if c]
        slots = tuple_text(slot_term(c) for c in condition)
        recorded = f"{piece.reading.element}({piece.number},{shared},{at},{index},{terms},{slots})"
        piece.record(recorded, [str(c.node) for c in condition if is_relaxed(c)])


def _theory_rule(piece: _Piece, at: int, part: Part) -> str:
    """Write the rule that records, in each answer set, whether an instance's theory atom holds."""
    reading, key = piece.reading, f"{piece.number},{tuple_text(piece.shared)}"
    atom = tree.child(part.node, "atom")
    return f"{reading.theory}({key},{at}) :- {reading.bind}({key}), {atom}."
