# Changelog

Notable changes to elenctic. The format follows
[Keep a Changelog](https://keepachangelog.com/).

**A patch bump will not break code written against the supported surface, and that surface is what
`import elenctic` gives you.** It may still fix a defect, and a fix changes behaviour — what it will
not do is remove a name, change a signature, or alter what a name means. Breaking changes are held
for a minor bump and described under the release that makes them. This is a narrower promise than
[Semantic Versioning](https://semver.org/) makes of a `0.x` release, which permits anything to
change at any time; [Using elenctic as a library](docs/library-api.md) says what is inside the
surface and what is not.

Changes are recorded under **Unreleased** as they merge; cutting a release renames that section to
the version and dates it. Entries describe what changed for someone using elenctic, and what it
means for them — a reader deciding whether to upgrade should not have to read the commits.

## [Unreleased]

**Upgrading from 0.3.0?** These are the changes that ask something of you. Each is written in
full under its own heading below; this is a place to look first, not a second account of them.
Every one of them is marked **What can break:** where it is described.

- A vocabulary for what a program declares observable: `ShownVocabulary`, `Unrestricted`, `Restricted` and `Signature`
- The command line takes a command: `elenctic run|explain|schema`
- A `@cautious`/`@brave` claim over a literal the program does not declare observable is now refused, where it used to be FAILed
- A `@query` whose answer the program does not determine is now refused rather than answered
- Escaped text is now spelled the way Python spells it, and is reversible
- A line break in corpus text is escaped, and a solver's own diagnostic is quoted instead
- A `where { … }` clause is refused wherever it is mis-placed, not only under a witness tag
- `@count 0` and `@count optimal 0` under `@expect unsat` are checked and reported
- A file's contract is read by a real tokenizer, so five things that were nearly-contracts now are not — or now are
- The curated surface stops accepting what it cannot honour
- A case that reaches outside its corpus is filed under a locus of its own, `containment`
- The machine-readable document is `schema_version` 2
- Library callers: what an exception's `str()` says has changed
- A case may not read past its corpus while the program is *solved*, not only while it is read
- `discovery.check_solver_available` no longer takes `where`
- A reader that stops reading no longer looks like a failed corpus


### Added

- **A refused command line names the word you probably meant.** `elenctic rnu tests/` now answers
  *invalid choice: 'rnu', maybe you meant 'run'?* rather than leaving a reader to spot the near miss
  in the enumeration themselves, and the same holds for a value — `--format huamn` names `human`.
  The command word makes mistyping one possible in the first place, so this arrives with it.

- **`elenctic.error_detail`** — the reason a caught fault gives, and the contract line it gives it
  about, as a pair. The sibling of `error_kind`: that one reads *where the fault lies* off the
  class, this reads *what it says* and *where it says it* off the value. It is what a caller
  building its own `ErrorRecord` wants, and it is how elenctic builds its own — so a runner of your
  own files a fault exactly as the shipped one does, without parsing a sentence to get there.

- **A vocabulary for what a program declares observable: `ShownVocabulary`, `Unrestricted`,
  `Restricted` and `Signature`.** A program with no `#show` at all and a program that shows nothing
  are opposite states — clingo shows everything in the first and nothing in the second — and both
  used to arrive as an empty set of signatures, so nothing downstream could tell them apart. They
  are now two shapes rather than one value, which is what lets the checks below be right about
  either. `ProgramFacts.shown` and `Case.shown` carry a `ShownVocabulary` where they carried a
  `frozenset` of signature pairs. **What can break:** anything reading those two fields.

- **`elenctic.run_plan`** joins `run_case` on the curated surface, so a runner of your own can hold
  a plan and run it rather than only run a case end to end.

### Changed

- **The command line takes a command: `elenctic run|explain|schema`.** Every invocation names one.

  | 0.3.0 | 0.4.0 |
  |---|---|
  | `elenctic tests/` | `elenctic run tests/` |
  | `elenctic tests/ --explain` | `elenctic explain tests/` |
  | `elenctic --print-schema` | `elenctic schema` |

  **What can break:** every existing invocation and every script that wraps one. `elenctic tests/`
  is refused, naming the three commands. There is deliberately no default command — `elenctic
  explain` would otherwise mean either the dry run or a corpus in a directory called `explain`, and
  whatever settled that would be a precedence no surface states.

  The two flags that each replaced the run were two independent booleans, so asking for both at
  once was answered by whichever branch was written first — a decision no surface stated. It is now
  unspellable rather than refused.

  **Each command carries the dials it reads, and no others.** The dry run accepted `--budget` and
  `--deadline`, read neither, and still refused a value of either that was not a positive finite
  number of seconds; the description accepted both, plus `--strict` and a target, and looked at none
  of them — its help said as much, in a sentence. Those are now unrecognized arguments. A dry run
  still has no machine-readable form in this version, so `--format` is one of `run`'s options and
  `elenctic explain --help` says why.

  `elenctic schema` takes **no target**, where `--print-schema` accepted one and ignored it: a
  reader who names their corpus there was handed something unrelated with the status that says
  nothing went wrong, and is now told instead.

- **An allocation that fails while *writing* the packaged description no longer blames a corpus.**
  One that failed while reading it was answered with the sentence about a description; one that
  failed writing it fell through to the run's backstop, which asks the reader to run their corpus
  with a memory limit and reduce what it grounds — of a command that walks no corpus and grounds
  nothing.

- **A `@cautious`/`@brave` claim over a literal the program does not declare observable is now
  refused, where it used to be FAILed.** These tags claim membership of ⋂ AS(P) and ⋃ AS(P), and
  elenctic decides them over the answer sets restricted to what the program shows. Where a claimed
  literal's signature is not declared, the literal reaches no projection at all, so the claim failed
  *whatever the program computed* — and a verdict that does not depend on the answer sets is not a
  reading of them. It failed a true claim as readily as a false one:

  ```asp
  % @cautious { p(x) }
  p(x). q(x).
  #show q/1.
  ```

  `p(x)` is a cautious consequence and the report said otherwise. Such a case now reports a
  discovery error naming the claim's line and what to declare. This covers all four tags —
  `@cautious`, `@brave`, `@cautious optimal`, `@brave optimal`. **What can break:** a case of yours
  goes from FAIL to a refusal — and the FAIL was not a reading of your program; declare the signature, or, where the
  predicate reaches the output through a `#show <term> : <body>.` directive, give what that
  directive selects a name of its own and claim that instead. The message says which.

- **A `@query` whose answer the program does not determine is now refused rather than answered.**
  This is the change with the most reach, and the one this release exists for. elenctic does not
  check the answer you claimed; it *computes* the query's three-valued answer from what the solver
  puts in the output. A literal that never reaches the output cannot be told apart from one no
  answer set contains, so where a signature the query reads is undeclared the computed answer
  described the `#show` directives rather than the program — and elenctic reported it as a verdict.
  Two routes were silently **wrong**, not merely unhelpful: `@query unknown { p }` passed where the
  true answer is `yes` because `p` was a fact that nothing showed, and `@query no { q(X) } = { }`
  passed on a program whose `no`-set was not empty.

  A `@query` now needs **every signature it reads** declared observable, and what a query reads
  depends on its form. A **ground** query reads every conjunct and every conjunct's contrary,
  whichever answer it claims — so a `yes` query missing the contrary is refused exactly as a `no`
  one is, which is the part most likely to surprise. A **binding** query (`{ q(X̄) } = { B }`)
  collects the tuples whose answer is the stated one, which is one-sided, so it reads `q` for `yes`,
  `-q` for `no`, and both for `unknown`; requiring the other sign there would refuse contracts
  elenctic answers exactly. **What can break:** a case that reported `1/1 passed`, or a FAIL, now
  reports a discovery error at exit `2`, naming the claim's line and the signature to declare.

  The other direction, so the trade is visible: **a `@query` in a program with no `#show` at all is
  now answered where it was refused.** No declaration means clingo shows every atom, which is the
  most observable a program gets; reading that as "shows nothing" was the same conflation, costing
  a refusal instead of a wrong answer.

- **A `@query` over a signature that is displayed *and* declared, or displayed by an otherwise
  unrestricted program, is now answered rather than refused.** Both were refused on the ground that
  a display directive could put in the output a term no answer set contains. It cannot: since 0.3.0
  an observable holds only symbols the model contains, so such a term is dropped before any reading
  sees it. What is left of the display form is that it emits its term only where its body holds,
  which costs nothing when the signature is declared as well or when the program restricts nothing.
  The refusal for a signature that is displayed and *not* declared is unchanged.

- **Escaped text is now spelled the way Python spells it, and is reversible.** `elenctic.legible`
  promised a `\xNN` escape and produced one only below U+0100: `:02x` is a *minimum* width, so
  U+2028 came out as `\x2028` and U+10FFFF as `\x10ffff`, which read under every convention as
  `\x20` followed by literal digits. Worse, `\` was printable and so never escaped, which made the
  encoding **not injective** — a path holding a real escape and a path holding the four characters
  `\x1b` rendered identically, in the report and in the `source` field of the machine-readable
  document, and a consumer un-escaping to recover the path re-injected the real escape into its own
  terminal. Escapes are now `\xNN`, `\uNNNN` and `\UNNNNNNNN` by width, and a backslash is doubled.
  **What can break:** anything matching on the old rendering, and anything that un-escaped it.

  **`explain` renders its subject through the same sanitizer**, which it did not. A repeatable
  tag's claim is text a corpus author wrote, and a `#show`n string term carries whatever is between
  its quotes, so a dry run over a hostile corpus wrote raw control characters to the terminal — the
  one frame of four that the guarantee stated per module had never been applied to.

- **A line break in corpus text is escaped, and a solver's own diagnostic is quoted instead.**
  `elenctic.legible` let `\n` through, on the reasoning that adding a line is harmless beside
  overwriting one. It is not: a report's structure **is** its line boundaries, so text that can add
  a line can write a row. A newline is a legal byte in a file name, and a file named with one
  printed a `[PASS]` directly above the `[FAIL]` its own case had just earned — two rows claiming
  the same contract line and contradicting each other. Every corpus-controlled string now comes
  back as one line, a break spelled `\x0a` like every other control character.

  **A solver's diagnostic still runs to several lines.** The human report re-emits the breaks
  itself and marks every line below the first with `  | `, a mark it writes nowhere else — so an
  added line is the report's own structure and never the corpus's. An indent could not promise
  that: text choosing its own leading spaces chooses which column it lands in.
  Nor could sorting fields into may-span and may-not, which is what settled the design — clingo
  writes the file's name *into* its diagnostic, so the one string that may span lines carries the
  one value that can forge one. An ordinary syntax error reads as a quoted block now, where its
  second line used to land on column 0 beside the case headers and the tally.

  **What can break:** anything matching on a rendered multi-line diagnostic; any consumer of the
  machine-readable document reading `message`, where a line break is now the `\x0a` escape,
  recovered exactly as every other escape in that document already is; and a runner of your own that
  renders an `ErrorRecord` itself — `message` is the one string a record carries that may run to
  several lines, which its own documentation now says, and `elenctic.legible` answers what a string
  may contain and not how many lines it may take.

- **A `where { … }` clause is refused wherever it is mis-placed, not only under a witness tag.**
  The guard said it was unconditional and required the tag above it to be `@model` or `@optimal`, so
  a `where` following a `@note` was **silently dropped**: the author's theory binding vanished, and
  because nothing recorded that a theory was wanted the clingcon requirement did not fire either —
  a contract quietly weakened, which is the outcome the guard exists to prevent. **What can break:**
  a `%` comment that *opens* with `where {` — set-builder notation in prose, say — is now read as a
  mis-placed clause and refused. That is a real cost of reading the one non-`@` piece of contract
  syntax by position, and it is taken deliberately: reword the comment.

- **`@count 0` and `@count optimal 0` under `@expect unsat` are checked and reported.** Both were
  accepted by the parser and then discarded, so a contract that claimed something was checked for
  nothing — against this file's own promise that a parse never silently discards, and against the
  schema's sentence that a document holds one entry per contract claim. `Unsat` now carries `count`
  and `count_optimal`, and refuses a non-zero count at construction. **What can break:** an unsat
  case gains an entry per claim in the machine-readable document, and a FAIL line per claim in the
  human report when the program turns out to be satisfiable. `Unsat` is a curated export, so a
  caller constructing one gains two optional fields.

- **A file's contract is read by a real tokenizer, so five things that were nearly-contracts now
  are not — or now are.** Contract tags were found by scanning lines; the scan did not know what
  clingo's comment grammar is, and five states came out wrong. Each is a migration line:

  **What can break:** a corpus that passed on 0.3.0 can fail here, and the first bullet is why.

  - **A run of tag lines *after* the program is a contract**, so a file that was a library because
    its tags trailed the rules is now a case. This is the one most likely to turn a green corpus
    red, and it is the one to look at first.
  - **Tags only inside a `%* … *%` block comment no longer make a file a case.** A block comment is
    a comment all the way through.
  - **A `%`-tag inside a `#script` body no longer makes a file a case**, for the same reason.
  - **A litset continuation ends at program text**, and at a comment that does not begin its line,
    rather than running past the rule in between.
  - **A file whose `%*` or `#script` never closes is refused at exit `2`** rather than filed away as
    a library. It was a *bug fix* rather than a tightening: an unterminated block swallows the rest
    of the file, so every contract below it was out of force and the file was silently treated as
    something to include rather than something to run.

- **The curated surface stops accepting what it cannot honour.** **What can break:** five things,
  each for someone: `solve`'s `solver` parameter is typed `Solver` rather than `str`, so an unknown name is
  a type error at the call site instead of a `ValueError` mid-run; `HygieneReport` is keyword-only
  (its two neighbouring fields are both `tuple[Path, ...]`, so a transposed pair type-checked clean
  and rendered a plausible row); `CheckReport` enforces the `@`-tag invariant its internal sibling
  always did, since its `label` goes straight into the published `tag` field; `Observable` refuses
  an assignment giving one variable two values, and does so with `HarnessError` rather than
  `ValueError`, so it costs one case its verdict instead of the whole run; and `Invocation`'s
  `strict`, `budget` and `deadline` now **default**, to exactly the command line's defaults, where
  all four fields were required and a consumer's reasonable prediction was false.

- **A case that reaches outside its corpus is filed under a locus of its own, `containment`.** It
  was filed under `discovery`, which said where elenctic happened to notice rather than what was
  wrong — and *which* phase notices is decided by whether the escaping file parses, so one rule
  could arrive as two different problems. Two things a script may match on move with it:

  ```
  0.3.0    "kind": "discovery"        DISCOVERY ERROR — <file>: this case loads …
  0.4.0    "kind": "containment"      CONTAINMENT ERROR — <file>: this case loads …
  ```

  `kind` is an open-valued field, so this needs no `schema_version` bump — but it is the eighth
  value of a field that carried seven in 0.3.0, and a consumer keeping a table of loci wants the
  row.

  **What can break:** a library consumer who catches it by class. 0.3.0 raised a `DiscoveryError`;
  this raises **`elenctic.ContainmentError`**, which is a `ProgramError` by inheritance and no
  longer a `DiscoveryError` at all. `except elenctic.DiscoveryError` stops catching an escaping
  `#include`; `except elenctic.ProgramError` catches it, and `except elenctic.ContainmentError`
  catches only it. The family moved because what is wrong is the program under test reaching
  somewhere it may not, which is its author's to fix — not the shape of the corpus around it.

  The class is **new on the curated surface**, and it is the distinction worth having a name for:
  every other locus a runner may want to answer differently already had one, and a case reaching
  outside the corpus it was given is a question about that corpus rather than about how one
  encoding is written. `elenctic.error_kind` still answers the same question from the value.

- **A containment diagnostic no longer claims the set it shows is ⋂ AS(P).** It reports what was
  observed, because the set elenctic can show is the shown projection and on any program that
  restricts its output that is a proper subset of the real one — every input fact is in every answer
  set and in none of these. The verdict was never affected. A `@cautious` failure read

  ```
  [FAIL] @cautious { tea } (line 10): { tea } ⊄ ⋂ AS(P) = { biscuit } (missing: { tea })
  ```

  and now reads

  ```
  [FAIL] @cautious { tea } (line 10): { tea } ⊄ ⋂ AS(P) (observed { biscuit }; missing { tea })
  ```

  The same text is the `message` field of a check in the machine-readable report.

- **Every diagnostic now names its file exactly once, wherever the fault was met.** This is the
  remaining half of 0.3.0's heading work, and it is settled the way that entry said it would have
  to be: provenance lives in the record, not in the message. A fault that would not ground used to
  read

  ```
  PROGRAM ERROR — tri/unsafe.lp: cannot run the program (tri/unsafe.lp): tri/unsafe.lp:3:1-14: error: …
  ```

  — the path three times — and now reads

  ```
  PROGRAM ERROR — tri/unsafe.lp: cannot run the program: tri/unsafe.lp:3:1-14: error: …
  ```

  where the first is elenctic saying which case produced no verdict and the second is clingo's own
  coordinate, quoted as it wrote it. A parse fault and a ground fault now read alike; they did not
  before, because the renderer decided whether to name the file from the *locus* while the thing it
  was reaching for was a property of the *message*.

  **A contract fault and an unanswerable `@query` now name the line as well** — `<file>:<line>:` —
  in the spelling clingo, rustc and pytest all use.

- **The machine-readable document is `schema_version` 2.** *If you consume `--format json`, this
  is the entry to read.*

  - `error.line` is **new and required**: the 1-based contract line the fault is about, or `null`
    where it is about no single line. It is the same field `check.line` has been.
  - `error.message` **no longer carries the file elenctic put there.** A solver's own coordinates
    remain inside it, because those say *where in the program* and nothing else does.
  - `error.source` is now populated in one case where it was `null` before: a named target that
    does not exist. The name typed is what such a fault is about.

  **What can break:** code recovering a path by splitting `error.message` gets a wrong string
  rather than an error. Read `error.source`, and `error.line` beside it.

  `elenctic schema` prints the v2 description; the packaged file is
  `elenctic/schema/output-v2.schema.json`.

- **Library callers: what an exception's `str()` says has changed.** A fault now states the
  reason and only the provenance its caller could not already know — which is the *line*, never the
  file, since the file is what the caller passed in. `ProgramError` no longer opens with the files
  it was handed (a join of all of them, which never identified the offending one; clingo's
  coordinate does). Most `DiscoveryError`s no longer name the case. `ContractError` is unchanged:
  it still reads `<source>:<line>: <reason>`.

  **What can break:** anything logging or matching on `str(exc)`. Nothing published had said that
  text was yours to rely on, and nothing now says it is — so the parts are given names instead.

  Both `ContractError` and `DiscoveryError` now also carry `.reason` and `.line` as attributes, so
  a caller building its own report reads the parts rather than parsing the sentence. `error_detail`
  above reads them off any fault, including the ones that carry neither.

- **`ErrorRecord` gained `line`, and two refusals.** A record with a line and no file is refused
  (half a coordinate points at line 3 of nothing), as is a line below 1. Built by keyword as
  before, so existing construction sites are unaffected unless they pass the new field.

- **A case may not read past its corpus while the program is *solved*, not only while it is read.**
  A case whose `#include` reaches outside the corpus is refused, and the solver's own account of
  the offending file — which names it, says how far in the solver got, and quotes the text it
  objected to — is withheld. That rule held when the escaping file failed to *parse*; a file that
  parsed and then would not *ground* was diagnosed in full. Which of the two a corpus met was
  decided by the offending file's syntax, so one rule was enforced in one frame and not the other.
  Both frames now ask one seam and answer in one set of words.

  `Case` gained **`boundary`** and `solve` gained **`within`** to carry it there, both optional and
  both defaulting to `None`, which states no rule — the reading a caller assembling its own files
  already has. A `Case` from `discover` carries the corpus it was found in, so a runner built on
  `run_case`/`run_plan` gets this without doing anything.

  **`Boundary` is now exported from `elenctic`.** It had to be: `Case` is on the curated surface and
  the boundary is one of its fields, so a consumer able to build a case but not the corpus it
  belongs to could not state the rule at all.

  **`Boundary` refuses a root that is not already resolved.** Containment compares a resolved
  candidate against it, so a root still carrying a symlink or a `..` reports *every* file in the
  corpus as outside it — including the case's own. Pass `path.resolve()`.

  **What can break:** a positional caller — `solve`'s `project` and `within` are keyword-only. They are
  adjacent, both optional and differently typed, so passing them positionally with `budget` omitted
  put a boundary in `project`, where it is truthy — the run silently projected and stated no
  containment rule. Call `solve(solver, mode, files=…, project=…, within=…)`.

- **A character the solver's lexer rejects no longer kills the run.** A single non-ASCII character
  where clingo will not take one — an accented identifier, a smart quote pasted from a document —
  used to end the process: empty standard output, a Python traceback and `PANIC: exception in
  nothrow scope` on standard error, exit 1, and **no report for any case in the corpus**. It is now
  an ordinary program fault: that case is reported, every other case still runs, and the run reaches
  its tally.

  clingo reports a lexer error by quoting the offending *byte*, and a lone UTF-8 lead byte does not
  decode. Handed to a Python logger the message is decoded by clingo, inside a frame declared not to
  throw, so the failure could not be caught — not even by `except BaseException`. elenctic now reads
  clingo's diagnostics from the descriptor clingo writes them to and decodes them itself, where a
  byte that will not decode becomes one replacement character in a diagnostic instead of the end of
  the run.

  **Valid UTF-8 was never affected and still is not:** a string literal such as `p("café")`, a
  UTF-8 comment, and a `@note` carrying an em dash all pass, as they did before. Refusing non-ASCII
  input was considered and rejected for exactly that reason — clingo accepts those.

  **A contract term** carrying such a character never killed the run; it reported the underlying
  `'utf-8' codec can't decode byte …` instead. It now names the term and the remedy.

  **What moves in the output:** where clingo reports *more than one* diagnostic for a program, they
  are no longer run together with `; ` between them — they appear in clingo's own framing, one blank
  line apart. A single-diagnostic fault is unchanged, byte for byte.

  **For library callers embedding elenctic in threads:** the capture redirects a process-wide file
  descriptor, so concurrent solves inside one process are serialised by a lock. Parallelising across
  processes — which is what a `pytest` plugin does — is unaffected.

### Removed

- **`discovery.check_solver_available` no longer takes `where`.** **What can break:** any caller
  passing it. It spelled that path into the
  refusal, which said nothing a caller asking about a case it holds did not already know. Call it
  as `check_solver_available(case.solver)`.

### Fixed

- **`--format json` no longer writes a corrupt document when standard error is closed.** Run as
  `2>&-`, elenctic wrote its diagnostics and its tally onto **standard output**, in front of the
  JSON — so the document did not parse, and on a passing corpus the status was still `0`: an
  unparseable document and a success signal together. Two mechanisms, and fixing one would have
  left four of the five routes open. With descriptor 2 closed it is the lowest free number, so the
  save-and-restore that exists to move diagnostics off the document pointed standard output at
  itself; and this language leaves `sys.stderr` unbuilt in that state, so `print` falls back to
  standard output from frames the redirect never covered — including argparse's own, which elenctic
  does not own at all. elenctic now establishes a standard error before anything else runs, so
  `2>&-` and `2>/dev/null` are two spellings of one wish and behave alike.

- **A reader that stops reading no longer looks like a failed corpus.** Piping into `head`, or
  quitting a pager, produced four different answers depending on format and how much had been
  buffered: exit `1` — the rung that means *a case was decided wrong* — with a raw Python traceback;
  exit `120`, which is on no documented ladder; or, for `--print-schema`, exit `3`, telling a reader
  who piped the schema into `head` that they had found a bug in elenctic. A run now leaves with the
  status it would have left with anyway, plus one sentence on standard error saying the output was
  cut short. **What can break:** a script keying on `120`, or reading exit `1` after a closed pipe
  as a corpus failure, sees different numbers — which is the point.

- **A case is judged against its corpus boundary before the solver's account of an escaping file
  escapes.** Containment was checked *after* the program had been read, so a case reaching outside
  its corpus for a file that would not parse was answered with clingo's diagnostic about that file —
  disclosing that it exists, roughly how long it is, and the coordinates it objected to, from a
  corpus. The rule's own docstring said the diagnostic names the escaping path and nothing from
  inside it. It does now, and the same rule is enforced whether the escaping file fails to parse or
  fails to ground.

- **The containment diagnostic says why the boundary is where it is when you name a single case.**
  Naming one file makes that file's own directory the corpus root, so `elenctic run corpus/x/case.lp`
  refused an `#include` that `elenctic run corpus/` accepts — the first thing anyone does when a
  case fails in CI, and neither the published documentation nor the message mentioned that the
  invocation form changes the rule. The behaviour is unchanged and deliberate; it is now said out
  loud, with the remedy.

- **The diagnostic a missing theory solver gives now names an install command that works.** It said
  `pip install "elenctic[theory]"`, and elenctic is not on PyPI, so the likeliest exit `2` a real
  user meets handed them a command that cannot succeed — and for the recommended path it was wrong
  twice, since clingcon comes from conda-forge and the extra is not needed there. The message now
  gives the conda-forge route and the git-URL form of the extra.

- **A refusal from a pipeline-stage module no longer lands in its payload.** The four inspection
  entries — `python -m elenctic.expectation|run|discovery|solvers` — print a usage line and leave
  with status 2 when the command line is wrong. Run with standard error *closed* rather than
  redirected (`2>&-`), this language leaves `sys.stderr` unbuilt and `print` writes to standard
  output instead, so the stream carrying the inspection received `usage: python -m elenctic.…` on
  the one run that produced no inspection at all. All four now establish a standard error before
  writing anything, as the `elenctic` console entry always has. A stage that *does* its work in that
  state now completes as well, where the solve previously failed outright on the missing descriptor.

- **A damaged output description is reported instead of published.** `elenctic schema`
  writes the packaged description of the machine-readable report. A packaging or vendoring step can
  drop that file, put something else in its way, re-encode it, or leave it half written; only the
  first two were reported. A file cut short was published as far as it went, and one cut to
  **nothing** was published as nothing — **exit 0, both streams empty**, the one outcome that tells
  a reader there is nothing to look into. All of them now leave with status 2.

  **The diagnostic carries the reason the read gave**, because that is what separates the remedies:
  a file that is absent is fixed by reinstalling, and one refused by its own permissions is not.
  Running out of memory on that path no longer reports itself as a corpus that grounded too much —
  no corpus is walked when the description is printed.

- **`elenctic schema` writes the packaged file byte for byte, including its line endings.** It was
  read as text, so a checkout or archive that gave the file CRLF had them translated back to LF on
  the way out, and what was published differed from what shipped by exactly the bytes someone
  diffing the two would see.

  **For library callers:** `elenctic.schema_text()` now raises rather than returning a string that
  describes nothing — `json.JSONDecodeError` where the packaged file is empty or truncated. What it
  returns when the package is intact is unchanged, and is now unchanged on every platform.

## [0.3.0] - 2026-08-04

The minor bump is deliberate, and this is the release with the most to re-check in it so far.
Six things can stop working: a fault in elenctic now exits `3` where it exited `2`; most
diagnostic headings changed, and the table below says which did not; `HygieneReport.render` is
gone; `Sat`, `Unsat` and `CheckReport` gained required fields, and the records a machine-readable
report is built from — `CheckReport` among them — are now keyword-only; `Collection` moved module;
and three invariants elenctic checks about its own result raise `HarnessError` where they raised
`ValueError`. Each is marked below. If you only run the command line, the first two are the ones to
look at; if you import elenctic, read the rest.

### Added

- **`--format json` — a machine-readable report, as one JSON object on standard output.** Everything
  else a run writes moves to standard error, so standard output carries a whole document or nothing
  at all and a consumer can parse it without filtering. Results stay in the three registers the exit
  status is built from: `cases` holds judgments about programs, `errors` says where no judgment could
  be made, `hygiene` holds observations about the corpus's own health. Each check carries the
  **line** its claim was written on, so a result can be placed where the claim is, and a
  `conclusion` saying how the search behind the verdict ended — which is what tells "the budget was
  too small" apart from "the program is wrong". The exit status is readable off the document alone.

  The default is `--format human`, which is also spellable, so a script can be explicit and get
  exactly what it gets by saying nothing. That is *not* what earlier versions printed: the
  diagnostic rows themselves changed on this release — see the per-line entry under Changed — so a
  job scraping standard output needs re-checking whichever way it spells the format. A format this
  version does not know is refused rather than quietly rendered as prose, since being handed prose
  where a document was expected is the failure a machine consumer would find hardest to notice.

- **elenctic can be used as a library, and the pieces `elenctic` itself runs on are the pieces you
  get.** `elenctic.run_corpus` takes an `Invocation` — the settled form of a command line — and
  returns everything the run produced; `elenctic.explain_corpus` derives the run plans instead;
  `elenctic.exit_status` reads either against the `ExitStatus` ladder; `elenctic.as_json` renders a
  *run's* outcome as the published document, this version describing no document for a plan — which
  is why the command line refuses `--explain --format json`. The console entry is now these calls
  with a command line in front of them rather than the place the work is done, so an editor plugin,
  a CI script or another test runner gets the same values it does. Working one case at a time with
  `run_case` is unchanged and still the right thing when you want elenctic's checks inside a runner
  of your own.

- **Both runners are silent, and take an observer if you want to watch.** They used to print as they
  went, which meant embedding elenctic also meant taking its prose: the only way to quieten it was
  to take over your own process's streams, which costs you your own output and still leaves the
  run's records reachable only by reading the prose back. They now write to no stream. A caller that
  wants to see a long run happen passes `observer=`, and is told each verdict, plan and fault as it
  is established; every error and every verdict handed to the observer is the same object that comes
  back in the result, so a report rendered as the run goes and one rendered at the end cannot
  describe the same run differently. (Corpus hygiene is settled before the first case is reached and
  is read off the result rather than announced.) `RunObserver` and `PlanObserver` describe the
  shape; inherit one and every method you do not override does nothing, or implement all of them
  and pass any object that fits. What they announce is `corpus_unreadable`, `case_unusable`,
  `case_started`, `case_unjudged`, and then `case_judged` for a run or `case_planned` for a dry one
  — *judged* rather than *decided* because `UNDECIDED` is a verdict, so a case that reached one is
  a case elenctic decided about.

  **A fault in an observer cannot cost the run its records.** Announcing is a courtesy; establishing
  is the work. If your observer raises, the run continues, everything it had already established is
  still in the value it returns, and the fault is reported through elenctic's logger — silent until
  you configure logging, and never written to a stream. Without this, a renderer that failed on the
  third case of a hundred and thirty-five discarded all hundred and thirty-five, and the console
  entry reported your bug as elenctic's.

- **The package publishes where to report a bug**, in its metadata and in the one diagnostic that
  asks you to. `Homepage`, `Repository`, `Issues` and `Changelog` are now in the project metadata,
  and the backstop that meets a fault no register anticipated names the issue tracker instead of
  asking you to find it. The other diagnostic that asks you to report something — a harness fault
  against a single case — still names only the locus, `harness`, which is the word to search for.

- **`py.typed`.** elenctic is annotated throughout and checked under `mypy --strict`, and none of
  that reached anyone who installed it: without this marker a type checker skips the package
  entirely (PEP 561) and reports it as missing stubs. Every curated name is also marked as an
  explicit re-export, so `elenctic.run_corpus` type-checks under a strict configuration rather than
  being reported as not exported.

- **`--print-schema`** writes the JSON Schema of that document and exits, without looking for a
  corpus. The schema ships inside the package, so it describes the version you have rather than
  whatever a web page says. `schema_version` changes when a field is added or removed or a closed
  enumeration gains a member; the open-valued fields (`kind`, `solver`, a check's `tag`) may gain
  values without one; every `message` is opaque and may be reworded at any time.

- **A new error locus, `environment`,** for a fault in the machine a corpus was run on rather than
  in the corpus: a declared solver this installation does not have, and a copy of elenctic that
  cannot read its own packaged output description. The first was filed as `discovery` before, which
  was never quite true — the declared solver is checked per case while the run is under way, not
  during the corpus walk at all — and the published description of `discovery` had grown an "or the
  environment … including a declared solver that is not installed" to cover it. The second is new
  with `--print-schema` and has never been anything else. Nothing about a
  corpus would change if either fault were fixed, which is the line between the two. `kind` is
  open-valued, so this needs no `schema_version` change; `is_elenctic_bug` is `false` for it, so
  the exit status is what it was.

### Changed

- **Every diagnostic heading now names where the fault lies, not which part of elenctic met it.**
  A heading used to report the frame that noticed a problem, so one problem was announced under
  several names depending on how you happened to invoke the run. Here is the same file, with the
  same unresolvable `#include`, run as a corpus and run as a single target — before:

  ```
  CASE ERROR — cannot resolve the program (route.lp): route.lp:3:1-22: error: file could not be opened:
    shared.lp
  corpus error: cannot resolve the program (route.lp): route.lp:3:1-22: error: file could not be opened:
    shared.lp
  ```

  and now:

  ```
  PROGRAM ERROR — cannot resolve the program (route.lp): route.lp:3:1-22: error: file could not be opened:
    shared.lp
  program error: cannot resolve the program (route.lp): route.lp:3:1-22: error: file could not be opened:
    shared.lp
  ```

  Every heading is now built from one rule, so what a terminal calls `PROGRAM ERROR` is what a
  document calls `"kind": "program"` and nobody has to keep a table between the two views of one
  run. With the word settled by the locus, the one thing left varying is the case and the
  punctuation, and it says what the fault *cost* — which is what `scope` means in the document:
  capitals where the run went on and still produced a report, lower case where it stopped and there
  is none. Both are fields on the record.

  **All of these go to standard error**, as every diagnostic always has; standard output carries
  the report — the tally under `--format human`, the document under `--format json`. A job
  scraping standard output for these was never seeing them.

  **If a job matches on these lines, re-check it.** `CASE ERROR`, `SOLVER ERROR`, `corpus error:`
  and `internal error:` are no longer printed at all:

  | was | is now |
  | --- | --- |
  | `CASE ERROR — ` | `CONTRACT` / `DISCOVERY` / `PROGRAM ERROR — `, by locus |
  | `SOLVER ERROR — ` | `ENVIRONMENT ERROR — ` |
  | `corpus error: ` | `contract error: ` / `discovery error: ` / `program error: `, by locus |
  | `internal error: ` | `harness error: ` |
  | `DEADLINE — ` | `DEADLINE ERROR — ` |
  | `resource error: ` | unchanged |
  | `PROGRAM` / `RESOURCE` / `HARNESS ERROR — ` | unchanged |

  Of the unchanged ones, only `PROGRAM ERROR — ` is now printed where it was not before — when
  discovery, rather than the runner, is what met the program it could not load. Two headings are
  new rather than changed, so nothing matched them in 0.2.0: `ENVIRONMENT ERROR — ` and
  `environment error: `, which belong to the new locus below.

  `usage error:` is deliberately untouched, and it is the one line that is not in this scheme: a
  command line that cannot be run has produced no run and so no record, and a heading names a locus
  only where a fault is filed under one.

  What a heading does **not** yet settle is whether the line goes on to name the file. That still
  varies by locus *and* by which part of elenctic met the fault — a program that will not load is
  reported as `PROGRAM ERROR — <message>` when discovery meets it and `PROGRAM ERROR — <file>:
  <message>` when the runner does — and where a message already carries its own path, the path is
  printed twice. Deciding it means deciding where provenance lives, in the message or in the
  record's `source`, which changes what a library caller catching one of these sees. It is the
  remaining half of this, and it is not done.

- **A fault in elenctic now exits `3`, apart from a fault in your corpus.** Exit `2` meant both
  "your corpus has something to fix" and "elenctic violated one of its own invariants" — one status
  for the two things a reader can least afford to confuse, since one is work for them and the other
  is a bug to report. A harness fault is now `3`, and it outranks every other signal, because a
  harness that is wrong about one case is evidence about every other. Everything else that was `2`
  stays `2`: a bad contract, a mis-shaped corpus, a program that will not ground, a case that ran
  out of memory, a run that passed its `--deadline`, and corpus-health observations under
  `--strict`. A job gating on non-zero is unaffected; one testing for exactly `2` will stop seeing
  elenctic's own faults, which is the point.

- **A corpus-health observation now carries the grade the run gave it.** `HygieneRecord` — new in
  this release — carries a `grade`: `error` under `--strict`, and otherwise `warning` for an orphan
  library and `silent` for an undeclared solver — the footing each observation already had. What is
  printed, what fails the run, and what a consumer is told are now read off that one field rather
  than each deriving it
  again from the flag, so they cannot come to disagree about a single observation. Nothing a run
  prints changed.

  It is a *grade* and not a severity, deliberately. This language keeps the two vocabularies apart:
  its severity ladder runs from debug to critical and has no member meaning *do not show this*,
  because suppression there is a filter and not a level. A reader meeting a field called a severity
  maps it onto a scale of severities — which works for two of these three values and fails on the
  one whose whole purpose is that nothing be drawn for it.

- **`--budget` and `--deadline` now require a positive finite number of seconds.** Converting the
  text was as far as the parser went, so a zero, a negative, an infinity and a NaN were all accepted
  and all reached the run. The last two have no JSON form at all, so a report carrying one could not
  be parsed by anything it was written for; the first two are simply not durations. All four are now
  refused before the run starts, with a diagnostic naming the flag, the value and what to ask for
  instead. **`--deadline 0` used to mean "reach no cases"** and is now refused: a run that wants no
  deadline leaves the flag off, which is the default.

  **The rule holds for a caller who never parsed a command line, too.** `elenctic.outcome`'s
  `Invocation` refuses the same four at construction, raising `ValueError`, and refuses an absent
  budget on the same footing — a run with no deadline leaves the flag off, but there is no way to
  ask for no per-solve budget at all. It was previously enforced on the command line alone, while
  the published description of the output states it unconditionally as a property of the
  *document* — so building `Invocation(budget=0.0)` directly produced, without complaint, a report
  contradicting the account it is published under. Nothing the command line can do changes, because
  it refuses first and in its own words; code that builds an `Invocation` itself must pass a
  positive finite number of seconds, and `None` only for the deadline. `elenctic.outcome` also now
  exports `is_duration`, so that rule is one a caller can ask about rather than only discover.

- **The exit statuses are a named type, `elenctic.outcome.ExitStatus`.** The numbers are unchanged
  and so is everything a shell sees: it is an `IntEnum`, so it *is* an `int`, `sys.exit` takes it,
  and a caller comparing a status against a literal is unaffected. What changes is that the ladder is
  now the one place the rungs and their meanings are written, and `--help` is rendered from it —
  where before the same mapping was stated in six places and checked in one. Two of those
  statements were wrong: exit `0` was glossed as "every case passed", which is told to a reader who
  ran `--explain` and solved nothing, and exit `2` omitted a declared solver this environment does
  not have, which is the likeliest `2` a real user meets. `exit_status` and `main` return the type;
  compare a status read back from a child process with `==` rather than `is`, since what a process
  returns is a plain integer.

  The ladder and `exit_status` live with the registers they read rather than with the console entry,
  so reading a status is something an embedder can do: it is total and pure over what a run
  produced, asks nothing about a process, and needs no command line to have been parsed.

- **`--help` says what the run leaves with, and files each option under what it is for.** Nothing in
  the help mentioned the exit status — the whole of what a script reads — and the six options were
  one undifferentiated block holding two things that run something other than the corpus, one that
  says who the report is written for, and three that bound or sharpen the run. Both are now in the
  help. One consequence reaches beyond it: the usage line lists options in the order they are
  defined, so the usage printed with a command-line error now names `--print-schema` second rather
  than last.

- **A failure now names the contract line it judged, and repeated claims no longer repeat one
  sentence.** Every claim carries the line it was written on, so a diagnostic can be placed against
  the claim rather than against the file, and a tag a contract may write more than once is shown
  with the claim it carries. Where several claims failed for the same reason, the reason is stated
  once and the claims follow it:

  ```
    [FAIL] @cautious { tea } (line 10): { tea } ⊄ ⋂ AS(P) = { biscuit } (missing: { tea })

    [FAIL] @cautious: no cautious consequences — AS(P) = ∅
           applied to { tea } (line 10), { coffee } (line 11), { biscuit } (line 12)
  ```

  Anything reading this output by shape will need updating. Nothing about a verdict changed: the
  case verdict folds a set, so sharing a row cannot move it.

- **`@cautious`, `@brave`, `@cautious optimal` and `@brave optimal` may be written on more than one
  line**, and each line is now its own check with its own verdict and its own diagnostic. Writing
  the claims on one line remains equivalent — `L₁ ⊆ S` and `L₂ ⊆ S` together say exactly what
  `L₁ ∪ L₂ ⊆ S` says — but a failure now names which line was false instead of the union.

- **`Sat` and `Unsat` no longer construct without a line. This is a breaking change** for anyone
  building either directly. Both now require `expect_line`, and
  every contract cell but the prose one carries a `Claimed` value pairing what was claimed with the
  line it was claimed on — `@note` holds documentation rather than a claim, so it holds bare
  strings. `CheckReport` likewise gained the claim's subject, its line, and how the search
  behind the verdict ended. Code that builds these directly — rather than through `parse` and
  `run_case`, which is the ordinary path — must pass the coordinate.

- **The records a machine-readable report is built from are constructed by keyword. This is a
  breaking change** for anyone constructing one positionally. `CheckReport`
  and the new `CaseOutcome`, `ErrorRecord`, `HygieneRecord` and `RunOutcome` take their fields by
  name. A report's `message` and `subject` are neighbouring strings, so a transposed pair type-checks
  clean and renders a plausible row against the wrong claim; and a report is identified by field
  name wherever it is decoded, so position would be a second identity that a field added later
  silently re-means.

- **An invariant elenctic violated about its own result now raises `HarnessError`. This is a
  breaking change** for a caller catching `ValueError` around these. The empty cost
  vector on a proven optimum, the four consistent shapes built around an empty collection, and the
  non-empty-census precondition on a conjunctive query raised `ValueError`, which no per-case handler
  catches — so a result that could not be right ended the whole run and discarded every case still to
  come. It now costs one case its verdict, like every other fault the runner isolates. What a caller
  got wrong at a boundary is still `ValueError`: an unknown solver name, and the contract payloads a
  parse re-raises with the author's provenance.

- **Whether a search had to finish is now decided per check, not per run.** One solve serves
  several checks and they do not all ask the same thing: a census, an intersection, a union or a
  proven optimum is a claim about every member of a collection, so a search that stopped early
  makes it a claim about an arbitrary part — while `@expect sat` reads nothing from the collection
  and one model settles it whatever the rest of the search would have found. The requirement is
  derived from what each check declares it reads, so it cannot drift from the reading it protects.
  A reading that outran its search is still UNDECIDED, never FAIL and never a PASS it did not earn.

- **An undecided report now says which kind of not-knowing it met** — the solve settled nothing,
  or it settled satisfiability over a search that stopped short of covering what this check
  reads, or one that was cut short from outside. Raising a budget and shrinking what a case
  enumerates are different remedies, and the single previous message distinguished neither.

- **`Collection` is now imported from `elenctic.result`** rather than `elenctic.run`; it describes
  what a *field* is a reading of, so it belongs beside the field vocabulary. `elenctic.Collection`
  is unchanged — but **`from elenctic.run import Collection` no longer resolves**, which is a
  breaking change for anyone who reached past the curated surface for it.

### Removed

- **`HygieneReport.render` was removed. This is a breaking change** for anyone who called it —
  `HygieneReport` is exported, so it was reachable as `elenctic.inspect_corpus(target).hygiene`.
  What a run prints about corpus hygiene and what fails the run under `--strict` are now read off
  the same records the run reports, rather than from a second rendering of the same facts. The
  observations themselves are unchanged, and so is what elenctic itself prints. There is no
  drop-in replacement: read `RunOutcome.hygiene` and render the `HygieneRecord`s, each of which
  carries its `kind`, its `grade`, the file it concerns and its message.

### Fixed

- **A literal set whose body parses to nothing is refused, and refused as the author's mistake.**
  `@cautious { () }` — or any body that tokenizes to no atom at all — was silently dropped, so a
  contract that claimed something was checked for nothing and passed on that basis. Briefly it was
  then reported as an elenctic bug, which sent the wrong reader to the wrong place. It is now a
  contract error against the line that wrote it, naming what it read and what a litset needs, and
  it costs that case its verdict rather than the run:

  ```
  CONTRACT ERROR — empty.lp:2: empty literal set {()}: it parses to no literals at all, and a litset needs at least one (an atom or -atom)
  ```

- **A solve cut short by `--budget` no longer throws away the answer it did reach.** A cancelled
  search still reports whether the program is satisfiable; elenctic decided the run was undecided
  before reading that, so every check on it came back UNDECIDED — including checks the search had
  already settled. Any corpus whose search outlives its budget met this, so it was not a corner
  case but the ordinary behaviour of a hit budget.

  Before, on a program with 2^20 answer sets under `--budget 0.5`:

  ```
  case.lp [clingo] — UNDECIDED
    [UNDECIDED] @count: the solve did not settle the question — UNDECIDED, never FAIL
    [UNDECIDED] @expect sat: the solve did not settle the question — UNDECIDED, never FAIL
  ```

  After — the satisfiability question was answered, so it is answered, and the census question
  says why it was not and what would help:

  ```
  case.lp [clingo] — UNDECIDED
    [UNDECIDED] @count (line 2): the search was cut short before covering the collection this reads, so what it holds is part of the collection and not the collection — UNDECIDED, never FAIL. The per-solve time budget is what stops a search this way from the command line, so a larger --budget may decide it
  ```

- **An optimal-class run that could not finish enumerating no longer reports the program as having
  no answer set.** The optimal-class modes solve twice: prove the optimum, then enumerate at it.
  The second solve's "no model" answer was read as a statement about the program, when it is a
  statement about that solve — by then the first has already found a model, so the program is known
  to have an answer set. A case whose optimal class was too large to enumerate inside `--budget`
  therefore came back with every optimal-base tag reporting `AS(P) = ∅`, as a definite failure,
  contradicted in the same report by the `@expect sat` that passed. Such a case is now UNDECIDED —
  it could not be decided, which is what happened — so a corpus that used to fail here will report
  differently, and `@cost`, `@optimal`, `@cautious optimal`, `@brave optimal`, `@count optimal` and
  `@assign optimal` are the tags affected.

- **A solve cut short by `--budget` can no longer report that your program has no answer set.** A
  cancelled solve sometimes comes back carrying clingo's "unsatisfiable" and "exhausted" bits
  together — measured at two occurrences in 1,400 zero-budget solves of a program with 2^30 answer
  sets, under the single-model configuration as much as the enumerating one. Read literally, that
  says the search covered the space and found nothing. elenctic believed it, so a case whose solve
  ran out of budget could report `AS(P) = ∅` as a decided fact about a program with more answer sets
  than could be counted. Every model-bearing tag then failed, and `@expect unsat` — which rides its
  own single-model run, one of the two configurations this was measured in — **passed**, upholding a
  claim nothing had established.

  A search cut short from outside is now believed about what it *found* and never about what it
  *finished*. A model it produced is evidence a cancellation cannot take back, so a cut-short solve
  still reports the satisfiability it settled; covering the space is a claim only a search that ran
  to its own end can make, so neither "no answer set" nor "the space was covered" survives a
  cancellation. Cases that met this now report UNDECIDED, which is what happened.

## [0.2.0] - 2026-08-01

The minor bump is deliberate. Earlier releases changed what a *consumer* had to catch; this one can
change whether a *corpus that ran before still runs*. A case may now only load files from inside
the corpus the run was pointed at, so a corpus that reached outside it — absolutely, with `../`, or
through a symlink — is refused rather than read. Reaching up and across to a shared encoding
remains the ordinary shape of a corpus and is unaffected.

### Added

- **`--deadline`**, which bounds the whole run rather than one solve. `--budget` bounds a single
  solve; a case routes to as many as four, and a corpus has as many cases as it has files, so the
  cost of a run is a product of three numbers of which only one was bounded. Past the deadline the
  run stops dispatching and every case it did not reach is counted into the not-run register, so
  the corpus total stays the corpus total. It is off unless asked for: a default low enough to
  bound a hostile corpus would turn a large honest one into cases that could not be run.

### Changed

- **A defect in elenctic's own code is now reported as one.** A failure inside the AST walk or the
  solve reduction used to be translated into a program fault, which named the corpus author. Worse,
  it named *every* author: the same internal failure recurs for each case, so one defect in
  elenctic produced an accusation against every file in the corpus and a summary saying none of
  them passed.

  ```text
  # before, with a defect injected into elenctic's own solve reduction
  PROGRAM ERROR — alpha.lp: cannot run the program (alpha.lp): <the internal failure>
  PROGRAM ERROR — beta.lp: cannot run the program (beta.lp): <the internal failure>

  0/2 passed, 2 could not be run
  ```

  ```text
  # after
  internal error: this is an elenctic bug, not a fault in your corpus. Please report it
  with the traceback below.
  Traceback (most recent call last):
    ...
  ```

  Both exit `2`. The change costs the run rather than the case — the same trade the outermost
  handler already makes for every other unanticipated fault — and it is the right one here, because
  what the run would go on to produce is of unknown worth once elenctic is known to be broken. If
  you match on `PROGRAM ERROR` lines in CI, note that a class of them has moved.
### Fixed

- **A search that stopped early is no longer reported as a complete collection.** A solve settles
  two independent things — whether a model exists, and whether the search covered what was asked of
  it — and only the first was read. A truncated search still answers "satisfiable", so its partial
  census, intersection, union or optimum was reported as the whole collection. Measured on 8-queens
  under a conflict limit, an enumeration reported 17 of the program's 92 answer sets and a
  consequence run 20 of its 23 brave consequences — figures that move with the search rather than
  being properties of the program, which is itself the defect. The worst case is silent: an
  intersection taken over a prefix is a
  *superset* of the true one, so a `@cautious` contract naming a surplus atom **passed a false
  claim**. A reading that ranges over a whole collection now requires the search to have finished;
  a witness reading does not, and that exemption is necessary rather than merely permitted.

- **A fault names its true owner, and a remedy is offered only where it is the remedy.** elenctic
  divides faults by whose they are, and carries that division on the exception type — but clingo
  reports nearly everything through one channel, so the division was only as good as what each
  guarded region did with what it caught. Guarded regions now span code with a single owner rather
  than asserting one owner over several. Among what that fixed or exposed: a file name that is not
  UTF-8 was reported as an elenctic bug rather than as the corpus's; `#include` advice was appended
  to faults that had nothing to do with includes, sending authors to inspect paths that were fine;
  an objective that grounds away accused elenctic of a broken precondition; and a failure inside
  elenctic's own AST walk or solve reduction was reported as a program that cannot be run.

- **Programs that show a non-predicate term are no longer refused.** `#show "text" : p.` and
  `#show 42 : p.` are valid — clingo runs both — but elenctic rejected them as faults in the
  program. A symbol's name is defined only for a function symbol, and clingo raises when one is
  read off a string or a number rather than reporting that there is none, so the guard meant to
  cover that case could never fire.

- **The walk over a program no longer has a depth of its own to run out of.** The AST walk
  recursed once per level, so how deeply elenctic could read was bounded by the interpreter's
  stack while the depth is chosen by the program under test. A term nested past it was refused,
  though clingo grounds and solves such programs without complaint. Measured: the walk gave out on
  a left-nested arithmetic chain of 1 000 terms, a strong-negation chain of 1 000, and a list
  written as `cons(a, cons(b, …))` of **500** elements — nothing adversarial about the last, which
  nests one level per element. Both the node walk and the signature reader are iterative now.

- **Exhausting memory costs one case's result instead of the whole run's.** It was caught only at
  the outermost frame, so the run stopped there: no summary, no results for the cases that had
  already passed, and no indication of which case did it — while every other way a case can fail to
  run is reported against its own file and leaves the rest of the corpus running. There is now a
  per-case register for it, with the outermost handler kept as the backstop for an allocation that
  fails where no case owns it. Neither message asserts a cause it cannot know: grounding is the
  usual explanation, but a solve holds every model it is shown, so the memory may have gone there.

- **One unusable file costs only its own result at discovery, too.** The runner already isolated a
  case that failed to ground, but the walk that builds those cases had no such guard, so a file that
  could not be read, parsed or resolved raised straight out of discovery — and stdout came back
  empty, denying every other case its result. A corpus of one healthy case and one with an
  unresolvable `#include` printed nothing at all; it now names the bad file and reports
  `1/2 passed, 1 could not be run`.

- **An oversized diagnostic stays readable, and clingo's own diagnostics stay on one channel.** A
  check renders the set it judged against, and the program decides how large that is — a cautious
  reading over a large fact base is the whole fact base. Sets are now shown as a sorted prefix with
  the remainder counted, so the diagnostic is both bounded and stable across runs. Separately,
  clingo's term parser was called with no logger, so a malformed contract produced elenctic's
  friendly error *and* clingo's own on stderr; that text is now folded into the error being raised.

- **A resource the run exhausts is reported rather than dumped as a traceback**, and a fault that
  reaches the top frame says whose it is before printing one — the traceback is the report, and the
  sentence above it is what tells a user this is not theirs to fix.

### Security

- **A case may only load files from the corpus it belongs to.** `#include` resolution belongs to
  clingo, which opens whatever path it is handed, and nothing constrained what a case could hand
  it — so a corpus could name any file the process can read, absolutely, by climbing out with
  `../`, or through a symlink. What is read does not stay read, either: a contract that fails
  renders the model it was judged against, so a case that includes a file and then asserts
  something false about it publishes that file's contents through elenctic's own diagnostic.
  Containment is rooted at the directory the run was pointed at, not at the case's own, because
  reaching across to a shared encoding is the ordinary shape of a corpus.

- **Corpus-controlled text can no longer rewrite the report it appears in.** A case's path, its
  `@note` prose, the atoms in its answer sets and the solver's diagnostics about it all reached the
  terminal verbatim, and a terminal acts on some of that text rather than showing it — so a corpus
  could clear the screen, move the cursor, or overwrite a line just printed. Such text now passes
  through an escaping step: printable characters, spaces and newlines survive, anything else
  becomes a visible `\xNN`. Newlines are deliberately kept, since a solver diagnostic is
  legitimately multi-line; a newline can add a line but cannot conceal or overwrite one.

- **A solve is now bounded in memory as well as in time.** A solve holds every model it is shown,
  and the time budget says nothing about how fast they arrive — so a corpus could exhaust memory
  inside a budget that never expired, which made the advertised hang protection a bound on one
  resource presented as the bound. A model cap stops the search, on both the clingo and clingcon
  paths. It needs no verdict vocabulary of its own: a stopped search reports itself as not
  exhausted, and running out of room and running out of time are the same fact about knowledge.

- **The contract scanner finishes, and its lines are clingo's lines.** While a braced payload was
  open, every following line re-read the whole accumulated text and every continuation rebuilt it —
  two quadratics, the first running for each line in the file, all of it during the corpus walk and
  so upstream of every budget. A tag carrying ~24 KB followed by 40 000 ordinary lines took half a
  minute; it now takes a tenth of a second. Separately, the scan split on Python's notion of a line
  boundary — which includes `\v`, `\f`, the file/group/record separators, NEL, and the Unicode line
  and paragraph separators — while a clingo `%` comment runs to a newline. A single physical line
  could therefore carry a second contract tag that elenctic acted on and no reviewer could see.

## [0.1.3] - 2026-07-27

### Added

- **`SolverUnavailableError`** (`elenctic.SolverUnavailableError`), raised when a case declares a
  solver this environment does not have. It is deliberately both a `DiscoveryError` — a corpus
  naming an absent solver cannot be run — and an `ImportError`, which is what a missing optional
  dependency is in Python, so a caller following either convention catches it without knowing
  about the other. The same type is raised whether the condition is met through the corpus walk
  or through a direct `solve` call.

### Changed

- **`ProgramError` is no longer a subclass of `HarnessError`, and is now exported.** The
  inheritance asserted that a broken program under test is a kind of elenctic bug, which is
  false and is why a program that would not ground had no register to be routed to. The two are
  now disjoint roots: `ContractError`, `DiscoveryError` and `ProgramError` are the author's to
  fix, `HarnessError` is elenctic's. **This is a breaking change** for any consumer that caught
  program faults via `HarnessError`; catch `elenctic.ProgramError` instead.

- **The exit status `2` now covers a program that cannot be run**, alongside a bad contract, a
  mis-shaped corpus and an internal error. No status changed meaning; the register gained a
  member.
### Fixed

- **A program that cannot be run is reported, instead of crashing the run.** A program that
  parses but fails to ground — an unsafe variable is the usual cause — cleared discovery and
  then died at solve time as an unhandled error, aborting the whole run. Every case that had
  already passed lost its result too, because the summary line was never reached, so the run
  produced no output at all and exited with the status that means *a case was tested and
  decided wrong*. Such a program is now reported as a `ProgramError` naming the offending file
  and line with clingo's own diagnostic, the remaining cases still run, and the run exits in
  the error register. A program that will not ground is never reported as unsatisfiable: its
  answer sets are undefined, not empty, and conflating the two would silently pass an
  `@expect unsat` contract written against a broken program.

- **A declared solver that is not installed is reported, instead of crashing the run.** A case
  declaring `@elenctic solver clingcon` in an environment without clingcon failed on the import
  inside the solver, at the latest possible moment. It is now checked before the case is
  solved and reported against that case with the command that fixes it. Only the cases that
  declare the missing solver are affected; the rest of the corpus still runs, and `--explain`,
  which never reaches a solver, does not require one to be installed.

- **A solve that completes without deciding is `UNDECIDED`.** clingo's solve result is
  three-valued — satisfiable, unsatisfiable, or unknown — but the result was read as two bits,
  so a search that gave up fell through to the satisfiable branch and every mode then failed
  trying to build an answer out of an empty search: as an internal error, as a false claim that
  the program has no answer sets, or as a report that an encoding lacks the objective it
  visibly has. One reduction now reads the result, at every solve site, including both phases
  of the optimal-class enumeration — whose second phase previously discarded its result
  entirely.

- **An internal fault during a solve is no longer reported as a fault in the program under
  test.** Driving a solve asynchronously, clingo does not re-raise an exception from a model
  callback unchanged: it arrives as a plain error carrying only the message. Since the new
  ground/solve boundary reads such an error as a fault in the program, elenctic's own failures
  are now recorded before that erasure and re-raised intact — on both the normal and the
  cancelled path, the latter of which would otherwise have reported an internal bug as the
  verdict `UNDECIDED`.

## [0.1.2] - 2026-07-16

### Added

- **`Collection` (`elenctic.Collection`) — what a reading ranges over**: AS(P), Opt(P), or one
  answer set, readable as `Mode.asks`. It is *derived* from the fields a mode populates,
  not declared beside them, so a mode cannot claim one collection while reading another's.
  Each mode now states the optimization its collection requires instead of inheriting the
  solver's default, and a gating test holds every mode to it.
### Fixed

- **The AS(P) tags now mean AS(P) on an optimizing encoding.** clingo optimizes by
  default, so on an encoding carrying an objective (`#minimize`, `#maximize` or `:~`) an
  enumerating solve reported only clingo's branch-and-bound *improving sequence*: the
  models the search passed through on its way to the optimum. That sequence is neither
  AS(P) nor Opt(P), and it moves with the search heuristic, so every tag whose reading
  ranges over AS(P) quietly answered a different question:
  - `@count` reported a wrong number;
  - `@model` and `@brave` rejected genuine answer sets (a false `FAIL`);
  - `@cautious` admitted atoms that are not cautious consequences, and `@query` returned
    a wrong three-valued answer. Both of these **passed a false claim**.

  The `* optimal` family (`@cost`, `@optimal`, `@count optimal`, `@cautious optimal`, and
  the rest) was never affected, because it states its optimization explicitly. `@expect`
  is likewise unaffected: satisfiability does not depend on an objective.

  **On upgrading:** a contract that passed under 0.1.1 may now fail. Where it does, the
  earlier `PASS` was unsound and the new verdict is the true one. A bare `@count` on a
  large optimizing encoding now enumerates all of AS(P), so it may reach the time budget
  and report `UNDECIDED` instead of a fast wrong number.

- **A bare AS(P) tag over a theory-native objective is now refused, not answered.**
  `--opt-mode=ignore` switches off clingo's optimize statements; clingcon's `&minimize` /
  `&maximize` is driven by the theory's own propagator, which no clingo setting reaches.
  Such an encoding also produced no `#minimize` node, so it read as objective-free and
  passed every precondition, leaving `@cautious` and friends to answer from a search
  pruned to the optimum. Theory-native optimization stays outside v1, but the exclusion is
  now **loud**: discovery reports a corpus error (exit 2) naming the fix, rather than a
  quiet wrong verdict.

## [0.1.1] - 2026-06-26

The first tagged release. **elenctic** is a declarative testing framework for Answer
Set Programming: you write in-file `@`-contracts over the *observable* of an answer-set
program (its shown atoms and theory assignment), and elenctic discovers, runs, and
checks them across clingo and clingcon, reporting a three-valued verdict
(PASS / FAIL / UNDECIDED) that never conflates a timeout with a refutation.

Highlights of the initial release:

- **Contracts over the observable:** `@expect`, `@model`, `@cautious` / `@brave`,
  `@count`, `@cost`, `@optimal` (and the optimal-base family), `@assign` (theory / CSP),
  the three-valued `@query` (Gelfond–Kahl Def 2.2.2, errata-corrected), and `@note`.
- **Content-keyed discovery:** a file is a *case* iff it carries a contract tag;
  dependencies are declared with `#include`; the solver is declared with
  `@elenctic solver` (default `clingo`). A `--strict` dial gates corpus hygiene, and
  `--explain` narrates the run plan, led by the `@note` gloss.
- **clingo and clingcon backends,** with a projection-aware theory path for CSP
  observables.
- **Standalone runner** (`elenctic <path>`) and an importable library API; each
  pipeline stage also runs under `python -m elenctic.<stage>` for inspection.

This release also makes every in-source comment self-contained for external
contributors, single-sources the version from `elenctic.__version__`, and runs CI on
Linux and macOS.

[Unreleased]: https://github.com/GregoryGelfond/elenctic/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/GregoryGelfond/elenctic/releases/tag/v0.3.0
[0.2.0]: https://github.com/GregoryGelfond/elenctic/releases/tag/v0.2.0
[0.1.3]: https://github.com/GregoryGelfond/elenctic/releases/tag/v0.1.3
[0.1.2]: https://github.com/GregoryGelfond/elenctic/releases/tag/v0.1.2
[0.1.1]: https://github.com/GregoryGelfond/elenctic/releases/tag/v0.1.1
