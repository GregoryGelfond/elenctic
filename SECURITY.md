# Security

## Reporting a vulnerability

Please report privately, through GitHub's
[private vulnerability reporting](https://github.com/GregoryGelfond/elenctic/security/advisories/new)
on this repository. If that is unavailable to you, open an issue that says only that you have a
security report and how to reach you — **do not put the details in a public issue**.

A useful report contains the `.lp` file or corpus that provokes it, what you expected elenctic to
refuse, and what it did instead. The output of `elenctic run TARGET --format json` carries the same
run in a form that does not depend on how your terminal rendered it.

Fixes land in the current release. elenctic does not backport to earlier ones.

## The thing worth understanding first

**A corpus is code, and elenctic runs it.** Discovery reads every `.lp` file under the target,
resolves its `#include`s, and hands the result to the solver — so pointing elenctic at a corpus is
as consequential as running any other program from that directory. Corpora are cloned, and they
arrive in pull requests, so that is treated here as untrusted input rather than as your own code.

Everything below follows from that one fact: the interesting question is not whether elenctic can be
made to run a hostile program — it will, that is its job — but whether a hostile program can reach
past the corpus, mislead the report, or take the run down with it.

## What elenctic defends against

**A case reaching outside the corpus it belongs to.** `#include` resolution belongs to the solver,
which will open whatever path it is handed, so without a rule a corpus could name any file the
process can read. A case may only load files from inside the corpus it was run against; anything
else is refused as a `containment` fault. Two details are load-bearing:

- the rule is applied whether or not the escaping file parses — a file that will not parse is
  refused while the program is being *read*, and one that grounds badly while it is being
  *grounded*, in the same words, so which frame notices is not something an author can steer;
- where a diagnostic would describe a file outside the corpus, **the solver's own diagnostic is
  withheld rather than republished**. Repeating it would report that the file exists, how far into
  it the solver got, and which characters it objected to — an existence-and-shape oracle over
  anything the process can read, driven from a corpus.

Symlinks and `..` are judged by where they land rather than by how they are spelled, and the
boundary itself must be a resolved path before any comparison is made.

**Corpus text rewriting the report.** Everything elenctic prints about a case is influenced by the
case: its path, its `@note` prose, the atoms in its answer sets, and the solver's diagnostics about
it. A terminal treats some of that text as instructions rather than as characters — an escape
sequence can clear the screen or move the cursor, a carriage return can overwrite the line just
printed, and a line break starts a line of its own, which is how a diagnostic forges a verdict in
the report it appears in. All corpus-controlled text passes through a sanitizer before it is shown:
printable characters survive — the ASCII space among them — everything else becomes a visible
escape, and backslashes are doubled so the encoding is unambiguous in both directions. What comes
back is one line.

**One sink is deliberately outside that rule**: the traceback printed when elenctic violates one of
its own invariants. It goes out raw, under a line saying it is elenctic's fault and not yours,
because a traceback whose file-and-line coordinates were escaped is one no editor can follow — and
following it is the whole of what it is for.

Line breaks were once kept, on the reasoning that adding a line is harmless beside overwriting one.
That was wrong, and the correction is recorded here rather than quietly made: a report's structure
**is** its line boundaries, so text that can add a line can write a row, and a file name carrying
one printed a `[PASS]` directly above the `[FAIL]` its own case had earned.

A solver's own diagnostic does run to several lines, legitimately — and it is also where the solver
writes the corpus's file name, so the one string that may span lines carries the one value that can
forge one. Neither is sorted from the other by which field it came from. The report re-emits those
breaks itself and marks every line below the first with `|`, a mark it writes nowhere else, so an
added line is the report's own structure and never the corpus's.

**The machine-readable document being broken by what it carries.** The same seam covers the JSON
report, for a related reason — text a parser would act on can break the document it appears in. It
also settles two things the terminal never faces: a file name whose bytes are not valid UTF-8
reaches Python as a lone surrogate, which has no encoding at all and would fail at the moment of
writing rather than of reading; and the two separator characters that end a line for some readers of
JSON would split a document required to be exactly one.

**One bad file taking the run with it.** A file that cannot be read, parsed, or resolved is recorded
against itself and the walk continues, so one unusable file costs its own result and no other's. The
same holds at run time for a program that will not ground, a case that exhausts memory, and a fault
in an observer you supplied.

**A fault being reported as a verdict.** Errors are a separate register from verdicts and are never
dressed as one. This matters for a gate: a corpus that could not be read reports as an error and a
non-zero status, never as a corpus in which everything passed.

## What elenctic does not defend against

These are stated plainly because a reader deciding whether to run untrusted corpora needs them, and
because a defence nobody documents is one people assume is there.

**Grounding is not bounded.** A small program can ground to something enormous, and clingo offers no
API to cap that — it is not a limit elenctic can impose. `--budget` bounds a *solve*, and grounding
happens before one. **Running an untrusted corpus therefore belongs inside whatever isolation your
platform already provides: a container with a memory limit and a job timeout.** Running out of
memory is reported against the case that ran out of it and costs that case's result rather than the
whole run's, but it cannot be prevented from here.

**A tree that changes while a run is in progress.** A case's sources are judged when it is
discovered. A case whose files are swapped between discovery and solving reaches the solver carrying
files the containment rule never saw.

**Anything the solver itself does.** elenctic drives clingo and clingcon through their Python APIs
and inherits whatever they do with a program. Vulnerabilities in those belong upstream, at
[Potassco](https://github.com/potassco).

**Denial of service in general.** elenctic is a test harness, not a sandbox. A corpus that takes
forever, allocates everything, or produces an unreadable amount of output is a corpus you should not
be running unattended without the isolation described above.

## Scope

A report is in scope if it shows elenctic doing something a reader of these documents would not
predict — reaching outside a corpus, publishing something about a file the run was never pointed at,
producing output that misrepresents a verdict, or reporting success where a fault occurred. A corpus
that consumes a great deal of time or memory is not in scope on its own, since grounding is
unbounded by construction and is documented as such above.
