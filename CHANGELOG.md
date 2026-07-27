# Changelog

Notable changes to elenctic. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims at
[Semantic Versioning](https://semver.org/).

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

[0.1.3]: https://github.com/GregoryGelfond/elenctic/releases/tag/v0.1.3
[0.1.2]: https://github.com/GregoryGelfond/elenctic/releases/tag/v0.1.2
[0.1.1]: https://github.com/GregoryGelfond/elenctic/releases/tag/v0.1.1
