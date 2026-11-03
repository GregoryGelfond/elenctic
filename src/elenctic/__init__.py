"""Contracts and queries for answer set programs."""

from elenctic.check import check
from elenctic.contract import Assigns, Claim, Contract, Costs, Solver
from elenctic.determination import (
    Assignment,
    Conclusion,
    Consequences,
    Consistent,
    Cost,
    Determination,
    Exhausted,
    Inconclusive,
    Inconsistent,
    Incumbent,
    Mode,
    Model,
    Models,
    NoAssumptions,
    NotThese,
    Optimized,
    Optimum,
    Range,
    Refutation,
    These,
    Truncation,
    Valuation,
    WorldView,
    optimal_view,
    world_view,
)
from elenctic.engine import ground, solve
from elenctic.extension import Extension
from elenctic.facts import Facts
from elenctic.grounded import Grounded
from elenctic.judge import judge
from elenctic.literals import (
    AnswerSet,
    Assumption,
    Literal,
    Scenario,
    Signature,
)
from elenctic.patterns import Pattern
from elenctic.program import Fault, Locus, Program
from elenctic.query import (
    Answer,
    Bindings,
    Query,
    Truth,
    answer,
    bindings,
    evaluate,
)
from elenctic.reader import parse_contract
from elenctic.search import Interrupt, Limit, Limits, Request
from elenctic.spans import Diagnostic, Position, Severity, Span
from elenctic.substitution import Substitution
from elenctic.terms import Compound, Term, Variable
from elenctic.unify import Unifier, mgu
from elenctic.verdicts import Finding, Report, Verdict
from elenctic.writer import render

__all__ = [
    "Answer",
    "AnswerSet",
    "Assignment",
    "Assigns",
    "Assumption",
    "Bindings",
    "Claim",
    "Compound",
    "Conclusion",
    "Consequences",
    "Consistent",
    "Contract",
    "Cost",
    "Costs",
    "Determination",
    "Diagnostic",
    "Exhausted",
    "Extension",
    "Facts",
    "Fault",
    "Finding",
    "Grounded",
    "Inconclusive",
    "Inconsistent",
    "Incumbent",
    "Interrupt",
    "Limit",
    "Limits",
    "Literal",
    "Locus",
    "Mode",
    "Model",
    "Models",
    "NoAssumptions",
    "NotThese",
    "Optimized",
    "Optimum",
    "Pattern",
    "Position",
    "Program",
    "Query",
    "Range",
    "Refutation",
    "Report",
    "Request",
    "Scenario",
    "Severity",
    "Signature",
    "Solver",
    "Span",
    "Substitution",
    "Term",
    "These",
    "Truncation",
    "Truth",
    "Unifier",
    "Valuation",
    "Variable",
    "Verdict",
    "WorldView",
    "answer",
    "bindings",
    "check",
    "evaluate",
    "ground",
    "judge",
    "mgu",
    "optimal_view",
    "parse_contract",
    "render",
    "solve",
    "world_view",
]
