# Reference

## Command line

`elenctic [test] PATH…` checks programs against the contracts in their comments. `PATH` is an
`.lp` file or a directory searched for them. With no command the arguments are paths; a path named
like a command is written `./why`.

| Option | Meaning |
|---|---|
| `--json` | write the run as JSON |
| `-V`, `--version` | print the version and exit; stands before the command (below) |
| `-v`, `--verbose` | list the claims that passed |
| `--color WHEN` | color the text: `auto` (default), `always` or `never` |
| `--icons[=WHEN]` | mark claims with Nerd Font glyphs: `auto`, `always` or `never`; given bare it is `auto`, left out it is `never`. A value takes an equals sign: `--icons always` names a path |
| `--max-seconds SECONDS\|all` | time allowed per search, in seconds (a positive number), or `all` for no limit (default 30) |
| `--max-answer-sets N\|all` | most answer sets read per search (a positive integer), or `all` for no limit (default 100,000) |

Zero and negative values of `--max-seconds` and `--max-answer-sets` are a usage error (`FAULT`, 2). In the library the same
choice is `Limits(max_seconds=…, max_answer_sets=…)`, each a number or `Limit.UNBOUNDED`, which is the default of the library; only the command line has default limits.

`elenctic version`, `elenctic --version` and `elenctic -V` print the same two lines on stdout and
exit `CLAIMS_HOLD` (0); `version` is a command, so a file of that name is written `./version`.
`--version` and `-V` are options of `elenctic` itself, as in `git --version`: they stand before the
command (or alone) and win over the rest of the line, so `elenctic --version test x.lp` prints the
version; a command does not take them, so `elenctic test --version` is a usage error (`FAULT`, 2).
`--color` and `--icons` may stand before the command too, as in `elenctic --icons --version`; a
command's own `--color` or `--icons` overrides them. The
first line is `elenctic VERSION | © 2026 Gregory Gelfond | MIT`: the version and license are those of
the installed package, the holder is its author. The second is the versions of clingo and clingcon as
loaded, such as `clingo 5.8.2 | clingcon 5.2.1`, or `clingcon not installed`. With `--icons` the
copyright sign is the Nerd Font glyph `fa-copyright`; the text takes no color.

`repl`, `why`, `ask` and `explain` are reserved: each writes a note on stderr and exits `FAULT` (2).
`--color` and `--icons` apply to every command; the other options belong to `test`.

## Output

Verdicts and the summary go to stdout; diagnostics for sources that could not be checked, the
reserved-command note and the internal-error line go to stderr. With `--json` the whole document is
on stdout and is never colored or marked with glyphs.

Color and glyphs are decided for each stream on its own, so `elenctic … > run.txt` leaves stderr
colored on a terminal. Color, `auto`, is decided in this order; the first rule that applies wins.

| Order | Rule | Color |
|---|---|---|
| 1 | `--color always` or `--color never` | on or off |
| 2 | `NO_COLOR` is set and not empty | off |
| 3 | `TERM` is `dumb` | off |
| 4 | the stream is a terminal | on, else off |

A redirected stream (a pipe or a file) stays plain in `auto` whatever the environment says;
`--color always` is the one way to color it. `CLICOLOR_FORCE`, `CLICOLOR` and `FORCE_COLOR` are
not read. This decision covers elenctic's own report and diagnostics. The help and usage messages
are written by Python's `argparse`, which colors them by its own defaults, including
`FORCE_COLOR`, `PYTHON_COLORS` and `NO_COLOR`; `--color` does not reach them.

Glyphs ignore the environment. `--icons=always` marks claims with a glyph in place of `[PASS]`,
`[FAIL]` and `[UNDECIDED]`; `auto` does so on a terminal; `never` and no option leave the text.
Glyphs and color are independent. The glyphs are from a Nerd Font: a terminal without one shows
boxes, which is why they are off unless asked for. Program text is made legible before it is
colored or marked, so a program cannot write escape sequences.

Colors by role: error `1;31` (a `FAIL`, an error, an internal error), warning `1;33`
(`UNDECIDED`), note `1;32` (`PASS`), help `1;36` (the reserved-command note), margin `1;34` (line
numbers) and emphasis `1` (sources and the summary).

## Exit codes

Each command returns an outcome of its own, an `IntEnum` that states its process code once; the
values are fixed. `elenctic test` (and the refusal of a reserved command) returns
`elenctic.report.Exit`:

| Name | Value | Meaning |
|---|---|---|
| `CLAIMS_HOLD` | 0 | every claim passed |
| `CLAIM_UNMET` | 1 | some claim failed or was undecided |
| `FAULT` | 2 | some file could not be checked, or the command was refused |
| `INTERNAL_ERROR` | 3 | elenctic itself failed; one line on stderr, no traceback |

`elenctic version` returns `elenctic.about.VersionExit`, a different type that shares codes with
`Exit` and not members:

| Name | Value | Meaning |
|---|---|---|
| `REPORTED` | 0 | the text was written |
| `INTERNAL_ERROR` | 3 | the metadata or the solvers could not be read; one line on stderr |

A usage error is argparse's, status 2, before any command runs.

## Contract syntax

A claim is a comment line beginning `%` followed by a tag. A brace group may continue over
following comment lines. A contract has exactly one `@expect`, without `assuming`. Several claims
of the same kind are independent claims: two `@answer-set` claims are two existential claims.

| Claim | Holds when |
|---|---|
| `@expect sat` / `@expect unsat` | the program has / has no answer set |
| `@count n` | exactly `n` distinct shown answer sets; under clingcon, distinct (shown atoms, assignment) pairs |
| `@answer-set { L }` | some answer set shows exactly `L` |
| `@answer-set { L } where { x=1, … }` | some answer set shows exactly `L` and assigns each variable that integer (clingcon) |
| `@assign { x=1, … }` | some answer set assigns each variable that integer (clingcon) |
| `@cautious { L }` | `L` is in every answer set (⋂ AS(P)); computed by the solver |
| `@brave { L }` | `L` is in some answer set (∪ AS(P)); computed by the solver |
| `@query A { L, … }` | the three-valued answer to the query is `A` (`yes`, `no`, `unknown`) |
| `@query A { p(X, b) } = { 1, 2 }` | the bindings of `X` with answer `A` are exactly these |
| `@answer-set optimal { L }`, `@cautious optimal { L }`, `@brave optimal { L }` | the same, over the optimal answer sets Opt(P); `@optimal { L }` is `@answer-set optimal { L }` |
| `@assign optimal { x=1, … }` | the same, over the optimal answer sets |
| `@count optimal n` | exactly `n` distinct shown optimal answer sets |
| `@cost { c1 c2 … }` | the optimum's cost, highest priority first, is exactly this (see below) |
| any of the above `assuming { l, not l }` | the claim is judged under those assumptions |

`@note` is ignored. `% @elenctic solver clingcon` (or `clingo`, the default) names the solver the
contract is checked with; it needs `elenctic[theory]`, and is a fault (`FAULT`, 2) when clingcon is
not installed. A variable is a term of the program (`x`, `digit(s)`), an integer its value.

### Costs

A cost is the minimized sum per priority level, as clingo reports it. A `#maximize` level is
negated: `@cost { -5 }` claims that the optimum of a `#maximize` is 5.

### Preconditions

A contract that would be misread is not judged; the file is reported as an error (`FAULT`, 2):

- the program has theory atoms and the contract does not declare `% @elenctic solver clingcon`
  (clingo would ground them and ignore their constraints);
- a theory objective (`&minimize`), which clingcon applies in every search and clingo's cost does
  not see;
- `@assign` or `where` under clingo, which has no assignment to read;
- an `optimal` or `@cost` claim over a program whose objective grounds away;
- `@count optimal N` greater than an explicit `@count M`;
- a `no` or `unknown` query that reads a contrary `-p` off the shown atoms when the program can
  derive `-p` and does not `#show` it;
- no `@expect`, more than one, or more than one `% @elenctic solver`;
- under `@expect unsat`, an answer set claim other than `@count 0`; under `@expect sat`, `@count 0`
  (each judged under the same assumptions).
## Verdicts

`pass`, `fail`, `undecided`. A report's verdict is the worst, with `fail` over `undecided`. A
search cut short by `--max-seconds` or `--max-answer-sets` can pass an existential claim (a witness was seen) or
fail a universal one (a counter-example was seen); anything else it leaves `undecided`.

## Library

Everything in `elenctic.__all__`, and nothing else is promised; from 1.0 it follows semver, and
until then the changelog's Unreleased section is the record. Results are frozen dataclasses; spans
are half-open, `[start, end)`, one-based. Use one search at a time per `Grounded`; this is not
enforced. Every elenctic type that a public signature names is among them (a test checks it),
so `from elenctic import *` brings `All` and `Any`, the parts of a `Query`; `Any` is not `typing.Any`.

| Question | Call | Result |
|---|---|---|
| Is there an answer set? Which? | `solve(program, scenario)` | `Determination[AnswerSets]` |
| What is cautious or brave? | `Grounded.consequences(mode, scenario)` | `Determination[Consequences]` |
| What is optimal, at what cost? | `Grounded.optimize(scenario)` | `Determination[Optimized]` |
| Over which solver? | `solve(program, solver=Solver.CLINGCON)`, `ground(program, solver)` | the same; an `AnswerSet` carries its `assignment` |
| Why is there none? | the `Inconsistent` result's `refutation` | `These`, `NotThese` or `NoAssumptions` |
| Do two patterns have a common instance? | `mgu(first, second)` | a `Unifier`, or `None` |

`mgu` renames the two patterns apart, so that a variable of one is not the variable of the other for
having the same name, and returns a `Unifier`: the two renamed patterns, the `Substitution` that
makes them one, and `instance`, the pattern both become (the most general common instance). It is
public for answering queries and for the interactive session to come; `Pattern.match`, which reads a
pattern off a ground answer set, does not use it.

## Names

Each name in `elenctic.__all__`, once; a test fails on a name that has no row.

### Programs and searches

| Name | What it is |
|---|---|
| `Program` | ASP source text and where it came from |
| `Grounded` | a program grounded once, to be searched under any number of scenarios |
| `ground` | ground a program for a `Solver`: a `Grounded`, or a `Fault` saying why not |
| `solve` | enumerate the answer sets of a program under a scenario |
| `Solver` | what a contract is checked with: `CLINGO`, or `CLINGCON`, which adds the clingcon theory |
| `Fault` | a failure that is no answer about the program: it could not be asked; `locus` says whose, `diagnostics` what |
| `Locus` | whose fault it is: `PROGRAM` or `REQUEST` |
| `Request` | what a search is asked: a `Scenario`, its `Limits` and an optional `Interrupt` |
| `Limits` | how far a search may go, in seconds and in answer sets read, each a number or `Limit.UNBOUNDED` |
| `Limit` | what a limit may be besides a number: `UNBOUNDED` |
| `Interrupt` | a request to stop, made from any thread with `pull()` and heeded between answer sets |
| `Cut` | the function a search asks whether to stop: a `Truncation`, or `None` to go on |
| `Facts` | what the grounded program says about itself, against which a contract is checked |
| `Shown` | the predicates `#show` selects; with no `#show` every atom is shown |

### Results of a search

| Name | What it is |
|---|---|
| `Determination` | a search's result: `Consistent`, `Inconsistent` or `Inconclusive`, over its evidence |
| `Consistent` | an answer set exists; `evidence` is what the search found and `conclusion` how it ended |
| `Inconsistent` | the search covered everything and no answer set satisfies the request; `refutation` says why |
| `Inconclusive` | the search was cut short before it decided |
| `Conclusion` | how a consistent search ended: `Exhausted` or a `Truncation` |
| `Exhausted` | the search covered every answer set under the request |
| `Truncation` | the search was cut short, and by what |
| `AnswerSets` | at least one answer set, in the order the solver found them |
| `Consequences` | the atoms true in every (cautious) or some (brave) answer set, among those shown |
| `Optimized` | the evidence of an optimization: an `Optimum` or an `Incumbent` |
| `Optimum` | a proven optimum: its cost and the optimal answer sets found (all, if exhausted) |
| `Incumbent` | the best answer set found before the search was cut: not proven optimal |
| `Refutation` | why there is no answer set: `These`, `NotThese` or `NoAssumptions` |
| `These` | these assumptions, no fewer when `minimal`, admit no answer set |
| `NotThese` | no answer set whatever is assumed, and something is assumed |
| `NoAssumptions` | no answer set, and nothing is assumed |
| `AnswerSet` | an answer set: every atom, the atoms `#show` selects, its theory assignment and cost |
| `Mode` | `CAUTIOUS` or `BRAVE`: consequences true in every, or in some, answer set |
| `Range` | the range of answer sets a value ranges over: `ALL` answer sets, or the `OPTIMAL` ones |
| `Cost` | an optimum's cost, one integer for each priority level |
| `Assignment` | an answer set's theory assignment: a set of `Valuation` |
| `Valuation` | a theory variable and the integer an answer set gives it |

### Literals and terms

| Name | What it is |
|---|---|
| `Literal` | a ground classical literal: `p(t, ...)`, or `-p(t, ...)` when not `positive` |
| `Signature` | a predicate with its arity and sign: `p/1`, or `-p/1` |
| `Atoms` | a set of `Literal` |
| `Assumption` | a literal taken to hold, or, when not `holds`, taken not to |
| `Scenario` | a set of `Assumption` under which a search is made |
| `Term` | a clingo symbol, a `Variable` or a `Compound` |
| `Variable` | a named variable; `_` is anonymous, and each of its occurrences is a different variable |
| `Compound` | a function term `f(...)`, `-f(...)` when not `positive`, or a tuple (empty `name`) |
| `Pattern` | a literal whose arguments may be terms with variables, nested to any depth |
| `Substitution` | what some variables stand for, as the matching or unifying of patterns found |
| `Extension` | literals ordered by signature, so that those a pattern can match are found by binary search |
| `mgu` | the most general unifier of two patterns, or `None` |
| `Unifier` | two patterns renamed apart, the `Substitution` that makes them one, and the `instance` both become |

### Queries

| Name | What it is |
|---|---|
| `Query` | what a `WorldView` is asked: `Literal \| Pattern \| All \| Any` |
| `All` | the conjunction of its parts |
| `Any` | the disjunction of its parts; not `typing.Any` |
| `Answer` | `YES`, `NO` or `UNKNOWN`: a query true in every answer set, false in every one, or neither |
| `Truth` | truth in one answer set, ordered `FALSE < UNKNOWN < TRUE`, so that conjunction is `min` and disjunction `max` |
| `evaluate` | a query's `Truth` in one answer set |
| `answer` | a query's `Answer` over a `WorldView` |
| `Bindings` | the values of a pattern's variables that give each answer; `giving(answer)` selects those of one |
| `bindings` | the `Bindings` of a pattern over a `WorldView` |
| `WorldView` | the answer sets of a program, all of them: only an exhausted search yields one |
| `world_view` | close a consistent search over answer sets into its `WorldView`, or give the `Truncation` that left it open |
| `optimal_view` | close a proven optimum into the `WorldView` of its optimal answer sets, or give what cut it |

### Contracts and verdicts

| Name | What it is |
|---|---|
| `check` | check the contract written in a program: a `Report`, or `None` if it carries none |
| `parse_contract` | read each tag of a text: a claim for every one that reads, a diagnostic for the rest |
| `render` | write a claim as the tag line that reads back to it |
| `judge` | judge one claim against the search over its scenario: a `Finding` |
| `Contract` | the claims of a source, the diagnostics of its tags and its `solver` |
| `Claim` | a `Reading` to hold under a `Scenario`, and where it was written |
| `Reading` | the meaning of one tag: one of the eight below |
| `Satisfiable` | `@expect sat \| unsat` |
| `Census` | `@count [optimal] n` |
| `Witness` | `@answer-set [optimal] { L } [where { A }]`, or `@optimal { L }` |
| `Assigns` | `@assign [optimal] { A }` |
| `Entails` | `@cautious [optimal] { L }` and `@brave [optimal] { L }` |
| `Costs` | `@cost { c1 c2 ... }` |
| `Asks` | `@query A { L, ... }`: a conjunction of ground literals has the answer `A` |
| `Binds` | `@query A { q(X, ...) } = { B }`: the bindings giving `A` are exactly `B` |
| `Finding` | a claim, the verdict on it, and what was expected against what was found |
| `Found` | a search `judge` can read: a `Determination` over `AnswerSets`, `Consequences` or `Optimized` |
| `Report` | the findings for one source; `verdict` is `FAIL` if any fails, else `UNDECIDED` if any is, else `PASS` |
| `Verdict` | `PASS`, `FAIL` or `UNDECIDED` |

### Sources

| Name | What it is |
|---|---|
| `Position` | a point in a source; line and column both count from 1 |
| `Span` | the half-open stretch of a source from `start` to `end` |
| `Diagnostic` | a message about a `Span`, with its `Severity` |
| `Severity` | `ERROR`, `WARNING` or `NOTE` |

## JSON

`{"schema": 1, "run": {"entries": [...]}, "exit_code": n}`, where `n` is the `Exit` of that `test` run (0, 1 or 2); see `elenctic.json_view.encode`. A
dataclass becomes `{"kind": type_name, field: …}`, the `kind` being the type's name in snake case (`Census` is `census`, `AnswerSet` is `answer_set`), an enum its value, a set a sorted list. Keys and enum values are snake_case (`max_answer_sets`);
the command-line flags keep their hyphens (`--max-answer-sets`).

## Examples

[Every claim kind with its real output](examples.md).
