# Semantics

**Answers are three-valued per answer set.** Over a set of answer sets, a ground query
(singleton, conjunctive or disjunctive) is `yes` if true in every one, `no` if false in every
one, and `unknown` otherwise. A literal absent from an answer set is unknown there unless its
contrary is present (Gelfond and Kahl, Definition 2.2.2, with the errata that this rule holds for
every ground query).

**Queries range over the full answer sets.** `@query` reads every atom of each answer set, not
only those `#show` selects. `#show` still governs what `@answer-set`, `@count`, `@cautious` and
`@brave` report, and those claims (when they need no full answer set) enumerate under projection onto `#show`. When a query reads a literal (or its contrary) the program can derive and does not `#show`,
the run records a note (a lint) on that claim; the note does not change the verdict or the exit. A
later `--strict` may promote such notes to faults; that flag is not built yet.

**A query with variables has bindings, found by unification.** The cautious consequences
(⋂ AS(P), over the full answer sets) are the facts a pattern is unified with: an instance `p(t)` is
`yes` exactly when it is one of them and `no` exactly when its contrary `-p(t)` is, by the rule
above, so the yes and no bindings are the pattern's most general unifiers with those facts and with
the contrary's. A ground literal is answered the same way. The `unknown` bindings are the instances
some answer set entertains (they or their contrary are in ∪ AS(P), the brave consequences) that are
neither; the brave consequences are read for this alone, since infinitely many instances are in no
answer set and are not listed. A conjunction or disjunction can be `no` or `yes` for a different part
in each answer set, which no consequence records, so each of its instances is answered over the
answer sets themselves. An anonymous variable, `_`, names no binding and is refused. A binding claim
`@query A { p(X) } = { … }` holds when the bindings with answer `A` equal the stated set; no other
relation (subset, superset) is offered.

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

**Claims sharing assumptions share a search.** A contract of only `@expect` claims stops once
satisfiability is decided (one answer set, or none).

**An objective ranks answer sets; it never removes any.** AS(P) is every answer set of the program,
whatever it says in `#minimize`, `#maximize` or `:~`. Opt(P) is the subset of AS(P) that no other
answer set beats, so Opt(P) ⊆ AS(P). The unqualified claims (`@answer-set`, `@count`, `@assign`,
`@cautious`, `@brave`) and unqualified `@query` read AS(P), with or without an objective in the
program. Only the claims that say `optimal` (including `@query optimal`), and `@cost`, read Opt(P).
A `#maximize` level is negated in `@cost` (clingo's minimized sums); see the reference.
A consequence carries which set it ranges over, so `⋂ Opt(P)` is never read as `⋂ AS(P)`.

**An optimum is proven or it is an incumbent.** A truncated search can have found a good answer set but
not shown it is best. `@cost` and the `optimal` claims are `undecided` then, never `pass`.

**Consequences are atoms.** `@cautious` and `@brave` range over shown atoms; under clingcon an
assignment is never reported as a consequence.

**Programs are not isolated.** An untrusted program can exhaust memory; elenctic limits time and
answer sets, not memory. Non-ASCII outside strings and comments is refused with a diagnostic
before clingo sees it, so a bad character never aborts the process.

**A contract that would be misread is an error, not a verdict.** See the preconditions in the
reference.

**Evidence is a counterexample, explained.** `explain` re-runs a failed claim's search in a session
of its own and picks the answer set it fails in: for `@cautious`, the first without a literal; for
`@brave`, the first, and the literals the solver's brave consequences lack; for `@query yes`, the
first where the query is false, else the first where it is unknown, and the reverse for `@query no`.
Its roots are the literals that make it fail there: those absent, or the contrary that holds. A
failed `@expect sat` has its refutation as evidence, and a failed `@expect unsat` its first answer
set, with nothing to explain. For `@cautious`, `@brave` and `@expect unsat` the search stops at that
answer set, so its name gives no count: `answer set 1`, not `answer set 1 of 7`. Claims about counts, witnesses, assignments, costs and bindings have no evidence yet, and
neither has an undecided claim. `test` computes none, so it is as fast as it was.

**`why` explains an answer set it is asked for; `ask` answers as `@query` does.** `why` picks the
K-th answer set the search reads, of AS(P) or of Opt(P), and explains its atom by the two rules
below: present, or absent by default negation, whether or not its contrary holds. Which answer set
is K-th depends on enumeration order, as nothing else here does. `ask` keeps the three values: an
atom in no answer set and whose contrary is in none is `unknown`, never `no`. Beside the answer it
names, for each value the query takes in one answer set alone, the first answer set taking it;
that answer set too depends on order, the answer does not.

**Presence is well-founded support; it is sound, not minimal.** An atom that holds gets one ground
rule instance whose body holds, each of whose positive atoms got its own before it, so the support
has no cycle. Negative literals and comparisons are listed as the instance's conditions, not
explained. Another support may be smaller; none is sought. `max_depth` bounds absences only;
a support is shown in full.

**Absence is complete over the candidates.** The candidates for an atom are the ground instances of
a positive relaxation of the program, which drops negative literals, theory atoms and constraints
and grounds what is left; every instance whose body could hold in some answer set is one, and an
atom with none has no rule instance that can derive it. Each candidate is shown with the first
literal of its body, in the order written, that fails, or as a choice not made. An absence can lead
back to itself, which is an unfounded loop; each node appears once and is pointed back to. The
explanation goes as many absences deep as `max_depth` allows and is `complete` only if no branch
stopped there.

**An outranked result is three solver calls.** For an optimal claim whose literals some answer set
holds, the evidence compares the optimum with the best answer set under the literals, priority by
priority, and names the weak-constraint instances each pays and the other does not. When no answer
set holds the literals, or the best that does is optimal too, the evidence is the absence of the
literals from the optimum.

**Every view renders one representation.** The text and JSON views, and any later one, show the
same model, and each mark, style, word and order comes from one legend; a view decides only where
things go. So both list an answer set in one order, and a finding and its evidence word a refutation
alike. A difference between two views is a fault in a view, not in what was found.

**The session does not change what it explains.** It adds rules that record the weak-constraint
instances each answer set pays and the truth of each theory atom of a body, under names the program
does not use; they derive no atom of the program and add no answer set.
