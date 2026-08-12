# The machine-readable report

**For:** anyone consuming elenctic's output from a program — a CI job, a dashboard, an editor
plugin. Assumes you have read [Running a corpus](running.md).

`--format json` writes the whole run as **one JSON object on standard output**, and moves everything
else — the per-case report, the hygiene summary, every diagnostic — to standard error. Standard
output carries a whole document or nothing at all, so a consumer can parse it without filtering.
**Closing standard error is honoured as "discard the diagnostics" rather than paid for by the
document**: `elenctic run tests/ --format json 2>&-` writes the same bytes on standard output as
`2>/dev/null` does, and a reader that stops reading — a pipe into `head`, a pager you quit — leaves
the run with its own exit status and one sentence about the truncation, not a traceback.
## A worked run

The example below runs this case, which claims that every answer set contains `tea` — and it
does not, because exactly one of `tea` and `coffee` is chosen:

```asp
% @elenctic solver clingo
% @expect sat
% @cautious { tea }

1 { tea; coffee } 1.
#show tea/0.
#show coffee/0.
```

```console
$ elenctic run menu.lp --format json
{
  "schema_version": 2,
  "invocation": {
    "target": "menu.lp",
    "strict": false,
    "budget": 30.0,
    "deadline": null
  },
  "summary": {
    "total": 1,
    "passed": 0,
    "failed": 1,
    "undecided": 0,
    "errors": 0,
    "hygiene": 0
  },
  "cases": [
    {
      "source": "menu.lp",
      "solver": "clingo",
      "verdict": "fail",
      "checks": [
        {
          "tag": "@cautious",
          "subject": "{ tea }",
          "status": "fail",
          "message": "{ tea } ⊄ ⋂ AS(P) (observed { }; missing { tea })",
          "line": 3,
          "conclusion": "exhausted"
        },
        {
          "tag": "@expect sat",
          "subject": "",
          "status": "pass",
          "message": "AS(P) ≠ ∅ — a model exists",
          "line": 2,
          "conclusion": "incomplete"
        }
      ]
    }
  ],
  "errors": [],
  "hygiene": []
}
```

## Reading the document

**Three registers, and confusing them is the one mistake worth guarding against.** A case in `cases`
received a judgment about the program under test. An entry in `errors` says *no* judgment could be
made, and why — usually not a fault in the contract at all. An entry in `hygiene` is an observation
about the corpus's own health and is neither. Draw a failure indicator for a non-passing case; never
for an error.

**The exit status is readable off the document alone**, in this order: `3` if any error has
`is_elenctic_bug` true; otherwise `2` if there is any error at all, or any observation graded
`error`; otherwise `1` if any case's verdict is not `pass`; otherwise `0`.

**Each check carries the line its claim was written on**, 1-based, so a result can be placed where
the claim is rather than against the file. `conclusion` says how the search behind the verdict
ended, which is what tells "the budget was too small" apart from "the program is wrong".

**An error carries where it is in the same two fields, and says it in no other way.** `source` is the
file, `line` is the 1-based contract line within it — or `null` where the fault is about no single
line, which is most of them: a program that will not ground, a corpus that could not be read, a
deadline the run passed. Read those two; **do not recover a path by parsing `message`**, which no
longer states one. What a `message` may still contain is the *solver's* own `file:line:column`,
quoted as the solver wrote it, because that says where in the *program* the fault is and nothing
else does.

**A `message` is always one line**, whatever the solver wrote. A diagnostic that ran to several
arrives with each break escaped as `\x0a`, on the same footing as every other character a reader's
tooling would act on rather than display. The human report re-emits those breaks under a mark of
its own; a document has no layout to re-emit them into, so it carries them as text.

## What you may rely on across versions

**Three tiers of change, so you know what you may rely on.** `schema_version` changes when a field is
added or removed, or when one of the closed enumerations (`verdict`, `status`, `conclusion`,
`scope`, `grade`) gains a member. The open-valued string fields — `kind`, `solver`, and a check's
`tag` — may gain values *without* a version bump, so treat an unfamiliar one as a value rather than
an error. Every `message` is **opaque**: display it, do not parse it, and expect its wording to
change.

**And when a bump can reach you.** The document is a surface like the importable one, held to the
same rule: `schema_version` never changes in a release that changes only its patch number, because a
reader written against one version is code and a patch may not break code. A bump is held for a
minor release, and the release that makes it says so. Note that *every* bump is breaking, whatever
moved: the description above pins the version as a constant, so a validating consumer refuses an
unfamiliar number outright rather than tolerating an added field. `schema_version` went from 1 to 2
between 0.3.0 and 0.4.0, which is the change this release's changelog describes.

So a consumer has two ways to be safe and both are cheap. Pin a minor version and the document's
shape is fixed for every patch under it. Or read `schema_version` out of the document — it is the
first field for that reason — and refuse a number you were not written for, which is better than
inferring the shape from whichever fields you happen to find.

Paths in the document follow the target as you named it, so a relative target yields relative paths;
resolve them against the directory you ran from, which the document does not record.

## The schema, and what is refused

`elenctic schema` writes the JSON Schema of this document and exits, without looking for a corpus.
Two things are refused rather than guessed at: a `--format` this version does not know, and a
`--budget` or `--deadline` that is not a positive finite number of seconds. A dry run has no
machine-readable form in this version, and that is now said by the grammar rather than refused:
`--format` is one of `run`'s options, and `elenctic explain` has none. A refused command line
produces **no** document, so check the exit status before parsing — and note that `elenctic schema`
puts the *schema* on that stream, which parses as JSON and has none of the fields above.

Redirecting standard error onto standard output (`--format json 2>&1`) gives away the guarantee by
your own hand, and it is now the only way to: closing standard error costs the document nothing, so
`2>&-` and `2>/dev/null` are two spellings of one wish and behave alike.

## Closing a stream

**Closing a stream is read as "discard what goes there", and the two streams answer differently
because what they carry differs.** Closing standard error discards the diagnostics and costs the
report nothing. Closing standard *output* discards the report — `elenctic run tests/ >&-` and
`elenctic explain tests/ >&-` run to completion and leave with the status they would have left with
anyway, `0`, `1` or `2` as the corpus decides, so a caller reading only the status is unaffected.

The exception is the pair whose whole purpose is an artefact on that stream: `run --format json`
and `schema` are **refused**, with a usage error and status `2`, when the process has no standard
output. Those two have nothing left to do, and the alternative is the one outcome that misleads —
producing nothing, on both streams, under a status that says nothing went wrong. It is a refusal
rather than a guess for the same reason the other two are: elenctic will not decide on your behalf
where a document you asked for should go.

