from elenctic.extension import Extension
from elenctic.literals import Literal, Signature


def lit(text: str) -> Literal:
    return Literal.parse(text)


def test_the_literals_of_one_signature_are_found_together() -> None:
    extension = Extension([lit("p(1)"), lit("q(1)"), lit("p(2)"), lit("-p(3)"), lit("p(1,2)")])
    assert set(extension.with_signature(Signature("p", 1))) == {lit("p(1)"), lit("p(2)")}
    assert set(extension.with_signature(Signature("p", 1, positive=False))) == {lit("-p(3)")}
    assert set(extension.with_signature(Signature("p", 2))) == {lit("p(1,2)")}


def test_a_signature_that_no_literal_has_finds_nothing() -> None:
    extension = Extension([lit("p(1)"), lit("r(1)")])
    assert extension.with_signature(Signature("q", 1)) == ()
    assert Extension([]).with_signature(Signature("q", 1)) == ()


def test_an_extension_holds_each_literal_once_whatever_the_order_given() -> None:
    extension = Extension([lit("q"), lit("p"), lit("p")])
    assert len(extension) == 2
    assert {str(each) for each in extension} == {"p", "q"}
