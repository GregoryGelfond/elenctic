"""Properties every explanation has, over programs drawn from a pool of rules."""

import re

from clingo import Number
from hypothesis import given, settings
from hypothesis import strategies as st

from elenctic.contract import Solver
from elenctic.determination import Consistent, Inconsistent
from elenctic.explanation import (
    Blocked,
    Chosen,
    Counterexample,
    Derived,
    Explanation,
    Fact,
    Node,
    NoRule,
    Unexplained,
    Unsupported,
)
from elenctic.literals import Assumption, Literal
from elenctic.program import Program
from elenctic.search import Limit
from elenctic.session import Session, session

RULES = (
    "{ a }.", "{ b }.", "b :- not a.", "c :- a, b.", "c :- not b.", "d :- c.", "d :- e.",
    "e :- d.", "{ q(1..3) }.", "f :- #count { X: q(X) } >= 2.", "g(X) :- q(X), not h(X).",
    "h(2).", "1 { r; s } 1.", "t :- r, not a.", ":- t, b.", "u ; v :- c.", "w :- not f, q(1).",
)  # fmt: skip
ATOMS = (
    *(Literal(name) for name in "abcdefrstuvw"),
    *(Literal(name, (Number(i),)) for name in "gq" for i in (1, 2, 3)),
    Literal("h", (Number(2),)),
)

BRANCH = re.compile(r"#r[0-9]+(\(|\.|$)")
"""The end of the handle of an instance that could derive an absent atom: `#r8(ann)`, `#r3.1`."""


def _handle_atom(node: Node) -> tuple[bool, str]:
    """Say whether a node's handle names an atom that holds, and the atom, as the handle has it."""
    text = node.handle.split("/", 1)[1]
    return (False, text[4:]) if text.startswith("not ") else (True, text)


def _explained(rules: list[str]) -> tuple[Session, frozenset[str], Explanation] | None:
    opened = session(Program("\n".join(rules), "t.lp"), Solver.CLINGO)
    assert isinstance(opened, Session), opened
    found = opened.solve()
    if not isinstance(found, Consistent):
        return None
    first = found.evidence.first
    atoms = frozenset(str(literal) for literal in first.atoms)
    counterexample = Counterexample(first, 1, None)
    return opened, atoms, opened.explain(ATOMS, counterexample, max_depth=Limit.UNBOUNDED)


@settings(max_examples=60, deadline=None)
@given(st.lists(st.sampled_from(RULES), min_size=1, max_size=8, unique=True))
def test_every_explanation_is_sound_well_founded_and_complete(rules: list[str]) -> None:
    explained = _explained(rules)
    if explained is None:
        return
    opened, atoms, found = explained
    by = {node.handle: node for node in found.nodes}
    assert found.complete
    for node in found.nodes:
        assert not isinstance(node.reason, Unexplained), node
        if BRANCH.search(node.handle):
            assert not node.holds, node
            continue
        if node.handle.split("/", 1)[1][:1].isdigit():
            continue
        holds, atom = _handle_atom(node)
        assert node.holds is holds
        assert (atom in atoms) is holds, node
        _check_reason(node, by, atoms)
        if isinstance(node.reason, NoRule):
            literal = next(literal for literal in ATOMS if str(literal) == atom)
            assert isinstance(opened.solve(frozenset({Assumption(literal)})), Inconsistent)
    _check_well_founded(found, by)


def _check_reason(node: Node, by: dict[str, Node], atoms: frozenset[str]) -> None:
    match node.reason:
        case Fact() | Derived() | Chosen():
            assert all(by[child].holds for child in node.children), node
        case Unsupported(candidates):
            assert len(node.children) == candidates
            for child in node.children:
                if (
                    isinstance(blocked := by[child].reason, Blocked)
                    and blocked.literal.isidentifier()
                ):
                    assert blocked.literal not in atoms
        case _:
            pass


def _check_well_founded(found: Explanation, by: dict[str, Node]) -> None:
    """Follow the support of each atom that holds: it never comes back to the atom."""
    done: set[str] = set()
    for root in (node.handle for node in found.nodes if node.holds):
        path: list[str] = [root]
        stack = [(root, iter(by[root].children))]
        while stack:
            handle, children = stack[-1]
            child = next(children, None)
            if child is None:
                stack.pop()
                path.pop()
                done.add(handle)
                continue
            if not by[child].holds or child in done:
                continue
            assert child not in path, path
            path.append(child)
            stack.append((child, iter(by[child].children)))
