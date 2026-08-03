# Changelog

Notable changes to elenctic. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims at
[Semantic Versioning](https://semver.org/).

Changes are recorded under **Unreleased** as they merge; cutting a release renames that section to
the version and dates it. Entries describe what changed for someone using elenctic, and what it
means for them — a reader deciding whether to upgrade should not have to read the commits.

## [Unreleased]

### Fixed

- **A solve cut short by `--budget` no longer throws away the answer it did reach.** A cancelled
  search still reports whether the program is satisfiable; elenctic decided the run was undecided
  before reading that, so every check on it came back UNDECIDED — including checks the search had
  already settled. Any corpus whose search outlives its budget met this, so it was not a corner
  case but the ordinary behaviour of a hit budget.

  Before, on a program with 2^20 answer sets under `--budget 0.5`:

  ```
  case.lp [clingo] — UNDECIDED
    [UNDECIDED] @count: the solve did not settle the question — UNDECIDED, never FAIL
    [UNDECIDED] @expect sat: the solve did not settle the question — UNDECIDED, never FAIL
  ```

  After — the satisfiability question was answered, so it is answered, and the census question
  says why it was not and what would help:

  ```
  case.lp [clingo] — UNDECIDED
    [UNDECIDED] @count (line 2): the search was cut short before covering the collection this
    reads, so what it holds is part of the collection and not the collection — UNDECIDED, never
    FAIL. The per-solve time budget is what stops a search this way from the command line, so a
    larger --budget may decide it
  ```

- **An optimal-class run that could not finish enumerating no longer reports the program as having
  no answer set.** The optimal-class modes solve twice: prove the optimum, then enumerate at it.
  The second solve's "no model" answer was read as a statement about the program, when it is a
  statement about that solve — by then the first has already found a model, so the program is known
  to have an answer set. A case whose optimal class was too large to enumerate inside `--budget`
  therefore came back with every optimal-base tag reporting `AS(P) = ∅`, as a definite failure,
  contradicted in the same report by the `@expect sat` that passed. Such a case is now UNDECIDED —
  it could not be decided, which is what happened — so a corpus that used to fail here will report
  differently, and `@cost`, `@optimal`, `@cautious optimal`, `@brave optimal`, `@count optimal` and
  `@assign optimal` are the tags affected.

- **A solve cut short by `--budget` can no longer report that your program has no answer set.** A
  cancelled solve sometimes comes back carrying clingo's "unsatisfiable" and "exhausted" bits
  together — measured at two occurrences in 1,400 zero-budget solves of a program with 2^30 answer
  sets, under the single-model configuration as much as the enumerating one. Read literally, that
  says the search covered the space and found nothing. elenctic believed it, so a case whose solve
  ran out of budget could report `AS(P) = ∅` as a decided fact about a program with more answer sets
  than could be counted. Every model-bearing tag then failed, and `@expect unsat` — which rides its
  own single-model run, one of the two configurations this was measured in — **passed**, upholding a
  claim nothing had established.

  A search cut short from outside is now believed about what it *found* and never about what it
  *finished*. A model it produced is evidence a cancellation cannot take back, so a cut-short solve
  still reports the satisfiability it settled; covering the space is a claim only a search that ran
  to its own end can make, so neither "no answer set" nor "the space was covered" survives a
  cancellation. Cases that met this now report UNDECIDED, which is what happened.

### Changed

- **A fault in elenctic now exits `3`, apart from a fault in your corpus.** Exit `2` meant both
  "your corpus has something to fix" and "elenctic violated one of its own invariants" — one status
  for the two things a reader can least afford to confuse, since one is work for them and the other
  is a bug to report. A harness fault is now `3`, and it outranks every other signal, because a
  harness that is wrong about one case is evidence about every other. Everything else that was `2`
  stays `2`: a bad contract, a mis-shaped corpus, a program that will not ground, a case that ran
  out of memory, a run that passed its `--deadline`, and corpus-health observations under
  `--strict`. A job gating on non-zero is unaffected; one testing for exactly `2` will stop seeing
  elenctic's own faults, which is the point.

- **A corpus-health observation now carries the grade the run gave it.** `HygieneRecord` gained a
  `severity`: `error` under `--strict`, and otherwise `warning` for an orphan library and `silent`
  for an undeclared solver — the footing each observation already had. What is printed, what fails
  the run, and what a consumer is told are now read off that one field rather than each deriving it
  again from the flag, so they cannot come to disagree about a single observation. Nothing a run
  prints changed.

- **A failure now names the contract line it judged, and repeated claims no longer repeat one
  sentence.** Every claim carries the line it was written on, so a diagnostic can be placed against
  the claim rather than against the file, and a tag a contract may write more than once is shown
  with the claim it carries. Where several claims failed for the same reason, the reason is stated
  once and the claims follow it:

  ```
    [FAIL] @cautious { tea } (line 10): { tea } ⊄ ⋂ AS(P) = { biscuit } (missing: { tea })

    [FAIL] @cautious: no cautious consequences — AS(P) = ∅
           applied to { tea } (line 10), { coffee } (line 11), { biscuit } (line 12)
  ```

  Anything reading this output by shape will need updating. Nothing about a verdict changed: the
  case verdict folds a set, so sharing a row cannot move it.

- **`@cautious`, `@brave`, `@cautious optimal` and `@brave optimal` may be written on more than one
  line**, and each line is now its own check with its own verdict and its own diagnostic. Writing
  the claims on one line remains equivalent — `L₁ ⊆ S` and `L₂ ⊆ S` together say exactly what
  `L₁ ∪ L₂ ⊆ S` says — but a failure now names which line was false instead of the union.

- **`Sat` and `Unsat` no longer construct without a line.** Both now require `expect_line`, and
  every contract cell carries a `Claimed` value pairing what was claimed with the line it was
  claimed on. `CheckReport` likewise gained the claim's subject, its line, and how the search
  behind the verdict ended. Code that builds these directly — rather than through `parse` and
  `run_case`, which is the ordinary path — must pass the coordinate.

- **The records a machine-readable report is built from are constructed by keyword.** `CheckReport`
  and the new `CaseOutcome`, `ErrorRecord`, `HygieneRecord` and `RunOutcome` take their fields by
  name. A report's `message` and `subject` are neighbouring strings, so a transposed pair type-checks
  clean and renders a plausible row against the wrong claim; and a report is identified by field
  name wherever it is decoded, so position would be a second identity that a field added later
  silently re-means.

- **An invariant elenctic violated about its own result now raises `HarnessError`.** The empty cost
  vector on a proven optimum, the four consistent shapes built around an empty collection, and the
  non-empty-census precondition on a conjunctive query raised `ValueError`, which no per-case handler
  catches — so a result that could not be right ended the whole run and discarded every case still to
  come. It now costs one case its verdict, like every other fault the runner isolates. What a caller
  got wrong at a boundary is still `ValueError`: an unknown solver name, and the contract payloads a
  parse re-raises with the author's provenance.

- **`HygieneReport.render` was removed.** What a run prints about corpus hygiene and what fails the
  run under `--strict` are now read off the same records the run reports, rather than from a second
  rendering of the same facts. The observations themselves are unchanged, and so is what is printed.

- **Whether a search had to finish is now decided per check, not per run.** One solve serves
  several checks and they do not all ask the same thing: a census, an intersection, a union or a
  proven optimum is a claim about every member of a collection, so a search that stopped early
  makes it a claim about an arbitrary part — while `@expect sat` reads nothing from the collection
  and one model settles it whatever the rest of the search would have found. The requirement is
  derived from what each check declares it reads, so it cannot drift from the reading it protects.
  A reading that outran its search is still UNDECIDED, never FAIL and never a PASS it did not earn.

- **An undecided report now says which kind of not-knowing it met** — the solve settled nothing,
  or it settled satisfiability over a search that stopped short of covering what this check
  reads, or one that was cut short from outside. Raising a budget and shrinking what a case
  enumerates are different remedies, and the single previous message distinguished neither.

- **`Collection` is now imported from `elenctic.result`** rather than `elenctic.run`; it describes
  what a *field* is a reading of, so it belongs beside the field vocabulary. `elenctic.Collection`
  is unchanged.

## [0.2.0] - 2026-08-01

The minor bump is deliberate. Earlier releases changed what a *consumer* had to catch; this one can
change whether a *corpus that ran before still runs*. A case may now only load files from inside
the corpus the run was pointed at, so a corpus that reached outside it — absolutely, with `../`, or
through a symlink — is refused rather than read. Reaching up and across to a shared encoding
remains the ordinary shape of a corpus and is unaffected.

### Security

- **A case may only load files from the corpus it belongs to.** `#include` resolution belongs to
  clingo, which opens whatever path it is handed, and nothing constrained what a case could hand
  it — so a corpus could name any file the process can read, absolutely, by climbing out with
  `../`, or through a symlink. What is read does not stay read, either: a contract that fails
  renders the model it was judged against, so a case that includes a file and then asserts
  something false about it publishes that file's contents through elenctic's own diagnostic.
  Containment is rooted at the directory the run was pointed at, not at the case's own, because
  reaching across to a shared encoding is the ordinary shape of a corpus.

- **Corpus-controlled text can no longer rewrite the report it appears in.** A case's path, its
  `@note` prose, the atoms in its answer sets and the solver's diagnostics about it all reached the
  terminal verbatim, and a terminal acts on some of that text rather than showing it — so a corpus
  could clear the screen, move the cursor, or overwrite a line just printed. Such text now passes
  through an escaping step: printable characters, spaces and newlines survive, anything else
  becomes a visible `\xNN`. Newlines are deliberately kept, since a solver diagnostic is
  legitimately multi-line; a newline can add a line but cannot conceal or overwrite one.

- **A solve is now bounded in memory as well as in time.** A solve holds every model it is shown,
  and the time budget says nothing about how fast they arrive — so a corpus could exhaust memory
  inside a budget that never expired, which made the advertised hang protection a bound on one
  resource presented as the bound. A model cap stops the search, on both the clingo and clingcon
  paths. It needs no verdict vocabulary of its own: a stopped search reports itself as not
  exhausted, and running out of room and running out of time are the same fact about knowledge.

- **The contract scanner finishes, and its lines are clingo's lines.** While a braced payload was
  open, every following line re-read the whole accumulated text and every continuation rebuilt it —
  two quadratics, the first running for each line in the file, all of it during the corpus walk and
  so upstream of every budget. A tag carrying ~24 KB followed by 40 000 ordinary lines took half a
  minute; it now takes a tenth of a second. Separately, the scan split on Python's notion of a line
  boundary — which includes `\v`, `\f`, the file/group/record separators, NEL, and the Unicode line
  and paragraph separators — while a clingo `%` comment runs to a newline. A single physical line
  could therefore carry a second contract tag that elenctic acted on and no reviewer could see.

### Fixed

- **A search that stopped early is no longer reported as a complete collection.** A solve settles
  two independent things — whether a model exists, and whether the search covered what was asked of
  it — and only the first was read. A truncated search still answers "satisfiable", so its partial
  census, intersection, union or optimum was reported as the whole collection. Measured on 8-queens
  under a conflict limit, an enumeration reported 17 of the program's 92 answer sets and a
  consequence run 20 of its 23 brave consequences — figures that move with the search rather than
  being properties of the program, which is itself the defect. The worst case is silent: an
  intersection taken over a prefix is a
  *superset* of the true one, so a `@cautious` contract naming a surplus atom **passed a false
  claim**. A reading that ranges over a whole collection now requires the search to have finished;
  a witness reading does not, and that exemption is necessary rather than merely permitted.

- **A fault names its true owner, and a remedy is offered only where it is the remedy.** elenctic
  divides faults by whose they are, and carries that division on the exception type — but clingo
  reports nearly everything through one channel, so the division was only as good as what each
  guarded region did with what it caught. Guarded regions now span code with a single owner rather
  than asserting one owner over several. Among what that fixed or exposed: a file name that is not
  UTF-8 was reported as an elenctic bug rather than as the corpus's; `#include` advice was appended
  to faults that had nothing to do with includes, sending authors to inspect paths that were fine;
  an objective that grounds away accused elenctic of a broken precondition; and a failure inside
  elenctic's own AST walk or solve reduction was reported as a program that cannot be run.

- **Programs that show a non-predicate term are no longer refused.** `#show "text" : p.` and
  `#show 42 : p.` are valid — clingo runs both — but elenctic rejected them as faults in the
  program. A symbol's name is defined only for a function symbol, and clingo raises when one is
  read off a string or a number rather than reporting that there is none, so the guard meant to
  cover that case could never fire.

- **The walk over a program no longer has a depth of its own to run out of.** The AST walk
  recursed once per level, so how deeply elenctic could read was bounded by the interpreter's
  stack while the depth is chosen by the program under test. A term nested past it was refused,
  though clingo grounds and solves such programs without complaint. Measured: the walk gave out on
  a left-nested arithmetic chain of 1 000 terms, a strong-negation chain of 1 000, and a list
  written as `cons(a, cons(b, …))` of **500** elements — nothing adversarial about the last, which
  nests one level per element. Both the node walk and the signature reader are iterative now.

- **Exhausting memory costs one case's result instead of the whole run's.** It was caught only at
  the outermost frame, so the run stopped there: no summary, no results for the cases that had
  already passed, and no indication of which case did it — while every other way a case can fail to
  run is reported against its own file and leaves the rest of the corpus running. There is now a
  per-case register for it, with the outermost handler kept as the backstop for an allocation that
  fails where no case owns it. Neither message asserts a cause it cannot know: grounding is the
  usual explanation, but a solve holds every model it is shown, so the memory may have gone there.

- **One unusable file costs only its own result at discovery, too.** The runner already isolated a
  case that failed to ground, but the walk that builds those cases had no such guard, so a file that
  could not be read, parsed or resolved raised straight out of discovery — and stdout came back
  empty, denying every other case its result. A corpus of one healthy case and one with an
  unresolvable `#include` printed nothing at all; it now names the bad file and reports
  `1/2 passed, 1 could not be run`.

- **An oversized diagnostic stays readable, and clingo's own diagnostics stay on one channel.** A
  check renders the set it judged against, and the program decides how large that is — a cautious
  reading over a large fact base is the whole fact base. Sets are now shown as a sorted prefix with
  the remainder counted, so the diagnostic is both bounded and stable across runs. Separately,
  clingo's term parser was called with no logger, so a malformed contract produced elenctic's
  friendly error *and* clingo's own on stderr; that text is now folded into the error being raised.

- **A resource the run exhausts is reported rather than dumped as a traceback**, and a fault that
  reaches the top frame says whose it is before printing one — the traceback is the report, and the
  sentence above it is what tells a user this is not theirs to fix.

### Added

- **`--deadline`**, which bounds the whole run rather than one solve. `--budget` bounds a single
  solve; a case routes to as many as four, and a corpus has as many cases as it has files, so the
  cost of a run is a product of three numbers of which only one was bounded. Past the deadline the
  run stops dispatching and every case it did not reach is counted into the not-run register, so
  the corpus total stays the corpus total. It is off unless asked for: a default low enough to
  bound a hostile corpus would turn a large honest one into cases that could not be run.

### Changed

- **A defect in elenctic's own code is now reported as one.** A failure inside the AST walk or the
  solve reduction used to be translated into a program fault, which named the corpus author. Worse,
  it named *every* author: the same internal failure recurs for each case, so one defect in
  elenctic produced an accusation against every file in the corpus and a summary saying none of
  them passed.

  ```text
  # before, with a defect injected into elenctic's own solve reduction
  PROGRAM ERROR — alpha.lp: cannot run the program (alpha.lp): <the internal failure>
  PROGRAM ERROR — beta.lp: cannot run the program (beta.lp): <the internal failure>

  0/2 passed, 2 could not be run
  ```

  ```text
  # after
  internal error: this is an elenctic bug, not a fault in your corpus. Please report it
  with the traceback below.
  Traceback (most recent call last):
    ...
  ```

  Both exit `2`. The change costs the run rather than the case — the same trade the outermost
  handler already makes for every other unanticipated fault — and it is the right one here, because
  what the run would go on to produce is of unknown worth once elenctic is known to be broken. If
  you match on `PROGRAM ERROR` lines in CI, note that a class of them has moved.

## [0.1.3] - 2026-07-27

### Fixed

- **A program that cannot be run is reported, instead of crashing the run.** A program that
  parses but fails to ground — an unsafe variable is the usual cause — cleared discovery and
  then died at solve time as an unhandled error, aborting the whole run. Every case that had
  already passed lost its result too, because the summary line was never reached, so the run
  produced no output at all and exited with the status that means *a case was tested and
  decided wrong*. Such a program is now reported as a `ProgramError` naming the offending file
  and line with clingo's own diagnostic, the remaining cases still run, and the run exits in
  the error register. A program that will not ground is never reported as unsatisfiable: its
  answer sets are undefined, not empty, and conflating the two would silently pass an
  `@expect unsat` contract written against a broken program.

- **A declared solver that is not installed is reported, instead of crashing the run.** A case
  declaring `@elenctic solver clingcon` in an environment without clingcon failed on the import
  inside the solver, at the latest possible moment. It is now checked before the case is
  solved and reported against that case with the command that fixes it. Only the cases that
  declare the missing solver are affected; the rest of the corpus still runs, and `--explain`,
  which never reaches a solver, does not require one to be installed.

- **A solve that completes without deciding is `UNDECIDED`.** clingo's solve result is
  three-valued — satisfiable, unsatisfiable, or unknown — but the result was read as two bits,
  so a search that gave up fell through to the satisfiable branch and every mode then failed
  trying to build an answer out of an empty search: as an internal error, as a false claim that
  the program has no answer sets, or as a report that an encoding lacks the objective it
  visibly has. One reduction now reads the result, at every solve site, including both phases
  of the optimal-class enumeration — whose second phase previously discarded its result
  entirely.

- **An internal fault during a solve is no longer reported as a fault in the program under
  test.** Driving a solve asynchronously, clingo does not re-raise an exception from a model
  callback unchanged: it arrives as a plain error carrying only the message. Since the new
  ground/solve boundary reads such an error as a fault in the program, elenctic's own failures
  are now recorded before that erasure and re-raised intact — on both the normal and the
  cancelled path, the latter of which would otherwise have reported an internal bug as the
  verdict `UNDECIDED`.

### Added

- **`SolverUnavailableError`** (`elenctic.SolverUnavailableError`), raised when a case declares a
  solver this environment does not have. It is deliberately both a `DiscoveryError` — a corpus
  naming an absent solver cannot be run — and an `ImportError`, which is what a missing optional
  dependency is in Python, so a caller following either convention catches it without knowing
  about the other. The same type is raised whether the condition is met through the corpus walk
  or through a direct `solve` call.

### Changed

- **`ProgramError` is no longer a subclass of `HarnessError`, and is now exported.** The
  inheritance asserted that a broken program under test is a kind of elenctic bug, which is
  false and is why a program that would not ground had no register to be routed to. The two are
  now disjoint roots: `ContractError`, `DiscoveryError` and `ProgramError` are the author's to
  fix, `HarnessError` is elenctic's. **This is a breaking change** for any consumer that caught
  program faults via `HarnessError`; catch `elenctic.ProgramError` instead.

- The exit status `2` now covers a program that cannot be run, alongside a bad contract, a
  mis-shaped corpus and an internal error. No status changed meaning; the register gained a
  member.

## [0.1.2] - 2026-07-16

### Fixed

- **The AS(P) tags now mean AS(P) on an optimizing encoding.** clingo optimizes by
  default, so on an encoding carrying an objective (`#minimize`, `#maximize` or `:~`) an
  enumerating solve reported only clingo's branch-and-bound *improving sequence*: the
  models the search passed through on its way to the optimum. That sequence is neither
  AS(P) nor Opt(P), and it moves with the search heuristic, so every tag whose reading
  ranges over AS(P) quietly answered a different question:
  - `@count` reported a wrong number;
  - `@model` and `@brave` rejected genuine answer sets (a false `FAIL`);
  - `@cautious` admitted atoms that are not cautious consequences, and `@query` returned
    a wrong three-valued answer. Both of these **passed a false claim**.

  The `* optimal` family (`@cost`, `@optimal`, `@count optimal`, `@cautious optimal`, and
  the rest) was never affected, because it states its optimization explicitly. `@expect`
  is likewise unaffected: satisfiability does not depend on an objective.

  **On upgrading:** a contract that passed under 0.1.1 may now fail. Where it does, the
  earlier `PASS` was unsound and the new verdict is the true one. A bare `@count` on a
  large optimizing encoding now enumerates all of AS(P), so it may reach the time budget
  and report `UNDECIDED` instead of a fast wrong number.

- **A bare AS(P) tag over a theory-native objective is now refused, not answered.**
  `--opt-mode=ignore` switches off clingo's optimize statements; clingcon's `&minimize` /
  `&maximize` is driven by the theory's own propagator, which no clingo setting reaches.
  Such an encoding also produced no `#minimize` node, so it read as objective-free and
  passed every precondition, leaving `@cautious` and friends to answer from a search
  pruned to the optimum. Theory-native optimization stays outside v1, but the exclusion is
  now **loud**: discovery reports a corpus error (exit 2) naming the fix, rather than a
  quiet wrong verdict.

### Added

- `Collection` (`elenctic.Collection`), what a reading ranges over (AS(P), Opt(P), or one
  answer set), readable as `Mode.asks`. It is *derived* from the fields a mode populates,
  not declared beside them, so a mode cannot claim one collection while reading another's.
  Each mode now states the optimization its collection requires instead of inheriting the
  solver's default, and a gating test holds every mode to it.

## [0.1.1] - 2026-06-26

The first tagged release. **elenctic** is a declarative testing framework for Answer
Set Programming: you write in-file `@`-contracts over the *observable* of an answer-set
program (its shown atoms and theory assignment), and elenctic discovers, runs, and
checks them across clingo and clingcon, reporting a three-valued verdict
(PASS / FAIL / UNDECIDED) that never conflates a timeout with a refutation.

Highlights of the initial release:

- **Contracts over the observable:** `@expect`, `@model`, `@cautious` / `@brave`,
  `@count`, `@cost`, `@optimal` (and the optimal-base family), `@assign` (theory / CSP),
  the three-valued `@query` (Gelfond–Kahl Def 2.2.2, errata-corrected), and `@note`.
- **Content-keyed discovery:** a file is a *case* iff it carries a contract tag;
  dependencies are declared with `#include`; the solver is declared with
  `@elenctic solver` (default `clingo`). A `--strict` dial gates corpus hygiene, and
  `--explain` narrates the run plan, led by the `@note` gloss.
- **clingo and clingcon backends,** with a projection-aware theory path for CSP
  observables.
- **Standalone runner** (`elenctic <path>`) and an importable library API; each
  pipeline stage also runs under `python -m elenctic.<stage>` for inspection.

This release also makes every in-source comment self-contained for external
contributors, single-sources the version from `elenctic.__version__`, and runs CI on
Linux and macOS.

[Unreleased]: https://github.com/GregoryGelfond/elenctic/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/GregoryGelfond/elenctic/releases/tag/v0.2.0
[0.1.3]: https://github.com/GregoryGelfond/elenctic/releases/tag/v0.1.3
[0.1.2]: https://github.com/GregoryGelfond/elenctic/releases/tag/v0.1.2
[0.1.1]: https://github.com/GregoryGelfond/elenctic/releases/tag/v0.1.1
