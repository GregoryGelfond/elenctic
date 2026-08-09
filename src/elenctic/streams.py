"""The streams a program is owed: established before it writes anything, and answered for after.

Every way elenctic can be *run* — the console entry, and each pipeline stage under
``python -m elenctic.<stage>`` — is a program handed a process, and a process can be started
missing a stream rather than having it pointed somewhere. What this language does with that absence
is quiet and costly, and the answer to it is the same wherever it is asked, so it is stated once
here and asked by each entry point rather than restated in five places that can drift apart.

Past that beginning, the console entry has three more questions about the same two streams and
nobody else has any: where a published artefact goes, what is owed to a reader who stopped reading,
and how to keep everything but the document off standard output while a run is going. They are
here rather than beside the command line because none of them is a question about a command line —
each is a fact about this process's descriptors, and a reader looking for one should not have to
read an argument parser to find it.

This module has no elenctic dependencies, which is what lets every entry point reach it: the stages
sit at different layers and the console entry imports all of them, so a rule any of them can ask has
to live below all of them. It is not part of the curated surface — a consumer composing elenctic's
pieces owns their own process and its streams; this is what *being run as a program* needs.
"""

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress

__all__ = [
    "establish_standard_error",
    "hand_over_standard_output",
    "publish",
    "stdout_to_stderr",
]

# What a reader is told when nothing was left to write to. It is not a fault — not in the corpus,
# and not in elenctic — so it files no record and changes no status: whatever the process was going
# to leave with, it still leaves with. What it owes the reader is the one fact they cannot see from
# where they are standing, which is that what they hold is not all of it.
#
# Three of its words are chosen against a path each. It opens on a noun, as every other heading this
# program writes does, so a reader meeting it at the end of a log has a subject rather than an
# adjective; "output" rather than "report", because the description of the report's shape is written
# the same way and is answered without a corpus being looked at. It does not say the writing stopped
# *part-way*, because a reader can go before the first byte lands and then nothing reached them at
# all. And the reassurance names its subject, because on a run the backstop has already reported an
# unqualified "nothing else is affected" reads as a claim about the run, directly under a line
# saying the run went wrong.
_REPORT_CUT_SHORT = (
    "output cut short: nothing is reading standard output, so what reached the other end is "
    "incomplete. Losing the reader affected nothing else — this leaves with the status it would "
    "have left with anyway. Whoever needs the whole of it should read to the end, or write it to a "
    "file and read the file."
)


def establish_standard_error() -> None:
    """Give this process a standard error where it has none, before anything is written.

    A process can be started with the descriptor closed rather than redirected — ``2>&-`` in a
    shell — and one absence then costs the run two different things, which is why it is established
    here rather than guarded twice.

    The first is that this language answers a missing standard error by leaving ``sys.stderr`` as
    ``None``, and ``print`` writes to standard output when handed that. Under a machine-readable
    format standard output is the document's alone, so every diagnostic written outside the
    redirect region lands in the middle of the report and no consumer can parse it. Nothing about
    the run went wrong, so a passing corpus reports success and hands back something unreadable —
    the worst shape a defect can take, because the status says there is nothing to look into. A
    stage module run for inspection has the same stream and a smaller version of the same problem:
    what lands in its payload is the usage line refusing the command it was given.

    The second is that a closed descriptor is the lowest free number, so it is the first thing
    handed out: the copy of standard output :func:`stdout_to_stderr` takes on its way in *becomes*
    descriptor 2, and the region then points standard output at standard output and moves nothing
    anywhere.

    The null device is what goes there, because closing the descriptor and pointing it at the null
    device are two spellings of one wish and only one of them worked. Nothing is written that would
    not have been written anyway, and what is written goes nowhere — which is what closing the
    descriptor asked for.

    **The two are asked separately, and that is the whole of this function's shape.** They arrive
    together — one closed descriptor causes both — but they are cured by different acts and they
    stop coinciding almost immediately. Descriptor 2 being free is a fact with a lifetime: it is the
    next number handed out, and this runs *after* the entire import graph has loaded. Anything that
    opened a file on the way took it. Then a probe of the descriptor succeeds while ``sys.stderr``
    is still unbuilt, and a guard that read the first as an answer to the second would skip its own
    body and leave every diagnostic going to standard output — the defect this exists to prevent,
    restored by the thing meant to prevent it, and with nothing to see.

    So the stream is rebuilt on ``sys.stderr is None``, which is the condition it is about, and the
    descriptor is repaired on the descriptor being gone, which is the condition *that* is about.

    **What the rebuilt stream is written to, when something else took descriptor 2.** Descriptor 2,
    still — because at that point descriptor 2 *is* this process's standard error, whatever opened
    it. Every library in the process that writes to standard error is already writing there, and a
    stream of ours pointed somewhere else would be the one thing in the process disagreeing about
    where standard error is. Nothing here can undo an import having taken that number; what it can
    do is not compound it by writing diagnostics into the payload instead.

    **If the null device cannot be opened** — no ``/dev/null`` in a chroot, or no descriptors left —
    this raises rather than returning quietly, and that is deliberate. The postcondition cannot be
    met, and a caller told so loudly is better off than one whose next diagnostic silently lands in
    the report it was writing.
    """
    try:
        os.fstat(2)
    except OSError:
        # The same rule that causes the second problem answers this one: the lowest free descriptor
        # is what gets handed out, and descriptor 2 is free — so opening the null device *is*
        # opening descriptor 2, and there is nothing further to do. Only where a lower descriptor is
        # missing as well does the copy have to be moved into place and the original released; doing
        # it unconditionally closes descriptor 2 again, one statement after opening it.
        null = os.open(os.devnull, os.O_WRONLY)
        if null != 2:
            try:
                os.dup2(null, 2)
            finally:
                os.close(null)
    # Rebuilt only where this language left it unbuilt, so a caller who supplied a stream of their
    # own keeps it. Line buffered and lenient about a character it cannot encode, which is what an
    # interpreter gives a standard error it builds for itself.
    #
    # Outside the arm above, not inside it: what is repaired there is the descriptor, and this is
    # about the stream. Descriptor 2 is open by the time this is reached either way — it already
    # was, or the arm above has just made it so.
    if sys.stderr is None:
        sys.stderr = os.fdopen(2, "w", buffering=1, errors="backslashreplace", closefd=False)


def publish(document: str) -> None:
    """Put a published artefact on standard output, encoded as UTF-8 whatever this environment's
    locale would have chosen — or say why the reader did not get it.

    Both things written this way are JSON — the report, and the description of the report's shape —
    and JSON is UTF-8 by its own specification. Written through the text layer they would be encoded
    in whatever the environment picked, which on a machine whose standard output is ASCII does not
    write them at all: it raises, on a character the document is entitled to contain, and what
    reaches the consumer is a failure to produce a report rather than the report. The encoding of a
    published artefact belongs to the artefact.

    Handing the bytes over is part of publishing rather than something left for the interpreter to
    finish, because a reader who has stopped reading can be answered while this frame is still
    standing and cannot be answered after it has returned. Left pending, that arrives too late to
    say anything about, and what reaches the reader instead is the name of an exception and a status
    this program's ladder does not publish. How much a stream holds before it writes through decides
    which of the two a given run meets, and that number belongs to the language rather than to this
    project.

    Both the encoding above and the handing over below are the artefact's own business, which is why
    they are one step and not two: an artefact half encoded and never delivered is the shape this
    exists to make impossible.
    """
    hand_over_standard_output(document.encode("utf-8"))


def hand_over_standard_output(published: bytes = b"", *, prose: str = "") -> None:
    """Write anything still owed to standard output, empty it, and answer once if no reader is
    left.

    Two payloads, because there are two kinds of thing to write and they belong to different
    layers. ``published`` is an artefact that carries its own encoding — the machine-readable
    document, UTF-8 by its own specification — and goes to the byte layer for the reason given
    below. ``prose`` is the run's own last sentence, which belongs to whatever encoding the
    environment picked for everything else the run printed, and goes through the text layer. Both
    arrive here rather than being written by their callers so that every standard-output write on
    either path is one this frame makes, which is what lets a failure be read as a fact about
    standard output.

    A reader that stops — a pager quit, a ``head`` that had enough, a consumer that found what it
    came for — leaves every further write with nowhere to land. It is neither a fault in the corpus
    nor a fault in elenctic, and the only thing owed is to say so: whatever the process was going to
    leave with, it still leaves with. A status saying otherwise would fail a job for the plumbing
    around it, and *which* wrong status it said would depend on where the write happened to be.

    Emptying the stream here is what makes that one answer possible. Whatever is still held is
    written where a failure can still be reported, rather than after the last frame that could say
    anything has returned — and the descriptor is then pointed at the null device, so that what is
    still pending is discarded rather than met a second time by an interpreter that answers
    differently.

    **Every write this can fail on is one this frame makes**, which is what lets a failure be read
    as a fact about standard output. Written as a region wrapped around a caller's work instead, it
    would answer for whatever that work wrote — and the tail of a run writes to *both* streams, so
    a broken standard error came back as a sentence about standard output and took a healthy
    standard output down with it, discarding the report a reader was going to keep.

    The property is narrower than *every* write this program makes to standard output, and saying
    which is the difference between a reader predicting the runtime and being surprised by it. A run
    narrating itself writes a line per case, through an observer — and those writes are isolated by
    the corpus's announcement seam, which swallows a lost reader, reports it once to a logger nobody
    has configured, and lets the run go on writing into a dead pipe. On a stream that writes through
    it is the *first* of those, not this frame, that meets the lost reader; what is lost with it
    is a case's report, and the run says nothing about that until it arrives here.

    What holds is that every standard-output write whose failure would otherwise reach the backstop
    is one this frame makes. The tail's own tally used to be the exception — written elsewhere, it
    failed before this was ever reached and was answered as a bug in elenctic. It hands the tally
    back to be written here now.

    That event and no other. Standard output can refuse the bytes for reasons that are nothing to do
    with a reader — no space left, a device that failed — and those have a different remedy, a
    different owner, and no answer this frame is in a position to give.

    Afterwards, on the path that answered, standard output is the null device for the rest of the
    process: what was pending has nowhere left to fail, and anything written later goes nowhere and
    is not reported again.
    """
    # A process can be started with standard output closed, and then there is nothing to hand over:
    # this language leaves ``sys.stdout`` unbuilt, ``print`` writes nowhere without complaining, and
    # no bytes are held anywhere. It is not the missing standard error `establish_standard_error`
    # repairs on the way in — that absence costs the document its stream, and this one means there
    # is no document to write — so the two are not answered the same way.
    if sys.stdout is None:
        return
    try:
        # The text layer first, so that anything already written to it stays ahead of these bytes;
        # then the bytes; then the whole of it, so the hand-over either happens or is reported.
        #
        # Nothing to publish is the ordinary case — a run that wrote its report as it went is here
        # to have that handed over and to write its last sentence — and asking for the byte layer
        # at all is what a caller who replaced standard output with a text stream of their own
        # cannot answer. Writing no bytes must not be the thing that narrows what this accepts,
        # which is why the prose above is not encoded into the same argument.
        if prose:
            sys.stdout.write(prose)
        sys.stdout.flush()
        if published:
            sys.stdout.buffer.write(published)
        sys.stdout.flush()
    except BrokenPipeError:
        # Saying it can meet the very fault it is about. Standard error redirected onto standard
        # output — `2>&1 | head`, an ordinary way to read a long report — puts this sentence on the
        # stream that stopped being read, and there is then nowhere left to answer from. Nothing can
        # be done about that, and it must not become a second failure stacked on the first: the
        # frame whose whole job is to answer a reader who has gone cannot itself die of one.
        with suppress(OSError):
            print(_REPORT_CUT_SHORT, file=sys.stderr)
        # The descriptor standard output actually is, asked of the stream rather than assumed to be
        # the usual number. Reaching this arm means a write to that stream raised, so it has one; a
        # caller who moved standard output elsewhere would otherwise have a descriptor they were
        # still using pointed at the null device instead.
        null = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(null, sys.stdout.fileno())
        finally:
            os.close(null)
    except OSError:
        # Left exactly where it was already answered. The bytes stay pending, so the interpreter
        # meets the same failure emptying this stream on its way out and reports it as it always
        # has. Taken any further, a full disk becomes a fault filed against elenctic: answered here
        # it would be given a sentence about a reader, and let past it reaches the console entry's
        # own backstop, which tells the reader they have found a bug in this program.
        pass


@contextmanager
def stdout_to_stderr() -> Iterator[None]:
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
    And there has to *be* a standard error: a process whose descriptor 2 is closed has none to
    divert to, and the free number that leaves behind is the one the copy below would be given.
    Every entry point calls :func:`establish_standard_error` before any of this runs.
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
            # The release is owed even where putting it back failed. A copy that could not be
            # restored is still a descriptor this process holds, and the next region takes another.
            try:
                os.dup2(saved, 1)
            finally:
                os.close(saved)
