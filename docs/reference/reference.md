# Reference

## Command line

`elenctic [test] PATH…` checks programs against the contracts in their comments. `python -m elenctic` is the same command line as the `elenctic` console script. `PATH` is an
`.lp` file or a directory searched for them. With no command the arguments are paths; a path named
like a command is written `./why`.

| Option | Meaning |
|---|---|
| `--format text\|json\|tui` | how to write the run: text (default), JSON, or the [interactive view](#the-interactive-view) |
| `--short` | write each diagnostic on one line, in the gcc form ([diagnostics](#diagnostics)); text only |
| `--json` | write the run as JSON (same as `--format json`) |
| `-V`, `--version` | print the version and exit; stands before the command (below) |
| `-v`, `--verbose` | list the claims that passed |
| `--color WHEN` | color the text: `auto` (default), `always` or `never` |
| `--icons[=WHEN]` | mark claims with Nerd Font glyphs: `auto`, `always` or `never`; given bare it is `auto`, left out it is `never`. A value takes an equals sign: `--icons always` names a path |
| `--max-seconds SECONDS\|all` | time allowed per search, in seconds (a positive number), or `all` for no limit (default: 30) |
| `--max-answer-sets N\|all` | most answer sets read per search (a positive integer), or `all` for no limit (default: 100,000) |
| `--root DIR` | the root: the directory every path and every `#include` must lie under (default: each directory searched, or a named file's own directory) |

`--format full` and `--format short`, the spellings of 1.0, still work: they are `--format text`
and `--format text --short`, with a warning on stderr naming the new spelling. 2.0 removes them.

Zero and negative values of `--max-seconds` and `--max-answer-sets` are a usage error (`FAULT`, 2). In the library the same
choice is `Limits(max_seconds=…, max_answer_sets=…)`, each a number or `Limit.UNBOUNDED`, which is the default of the library; only the command line has default limits.

Every file a case reaches by `#include` must lie under its root once symbolic links and `..` are
resolved; the root is `--root DIR`, else the directory searched, else a named file's own directory.
An `#include "…"` is found as clingo finds it: as written, from the working directory, then beside
the including file, then under each directory of `CLINGOPATH`. Write it relative to the including
file and keep the working directory free of a file by the same name.
A case that includes a file outside it is refused (`FAULT`, 2) before it runs, naming the path and
never its contents. With `--root`, a path not under DIR is refused the same way and the other paths
still run; a `--root` that is not a directory is a usage error. In the library the root is
`check(program, root=…)`, by default the program's own directory.

`elenctic version`, `elenctic --version` and `elenctic -V` print the same two lines on stdout and
exit `REPORTED` (0); `version` is a command, so a file of that name is written `./version`.
`--version` and `-V` are options of `elenctic` itself, as in `git --version`: they stand before the
command (or alone) and win over the rest of the line, so `elenctic --version test x.lp` prints the
version; a command does not take them, so `elenctic test --version` is a usage error (`FAULT`, 2).
`--color` and `--icons` may stand before the command too, as in `elenctic --icons --version`; a
command's own `--color` or `--icons` overrides them. The
first line is `elenctic VERSION | © 2026 Gregory Gelfond | MIT`: the version and license are those of
the installed package, the holder is its author. The second is the versions of clingo and clingcon as
loaded, such as `clingo 5.8.2 | clingcon 5.2.1`, or `clingcon not installed`. With `--icons` the
copyright sign is the Nerd Font glyph `fa-copyright`; the text takes no color.

`elenctic explain PATH…` is `test`, with the evidence for each failed claim after its source's
verdicts. It takes the options of `test` and two of its own; its exit codes are those of `test`.
On a terminal with the `tui` extra installed it opens the [interactive view](#the-interactive-view)
unless `--format` says otherwise.

| Option | Meaning |
|---|---|
| `--max-depth N\|all` | how many absent atoms deep an explanation goes (a positive integer), or `all` for no limit (default: 3) |
| `--spans` | beneath each rule instance, the rule as written, its place, and its substitution |

`elenctic why PATH ATOM` explains why the ground literal `ATOM` holds, or not, in one answer set of
the program at `PATH`; a leading `not` is dropped, since the answer set says which. `elenctic ask
PATH QUERY` answers a query, written as `@query` writes it (`{ a, -b }`, or one pattern `{ p(X) }`;
braces optional), over every answer set. Each takes `--format`, `--short`, `--json`,
`--max-seconds` and `--max-answer-sets` as `test` does, and opens the interactive view as `explain`
does; and these:

| Option | Meaning |
|---|---|
| `--over all\|optimal` | all the answer sets (default), or only the optimal ones |
| `--answer-set K` | `why`: the answer set explained, counted from 1 among those `--over` reads (default: 1) |
| `--assuming L,…` | `why`: literals assumed, `p` or `not p`, as `assuming { … }` writes them |
| `--max-depth N\|all`, `--spans` | `why`: as for `explain` |

`repl` is reserved: it writes a note on stderr and exits `FAULT` (2). `--color` and `--icons`
apply to every command.

## Output

Verdicts, the summary and the blocks `why` and `ask` write go to stdout; diagnostics for sources
that could not be checked, the reserved-command note and the internal-error line go to stderr. With
`--json` the whole document is on stdout and is never colored or marked with glyphs.

Color and glyphs are decided for each stream on its own, so `elenctic … > run.txt` leaves stderr
colored on a terminal. Color, `auto`, is decided in this order; the first rule that applies wins.

| Order | Rule | Color |
|---|---|---|
| 1 | `--color always` or `--color never` | on or off |
| 2 | `NO_COLOR` is set and not empty | off |
| 3 | `TERM` is `dumb` | off |
| 4 | the stream is a terminal | on, else off |

A redirected stream (a pipe or a file) stays plain in `auto` whatever the environment says;
`--color always` is the one way to color it. `CLICOLOR_FORCE`, `CLICOLOR` and `FORCE_COLOR` are
not read. This decision covers elenctic's own report and diagnostics. The help and usage messages
are written by Python's `argparse`, which colors them by its own defaults, including
`FORCE_COLOR`, `PYTHON_COLORS` and `NO_COLOR`; `--color` does not reach them.

Glyphs ignore the environment. `--icons=always` marks claims with a glyph in place of `[PASS]`,
`[FAIL]` and `[UNDECIDED]`; `auto` does so on a terminal; `never` and no option leave the text.
Glyphs and color are independent. The glyphs are from a Nerd Font: a terminal without one shows
boxes, which is why they are off unless asked for. Program text is made legible before it is
colored or marked, so a program cannot write escape sequences.

Colors by role: error `1;31` (a `FAIL`, an error, an internal error), warning `1;33` (`UNDECIDED`),
note `1;32` (`PASS`, the `why:` and `ask:` headings), help `1;36` (the reserved-command note, `=
help:`), margin `1;34` (line numbers) and emphasis `1` (sources and the summary). Evidence adds
aside `3`, italic (substitutions, guards, counts) and reference `2`, dim (a rule's line).

### Evidence

`explain` writes a block for each failed claim: `evidence:` and the claim, its place, the
counterexample (`answer set K`, and `of N` when the search read all N, as a claim over the optimal
answer sets or a `@query` does), then a tree with one line for each atom. A line that a rule instance accounts for shows the instance, its
variables replaced by their values, and the rule's line:

| Line | Says |
|---|---|
| `p(a) :- q(a), not r(a).  line 5` | `p(a)` holds by this instance |
| `q(a)  fact, line 2` | a fact |
| `2 <= { t(a): c(a); … } <= 3.  chosen, line 4 (2 of 2..3 chosen)` | a choice made |
| `not p(a)  no rule fires (N candidates)` | absent; one line below for each instance that could derive it |
| `p(a) :- q(a).  line 5: blocked by q(a)` | this instance does not fire: its first literal that fails |
| `… line 4: not chosen (2 of 2..3 chosen)` | the choice could have made it and did not |
| `not N = #count { … }  aggregate, line 6: is 1, needs = 2` | an aggregate, its value and its guard |
| `&sum { s } >= 7  the theory holds under { s=7 }` | a theory atom, and the assignment of its variables |
| `not p  no rule instance can derive it` | no instance's body can ever hold |
| `^ p(a)  shown above [1/p(a)]` | a node drawn once already, by its handle |
| `... not p  not expanded (depth 3)` | the tree stops at `--max-depth` |
| `p  not explained: …` | a rule with a construct no reason covers yet (`#min`, `#max`, a conditional literal, a head aggregate) |

A step with more than one child branches with `├──` and `└──`. The only child of a step that is not
a root sits at that step's indent with no branch, so a chain of single reasons keeps one indent
however long it is.

`why` writes the same block under `why:` and the atom as it was asked, `not` kept (`why: not
access(ann,db)`), naming the program's path; its answer set is
`answer set K`, the search stopping there, or `optimal answer set K of N` under `--over optimal`, and
`counterexample:` stays for failed claims. `ask` writes `ask:` and the query, then `= answer: yes|no|unknown` and, for
each answer the query takes in one answer set alone, the first answer set that gives it: `true in
answer set 3: { … }`, `false in …`, or `neither p nor -p in …` (`neither true nor false` for a
conjunction). A one-literal query asks apart which answers some answer set gives, and the search
stops at the first answer set to give the last of them. If a limit stops it first, the query is
still answered, and an answer it did not reach is `true in an answer set past the 100000 read:
search ended: …`. A conjunction, a disjunction, or a query `--over optimal` reads every answer set,
and names them `answer set 3 of 7`. A one-literal query ends with a `= help:` line giving the `why` command for that
answer set. A pattern with variables writes `= yes bindings: { … }`, and the `no` and `unknown`
bindings when there are any. With no answer set, each shows the refutation; a search cut short shows
what ended it.

An outranked result first shows the costs with and without the claim's literals, by priority, and
the weak-constraint instances paid differently, each at its place in the source. A refuted `@expect
sat` shows its refutation. A search cut short shows what ended it. The block ends with
`= note: support is sound, not minimal`. With `--icons` each line starts with a Nerd Font 3.5.1
glyph: `fa-database` (fact), `cod-symbol_method` (derived), `fa-random` (chosen, not chosen),
`fa-ban` (absent, blocked), `md-sigma` (aggregate), `fa-calculator` (theory atom),
`cod-references` (shown above, `^` without icons), `fa-ellipsis_h` (not expanded, `...`),
`fa-balance_scale` (outranked) and `fa-eye` (the counterexample, or an answer set `why` or `ask`
names).

### The interactive view

`--format tui` shows what `explain`, `why`, `ask` or `test` found as a tree to read with the keys.
It needs the `tui` extra (`pip install 'elenctic[tui]'`, Textual 8) and a terminal on stdin and
stdout; without either, `--format tui` is refused (`FAULT`, 2). With no `--format`, `explain`, `why`
and `ask` open it when the extra is installed and stdin and stdout are terminals, `TERM` not `dumb`;
otherwise they write text. `test` writes text unless asked. There is no environment variable for
the choice: `--format text` is it.

Each row is the text view's line, its guides aside: the same words, order, glyphs (with `--icons`),
roles and handles, painted by the same roles; `NO_COLOR` and `--color never` leave it plain. A
shared node is drawn once, and a chain of single reasons keeps one indent. A source's diagnostics
open into the block the text view writes. `explain` and `why` start at `--max-depth` (3), as the text
does; `+` asks the library for one step more, and the cursor stays on the step it deepened, as it
stays on its row while evidence comes in or `f` and `e` change the rows around it. `test` lists
every claim, as `--verbose` does, and finds a failed claim's evidence when it is opened; `explain`
opens with each failed claim open and finds its evidence then. The pane shows the rule the selected step cites, as `--spans` writes it
with its line quoted; on a row that cites none, such as a source or a claim, it shows the first rule
cited below it, titled `first step beneath`; on a row of how the objective ranks a claim, such as
its costs, it quotes the weak constraints paid differently, as the text quotes them. Below 100
columns the pane is hidden, and it never narrows a source's heading. A title too long for the title
bar is cut short with `…`, or left out where even that does not fit, and the tally beside it kept
whole. The command exits with its own code when the view is closed, and the diagnostics of a run go
to stderr then.

The view opens once the run is checked, and asks the library for anything more (evidence, `+`,
`why` from `ask`) off its own thread, one call at a time: the keys answer meanwhile, the row waiting
reads `searching` and the title `searching · esc cancels`. Esc stops the search and nothing it
found is shown; Ctrl-C quits, stopping it first. Each call has `--max-seconds` and
`--max-answer-sets`, as in the text. The window is titled by the command and what it was asked of,
and the view's own parts take the colours of the text view's roles: the pane's border the margin's,
a key the help's. The selected row is shown reversed, as a terminal shows a selection, so each of
its pieces keeps its role's colour and reads as well as it does unselected; the scrollbars are the
terminal's grey.

| Key | Action |
|---|---|
| ↑ ↓, `k` `j` | move |
| → `l`, ← `h` | open, close; ← on a closed row goes to its parent |
| ⏎ | a shared row: go to its first row; an answer set `ask` names: `why` on it; else open or close |
| `s` | show or hide the pane: the rule the selected row cites, or the first cited below it |
| `+` | explain the selected step's block one step deeper |
| `/`, `n` | find a literal, the next match |
| `f` | `test`, `explain`: only the sources that did not pass |
| `e` | `test`, `explain`: open every failed claim's evidence, finding it if need be |
| `?` | the keys that apply to the view, in these words |
| `q`, Ctrl-C; Esc | quit; Esc first closes the find box, else stops a search, else closes a `why` opened from `ask` |

`f` and `e` apply to `test` and `explain`, `s` and `+` to all but `ask`; neither the footer nor `?`
lists a key that does not apply.

The mouse selects and opens rows, and nothing else.

## Diagnostics

A diagnostic names what is wrong. Its message is lowercase and has no trailing period. How to fix
it stands only on a `help` line; context stands on a `note`. The default is the
rustc form: `error: message`, then ` --> path:line:col`, a source snippet with carets and a primary
label, then `= note:` and `= help:` lines. `--short` prints one line per diagnostic in the
gcc form `path:line:col-col: error: message`. Columns count Unicode scalars; clingo's byte columns
are converted at the boundary. Syntax errors read `expected X, found Y`. Non-ASCII outside strings and comments is refused before clingo sees it (program text, `#include`d files, and tag payloads), so a bad character never aborts the process.

## Exit codes

Each command returns an outcome of its own, an `IntEnum` that states its process code once; the
values are fixed. `elenctic test`, `elenctic explain` (and the refusal of a reserved command) return
`elenctic.report.Exit`:

| Name | Value | Meaning |
|---|---|---|
| `CLAIMS_HOLD` | 0 | every claim passed |
| `CLAIM_UNMET` | 1 | some claim failed or was undecided |
| `FAULT` | 2 | some source could not be checked, or the command was refused |
| `INTERNAL_ERROR` | 3 | elenctic itself failed; one line on stderr, no traceback |

`elenctic version` returns `elenctic.about.VersionExit`, a different type that shares codes with
`Exit` and not members:

| Name | Value | Meaning |
|---|---|---|
| `REPORTED` | 0 | the text was written |
| `INTERNAL_ERROR` | 3 | the metadata or the solvers could not be read; one line on stderr |

`elenctic why` returns `elenctic.inquiry.WhyExit` and `elenctic ask` returns
`elenctic.inquiry.AskExit`; `ask` exits 0 whatever the answer is:

| Name | Value | Meaning |
|---|---|---|
| `EXPLAINED` / `ANSWERED` | 0 | the atom was explained / the query was answered |
| `ENDED` | 1 | the search ended before it reached the answer set, or read them all |
| `FAULT` | 2 | the program or an argument was refused, there is no answer set `K`, or none at all (the refutation is shown) |
| `INTERNAL_ERROR` | 3 | elenctic itself failed; one line on stderr |

A usage error is argparse's, status 2, before any command runs.

Stderr lines use one of two prefixes: `elenctic: …` for a failure of the command (a reserved-command note, or an internal error), and `path:line:col: error: …` (or the rustc multi-line form) for a fault in a source. A fault in an argument of `why` or `ask` names the argument in place of the path: `ATOM:1:1`, `QUERY:1:1`, `--assuming:1:1`.

## Contract syntax

A claim is a comment line beginning `%` followed by a tag. A brace group may continue over
following comment lines. A contract has exactly one `@expect`, without `assuming`. Several claims
of the same kind are independent claims: two `@answer-set` claims are two existential claims.

| Claim | Holds when |
|---|---|
| `@expect sat` / `@expect unsat` | the program has / has no answer set |
| `@count n` | exactly `n` distinct shown answer sets; under clingcon, distinct (shown atoms, assignment) pairs |
| `@answer-set { L }` | some answer set shows exactly `L` |
| `@answer-set { L } where { x=1, … }` | some answer set shows exactly `L` and assigns each variable that integer (clingcon) |
| `@assign { x=1, … }` | some answer set assigns each variable that integer (clingcon) |
| `@cautious { L }` | `L` is in every answer set (⋂ AS(P)); computed by the solver |
| `@brave { L }` | `L` is in some answer set (∪ AS(P)); computed by the solver |
| `@query A { L, … }` | the three-valued answer to the query is `A` (`yes`, `no`, `unknown`), over AS(P) |
| `@query A { p(X, b) } = { 1, 2 }` | the bindings of `X` with answer `A` are exactly these; every variable is named (`_` is refused) |
| `@query optimal A { L, … }`, `@query optimal A { p(X) } = { … }` | the same, over the optimal answer sets Opt(P) |
| `@answer-set optimal { L }`, `@cautious optimal { L }`, `@brave optimal { L }` | the same, over the optimal answer sets Opt(P); `@optimal { L }` is `@answer-set optimal { L }` |
| `@assign optimal { x=1, … }` | the same, over the optimal answer sets |
| `@count optimal n` | exactly `n` distinct shown optimal answer sets |
| `@cost { c1 c2 … }` | the optimum's cost, highest priority first, is exactly this (see below) |
| any of the above `assuming { l, not l }` | the claim is judged under those assumptions |

An objective ranks answer sets and never removes any: every claim above without `optimal`, and
unqualified `@query`, reads all the answer sets AS(P) whatever the program optimizes; only the
`optimal` claims (including `@query optimal`) and `@cost` read the optimal ones, Opt(P) ⊆ AS(P).
`@query` evaluates over the full answer sets (every atom), not only those `#show` selects; a query
that reads a derivable unshown literal gets a note in the report, which does not change the exit
([Semantics](../explanation/semantics.md)).

`@note` is ignored. `% @elenctic solver clingcon` (or `clingo`, the default) names the solver the
contract is checked with; it needs `elenctic[theory]`, and is a fault (`FAULT`, 2) when clingcon is
not installed. A variable is a term of the program (`x`, `digit(s)`), an integer its value.

### Costs

A cost is the minimized sum per priority level, as clingo reports it. A `#maximize` level is
negated: `@cost { -5 }` claims that the optimum of a `#maximize` is 5.

### Preconditions

A contract that would be misread is not judged; the source is reported as an error (`FAULT`, 2):

- the program has theory atoms and the contract does not declare `% @elenctic solver clingcon`
  (clingo would ground them and ignore their constraints);
- a theory objective (`&minimize`), which clingcon applies in every search and clingo's cost does
  not see;
- `@assign` or `where` under clingo, which has no assignment to read;
- an `optimal` or `@cost` claim over a program whose objective grounds away;
- `@count optimal N` greater than an explicit `@count M`;
- no `@expect`, more than one, or more than one `% @elenctic solver`;
- under `@expect unsat`, an answer set claim other than `@count 0`; under `@expect sat`, `@count 0`
  (each judged under the same assumptions).
## Verdicts

`pass`, `fail`, `undecided`. A report's verdict is the worst, with `fail` over `undecided`. A
search truncated by `--max-seconds` or `--max-answer-sets` can pass an existential claim (a witness was seen) or
fail a universal one (a counter-example was seen); anything else it leaves `undecided`.

When a truncation leaves a claim open, the text says what truncated the search: `search ended: answer-set limit reached
(--max-answer-sets)`, `time limit reached (--max-seconds)` or `interrupted`. In JSON the finding's `detail`
is then an object, `{"kind": "ended", "cut": "max_seconds", "optimum_unproven": false}`.

## Library

Everything in `elenctic.__all__`, and nothing else is promised; from 1.0 it follows semver, and
until then the changelog's Unreleased section is the record. Results are frozen dataclasses; spans
are half-open, `[start, end)`, one-based. Use one search at a time per `Grounded`; this is not
enforced. Every elenctic type that a public signature names is among them (a test checks it),
so `from elenctic import *` brings `All` and `Any`, the parts of a `Query`; `Any` is not `typing.Any`.

| Question | Call | Result |
|---|---|---|
| Is there an answer set? Which? | `solve(program, scenario)` | `Determination[AnswerSets]` |
| What is cautious or brave? | `Grounded.consequences(mode, scenario)` | `Determination[Consequences]` |
| What is optimal, at what cost? | `Grounded.optimize(scenario)` | `Determination[Optimized]` |
| Over which solver? | `solve(program, solver=Solver.CLINGCON)`, `ground(program, solver)` | the same; an `AnswerSet` carries its `assignment` |
| Why is there none? | the `Inconsistent` result's `refutation` | `These`, `NotThese` or `NoAssumptions` |
| Why does a claim fail? | `evidenced(report, program)`, or `Session.evidence(finding)` | each failed `Finding` with its `evidence` |
| Which is the k-th answer set, of all or of the optima? | `Session.counterexample(k, scenario, over=range)` | a `Counterexample`, the search stopping at it; the `Refutation` when there is none; `Ended`; or `None` past the last |
| What does a query come to over the answer sets? | `Session.answer(query, scenario, over=range)` | an `Answered`, the `Refutation` when there are none, or `Ended` |
| Why does an atom hold, or not, in an answer set? | `session(program).explain(literals, counterexample)` | an `Explanation` |
| Why does an atom hold, or not, in the k-th answer set? | `why(program, atom, index=k, scenario=…, over=…)` | an `Explanation`, the `Refutation`, `Ended`, or a `Fault` |
| What does a query come to over a program's answer sets? | `ask(program, query, over=…)` | an `Answered`, the `Refutation`, `Ended`, or a `Fault` |
| How does the objective rank some literals? | `Session.outrank(literals, scenario)` | `Outranked`, `Ended`, or `None` |
| Do two patterns have a common instance? | `mgu(first, second)` | a `Unifier`, or `None` |
| The same, their variables shared by name? | `unify(first, second)` | a `Substitution`, or `None` |

`mgu` renames the two patterns apart, so that a variable of one is not the variable of the other for
having the same name, and returns a `Unifier`: the two renamed patterns, the `Substitution` that
makes them one, and `instance`, the pattern both become (the most general common instance). `unify`
is the same unifier without the renaming: a variable of one pattern is the variable of the other with
its name. Both rest on one algorithm (Martelli and Montanari, near-linear, without recursion), and
queries are answered by it: a pattern's bindings are its unifiers with the cautious and brave
consequences ([Semantics](../explanation/semantics.md)). Against a ground pattern there is nothing
to rename, and `unify` and `mgu` find the same unifier.

## Names

Each name in `elenctic.__all__`, once; a test fails on a name that has no row.

### Programs and searches

| Name | What it is |
|---|---|
| `Program` | ASP source text and where it came from |
| `Grounded` | a program grounded once, to be searched under any number of scenarios |
| `ground` | ground a program for a `Solver`: a `Grounded`, or a `Fault` saying why not |
| `solve` | enumerate the answer sets of a program under a scenario |
| `Solver` | what a contract is checked with: `CLINGO`, or `CLINGCON`, which adds the clingcon theory |
| `Fault` | a failure that is no answer about the program: it could not be asked; `locus` says whose, `diagnostics` what |
| `Locus` | whose fault it is: `PROGRAM` or `REQUEST` |
| `Request` | what a search is asked: a `Scenario`, its `Limits` and an optional `Interrupt` |
| `Limits` | how far a search may go, in seconds and in answer sets read, each a number or `Limit.UNBOUNDED` |
| `Limit` | what a limit may be besides a number: `UNBOUNDED` |
| `Interrupt` | a request to stop, made from any thread with `pull()` and heeded between answer sets |
| `Keep` | which symbol sets of each answer set to retain for literal conversion (`atoms`, `shown`) |
| `Cut` | the function a search asks whether to stop: a `Truncation`, or `None` to go on |
| `Facts` | what the grounded program says about itself, against which a contract is checked |
| `Shown` | the predicates an unconditional `#show` selects; with no `#show` every atom is shown; a conditional or variable `#show` names none |

### Results of a search

| Name | What it is |
|---|---|
| `Determination` | a search's result: `Consistent`, `Inconsistent` or `Inconclusive`, over its evidence |
| `Consistent` | an answer set exists; `evidence` is what the search found and `conclusion` how it ended |
| `Inconsistent` | the search covered everything and no answer set satisfies the request; `refutation` says why |
| `Inconclusive` | the search was truncated before it decided |
| `Conclusion` | how a consistent search ended: `Exhausted` or a `Truncation` |
| `Exhausted` | the search covered every answer set under the request |
| `Truncation` | the search was truncated, and by what |
| `AnswerSets` | at least one answer set, in the order the solver found them |
| `Consequences` | the atoms true in every (cautious) or some (brave) answer set, among those shown |
| `Optimized` | the evidence of an optimization: an `Optimum` or an `Incumbent` |
| `Optimum` | a proven optimum: its cost and the optimal answer sets found (all, if exhausted) |
| `Incumbent` | the best answer set found before the search was truncated: not proven optimal |
| `Refutation` | why there is no answer set: `These`, `NotThese` or `NoAssumptions` |
| `These` | these assumptions, no fewer when `minimal`, admit no answer set |
| `NotThese` | no answer set whatever is assumed, and something is assumed |
| `NoAssumptions` | no answer set, and nothing is assumed |
| `AnswerSet` | an answer set: every atom, the atoms `#show` selects, its theory assignment and cost |
| `Mode` | `CAUTIOUS` or `BRAVE`: consequences true in every, or in some, answer set |
| `Range` | the range of answer sets a value ranges over: `ALL` answer sets, or the `OPTIMAL` ones |
| `Cost` | an optimum's cost, one integer for each priority level |
| `Assignment` | an answer set's theory assignment: a set of `Valuation` |
| `Valuation` | a theory variable and the integer an answer set gives it |

### Literals and terms

| Name | What it is |
|---|---|
| `Literal` | a ground classical literal: `p(t, ...)`, or `-p(t, ...)` when not `positive` |
| `Signature` | a predicate with its arity and sign: `p/1`, or `-p/1` |
| `Atoms` | a set of `Literal` |
| `Assumption` | a literal taken to hold, or, when not `holds`, taken not to; ordered by literal, then sign |
| `Scenario` | a set of `Assumption` under which a search is made |
| `Term` | a clingo symbol, a `Variable` or a `Compound` |
| `Variable` | a named variable; `_` is anonymous, and each of its occurrences is a different variable |
| `Compound` | a function term `f(...)`, `-f(...)` when not `positive`, or a tuple (empty `name`) |
| `Pattern` | a literal whose arguments may be terms with variables, nested to any depth |
| `Substitution` | what some variables stand for, as the unifying of patterns found |
| `Extension` | literals ordered by signature, so that those a pattern can unify with are found by binary search |
| `mgu` | the most general unifier of two patterns renamed apart, as a `Unifier`, or `None` |
| `unify` | the most general unifier of two patterns that share their variables by name, as a `Substitution`, or `None` |
| `Unifier` | two patterns renamed apart, the `Substitution` that makes them one, and the `instance` both become |

### Queries

| Name | What it is |
|---|---|
| `Query` | what a `WorldView` is asked: `Literal \| Pattern \| All \| Any` |
| `All` | the conjunction of its parts |
| `Any` | the disjunction of its parts; not `typing.Any` |
| `Answer` | `YES`, `NO` or `UNKNOWN`: a query true in every answer set, false in every one, or neither |
| `Truth` | truth in one answer set, ordered `FALSE < UNKNOWN < TRUE`, so that conjunction is `min` and disjunction `max` |
| `evaluate` | a query's `Truth` in one answer set |
| `answer` | a query's `Answer` over a `WorldView` |
| `answered` | a query answered over answer sets given in the order read: an `Answered` |
| `Answered` | a query's `answer`, or its `Bindings` for a pattern with variables, over the answer sets, `read` of them when the search read them all (else `None`), `over` all or the optima, with what it is `taken` to be in one answer set alone, and the answers `unreached` |
| `Taken` | an `answer` a query takes in one answer set alone, and the `index` of the first that gives it |
| `Unreached` | an `answer` a query takes in some answer set alone, past the `read` answer sets a search read before `cut` stopped it |
| `Bindings` | the values of a pattern's variables that give each answer; `giving(answer)` selects those of one |
| `bindings` | the `Bindings` of a `Pattern` over a `WorldView`: its unifiers with the cautious consequences (yes, and no by the contrary), and with the brave ones for the rest it entertains (unknown) |
| `WorldView` | the answer sets of a program, all of them: only an exhausted search yields one |
| `world_view` | close a consistent search over answer sets into its `WorldView`, or give the `Truncation` that left it open |
| `optimal_view` | close a proven optimum into the `WorldView` of its optimal answer sets, or give the `Truncation` that left it open |

### Contracts and verdicts

| Name | What it is |
|---|---|
| `check` | check the contract written in a program: a `Report`, or `None` if it carries none |
| `why` | explain an atom in one answer set of a program, opened as `check` opens it |
| `ask` | answer a query over the answer sets of a program, opened as `check` opens it |
| `Why` | what `why` comes to: `Explanation \| Refutation \| Ended \| Fault` |
| `Ask` | what `ask` comes to: `Answered \| Refutation \| Ended \| Fault` |
| `WhyExit` | the status `why` exits with, named by `WhyExit.of(result)`; an `Internal` failure is 3 |
| `AskExit` | the status `ask` exits with, named by `AskExit.of(result)`; an `Internal` failure is 3 |
| `Internal` | elenctic itself failed: the `error_type` and `message` of the exception |
| `parse_contract` | read each tag of a text: a claim for every one that reads, a diagnostic for the rest |
| `render` | write a claim as the tag line that reads back to it |
| `judge` | judge one claim against the search over its scenario: a `Finding` |
| `Contract` | the claims of a source, the diagnostics of its tags and its `solver` |
| `Claim` | a `Reading` to hold under a `Scenario`, and where it was written |
| `Reading` | the meaning of one tag: one of the eight below |
| `Satisfiable` | `@expect sat \| unsat` |
| `Census` | `@count [optimal] n` |
| `Witness` | `@answer-set [optimal] { L } [where { A }]`, or `@optimal { L }` |
| `Assigns` | `@assign [optimal] { A }` |
| `Entails` | `@cautious [optimal] { L }` and `@brave [optimal] { L }` |
| `Costs` | `@cost { c1 c2 ... }` |
| `Asks` | `@query [optimal] A { L, ... }`: a conjunction of ground literals has the answer `A` |
| `Binds` | `@query [optimal] A { q(X, ...) } = { B }`: the bindings giving `A` are exactly `B` |
| `Finding` | a claim, the verdict on it, its `Detail`: what was expected against what was found, and its `evidence`, `None` unless `explain` found some |
| `Detail` | text, or an `Ended` when the search ended before it could settle the claim |
| `Ended` | the `Truncation` that truncated the search, and whether an optimum went unproven; the text view words it, and in JSON it is the finding's `detail` |
| `Found` | a search `judge` can read: a `Determination` over `AnswerSets`, `Consequences` or `Optimized` |
| `Report` | the findings for one source, and `lints` (notes on queries that read a hidden literal); `verdict` is `FAIL` if any fails, else `UNDECIDED` if any is, else `PASS` |
| `Verdict` | `PASS`, `FAIL` or `UNDECIDED` |

### Evidence

| Name | What it is |
|---|---|
| `session` | ground a program for a `Solver` into a `Session`, or a `Fault` saying why not |
| `Session` | a `Grounded` that can explain what it finds: `counterexample`, `answer`, `explain`, `outrank`, `evidence` |
| `evidenced` | a `Report` with the `evidence` of each failed finding, or a `Fault` |
| `Evidence` | why a claim fails: an `Explanation`, a `Refutation` or an `Outranked` |
| `Explanation` | why each root holds or not in a `Counterexample`: its `nodes` in first-visit order, each once; `minimality`, `max_depth`, and `complete` when no node is `Unexpanded` |
| `Counterexample` | the answer set explained, as a claim fails in it or as asked for: the `index`-th found, of `read` (`None` when the search did not read them all) |
| `Node` | a `handle`, an `atom`, whether it `holds`, its `Reason`, and its `children` by handle |
| `Handle` | a node's name, built from what it says: `1/p(a)`, `1/not p(a)`, and `1/not p(a)#r8(a)` for the instance of statement 8 with its variables' values `(a)`; `1/` is the counterexample's index |
| `Reason` | why a node holds or not: one of the eleven below |
| `Fact` | holds: a fact, its `rule` |
| `Derived` | holds: a rule instance, its `substitution`, the ground `instance`, and its `conditions` (the literals not expanded) |
| `Chosen` | holds: a choice made, its bounds and how many were `chosen` |
| `NotChosen` | could hold: the choice could have made it, and did not |
| `Aggregate` | an aggregate, its ground `atom`, its `value` and its `guard`; its children are the elements counted, and those missing when it fails |
| `TheoryAtom` | a theory atom and the `assignment` of its variables |
| `Unsupported` | absent: `candidates` instances could derive it, each a child |
| `Blocked` | an instance that does not fire, and its first `literal` that fails |
| `NoRule` | absent: no instance's body can ever hold |
| `Unexpanded` | the explanation stops here, at its `max_depth` |
| `Unexplained` | a construct no reason covers yet; its `rule`, if any |
| `Rule` | a statement of the source: its index, `span` and `text` |
| `Minimality` | what an explanation promises: `NONE`, sound support that may not be minimal |
| `Outranked` | literals some answer set holds and the objective ranks below the optimum: the costs by `priorities`, the first `priority` that differs, the instances paid only by each side, and the `explanation` of their absence from the optimum |
| `Paid` | a weak-constraint instance an answer set pays: its `rule`, `weight`, `priority`, `terms` and `substitution` |

### Sources

| Name | What it is |
|---|---|
| `Position` | a point in a source; line and column both count from 1 |
| `Span` | the half-open stretch of a source from `start` to `end` |
| `Diagnostic` | a message about a `Span` (or the whole source when `span` is none), with its `Severity`, optional `label`, and `children` (`note`/`help`); the JSON schema also declares an optional `code` (unused in 1.0) |
| `Child` | a `note` or `help` attached to a diagnostic |
| `Severity` | `ERROR`, `WARNING`, `NOTE` or `HELP` |

## JSON

`{"schema": 1, "run": {"entries": [...]}, "exit_code": n}`, where `n` is the `Exit` of that `test` run (0, 1, 2, or 3); see `elenctic.json_view.encode`. `why` writes `{"schema": 1, "why": …, "exit_code": n}`, the value an `explanation`, a refutation, `ended`, a `fault` or `internal`; `ask` writes `"ask"` the same way, its value an `answered` in place of the explanation, and `n` is the command's own exit. A
dataclass becomes `{"kind": type_name, field: …}`, the `kind` being the type's name in snake case (`Census` is `census`, `AnswerSet` is `answer_set`), an enum its value, a set a sorted list. Keys and enum values are snake_case (`max_answer_sets`);
the command-line flags keep their hyphens (`--max-answer-sets`). A `Substitution` is a string,
`"{X=b, Y=c}"`, as a literal is. A finding has an `evidence` key only when it has evidence, so a
`test` run is written as before. The published JSON Schema of that document is [`output-v1.schema.json`](output-v1.schema.json), generated from the same types by `scripts/write_output_schema.py` (`elenctic.json_view.schema_document`); a test fails if it is stale.

## Examples

[Every claim kind with its real output](examples.md).
