"""The streams a program is owed: established before it writes anything, and answered for after.

Every way elenctic can be *run* — the console entry, and each pipeline stage under
``python -m elenctic.<stage>`` — is a program handed a process, and a process can be started missing
a stream rather than having it pointed somewhere. The answer is the same wherever it is asked, so it
is stated here once rather than in each entry point.

Past that, the console entry has three further questions about the same two streams and nobody else
has any: where a published artefact goes, what is owed to a reader who stopped reading, and how to
keep everything but the document off standard output while a run is going. Each is a fact about this
process's descriptors rather than about a command line.

No elenctic dependencies, which is what lets every entry point reach it: a rule any of the stages
can ask has to live below all of them. Not part of the curated surface — a consumer composing
elenctic's pieces owns their own process; this is what *being run as a program* needs.
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

# What a reader is told when nothing was left to write to. Not a fault — not in the corpus, and not
# in elenctic — so it files no record and changes no status; what it owes the reader is the one fact
# they cannot see from where they are standing, that what they hold is not all of it.
#
# Three constraints on the wording. It opens on a noun, as every heading this program writes does.
# It does not say the writing stopped *part-way*, because a reader can leave before the first byte
# lands. And the reassurance names its subject, so that under a backstop line saying the run went
# wrong it is not read as a claim about the run.
_REPORT_CUT_SHORT = (
    "output cut short: nothing is reading standard output, so what reached the other end is "
    "incomplete. Losing the reader affected nothing else — this leaves with the status it would "
    "have left with anyway. Whoever needs the whole of it should read to the end, or write it to a "
    "file and read the file."
)


def establish_standard_error() -> None:
    """Give this process a standard error where it has none, before anything is written.

    A process can be started with the descriptor closed rather than redirected — ``2>&-`` in a
    shell — and that one absence costs the run two separate things.

    The stream: this language leaves ``sys.stderr`` as ``None``, and ``print`` writes to standard
    output when handed that. Under a machine-readable format standard output is the document's
    alone, so a diagnostic written outside the redirect region lands in the middle of the report, no
    consumer can parse it, and the status says there is nothing to look into.

    The descriptor: 2 is then the lowest free number and so the first handed out, which makes the
    copy :func:`stdout_to_stderr` takes on its way in *become* descriptor 2 — and the region then
    points standard output at itself. The null device goes there rather than the descriptor being
    left closed, so that what is written goes nowhere instead of failing.

    **The two are asked separately, and that is the whole of this function's shape.** Descriptor 2
    being free is a fact with a lifetime: this runs after the entire import graph has loaded, so
    anything that opened a file on the way has taken it. A probe of the descriptor can therefore
    succeed while ``sys.stderr`` is still unbuilt, and one condition read as an answer to the other
    leaves every diagnostic going to standard output.

    Where something else did take descriptor 2, the rebuilt stream is written to it anyway: at that
    point descriptor 2 *is* this process's standard error, and every library in the process writing
    to standard error is already writing there.

    Raises if the null device cannot be opened — no ``/dev/null`` in a chroot, or no descriptors
    left. The postcondition cannot be met, and a caller told so loudly is better off than one whose
    next diagnostic silently lands in the report it was writing.
    """
    try:
        os.fstat(2)
    except OSError:
        # The lowest free descriptor is handed out and descriptor 2 is free, so opening the null
        # device *is* opening descriptor 2. Only where a lower descriptor is missing too must the
        # copy be moved and the original released; done unconditionally, that closes descriptor 2
        # one statement after opening it.
        null = os.open(os.devnull, os.O_WRONLY)
        if null != 2:
            try:
                os.dup2(null, 2)
            finally:
                os.close(null)
    # Rebuilt only where this language left it unbuilt, so a caller who supplied a stream of their
    # own keeps it. Line buffered and lenient about a character it cannot encode, as an interpreter
    # building one for itself would be. Outside the arm above, not inside it: that arm repairs the
    # descriptor and this is about the stream, and descriptor 2 is open by now either way.
    if sys.stderr is None:
        sys.stderr = os.fdopen(2, "w", buffering=1, errors="backslashreplace", closefd=False)


def publish(document: str) -> None:
    """Put a published artefact on standard output, encoded as UTF-8 whatever this environment's
    locale would have chosen — or say why the reader did not get it.

    Both things written this way are JSON, and JSON is UTF-8 by its own specification. Through the
    text layer they would take whatever encoding the environment picked, which on a machine whose
    standard output is ASCII raises on a character the document is entitled to contain: what reaches
    the consumer is a failure to produce a report rather than the report.

    Handing the bytes over is part of publishing rather than something left for the interpreter to
    finish, because a reader who has stopped reading can be answered while this frame is still
    standing and cannot be answered after it has returned. The encoding and the hand-over are one
    step and not two: an artefact half encoded and never delivered is the shape this makes
    impossible.
    """
    hand_over_standard_output(document.encode("utf-8"))


def hand_over_standard_output(published: bytes = b"", *, prose: str = "") -> None:
    """Write anything still owed to standard output, empty it, and answer once if no reader is
    left.

    Two payloads, because they belong to different layers. ``published`` is an artefact carrying its
    own encoding — the machine-readable document, UTF-8 by specification — and goes to the byte
    layer; ``prose`` is the run's own last sentence, which belongs to whatever encoding the
    environment picked for everything else the run printed, and goes through the text layer.

    A reader that stops — a pager quit, a ``head`` that had enough — leaves every further write with
    nowhere to land. It is a fault in neither the corpus nor elenctic, and the only thing owed is to
    say so: whatever the process was going to leave with, it still leaves with. A status saying
    otherwise would fail a job for the plumbing around it, and *which* wrong status would depend on
    where the write happened to be.

    Emptying the stream here is what makes that one answer possible: whatever is still held is
    written where a failure can still be reported rather than after the last frame that could say
    anything has returned, and the descriptor is then pointed at the null device so what is still
    pending is discarded rather than met again by an interpreter that answers differently.

    **Every write whose failure would otherwise reach the backstop is one this frame makes**, which
    is what lets a failure be read as a fact about standard output. Wrapped around a caller's work
    instead, it would answer for whatever that work wrote — and the tail writes to *both* streams,
    so a broken standard error would be reported as a fact about a healthy standard output.

    Narrower than *every* standard-output write this program makes: a run narrating itself writes a
    line per case through the corpus's announcement seam, which swallows a lost reader and goes on,
    so there it is the first of those writes rather than this frame that meets the reader who left.

    That event and no other. Standard output can refuse the bytes for reasons nothing to do with a
    reader — no space left, a device that failed — and those have a different remedy, a different
    owner, and no answer this frame is in a position to give.
    """
    # Standard output closed leaves nothing to hand over: ``sys.stdout`` is unbuilt, ``print``
    # writes nowhere without complaining, and no bytes are held. Not the missing standard error
    # `establish_standard_error` repairs on the way in — that absence costs the document its stream,
    # this one means there is no document — so the two are answered differently.
    if sys.stdout is None:
        return
    try:
        # The text layer first, so anything already written to it stays ahead of these bytes; then
        # the bytes; then the whole of it, so the hand-over either happens or is reported. The byte
        # layer is asked for only when there are bytes, since a caller who replaced standard output
        # with a text stream of their own cannot answer for `buffer`.
        if prose:
            sys.stdout.write(prose)
        sys.stdout.flush()
        if published:
            sys.stdout.buffer.write(published)
        sys.stdout.flush()
    except BrokenPipeError:
        # Saying it can meet the very fault it is about: `2>&1 | head` puts this sentence on the
        # stream that stopped being read, leaving nowhere to answer from. The frame whose whole job
        # is to answer a reader who has gone cannot itself die of one.
        with suppress(OSError):
            print(_REPORT_CUT_SHORT, file=sys.stderr)
        # The descriptor standard output actually is, asked of the stream rather than assumed to be
        # the usual number: a caller who moved standard output elsewhere would otherwise have a
        # descriptor they were still using pointed at the null device.
        null = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(null, sys.stdout.fileno())
        finally:
            os.close(null)
    except OSError:
        # Left where it was already answered: the bytes stay pending, so the interpreter meets the
        # same failure emptying this stream on its way out. Answered here, a full disk would be
        # given a sentence about a reader; let past, it reaches the backstop, which tells the
        # reader they have found a bug in this program.
        pass


@contextmanager
def stdout_to_stderr() -> Iterator[None]:
    """Send everything written to the process's standard output to standard error instead, for the
    duration of the region.

    Under a machine-readable format the report is the only thing that may appear on standard
    output: one foreign byte and the document will not parse. The redirect is at the
    file-descriptor level rather than at ``sys.stdout``, because rebinding the Python object
    leaves anything writing to the descriptor beneath it untouched — a C library reached through a
    binding writes where it chooses. What would otherwise land beside the document is moved rather
    than discarded.

    It catches every write *made while the region is open*, at whatever level. A writer that buffers
    below this process's control and empties after the region closes writes to the descriptor as it
    is then, which is the restored standard output; the distinction is recorded because the
    mechanism cannot enforce it.

    The buffer is emptied at each boundary because the boundaries decide which stream holds what.
    Within the region the two are not ordered against each other — standard error is line-buffered
    and standard output need not be — so writes can reach a reader in an order other than the one
    they were made in.

    The caller's side of the bargain: nothing inside the region may write to standard output, since
    for its length there is no way to reach it, and anything asking the descriptor about itself is
    answered for standard error. And there has to *be* a standard error, so every entry point calls
    :func:`establish_standard_error` first.
    """
    sys.stdout.flush()
    saved = os.dup(1)
    try:
        os.dup2(2, 1)
        yield
    finally:
        # The flush guards the restore because it is the step that can fail: it is issued against
        # standard error, so whatever makes standard error unwritable meets it here. Left unguarded,
        # it would keep the descriptor diverted for the rest of the process and send the report
        # itself to the one stream this region exists to keep it out of.
        try:
            sys.stdout.flush()
        finally:
            # The release is owed even where putting it back failed: a copy that could not be
            # restored is still a descriptor this process holds, and the next region takes another.
            try:
                os.dup2(saved, 1)
            finally:
                os.close(saved)
