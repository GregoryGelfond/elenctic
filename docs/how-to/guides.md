# How-to guides

## Limit a search

`elenctic --budget 5 --models 1000 file.lp` stops each search after five seconds or a thousand
answer sets. A claim that needed more than was read is `undecided`, never `pass`.
`all` lifts a limit: `--budget all`, `--models all`. Without `--models` the command line reads at most
100,000 answer sets per search; a claim that needed more is `undecided`, never `pass`. Zero and negative
values are refused. In the library: `Limits(seconds=5, answer sets=1000)`; a limit left out is
`Limit.UNBOUNDED`, since a library call states its own limits.

## Check a claim under assumptions

Add `assuming { coffee, not tea }` to any claim. The claim is judged over the answer sets that
contain `coffee` and not `tea`. With none, the verdict is `fail`.

## Read the result as JSON

`elenctic --json file.lp` writes `{"schema": 1, "run": …, "exit_code": n}`. Every object carries a
`kind` naming its library type; the shape is derived from the types, so it cannot drift.

## Cancel a search

Pass an `Interrupt` to `check` or `solve` and call `pull()` from any thread. The result is
`Inconclusive` with the truncation `interrupted`.

## Use the kernel without a contract

```python
from elenctic import Limits, Literal, Program, Query, ground, solve, world_view, answer
```

`solve` yields a `Determination`; `world_view` accepts only an exhausted one; `answer` evaluates a
`Query` over it.

## Check the optimum of a program

Add `@cost { c }` for the optimum's cost and `@count optimal n`, `@model optimal { L }`,
`@cautious optimal { L }` or `@brave optimal { L }` for the optimal answer sets. A `#maximize`
level is negated in a cost. The program must optimize something, or the file is an error.
See [`optimum.lp`](../reference/examples.md).

## Check a program with integer constraints

Install `elenctic[theory]` (or use the pixi `theory` environment), write
`% @elenctic solver clingcon`, then `@assign { x=1 }` and `@model { L } where { x=1 }`. Under
clingcon an answer is a shown set with its assignment, so `@count` counts both. See
[`clingcon.lp`](../reference/examples.md).

## Ask what is true in every answer set without enumerating them

`@cautious { L }` and `@brave { L }` are computed by the solver; a contract holding only these
reads no answer set and is decided whatever `--models` says.

## Find out why a claim has no answer set

A claim `assuming { … }` that no answer set satisfies fails with a minimal set of assumptions
that clash: `no answer set satisfies the assumptions (p, q)`. In the library, the `Inconsistent`
result's `refutation` is `These(core)`; `core` is minimal unless `minimal` is false (the search was
cut short while shrinking it).

## Read the optimum from the library

```python
from elenctic import Limits, Program, ground

grounded = ground(Program("{ a; b }. #minimize { 1,a : a; 2,b : b }."))
found = grounded.optimize(limits=Limits(seconds=5))
```

`found.evidence` is an `Optimum` (proven) or an `Incumbent` (best found when the search ended
early); it never claims more than the search showed.
