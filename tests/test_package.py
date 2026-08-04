"""The curated public API: ``elenctic``'s top-level surface is the documented, ordered one."""

import subprocess
import sys
from importlib.resources import files
from pathlib import Path

import elenctic


def test_public_api_exports_the_pipeline_and_outcome_surface() -> None:
    expected = {
        # the pipeline
        "Case",
        "discover",
        "parse",
        "Expectation",
        "Sat",
        "Unsat",
        "runs_for",
        "Run",
        "Mode",
        "solve",
        "run_case",
        "case_verdict",
        "render",
        "CheckReport",
        # the outcomes
        "Determination",
        "Verdict",
        "Observable",
        "Optimum",
        # the error taxonomy
        "ContractError",
        "DiscoveryError",
        "SolverUnavailableError",
        "ProgramError",
        "HarnessError",
        "RoutingError",
        "SeamError",
        # the solver registry
        "Solver",
        "SOLVERS",
        # running a whole corpus, and reading what it produced
        "Invocation",
        "run_corpus",
        "explain_corpus",
        "RunObserver",
        "PlanObserver",
        "exit_status",
        "ExitStatus",
        "PlanOutcome",
        "as_json",
        "schema_text",
        "SCHEMA_VERSION",
    }
    assert expected <= set(elenctic.__all__)
    for name in elenctic.__all__:
        assert hasattr(elenctic, name), f"__all__ names {name!r} but there is no such attribute"


def test_the_package_tells_a_type_checker_that_it_is_typed() -> None:
    # Every annotation in this package is invisible to a consumer without this file (PEP 561): a
    # type checker skips a package that does not carry the marker, whatever is inside it, and says
    # so as a missing-stubs error rather than as anything about elenctic. It shipped that way, and
    # nothing here noticed, because the project's own checks read the source tree rather than an
    # installed copy — so this asks the question the way an installed copy answers it, as a package
    # resource beside the modules, exactly as the packaged schema is read.
    assert (files("elenctic") / "py.typed").is_file(), (
        "elenctic is annotated throughout and gated on a strict type check; without this marker "
        "none of that reaches anyone who installs it"
    )


def test_public_api_is_curated_not_dumped() -> None:
    # __all__ is explicitly sorted (a curated surface — not a dump of every importable name).
    assert elenctic.__all__ == sorted(elenctic.__all__)
    # internals stay internal: the Consistent shapes, accessors, check builders are not exported.
    for internal in ("ConsistentWitness", "witness_of", "has_model", "Field", "_Collector"):
        assert internal not in elenctic.__all__


# A whole corpus run, and its status read, by someone who never went near a command line: the
# console entry is a caller of this and not the place it happens. It proves first that it is the
# tree under test, since a child that quietly loaded another copy answers a different question.
_A_CORPUS_RUN_WITHOUT_THE_CONSOLE_ENTRY = """
import sys
from pathlib import Path

import elenctic.corpus
from elenctic.corpus import run_corpus
from elenctic.outcome import ExitStatus, Invocation, exit_status

if elenctic.corpus.__file__ != {loaded!r}:
    raise SystemExit("the child loaded " + str(elenctic.corpus.__file__) + ", not the tree")

outcome = run_corpus(Invocation(target=Path(sys.argv[1]), strict=False, budget=30.0, deadline=None))
if [case.verdict.value for case in outcome.cases] != ["pass"]:
    raise SystemExit("the one case did not pass: " + repr(outcome))
if exit_status(outcome) != ExitStatus.OK:
    raise SystemExit("a corpus whose every case passed is not the rung that says so")
if "elenctic.cli" in sys.modules:
    raise SystemExit("running a corpus pulled in the console entry")
"""


def test_the_package_alone_does_everything_the_console_entry_does(tmp_path: Path) -> None:
    # The shape the console entry is supposed to be a derivation of: settle an invocation, run it,
    # watch it as it goes, render what came back, read a status off it, write the document. Every
    # step is a call into the curated surface and there is nothing else in it — which is the claim
    # `main` makes about itself, made here without `main`.
    (tmp_path / "case.lp").write_text(
        "% @expect sat\n% @model { a }\n\na.\n#show a/0.\n", encoding="utf-8"
    )
    watched: list[str] = []

    class Watching:
        def unusable(self, record: elenctic.ErrorRecord) -> None:
            watched.append(f"unusable {record.kind.value}")

        def undecided(self, record: elenctic.ErrorRecord) -> None:
            watched.append(f"undecided {record.kind.value}")

        def decided(self, outcome: elenctic.CaseOutcome) -> None:
            watched.append(f"decided {outcome.verdict.value}")

    invocation = elenctic.Invocation(target=tmp_path, strict=False, budget=30.0, deadline=None)
    outcome = elenctic.run_corpus(invocation, observer=Watching())
    document = elenctic.as_json(outcome, invocation)

    assert watched == ["decided pass"], "the run was watched as it went, not only at the end"
    assert elenctic.exit_status(outcome) == elenctic.ExitStatus.OK
    assert document["summary"] == {
        "total": 1,
        "passed": 1,
        "failed": 0,
        "undecided": 0,
        "errors": 0,
        "hygiene": 1,
    }
    assert elenctic.dumps(document).endswith("\n"), "the document is text ready to be written"
    # The other mode, through the same surface, with the observer it takes rather than this one.
    plans = elenctic.explain_corpus(invocation)
    assert [plan.case.contract_source for plan in plans.plans] == [tmp_path / "case.lp"]


def test_running_a_corpus_does_not_reach_for_the_console_entry(tmp_path: Path) -> None:
    # The keystone, stated as something that can fail: the command line is a derivation of the
    # library, so the library has to hold what it derives from. If running a corpus needed the
    # console entry, the derivation would run the other way — an embedder would have to go through
    # a command line to do the one thing they came for.
    #
    # A process, because the rest of the suite imports the console entry; by the time this runs it
    # is already in `sys.modules` and the question cannot be asked in-session at all.
    (tmp_path / "case.lp").write_text(
        "% @expect sat\n% @model { a }\n\na.\n#show a/0.\n", encoding="utf-8"
    )
    import elenctic.corpus

    ran = subprocess.run(
        [
            sys.executable,
            "-c",
            _A_CORPUS_RUN_WITHOUT_THE_CONSOLE_ENTRY.format(loaded=elenctic.corpus.__file__),
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr or ran.stdout
