import json

import pytest

from elenctic.check import Report, check
from elenctic.program import Fault, Program
from elenctic.report import SCHEMA, Entry, Run, encode, to_json, to_text

PASSING = "p.\n% @expect sat\n% @cautious { p }\n"
FAILING = "p.\n% @expect sat\n% @cautious { q }\n"


def entry(text: str, source: str) -> Entry:
    result = check(Program(text, source))
    assert isinstance(result, Report | Fault)
    return Entry(source, result)


def test_a_run_of_passing_sources_exits_zero_and_says_so() -> None:
    run = Run((entry(PASSING, "a.lp"),))
    assert run.exit_code == 0
    assert to_text(run) == "1/1 passed"


def test_a_failing_claim_is_named_with_its_line_and_what_was_found() -> None:
    run = Run((entry(PASSING, "a.lp"), entry(FAILING, "b.lp")))
    assert run.exit_code == 1
    assert to_text(run).splitlines() == [
        "b.lp — FAIL",
        "  [FAIL] @cautious { q } (line 3): { q } ⊆ ⋂ AS(P) = { p } (missing: { q })",
        "",
        "1/2 passed, 1 fail",
    ]


def test_a_fault_exits_two_and_is_located() -> None:
    run = Run((entry("p.\n% @count x\n", "c.lp"),))
    assert run.exit_code == 2
    assert to_text(run).splitlines()[0].startswith("c.lp:2:")


def test_verbose_lists_the_claims_that_passed() -> None:
    assert "[PASS] @expect sat" in to_text(Run((entry(PASSING, "a.lp"),)), verbose=True)


def test_json_is_derived_from_the_result_types() -> None:
    document = json.loads(to_json(Run((entry(FAILING, "b.lp"),))))
    assert document["schema"] == SCHEMA
    assert document["exit_code"] == 1
    (only,) = document["run"]["entries"]
    report = only["result"]
    assert report["kind"] == "Report"
    claim = report["findings"][1]["claim"]
    assert claim["reading"] == {
        "kind": "Entails",
        "mode": "cautious",
        "literals": ["q"],
        "over": "all",
    }
    assert claim["span"]["start"] == {"kind": "Position", "line": 3, "column": 3}
    assert report["findings"][1]["verdict"] == "fail"


def test_a_type_is_not_a_result_and_is_not_encoded() -> None:
    with pytest.raises(TypeError, match="cannot encode type"):
        encode(Entry)
    with pytest.raises(TypeError, match="cannot encode object"):
        encode(object())
