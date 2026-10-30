# How-to guides

## Limit a search

`aspnext --budget 5 --models 1000 file.lp` stops each search after five seconds or a thousand
answer sets. A claim that needed more than was read is `undecided`, never `pass`.
In the library: `Limits(seconds=5, models=1000)`.

## Check a claim under assumptions

Add `assuming { coffee, not tea }` to any claim. The claim is judged over the answer sets that
contain `coffee` and not `tea`. With none, the verdict is `fail`.

## Read the result as JSON

`aspnext --json file.lp` writes `{"schema": 1, "run": …, "exit_code": n}`. Every object carries a
`kind` naming its library type; the shape is derived from the types, so it cannot drift.

## Cancel a search

Pass an `Interrupt` to `check` or `solve` and call `pull()` from any thread. The result is
`Inconclusive` with the truncation `interrupted`.

## Use the kernel without a contract

```python
from aspnext import Limits, Literal, Program, Query, ground, solve, world_view, answer
```

`solve` yields a `Determination`; `world_view` accepts only an exhausted one; `answer` evaluates a
`Query` over it.
