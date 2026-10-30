"""A naive, recursive unifier to check the real one against, and the means to compare results."""

from clingo import Symbol, SymbolType

from elenctic.terms import Compound, Term, Variable, build

type Theta = dict[Variable, Term]


def children(term: Term) -> tuple[Term, ...]:
    """Return the arguments of a term, of whichever kind, and none for a leaf."""
    if isinstance(term, Compound):
        return term.arguments
    if isinstance(term, Symbol) and term.type is SymbolType.Function:
        return tuple(term.arguments)
    return ()


def shape(term: Term) -> tuple[str, bool, int] | None:
    """Return what must agree for two terms to unify, or `None` for a variable."""
    if isinstance(term, Variable):
        return None
    if isinstance(term, Compound) or term.type is SymbolType.Function:
        return term.name, term.positive, len(children(term))
    return str(term), True, -1


def walk(term: Term, theta: Theta) -> Term:
    while isinstance(term, Variable) and term in theta:
        term = theta[term]
    return term


def occurs(variable: Variable, term: Term, theta: Theta) -> bool:
    term = walk(term, theta)
    return term == variable or any(occurs(variable, kid, theta) for kid in children(term))


def unify(left: Term, right: Term, theta: Theta) -> Theta | None:
    """Robinson's algorithm, with the occurs check at every binding, by plain recursion."""
    left, right = walk(left, theta), walk(right, theta)
    if left == right:
        return theta
    for variable, other in ((left, right), (right, left)):
        if isinstance(variable, Variable):
            return None if occurs(variable, other, theta) else {**theta, variable: other}
    if shape(left) != shape(right):
        return None
    result: Theta | None = theta
    for a, b in zip(children(left), children(right), strict=True):
        result = None if result is None else unify(a, b, result)
    return result


def resolve(term: Term, theta: Theta) -> Term:
    term = walk(term, theta)
    if isinstance(term, Variable) or not children(term):
        return term
    name, positive, _ = shape(term) or ("", True, 0)
    return build(name, [resolve(kid, theta) for kid in children(term)], positive=positive)


def reference_instance(left: Term, right: Term) -> Term | None:
    """Return the common instance `left` and `right` unify to, or `None` if they do not unify."""
    theta = unify(left, right, {})
    return None if theta is None else resolve(left, theta)


def alpha_equivalent(left: Term, right: Term) -> bool:
    """Say whether two terms differ at most by a one-to-one renaming of their variables."""
    forward: dict[Variable, Variable] = {}
    backward: dict[Variable, Variable] = {}

    def same(a: Term, b: Term) -> bool:
        if isinstance(a, Variable) and isinstance(b, Variable):
            return forward.setdefault(a, b) == b and backward.setdefault(b, a) == a
        if isinstance(a, Variable) or isinstance(b, Variable) or shape(a) != shape(b):
            return False
        if not children(a):
            return a == b
        return all(same(x, y) for x, y in zip(children(a), children(b), strict=True))

    return same(left, right)
