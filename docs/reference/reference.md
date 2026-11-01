# Reference

## Command line

`elenctic [test] PATH…` checks programs against the contracts in their comments. `PATH` is an
`.lp` file or a directory searched for them. With no command the arguments are paths; a path named
like a command is written `./why`.

| Option | Meaning |
|---|---|
| `--json` | write the run as JSON |
| `-v`, `--verbose` | list the claims that passed |
| `--budget SECONDS\|all` | time allowed per search, in seconds (a positive number), or `all` for no limit (default 30) |
| `--models N\|all` | most answer sets read per search (a positive integer), or `all` for no limit (default 100,000) |

Zero and negative values of `--budget` and `--models` are a usage error (`FAULT`, 2). In the library the same
choice is `Limits(seconds=…, models=…)`, each a number or `Limit.UNBOUNDED`, which is the default of the library; only the command line has a default cap.

`repl`, `why`, `ask` and `explain` are reserved: each writes a note on stderr and exits `FAULT` (2).

## Exit codes

The status is `elenctic.report.Exit`, an `IntEnum`; the values are fixed.

| Name | Value | Meaning |
|---|---|---|
| `CLAIMS_HOLD` | 0 | every claim passed |
| `CLAIM_UNMET` | 1 | some claim failed or was undecided |
| `FAULT` | 2 | some file could not be checked, or the command was refused |
| `INTERNAL_ERROR` | 3 | elenctic itself failed; one line on stderr, no traceback |

## Contract syntax

A claim is a comment line beginning `%` followed by a tag. A brace group may continue over
following comment lines. Every contract begins with `@expect`.

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
  derive `-p` and does not `#show` it.

## Verdicts

`pass`, `fail`, `undecided`. A report's verdict is the worst, with `fail` over `undecided`. A
search cut short by `--budget` or `--models` can pass an existential claim (a witness was seen) or
fail a universal one (a counter-example was seen); anything else it leaves `undecided`.

## Library

Everything in `elenctic.__all__`. Results are frozen dataclasses; spans are half-open,
`[start, end)`, one-based.

| Question | Call | Result |
|---|---|---|
| Is there an answer set? Which? | `solve(program, scenario)` | `Determination[Models]` |
| What is cautious or brave? | `Grounded.consequences(mode, scenario)` | `Determination[Consequences]` |
| What is optimal, at what cost? | `Grounded.optimize(scenario)` | `Determination[Optimized]` |
| Over which solver? | `solve(program, solver=Solver.CLINGCON)`, `ground(program, solver)` | the same; a `Model` carries its `assignment` |
| Why is there none? | the `Inconsistent` result's `refutation` | `These`, `NotThese` or `NoAssumptions` |

## JSON

`{"schema": 1, "run": {"entries": [...]}, "exit_code": n}`; see `elenctic.report.encode`.

## Examples

[Every claim kind with its real output](examples.md).
