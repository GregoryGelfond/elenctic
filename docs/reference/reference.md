# Reference

## Contract syntax

A claim is a comment line beginning `%` followed by a tag. A brace group may continue over
following comment lines.

| Claim | Holds when |
|---|---|
| `@expect sat` / `@expect unsat` | the program has / has no answer set |
| `@count n` | exactly `n` distinct shown answer sets |
| `@model { L }` | some answer set shows every literal of `L` |
| `@cautious { L }` | `L` is in every answer set (⋂) |
| `@brave { L }` | `L` is in some answer set (∪) |
| `@query A { L, … }` | the three-valued answer to the query is `A` (`yes`, `no`, `unknown`) |
| `@query A { q(X) } = { B }` | the bindings of `q(X)` with answer `A` are exactly `B` |
| any of the above `assuming { l, not l }` | the claim is judged under those assumptions |

`@note` is ignored. `@optimal`, `@cost`, `@assign` and `@elenctic` are reported as not supported yet.

## Verdicts

`pass`, `fail`, `undecided`. A report's verdict is the worst, with `fail` over `undecided`.

## Exit codes

0 every claim passed; 1 some claim did not; 2 some file could not be checked.

## API

Everything in `elenctic.__all__`. Results are frozen dataclasses; spans are half-open,
`[start, end)`, one-based.

## JSON

`{"schema": 1, "run": {"entries": [...]}, "exit_code": n}`; see `elenctic.report.encode`.
