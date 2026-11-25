# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-11-19

### Added
- `elenctic explain PATH…`: `test`, then the evidence for each failed claim: the counterexample,
  and a tree in which each step shows its ground rule instance and line, `file:line` for a rule
  from a file other than the case's. `--spans` adds each rule as written with its substitution;
  `--max-depth N|all` bounds how many absences deep it goes (default 3).
- `elenctic why PATH QUERY`: what warrants the answer `ask` gives a query, in its `--mode`, or one
  binding's, `--binding 'X = a'`, under `--assuming L,…`, of all or `--over optimal` (refused,
  as an optimal claim is, for a program with no objective): the
  `Warrant` below, in `ask`'s block, headed `why:` and the instance. `--answer-set K`: why
  `QUERY`, a ground literal, holds, or not, in the K-th answer set; the block of `explain`, headed
  `why:` and the atom as it was asked, `not` kept. An option of one form given to the other is
  refused.
- `elenctic ask PATH QUERY`: a query, written as `@query` writes it, answered over the answer sets,
  with the first answer set taking each value, or a pattern's bindings. A query, in `ask`, `why`
  and `@query`, may put `not` before a literal (true where the literal is absent), may end with a
  full stop, and refuses `;`; a query that starts with `-`, `ask PATH -p(X)`, is not taken for an
  option. `ask --mode default|cautious|brave`: the Gelfond–Kahl three-valued answer, or `yes` /
  `not entailed` (true in every answer set or not), or `yes` / `none holds` (true in some or none,
  naming only answer sets where it is true); `Answer` gains `NOT_ENTAILED` and `NONE_HOLDS`, and
  `Answered` its `mode`.
- A query with variables may be a conjunction, `{ p(X), not q(X) }`, each instance answered over
  every answer set: `answers`, `Answers` of `Bound`, and the JSON `answers` kind, which replaces
  `bindings` in `ask` output. `ask` writes the bindings one a line, `= yes: X = a`, after their
  counts, and ends with `= no more bindings`, in place of the grouped `= yes bindings: { … }`;
  `unknown` ones only with `--unknown`. `stream` yields them in that order. A brave search cut
  short keeps the `yes` it found, `Answered.cut` saying what cut it, and exits 1.
- `Session.warrant` gives what shows an answer, or a binding's: `Warrant`, its witnesses (one
  answer set where it is true for `yes`; for `unknown`, one where it is not true and one where it
  is not false) and, for an answer every answer set must give, the refutation of the program kept
  to the answer sets that would overturn it. `why` and `ask` each exit with their own outcome,
  `WhyExit` or `AskExit`; `repl` stays reserved.
- `--with FILE`, repeatable, for `test`, `explain`, `why` and `ask`: a library, such as a base
  encoding, loaded with every case after its own text, as clingo loads the files it is given. A
  file the case already loads is not loaded again. The root defaults to the directory that holds
  every path and `--with` file, and is refused when that is the file system's root or holds the
  home directory. A `--with` file that cannot be read, lies outside `--root` or carries a contract
  tag is refused, and no case runs. `Program` takes `libraries`, which `check`, `why` and `ask`
  hold by default to the directory that holds the program's file and them; the library reads no
  home directory, so only the file system's root is too wide. A JSON entry lists them as `libraries`.
- `why` and `ask` take `--root DIR` and `--with` as `test` does, and a refused root or `--with`
  file stops them before they run; a `PATH` that is a directory is a usage error.
- Library: `why(program, query, …)`, a `Warrant`, or given an `index`, an atom's `Explanation`,
  and `ask(program, query, …)`; `Session.answer(query, scenario, over=)`, `answered`, `Answered`
  and `Taken`. `Session.counterexample` gives the refutation when
  there is no answer set.
- JSON: `why` and `ask` write their result under their names, `{"schema": 1, "why": …}`; the schema
  gains them, `answered`, `taken`, `answers`, `bound`, `warrant` and the query part `not`, and a
  run is written as before.
- Library: `session(program, solver)` and `Session`, a `Grounded` with `counterexample(index,
  scenario, over=)`, `explain(literals, counterexample)`, `outrank(literals, scenario)` and
  `evidence(finding)`; `evidenced(report, program)`; the model: `Explanation`, `Counterexample`,
  `Node`, `Handle`, `Rule`, `Minimality`, the `Reason` kinds (`Fact`, `Derived`, `Chosen`,
  `NotChosen`, `Aggregate`, `TheoryAtom`, `Unsupported`, `Blocked`, `NoRule`, `Unexpanded`,
  `Unexplained`), `Outranked`, `Paid` and `Evidence`.
- `Finding.evidence`, `None` unless `explain` found some. In JSON a finding has an `evidence` key
  only then, so a `test` run is written as before; a `Substitution` is written as a string. The
  schema gains the new kinds and nothing else changes.
- Text roles `aside` (italic) and `reference` (dim), and a Nerd Font glyph for each kind of evidence
  line, shown with `--icons`.
- Five examples of evidence: `absent.lp`, `chain.lp`, `laptop.lp`, `late.lp`, `team.lp`.
- The interactive view, `--format tui`, from the optional `tui` extra (Textual 8): what `explain`,
  `why`, `ask` or `test` found as a tree, each row the text view's line in its roles and glyphs,
  with a pane for the selected step's rule as written, or the first one cited below the selected
  row. `+` asks the library for one absence more, ⏎ on a shared step reaches its first row and on an
  answer set `ask` names shows `why`, `test` finds a claim's evidence when it is opened. `explain`,
  `why` and `ask` open it by default when the extra is installed and stdin and stdout are terminals;
  `test` writes text unless asked. It calls the library off its own thread, so the keys answer while
  a search runs; Esc stops it, Ctrl-C quits. `?` lists the keys that apply, and the view's own parts
  take the text view's roles; the selected row is reversed, so each piece keeps its role's colour.
  On a row of how the objective ranks a claim, the pane quotes the weak constraints paid
  differently. A title too long for its bar is cut short, the tally kept whole. After `+` the
  cursor stays on the step it deepened, and on its row as evidence comes in or `f` and `e` change
  the rows around it.
- A `Session` keeps the answer sets it reads of each scenario, in its order, so a counterexample
  keeps its number from call to call: clingo enumerates in another order once it has solved, and
  going deeper (`+`) chose another counterexample than `--max-depth` did. A search that must read on
  numbers only the answer sets it had not read, after them.
- `explain`, `why` and `ask` read only the answer sets they need: a `@cautious`, `@brave` or
  `@expect unsat` counterexample and `why --answer-set K` stop at it, and a one-literal `ask` asks
  apart which answers it is given, then stops once each has been given (`consequences.lp`, with
  2^40 answer sets, takes 0.1 s, not 10). An answer set is named `answer set K`, and `of N` only
  when the search read all N; in JSON its `read` is `null`. `ask` answers a huge program it used to
  end on, and an answer a limit kept it from reaching is `true in an answer set past the 100000
  read: search ended: …` (`unreached` in JSON). A rule's instances are ordered by their values'
  text, each spelled once.
- `--format text|json|tui` on `test`, `explain`, `why` and `ask`, and `--short` for one-line
  diagnostics.

### Changed
- JSON lists a set of literals or valuations in their own order, `p(2)` before `p(10)`, as the text
  does; it sorted them by their encoding. The schema is unchanged.
- A refutation lists its assumptions in the order the claim writes them, `(not b, c)`; it sorted
  them as text. `Assumption` is ordered by literal, then sign.
- A binding claim's detail writes its rows as the claim does: bare for one variable (`{ 2, 10 }`),
  tuples for several (`{ (b,2), (b,10) }`), each in symbol order, so `2` comes before `10`; it wrote
  every row in parentheses, in text order. Claims, details and JSON share that order, and no
  bindings is written `{ }` (it was `{  }`).
- The glyph, role and wording tables move to one module, `legend` (from `glyphs` and `human`), which
  every view reads.
- Four more modules parse, ground or solve with clingo and import it: `clauses`, `relaxation`,
  `instances` and `session`; `support`, `failures`, `holding` and `written`, which explain, do not.
  `classes`, `patterns`, `relation`, `rows` and `terms` no longer do: they meet clingo's terms
  through `literals`, so fourteen modules import clingo (fifteen in 1.0.0). The clingo contract is
  named for that: only the modules that parse, ground or solve with clingo import it; judging and
  reporting never do.
- The legend words the lines the text view drew itself (headings, notes, the costs of an outranked
  result, the weak constraints it pays), so the interactive view reads the same phrases; the text is
  byte for byte the same.
- Each source is split into lines once, by `spans.split_lines`, however many of its lines are read:
  snippets, tags and the reading of a program's rules for evidence. Reading rules is linear in their
  number; it split the whole text for each rule (`ask` over 20,000 facts: 34.6 s, now 9.3 s).

### Deprecated
- `--format full` and `--format short`, read as `--format text` and `--format text --short` with a
  warning on stderr; 2.0 removes them.

### Fixed
- A program with an `#external` stopped a one-literal `ask` or `why`, and a claim assuming an
  external, with an internal error (`KeyError`, exit 3): clingo's core names the externals' values
  too, which are the program's, not assumptions. `assuming { e }` of an external `e` that is false
  admits no answer set, as for any atom no answer set holds.
- A closed stdout, as in `elenctic … | head`, ended the command with an internal error
  (`BrokenPipeError`, exit 3); it ends the process by `SIGPIPE`, quietly, as it ends `ls`.
- An atom the grounding names but no answer set can hold, such as `p(2)` in `q(2). p(X) :- p(X),
  not q(X). q(X) :- q(X), not p(X).`, was taken to be assumable: `assuming { p(2) }` admitted
  answer sets without it, so `@expect sat` passed and `@expect unsat` failed, and `ask` gave
  `unknown` for `no` and, bravely, `yes` for `none holds`. Assuming it now admits no answer set.
- A linked program is held by default to the directory its file resolves to, as on the command
  line; `check` refused it for lying outside its link's directory.
- The root holds every file clingo loads. An `#include` is found as clingo finds it: as written,
  from the working directory, then beside the including file, then under `CLINGOPATH`. The check
  looked only beside the file, so a file clingo found from the working directory, inside the root
  or outside it, went unchecked. `#include <…>` names a built-in program, never a file.
- Comments and strings are read as clingo reads them: block comments nest, a `%` inside one
  comments out the rest of its line, `#!` starts a comment, and a string ends on its line. A
  directive in a nested comment is not followed, one with a comment before its file is, and
  non-ASCII after a `"` that opens no string is refused instead of aborting the process.
- An included file that is not UTF-8 is refused (`cannot read`) instead of aborting the process.
  It, and one refused for non-ASCII outside strings, is named as clingo names it, not resolved.
- A theory atom or objective, and a syntax or grounding error in a program given as text under a
  name, is placed in Unicode columns, as every other span is: after a string with non-ASCII text on
  the same line, its column and caret sat one place right for each extra byte.
- A file clingo loads is named as clingo names it, so its spans are in Unicode columns too: one
  included as `./x.lp` or `sub//x.lp`, through a `CLINGOPATH` directory ending in `/`, or by both
  the program and a library sat in bytes.
- A case, `--with` file or included file that is not a regular file is refused (`cannot read`,
  naming it as clingo does) before it is read: a FIFO hung the run, and a directory or a device
  such as `/dev/null` loaded as an empty file.

## [1.0.0] - 2026-11-06

### Added
- `--root DIR`: one root for every path and `#include` of a run, so a subtree whose cases include
  files from a sibling directory can be tested on its own.
- `Containerfile`: a local multi-stage recipe for the CLI (uv sync from the lockfile with the
  theory extra). Build it yourself; there is no published image and no CI image build.
- Pixi environments `py314` and `py315` for the test suite under those Pythons (`pixi run -e py314 test`).
- JSON Schema for the `--json` document: `docs/reference/output-v1.schema.json`, generated from the
  result types `encode` walks (`elenctic.json_view.schema_document`); regenerate with
  `scripts/write_output_schema.py`. A test fails if the committed file is stale.
- `python -m elenctic` runs the same CLI as the `elenctic` console script (`src/elenctic/__main__.py`).
- Import contracts (import-linter, in `pyproject.toml`): the layering, clingo reached only by the fifteen
  modules that read and run programs, clingcon only by `theory`, and `spans` free of both. They run
  in `pixi run check` and in CI.
- Library: `Program`, `ground`, `solve` with `Limits` and a cancelable `Interrupt`; results as
  `Consistent | Inconsistent | Inconclusive` over `AnswerSets` or `Consequences`.
- Query kernel in the public API: `Literal`, `Pattern`, `Query` (`Literal | Pattern | All | Any`), `Answer`,
  `answer`, `bindings`, over a `WorldView` that only an exhausted search yields.
- A row for every name of `elenctic.__all__` in `docs/reference/reference.md`, checked by a test.
- `mgu(first, second)` and `Unifier`: the most general unifier of two patterns, renamed apart, and
  the pattern both become. Public for answering queries and for the interactive session to come.
- `unify(first, second)`: the same unifier for two patterns that share their variables by name, as a
  `Substitution`. It is what query answering calls; against a ground pattern it agrees with `mgu`.
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
- `@query optimal …`: the same three-valued query path over Opt(P); unqualified `@query` still reads
  AS(P).
- Preconditions that make a misreadable contract an error: theory atoms, an objective that grounds
  away, a nested `@count optimal`.
- `Report.lints`: notes when a query reads a literal the program can derive and does not `#show`.
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

### Fixed
- Docs: JSON `exit_code` includes 3; guides state `world_view` on a truncation; `@expect`-only searches stop once satisfiability is decided.
- Guides: an interrupted `check` yields undecided findings; `solve` yields `Inconclusive`.
- An `#include` that resolves outside the root is refused before the case is run; the diagnostic names the escaping path and never its contents.
- Non-ASCII outside strings and comments is refused with a located diagnostic before clingo sees
  it (program text, `#include`d files, and tag payloads), so a bad character never aborts the
  process; `--json` still emits a document.
- Binding sets keep tuple structure: `{ (1,2) }` for one variable is one binding, and `{ ((1,2),3) }` for two is accepted; a bare `{ a, 1 }` for arity 2 is refused.
- A named `.lp` with no contract tag is a fault (exit 2), not a silent `0/0 passed`; a UTF-8 BOM is refused with a located diagnostic; a walked library whose `@tag` looks misspelled is a note.
- Search groups that read only shown identities project onto `#show`, so `@count` and `@answer-set` no longer enumerate hidden variation; optimal groups prove the cost first, then enumerate at that bound; witness-only groups stop once every claim is decided.


- Undecided truncated claims carry an `Ended` detail in JSON; `world_view` and `optimal_view` range over full answer sets by default; the hidden-read lint covers a query's contrary; `bindings` takes a single `Pattern`.

- JSON entries carry `verdict` and `solver`, omit program `text`; diagnostic `label`/`children` are optional in the schema; `$id` points at the raw file under `docs/reference/`; the schema ships in the wheel.

- An unexpected failure while checking one source is recorded for that source and the rest of the corpus still runs; the run exits 3.

- Satisfiability-only groups keep no answer-set symbols; signatures come from clingo; atom→literal is looked up on demand.

- A refutation core shows `not L` for an assumption that does not hold.
- A one-element tuple keeps its trailing comma when rendered.
- A query that is empty or uses `not` is refused as such; a variable query's help cites the user's pattern.
- `@count optimal 0` under `@expect sat` names `optimal` in the contradiction.
- Empty braces render as `{ }`; `@count` accepts only ASCII digits.
- At most one `@count` per scenario and range.
- `@expect` alone is admitted over a theory objective.

- A second SIGINT restores the default handler so the process can exit 130.

### Changed
- The include refusal says `outside the root DIR` and has a help line.
- An unknown `@model` is told the tag is spelled `@answer-set`; a walked library or a named file
  whose tags are not tags says so (`@model` is not a tag) with the same help as an unknown tag.
- A missing clingcon's help no longer names a pixi environment.
- Consistency across docs, help and internals: truncation prose; reserved-command helps as imperatives; `--help` says "answer set programs"; `(default: …)` in the reference; "source" for a checked unit; stderr prefix rule; `render_run`, `holds_flag`, `Classes.merge`; CLI writes with `write` only; American-spelling and reading-name notes in the README; mechanical checks in `tests/test_consistency.py`.
- Diagnostics follow the rustc model by default (`--format full`): `error: message`, ` --> path:line:col`, a source snippet with carets and a primary label, then `= note:` / `= help:` lines. `--format short` keeps today's one-line gcc form; `--json` is an alias of `--format json`. Messages are lowercase with no trailing period; fix-it wording stands only on `help`. Clingo's byte columns are converted to Unicode scalar columns so carets land. The JSON schema keeps `SCHEMA = 1` and adds optional `label`, `children`, and `code` on `diagnostic` (no codes in 1.0).
- CI cancels superseded pull-request runs (`concurrency` with `cancel-in-progress` on pull requests only).
- `uv.lock` pins clingo 5.8.3 and clingcon 5.2.2 so Python 3.15 installs from wheels.
- The bindings of a query pattern are its most general unifiers with the cautious consequences of
  the full answer sets: yes where it unifies with one, no where its contrary does. The brave
  consequences give only the unknown instances (entertained, neither yes nor no). A ground literal
  is yes when cautious and no when its contrary is. A conjunction or disjunction is still answered
  over each answer set. The answers are unchanged; how they are found is not.
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
- A query that reads a literal the program can derive and does not `#show` is noted (a lint on the
  report), not refused; the note does not change the exit. The old refusal of such queries, and the
  refusal of a `no`/`unknown` query whose contrary was derivable and unshown, are gone: full
  answer-set evaluation makes both gates redundant for correctness. A later `--strict` may promote
  the notes to faults; that flag is not built yet.
- A theory atom with no `#theory` declaration is reported with elenctic's own message and location
  rather than clingo's.
- The theory-atom error points at the first theory atom, not at line 1.

### Removed
- `Pattern.match`, `Pattern.bindings_in` and the module `elenctic.matching`, a one-sided matcher of a
  pattern against ground symbols. Query answering unifies instead (`unify`, the algorithm of `mgu`);
  there is one mechanism for "does this pattern have this instance".

### Fixed
- Reference: `elenctic version` exits `REPORTED` (0), not `CLAIMS_HOLD`.
- A binding query with an anonymous variable, `@query yes { p(_, X) } = { … }`, is refused where it
  is read (`FAULT`, 2: "an anonymous variable has no binding to state: name it") instead of
  failing inside elenctic (`INTERNAL_ERROR`, 3); `bindings` raises `ValueError` for it. An instance
  of such a pattern is not ground, so it has no answer to give.
- Documented that an objective only ranks answer sets and never removes any: unqualified claims and
  every `@query` read all answer sets, and only `optimal` claims and `@cost` read the optimal ones
  (`docs/explanation/semantics.md`, which the reference and the guides point to). The behavior is unchanged.
- Queries evaluate over the full answer sets, not the shown projection: `-b. #show b/0.` with
  `@query yes { -b }` is yes, and `-p. #show p/0.` with `@query yes { p }` reports no (not unknown).
- An empty `no` binding is no longer a vacuous pass when a contrary holds:
  `-p(1). #show p/1.` with `@query no { p(X) } = { }` fails; the no-set is `{1}`.
- A variable `#show X : q(X).` no longer makes every predicate "shown" for coverage checks, and a
  conditional `#show p : r.` no longer counts as unconditionally showing `p`.
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

[1.1.0]: https://github.com/GregoryGelfond/elenctic/releases/tag/v1.1.0
[1.0.0]: https://github.com/GregoryGelfond/elenctic/releases/tag/v1.0.0
