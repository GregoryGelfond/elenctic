# Changelog

Notable changes to elenctic. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims at
[Semantic Versioning](https://semver.org/).

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

[0.1.2]: https://github.com/GregoryGelfond/elenctic/releases/tag/v0.1.2
[0.1.1]: https://github.com/GregoryGelfond/elenctic/releases/tag/v0.1.1
