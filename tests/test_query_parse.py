"""Parsing the ``@query`` surface into its two forms — ground and binding — including a repeated
variable collapsing to one column, a strongly-negated goal, and what the parser refuses."""

import pytest
from clingo import parse_term

from elenctic.query import Answer, BindingQuery, GroundQuery, QueryLiteral, Var, parse_query


@pytest.mark.parametrize(
    ("answer", "payload", "expected"),
    [
        pytest.param(
            "yes",
            "{ start(s), end(t) }",
            GroundQuery(Answer.yes, (parse_term("start(s)"), parse_term("end(t)"))),
            id="ground-conjunctive",
        ),
        pytest.param(
            "no",
            "{ reachable(x) }",
            GroundQuery(Answer.no, (parse_term("reachable(x)"),)),
            id="ground-single",
        ),
    ],
)
def test_parse_ground_query(answer: str, payload: str, expected: GroundQuery) -> None:
    assert parse_query(answer, payload) == expected


def test_parse_binding_query_one_arg() -> None:
    q = parse_query("yes", "{ reachable(X) } = { s, a, t }")
    assert isinstance(q, BindingQuery)
    assert q.goal == QueryLiteral("reachable", True, (Var("X"),))
    assert q.goal.variables == ("X",)
    assert q.bindings == frozenset({(parse_term("s"),), (parse_term("a"),), (parse_term("t"),)})


def test_parse_binding_query_two_arg() -> None:
    q = parse_query("yes", "{ edge(X, Y) } = { (s, a), (a, t) }")
    assert isinstance(q, BindingQuery)
    assert q.goal == QueryLiteral("edge", True, (Var("X"), Var("Y")))
    assert q.goal.variables == ("X", "Y")
    assert q.bindings == frozenset(
        {(parse_term("s"), parse_term("a")), (parse_term("a"), parse_term("t"))}
    )


def test_parse_binding_query_repeated_variable_collapses_to_one_column() -> None:
    # Def 2.2.2: "the list of variables occurring in q" is distinct → q(X, X) has arity 1.
    q = parse_query("yes", "{ rel(X, X) } = { a, b }")
    assert isinstance(q, BindingQuery)
    assert q.goal.variables == ("X",)
    assert q.bindings == frozenset({(parse_term("a"),), (parse_term("b"),)})


def test_parse_binding_query_strong_negation_goal() -> None:
    q = parse_query("yes", "{ -blocked(X) } = { a }")
    assert isinstance(q, BindingQuery)
    assert q.goal == QueryLiteral("blocked", False, (Var("X"),))


@pytest.mark.parametrize(
    ("answer", "payload", "match"),
    [
        pytest.param("maybe", "{ a }", "yes|no|unknown", id="bad-answer"),
        pytest.param(
            "yes", "{ path(X, a, Y) } = { (s, t) }", "all-variable", id="partially-ground"
        ),
        pytest.param("yes", "a, b", "brace set", id="missing-braces"),
        pytest.param("yes", "{ }", "at least one literal", id="empty-litset"),
        pytest.param("yes", "{ a, 1 }", "must be literals", id="non-literal-conjunct"),
        pytest.param("yes", "{ reachable(X) }", "variable-free", id="variable-in-ground-litset"),
        pytest.param("yes", "{ foo } = { }", "at least one variable", id="zero-variable-binding"),
    ],
)
def test_parse_query_rejects(answer: str, payload: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_query(answer, payload)


def test_a_ground_query_with_no_conjuncts_is_unrepresentable() -> None:
    # The empty conjunction is vacuously true, so a query carrying one would PASS whatever the
    # program says — refused at construction rather than left for an evaluator to notice, which is
    # the same boundary `terms.parse_litset` draws. Never provoked until now: the refusal was
    # written and no test had ever reached it.
    with pytest.raises(ValueError, match="needs at least one conjunct"):
        GroundQuery(Answer.yes, ())


def test_a_ground_query_conjunct_that_is_not_a_literal_is_refused() -> None:
    # `contrary` and both evaluators assume every conjunct is a function symbol; a number or a
    # string reaching them would fail somewhere with no account of which claim was at fault.
    with pytest.raises(ValueError, match="must be literals"):
        GroundQuery(Answer.yes, (parse_term("42"),))


@pytest.mark.parametrize(
    ("goal", "refused"),
    [
        ("p(X", "malformed query goal"),
        ("-p(X", "malformed query goal"),
        ("P(X)", "must be an ASP constant"),
        ("-P(X)", "must be an ASP constant"),
    ],
    ids=["unclosed", "unclosed and negated", "a variable in predicate position", "and negated"],
)
def test_a_binding_goal_that_is_not_an_asp_literal_is_refused(goal: str, refused: str) -> None:
    # Written in the BINDING form deliberately: a ground payload is read by `terms.parse_litset`,
    # and only a goal on the left of the binding separator reaches this parser at all. A predicate
    # name that is not an ASP constant is what a reader is most likely to write here, since `P(X)`
    # is how the same claim is spelled in most other notations — and until now nothing had ever
    # provoked either refusal.
    with pytest.raises(ValueError, match=refused):
        parse_query("unknown", f"{{ {goal} }} = {{ (a) }}")


def test_a_binding_query_built_without_a_variable_is_refused_by_the_type() -> None:
    # The parser refuses this shape, and so does the type — the same two layers `parse_litset` and
    # `GroundQuery` already form. A caller assembling a query themselves is the one who can reach
    # past the parser, and every evaluator and every diagnostic that renders a goal assumes the
    # binding form has something to bind.
    with pytest.raises(ValueError, match="at least one variable"):
        BindingQuery(Answer.unknown, QueryLiteral("p", True, ()), frozenset())
