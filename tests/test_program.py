"""The resolved-program inspector: theory presence, shown vocab + optimization, via
parse_files over the case + resolved #includes."""

from pathlib import Path

import pytest
from clingo.ast import AST, ASTType, parse_string

from elenctic.program import ProgramError, Restricted, Unrestricted, inspect


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
    assert facts.shown == Restricted(signatures=frozenset({("q", 0)}), displayed=frozenset())


def test_shown_vocabulary_is_sign_aware(tmp_path: Path) -> None:
    case = _write(tmp_path, "c.lp", "#show reachable/1. #show -reachable/1.\n")
    assert inspect((case,)).shown == Restricted(
        signatures=frozenset({("reachable", 1), ("-reachable", 1)}), displayed=frozenset()
    )


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


# --- the two states a set of signatures spells the same way. Measured against clingo below: a
# program with no declaration shows every atom and one whose only declaration is a bare `#show.`
# shows none, so a vocabulary that is only a set cannot tell them apart. ---


def test_a_bare_show_restricts_the_output_to_nothing(tmp_path: Path) -> None:
    case = _write(tmp_path, "c.lp", "p(1).\n#show.\n")
    assert inspect((case,)).shown == Restricted(signatures=frozenset(), displayed=frozenset())


def test_a_program_with_no_show_at_all_restricts_nothing(tmp_path: Path) -> None:
    case = _write(tmp_path, "c.lp", "p(1). q(1).\n")
    assert inspect((case,)).shown == Unrestricted()


def test_the_two_are_not_the_same_value(tmp_path: Path) -> None:
    # The point of the alternative, stated as the inequality it exists to make true. Under a bare
    # frozenset both of these programs read `frozenset()`, and a refusal naming "the shown
    # vocabulary {}" was printed about the one that shows everything.
    nothing = _write(tmp_path, "nothing.lp", "p(1).\n#show.\n")
    everything = _write(tmp_path, "everything.lp", "p(1).\n")
    assert inspect((nothing,)).shown != inspect((everything,)).shown


def test_a_conditional_term_show_alone_restricts_nothing(tmp_path: Path) -> None:
    # `#show <term> : <body>.` displays a term; it does not switch clingo into selective output.
    # So a program carrying only these still shows every atom, and reading one as a declaration
    # would understate what is observable — a refusal for a literal that is in fact readable.
    #
    # It is recorded as displayed even here, where nothing is restricted, because unrestricted is
    # not the same as faithful: the output holds every literal of the answer set AND whatever the
    # directive emits on top, which need not be an atom of the program at all.
    case = _write(tmp_path, "c.lp", "p(1). q(1).\n#show p(X) : q(X).\n")
    assert inspect((case,)).shown == Unrestricted(displayed=frozenset({("p", 1)}))


def test_a_conditional_term_show_declares_nothing_beside_a_declaration(tmp_path: Path) -> None:
    # And where a declaration is present, the term form is kept out of the vocabulary rather than
    # added to it: the term reaches the output only where its body holds, so `p/1` is visible for
    # some ground instances and not others. It is remembered separately, which is what lets a
    # refusal name the directive the author actually wrote.
    case = _write(tmp_path, "c.lp", "p(1). p(2). q(1).\n#show q/1.\n#show p(X) : q(X).\n")
    assert inspect((case,)).shown == Restricted(
        signatures=frozenset({("q", 1)}), displayed=frozenset({("p", 1)})
    )


def test_clingo_still_restricts_on_a_declaration_and_not_on_a_term(tmp_path: Path) -> None:
    # The premise the two readings above rest on is a fact about clingo, not about elenctic, so it
    # is pinned rather than assumed: if a future clingo made the term form restrictive, the
    # vocabulary would understate what is observable and every reading built on it would follow.
    import clingo

    def shown(body: str) -> set[str]:
        case = _write(tmp_path, f"probe{len(body)}-{body.count(chr(35))}.lp", body)
        control = clingo.Control(["--models=1"])
        control.load(str(case))
        control.ground([("base", [])])
        with control.solve(yield_=True) as handle:
            return {str(symbol) for model in handle for symbol in model.symbols(shown=True)}

    program = "p(a). p(b). q(a).\n"
    assert shown(program) == {"p(a)", "p(b)", "q(a)"}, "no declaration shows every atom"
    assert shown(program + "#show.\n") == set(), "a bare declaration shows none"
    assert shown(program + "#show q/1.\n") == {"q(a)"}, "a declaration restricts to itself"
    # The displayed term names a predicate that is in NO answer set, so this observes both halves
    # at once: the output is not narrowed, AND it gains a symbol the answer set does not contain.
    assert shown(program + "#show seen(X) : q(X).\n") == {"p(a)", "p(b)", "q(a)", "seen(a)"}, (
        "a term directive adds to the output and does not restrict it"
    )


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
    # the commented -reachable is prose
    assert inspect((case,)).shown == Restricted(
        signatures=frozenset({("reachable", 1)}), displayed=frozenset()
    )


# --- nesting depth: the program under test decides it, so the walk must not borrow a limit from
# the interpreter. clingo grounds and solves all three of these at ten thousand deep. ---

_DEEP = 5_000
"""An order of magnitude past the shallowest depth the recursive walk gave out at (a cons list, at
five hundred), and a depth clingo itself handles without complaint."""


def test_a_deeply_nested_arithmetic_term_is_walked(tmp_path: Path) -> None:
    # The hostile shape: a left-nested chain, one AST level per term.
    case = _write(tmp_path, "deep.lp", f"p(X) :- X = {'1' + '+1' * _DEEP}.\n#show p/1.\n")
    assert inspect((case,)).shown == Restricted(
        signatures=frozenset({("p", 1)}), displayed=frozenset()
    )


def test_a_long_cons_list_is_walked(tmp_path: Path) -> None:
    # The ordinary one, and the reason this is worth removing rather than documenting: a list
    # written as cons(a, cons(b, …)) nests one level per element, so an encoding nobody would call
    # adversarial reaches the limit in the ordinary course of things.
    term = "nil"
    for index in range(_DEEP):
        term = f"cons(a{index},{term})"
    case = _write(tmp_path, "list.lp", f"list({term}).\n#show list/1.\n")
    assert inspect((case,)).shown == Restricted(
        signatures=frozenset({("list", 1)}), displayed=frozenset()
    )


def test_a_long_strong_negation_chain_is_walked(tmp_path: Path) -> None:
    # The signature reader walks its own chain, so removing the limit from the node walk alone
    # would leave this one refused at the same depth. The accumulated sign is preserved exactly:
    # the reader records what was written, and folding -- away is not its decision to make.
    #
    # A negation chain this long is spellable only in the term form (a declaration carries one sign
    # flag), and a term form is read only where a declaration puts the program in the restricted
    # state — so the `#show q/1.` here is what keeps the input reaching the reader under test.
    case = _write(tmp_path, "neg.lp", f"q(1).\n#show q/1.\n#show {'-' * _DEEP}p(X) : q(X).\n")
    assert inspect((case,)).shown == Restricted(
        signatures=frozenset({("q", 1)}), displayed=frozenset({("-" * _DEEP + "p", 1)})
    )


# --- the theory-native objective gate: what sets it, rather than what reads it. The gate refuses
# a v1 exclusion loudly, so a form it fails to recognise is a program admitted in silence. ---


@pytest.mark.parametrize(
    "body",
    [
        "&minimize { x }.\n",
        "&maximize { x }.\n",
        "&minimize { 1*x : p }.\n",
        ":- &minimize { x }.\n",
        "&minimize(3) { x }.\n",
    ],
)
def test_a_theory_native_objective_is_detected_in_every_form(tmp_path: Path, body: str) -> None:
    # Head and body, with arguments and with a condition. clingo represents the atom's term as a
    # function node in all of them, which is what makes reading the name by type total.
    assert inspect((_write(tmp_path, "c.lp", body),)).has_theory_optimization is True


@pytest.mark.parametrize("body", ["&sum { x } >= 1.\n", "&diff { a - b } <= 3.\n"])
def test_a_theory_atom_that_is_not_an_objective_does_not_trip_the_gate(
    tmp_path: Path, body: str
) -> None:
    # The other side: the gate is about the objective, not about theories. A constraint atom is
    # ordinary use, and refusing it would refuse the fragment the theory extra exists for.
    facts = inspect((_write(tmp_path, "c.lp", body),))
    assert facts.has_theory_atom is True
    assert facts.has_theory_optimization is False


def test_a_symbol_reports_a_name_it_lacks_by_raising_not_by_absence() -> None:
    # The premise behind asking a symbol's type before its name, pinned against clingo rather than
    # assumed — and the reason a defect hid here. A missing field on an *AST node* falls back to
    # the default, which is what made the pattern look safe everywhere; a name read off a symbol
    # that has none raises instead, so the default cannot stand in for it. If a future clingo makes
    # the two agree, this test fails and says so.
    statements: list[AST] = []
    parse_string('#show "text" : p.\np.\n', statements.append, logger=lambda *_args: None)
    shown = next(node for node in statements if node.ast_type is ASTType.ShowTerm)

    assert getattr(shown, "no_such_field", None) is None, "a missing AST field falls back"
    with pytest.raises(RuntimeError):
        getattr(shown.term.symbol, "name", None)  # the default is the point: it cannot fire


def test_a_shown_non_predicate_term_declares_no_signature(tmp_path: Path) -> None:
    # `#show <term> : body.` need not show a predicate at all: clingo runs both of these and prints
    # `p "text"` and `p 42`. A symbol's name is defined only for a function symbol, and clingo
    # raises when one is read off a string or a number rather than reporting that there is none —
    # so asking for a name without asking the type first refused a program that is valid.
    case = _write(tmp_path, "c.lp", '#show "text" : p.\n#show 42 : p.\np.\n#show p/0.\n')
    assert inspect((case,)).shown == Restricted(
        signatures=frozenset({("p", 0)}), displayed=frozenset()
    )


def test_percent_inside_a_string_term_is_not_a_comment(tmp_path: Path) -> None:
    case = _write(tmp_path, "c.lp", 'label("50% done"). #show label/1.\n')
    assert inspect((case,)).shown == Restricted(
        signatures=frozenset({("label", 1)}), displayed=frozenset()
    )
