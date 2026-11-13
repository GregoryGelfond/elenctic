# How-to guides

## Limit a search

`elenctic --max-seconds 5 --max-answer-sets 1000 file.lp` stops each search after five seconds or a thousand
answer sets. A claim that needed more than was read is `undecided`, never `pass`.
`all` lifts a limit: `--max-seconds all`, `--max-answer-sets all`. Without `--max-answer-sets` the command line reads at most
100,000 answer sets per search; a claim that needed more is `undecided`, never `pass`. Zero and negative
values are refused. In the library: `Limits(max_seconds=5, max_answer_sets=1000)`; a limit left out is
`Limit.UNBOUNDED`, since a library call states its own limits.

## Check a claim under assumptions

Add `assuming { coffee, not tea }` to any claim. The claim is judged over the answer sets that
contain `coffee` and not `tea`. With none, the verdict is `fail`.

## Read the result as JSON

`elenctic --json file.lp` writes `{"schema": 1, "run": …, "exit_code": n}`. Every object carries a
`kind` naming its library type in snake case (`report`, `entails`, `fault`); the shape is derived from the types, so it cannot drift. The published schema is `docs/reference/output-v1.schema.json`.

## Cancel a search

Pass an `Interrupt` to `check` or `solve` and call `pull()` from any thread. `solve` returns
`Inconclusive` with the truncation `interrupted`; `check` returns a `Report` whose findings are
`undecided` for the same reason.

## Use the kernel without a contract

```python
from elenctic import Limits, Literal, Program, Query, ground, solve, world_view, answer
```

`solve` yields a `Determination`; `world_view` turns an exhausted one into a `WorldView` and a
truncated one into that `Truncation`; `answer` evaluates a `Query` over a world view.

## Check the optimum of a program

Add `@cost { c }` for the optimum's cost and `@count optimal n`, `@answer-set optimal { L }`,
`@cautious optimal { L }` or `@brave optimal { L }` for the optimal answer sets. A `#maximize`
level is negated in a cost. The program must optimize something, or the file is an error. Claims
without `optimal`, and queries, still read every answer set; an objective only ranks them (see
[Semantics](../explanation/semantics.md)).
See [`optimum.lp`](../reference/examples.md).

## Check a program with integer constraints

Install `elenctic[theory]` (or install clingcon in the same environment), write
`% @elenctic solver clingcon`, then `@assign { x=1 }` and `@answer-set { L } where { x=1 }`. Under
clingcon an answer is a shown set with its assignment, so `@count` counts both. See
[`clingcon.lp`](../reference/examples.md).

## Ask what is true in every answer set without enumerating them

`@cautious { L }` and `@brave { L }` are computed by the solver; a contract holding only these
reads no answer set and is decided whatever `--max-answer-sets` says.

## Find out why a claim has no answer set

A claim `assuming { … }` that no answer set satisfies fails with a minimal set of assumptions
that clash: `no answer set satisfies the assumptions (p, q)`. In the library, the `Inconsistent`
result's `refutation` is `These(core)`; `core` is minimal unless `minimal` is false (the search was
truncated while shrinking it).

## See why a claim fails

`elenctic explain PATH` checks as `test` does and, for each failed claim, shows the answer set it
fails in and the tree of rule instances behind it, each with its variables filled in:

```
  not access(ann,db)                no rule fires (1 candidate)
  └── access(ann,db) :- role(ann,admin), permits(admin,db), not suspended(ann).  line 6: blocked by not suspended(ann)
      └── suspended(ann) :- flagged(ann), not cleared(ann).  line 5
          └── flagged(ann)          fact, line 4
```

`--spans` adds each rule as written beneath its instance, with its place and substitution;
`--max-depth N` lets an absence go deeper than 3; `--json` adds the same evidence to the run `test`
writes. In the library, `evidenced(report, program)` gives each failed finding its `evidence`,
and `session(program).explain(literals, counterexample)` explains any literals in an answer set the
session found. [Every example](../reference/examples.md) from `absent.lp` to `team.lp` shows one
kind of evidence.

## Read the optimum from the library

```python
from elenctic import Limits, Program, ground

grounded = ground(Program("{ a; b }. #minimize { 1,a : a; 2,b : b }."))
found = grounded.optimize(limits=Limits(max_seconds=5))
```

`found.evidence` is an `Optimum` (proven) or an `Incumbent` (best found when the search ended
early); it never claims more than the search showed.
