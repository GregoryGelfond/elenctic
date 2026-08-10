# The contract language

**For:** anyone writing `@`-contracts in a `.lp` file. Assumes you can read ASP and have run
the first example in the [README](../README.md).

A **contract block** is a run of `%`-comment lines `% @<tag> …`. It does not have to come first: a
run of tag lines *after* the program is a contract too, and a file carrying one anywhere is a case.
A `%* … *%` block comment is a comment all the way through, so a tag written inside one is not a
contract tag and a file whose only tags are in there is a library rather than a case. Every
model-bearing tag ranges over the **observable**.

## Governing principles

**The observable.** A contract may speak only of what the program makes observable: the projection of
an answer set onto its `#show`-declared predicates, plus the theory (CSP) assignment when a theory
is in force. Hidden atoms are not checkable. A **strong-negation literal** `-a` is a *distinct* atom
from `a`, observable only if the program shows it on the same footing.

Which is to say the program is tested through the interface it declares, and clingo gives you two
`#show`s that read alike and are not:

- `#show p/1.` **declares** the predicate `p/1` observable. One such directive anywhere also
  narrows the output to what is declared — that is clingo's rule, not elenctic's.
- `#show hello : p.` **displays** a term. It puts `hello` in the output when `p` holds, but `hello`
  is not an atom of any answer set, so it is not something a contract can claim. Where the program
  declares anything at all, a claim over a displayed-but-undeclared signature is **refused**, and
  the message says to give what the directive selects a name of its own. Where a display directive
  is the program's only `#show`, nothing is declared, every atom is observable, and the claim is
  read against the answer set — so `@cautious { hello }` **fails**, because the displayed term is
  not in it.
- A program with **no `#show` at all** declares nothing and hides nothing: clingo shows every atom,
  and every tag reads the whole answer set. That is exact for the literal-wise tags, and rarely what
  you want for `@model` or `@count`, which then range over every internal atom too.

So the way to make a filtered value testable is not to display it — derive a predicate and declare
that.

**The base.** A model-base tag is evaluated over a chosen set of answer sets. Writing `optimal`
before the payload chooses the optimal class `Opt(P)`; writing nothing chooses every answer set
`AS(P)`, which is what the grammar table below means by a base of `all`. So `@cautious optimal { L
}` reads "`L` holds in every optimal model." The default has a name so that it can be talked about,
but it has no spelling: `optimal` is the only qualifier a contract may write, and `@cautious all { L
}` is a contract error.

## Grammar

| tag | meaning (over the observable; base defaults to `all`) |
|---|---|
| `@expect sat \| unsat` | the program has at least one answer set / none |
| `@model [optimal] { L }` | some (optimal) answer set's shown projection equals `L` |
| `@cautious [optimal] { L }` | each literal in `L` holds in **every** (optimal) answer set (⋂) |
| `@brave [optimal] { L }` | each literal in `L` holds in **some** (optimal) answer set (⋃) — severally, not jointly |
| `@count [optimal] n` | exactly `n` distinct (optimal) observables |
| `@cost { c }` | the proven optimal cost vector (priority-ordered) is `c` |
| `@optimal { L }` | sugar for `@model optimal { L }` |
| `@assign [optimal] { v=k, … }` | some (optimal) answer set's theory assignment includes `v=k, …` (clingcon) |
| `@model [optimal] { L } where { A }` | one (optimal) answer set has shown projection `L` **and** assignment ⊇ `A` (jointly, on the same model; clingcon) |
| `@query A { Q }` | the answer to the query `Q` is `A ∈ {yes, no, unknown}` (Gelfond Def 2.2.2) |
| `@query A { q(X̄) } = { B }` | the bindings yielding answer `A` are exactly `B` |
| `@note …` | free prose, surfaced in the diagnostic |

**Which tags may be written more than once.** `@cautious`, `@brave`, their two `optimal` siblings,
and `@query` may each appear on several lines of one contract; `@note` may too. Each writing is an
**independent claim**, with its own verdict, its own diagnostic and its own line — writing
`@cautious { a }` and `@cautious { b }` on two lines says exactly what `@cautious { a, b }` says on
one, but a failure names the line whose claim was false rather than the union.

Every other tag may appear at most once **per `(mode, base)` cell**, which is not the same as at
most once: `@model`, `@count` and `@assign` each have an `all` cell and an `optimal` cell, so
`@count 12` and `@count optimal 3` may be written together (and are then cross-checked, since an
optimal class cannot be larger than the whole). `@optimal { L }` is sugar for `@model optimal { L }`
and shares its cell. Only `@expect` and `@cost` are one to a contract outright.

A litset `{ … }` is comma-separated and paren-aware (an atom may contain commas, e.g.
`included(s,a,2,1)`), and may span continuation `%` lines while a brace stays open. The run of
comment lines is what carries it, so program text ends it: a litset left open when the comments stop
is refused rather than continued past the rule in between. An `@`-tag's payload runs to the end of
its line, so write explanatory comments on their own lines (a `%%` or `%` line), not after the
payload — `% @count 2  % two answer sets` reads the comment as part of the count and refuses the
line, loudly, rather than miscounting. (Inline-comment support after a payload is a planned
convenience.)

A `where { … }` clause is the one piece of contract syntax that is not `@`-initial, so it is read by
position: it rides its witness's litset-closing line, or a continuation line while that litset's
brace is still open. Written on a line of its own it is a *dangling* `where` and is refused — which
means a `%` comment may not **open** with `where {`, even as prose. That is a real cost of reading
it by position, and it is taken deliberately: a `where` clause silently dropped is a contract
weakened without a word, which is the outcome worth more than the odd reworded comment.

## The three-valued query

`@query` is Gelfond's epistemic query, faithfully: it asks *what answer the program gives*, and the
answer is three-valued. **yes** if the (conjunctive) query is true in every answer set; **no** if it
is false in every answer set (some conjunct's *contrary* present in each — a "no" needs the contrary
shown, never mere failure-to-derive); **unknown** otherwise — the entertained-but-unsettled middle
that classical logic cannot name. (See the worked examples below.)

## Well-formedness

`parse` accepts exactly the well-formed blocks and **rejects every other with a diagnostic** — it
never silently defaults. Exactly one `@expect`; **`@expect unsat` admits no model-bearing tag at
all** — no `@model`, `@count` (beyond `@count 0` and `@count optimal 0`, both of which are checked
and reported), `@cautious`, `@brave`, `@optimal`, `@cost`, `@assign` or `@query`, because a program
with no answer sets has nothing for any of them to be
about, which is what makes a contract one shape or the other rather than a bag of tags;
single-valued witness/scalar tags per `(mode, base)` cell; `@count 0 ⟺ @expect unsat`; and the
precondition tags are checked at discovery **against the actual encoding**, not at parse time.

Those discovery-time preconditions are the ones most likely to surprise, so in full. `@cost` and the
`optimal` base need an optimizing encoding (a `#minimize`, `#maximize` or `:~`). `@assign`, `@assign
optimal` and a `where`-witness need clingcon. **A `@query` needs every signature it reads declared
observable.** elenctic does not check the answer you wrote; it *computes* the query's three-valued
answer from what the solver puts in the output and then compares. A literal that never reaches the
output cannot be told apart from one no answer set contains, so the computation would describe the
`#show` directives rather than the program. What each form reads differs, because what each form
computes differs:

- A **ground** `@query` — `{ fly(sam) }`, or a conjunction — reads every conjunct **and every
  conjunct's contrary**, whichever answer it claims. Its answer is three-valued, and `no` is
  distinguishable from `unknown` only by seeing the contrary. So a `yes` query missing the contrary
  is refused for exactly the reason a `no` one is: unshown, a true `no` would compute as `unknown`.
- A **binding** `@query` — `{ q(X̄) } = { B }` — collects the tuples whose answer is the stated one,
  which is a one-sided reading, so it needs only the goal it collects: `q` for `yes`, `-q` for `no`,
  and both for `unknown`. Requiring the other sign would refuse contracts elenctic answers exactly.

A program with a theory atom needs a
theory solver declared, since plain clingo grounds theory atoms and silently ignores the constraints
— a wrong PASS. And two more that the grammar above gives no hint of:

- **`@cost` is refused over a `#maximize` objective.** clingo reports such a cost in negated form,
  and elenctic will not present a number that is not the one you wrote. Use `#minimize`, or an
  optimal-base tag.
- **Every tag that reads AS(P) is refused over a *theory-native* objective** (`&minimize`,
  `&maximize`) — that is `@model`, `@count`, `@assign`, `@cautious`, `@brave` and `@query`. The
  theory's propagator drives the search to the optimum and no clingo setting switches that off, so
  an enumeration would silently cover only part of AS(P). Move the objective into ASP, which the
  AS(P) modes *do* switch off, or drop to `@expect sat` or an optimal-base tag.

Each is a hard exit `2` with a diagnostic naming the file — never a `FAIL`, because none of them is
the program being wrong.


## Worked examples

UNSAT, with a documenting note:

```asp
% @expect unsat
% @note   the budget cap excludes every s–t path
```

Optimization — the proven optimal cost, and one optimal model (a shortest path under an edge
budget):

```asp
% @expect  sat
% @cost    { 4 2 }
% @optimal { included(s,a,2,1), included(a,t,2,1), start(s), end(t) }
% @note    the budget rules out the direct edge; the two-hop detour is optimal
```

A unique, counted, CSP-only solution (the answer lives entirely in the theory assignment):

```asp
% @expect sat
% @count  1
% @assign { digit(s)=9, digit(e)=5, digit(n)=6, digit(d)=7,
%           digit(m)=1, digit(o)=0, digit(r)=8, digit(y)=2 }
```

The three-valued query, on Gelfond & Kahl's *cowardly students* (§5.1.2; an encoding that shows the
relevant strong-negation literals, so a "no" means *known* false, not merely underived):

```asp
% @expect    sat
% @query yes     { afraid(john,math) }
% @query no      { afraid(mary,math) }
% @query unknown { afraid(bob,math) }
```

John (English) is afraid of math by default; Mary is a stated strong exception (known *not* afraid);
Bob, in CS, is genuinely undetermined — the **unknown** that the consequence vocabulary cannot name.

