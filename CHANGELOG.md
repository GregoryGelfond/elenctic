# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Library: `Program`, `ground`, `solve` with `Limits` and a cancellable `Interrupt`; results as
  `Consistent | Inconsistent | Inconclusive` over `Models` or `Consequences`.
- Query kernel in the public API: `Literal`, `Pattern`, `Query` (`Literal | All | Any`), `Answer`,
  `answer`, `singleton_answer`, `bindings`, over a `WorldView` that only an exhausted search yields.
- Contracts read from comments with source spans: `@expect`, `@count`, `@model`, `@cautious`,
  `@brave`, `@query` with optional `= { bindings }`, and an `assuming { … }` form on any claim.
- `check` with the verdicts `pass`, `fail` and `undecided`.
- Command line with `--json`, `--verbose`, `--budget` and `--models`; exit codes 0, 1 and 2.
- Native cautious and brave consequences (`Grounded.consequences`), used by `check` when a search
  holds only such claims.
- Minimal unsatisfiable cores over assumptions: `Refutation` is `These | NotThese | NoAssumptions`.
- Optimization: `Grounded.optimize` returns `Optimum` or `Incumbent`; claims `@model optimal`,
  `@cautious optimal`, `@brave optimal`, `@optimal { L }`, `@count optimal n` and `@cost { … }`.
- Preconditions that make a misreadable contract an error: theory atoms, an objective that grounds
  away, a nested `@count optimal`, a derivable unshown contrary under `no`/`unknown`.
- Subcommands: `elenctic test` (the default) and the reserved `repl`, `why`, `ask`, `explain`.
- Examples with real output in `docs/reference/examples.md`, checked by a test.
- Packaging for uv, pixi and conda-forge (`recipe/recipe.yaml`).

### Changed

- A refutation by assumptions whose core may not be minimal (the search was cut short) now says so.
- `@cost` over `#maximize` is accepted: costs are clingo's minimized sums, so a maximized level is
  negated.
- A `no`/`unknown` query faults only when its contrary is derivable and not shown.
