"""Case discovery — the pure, total corpus walk parameterized by a ``Layout`` (spec §5).

``discover(layout)`` reads a corpus tree and produces one :class:`Case` per *(instance × applicable
encoding)*: the clingo baseline and, when present, the ``-clingcon`` variant, each checked against
the instance's single contract. A **self-contained** encoding (no instances) is its own case, its
contract in the encoding header. **Flatness is detected structurally** — a domain with no
``variant-NN`` subdir pairs its instances with the domain's encoding(s); a ``variant-NN`` dir pairs
with the matching ``…-variant-NN[-clingcon]`` encoding — so no domain is a named special case (RR8).

Discovery is where the §2.2-rule-4 **preconditions that need the encoding** are enforced as loud
errors: an ``optimal`` base or ``@cost``/``@optimal`` needs an optimizing encoding
(``#minimize``/``#maximize``/``:~``); ``@assign`` needs a theory solver (clingcon); a ``no``/
``unknown`` ``@query`` needs the relevant *contrary* literal in the shown vocabulary (§2.0). It is
**total**: a ``.lp`` file matching no convention is handled per ``Layout.on_unmatched`` (a loud
error by default, or skip-with-log). The :class:`Case` is **provenance-rich** (dx#2): it carries the
parsed :class:`~elenctic.expectation.Expectation` (notes intact) and ``contract_source``, so a later
renderer or docs tool reads the case without re-parsing. Pure over the tree (filesystem reads and a
skip log are its only effects); only ``solvers.py`` touches a solver.

Two v1 boundaries are deliberate and recorded in the dev-diaries ledger, not silent: (1) the shown
vocabulary is keyed by sign-aware **name**, not ``(name, arity)`` — an arity mismatch on a contrary
surfaces downstream as a *loud* ``@query`` FAIL, never a silent wrong PASS (an unshown contrary can
never enter ⋂/⋃), and a faithful arity-aware reader wants a real ASP parser robust to clingcon
theory syntax; (2) only the §2.2-rule-4 *contrary* precondition is gated here — the broader §2.0/RR9
"every positive literal in the shared shown vocabulary" precondition is deferred (an unshown
positive literal also fails loudly downstream, never wrong-passes).
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from clingo import Symbol

from elenctic.expectation import Expectation, Sat, parse
from elenctic.query import Answer, BindingQuery, GroundQuery, Query, QueryLiteral
from elenctic.terms import contrary

__all__ = ["Case", "DiscoveryError", "Layout", "Solver", "discover"]

_log = logging.getLogger(__name__)

# A #show declaration names a predicate in the signature form (`#show p/1.`) or the conditional-term
# form (`#show p(X) : body.` and the 0-ary `#show p : body.`, dx#5); the bare `#show.` names none. A
# strong negation (`-reachable`) is a distinct shown atom (§2.0), so the captured name is signed.
_SHOW = re.compile(r"^\s*#show\s+(?P<name>-?[a-z_][A-Za-z0-9_']*)\s*(?:/\s*\d+|\(|:)", re.M)

# An optimizing construct: a #minimize/#maximize directive, or a :~ weak constraint (§2.2 rule 4).
_OPTIMIZE = re.compile(r"#(?:minimize|maximize)\b|:~")

# A variant subdirectory (`variant-03`), the structural flatness signal (spec §5).
_DEFAULT_VARIANT_DIR = re.compile(r"variant-\d+")

type Solver = Literal["clingo", "clingcon"]


class DiscoveryError(Exception):
    """A corpus that violates a discovery-time precondition (§2.2 rule 4) or holds a ``.lp`` file
    matching no convention under ``on_unmatched="error"`` (spec §5). Loud by design — discovery
    never silently drops a case."""


@dataclass(frozen=True, slots=True)
class Layout:
    """Where a corpus lives and how its structure is read — the single value that parameterizes
    discovery so it hard-codes nothing about any corpus (spec §5, RR8).

    ``encodings_root`` holds ``<domain>/`` encoding files; ``cases_root`` holds
    ``<domain>/[variant-NN/]`` instances. A filename ending ``clingcon_suffix`` is the clingcon
    variant, else the clingo baseline. ``variant_dir`` matches the structural-flatness subdir.
    ``on_unmatched`` governs a ``.lp`` file matching no convention: a loud ``DiscoveryError``
    (default) or a logged skip.
    """

    encodings_root: Path
    cases_root: Path
    clingcon_suffix: str = "-clingcon"
    variant_dir: re.Pattern[str] = _DEFAULT_VARIANT_DIR
    on_unmatched: Literal["error", "skip-with-log"] = "error"


@dataclass(frozen=True, slots=True)
class Case:
    """One *(encoding, instance?, solver)* triple with its parsed contract and shown vocabulary.

    ``instance`` is ``None`` for a self-contained encoding. ``shown`` is the sign-aware shown
    predicate vocabulary (e.g. ``{"reachable", "-reachable"}``), the §2.0 precondition surface.
    Provenance-rich (dx#2): the parsed ``expectation`` keeps its ``notes``, and ``contract_source``
    names the file the contract came from, so a renderer or docs tool reads the case without
    re-parsing. ``files`` and ``contract_source`` are derived, not stored — single source of truth.
    """

    encoding: Path
    instance: Path | None
    solver: Solver
    expectation: Expectation
    shown: frozenset[str]

    @property
    def contract_source(self) -> Path:
        """The file the contract was parsed from: the instance when paired, else the self-contained
        encoding (dx#2 provenance)."""
        return self.instance if self.instance is not None else self.encoding

    @property
    def files(self) -> tuple[Path, ...]:
        """The grounding load order the facade feeds a solver: the encoding, then the instance when
        paired (spec §5)."""
        return (self.encoding,) if self.instance is None else (self.encoding, self.instance)


def discover(layout: Layout) -> tuple[Case, ...]:
    """Discover every *(instance × applicable encoding)* case under ``layout`` (pure, total; §5).

    Encodings and instances are grouped by domain (the first path component under each root); each
    domain's cases are derived together. Output is deterministic (domains sorted, files sorted
    within each). Raises :class:`DiscoveryError` on a precondition violation or an unmatched ``.lp``
    (unless ``on_unmatched="skip-with-log"``); a malformed contract surfaces the sourced
    :class:`~elenctic.expectation.ContractError` from ``parse`` (provenance already attached).
    """
    encodings = _by_domain(layout.encodings_root)
    instances = _by_domain(layout.cases_root)
    cases: list[Case] = []
    for domain in sorted(encodings.keys() | instances.keys()):
        cases.extend(
            _domain_cases(domain, encodings.get(domain, ()), instances.get(domain, ()), layout)
        )
    return tuple(cases)


def _by_domain(root: Path) -> dict[str, tuple[Path, ...]]:
    """Group the ``.lp`` files under ``root`` by domain (their first path component), sorted."""
    if not root.exists():
        return {}
    grouped: dict[str, list[Path]] = {}
    for path in sorted(root.rglob("*.lp")):
        domain = path.relative_to(root).parts[0]
        grouped.setdefault(domain, []).append(path)
    return {domain: tuple(paths) for domain, paths in grouped.items()}


def _domain_cases(
    domain: str, encodings: tuple[Path, ...], instances: tuple[Path, ...], layout: Layout
) -> list[Case]:
    """The cases for one domain: self-contained encodings if no instances, else each instance paired
    with its applicable encoding(s). An instance with no encoding is unmatched (spec §5)."""
    if not encodings:
        for instance in instances:
            _unmatched(instance, f"domain {domain!r} has no encoding", layout)
        return []
    if not instances:
        return [_make_case(encoding, None, layout) for encoding in encodings]
    cases: list[Case] = []
    for instance in instances:
        applicable = _encodings_for(instance, encodings, layout)
        if not applicable:
            _unmatched(instance, "no encoding matches its variant", layout)
            continue
        cases.extend(_make_case(encoding, instance, layout) for encoding in applicable)
    return cases


def _encodings_for(instance: Path, encodings: tuple[Path, ...], layout: Layout) -> tuple[Path, ...]:
    """The encoding(s) an instance pairs with: every domain encoding when flat, else the encodings
    whose stem matches the instance's ``variant-NN`` at a name boundary (dx#7), spec §5."""
    variant = _variant_of(instance, layout)
    if variant is None:
        return encodings
    return tuple(e for e in encodings if _matches_variant(e, variant, layout))


def _variant_of(instance: Path, layout: Layout) -> str | None:
    """The ``variant-NN`` directory governing an instance, or ``None`` for a flat domain (§5)."""
    parts = instance.relative_to(layout.cases_root).parts
    return next((part for part in parts if layout.variant_dir.fullmatch(part)), None)


def _matches_variant(encoding: Path, variant: str, layout: Layout) -> bool:
    """Whether ``encoding`` is the ``…-variant-NN[-clingcon]`` encoding for ``variant`` — a boundary
    match (``variant-1`` never matches ``variant-10``), the dx#7 fix over a substring test."""
    core = encoding.stem
    if core.endswith(layout.clingcon_suffix):
        core = core[: -len(layout.clingcon_suffix)]
    return core == variant or core.endswith(f"-{variant}")


def _unmatched(instance: Path, reason: str, layout: Layout) -> None:
    """Handle a ``.lp`` file matching no convention per ``layout.on_unmatched`` (total, spec §5)."""
    message = f"{instance}: matches no encoding convention ({reason}) — spec §5"
    if layout.on_unmatched == "error":
        raise DiscoveryError(message)
    _log.warning("skipping unmatched case — %s", message)


def _make_case(encoding: Path, instance: Path | None, layout: Layout) -> Case:
    """Build one case: parse the contract (with provenance), read the shown vocabulary, fix the
    solver, and enforce the §2.2-rule-4 preconditions before the case is admitted."""
    encoding_text = encoding.read_text(encoding="utf-8")
    if instance is None:  # self-contained: the contract is the encoding header
        contract_text, contract_source = encoding_text, encoding
    else:
        contract_text, contract_source = instance.read_text(encoding="utf-8"), instance
    expectation = parse(contract_text, source=str(contract_source))
    # Scan comment-free code so a #show/#minimize mentioned only in prose cannot satisfy a gate.
    encoding_code = _strip_comments(encoding_text)
    shown = _shown_predicates(encoding_code)
    solver: Solver = "clingcon" if encoding.stem.endswith(layout.clingcon_suffix) else "clingo"
    _check_preconditions(expectation, encoding_code, shown, solver, contract_source)
    return Case(encoding, instance, solver, expectation, shown)


def _strip_comments(text: str) -> str:
    """Blank out ASP comments (``%``-to-EOL and ``%* … *%`` blocks) so the ``#show``/optimization
    scans see only active directives, never a token in prose — a ``#minimize`` in a comment must not
    satisfy the optimization precondition (the fail-open soundness gap). Quote-aware: a ``%`` in a
    double-quoted string term is not a comment. Newlines are preserved, so the line-anchored
    :data:`_SHOW` regex still reads one directive per line."""
    kept: list[str] = []
    index = 0
    in_quote = False
    in_block = False
    while index < len(text):
        char = text[index]
        pair = text[index : index + 2]
        if in_block:
            in_block = pair != "*%"
            index += 1 if in_block else 2
        elif in_quote:
            kept.append(char)
            in_quote = char != '"'
            index += 1
        elif pair == "%*":
            in_block = True
            index += 2
        elif char == "%":
            newline = text.find("\n", index)
            if newline == -1:
                break  # a trailing line comment to EOF: nothing of substance remains
            index = newline  # keep the newline itself (appended on the next iteration)
        else:
            in_quote = char == '"'
            kept.append(char)
            index += 1
    return "".join(kept)


def _shown_predicates(encoding_code: str) -> frozenset[str]:
    """The sign-aware shown predicate names declared by the encoding's ``#show`` directives (§2.0).
    Recognises the signature (``p/1``) and conditional-term (``p(X) : body``, ``p : body``) forms;
    bare ``#show.`` contributes none. ``encoding_code`` is comment-stripped (in :func:`_make_case`),
    so a commented-out ``#show`` does not pollute the vocabulary."""
    return frozenset(match.group("name") for match in _SHOW.finditer(encoding_code))


def _check_preconditions(
    expectation: Expectation, encoding_code: str, shown: frozenset[str], solver: Solver, where: Path
) -> None:
    """Enforce the §2.2-rule-4 preconditions that need the encoding (spec §5): optimization, a
    theory solver for ``@assign``, and a shown contrary for a ``no``/``unknown`` ``@query``. Loud;
    ``@expect unsat`` carries no model-bearing tag, so it has nothing to check. ``encoding_code`` is
    comment-stripped, so a ``#minimize`` in prose cannot satisfy the optimization gate."""
    if not isinstance(expectation, Sat):
        return
    if expectation.requires_optimization and not _OPTIMIZE.search(encoding_code):
        raise DiscoveryError(
            f"{where}: @cost/@optimal/an optimal-base tag needs an optimizing encoding "
            "(#minimize/#maximize/:~), but the encoding has none (spec §2.2 rule 4)"
        )
    if expectation.requires_theory and solver != "clingcon":
        raise DiscoveryError(
            f"{where}: @assign reads the theory half of the observable, so it needs a theory "
            f"solver (clingcon), not {solver} (spec §2.2 rule 4)"
        )
    for query in expectation.queries:
        if missing := _contraries_needed(query) - shown:
            names = ", ".join(sorted(missing))
            raise DiscoveryError(
                f"{where}: a no/unknown @query reads the contrary literal(s) {names} off the shown "
                f"⋂/⋃, but they are absent from the shown vocabulary {sorted(shown)} "
                "(spec §2.0/§2.2 rule 4)"
            )


def _contraries_needed(query: Query) -> frozenset[str]:
    """The sign-aware shown names a query reads as *contraries* off ⋂/⋃, which must therefore be
    shown (§2.2 rule 4):

    - a ground ``no``/``unknown`` query needs **every** conjunct's contrary. Under the corrected ∀∃
      "no" (each model may falsify a *different* conjunct, §2.1), any conjunct's contrary may be the
      witness, so requiring all of them is the conservative *sound* reading (it can over-require,
      but never silently passes an unsound case);
    - a binding query needs the goal's contrary when ``unknown`` (its unknown-set reads ``-q`` off
      ⋃/⋂, so an unshown ``-q`` would under-compute it — sounder than the spec's letter, which omits
      the unknown-binding form; reconciliation ledgered), or ``no`` with a **non-empty** set (an
      empty ``no`` set is vacuously satisfiable without ``-q``: rule 4's "non-empty" carve-out).

    A ``yes`` query reads only the positive literal, covered by the §2.0/RR9 shown-vocabulary
    precondition (deferred), not this rule. Names are arity-blind (see the module docstring)."""
    match query:
        case GroundQuery(answer, conjuncts) if answer in {Answer.no, Answer.unknown}:
            return frozenset(_signed_name(contrary(conjunct)) for conjunct in conjuncts)
        case BindingQuery(Answer.unknown, goal, _):
            return frozenset({_goal_contrary_name(goal)})
        case BindingQuery(Answer.no, goal, bindings) if bindings:
            return frozenset({_goal_contrary_name(goal)})
        case _:
            return frozenset()


def _signed_name(literal: Symbol) -> str:
    """The sign-aware predicate name of a ground literal, matching ``#show`` vocabulary (§2.0)."""
    return literal.name if literal.positive else f"-{literal.name}"


def _goal_contrary_name(goal: QueryLiteral) -> str:
    """The sign-aware name of a binding goal's *contrary* literal (§2.2 rule 4): ``-q`` for ``q``,
    ``q`` for ``-q`` — the dual of :func:`_signed_name` for a (non-ground) goal."""
    return f"-{goal.name}" if goal.positive else goal.name
