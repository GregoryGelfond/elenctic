"""Answer queries again without elenctic's evaluation, and compare: two oracles of the same rule.

The first asks clingo for the brave and cautious consequences of rules whose heads hold where an
instance of the query is true, or false; the second reads every answer set clingo enumerates and
evaluates each part itself. Neither imports elenctic's evaluation, so neither shares its mistakes.
"""

from collections.abc import Sequence
from typing import NamedTuple

import clingo
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from elenctic.inquiry import ask
from elenctic.program import Program
from elenctic.queries import read_query
from elenctic.query import Answer, Answered, AnswerMode, Answers
from elenctic.spans import Diagnostic

NAMES, VALUES = ("p", "q", "r"), ("1", "2")


class Part(NamedTuple):
    """A query part: `not` before it or not, classically negated or not, its name and its term."""

    under: bool
    negated: bool
    name: str
    term: str

    def atom(self, value: str, *, contrary: bool = False) -> str:
        sign = "-" if self.negated is not contrary else ""
        return f"{sign}{self.name}({value if self.term == 'X' else self.term})"


type Answers_ = dict[AnswerMode, dict[str, Answer]]

statements = st.one_of(
    st.builds("{}({}).".format, st.sampled_from(NAMES), st.sampled_from(VALUES)),
    st.builds("-{}({}).".format, st.sampled_from(NAMES), st.sampled_from(VALUES)),
    st.builds("{{ {}({}) }}.".format, st.sampled_from(NAMES), st.sampled_from(VALUES)),
    st.builds(
        "{}(X) :- {}(X), not {}(X).".format,
        st.sampled_from(NAMES),
        st.sampled_from(NAMES),
        st.sampled_from(NAMES),
    ),
    st.builds("-{}(X) :- {}(X).".format, st.sampled_from(NAMES), st.sampled_from(NAMES)),
)
parts = st.builds(
    Part, st.booleans(), st.booleans(), st.sampled_from(NAMES), st.sampled_from(("X", *VALUES))
)


def _models(text: str, *arguments: str) -> list[frozenset[str]]:
    control = clingo.Control([*arguments, "--warn=none"])
    control.add("base", [], text)
    control.ground([("base", [])])
    found: list[frozenset[str]] = []
    control.solve(on_model=lambda m: found.append(frozenset(map(str, m.symbols(atoms=True)))))
    return found


def _open(query: Sequence[Part]) -> bool:
    return any(part.term == "X" for part in query)


def _candidates(text: str, query: Sequence[Part], mode: AnswerMode) -> list[str]:
    """Find the values each positive part's instance, or by default its contrary, has bravely."""
    if not _open(query):
        return [""]
    brave = _models(text, "--enum-mode=brave", "0")[-1]
    found = set(VALUES)
    for part in query:
        if not part.under:
            found = {
                value
                for value in found
                if part.atom(value) in brave
                or (mode is AnswerMode.DEFAULT and part.atom(value, contrary=True) in brave)
            }
    return sorted(found)


def _true(part: Part, value: str) -> str:
    return f"not {part.atom(value)}" if part.under else part.atom(value)


def _false(part: Part, value: str) -> str:
    return part.atom(value, contrary=not part.under)


def _decided(mode: AnswerMode, *, everywhere: bool, somewhere: bool, nowhere_false: bool) -> Answer:
    match mode:
        case AnswerMode.DEFAULT:
            return Answer.YES if everywhere else Answer.NO if nowhere_false else Answer.UNKNOWN
        case AnswerMode.CAUTIOUS:
            return Answer.YES if everywhere else Answer.NOT_ENTAILED
        case AnswerMode.BRAVE:
            return Answer.YES if somewhere else Answer.NONE_HOLDS


def _by_consequences(text: str, query: Sequence[Part]) -> Answers_:
    """Answer each binding from clingo's cautious and brave consequences of `true_` and `false_`."""
    rules = []
    for value in VALUES if _open(query) else ("",):
        rules.append(f"true_({value or 0}) :- {', '.join(_true(p, value) for p in query)}.")
        rules += [f"false_({value or 0}) :- {_false(p, value)}." for p in query]
    extended = text + "\n" + "\n".join(rules)
    brave = _models(extended, "--enum-mode=brave", "0")[-1]
    cautious = _models(extended, "--enum-mode=cautious", "0")[-1]
    return {
        mode: {
            value: _decided(
                mode,
                everywhere=f"true_({value or 0})" in cautious,
                somewhere=f"true_({value or 0})" in brave,
                nowhere_false=f"false_({value or 0})" in cautious,
            )
            for value in _candidates(text, query, mode)
        }
        for mode in AnswerMode
    }


def _truth(part: Part, value: str, member: frozenset[str]) -> int:
    """0 false, 1 unknown, 2 true: `not l` by presence alone, `l` by it and its contrary's."""
    if part.under:
        return 0 if part.atom(value) in member else 2
    if part.atom(value) in member:
        return 2
    return 0 if part.atom(value, contrary=True) in member else 1


def _by_evaluation(text: str, query: Sequence[Part]) -> Answers_:
    """Answer each binding by evaluating its parts in every answer set clingo enumerates."""
    members = _models(text, "0")
    found: Answers_ = {}
    for mode in AnswerMode:
        found[mode] = {}
        for value in _candidates(text, query, mode):
            truths = {min(_truth(p, value, member) for p in query) for member in members}
            found[mode][value] = _decided(
                mode, everywhere=truths == {2}, somewhere=2 in truths, nowhere_false=truths == {0}
            )
    return found


def _by_elenctic(text: str, query: Sequence[Part]) -> Answers_:
    read = read_query(", ".join(_true(part, "X") for part in query), "QUERY")
    assert not isinstance(read, Diagnostic), read
    found: Answers_ = {}
    for mode in AnswerMode:
        answered = ask(Program(text, "t.lp"), read, mode=mode)
        assert isinstance(answered, Answered), answered
        if isinstance(answered.answer, Answers):
            found[mode] = {str(b.values[0]): b.answer for b in answered.answer.bound}
        else:
            found[mode] = {"": answered.answer}
    return found


def _safe(query: Sequence[Part]) -> bool:
    return not _open(query) or any(not part.under and part.term == "X" for part in query)


@settings(max_examples=200, deadline=None)
@given(st.lists(statements, min_size=1, max_size=6), st.lists(parts, min_size=1, max_size=3))
def test_every_answer_is_the_one_clingo_consequences_and_a_plain_evaluation_give(
    program: list[str], query: list[Part]
) -> None:
    text = "\n".join(program)
    assume(_safe(query) and _models(text, "1"))
    expected = _by_consequences(text, query)
    assert _by_evaluation(text, query) == expected
    assert _by_elenctic(text, query) == expected


def test_the_oracles_agree_on_the_conjunction_with_not_they_were_written_for() -> None:
    text = "r(1). r(2). { c(2) }."
    query = [
        Part(under=False, negated=False, name="r", term="X"),
        Part(under=True, negated=False, name="c", term="X"),
    ]
    expected = {
        AnswerMode.DEFAULT: {"1": Answer.YES, "2": Answer.UNKNOWN},
        AnswerMode.CAUTIOUS: {"1": Answer.YES, "2": Answer.NOT_ENTAILED},
        AnswerMode.BRAVE: {"1": Answer.YES, "2": Answer.YES},
    }
    assert _by_consequences(text, query) == _by_evaluation(text, query) == expected
    assert _by_elenctic(text, query) == expected
