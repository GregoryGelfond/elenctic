# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Import contracts (import-linter, in `pyproject.toml`): the layering, clingo reached only by the sixteen
  modules that read and run programs, clingcon only by `theory`, and `spans` free of both. They run
  in `pixi run check` and in CI.
- Library: `Program`, `ground`, `solve` with `Limits` and a cancelable `Interrupt`; results as
  `Consistent | Inconsistent | Inconclusive` over `AnswerSets` or `Consequences`.
- Query kernel in the public API: `Literal`, `Pattern`, `Query` (`Literal | Pattern | All | Any`), `Answer`,
  `answer`, `bindings`, over a `WorldView` that only an exhausted search yields.
- A row for every name of `elenctic.__all__` in `docs/reference/reference.md`, checked by a test.
- `mgu(first, second)` and `Unifier`: the most general unifier of two patterns, renamed apart, and
  the pattern both become. Public for answering queries and for the interactive session to come.
- Contracts read from comments with source spans: `@expect`, `@count`, `@answer-set`, `@cautious`,
  `@brave`, `@query` with optional `= { bindings }`, and an `assuming { … }` form on any claim.
- `check` with the verdicts `pass`, `fail` and `undecided`.
- Command line with `--json`, `--verbose`, `--max-seconds` and `--max-answer-sets`; exit codes `CLAIMS_HOLD` (0), `CLAIM_UNMET` (1) and
  `FAULT` (2), and `INTERNAL_ERROR` (3) for a failure of elenctic itself, reported as one line on
  stderr. They are the members of `elenctic.report.Exit`, an `IntEnum`, the outcome of `test`; `version` has its
  own, `elenctic.about.VersionExit` (`REPORTED` 0, `INTERNAL_ERROR` 3), so no member is shared.
- Native cautious and brave consequences (`Grounded.consequences`), used by `check` when a search
  holds only such claims.
- Minimal unsatisfiable cores over assumptions: `Refutation` is `These | NotThese | NoAssumptions`.
- Optimization: `Grounded.optimize` returns `Optimum` or `Incumbent`; claims `@answer-set optimal`,
  `@cautious optimal`, `@brave optimal`, `@optimal { L }`, `@count optimal n` and `@cost { … }`.
- Preconditions that make a misreadable contract an error: theory atoms, an objective that grounds
  away, a nested `@count optimal`, a derivable unshown contrary under `no`/`unknown`.
- Subcommands: `elenctic test` (the default) and the reserved `repl`, `why`, `ask`, `explain`.
- `elenctic version`, `--version` and `-V`: one text with the version, the license, the holder and the
  versions of clingo and clingcon that are loaded. `--version` and `-V` are options of `elenctic`
  itself: valid before the command and winning over the rest of the line, not taken by a command.
- Every type that a public signature names is exported, so a signature can be read and a value built
  from `elenctic` alone: the readings `Satisfiable`, `Census`, `Witness`, `Entails`, `Asks`, `Binds`
  and their union `Reading`, the query parts `All` and `Any`, `Shown`, `Found` and `Cut`. A test walks
  the signatures of `__all__` and fails on a type left out. `elenctic.Any` is the disjunction of
  queries, not `typing.Any`.
- Examples with real output in `docs/reference/examples.md`, checked by a test.
- Packaging for uv, pixi and conda-forge (`recipe/recipe.yaml`).
- clingcon: `% @elenctic solver clingcon` in a contract, claims `@assign [optimal] { x=1, … }` and
  `@answer-set … where { x=1, … }`, the library types `Solver`, `Assignment`, `Valuation` and
  `AnswerSet.assignment`. An answer under clingcon is a shown set with its assignment, and `@count`
  counts those. Optional: `elenctic[theory]`, or the pixi `theory` environment; a contract that
  declares clingcon without it is an error (`FAULT`, 2).

- `--color auto|always|never` (default `auto`) and `--icons[=WHEN]` (Nerd Font glyphs, off unless asked),
  each decided per stream, and valid before the command as well as after it. `auto` follows
  `NO_COLOR`, `TERM=dumb`, then whether the stream is a terminal, so a redirected stream stays plain; only `--color always` colors it. `CLICOLOR_FORCE`,
  `CLICOLOR` and `FORCE_COLOR` are not read. This governs elenctic's own report and diagnostics;
  the help and usage messages are colored as Python's `argparse` does by default. See the output
  section of the reference.

### Changed
- Limits are named for what they bound: `--max-seconds` (was `--budget`) and `--max-answer-sets` (was
  `--models`), `Limits.max_seconds` and `Limits.max_answer_sets`, `DEFAULT_MAX_SECONDS` and
  `DEFAULT_MAX_ANSWER_SETS`, and the truncations `MAX_SECONDS` and `MAX_ANSWER_SETS`. `UNLIMITED` is gone: use `Limits()`.
- One answer set is an answer set everywhere: the tag `@answer-set` (was `@model`), the types `AnswerSet` (was
  `Model`) and `AnswerSets` (was `Models`), `Atoms` (was `AnswerSet`), `Optimum.answer_sets`,
  `Incumbent.answer_set`, `Seen.answer_set` and `search.answer_sets()`, and the same keys in the JSON.
  The old names are gone.
- Every enum value in the JSON is snake_case, and each is its member's name in lower case, so the
  truncations are `max_answer_sets`, `max_seconds` and `interrupted`; the command-line flags keep their
  hyphens.
- The `kind` of every JSON object is its type's name in snake case (`report`, `entails`, `answer_set`), derived in
  one place, `json_view.kind_of`.
- A search cut short is worded for people by the text view: `search ended: answer-set limit reached
  (--max-answer-sets)`, `time limit reached (--max-seconds)` or `interrupted`, where the text said
  `max_answer_sets`. A finding's `detail` is text or `Ended` (the `Truncation`, and whether an optimum went
  unproven), which is an object in the JSON; `Detail` and `Ended` are exported. The option names come from
  `determination.option`, which the command line uses too.

- Diagnostics for a source that could not be checked go to stderr, with the reserved-command note
  and the internal-error line; verdicts and the summary stay on stdout. `--json` is all on stdout.
- The terminal text is `elenctic.human`, the JSON is `elenctic.json_view` (`encode`, moved from
  `elenctic.report`, which holds the run's values); escape sequences are written by `elenctic.paint`
  alone.
- `pixi run -e theory check` is the one documented gate; `check.sh` only runs it. `uv.lock` is tracked.
  The CI uv job is a secondary install check (`uv sync --locked`, then the tests).
- `--max-seconds` and `--max-answer-sets` take a positive number or the word `all` (no limit); `--max-answer-sets` defaults to
  100,000 (`DEFAULT_MAX_ANSWER_SETS`), so a search that would read more is `undecided`; `--max-answer-sets all` lifts
  it. The library default stays `Limit.UNBOUNDED`. `0` and negative values are a usage error: `--max-seconds 0` used to mean no limit and `--max-answer-sets 0`
  an immediate cut. `Limits.max_seconds` and `Limits.max_answer_sets` are a number or `Limit.UNBOUNDED`, replacing
  `None`.
- A refutation by assumptions whose core may not be minimal (the search was cut short) now says so.
- `@cost` over `#maximize` is accepted: costs are clingo's minimized sums, so a maximized level is
  negated.
- A `no`/`unknown` query faults only when its contrary is derivable and not shown.
- A theory atom with no `#theory` declaration is reported with elenctic's own message and location
  rather than clingo's.
- The theory-atom error points at the first theory atom, not at line 1.

### Fixed
- A query faults when it reads a literal the program can derive and does not `#show`, whatever its answer:
  `-b. #show b/0.` with `@query yes { -b }` was a false failure and with `@query unknown { -b }` a false
  pass. The gate had checked only the contraries read by `no` and `unknown`, and still does, so a
  contrary the program cannot derive needs no `#show`.
- `Program.read` accepts any path-like (`str | PathLike`).
- A search is about 2.3 times faster: an answer set is read into literals only once it is kept, and each
  clingo symbol is converted once.
- Native `@cautious`/`@brave` under a limit on answer sets are decided from the solver, not the cut search.
- A minimal core is tested on a non-trivial case and under a time limit (`minimal=False`).
- A native `@cautious`/`@brave` claim is judged only from a search that ran to its end; if the search
  was cut by a limit on seconds or answer sets, or by an interrupt, it is undecided, where it was reported as a pass or a
  fail on the partial set.
- A term nested thousands deep in a theory atom, an objective or a `#show` is checked or refused
  instead of raising `RecursionError`.
- Program text in the terminal report is shown with control characters escaped, so a program cannot
  write terminal control sequences; JSON is unchanged.
- A file that is not UTF-8 is a refusal of the request (`FAULT`, 2), not a traceback.
- `pixi run check` prints the number of tests: pytest was given `-q` twice.
