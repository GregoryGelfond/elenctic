"""The resolved-program inspector: theory presence, shown vocab + optimization, via
parse_files over the case + resolved #includes."""

from pathlib import Path

import pytest

from elenctic.program import ProgramError, inspect


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_theory_atom_detected_in_a_head(tmp_path: Path) -> None:
    case = _write(tmp_path, "c.lp", "&dom { 1..3 } = x.\n")
    assert inspect((case,)).has_theory_atom is True


def test_theory_atom_detected_in_a_body_position_robust(tmp_path: Path) -> None:
    # The body atom is Rule -> body[i] (Literal) -> atom (TheoryAtom); detection must traverse
    # clingo's ASTSequence (NOT a python list). A #theory def lets it ground; presence is the point.
    case = _write(
        tmp_path,
        "c.lp",
        "#theory t { lt { - : 3, unary }; &sum/0 : lt, {>=}, lt, any }.\nok :- &sum { x } >= 1.\n",
    )
    assert inspect((case,)).has_theory_atom is True


def test_theory_atom_detected_through_include(tmp_path: Path) -> None:
    _write(tmp_path, "lib/sched.lp", "&dom { 1..3 } = x. &sum { x } >= 2.\n")
    case = _write(tmp_path, "tests/c.lp", '#include "../lib/sched.lp".\n#show.\n')
    assert inspect((case,)).has_theory_atom is True


def test_no_theory_atom_in_plain_asp(tmp_path: Path) -> None:
    case = _write(tmp_path, "c.lp", "p(1). q :- p(1). #show q/0.\n")
    facts = inspect((case,))
    assert facts.has_theory_atom is False
    assert facts.shown == frozenset({("q", 0)})


def test_shown_vocabulary_is_sign_aware(tmp_path: Path) -> None:
    case = _write(tmp_path, "c.lp", "#show reachable/1. #show -reachable/1.\n")
    assert inspect((case,)).shown == frozenset({("reachable", 1), ("-reachable", 1)})


def test_sources_are_the_files_clingo_actually_loads(tmp_path: Path) -> None:
    # `sources` is the authoritative loaded-file set from clingo's own parse (the case + the files
    # it transitively #includes), resolved — what the orphan backstop reads, NOT a regex. A
    # block-commented #include is invisible to clingo, so it is correctly absent (no false dep).
    _write(tmp_path, "lib/facts.lp", "p(1..3).\n")
    case = _write(
        tmp_path,
        "case.lp",
        '#include "lib/facts.lp".\nq :- p(1).\n%*\n#include "orphan.lp".\n*%\n#show q/0.\n',
    )
    _write(tmp_path, "orphan.lp", "never(used).\n")  # only "included" inside a block comment
    sources = inspect((case,)).sources
    assert sources == frozenset({case.resolve(), (tmp_path / "lib" / "facts.lp").resolve()})
    assert (tmp_path / "orphan.lp").resolve() not in sources  # block comment is not a dependency


def test_bare_show_nothing_contributes_no_name(tmp_path: Path) -> None:
    case = _write(tmp_path, "c.lp", "p(1).\n#show.\n")
    assert inspect((case,)).shown == frozenset()


def test_conditional_term_show_contributes_its_function_name(tmp_path: Path) -> None:
    case = _write(tmp_path, "c.lp", "p(1). q(1).\n#show p(X) : q(X).\n")
    assert ("p", 1) in inspect((case,)).shown


def test_optimization_and_maximize_by_weight_sign(tmp_path: Path) -> None:
    # #minimize and #maximize are BOTH `Minimize` AST nodes (maximize = negated weights), so
    # has_maximize is decided by weight sign, not node type.
    mini = _write(tmp_path, "min.lp", "1{a;b}1. #minimize { 1,a : a }.\n")
    maxi = _write(tmp_path, "max.lp", "1{a;b}1. #maximize { 2,b : b }.\n")
    assert inspect((mini,)).has_optimization is True
    assert inspect((mini,)).has_maximize is False
    assert inspect((maxi,)).has_optimization is True
    assert inspect((maxi,)).has_maximize is True


def test_weak_constraint_is_optimization(tmp_path: Path) -> None:
    # :~ lowers to a Minimize node too, so has_optimization covers it.
    case = _write(tmp_path, "w.lp", "p(1..3).\n:~ p(X). [X@1]\n")
    assert inspect((case,)).has_optimization is True


def test_missing_include_is_a_friendly_program_error(tmp_path: Path) -> None:
    case = _write(tmp_path, "c.lp", '#include "does-not-exist.lp".\n')
    with pytest.raises(ProgramError, match=r"does-not-exist\.lp|#include"):
        inspect((case,))


def test_non_utf8_file_is_a_friendly_program_error(tmp_path: Path) -> None:
    # A non-UTF-8 .lp (plausible in the literate kr-domains corpus: an accented byte in a comment)
    # must surface as a friendly ProgramError, never a raw UnicodeDecodeError traceback.
    case = tmp_path / "bad.lp"
    case.write_bytes("ok. % résumé café\n".encode("latin-1"))
    with pytest.raises(ProgramError, match=r"bad\.lp"):
        inspect((case,))


def test_syntactically_broken_file_is_a_friendly_program_error(tmp_path: Path) -> None:
    case = _write(tmp_path, "c.lp", "this is not :- valid ASP %(\n")
    with pytest.raises(ProgramError, match=r"c\.lp"):
        inspect((case,))


# --- comment robustness: a directive in prose is not a directive (clingo's parser strips comments,
# so the AST never sees it — the AST approach makes this trivially correct, no regex stripper) ---


def test_minimize_in_a_comment_is_not_optimization(tmp_path: Path) -> None:
    case = _write(tmp_path, "c.lp", "% TODO: maybe add a #minimize here\np(1). #show p/1.\n")
    assert inspect((case,)).has_optimization is False


def test_commented_show_does_not_pollute_the_shown_vocabulary(tmp_path: Path) -> None:
    case = _write(tmp_path, "c.lp", "% #show -reachable/1.\n#show reachable/1.\n")
    assert inspect((case,)).shown == frozenset({("reachable", 1)})  # commented -reachable is prose


# --- nesting depth: the program under test decides it, so the walk must not borrow a limit from
# the interpreter. clingo grounds and solves all three of these at ten thousand deep. ---

_DEEP = 5_000
"""An order of magnitude past the shallowest depth the recursive walk gave out at (a cons list, at
five hundred), and a depth clingo itself handles without complaint."""


def test_a_deeply_nested_arithmetic_term_is_walked(tmp_path: Path) -> None:
    # The hostile shape: a left-nested chain, one AST level per term.
    case = _write(tmp_path, "deep.lp", f"p(X) :- X = {'1' + '+1' * _DEEP}.\n#show p/1.\n")
    assert inspect((case,)).shown == frozenset({("p", 1)})


def test_a_long_cons_list_is_walked(tmp_path: Path) -> None:
    # The ordinary one, and the reason this is worth removing rather than documenting: a list
    # written as cons(a, cons(b, …)) nests one level per element, so an encoding nobody would call
    # adversarial reaches the limit in the ordinary course of things.
    term = "nil"
    for index in range(_DEEP):
        term = f"cons(a{index},{term})"
    case = _write(tmp_path, "list.lp", f"list({term}).\n#show list/1.\n")
    assert inspect((case,)).shown == frozenset({("list", 1)})


def test_a_long_strong_negation_chain_is_walked(tmp_path: Path) -> None:
    # The signature reader walks its own chain, so removing the limit from the node walk alone
    # would leave this one refused at the same depth. The accumulated sign is preserved exactly:
    # the reader records what was written, and folding -- away is not its decision to make.
    case = _write(tmp_path, "neg.lp", f"q(1).\n#show {'-' * _DEEP}p(X) : q(X).\n")
    assert inspect((case,)).shown == frozenset({("-" * _DEEP + "p", 1)})


def test_a_shown_non_predicate_term_declares_no_signature(tmp_path: Path) -> None:
    # `#show <term> : body.` need not show a predicate at all: clingo runs both of these and prints
    # `p "text"` and `p 42`. A symbol's name is defined only for a function symbol, and clingo
    # raises when one is read off a string or a number rather than reporting that there is none —
    # so asking for a name without asking the type first refused a program that is valid.
    case = _write(tmp_path, "c.lp", '#show "text" : p.\n#show 42 : p.\np.\n#show p/0.\n')
    assert inspect((case,)).shown == frozenset({("p", 0)})


def test_percent_inside_a_string_term_is_not_a_comment(tmp_path: Path) -> None:
    case = _write(tmp_path, "c.lp", 'label("50% done"). #show label/1.\n')
    assert inspect((case,)).shown == frozenset({("label", 1)})
