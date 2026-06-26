# Changelog

Notable changes to elenctic. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims at
[Semantic Versioning](https://semver.org/).

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

[0.1.1]: https://github.com/GregoryGelfond/elenctic/releases/tag/v0.1.1
