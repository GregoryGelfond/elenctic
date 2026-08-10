"""The ``elenctic`` console entry: three commands, and the dials each of them reads.

``elenctic run [target]`` discovers cases under ``target`` — a single ``.lp`` case file or a
directory walked for contract-bearing files (default ``tests/``) — validates **every** case's run
plan up front (so a misroute, which is a harness bug, is reported before any solving), then solves
and checks each case, rendering any non-``PASS`` outcome. ``elenctic explain [target]`` stops after
the plan: it narrates the derived runs (mode + checks) per case without solving, the dry run the
``reads``/``populates`` surface was made introspectable for. ``elenctic schema`` writes the
description of the machine-readable report, answered from the installed package alone.

**Commands rather than flags, and what that changes is what can be typed.** Each of the three
replaces the others, so at most one of them is what an invocation is — and while that was two
booleans, four states could be written down, three of them meant something, and which flag won when
both were given was settled by the order two statements happened to be in. A command word makes the
fourth state unspellable instead of refused, and it carries the dials with it: ``--budget`` and
``--deadline`` bound solving, so only ``run`` has them; ``schema`` takes no target because it looks
at none.

``run --format`` chooses who the report is written for. The default writes prose for a reader.
``--format json`` writes the whole run as one machine-readable document on standard output and
moves every diagnostic to standard error, so that nothing a consumer's parser would choke on lands
beside the document; ``elenctic schema`` describes that document's shape without running anything.

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
from enum import Enum
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


class _Command(Enum):
    """The three things elenctic can be asked to do, as one value with three cases.

    This module's opening paragraph has always said an invocation *is* one of three things. The code
    said it with two independent booleans, which can be written down four ways — and the fourth,
    both at once, was answered by whichever ``if`` had been written first. That is a decision no
    surface states, so no reader could have found it, and no test could have been about it.

    Held as an enumeration rather than as the strings the parser produces, because everything that
    asks *which* of the three this is wants to be told when a fourth appears. ``match`` over these
    with :func:`typing.assert_never` is checked; ``==`` against a ``str`` is not, and a command
    added without a home would simply fall through to whichever arm was last.

    The values are the words a reader types, and the parser is built from them, so the word on the
    command line and the case in this type cannot come to differ.
    """

    RUN = "run"
    EXPLAIN = "explain"
    SCHEMA = "schema"


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

# The one thing the schema command can fail at, said in terms the reader can act on. It is worth its
# own sentence rather than the internal-error backstop, because the backstop asks for a bug report
# and this is not a bug in elenctic: the description ships beside the modules, so a copy whose
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

# Why asking for an artefact with nowhere to put it is refused rather than attempted. Closing
# standard output is something a caller did on purpose, so it is answered the way the missing
# packaged description is: told plainly, not sent to the issue tracker. The human format is not
# refused for the same condition, and that is the distinction this program already draws rather
# than an inconsistency — a published artefact is the deliverable, and prose is a courtesy. Asking
# for a document with nowhere to write it is a contradiction; running a corpus with nobody to
# narrate to is an ordinary thing to want, and it still earns its exit status.
_NOWHERE_TO_PUBLISH = (
    "elenctic was asked to write to standard output, and this process has none: it was started "
    "with standard output closed. run --format json writes one document there, and schema writes "
    "the description of that document there. Leave standard output open, or ask for the human "
    "format, which writes prose when there is somewhere to write it and is silent when there is "
    "not."
)


# What --strict does, written once for the two commands that offer it. Both grade a corpus: hygiene
# is settled at discovery, so the dry run reports and escalates it exactly as a real run does. The
# sentence says "fail" rather than "fail the run", which is what makes one sentence true of both.
_STRICT = (
    "fail on any corpus-hygiene issue (the CI gate): orphan libraries (warned by default) become "
    "errors, and undeclared solvers (silent by default) are required explicit"
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
    """The command line: three commands, each carrying the dials it reads and no others.

    A dial a command does not read is worse than an absent one, and elenctic had three of them: the
    dry run accepted ``--budget`` and ``--deadline``, read neither, and still refused a value of
    either that was not a duration; the description accepted both plus ``--strict`` and a target,
    and looked at none of them. Its own help *said* so — "the target and every dial of the run are
    ignored" — which is the sentence a grammar makes unnecessary by not offering them.

    Each command's options are filed under a heading saying what they are for, and the catch-all is
    left to the one option this program did not define. The closing text, which says what the run
    leaves with, is the whole program's rather than any command's, so it is written once here — the
    one thing ``argparse`` never volunteers and the one a script has to know.
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
    # Required, so that a command line naming no command is refused before anything is discovered —
    # which is what the closing text above it already promises of any command line elenctic cannot
    # use. There is deliberately no default command: `elenctic explain` would then mean either the
    # dry run or a corpus in a directory called `explain`, and whatever settled that would be a
    # precedence no surface states, which is the thing this grammar exists to remove.
    commands = parser.add_subparsers(dest="command", required=True, title="commands")

    runner = commands.add_parser(
        _Command.RUN.value,
        help="run the corpus and check every case against its contract",
        description="Discover the cases under `target`, validate every case's run plan before any "
        "solving, then solve and check each one. Only a case that did not pass is rendered.",
    )
    _add_target(runner)
    report = runner.add_argument_group("the report")
    report.add_argument(
        "--format",
        choices=("human", "json"),
        default="human",
        help="who the report is written for: prose for a reader (the default), or one JSON "
        "document on standard output with every diagnostic moved to standard error, which is the "
        "published machine-readable contract `elenctic schema` describes",
    )
    run = runner.add_argument_group("the run")
    run.add_argument("--strict", action="store_true", help=_STRICT)
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

    explainer = commands.add_parser(
        _Command.EXPLAIN.value,
        help="narrate the run plan each case derives, without solving (a dry run)",
        description="Narrate the runs each case derives — the mode, and what every check reads — "
        "without solving anything. This version describes no machine-readable form for a plan, so "
        "there is no --format to ask for here; it is one of `run`'s.",
    )
    _add_target(explainer)
    explainer.add_argument_group("the run").add_argument(
        "--strict", action="store_true", help=_STRICT
    )

    commands.add_parser(
        _Command.SCHEMA.value,
        help="write the description of the machine-readable report, and nothing else",
        description="Write the JSON schema of the document `elenctic run --format json` writes, to "
        "standard output. It is answered from the installed package alone — nothing is walked and "
        "nothing is solved — which is why this command takes neither a target nor any dial of a "
        "run. A command line it cannot use is still refused.",
    )
    return parser


def _add_target(command: argparse.ArgumentParser) -> None:
    """The corpus a command is pointed at, for the two commands that look at one.

    Written once rather than twice because it is one thing a reader learns, and a second copy is a
    second sentence to keep true. ``schema`` is not given it: what it writes is the same whatever is
    on disk, so a target there could only be accepted and ignored.
    """
    command.add_argument(
        "target",
        type=Path,
        nargs="?",
        default=Path("tests"),
        help="a case file or a directory to walk for contract-bearing cases (default: tests/)",
    )


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

    **The description is carried out in a guarded frame of its own**, above the invocation rather
    than inside it, and that is forced rather than chosen: it has no target and no dials, so there
    is no invocation for it to be carried out under — and a document published below would then be
    reading a name bound on some paths and not on the one a handler arrives by. It is guarded all
    the same, because a fault no register anticipated is one wherever it is met.

    The invocation is settled in this frame rather than one below it: below here it is a value of
    a type that cannot express a mode which produces no run, which is what lets running be total
    rather than something that has to refuse."""
    # First, and before the parser can write a word: everything past this line assumes there are
    # two streams to write to, and a process can be started with only one.
    establish_standard_error()
    args = _build_parser().parse_args(argv)
    # Which of the three this invocation is, settled here and read as that everywhere below. The
    # parser restricts the word to the three, so this cannot fail on anything a command line says.
    command = _Command(args.command)
    if (refusal := _refusal(command, args)) is not None:
        # A command line that cannot be run has produced no run, so there is nothing to report
        # about one: no record, no document, and nothing on standard output. That is what the
        # parser itself does with a flag it cannot read, and a machine consumer meets one thing
        # rather than two.
        print(f"usage error: {refusal}", file=sys.stderr)
        return ExitStatus.USER_FAULT
    if command is _Command.SCHEMA:
        try:
            return _describe()
        except MemoryError:
            # Answered here rather than by the corpus's sentence below, which is the whole reason
            # the two are worded apart: this frame walked nothing and ground nothing, so asking the
            # reader to reduce what their corpus grounds would describe a run that did not happen.
            return exit_status(_announce_fault(ErrorKind.RESOURCE, _DESCRIPTION_OUT_OF_MEMORY))
        except Exception as exc:
            return exit_status(_internal_fault(exc))
    # Settled above the guarded region rather than inside it, because a handler down there reports
    # a run that produced nothing else, and a machine-readable report has to say what the run was
    # asked to do. Neither step can fail here, and for the two dials that could the reason is
    # ordering rather than permissiveness: the record does refuse a duration that is not one, and
    # the refusal above has already returned on exactly those values. So what makes this safe is
    # that it stands below the refusal — move it above and the guard it depends on has not run.
    #
    # The dry run is given neither duration, because it reads neither: it solves nothing, so there
    # is no solve for a budget to bound and no clock for a deadline to be checked against. The
    # defaults it gets instead are the library's own, and nothing looks at them.
    invocation = (
        Invocation(
            target=args.target, strict=args.strict, budget=args.budget, deadline=args.deadline
        )
        if command is _Command.RUN
        else Invocation(target=args.target, strict=args.strict)
    )
    machine_readable = command is _Command.RUN and args.format == "json"
    try:
        if not machine_readable:
            produced: Outcome = (
                explain_corpus(invocation, observer=TerminalPlan())
                if command is _Command.EXPLAIN
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
        outcome = _announce_fault(ErrorKind.RESOURCE, _CORPUS_OUT_OF_MEMORY)
    except Exception as exc:
        outcome = _internal_fault(exc)
    if machine_readable:
        # One write, made after the region has closed and never inside it, so standard output
        # carries a whole document or carries nothing at all — never the front half of one, cut
        # off by the fault that stopped the run.
        #
        # A document reports a run, so where no run was asked for there is none: a refused command
        # line produces nothing here, and neither does the description, whichever way that fails —
        # which is now a fact about where that command is carried out rather than a second clause
        # here. Reporting a fault in *that* as a run would describe a corpus nothing had looked at.
        publish(dumps(as_json(outcome, invocation)))
    return exit_status(outcome)


def _refusal(command: _Command, args: argparse.Namespace) -> str | None:
    """Why this command line cannot be run, or ``None`` when it can.

    Answered before anything is discovered and before anything is printed, which is where the
    parser answers a flag it cannot read — so every refusal a reader can provoke arrives at the
    same point in the run, and none of them arrives after a run has half happened.

    What is asked here is what the parser cannot ask for itself: whether this process has the stream
    an artefact would go to, and whether a number it converted is a number this program can use. It
    used to ask a third thing — whether two flags that each make sense alone make sense together —
    and that question is now the grammar's, which is what a command word buys.
    """
    # Whether this process has a standard output at all is exactly what the parser cannot ask for
    # itself, and it is asked here for the reason every other refusal is: a command line elenctic
    # cannot carry out is refused before anything is discovered, so a report is whole or absent and
    # never half written. Met mid-run instead, both of these reached the backstop that tells a
    # reader they have found a bug in this program — over a stream they closed themselves.
    if sys.stdout is None and (
        command is _Command.SCHEMA or (command is _Command.RUN and args.format == "json")
    ):
        return _NOWHERE_TO_PUBLISH
    if command is not _Command.RUN:
        # The two durations below are `run`'s alone — they bound solving, and neither other command
        # solves — so they are not on those command lines to be asked about. An `if` rather than a
        # third arm saying nothing: two of the three have nothing further to be refused for, and
        # writing that out as two empty arms would be a symmetry the commands do not have.
        return None
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


def _describe() -> ExitStatus:
    """Write the description of the machine-readable report, and say so if this copy has none.

    Answered from the package alone, so it is answered before anything is looked for on disk:
    someone asking what the output looks like need not have a corpus. That the target cannot turn
    the question into a fault is now the grammar's doing rather than this frame's — the command
    takes none. Written rather than printed, so what a reader redirects into a file is the file.

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

    The allocation failure met *reading* the file is answered here, for the reason the run's is
    worded separately from a case's: this path walks no target and grounds nothing, so the remedy
    that asks for a corpus to be bounded is about a run that did not happen. One met *writing* it is
    answered by the frame in :func:`main` that calls this, with the same sentence — it used to fall
    through to the corpus's, which told a reader who ran no corpus to reduce what theirs grounds.

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
        return exit_status(_announce_fault(ErrorKind.ENVIRONMENT, reason))
    except MemoryError:
        return exit_status(_announce_fault(ErrorKind.RESOURCE, _DESCRIPTION_OUT_OF_MEMORY))
    publish(description)
    return ExitStatus.OK


def _announce_fault(kind: ErrorKind, message: str) -> RunOutcome:
    """Tell the reader about a fault no register anticipated, and hand back the outcome it is the
    whole of.

    Four frames reach this — an allocation that failed with no case to charge it to, one that failed
    reading the packaged description, one that failed writing it, and a description this copy has
    not got — and each used to write the same three steps out for itself. Written once, they cannot
    come to differ: the record is built before the reader is told anything, what is printed is that
    record through the renderer every other record goes through, and the status the caller reads is
    a reading of the outcome rather than a number chosen beside it.

    Not for the fault nobody anticipated at all, which says something deliberately different and has
    :func:`_internal_fault` of its own.
    """
    record = _unowned_fault(kind, message)
    print(announced(record), file=sys.stderr)
    return _fault_outcome(record)


def _internal_fault(exc: Exception) -> RunOutcome:
    """Say that a fault no register anticipated is elenctic's own, show the traceback, and hand back
    the outcome it is the whole of.

    Whatever this is, the user did not cause it and cannot fix it. Say so first, then show the
    traceback: it is the report, not a failure to produce one. The record names the family rather
    than rendering the exception, so the last frame that can report anything cannot itself fail on a
    ``__repr__`` that raises.

    What is printed is deliberately not the record's message, which is why this does not go through
    :func:`_announce_fault`: the address to report it at belongs in the diagnostic and not in the
    record, because the record's message is carried into a published document, where a URL would be
    a second place this address has to stay true.
    """
    internal = _unowned_fault(ErrorKind.HARNESS, f"{_INTERNAL_ERROR}: {type(exc).__name__}")
    print(
        f"{heading(internal.kind, internal.scope)} {_INTERNAL_ERROR}. Please report it at\n"
        f"{_ISSUES}, with the traceback below.",
        file=sys.stderr,
    )
    traceback.print_exc()
    return _fault_outcome(internal)


def _unowned_fault(kind: ErrorKind, message: str) -> ErrorRecord:
    """One fault met where no case owned it, and which therefore cost the whole run.

    No file is named, by any of them. An allocation that failed with no case running, and a fault
    no register anticipated, know something went wrong and not which file it was about, and claiming
    one would be worse than naming none. A fault met over the packaged description knows its file
    exactly and still names none, for a different reason: ``source`` is a path into the corpus under
    test, resolved the way a case's is, and that description lives inside the installed package.
    Putting one where the other is expected would send a reader looking for it in their own tree.

    Built before the reader is told anything, rather than after, so that what is printed and what is
    reported are the one record read twice — and now literally so, since what is printed is this
    record put through the renderer every other record goes through. Its callers used to choose
    their own heading beside the record and each chose a different word for it, which is how a fault
    filed under one locus came to be announced as another.

    ``message`` is carried **raw**, whatever it quotes, on the same terms as every other record's:
    a record is a value and making text safe to show belongs to whoever shows it. A frame that
    sanitizes on the way in hands a renderer something already escaped, and escaping is not an
    idempotent act — the one carrying a reason from outside this program did exactly that, and a
    document carrying the result would have shown a reader two backslashes where their path had
    one."""
    return ErrorRecord(kind=kind, scope=Scope.CORPUS, source=None, message=message)


def _fault_outcome(record: ErrorRecord) -> RunOutcome:
    """A run whose whole result is one fault.

    A whole outcome rather than a record because such a fault *is* the whole of what the invocation
    produced, and the status is then the ordinary reading of an outcome rather than a number chosen
    beside one."""
    return RunOutcome(cases=(), errors=(record,), hygiene=())


if __name__ == "__main__":
    sys.exit(main())
