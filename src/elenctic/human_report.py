"""A run as the prose a person reads — the renderer for the other audience.

Two audiences, one module each. :mod:`elenctic.json_report` renders a whole run as one
machine-readable document for a consumer's parser; this renders it as sentences for a person at
a terminal. Both are built from the registers a run hands back — never from each other's output,
and never from a second account kept alongside — so what a reader is told, what a document
carries, and what the exit status is read off cannot come to disagree about a number or a
verdict.

**This one is live under both formats, and the flag names suggest otherwise.** ``--format``
decides who the *report* is written for; it does not decide whether there is a person. Under
``--format human`` the prose here is the report. Under ``--format json`` it is still written —
moved to standard error, so a reader still sees it where a parser is not looking — and the
document is what lands on standard output instead. The document's module is the conditional
one; this is not.

**Where the two stop being alike.** A document is one value written once, at the end. Prose is not:
a reader watching a long run wants each case as it lands, so this renders in two moments where the
document renders in one. The observers below are the as-it-goes half, turning each verdict and fault
into a line as the run establishes it; :func:`render_tail` is the other half, the things about the
whole run that cannot be said while it is going. Hence observers here and none in the document's
module.

**Every string a corpus had a hand in passes through the sanitizer.** A path, a ``@note``, an atom,
a solver's own diagnostic: text a reader's terminal would act on rather than display can move the
cursor over a line already printed, so a diagnostic that reproduces one can erase the verdict above
it. The document seam states the same rule for a related reason — text a parser would act on can
break the document it appears in — and each renderer owns its own seam, so a field or a line added
to either inherits the guarantee from the one place its own module has to add it.

This is not part of the curated surface. A consumer embedding elenctic already has the records,
:func:`~elenctic.harness.render` for one case's diagnostic, and
:func:`~elenctic.json_report.as_json` for the whole run; what is here is *this program's* narration
of a run to a terminal, which is the console entry's business and not a library's.
"""

import sys
from contextlib import suppress
from pathlib import Path
from typing import assert_never

from elenctic.corpus import Observer
from elenctic.discovery import Case
from elenctic.display import legible
from elenctic.harness import render
from elenctic.outcome import (
    CaseOutcome,
    CasePlan,
    ErrorKind,
    ErrorRecord,
    Grade,
    HygieneKind,
    HygieneRecord,
    Invocation,
    Outcome,
    PlanOutcome,
    RunOutcome,
    Scope,
    render_seconds,
    summary,
)
from elenctic.result import Verdict

__all__ = ["TerminalPlan", "TerminalRun", "announced", "heading", "render_tail"]


class _Terminal(Observer):
    """What both modes say to a reader as the run goes — the announcements they share.

    Inherits the protocol rather than merely fitting it, which is what supplies a do-nothing body
    for every announcement neither mode renders. A run says nothing when a case is taken up: what a
    reader wants from a corpus of a hundred and thirty-five is the ones that did not pass, and the
    tally at the end accounts for the rest. A dry run does say so, and overrides it below.

    The prose lives here and nowhere below: a run establishes records and this turns them into
    sentences, so the same run can be watched by a reader, written as a document, or embedded in
    something else without any of the three re-deriving what the others know. Every string a corpus
    had a hand in passes through the sanitizer, because text a reader's terminal would act on rather
    than display can forge a verdict in the report it appears in.
    """

    # Both go through the one renderer, so a fault reads the same whichever frame met it. What
    # differs is what the fault cost — a corpus nothing could be read from, or one file among others
    # that will produce no verdict while the rest of the corpus still runs — and the run says which
    # by which of these it calls, so nothing here has to ask a record what it was.

    def corpus_unreadable(self, record: ErrorRecord) -> None:
        print(announced(record), file=sys.stderr)

    def case_unusable(self, record: ErrorRecord) -> None:
        print(announced(record), file=sys.stderr)


class TerminalRun(_Terminal):
    """What a run says to a reader, case by case, as each one lands."""

    def case_unjudged(self, record: ErrorRecord) -> None:
        """One case that produced no verdict — said here unless the report says it once at the
        end instead, which is the arm :func:`_unjudged_line` decides."""
        if (line := _unjudged_line(record)) is not None:
            print(line, file=sys.stderr)

    def case_judged(self, outcome: CaseOutcome) -> None:
        """One case that reached a verdict — rendered only where the verdict is not PASS."""
        # A passing case says nothing. What a reader wants from a corpus of a hundred and
        # thirty-five is the ones that did not pass, and the tally at the end accounts for the rest.
        if outcome.verdict is not Verdict.PASS:
            print(render(outcome.case, outcome.reports))


class TerminalPlan(_Terminal):
    """What a dry run says to a reader: the plan each case derived to, under the case it belongs
    to."""

    def case_started(self, case: Case) -> None:
        """The case a plan belongs to, and any notes its author wrote on it."""
        print(f"{_text(case.contract_source)} [{case.solver}]")
        # The @note prose leads the narration — the author's what/why above the harness's how.
        # Both Sat and Unsat carry notes; documentation, never a verdict.
        for note in case.expectation.notes:
            print(f"    note: {_text(note)}")

    def case_planned(self, case_plan: CasePlan) -> None:
        """The runs one case derived to: each mode, and what every check in it reads."""
        for plan in case_plan.runs:
            projects = "yes" if plan.projects_to_shown else "no"
            print(f"    {plan.mode.name} (projects: {projects}):")
            for check in plan.checks:
                # subject discerns the repeatable @query tag before any solve. It is built from the
                # literals the contract author wrote, so it is corpus text and goes through the
                # sanitizer; the label beside it is elenctic's own, from a fixed vocabulary.
                name = f"{check.label} ({_text(check.subject)})" if check.subject else check.label
                reads = ", ".join(sorted(field.value for field in check.reads)) or "—"
                print(f"        {name} — reads {{{reads}}}")

    def case_unjudged(self, record: ErrorRecord) -> None:
        """A case this run could not judge, indented under the case the narration has already
        named."""
        # Indented under the case the narration has already named, and it names the file again
        # because it goes to the other stream: a reader who has only that one is owed it.
        #
        # The same sentence as a real run's, rather than one of its own. A dry run solves nothing,
        # so the only fault it can meet today is a plan that could not be built — but that is a fact
        # about what this mode currently does, not a property of the renderer, and a renderer that
        # answered "elenctic's own fault" to whatever it was handed would one day tell an author
        # their corpus is a harness bug. Filing a fault as the wrong owner is a defect this project
        # has shipped twice.
        if (line := _unjudged_line(record)) is not None:
            print(f"    {line}", file=sys.stderr)


def _unjudged_line(record: ErrorRecord) -> str | None:
    """What a reader is told about one case that produced no verdict — or ``None`` where the report
    says it once at the end instead.

    One arm decides, and it is about *when* a fault is said rather than about what it says. A
    passed deadline costs every case it did not reach, and a line apiece would bury the reason under
    its own consequences, so its records are still filed per case — where they can say which case —
    and the sentence is rendered from the whole register once the run is over. Every other locus is
    announced where it is met.

    Nothing else here is keyed on the locus. Where a fault lies and where it is written are two
    different facts, and the second has one home — :class:`~elenctic.outcome.ErrorRecord`'s
    ``source`` and ``line`` — and one renderer, so no arm has provenance left to decide.
    """
    if record.kind is ErrorKind.DEADLINE:
        return None
    return announced(record)


def _text(value: str | Path) -> str:
    """Anything the corpus had a hand in, made safe to show.

    One seam for every such string rather than a judgment per call site, because which of them a
    corpus can reach is a question whose answer changes: a message is elenctic's own prose until the
    day it quotes the solver, and a path is corpus-chosen always. Text a reader's terminal would act
    on rather than display can move the cursor over a line already printed, so a diagnostic that
    reproduces one can erase the verdict above it.

    The document seam states the same rule for a related reason, and settles narrower questions
    besides, which its own module states. Both exist because a *renderer added later* inherits
    the guarantee only if there is one place to inherit it from — three call sites
    here were reachable with hostile text and unsanitized, each having been judged individually.
    """
    return legible(str(value))


def heading(kind: ErrorKind, scope: Scope) -> str:
    """What a fault is announced as: where it lies, and what it cost.

    Two facts, and neither of them a fact about elenctic. The **word** is the locus, so one fault is
    announced by one name however it was met — reporting which part of elenctic noticed instead
    would make one broken ``#include`` a ``CASE ERROR`` where discovery walks into it and a
    ``PROGRAM ERROR`` where the runner does. The **case and the punctuation** are what it cost,
    which is what ``Scope`` means: capitals where the run went on and still produced a report, lower
    case where it stopped and there is none.

    The word is the locus's own name rather than a second vocabulary beside it, so nobody has to
    keep a table: what is printed here as ``PROGRAM ERROR`` is what a document calls
    ``"kind": "program"``. Derived from the vocabulary rather than written out locus by locus, so a
    locus added later cannot be announced by whatever heading the frame that met it happens to
    carry.

    The two facts are taken as themselves rather than as a record holding them, and that is what
    lets every line naming a locus come through here — including the deadline notice, which is a
    reading of *many* records and so has no one record to be handed. It also makes the paragraph
    above a property of the signature rather than a promise about the body: there is nothing else
    here to read.
    """
    match scope:
        case Scope.CORPUS:
            return f"{kind.value} error:"
        case Scope.CASE:
            return f"{kind.value.upper()} ERROR —"
        case unreachable:
            assert_never(unreachable)


def announced(record: ErrorRecord) -> str:
    """One record as one line: where it is, and what is wrong there.

    The one renderer for a record, whichever frame met the fault and whatever it was about, and the
    *only* one: this module announces records as a run goes — a corpus nothing could be read from, a
    file discovery could not use, a case a run could not judge — and the console entry's own
    backstops announce the faults no register anticipated. Composing a line at each of those sites
    is how one fault comes to be printed several ways depending on where it was caught.

    ``source:line:`` is the one spelling, the one clingo, rustc and pytest all write and the one
    an author's editor already knows how to open. A record with no line has no coordinate, so it
    names the file alone; a corpus-level fault belongs to no file and gets the message by itself.
    That last case is not a precondition waived: the only way to state one here would be to render
    the word ``None`` at a reader, which says a file called None rather than no file at all.

    Both halves are sanitized, and neither is elenctic's own text: the message quotes the solver or
    an exception, and the path is a filename the corpus chose. Text a reader's terminal would act on
    rather than display can move a cursor over a line already printed, which is how a diagnostic
    forges a verdict in the report it appears in. The line number is elenctic's own count and is
    rendered as the integer it is."""
    opening = heading(record.kind, record.scope)
    if record.source is None:
        return f"{opening} {_text(record.message)}"
    at = _text(record.source) if record.line is None else f"{_text(record.source)}:{record.line}"
    return f"{opening} {at}: {_text(record.message)}"


def render_tail(outcome: Outcome, invocation: Invocation) -> str:
    """What the report says once, when the run is over: the two diagnostics it writes, and the
    tally it **hands back** for its caller to write.

    Three things that are about the whole run rather than about any one case, and so cannot be said
    while it is going: that a deadline stopped it, how many cases passed, and what was observed
    about the corpus's health. Each is rendered from the registers the run handed back, so what a
    reader is told and what the exit status is read off cannot come to disagree.

    The tally is returned rather than printed, and that is the difference between a property of one
    frame and a property of the program. A standard-output write made here is one made outside the
    frame that answers for standard output, so on a stream that writes through rather than holding
    what it is given — which is what ``PYTHONUNBUFFERED`` in an ordinary CI image makes it — a
    reader that has stopped reading is met by this write first, and the failure reads as a bug in
    elenctic. Handing it back puts *this function makes no standard-output write* where a reader can
    see it: in the signature, and in the pair of statements at each call site in
    :func:`~elenctic.cli.main`.

    What it costs is that the tally follows the two diagnostics rather than standing between them.
    No order is lost by that — measured, the merged view flips on buffering either way, so a
    developer at a terminal and the same command in CI see different ones. Both formats order
    deadline → hygiene → tally, which is the shape the category has: a summary last, as pytest,
    cargo and go all put theirs.

    The empty string means there is nothing to tally. A dry run decided nothing to tally, and
    neither did a run that never got past discovery: a corpus-scoped fault is the whole of what such
    an invocation produced, and ``0/0 passed`` under it would answer a question nobody could have
    asked — it reads as a corpus that was looked at and found to hold nothing, which is a different
    thing from one that could not be read. An empty corpus *does* tally, and says exactly that.
    """
    if any(record.scope is Scope.CORPUS for record in outcome.errors):
        return ""
    # A diagnostic that cannot be delivered does not stop the report from being delivered. These
    # two write to standard error, and now that they stand *ahead* of the tally a stream that
    # refuses them would otherwise cost a healthy standard output the report it was keeping —
    # which is the same trade the run already makes for a console observer, and the same one the
    # hand-over makes for the reader that stopped reading. There is nowhere to report this: the
    # stream that would carry the complaint is the one that would not take the message.
    with suppress(OSError):
        match outcome:
            case RunOutcome():
                _report_deadline(outcome, invocation)
                _report_hygiene(outcome.hygiene)
            case PlanOutcome():
                _report_hygiene(outcome.hygiene)
            case unreachable:
                assert_never(unreachable)
    return f"\n{_summary_line(outcome)}\n" if isinstance(outcome, RunOutcome) else ""


def _report_deadline(outcome: RunOutcome, invocation: Invocation) -> None:
    """Say once that the deadline stopped the run, and how many cases it did not reach.

    Counted off the register rather than remembered from the loop: a case the deadline never reached
    has a record of its own saying so, and the reader's sentence is a reading of those rather than a
    second account of the same event kept alongside them.

    Announced through the same vocabulary as every other fault, although it is the one line built
    from many records rather than from one. That is why the heading is asked for by locus and scope
    rather than handed a record: there is no single record here to hand it, and picking one of the
    several would make an arbitrary choice look like a considered one. The scope is the one every
    record in this register carries — a deadline costs cases, and the run still reports on the ones
    it reached, which is exactly what the tally below this line goes on to say."""
    unreached = [record for record in outcome.errors if record.kind is ErrorKind.DEADLINE]
    # A deadline record exists only where a deadline was set, so the second test is the type system
    # asking for what the first already establishes. Answered rather than asserted, because the one
    # state it rules out is this line printing the word "None" at a reader where a number belongs.
    if not unreached or (deadline := invocation.deadline) is None:
        return
    print(
        f"{heading(ErrorKind.DEADLINE, Scope.CASE)} the run passed its "
        f"{render_seconds(deadline)}s "
        f"deadline; {len(unreached)} case(s) were not reached",
        file=sys.stderr,
    )


def _report_hygiene(hygiene: tuple[HygieneRecord, ...]) -> None:
    """Report corpus hygiene as an aggregated end-of-run stderr summary, at the footing each
    observation was graded on. Orphan libraries warn by default; under ``--strict`` they — plus the
    otherwise-silent undeclared solvers — become errors that fail the run (the CI gate). Hygiene is
    never a verdict; what a reported observation does to the exit status is decided with the rest of
    it.

    Rendered from the records themselves — their text as well as their grade — so what is printed
    and what fails the run cannot disagree about a single observation. Every kind is walked and the
    match over them is exhaustive, because a kind that reached the grading but not the rendering
    would fail a run under ``--strict`` and print nothing to say why."""
    reported = [record for record in hygiene if record.grade is not Grade.SILENT]
    lines: list[str] = []
    for kind in HygieneKind:
        observed = [record for record in reported if record.kind is kind]
        if not observed:
            continue
        match kind:
            case HygieneKind.ORPHAN_LIBRARY:
                lines.extend(
                    f"orphan library: {_text(record.source)} {_text(record.message)}"
                    for record in observed
                )
            case HygieneKind.UNDECLARED_SOLVER:
                # Aggregated: a corpus that never declares a solver would otherwise report every
                # case, and the observation is about the corpus's habit rather than about any one
                # file. The sentence is stated once because it is one observation, and every record
                # of a kind carries the same one.
                listed = ", ".join(_text(record.source) for record in observed)
                lines.append(
                    f"undeclared solver: {len(observed)} case(s) "
                    f"{_text(observed[0].message)}: {listed}"
                )
            case _:
                assert_never(kind)
    if not lines:
        return
    failing = any(record.grade is Grade.ERROR for record in reported)
    print(f"\nhygiene {'errors (--strict)' if failing else 'warnings'}:", file=sys.stderr)
    for line in lines:
        print(f"  {line}", file=sys.stderr)


def _summary_line(outcome: RunOutcome) -> str:
    """The end-of-run tally, read off the registers the machine-readable form is built from — so
    the two renderings cannot come to disagree about a number. The two error levels are kept apart
    because they ask different things of the reader: one is a corpus to fix, the other is a bug to
    report."""
    counts = summary(outcome)
    # Both are cases that produced no verdict, split by who can act on them — so neither is named
    # for the running they did not do, which is the half they have in common.
    theirs = sum(
        1
        for error in outcome.errors
        if error.scope is Scope.CASE and not error.kind.is_elenctic_bug
    )
    # Both counters are over case-scoped records, and both have to be: `total` counts the cases
    # discovered and counts an unrun one by its case-scoped record, so a corpus-scoped fault counted
    # here would be reported beside a total that does not include it — a line that fails its own
    # arithmetic. Nothing files a corpus-scoped fault into an outcome that also has cases today, and
    # this is what keeps that from being the reason the line is right.
    ours = sum(
        1 for error in outcome.errors if error.kind.is_elenctic_bug and error.scope is Scope.CASE
    )
    line = f"{counts['passed']}/{counts['total']} passed"
    if theirs:
        line += f", {theirs} could not be run"
    if ours:
        line += f", {ours} harness error(s)"
    return line
