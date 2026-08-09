"""The streams a program is owed, established before it writes anything.

Every way elenctic can be *run* — the console entry, and each pipeline stage under
``python -m elenctic.<stage>`` — is a program handed a process, and a process can be started
missing a stream rather than having it pointed somewhere. What this language does with that absence
is quiet and costly, and the answer to it is the same wherever it is asked, so it is stated once
here and asked by each entry point rather than restated in five places that can drift apart.

This module has no elenctic dependencies, which is what lets every entry point reach it: the stages
sit at different layers and the console entry imports all of them, so a rule any of them can ask has
to live below all of them. It is not part of the curated surface — a consumer composing elenctic's
pieces owns their own process and its streams; this is what *being run as a program* needs.
"""

import os
import sys

__all__ = ["establish_standard_error"]


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
    handed out: the copy of standard output the redirect region takes on its way in *becomes*
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
