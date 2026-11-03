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
| `--color WHEN` | colour the text: `auto` (default), `always` or `never` |
| `--icons[=WHEN]` | mark claims with Nerd Font glyphs: `auto`, `always` or `never`; given bare it is `auto`, left out it is `never`. A value takes an equals sign: `--icons always` names a path |
| `--budget SECONDS\|all` | time allowed per search, in seconds (a positive number), or `all` for no limit (default 30) |
| `--models N\|all` | most answer sets read per search (a positive integer), or `all` for no limit (default 100,000) |

Zero and negative values of `--budget` and `--models` are a usage error (`FAULT`, 2). In the library the same
choice is `Limits(seconds=…, models=…)`, each a number or `Limit.UNBOUNDED`, which is the default of the library; only the command line has a default cap.

`elenctic version`, `elenctic --version` and `elenctic -V` print the same two lines on stdout and
exit `CLAIMS_HOLD` (0); `version` is a command, so a file of that name is written `./version`.
`--version` and `-V` are options of `elenctic` itself, as in `git --version`: they stand before the
command (or alone) and win over the rest of the line, so `elenctic --version test x.lp` prints the
version; a command does not take them, so `elenctic test --version` is a usage error (`FAULT`, 2).
`--color` and `--icons` may stand before the command too, as in `elenctic --icons --version`; a
command's own `--color` or `--icons` overrides them. The
first line is `elenctic VERSION | © 2026 Gregory Gelfond | MIT`: the version and licence are those of
the installed package, the holder is its author. The second is the versions of clingo and clingcon as
loaded, such as `clingo 5.8.2 | clingcon 5.2.1`, or `clingcon not installed`. With `--icons` the
copyright sign is the Nerd Font glyph `fa-copyright`; the text takes no colour.

`repl`, `why`, `ask` and `explain` are reserved: each writes a note on stderr and exits `FAULT` (2).
`--color` and `--icons` apply to every command; the other options belong to `test`.

## Output

Verdicts and the summary go to stdout; diagnostics for sources that could not be checked, the
reserved-command note and the internal-error line go to stderr. With `--json` the whole document is
on stdout and is never coloured or marked with glyphs.

Colour and glyphs are decided for each stream on its own, so `elenctic … > run.txt` leaves stderr
coloured on a terminal. Colour, `auto`, is decided in this order; the first rule that applies wins.

| Order | Rule | Colour |
|---|---|---|
| 1 | `--color always` or `--color never` | on or off |
| 2 | `NO_COLOR` is set and not empty | off |
| 3 | `TERM` is `dumb` | off |
| 4 | the stream is a terminal | on, else off |

A redirected stream (a pipe or a file) stays plain in `auto` whatever the environment says;
`--color always` is the one way to colour it. `CLICOLOR_FORCE`, `CLICOLOR` and `FORCE_COLOR` are
not read. This decision covers elenctic's own report and diagnostics. The help and usage messages
are written by Python's `argparse`, which colours them by its own defaults, including
`FORCE_COLOR`, `PYTHON_COLORS` and `NO_COLOR`; `--color` does not reach them.

Glyphs ignore the environment. `--icons=always` marks claims with a glyph in place of `[PASS]`,
`[FAIL]` and `[UNDECIDED]`; `auto` does so on a terminal; `never` and no option leave the text.
Glyphs and colour are independent. The glyphs are from a Nerd Font: a terminal without one shows
boxes, which is why they are off unless asked for. Program text is made legible before it is
coloured or marked, so a program cannot write escape sequences.

Colours by role: error `1;31` (a `FAIL`, an error, an internal error), warning `1;33`
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
of the same kind are independent claims: two `@model` claims are two existential claims.

| Claim | Holds when |
|---|---|
| `@expect sat` / `@expect unsat` | the program has / has no answer set |
| `@count n` | exactly `n` distinct shown answer sets; under clingcon, distinct (shown atoms, assignment) pairs |
| `@model { L }` | some answer set shows exactly `L` |
| `@model { L } where { x=1, … }` | some answer set shows exactly `L` and assigns each variable that integer (clingcon) |
| `@assign { x=1, … }` | some answer set assigns each variable that integer (clingcon) |
| `@cautious { L }` | `L` is in every answer set (⋂ AS(P)); computed by the solver |
| `@brave { L }` | `L` is in some answer set (∪ AS(P)); computed by the solver |
| `@query A { L, … }` | the three-valued answer to the query is `A` (`yes`, `no`, `unknown`) |
| `@query A { p(X, b) } = { 1, 2 }` | the bindings of `X` with answer `A` are exactly these |
| `@model optimal { L }`, `@cautious optimal { L }`, `@brave optimal { L }` | the same, over the optimal answer sets Opt(P); `@optimal { L }` is `@model optimal { L }` |
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
- under `@expect unsat`, a model claim other than `@count 0`; under `@expect sat`, `@count 0`
  (each judged under the same assumptions).
## Verdicts

`pass`, `fail`, `undecided`. A report's verdict is the worst, with `fail` over `undecided`. A
search cut short by `--budget` or `--models` can pass an existential claim (a witness was seen) or
fail a universal one (a counter-example was seen); anything else it leaves `undecided`.

## Library

Everything in `elenctic.__all__`, and nothing else is promised; from 1.0 it follows semver, and
until then the changelog's Unreleased section is the record. Results are frozen dataclasses; spans
are half-open, `[start, end)`, one-based. Use one search at a time per `Grounded`; this is not
enforced.

| Question | Call | Result |
|---|---|---|
| Is there an answer set? Which? | `solve(program, scenario)` | `Determination[Models]` |
| What is cautious or brave? | `Grounded.consequences(mode, scenario)` | `Determination[Consequences]` |
| What is optimal, at what cost? | `Grounded.optimize(scenario)` | `Determination[Optimized]` |
| Over which solver? | `solve(program, solver=Solver.CLINGCON)`, `ground(program, solver)` | the same; a `Model` carries its `assignment` |
| Why is there none? | the `Inconsistent` result's `refutation` | `These`, `NotThese` or `NoAssumptions` |
| Do two patterns have a common instance? | `mgu(first, second)` | a `Unifier`, or `None` |

`mgu` renames the two patterns apart, so that a variable of one is not the variable of the other for
having the same name, and returns a `Unifier`: the two renamed patterns, the `Substitution` that
makes them one, and `instance`, the pattern both become (the most general common instance). It is
public for answering queries and for the interactive session to come; `Pattern.match`, which reads a
pattern off a ground answer set, does not use it.

## JSON

`{"schema": 1, "run": {"entries": [...]}, "exit_code": n}`, where `n` is the `Exit` of that `test` run (0, 1 or 2); see `elenctic.json_view.encode`. A
dataclass becomes `{"kind": TypeName, field: …}`, an enum its value, a set a sorted list.

## Examples

[Every claim kind with its real output](examples.md).
