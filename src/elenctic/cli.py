"""The ``elenctic`` console entry: run a corpus of ``@``-contracts, or explain its run plan.

``elenctic [target]`` discovers cases under ``target`` — a single ``.lp`` case file or a directory
walked for contract-bearing files (default ``tests/``) — validates **every** case's run plan up
front (so a misroute, which is a harness bug, is reported before any solving), then solves and
checks each case, rendering any non-``PASS`` outcome. ``--explain`` stops after the plan: it
narrates the derived runs (mode + checks) per case without solving, the dry-run the
``reads``/``populates`` surface was made introspectable for.

``--format`` chooses who the report is written for. The default writes prose for a reader.
``--format json`` writes the whole run as one machine-readable document on standard output and
moves every diagnostic to standard error, so that nothing a consumer's parser would choke on lands
beside the document; ``--print-schema`` describes that document's shape without running anything.

**What is this module's own, and what is not.** A command line, its refusals, the two streams and
which of them a published artefact goes to, the backstops for a fault no register anticipated, and
the prose a reader sees — these are a program's concerns and they are what is here. Everything
below them is the library's: ``corpus.run_corpus`` and ``corpus.explain_corpus`` carry out an
invocation, ``outcome.exit_status`` reads a status off what they produced, and both are reachable
without any of this. So ``main`` is a derivation of the library rather than the place its work is
done — it parses a command line into an :class:`~elenctic.outcome.Invocation`, calls in, renders
what comes back, and returns the status — and a consumer wanting elenctic's results inside a runner
of their own has the same pieces this is built from, whether they want a whole corpus or
``harness.run_case`` one case at a time.

The exit ladder is written once, in :class:`~elenctic.outcome.ExitStatus`, and ``--help`` is
rendered from there rather than restating it in words that could come to differ.
"""

import argparse
import os
import sys
import textwrap
import traceback
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from elenctic.corpus import explain_corpus, run_corpus
from elenctic.json_report import as_json, dumps, schema_text
from elenctic.outcome import (
    ErrorKind,
    ErrorRecord,
    ExitStatus,
    Invocation,
    RunOutcome,
    Scope,
    exit_status,
    is_duration,
)
from elenctic.solvers import TIME_BUDGET

# The same allocation failure with no case to name it against, and the reason it is worded
# separately rather than reused: a frame that cannot say which case was running cannot offer the
# remedy that names one, so it asks for the whole corpus to be bounded instead.
_CORPUS_OUT_OF_MEMORY = (
    "elenctic ran out of memory running this corpus. Grounding has no size limit available to it, "
    "and a solve holds every model it is shown — run this corpus with a memory limit, or reduce "
    "what it grounds and enumerates. No verdict was produced."
)

# What a fault no register anticipated says about itself. Shared by the diagnostic and the record
# for the same reason as the two above: one sentence, stated once.
_INTERNAL_ERROR = "this is an elenctic bug, not a fault in your corpus"

# The one thing --print-schema can fail at, said in terms the reader can act on. It is worth its own
# sentence rather than the internal-error backstop, because the backstop asks for a bug report and
# this is not a bug in elenctic: the description ships beside the modules, so a copy that has the
# modules and not the description was assembled by something downstream — a vendoring step, a
# repackaging, an installer that keeps code and drops data. Sending that reader to elenctic's issue
# tracker sends them somewhere that cannot help them.
_SCHEMA_UNREADABLE = (
    "elenctic could not read its own output description. It ships inside the package, beside the "
    "modules, at elenctic/schema/ — so this copy of elenctic has the code and not the data, which "
    "is something a packaging or vendoring step did rather than anything you configured. "
    "Reinstalling elenctic from a released wheel or from its source tree restores it. Nothing else "
    "is affected: running a corpus never reads this file."
)

# Everything below here is said to whoever typed a command line that cannot be run, and unlike the
# messages above none of them is also the text of a record: such a command line produced no run, so
# there is nothing for a record to be about.
#
# What to do instead of asking for a duration that is not one. The two answers differ because the
# flags do — there is no way to spell "no per-solve budget", while a run with no deadline is the
# default — so the deadline's remedy is to leave the flag off rather than to name a number.
_UNBOUNDED_BUDGET = "A run that wants no practical limit asks for a large finite number."
_UNBOUNDED_DEADLINE = "A run that wants no deadline leaves --deadline off, which is the default."

# Why the two flags cannot be asked for together. Each is fine alone: one narrates the plan a run
# would follow, the other writes what a run produced. There is no document for a plan in this
# version, so the pair could only mean writing prose to the one stream that has to carry a document.
_NO_MACHINE_READABLE_DRY_RUN = (
    "--explain and --format json cannot be combined. --explain narrates the plan each case would "
    "follow without solving anything, and this version describes no machine-readable form for a "
    "plan. Ask for --explain alone to read the plan, or for --format json alone to run the corpus "
    "and get the report."
)


# The width the ladder is wrapped to. The epilog is printed as it is written — argparse reflows a
# description and this formatter does not — so the wrapping happens here, over the glosses, rather
# than by hand in a string where a longer sentence would silently break the column a reader follows.
_HELP_WIDTH = 79


def _exit_status_help() -> str:
    """The exit-status table, rendered from the ladder rather than written beside it.

    What the run leaves with is the whole of what a script reads and the one thing argparse never
    volunteers. The ordering is precedence and not severity, which is worth saying outright: four
    ascending integers read as a severity scale, and on that reading a mis-shaped corpus would be
    worse than a refuted contract, which is not what the numbers mean.
    """
    rungs = "\n".join(
        textwrap.fill(
            status.gloss,
            width=_HELP_WIDTH,
            initial_indent=f"  {status.value}  ",
            subsequent_indent="     ",
        )
        for status in ExitStatus
    )
    refusal = textwrap.fill(
        "A command line elenctic cannot parse or use is refused before anything is discovered: "
        "the reason goes to standard error, standard output stays empty, and the status is "
        f"{ExitStatus.USER_FAULT.value}. So a report is either whole or absent, never half "
        "written.",
        width=_HELP_WIDTH,
    )
    return f"exit status, the first rung that applies:\n{rungs}\n\n{refusal}"


def _build_parser() -> argparse.ArgumentParser:
    """The command line, with each option filed under what it is for.

    Six options in one block is a block a reader has to sort: two of them do something other than
    running the corpus, one says who the report is written for, and three bound or sharpen the run
    itself. The headings say which is which, and the closing text says what the run leaves with —
    the one thing ``argparse`` never volunteers and the one a script has to know.
    """
    parser = argparse.ArgumentParser(
        prog="elenctic",
        description="Run a corpus of @-contracts over Answer Set Programs.",
        epilog=_exit_status_help(),
        # The ladder is a table, and the default formatter would reflow it into a paragraph. Only
        # the description and the epilog are left alone by this one; each option's help is still
        # wrapped to the terminal, which is what a reader wants of a sentence and not of a table.
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "target",
        type=Path,
        nargs="?",
        default=Path("tests"),
        help="a case file or a directory to walk for contract-bearing cases (default: tests/)",
    )

    instead = parser.add_argument_group("instead of running the corpus")
    instead.add_argument(
        "--explain",
        action="store_true",
        help="narrate the derived run plan per case, without solving (a dry-run)",
    )
    instead.add_argument(
        "--print-schema",
        action="store_true",
        help="write the JSON schema of the machine-readable report to standard output and exit, "
        "without running anything. It is answered from the package alone, so the target and every "
        "dial of the run are ignored — but a command line that cannot be run is still refused",
    )

    report = parser.add_argument_group("the report")
    report.add_argument(
        "--format",
        choices=("human", "json"),
        default="human",
        help="who the report is written for: prose for a reader (the default), or one JSON "
        "document on standard output with every diagnostic moved to standard error, which is the "
        "published machine-readable contract --print-schema describes",
    )

    run = parser.add_argument_group("the run")
    run.add_argument(
        "--strict",
        action="store_true",
        help="fail the run on any corpus-hygiene issue (the CI gate): orphan libraries (warned by "
        "default) become errors, and undeclared solvers (silent by default) are required explicit",
    )
    run.add_argument(
        "--budget",
        type=float,
        default=TIME_BUDGET,
        metavar="SECONDS",
        help="per-solve time budget, a positive finite number of seconds. A budget hit before the "
        "solve decides is UNDECIDED and never FAIL; one hit after it decides keeps what was "
        f"decided, and only the checks that needed more of the search are UNDECIDED (default "
        f"{TIME_BUDGET}s)",
    )
    run.add_argument(
        "--deadline",
        type=float,
        default=None,
        metavar="SECONDS",
        help="stop starting new cases once solving has taken this long, a positive finite number "
        "of seconds; cases not reached are reported as not run. The clock starts after discovery, "
        "and it is checked between cases, so a solve already under way runs to its own --budget "
        "(off by default — --budget bounds one solve, this bounds the solving of the corpus)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> ExitStatus:
    """Run the ``elenctic`` CLI; return the process exit status (0 pass / 1 fail or undecided /
    2 a fault in the corpus / 3 an elenctic bug).

    The two outermost handlers are here because a fault that reaches this frame is by definition one
    no inner register anticipated, and the user still has to be told something they can act on. Each
    files the fault it met into an outcome of its own and reads the status off that, so the status
    follows from a record rather than being chosen beside one. Both leave by the same tail as an
    ordinary run, because a fault that stopped everything is still something the invocation
    produced, and a consumer handed nothing at all cannot tell it apart from a corpus that held no
    cases.

    The invocation is settled in this frame rather than one below it: below here it is a value of
    a type that cannot express a mode which produces no run, which is what lets running be total
    rather than something that has to refuse."""
    args = _build_parser().parse_args(argv)
    if (refusal := _refusal(args)) is not None:
        # A command line that cannot be run has produced no run, so there is nothing to report
        # about one: no record, no document, and nothing on standard output. That is what the
        # parser itself does with a flag it cannot read, and a machine consumer meets one thing
        # rather than two.
        print(f"usage error: {refusal}", file=sys.stderr)
        return ExitStatus.USER_FAULT
    # Settled above the guarded region rather than inside it, because a handler down there reports
    # a run that produced nothing else, and a machine-readable report has to say what the run was
    # asked to do. Neither step can fail here, and for the two flags that could the reason is
    # ordering rather than permissiveness: the record does refuse a duration that is not one, and
    # the refusal above has already returned on exactly those values. So what makes this safe is
    # that it stands below the refusal — move it above and the guard it depends on has not run.
    invocation = Invocation(
        target=args.target,
        strict=args.strict,
        budget=args.budget,
        deadline=args.deadline,
    )
    machine_readable = args.format == "json"
    try:
        if args.print_schema:
            return _print_schema()
        if not machine_readable:
            produced = explain_corpus(invocation) if args.explain else run_corpus(invocation)
            return exit_status(produced)
        # Discovery is inside the region with the rest of the run, because discovery grounds, and
        # the grounder writes where rebinding a Python stream cannot follow it.
        with _stdout_to_stderr():
            outcome = run_corpus(invocation)
    except MemoryError:
        # The backstop, for an allocation that fails where no case owns it. A case that runs out of
        # memory is caught in the run loop and costs only its own result; reaching this frame means
        # there was no case to report it against. Being unable to *bound* the resource — clingo's
        # API offers neither a clock nor a size limit on grounding — is not a reason to be unable
        # to *report* it. What consumed the memory is not knowable from here, so it is not claimed.
        print(f"resource error: {_CORPUS_OUT_OF_MEMORY}", file=sys.stderr)
        outcome = _fault_outcome(ErrorKind.RESOURCE, _CORPUS_OUT_OF_MEMORY)
    except Exception as exc:
        # Whatever this is, the user did not cause it and cannot fix it. Say so first, then show
        # the traceback: it is the report, not a failure to produce one. The record names the family
        # rather than rendering the exception, so the last frame that can report anything cannot
        # itself fail on a __repr__ that raises.
        print(
            f"internal error: {_INTERNAL_ERROR}. Please report it with the traceback below.",
            file=sys.stderr,
        )
        traceback.print_exc()
        outcome = _fault_outcome(ErrorKind.HARNESS, f"{_INTERNAL_ERROR}: {type(exc).__name__}")
    if machine_readable and not args.print_schema:
        # One write, made after the region has closed and never inside it, so standard output
        # carries a whole document or carries nothing at all — never the front half of one, cut
        # off by the fault that stopped the run.
        #
        # A document reports a run, so where no run was asked for there is none: a refused command
        # line produces nothing here, and neither does printing the description, whichever way that
        # fails. Reporting a fault in *that* as a run would describe a corpus nothing had looked at.
        _publish(dumps(as_json(outcome, invocation)))
    return exit_status(outcome)


def _refusal(args: argparse.Namespace) -> str | None:
    """Why this command line cannot be run, or ``None`` when it can.

    Answered before anything is discovered and before anything is printed, which is where the
    parser answers a flag it cannot read — so every refusal a reader can provoke arrives at the
    same point in the run, and none of them arrives after a run has half happened.

    What is asked here is what the parser cannot ask for itself: whether two flags that each make
    sense alone make sense together, and whether a number it converted is a number this program can
    use.
    """
    if args.explain and args.format == "json":
        return _NO_MACHINE_READABLE_DRY_RUN
    for flag, seconds, remedy in (
        ("--budget", args.budget, _UNBOUNDED_BUDGET),
        ("--deadline", args.deadline, _UNBOUNDED_DEADLINE),
    ):
        # Converting the text is as far as the parser goes: it accepts a zero, a negative, and both
        # spellings of a number that is not one. What counts as a length of time is asked of the
        # one predicate that answers it everywhere, so this refusal and the record's cannot come to
        # disagree; what is *said* about it is written here, because refusing what was typed, in
        # terms of what was typed, is the only frame that still knows which flag it came from.
        #
        # The remedy differs by flag because what the two do about "no limit" differs. The reader
        # most likely to type a zero here is one carrying over a solver convention in which zero
        # means unbounded, so the sentence that tells them what to do instead is the half of the
        # message they came for.
        if seconds is not None and not is_duration(seconds):
            return (
                f"{flag} takes a positive finite number of seconds, and this run was given "
                f"{seconds}. {remedy}"
            )
    return None


def _print_schema() -> ExitStatus:
    """Write the description of the machine-readable report, and say so if this copy has none.

    Answered from the package alone, so it is answered before anything is looked for on disk:
    someone asking what the output looks like need not have a corpus, and a target that does not
    exist must not turn the question into a fault. Written rather than printed, so what a reader
    redirects into a file is the file.

    An unreadable description is the environment being mis-shaped rather than elenctic being wrong
    about something, which is why it is graded as a fault the reader can fix and not as a bug to
    report. The status is read off a record like every other, rather than chosen beside one.
    """
    try:
        description = schema_text()
    except OSError:
        print(f"environment error: {_SCHEMA_UNREADABLE}", file=sys.stderr)
        return exit_status(_fault_outcome(ErrorKind.DISCOVERY, _SCHEMA_UNREADABLE))
    _publish(description)
    return ExitStatus.OK


def _publish(document: str) -> None:
    """Put a published artefact on standard output, encoded as UTF-8 whatever this environment's
    locale would have chosen.

    Both things written this way are JSON — the report, and the description of the report's shape —
    and JSON is UTF-8 by its own specification. Written through the text layer they would be encoded
    in whatever the environment picked, which on a machine whose standard output is ASCII does not
    write them at all: it raises, on a character the document is entitled to contain, and what
    reaches the consumer is a failure to produce a report rather than the report. The encoding of a
    published artefact belongs to the artefact.

    The text layer is emptied first so that anything already written to it stays ahead of these
    bytes. They are not flushed here: what a stream that cannot take them should do is one question
    and this is another, and leaving it to the interpreter keeps that answer in one place.
    """
    sys.stdout.flush()
    sys.stdout.buffer.write(document.encode("utf-8"))


def _fault_outcome(kind: ErrorKind, message: str) -> RunOutcome:
    """A run whose whole result is one corpus-level fault, met where no case owned it.

    A whole outcome rather than a record because such a fault *is* the whole of what the invocation
    produced, and the status is then the ordinary reading of an outcome rather than a number chosen
    beside one.

    No file is named, and there is none to name: each of the three frames that reaches this — an
    allocation that failed with no case running, a fault no register anticipated, and a copy of the
    package that cannot read its own description — knows something went wrong and not which file it
    was about. Claiming one would be worse than naming none."""
    return RunOutcome(
        cases=(),
        errors=(ErrorRecord(kind=kind, scope=Scope.CORPUS, source=None, message=message),),
        hygiene=(),
    )


@contextmanager
def _stdout_to_stderr() -> Iterator[None]:
    """Send everything written to the process's standard output to standard error instead, for the
    duration of the region.

    Under a machine-readable format the report is the only thing that may appear on standard
    output: one foreign byte and the document will not parse. The redirect is at the file-descriptor
    level rather than at ``sys.stdout``, because rebinding the Python object leaves anything writing
    to the descriptor beneath it untouched — a C library reached through a binding writes where it
    chooses, and a guarantee that holds only while a dependency keeps choosing well is not one. What
    would otherwise land beside the document is moved rather than discarded: a reader still sees it,
    just not where a parser is looking.

    What it catches is every write *made while the region is open*, at whatever level it is made.
    A writer that buffers below this process's control and empties that buffer after the region has
    closed writes to the descriptor as it is then, which is the restored standard output; no writer
    on the paths this drives is known to do that, and the distinction is recorded because the
    mechanism cannot enforce it.

    The two boundaries decide which stream holds what, which is why the buffer is emptied at each:
    output written before the region belongs on standard output, and output written inside it
    belongs with the diagnostics. Within the region the two streams are not ordered against each
    other — standard error is line-buffered and standard output need not be — so writes to the two
    can reach a reader in an order other than the one they were made in.

    The caller's side of the bargain: nothing inside the region may write to standard output, since
    for the length of it there is no way to reach it. Anything that asks the descriptor about itself
    — whether it is a terminal, how wide it is — is answered for standard error while it is open.
    """
    sys.stdout.flush()
    saved = os.dup(1)
    try:
        os.dup2(2, 1)
        yield
    finally:
        # The flush guards the restore, because it is the step that can fail: it is issued against
        # standard error, so whatever makes standard error unwritable meets it here. Left
        # unguarded, it would keep the descriptor diverted for the rest of the process and send the
        # report itself to the one stream this region exists to keep it out of.
        try:
            sys.stdout.flush()
        finally:
            os.dup2(saved, 1)
            os.close(saved)


if __name__ == "__main__":
    sys.exit(main())
