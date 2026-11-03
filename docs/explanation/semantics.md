# Semantics

**Answers are three-valued per answer set.** Over a set of answer sets, a query is `yes` if true in
every one, `no` if false in every one, and `unknown` otherwise. A literal absent from an answer
set is unknown there unless its contrary is present (Gelfond and Kahl, Definition 2.2.2).

**A search ends in one of three ways.** The answer sets were exhausted, the search was truncated
(by `max-answer-sets`, `max-seconds` or interrupt), or the program has none. Only an exhausted search yields a world
view, and only a world view answers `@query`; a truncated search leaves such claims `undecided`.

**Existential claims** (`@answer-set`, `@brave`) pass when a witness is seen and fail only when the
search was exhausted without one. **Universal claims** (`@cautious`) fail when a counter-example is
seen and pass only when exhausted. `@count n` fails once more than `n` distinct shown sets are
seen.

**A verdict does not depend on enumeration order.** A decided verdict is a function of the set of
answer sets, and counts are of distinct shown sets. Order can change only whether a truncated search
decides.

**Claims sharing assumptions share a search.** A contract of only `@expect` claims reads one
answer set.

**An objective ranks answer sets; it never removes any.** AS(P) is every answer set of the program,
whatever it says in `#minimize`, `#maximize` or `:~`. Opt(P) is the subset of AS(P) that no other
answer set beats, so Opt(P) ⊆ AS(P). The unqualified claims (`@answer-set`, `@count`, `@assign`,
`@cautious`, `@brave`) and every `@query` read AS(P), with or without an objective in the program.
Only the claims that say `optimal`, and `@cost`, read Opt(P). A consequence carries which set it
ranges over, so `⋂ Opt(P)` is never read as `⋂ AS(P)`.

**An optimum is proven or it is an incumbent.** A search cut short can have found a good answer set but
not shown it is best. `@cost` and the `optimal` claims are `undecided` then, never `pass`.

**Consequences are atoms.** `@cautious` and `@brave` range over shown atoms; under clingcon an
assignment is never reported as a consequence.

**Programs are not isolated.** An untrusted program can crash or exhaust the process; elenctic
limits time and answer sets, not memory.

**A contract that would be misread is an error, not a verdict.** See the preconditions in the
reference.
