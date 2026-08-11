# Using elenctic as a library

**For:** anyone embedding elenctic in a runner of their own. Assumes you have read
[The machine-readable report](machine-readable-output.md) if you plan to emit one.

The command line is a derivation of the library, not the other way round: it parses an invocation,
runs it, renders what comes back, and reads a status off it. Every one of those steps is a call you
can make yourself, so elenctic's results can go into a runner of your own, a CI script, or an
editor plugin without shelling out and parsing prose.

**The library is silent.** Nothing below prints; you supply an observer if you want to watch a run
as it goes, and the announcements hand you *records* rather than strings, so nothing you display
has to be re-derived from a sentence elenctic wrote.

```python
from pathlib import Path

import elenctic


class Watching(elenctic.RunObserver):
    def case_started(self, case: elenctic.Case) -> None:
        print(f"running {case.contract_source.name}")

    def case_judged(self, outcome: elenctic.CaseOutcome) -> None:
        print(f"  {outcome.verdict.value}")


invocation = elenctic.Invocation(target=Path("encodings"))
outcome = elenctic.run_corpus(invocation, observer=Watching())

Path("report.json").write_text(
    elenctic.dumps(elenctic.as_json(outcome, invocation)), encoding="utf-8"
)
raise SystemExit(elenctic.exit_status(outcome))
```

`elenctic.RunObserver` is a protocol with a do-nothing body for every announcement, so **inheriting
it** lets you override only what you care about — as above. Implementing it *structurally*, without
inheriting, means supplying every member: a protocol's default bodies are inherited, never
conjured. The announcements are `corpus_unreadable`, `case_unusable`, `case_started`,
`case_unjudged`, and then `case_judged`. **A fault in your observer costs the run nothing**: it is
reported through a module logger and the records are unaffected, because in a CI job or an editor
the records are the deliverable and the channel an observer writes to is the part that fails.

`elenctic.Invocation` carries the same three dials the command line does, with the same defaults, so
only the target has to be given: `strict=False`, `budget=elenctic.TIME_BUDGET` (the constant behind
`--budget`), and `deadline=None`. All four are keyword-only.

`elenctic.explain_corpus` is the same shape for the dry run — it takes the same
`elenctic.Invocation`, announces `case_planned` through an `elenctic.PlanObserver`, and returns an
`elenctic.PlanOutcome`. `elenctic.exit_status` is total over both.

For one case at a time rather than a corpus: `elenctic.discover` yields cases, `elenctic.run_case`
yields the per-check reports, `elenctic.case_verdict` folds them, and `elenctic.render` formats the
diagnostic — which is what you want to drive `pytest.mark.parametrize` with.

`elenctic.discover` gives you the cases and nothing else, and raises on any file it could not turn
into one. When you want corpus hygiene as well, call `elenctic.inspect_corpus`: it walks once and
hands back an `elenctic.Corpus`, whose `cases` are the same, whose `hygiene` is an
`elenctic.HygieneReport` — its `clean` says whether the corpus carried any health observation at
all, the raw detection state before any invocation grades it — and whose `unrunnable` carries the
files that could not be made into cases, paired with why. That last field is what lets a runner
report a broken file and still run the rest of the corpus, which is what the command line does.

## What a fault says, and what you may rely on

**An exception's text is opaque — display it, do not parse it, and expect its wording to change.**
That is the same footing the machine-readable report puts its `message` field on, said here because
a library caller never reads that document and had no way to know the rule applied to them too.

What is *not* opaque is the parts. `elenctic.ContractError` and `elenctic.DiscoveryError` carry
`.reason` — what is wrong, without the coordinate — and `.line`, the contract line it is wrong on,
or `None`. `elenctic.error_detail` reads both off any fault, including the ones that carry neither,
and `elenctic.error_kind` reads the locus off its class. Between them a runner of your own builds
the same `elenctic.ErrorRecord` the shipped one does, without recovering anything from a sentence.

The file is deliberately not among them: a fault states the provenance its caller could not already
know, and the caller is the one who passed the file in.

**And the surface all of that is a promise about is `import elenctic`.** The names it reaches — the
package's own `__all__`, which is also what `dir(elenctic)` shows you — are the supported API: a
release that changes only its patch number, 0.4.0 to 0.4.1, will not remove one, change its
signature, or alter what it means. It may still fix a defect, and a fix changes behaviour; what it
will not do is break code written against the surface. Breaking changes are held for a minor bump,
and each is described in the [changelog](../CHANGELOG.md) under the release that makes it.

Everything else is internal **to import**, *including* the names a submodule exports without a
leading underscore. `elenctic.checks.count_is`, `elenctic.result.ConsistentWitness` and
`elenctic.solvers.run_clingo` are all real and all reachable; reach for one if you need it, and do
not expect it to still be there after an upgrade.

*To import* is the operative phrase, because elenctic has a second surface and the same promise
covers it: the command line. `elenctic run|explain|schema` and the four
`python -m elenctic.<stage>` inspection entries described in [Running a corpus](running.md) are
user-facing, and a patch will not break a command line that worked — the module a stage is spelled
with is part of how you invoke it, not a name you imported.

elenctic ships `py.typed`, so all of this is typed for whatever checker you run.

