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

**What is this module's own, and what is not.** A command line, what it refuses, which of the three
things it can be asked to do this invocation is, and the backstops for a fault no register
anticipated — these are what is here, and each of them is about *this invocation*. Two more of a
program's concerns are not, and neither is a question about a command line:

- **the prose a reader sees**, which is about an :class:`~elenctic.outcome.Outcome`, and is in
  :mod:`elenctic.human_report` beside the document renderer it is the counterpart of;
- **the two streams**, which are about this process's descriptors, and are in
  :mod:`elenctic.streams` — one module down, because the first thing asked of them, giving this
  process a standard error before it writes anything, has to be asked by every stage entry point
  as well, and that module has no elenctic dependencies so all five reach it.

Everything below them is the library's:
``corpus.run_corpus`` and ``corpus.explain_corpus`` carry out an
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
import sys
import textwrap
import traceback
from collections.abc import Sequence
from contextlib import suppress
from json import JSONDecodeError
from pathlib import Path

from elenctic.corpus import explain_corpus, run_corpus
from elenctic.human_report import TerminalPlan, TerminalRun, announced, heading, render_tail
from elenctic.json_report import as_json, dumps, schema_text
from elenctic.outcome import (
    ErrorKind,
    ErrorRecord,
    ExitStatus,
    Invocation,
    Outcome,
    RunOutcome,
    Scope,
    exit_status,
    is_duration,
    render_seconds,
)
from elenctic.solvers import TIME_BUDGET
from elenctic.streams import (
    establish_standard_error,
    hand_over_standard_output,
    publish,
    stdout_to_stderr,
)

__all__ = ["main"]

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

# Where to take it. Asking a reader to report something without saying where leaves them to search
# for a project they may only know by the name of a command, so the address is written out. It is
# only in the diagnostic and never in the record: the record's message is carried into a published
# document, where a URL would be a second place this address has to stay true.
_ISSUES = "https://github.com/GregoryGelfond/elenctic/issues"

# The one thing --print-schema can fail at, said in terms the reader can act on. It is worth its own
# sentence rather than the internal-error backstop, because the backstop asks for a bug report and
# this is not a bug in elenctic: the description ships beside the modules, so a copy whose
# description is missing or damaged was assembled by something downstream — a vendoring step, a
# repackaging, an installer that keeps code and drops data, an archive that unpacked short. Sending
# that reader to elenctic's issue tracker sends them somewhere that cannot help them.
#
# Missing, damaged *or unreadable*, and all three words are load-bearing: a file that is present and
# half written is the same accident, and a sentence saying this copy "has the code and not the data"
# would be false of the reader most likely to be confused by it — the one who can see the file
# sitting there.
#
# The reader's own reason is carried, because it is the only thing that separates the remedies. A
# file that is absent is fixed by reinstalling; a file that is present and refused by its mode, or
# has a directory sitting where it should be, is not — a reinstall into the same prefix reproduces
# it. Nothing in this sentence could tell those apart, so it gave everybody the packaging answer and
# told half of them that something they *did* configure was done to them by a vendoring step.
_SCHEMA_UNREADABLE = (
    "elenctic could not read its own output description: {reason}. It ships inside the package, "
    "beside the modules, at elenctic/schema/ — so this copy of it is missing, damaged, or not "
    "readable, which is something about this installation rather than anything about your corpus. "
    "If the reason above is a permission, or something in the way, that is what to fix; otherwise "
    "reinstalling elenctic from a released wheel or from its source tree replaces the file. "
    "Nothing else is affected: running a corpus never reads this file."
)

# The same allocation failure met where the package's own description is being read, and it is
# worded separately from the corpus one for the reason that one is worded separately from the
# per-case one: a frame that ran no corpus cannot offer the remedy that bounds one. This answers
# from the package alone — nothing was walked, nothing was grounded, and no case ran — so the
# sentence that asks the reader to reduce what their corpus grounds describes a run that did not
# happen.
_DESCRIPTION_OUT_OF_MEMORY = (
    "elenctic ran out of memory reading its own output description. That is answered from the "
    "package alone, so no corpus was looked at and nothing was grounded: what ran short is the "
    "memory this process was given, or the packaged file is not the small one that ships. Nothing "
    "else is affected: running a corpus never reads this file."
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

# Why asking for an artefact with nowhere to put it is refused rather than attempted. Closing
# standard output is something a caller did on purpose, so it is answered the way the missing
# packaged description is: told plainly, not sent to the issue tracker. The human format is not
# refused for the same condition, and that is the distinction this program already draws rather
# than an inconsistency — a published artefact is the deliverable, and prose is a courtesy. Asking
# for a document with nowhere to write it is a contradiction; running a corpus with nobody to
# narrate to is an ordinary thing to want, and it still earns its exit status.
_NOWHERE_TO_PUBLISH = (
    "elenctic was asked to write to standard output, and this process has none: it was started "
    "with standard output closed. --format json writes one document there, and --print-schema "
    "writes the description of that document there. Leave standard output open, or ask for the "
    "human format, which writes prose when there is somewhere to write it and is silent when "
    "there is not."
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
    # Each of these replaces the run, so at most one of them can be what this invocation is. Said
    # to the parser rather than checked afterwards: a pairing the parser can refuse itself is one
    # `_refusal` should not have to remember, and the alternative is a precedence — whichever
    # branch happens to be tested first — which is a decision no surface states.
    actions = instead.add_mutually_exclusive_group()
    actions.add_argument(
        "--explain",
        action="store_true",
        help="narrate the derived run plan per case, without solving (a dry-run)",
    )
    actions.add_argument(
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
        # `:g` because the default is a float and its bare repr is `30.0`, which reads as a
        # precision the dial does not have; the README states the same number and states it as 30.
        f"decided, and only the checks that needed more of the search are UNDECIDED (default "
        f"{TIME_BUDGET:g}s)",
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

    Returns it on every path this module owns. ``argparse`` leaves by raising ``SystemExit`` instead
    for the two it owns — ``--help``, and a value it cannot parse — so a caller that invokes this
    directly rather than through the console script catches that as well.

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
    # First, and before the parser can write a word: everything past this line assumes there are
    # two streams to write to, and a process can be started with only one.
    establish_standard_error()
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
            produced: Outcome = (
                explain_corpus(invocation, observer=TerminalPlan())
                if args.explain
                else run_corpus(invocation, observer=TerminalRun())
            )
            # This format writes prose to standard output for the length of the run, so this is
            # where it is handed over; the other writes one document, and hands it over itself.
            # After the tail rather than around it: the tail writes to standard error, and a frame
            # that answered for that stream would answer the wrong one. The tally comes back here
            # to be written rather than being written there, so that every standard-output write a
            # broken reader can meet is one the hand-over made.
            # Two statements, so that what the tail writes to standard error and what is then
            # written to standard output are in the order they happen, on the page. Nested as
            # one expression the ordering rested on argument evaluation, which is invisible at
            # exactly the point somebody would reorder it — and it is the order this seam was
            # changed to establish.
            tally = render_tail(produced, invocation)
            hand_over_standard_output(prose=tally)
            return exit_status(produced)
        # Discovery is inside the region with the rest of the run, because discovery grounds, and
        # the grounder writes where rebinding a Python stream cannot follow it. So is the tail: the
        # tally is written to standard output, and under this format standard output belongs to the
        # document alone.
        with stdout_to_stderr():
            outcome = run_corpus(invocation, observer=TerminalRun())
            # Written inside the region, where standard output is standard error: under this
            # format the tally is a diagnostic like the two above it, and the document owns the
            # stream. Answered like them too — a stream that will not take a diagnostic does not
            # get to stop the document being published, and this was the last of the three that
            # could still reach the backstop and be reported as a bug in elenctic.
            tally = render_tail(outcome, invocation)
            with suppress(OSError):
                print(tally, end="")
    except MemoryError:
        # The backstop, for an allocation that fails where no case owns it. A case that runs out of
        # memory is caught in the run loop and costs only its own result; reaching this frame means
        # there was no case to report it against. Being unable to *bound* the resource — clingo's
        # API offers neither a clock nor a size limit on grounding — is not a reason to be unable
        # to *report* it. What consumed the memory is not knowable from here, so it is not claimed.
        resource = _unowned_fault(ErrorKind.RESOURCE, _CORPUS_OUT_OF_MEMORY)
        print(announced(resource), file=sys.stderr)
        outcome = _fault_outcome(resource)
    except Exception as exc:
        # Whatever this is, the user did not cause it and cannot fix it. Say so first, then show
        # the traceback: it is the report, not a failure to produce one. The record names the family
        # rather than rendering the exception, so the last frame that can report anything cannot
        # itself fail on a __repr__ that raises.
        internal = _unowned_fault(ErrorKind.HARNESS, f"{_INTERNAL_ERROR}: {type(exc).__name__}")
        print(
            f"{heading(internal.kind, internal.scope)} {_INTERNAL_ERROR}. Please report it at\n"
            f"{_ISSUES}, with the traceback below.",
            file=sys.stderr,
        )
        traceback.print_exc()
        outcome = _fault_outcome(internal)
    if machine_readable and not args.print_schema:
        # One write, made after the region has closed and never inside it, so standard output
        # carries a whole document or carries nothing at all — never the front half of one, cut
        # off by the fault that stopped the run.
        #
        # A document reports a run, so where no run was asked for there is none: a refused command
        # line produces nothing here, and neither does printing the description, whichever way that
        # fails. Reporting a fault in *that* as a run would describe a corpus nothing had looked at.
        publish(dumps(as_json(outcome, invocation)))
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
    # Whether this process has a standard output at all is exactly what the parser cannot ask for
    # itself, and it is asked here for the reason every other refusal is: a command line elenctic
    # cannot carry out is refused before anything is discovered, so a report is whole or absent and
    # never half written. Met mid-run instead, both of these reached the backstop that tells a
    # reader they have found a bug in this program — over a stream they closed themselves.
    if sys.stdout is None and (args.format == "json" or args.print_schema):
        return _NOWHERE_TO_PUBLISH
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
                f"{render_seconds(seconds)}. {remedy}"
            )
    return None


def _print_schema() -> ExitStatus:
    """Write the description of the machine-readable report, and say so if this copy has none.

    Answered from the package alone, so it is answered before anything is looked for on disk:
    someone asking what the output looks like need not have a corpus, and a target that does not
    exist must not turn the question into a fault. Written rather than printed, so what a reader
    redirects into a file is the file.

    Several mechanisms and one sentence, because the argument below covers all of them: a step that
    drops the data file, one that puts something else where it goes or leaves it unreadable, one
    that re-encodes it, and one that leaves it half written. Only the first two raise ``OSError``,
    and catching those and not the rest sent the other readers to the backstop that asks for a bug
    report. What differs between them is the remedy, and that is why the reader's own reason is
    carried into the sentence rather than dropped.

    Named one at a time rather than caught as the ``ValueError`` two of them share, because a
    fault here that is *none* of them is elenctic being wrong about something and belongs at that
    backstop. Widening the catch to cover a mechanism nobody anticipated would tell a reader to
    reinstall a package that is fine.

    The allocation failure is answered here rather than left to the run's, for the same reason the
    run's is worded separately from a case's: this path walks no target and grounds nothing, so the
    remedy that asks for a corpus to be bounded is about a run that did not happen.

    An unreadable description is the environment being mis-shaped rather than elenctic being wrong
    about something, which is why it is graded as a fault the reader can fix and not as a bug to
    report. The status is read off a record like every other, rather than chosen beside one.
    """
    try:
        description = schema_text()
    # Parenthesised deliberately, and pinned so the formatter leaves it: PEP 758 (new in
    # 3.14) makes the bare form legal and `ruff format` canonicalises to it, but that form
    # reads as a Python 2 syntax error to anyone whose Python predates 3.14. Same meaning,
    # and one of the two spellings is misread on sight.
    except (OSError, UnicodeDecodeError, JSONDecodeError) as fault:  # fmt: skip
        # The reader's own reason, carried raw. It comes from outside this program — it quotes a
        # path chosen by whoever installed the package, and a terminal acts on some of what a path
        # may contain — so it is made safe by whoever shows it, which is the rule every other
        # record follows. Sanitized here instead it was safe once and escaped twice: the renderer
        # sanitizes what it is handed, and doubling a backslash is not an idempotent act.
        reason = _SCHEMA_UNREADABLE.format(reason=str(fault))
        unreadable = _unowned_fault(ErrorKind.ENVIRONMENT, reason)
        print(announced(unreadable), file=sys.stderr)
        return exit_status(_fault_outcome(unreadable))
    except MemoryError:
        exhausted = _unowned_fault(ErrorKind.RESOURCE, _DESCRIPTION_OUT_OF_MEMORY)
        print(announced(exhausted), file=sys.stderr)
        return exit_status(_fault_outcome(exhausted))
    publish(description)
    return ExitStatus.OK


def _unowned_fault(kind: ErrorKind, message: str) -> ErrorRecord:
    """One fault met where no case owned it, and which therefore cost the whole run.

    No file is named. Two of the three frames that reach this — an allocation that failed with no
    case running, and a fault no register anticipated — know something went wrong and not which file
    it was about, and claiming one would be worse than naming none. The third knows its file exactly
    and still names none, for a different reason: ``source`` is a path into the corpus under test,
    resolved the way a case's is, and the description this frame could not read lives inside the
    installed package. Putting one where the other is expected would send a reader looking for it in
    their own tree.

    Built before the reader is told anything, rather than after, so that what is printed and what is
    reported are the one record read twice — and now literally so, since what is printed is this
    record put through the renderer every other record goes through. These three frames used to
    choose their own heading beside the record and each chose a different word for it, which is how
    a fault filed under one locus came to be announced as another.

    ``message`` is carried **raw**, whatever it quotes, on the same terms as every other record's:
    a record is a value and making text safe to show belongs to whoever shows it. A frame that
    sanitizes on the way in hands a renderer something already escaped, and escaping is not an
    idempotent act — one of these three did exactly that, and a document carrying the result would
    have shown a reader two backslashes where their path had one."""
    return ErrorRecord(kind=kind, scope=Scope.CORPUS, source=None, message=message)


def _fault_outcome(record: ErrorRecord) -> RunOutcome:
    """A run whose whole result is one fault.

    A whole outcome rather than a record because such a fault *is* the whole of what the invocation
    produced, and the status is then the ordinary reading of an outcome rather than a number chosen
    beside one."""
    return RunOutcome(cases=(), errors=(record,), hygiene=())


if __name__ == "__main__":
    sys.exit(main())
