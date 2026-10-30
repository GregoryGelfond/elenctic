# Reference

## Command line

`elenctic [test] PATH…` checks programs against the contracts in their comments. `PATH` is an
`.lp` file or a directory searched for them. With no command the arguments are paths; a path named
like a command is written `./why`.

| Option | Meaning |
|---|---|
| `--json` | write the run as JSON |
| `-v`, `--verbose` | list the claims that passed |
| `--budget SECONDS` | time allowed per search; `0` is none (default 30) |
| `--models N` | most answer sets read per search |

`repl`, `why`, `ask` and `explain` are reserved: each writes a note on stderr and exits 2.

## Exit codes

0 every claim passed; 1 some claim failed or was undecided; 2 some file could not be checked.

## Contract syntax

A claim is a comment line beginning `%` followed by a tag. A brace group may continue over
following comment lines. Every contract begins with `@expect`.

| Claim | Holds when |
|---|---|
| `@expect sat` / `@expect unsat` | the program has / has no answer set |
| `@count n` | exactly `n` distinct shown answer sets |
| `@model { L }` | some answer set shows exactly `L` |
| `@cautious { L }` | `L` is in every answer set (⋂ AS(P)); computed by the solver |
| `@brave { L }` | `L` is in some answer set (∪ AS(P)); computed by the solver |
| `@query A { L, … }` | the three-valued answer to the query is `A` (`yes`, `no`, `unknown`) |
| `@query A { p(X, b) } = { 1, 2 }` | the bindings of `X` with answer `A` are exactly these |
| `@model optimal { L }`, `@cautious optimal { L }`, `@brave optimal { L }` | the same, over the optimal answer sets Opt(P); `@optimal { L }` is `@model optimal { L }` |
| `@count optimal n` | exactly `n` distinct shown optimal answer sets |
| `@cost { c1 c2 … }` | the optimum's cost, highest priority first, is exactly this (see below) |
| any of the above `assuming { l, not l }` | the claim is judged under those assumptions |

`@note` is ignored. `@assign` and `@elenctic` are reported as not supported yet.

### Costs

A cost is the minimized sum per priority level, as clingo reports it. A `#maximize` level is
negated: `@cost { -5 }` claims that the optimum of a `#maximize` is 5.

### Preconditions

A contract that would be misread is not judged; the file is reported as an error (exit 2):

- the program has theory atoms (clingo would ground them and ignore their constraints);
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
| Why is there none? | the `Inconsistent` result's `refutation` | `These`, `NotThese` or `NoAssumptions` |

## JSON

`{"schema": 1, "run": {"entries": [...]}, "exit_code": n}`; see `elenctic.report.encode`.

## Examples

[Every claim kind with its real output](examples.md).
