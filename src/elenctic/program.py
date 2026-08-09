"""Resolved-program inspection — the program-level facts read from the *resolved* AST (the case file
plus its ``#include``s), the shared fix vector for theory-presence detection and the
preconditions over the resolved program.

One ``clingo.ast.parse_files`` pass: ``parse_files`` resolves
``#include`` relative to the including file and exposes the included nodes in the AST, so the
case-file-text regex scan (which the migration of ``#show``/``#minimize`` into libraries would
defeat) is retired. Theory **presence** only — never identity (the gate is theory-agnostic).
Principle: *contract-level facts read the case file; program-level facts read the resolved program.*
"""

import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryFile
from threading import Lock
from typing import IO, Final

from clingo import SymbolType
from clingo.ast import AST, ASTType, UnaryOperator, parse_files as _parse_files

from elenctic.terms import Signature

__all__ = [
    "Boundary",
    "ContainmentError",
    "Diagnostics",
    "ProgramError",
    "ProgramFacts",
    "Restricted",
    "ShownVocabulary",
    "Unrestricted",
    "captured_diagnostics",
    "inspect",
    "refuse_strangers",
]


@dataclass(frozen=True, slots=True)
class Boundary:
    """The directory a case's program may not reach past, and why it is where it is.

    A value rather than a bare path because the rule is enforced in two frames — the one that judges
    the files a completed parse resolved, and the one that judges the diagnostics a failed parse
    left behind — and which of them a reader meets is decided by whether the escaping file happened
    to parse. Everything they say about the boundary therefore has to come from one place, or the
    same mistake gets a better explanation on the luckier path.

    ``from_named_file`` says the run was pointed at one case rather than at a directory.

    **What the rule is against, so that its limit is legible.** A corpus is untrusted *content* — it
    is cloned, or it arrives in a pull request — and the rule keeps that content from reading files
    the run was never pointed at. It is not a defence against a tree being changed *while the run is
    in progress*: a case's sources are judged when it is discovered, and a case whose files are
    swapped after that reaches the solver carrying facts this rule never saw. The boundary travels
    as far as the solve because a diagnostic is written there, and because a caller that grounds
    without discovering first would otherwise have no rule at all — not because the resolved sources
    are judged a second time.

    ``root`` must already be **resolved**, and that is refused rather than assumed. Containment
    compares a resolved candidate against this path, so a root still carrying a symlink or a ``..``
    fails that comparison for every file in the corpus — including the case's own — and the corpus
    is told it is reading from outside itself. The refusal is here because it is the only place that
    knows; by the time the comparison fails, the mistake looks like an escape."""

    root: Path
    from_named_file: bool = False

    def __post_init__(self) -> None:
        """Refuse a root that is not already resolved (see the class docstring)."""
        if self.root != (resolved := self.root.resolve()):
            raise ValueError(
                f"a containment boundary is stated as a resolved path; {self.root} resolves to "
                f"{resolved}, and comparing against the unresolved spelling reports every file "
                "in the corpus as outside it"
            )

    def refusal(self, escaped: list[str]) -> str:
        """What a case that loads ``escaped`` is told — the rule, and where the boundary came from
        when a reader would not have predicted it."""
        because = (
            " The boundary is that directory and not a wider one because you named a single case, "
            "and a file names no corpus to take as the root; run the corpus directory itself to "
            "make the tree around it reachable."
            if self.from_named_file
            else ""
        )
        return (
            f"this case loads {', '.join(escaped)}, which is outside the corpus at {self.root}. "
            "A case may only include files from the corpus it belongs to — a corpus is run as "
            f"given, so an include reaching past it would read a file the run was never pointed "
            f"at.{because}"
        )


class ProgramError(Exception):
    """A program under test that elenctic cannot run — a missing or cyclic ``#include``, a parse
    error, or a program that will not ground. Surfaced as a friendly diagnostic carrying clingo's
    own account of what is wrong, never a raw stack trace.

    It does not name the file, and that is not a gap: whoever called :func:`inspect` or a solver
    facade passed the files in, and clingo's diagnostic carries the ``file:line:col`` of the
    offending one — which a join of the inputs never did. Where the fault is recorded rather than
    raised, :class:`~elenctic.outcome.ErrorRecord` holds the file as a field.

    A fault in the program, so its author fixes the ``.lp``; deliberately **not** a
    ``HarnessError``, which claims elenctic violated one of its own invariants and should be
    reported. The two are disjoint roots so that neither can be caught as the other, and neither is
    ever a verdict about the program's answer-set behaviour."""


class ContainmentError(ProgramError):
    """A case that loads a file from outside the corpus it belongs to.

    Its own class because it is its own locus, and because one rule met at two moments must not
    read as two problems. Whether the escaping file *parses* decides which frame notices — the
    sources a completed parse resolved, or the diagnostics a failed one left behind — and that is an
    accident of the offending file's syntax, not a difference the author has any use for. Reported
    as two kinds it would need two buckets in a consumer's report and a rule for merging them; this
    package has made that mistake once already, when one broken ``#include`` was announced as a case
    fault or a program fault depending on which phase walked into it.

    A ``ProgramError`` by inheritance so that every register already catching that family keeps
    catching this, and so the discovery layer can raise it without either layer importing the
    other's errors. What a reader is told is the *locus*, which
    :func:`~elenctic.outcome.error_kind` reads from the class ahead of the family."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Unrestricted:
    """The program declares no output restriction, so every literal of every answer set reaches
    the output.

    A program reaches this state by carrying no ``#show`` directive at all, or by carrying only
    directives of the ``#show <term> : <body>.`` form — which display a term without switching the
    solver into selective output (measured; see :func:`inspect`).

    ``displayed`` is carried here for the same reason it is carried below, and the reason is that
    *unrestricted is not the same as faithful*: the output contains every literal of the answer set,
    and it may also contain terms that are in no answer set at all."""

    displayed: frozenset[Signature] = frozenset()


@dataclass(frozen=True, slots=True, kw_only=True)
class Restricted:
    """The program restricts its output, and ``signatures`` is what it declares observable.

    An empty ``signatures`` is *show nothing*: a program whose only declaration is a bare
    ``#show.``. That is the opposite of :class:`Unrestricted`, and keeping the two apart is the
    whole reason this is an alternative rather than a set — under one every literal is readable and
    under the other none is, and a set has the same emptiness for both.

    ``displayed`` holds the signatures named by a ``#show <term> : <body>.`` directive, which is
    **not** the same as declaring one observable, and is not weaker than it either — it is a
    different thing in two directions. Such a directive emits its term where the body holds, so the
    predicate is visible for some ground instances and not others; and the term it emits need not be
    an atom of the program at all, so the output can carry a symbol no answer set contains. A
    reading over such a signature is therefore not a projection of the answer set in either
    direction, which is why the two sets are kept apart rather than merged.

    Built by keyword: the fields are adjacent and share a type, so transposed they would type-check
    clean and read as a plausible vocabulary while meaning the reverse of what was written."""

    signatures: frozenset[Signature]
    displayed: frozenset[Signature] = frozenset()


type ShownVocabulary = Unrestricted | Restricted
"""What a program's ``#show`` directives make of its output — whether they restrict it, to what, and
which signatures they display rather than declare."""


@dataclass(frozen=True, slots=True)
class ProgramFacts:
    """The program-level facts the preconditions and the theory gate read.

    ``has_theory_atom`` — any ``&``-atom in the resolved program (presence, not identity).
    ``shown`` — the :data:`ShownVocabulary`: what the program makes observable, keyed by full
    sign-aware signature rather than by name, so a literal ``#show``n at the wrong arity is a
    *loud* precondition failure and not a silent miss. ``has_optimization`` — a ``#minimize``,
    ``#maximize``, or ``:~`` is present. ``has_maximize`` — an objective uses ``#maximize`` (a
    negated-weight ``Minimize`` node), which v1 cannot present a natural ``@cost`` over (the
    guarded miscompile).
    ``has_projection`` — a ``#project`` directive is present. Presence, not identity, for the same
    reason the theory-atom gate reads presence: what matters is that the program narrows the
    solver's own projection, and elenctic cannot tell from a parse whether the narrowing reaches
    below what a reading consults.
    ``has_theory_optimization`` — a *theory-native* objective (``&minimize``/``&maximize``) is
    present. It is tracked apart from ``has_optimization`` because it is a different object: the
    theory's own propagator drives it, so clingo's optimization switches do not reach it, and a
    reading of AS(P) cannot be made honest by turning them off.
    ``sources`` — the resolved source files the program spans: the case file plus every file it
    transitively ``#include``s, taken from clingo's own parse (each statement's ``location``), so it
    matches clingo's include resolution exactly (block comments, every include form). The corpus
    orphan-library backstop reads this rather than re-scanning text; only a *truly empty*
    included library (no statements — a comment-only file still yields ``Comment`` nodes) is absent
    and so over-reported as an orphan, the safe direction for a warn-only check.
    """

    has_theory_atom: bool
    shown: ShownVocabulary
    has_projection: bool
    has_optimization: bool
    has_maximize: bool
    has_theory_optimization: bool
    sources: frozenset[Path]


def inspect(files: tuple[Path, ...], *, within: Boundary | None = None) -> ProgramFacts:
    """Inspect the resolved program (``files`` + their ``#include``s) into ``ProgramFacts``. Raises
    ``ProgramError`` on an unreadable/missing/cyclic include, a parse error, or a source byte that
    is not UTF-8 — carrying clingo's own diagnostic, which is where the coordinates are, rather
    than repeating the ``files`` this was handed.

    ``within`` is the directory the program may not reach past — the caller's containment boundary,
    ``None`` for an inspection with none. It is here rather than only at the caller because a parse
    that *fails* inside an escaping file never returns the sources the caller would judge, while
    clingo's own diagnostic names that file, how far into it the parse got, and the coordinates it
    objected to. The boundary has to be known where the reading happens, or it is applied one step
    too late to matter.

    Three phases, because they have three different owners and a region can only name one. The
    parse is clingo's over the corpus author's text, so its failures are the program's. The walk
    over what clingo returned is elenctic's own code — with one exception, since clingo decodes
    node strings *lazily*, so a non-UTF-8 source byte surfaces here rather than at parse. Resolving
    the source names needs no clingo state at all and comes last, outside both regions."""
    statements: list[AST] = []
    # clingo's own diagnostics (with file:line:col), captured off the descriptor it writes them to
    # rather than through a logger callback — see `captured_diagnostics` for why the callback is
    # not survivable. The capture is entered first, so the region that translates a fault can still
    # read it while translating.
    with captured_diagnostics() as diagnostics, _parse_faults(diagnostics, within):
        _parse_files([str(path) for path in files], statements.append, logger=None)
    with _walk_faults():
        nodes = [node for statement in statements for node in _descendants(statement)]
        has_theory_atom = any(node.ast_type is ASTType.TheoryAtom for node in nodes)
        shown = _vocabulary(nodes)
        # Both spellings: `#project p/1.` is a signature and `#project q(a).` an atom.
        has_projection = any(
            node.ast_type in {ASTType.ProjectSignature, ASTType.ProjectAtom} for node in nodes
        )
        # `#minimize`, `#maximize`, AND `:~` all lower to `Minimize` nodes — one signal.
        has_optimization = any(node.ast_type is ASTType.Minimize for node in nodes)
        has_maximize = any(_is_maximize(node) for node in nodes)
        has_theory_optimization = any(_is_theory_objective(node) for node in nodes)
        # Each statement carries the file it came from (clingo's own include resolution); reading
        # that name is a decode, so it belongs here, while resolving it is a question for the
        # filesystem and belongs below.
        filenames = {statement.location.begin.filename for statement in statements}
    return ProgramFacts(
        has_theory_atom=has_theory_atom,
        shown=shown,
        has_projection=has_projection,
        has_optimization=has_optimization,
        has_maximize=has_maximize,
        has_theory_optimization=has_theory_optimization,
        # The distinct set, resolved once each, is the program's authoritative source-file span.
        sources=frozenset(Path(name).resolve() for name in filenames if name),
    )


# A clingo diagnostic opens with `path:line:col…`, which is the only place the name of a file the
# parse *failed* inside can be read — the statements it returned carry no trace of it, since a file
# whose parse failed contributed none. Where the path itself contains `:N:M` the split is genuinely
# ambiguous, so this matches the *separator* and every prefix of it is a candidate; picking one is
# what cannot be done safely, and picking the shortest could be steered by a corpus that committed
# a directory named for a time.
_DIAGNOSTIC_SEPARATOR = re.compile(r":\d+:\d+")


def _origins(line: str) -> list[Path]:
    """Every file this diagnostic line could be about: each prefix **of the line** that a
    ``:line:col`` follows, kept when it names something that exists.

    Existence is the disambiguator, and it is the right one because a diagnostic is always *about* a
    file the solver opened. A prefix naming nothing was never the origin — it is where a colon in
    somebody's directory name happened to look like a coordinate — so it neither licenses
    publication nor forbids it.

    Anchored at the start of the line, deliberately and with a stated limit: a *second* coordinate
    further along the same line yields the whole leading run as its candidate, which names nothing
    and is dropped, so a file named only there would not be judged. Every diagnostic measured puts
    at most one coordinate on a line and begins the line with it, which is what makes the anchor
    sound; a line carrying two would need this to search from each coordinate backwards instead, and
    that has no non-arbitrary place to stop.

    The empty prefix is not a candidate. A line beginning with its coordinate leaves nothing before
    it, and ``Path("")`` is ``Path(".")`` — which exists, resolves to the working directory, and
    would be judged as an origin the solver never opened, refusing an innocent corpus in the name of
    a file nobody named."""
    return [
        candidate
        for match in _DIAGNOSTIC_SEPARATOR.finditer(line)
        if (prefix := line[: match.start()]) and (candidate := Path(prefix)).exists()
    ]


def _strangers(detail: list[str], within: Path) -> list[str]:
    """The files these diagnostics are about that lie outside ``within``, sorted.

    A diagnostic about a file the run was never pointed at may not be published at all: it would
    report that the file exists, how far into it the solver got, and which characters it objected
    to — an existence-and-shape oracle over anything the process can read, driven from a corpus.

    **Every** candidate origin is judged, not the likeliest one. The split is ambiguous exactly when
    a path carries `:N:M`, and the text being split is the corpus author's to choose: a committed
    directory named for a time, and an include spelled through it, put the ambiguity where they
    want it. Judging one guess is then a rule the thing it constrains gets to aim.

    Resolution comes *after* the existence test, so a ``..`` that climbs out of the boundary is
    judged where it lands rather than where it is spelled — a containment test on the text is
    defeated by that spelling, since a parts-prefix check reads ``root/deep/../../elsewhere`` as
    under ``root``.

    A prefix that names nothing was never an origin, and the whole detail is scanned rather than the
    logged messages alone, so a fault reported through the exception's own text is judged too. That
    a line carries no identifiable origin is not a reason to withhold it: the leak is a *location*,
    naming a real file with real coordinates, and a line without one has none to give."""
    return sorted(
        {
            str(resolved)
            for message in detail
            for line in message.splitlines()
            for origin in _origins(line)
            if not (resolved := origin.resolve()).is_relative_to(within)
        }
    )


class Diagnostics:
    """What clingo has written about this program so far, read back from the descriptor it wrote to.

    A value rather than the list of messages this replaces, because the two frames that translate a
    fault need the text *while* the region that captures it is still open, and because what clingo
    writes to a descriptor has no message boundaries in it that a corpus cannot forge — see
    :func:`captured_diagnostics`."""

    def __init__(self, stream: IO[bytes]) -> None:
        self._stream = stream

    def text(self) -> str:
        """Everything clingo has written so far, decoded, ending in exactly one newline.

        Decoded **here**, by elenctic, in an ordinary frame that may fail safely — which is the
        whole difference from the decode this replaces. ``errors="replace"`` because a byte clingo
        quotes out of a program need not be valid UTF-8 on its own, and a diagnostic carrying one
        U+FFFD is a report where a raised ``UnicodeDecodeError`` is the absence of one.

        clingo ends each message with a newline and separates messages with a blank line, so the
        text arrives with a blank line at the end that terminates nothing. Only that padding is
        dropped: the last message keeps its own newline, because whatever a caller appends is a
        separate sentence and reads as one. Trimming it instead runs the two together — and the
        first message this was measured on ends in a semicolon, so a caller joining with one
        produced ``;;``.

        Read without disturbing the write position, so the region may be read again as it goes."""
        position = self._stream.tell()
        self._stream.seek(0)
        try:
            written = self._stream.read().decode("utf-8", errors="replace")
        finally:
            self._stream.seek(position)
        return f"{trimmed}\n" if (trimmed := written.rstrip("\n")) else ""


# Descriptor 2 belongs to the process, not to a call, so two captures at once would take each
# other's diagnostics or lose them. elenctic solves one case at a time and the documented way to
# parallelise it is across processes, which have a descriptor 2 each; a consumer using threads would
# otherwise get silent corruption, and serialising is the cheapest honest answer to that.
_CAPTURE_LOCK: Final = Lock()


@contextmanager
def captured_diagnostics() -> Iterator[Diagnostics]:
    """Send what clingo writes about a program to a file elenctic can read, for the length of the
    region, and hand back the value that reads it.

    **Why elenctic does not simply ask clingo for its messages.** A Python logger is handed the
    message already decoded, by clingo, inside a C++ frame declared not to throw. A lexer error
    quotes the *byte* it objected to, a lone UTF-8 lead byte does not decode, and the exception that
    raises cannot leave that frame: the process aborts, with no report of any kind and nothing
    elenctic can catch. Reading the descriptor instead puts the decode in :meth:`Diagnostics.text`,
    where a bad byte is a character in a diagnostic rather than the end of the run.

    **The text is kept whole and never split back into messages.** clingo ends each with a blank
    line, and splitting on it recovered the list byte-for-byte over every diagnostic measured —
    until a directory named with a newline in it put a blank line *inside* one, and one message
    became three. Message boundaries are not in the text; they are in a separator the corpus author
    can write. A rule whose input the constrained party chooses is not a rule, so no such rule is
    stated: what clingo wrote is reported in clingo's own framing.

    At the descriptor rather than at ``sys.stderr``, because clingo writes from C++ and rebinding a
    Python object leaves that untouched. A temporary file rather than a pipe, because a pipe's
    buffer is finite and a run emitting more than it would block for good — a hang, not an error.
    """
    with _CAPTURE_LOCK, TemporaryFile() as stream:
        sys.stderr.flush()  # or anything Python has buffered for stderr lands in the capture
        saved = os.dup(2)
        try:
            os.dup2(stream.fileno(), 2)
            yield Diagnostics(stream)
        finally:
            # The release is owed even where putting it back failed: a copy that could not be
            # restored is still a descriptor this process holds.
            try:
                os.dup2(saved, 2)
            finally:
                os.close(saved)


def refuse_strangers(detail: list[str], within: Boundary | None, cause: Exception) -> None:
    """Refuse to publish ``detail`` when any part of it is a diagnostic about a file outside
    ``within``; return, having decided nothing else, when every part may be published.

    The one statement of the rule, called from wherever a solver's own account of a failure is about
    to be republished — the parse below, and the ground and solve in the facades. Containment is a
    rule about *disclosure* rather than about one function, and a reader meets whichever frame the
    program happened to get as far as: refused while it is read if an escaping ``#include`` will not
    parse, while it is grounded if that file parses and then will not ground. Stated once per frame,
    the same escape would be refused in different words, or in one frame and not another, decided by
    a property of the offending file that its author has no use for.

    ``within`` is ``None`` for a caller who stated no rule — one that assembled the files itself
    rather than discovering them — and then there is nothing to be outside of.

    ``cause`` is the failure being translated, so the refusal is chained to it rather than to
    whatever this frame was doing: a reader following ``__cause__`` reaches the fault the solver
    reported, which is what the refusal is standing in for."""
    if within is None or not (escaped := _strangers(detail, within.root)):
        return
    raise ContainmentError(
        f"{within.refusal(escaped)} The solver's own diagnostic is withheld rather than "
        "repeated here — part of it describes a file the run was never pointed at, and "
        "the parts cannot be separated safely."
    ) from cause


@contextmanager
def _parse_faults(diagnostics: Diagnostics, within: Boundary | None = None) -> Iterator[None]:
    """Translate a failure raised by the parse into a ``ProgramError`` carrying clingo's own
    captured diagnostic — unless that diagnostic is about a file outside ``within``, in which case
    the escaping path is named and nothing else is.

    Which file the fault belongs to is **not** said here. Whoever called :func:`inspect` passed the
    files in, and a join of all of them would not say which one failed in any case — clingo's own
    coordinate does that, and it is in the diagnostic this carries.

    Everything under this region is clingo reading the corpus author's text, so every failure it
    reports is that author's to fix. A harness-logic bug (``AttributeError``/``KeyError``/...) is
    not caught and stays loud, and ``RecursionError`` is re-raised for the same reason it is in the
    solver facade: it is a ``RuntimeError`` subclass, and it never means the program is at fault.
    Nothing under this region recurses, but the callbacks clingo fires here run on whatever stack
    the caller had left."""
    try:
        yield
    except RecursionError:
        raise
    except UnicodeEncodeError as exc:
        # The file *name*, not its contents: clingo encodes the path strictly, so a name carrying a
        # byte that is not UTF-8 fails before the file is opened. A sibling of UnicodeDecodeError
        # rather than a subclass, so the tuple below does not cover it.
        raise ProgramError(
            "cannot open the program: the file name is not valid UTF-8, which the solver "
            "requires — rename the file"
        ) from exc
    except (RuntimeError, UnicodeDecodeError, OSError) as exc:
        # RuntimeError: a parse / missing-or-cyclic-#include failure (clingo logged the detail to
        # `messages`); UnicodeDecodeError: a source byte reaching Python through a diagnostic;
        # OSError: unreadable.
        # Both, never one or the other: the capture holds the provenance but accumulates routine
        # notices too, so a fault raised after a clean parse would otherwise be reported as
        # whichever harmless notice was written first, with the real cause dropped. An empty part
        # is dropped rather than joined, or a run that said nothing opens its detail with a
        # separator.
        parts = [part for part in (diagnostics.text(), str(exc)) if part]
        refuse_strangers(parts, within, exc)
        detail = "; ".join(parts)
        # The include advice is specific enough to act on, so it is offered only when it is the
        # remedy. Attached to a syntax error it sends the author to check paths that are fine.
        hint = (
            " — check the case's #include paths (they resolve relative to the including file)"
            if "could not be opened" in detail
            else ""
        )
        raise ProgramError(f"cannot resolve the program: {detail}{hint}") from exc


@contextmanager
def _walk_faults() -> Iterator[None]:
    """Translate the one failure of elenctic's own walk that belongs to the program: a source byte
    that is not valid UTF-8, which clingo decodes lazily and so raises here rather than at parse.

    Anything else raised under this region comes from elenctic's traversal of an AST clingo already
    accepted, and it is elenctic's — so it is left to propagate with its own type, and is reported
    as the defect it is instead of sending a corpus author to fix a file that parsed. That includes
    ``RecursionError``: nothing under this region recurses, so it can no longer describe a term the
    walk could not follow, and it means here what it means in the solver facade. The parse's
    captured diagnostics are deliberately not spliced into these messages: they describe the text,
    and a notice about an atom occurring in no rule head explains nothing about a byte that will
    not decode."""
    try:
        yield
    except UnicodeDecodeError as exc:
        raise ProgramError(
            "cannot read the program: a byte in the source is not valid UTF-8, which the solver "
            f"requires — re-encode the file as UTF-8 ({exc})"
        ) from exc


def _descendants(node: object) -> Iterator[AST]:
    """Every ``AST`` node reachable from ``node`` — traversing child attributes AND clingo's
    ``ASTSequence`` (iterable, but **not** a python ``list``; a naive ``isinstance(_, list)`` walk
    misses body literals).

    An explicit work-list, not recursive delegation. The depth here is decided by the program under
    test, so recursion would bound what elenctic can read by the interpreter's stack — and a term
    nested past it is one clingo grounds and solves without complaint. It is not only a hostile
    shape that reaches it: a list written as ``cons(a, cons(b, …))`` nests one level per element.
    The work-list yields in a different order than recursion would, which no reader depends on —
    each folds these nodes into a set or an existence check."""
    pending: list[object] = [node]
    while pending:
        current = pending.pop()
        if isinstance(current, AST):
            yield current
            # keys() is the AST child-field API, not a dict
            pending.extend(getattr(current, key) for key in current.keys())  # noqa: SIM118
        elif not isinstance(current, (str, bytes)) and hasattr(current, "__iter__"):
            pending.extend(current)


# The theory-native objective directives. clingcon spells its objective `&minimize`/`&maximize`,
# which parse as a TheoryAtom whose term is a plain function of that name — no `Minimize` node, so
# the clingo-native signal never sees them.
_THEORY_OBJECTIVES: Final = frozenset({"minimize", "maximize"})


def _is_theory_objective(node: AST) -> bool:
    """A theory-native objective (``&minimize { … }`` / ``&maximize { … }``): a ``TheoryAtom``
    whose term names one of them. Read by name, since the objective belongs to the theory rather
    than to clingo: no ``Minimize`` node is produced and no clingo optimization flag reaches it.

    The term's type is asked before its name, rather than reading the name with a default to fall
    back on. The fallback would work here — a missing field on an AST node does return the default
    — but relying on it is what hid a defect in the signature reader, where the same expression
    over a *symbol* raises instead, so the default could never fire. Nothing about the two spellings
    distinguishes them at a glance, so neither is written. clingo represents a theory atom's term
    as a function node in every form it accepts, in a head or a body, with arguments or with a
    condition, so asking is total."""
    return (
        node.ast_type is ASTType.TheoryAtom
        and node.term.ast_type is ASTType.Function
        and node.term.name in _THEORY_OBJECTIVES
    )


def _is_maximize(node: AST) -> bool:
    """A ``#maximize`` objective: clingo lowers it to a ``Minimize`` node whose ``weight`` is a
    negated term (``UnaryOperation`` with ``UnaryOperator.Minus``); ``#minimize`` carries a plain
    ``SymbolicTerm`` weight. v1 cannot present a natural ``@cost`` over a negated
    weight, so this is the guard signal. (A ``#minimize`` with an explicitly-negated literal weight
    is structurally identical post-parse and also trips this — correct, and loud-not-silent; full
    sign-tracking is deferred.)"""
    return (
        node.ast_type is ASTType.Minimize
        and node.weight.ast_type is ASTType.UnaryOperation
        # `operator_type` is a plain int (0); IntEnum `==` matches, `is` does NOT.
        and node.weight.operator_type == UnaryOperator.Minus
    )


def _vocabulary(nodes: list[AST]) -> ShownVocabulary:
    """Classify what the resolved program makes observable, from its ``#show`` nodes.

    clingo has **two** ``#show`` statements and they do different jobs, which is measurable and is
    the distinction this reads:

    - the *declaration* form — ``#show p/1.``, and the bare ``#show.`` — switches the solver into
      selective output. Its presence is what restricts the program at all, and each named one
      adds a signature that is then projected faithfully: every atom over it appears, and nothing
      else does.
    - the *display* form — ``#show <term> : <body>.`` — emits a chosen term wherever its body holds
      and **does not restrict anything**. A program carrying only these still shows every atom, so
      reading one as a declaration understates what is observable; and where a declaration is
      present too, reading one as a declaration *over*states it, since the term reaches the output
      for some ground instances and not others, and need not name an atom of the program at all.

    So a program is restricted exactly when it carries a declaration, and only declarations put a
    signature in the vocabulary. A display is recorded separately rather than dropped, because it is
    not silence: it is the one thing that can put in the output a symbol the answer set does not
    contain, which no amount of restriction describes and which a reader of the output has to be
    told about whichever state the program is in.
    """
    declarations = [node for node in nodes if node.ast_type is ASTType.ShowSignature]
    displayed = frozenset(
        signature
        for node in nodes
        if node.ast_type is ASTType.ShowTerm
        and (signature := _predicate_signature(node.term)) is not None
    )
    if not declarations:
        return Unrestricted(displayed=displayed)
    return Restricted(
        signatures=frozenset(
            signature
            for node in declarations
            if (signature := _declared_signature(node)) is not None
        ),
        displayed=displayed,
    )


def _declared_signature(node: AST) -> Signature | None:
    """The signature a ``#show p/1.`` declaration names, or ``None`` for the bare ``#show.``, which
    names none — it restricts the output to nothing and is what makes an empty vocabulary mean
    *show nothing* rather than *no restriction*."""
    if not node.name:
        return None
    return (node.name if node.positive else f"-{node.name}", node.arity)


def _predicate_signature(term: AST) -> Signature | None:
    """The signature of a displayed term: ``(p, n)`` / ``(-p, n)`` for a (possibly negated) function
    or constant; ``None`` for anything else (a non-predicate term has no name).

    The negation chain is peeled with a loop for the same reason the node walk uses one: its length
    is the program's to choose, and clingo accepts one far longer than the interpreter would let
    this recurse along. Each sign is kept rather than folded, so the signature records what the
    author wrote."""
    negations = 0
    while term.ast_type is ASTType.UnaryOperation and term.operator_type == UnaryOperator.Minus:
        negations += 1
        term = term.argument
    signature = _unsigned_signature(term)
    if signature is None:
        return None
    name, arity = signature
    return ("-" * negations + name, arity)


def _unsigned_signature(term: AST) -> Signature | None:
    """The ``(name, arity)`` of a displayed term with its negation chain already peeled: a function
    or constant carries one, anything else carries none."""
    if term.ast_type is ASTType.Function:
        return (term.name, len(term.arguments)) if term.name else None
    if term.ast_type is ASTType.SymbolicTerm:
        # The type is asked before the name, because a symbol's name is defined only for a function
        # symbol: reading one off a string or a number raises rather than reporting that there is
        # none, so a default cannot stand in for it. `#show "text" : p.` and `#show 42 : p.` are
        # both programs clingo runs, and neither declares a predicate.
        symbol = term.symbol
        if symbol.type is not SymbolType.Function:
            return None
        return (symbol.name, len(symbol.arguments)) if symbol.name else None
    return None
