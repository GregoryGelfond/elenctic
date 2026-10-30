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
- LSP diagnostics from a result (`aspnext.lsp`).
- Packaging for uv, pixi and conda-forge (`recipe/recipe.yaml`).
