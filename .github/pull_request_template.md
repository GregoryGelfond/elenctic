<!--
Thanks for the patch. CONTRIBUTING.md has the conventions this is read against; the short version
is below. Delete anything that does not apply — this is a prompt, not a form.
-->

## What this changes, and what it is for

<!-- If it changes behaviour, show the before and the after. -->

## Checklist

- [ ] `pixi run check` is green locally (ruff + `mypy --strict` + pytest — the whole gate, and
      exactly what CI runs)
- [ ] A changelog entry under `[Unreleased]`, if the change is visible to anyone using elenctic.
      Write for someone deciding whether to upgrade, rather than summarising the diff — and if it
      moves anything a script might match on, say so plainly and give the before and after
- [ ] A test, if this fixes a bug. A small patch with a failing test attached is easier to take
      than a large one without
- [ ] No assistant or editor configuration in the diff — no `.claude/`, `.serena/`, `.cursor/` or
      the equivalent, no session transcripts, generated plans or working notes

<!--
Using an AI assistant is fine, for any part of it, and there is nothing you need to disclose. The
one thing that does not change is that the contribution is yours: you are the one vouching for it.
-->
