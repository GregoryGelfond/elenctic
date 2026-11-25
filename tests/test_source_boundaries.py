"""Pin source masks, nested include boundaries and located refusals."""

import os
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

import pytest
from clingo.ast import parse_files

from conftest import Link
from elenctic import spans
from elenctic.check import check
from elenctic.engine import ground, included_sources, loaded_libraries
from elenctic.explanation import Explanation
from elenctic.human import render_run
from elenctic.inquiry import ask, why
from elenctic.literals import Literal
from elenctic.presentation import PLAIN
from elenctic.program import Fault, Locus, Program
from elenctic.query import All, Answered
from elenctic.report import Entry, Run
from elenctic.spans import (
    Position,
    Span,
    failure,
    first_unlexable,
    in_characters,
    in_code,
)
from elenctic.verdicts import Report, Verdict


@pytest.mark.parametrize(
    "segments",
    [
        [],
        [("a.", True)],
        [("%", False)],
        [("% comment", False)],
        [("% é", False), ("\na.", True)],
        [("a. ", True), ("% tail", False)],
        [("%**%", False), ("a.", True)],
        [("a.", True), ("%* ignored ** text *%", False), ("b.", True)],
        [("a.", True), ("%* a % comments out *% b.\n *%", False), ("c.", True)],
        [("a.", True), ("%* %* nested *% b. *%", False), ("c.", True)],
        [("#! b.", False), ("\nc.", True)],
        [("%* é", False)],
        [("%* trailing *", False)],
        [("a.", True), ("%* *%", False), ("%* *%", False), ("b.", True)],
        [('""', False), ("a", True)],
        [('"é"', False), ("b", True)],
        [('"unterminated', True)],
        [('"backslash' + "\\", True)],
        [('"two\nlines"', True)],
        [('"\\t is no escape"', True)],
        [('"escaped \\" quote"', False), ("p.", True)],
        [('"escaped \\\\"', False), ("p.", True)],
        [('"%* not a comment *%"', False), ("a.", True)],
        [('% " not a string', False), ("\np.", True)],
        [("#script (python)", True), ('\n# é "\n', False), ("#end.\np.", True)],
        [("#script(lua)", True), (" x = 1 ", False), ("#endx", True)],
        [("#script (python)", True), ("\n# never closed", False)],
        [("% #script (python)", False), ("\np(é).", True)],
    ],
)
def test_the_source_mask_marks_exactly_the_code(segments: list[tuple[str, bool]]) -> None:
    text = "".join(fragment for fragment, _ in segments)
    expected = [code for fragment, code in segments for _ in fragment]
    assert in_code(text) == tuple(expected)


@pytest.mark.parametrize(
    ("text", "line", "column", "message"),
    [
        ("é", 1, 1, "é"),
        ("a.\n  é", 2, 3, "é"),
        ("% é\n\n é", 3, 2, "é"),
        ('p("é").\n é', 2, 2, "é"),
        ("\x80", 1, 1, "U+0080"),
        ("\ufeff", 1, 1, "byte order mark"),
    ],
)
def test_a_refusal_locates_both_ends_of_the_first_character(
    text: str, line: int, column: int, message: str
) -> None:
    refused = first_unlexable(text, "case.lp")
    assert refused is not None
    assert refused.span == Span("case.lp", Position(line, column), Position(line, column + 1))
    assert message in refused.message


def test_the_ascii_boundary_is_not_a_non_ascii_character() -> None:
    assert first_unlexable("\x7f", "case.lp") is None


def test_a_missing_line_does_not_borrow_the_last_lines_characters() -> None:
    where = Span("case.lp", Position(0, 4), Position(0, 6))
    assert in_characters(where, "a\nlong last line") == Span(
        "case.lp", Position(0, 1), Position(0, 1)
    )


def test_a_missing_snippet_line_does_not_print_the_last_line() -> None:
    where = Span("missing-case.lp", Position(0, 4), Position(0, 6))
    fault = Fault(Locus.PROGRAM, (failure(where, "invalid source location"),))
    rendered = render_run(Run((Entry("missing-case.lp", fault, "a\nlast line"),)), PLAIN)
    assert "last line" not in rendered.stderr
    assert "missing-case.lp:0:4" in rendered.stderr


def nested_program(directory: Path, leaf: str) -> Program:
    (directory / "main.lp").write_text('#include "lib.lp".\n% @expect sat\n')
    (directory / "lib.lp").write_text('#include "leaf.lp".\n')
    (directory / "leaf.lp").write_text(leaf)
    return Program.read(directory / "main.lp")


def test_include_discovery_follows_more_than_one_edge(tmp_path: Path) -> None:
    program = nested_program(tmp_path, "a.")
    assert included_sources(program) == frozenset(
        tmp_path / name for name in ("main.lp", "lib.lp", "leaf.lp")
    )


def test_the_lexer_guard_reaches_nested_includes(tmp_path: Path) -> None:
    program = nested_program(tmp_path, "a.\né.\n")
    refused = ground(program)
    assert isinstance(refused, Fault)
    assert refused.diagnostics[0].span == Span(
        str(tmp_path / "leaf.lp"), Position(2, 1), Position(2, 2)
    )


def test_a_nested_include_fault_uses_that_files_own_source(tmp_path: Path) -> None:
    program = nested_program(tmp_path, "% é\nq2 :- q. p(X) :- q.\n")
    refused = check(program, root=tmp_path)
    assert isinstance(refused, Fault)
    spans = [diagnostic.span for diagnostic in refused.diagnostics]
    assert any(span is not None and span.start == Position(2, 10) for span in spans)
    rendered = render_run(Run((Entry(program.source, refused, program.text),)), PLAIN)
    assert "q2 :- q. p(X) :- q." in rendered.stderr


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        (Position(5, 7), Span("case.lp", Position(5, 8), Position(7, 4))),
        (Position(1, 1), Span("case.lp", Position(1, 2), Position(3, 4))),
    ],
)
def test_relative_spans_shift_columns_only_on_their_first_line(
    origin: Position, expected: Span
) -> None:
    assert Span("case.lp", Position(1, 2), Position(3, 4)).shifted(origin) == expected


def test_byte_columns_use_both_the_first_and_the_last_lines() -> None:
    where = Span("case.lp", Position(1, 3), Position(2, 3))
    assert in_characters(where, "éx\néy") == Span("case.lp", Position(1, 2), Position(2, 2))


def clingo_loads(program: Path) -> frozenset[Path]:
    """Return the files clingo itself reads statements from when it parses `program`."""
    names: set[str] = set()
    with suppress(RuntimeError):  # a syntax error still leaves what was read
        parse_files(
            [str(program)],
            lambda statement: names.add(statement.location.begin.filename),
            logger=lambda _code, _message: None,
        )
    return frozenset(Path(name).resolve() for name in names)


# Each layout: files (name -> text), the directory to run from, `CLINGOPATH` relative to the
# temporary directory (or none), and the files the case under test loads.
LAYOUTS = {
    "beside the including file": (
        {"case/t.lp": '#include "lib.lp".\nt.', "case/lib.lp": "lib."},
        ".",
        None,
        {"case/t.lp", "case/lib.lp"},
    ),
    "the working directory before the including file": (
        {"case/t.lp": '#include "lib.lp".\nt.', "case/lib.lp": "near.", "lib.lp": "far."},
        ".",
        None,
        {"case/t.lp", "lib.lp"},
    ),
    "CLINGOPATH last": (
        {"case/t.lp": '#include "lib.lp".\nt.', "path/lib.lp": "lib."},
        ".",
        "path",
        {"case/t.lp", "path/lib.lp"},
    ),
    "a nested include beside the name it was opened by": (
        {
            "case/t.lp": '#include "sub/a.lp".\nt.',
            "case/sub/a.lp": '#include "b.lp".\na.',
            "case/sub/b.lp": "b.",
        },
        "case",
        None,
        {"case/t.lp", "case/sub/a.lp", "case/sub/b.lp"},
    ),
    "a comment between the directive and its file": (
        {"case/t.lp": '#include %* note *% % line\n "lib.lp".\nt.', "case/lib.lp": "lib."},
        ".",
        None,
        {"case/t.lp", "case/lib.lp"},
    ),
    "an escaped name": (
        {"case/t.lp": '#include "l\\\\b.lp".\nt.', "case/l\\b.lp": "lib."},
        ".",
        None,
        {"case/t.lp", "case/l\\b.lp"},
    ),
    "a directive inside a nested comment": (
        {"case/t.lp": '%* %* *% #include "lib.lp". *%\nt.', "case/lib.lp": "lib."},
        ".",
        None,
        {"case/t.lp"},
    ),
    "a directive in a comment": (
        {"case/t.lp": 't.\n% #include\n"lib.lp".', "case/lib.lp": "lib."},
        ".",
        None,
        {"case/t.lp"},
    ),
    "a longer keyword, not a directive": (
        {"case/t.lp": 'p.\n#include_x "lib.lp".\nt.', "case/lib.lp": "lib."},
        ".",
        None,
        {"case/t.lp"},
    ),
    "a built-in program, not a file": (
        {"case/t.lp": "#include <incmode>.\nt.", "case/incmode": "lib."},
        "case",
        None,
        {"case/t.lp"},
    ),
}


@pytest.mark.parametrize("layout", LAYOUTS.values(), ids=LAYOUTS.keys())
def test_include_discovery_finds_exactly_what_clingo_loads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    layout: tuple[dict[str, str], str, str | None, set[str]],
) -> None:
    files, working, searched, loaded = layout
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    monkeypatch.chdir(tmp_path / working)
    if searched is None:
        monkeypatch.delenv("CLINGOPATH", raising=False)
    else:
        monkeypatch.setenv("CLINGOPATH", str(tmp_path / searched))
    case = Path(os.path.relpath(tmp_path / "case/t.lp"))
    expected = frozenset(tmp_path / name for name in loaded)
    assert clingo_loads(case) == expected
    assert included_sources(Program.read(case)) == expected


@pytest.mark.parametrize("tail", ["#include", "#include  \n", "#include %* note *%"])
def test_a_directive_cut_off_at_the_end_names_no_file(tmp_path: Path, tail: str) -> None:
    (tmp_path / "main.lp").write_text(f"p.\n{tail}")
    assert included_sources(Program.read(tmp_path / "main.lp")) == {tmp_path / "main.lp"}


def test_a_linked_file_includes_beside_its_link_not_its_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for directory in ("case", "real"):
        (tmp_path / directory).mkdir()
    (tmp_path / "case/t.lp").write_text('#include "a.lp".\nt.')
    (tmp_path / "real/a.lp").write_text('#include "b.lp".\na.')
    (tmp_path / "case/a.lp").symlink_to(tmp_path / "real/a.lp")
    (tmp_path / "case/b.lp").write_text("near.")
    (tmp_path / "real/b.lp").write_text("far.")
    monkeypatch.chdir(tmp_path)
    expected = {tmp_path / name for name in ("case/t.lp", "real/a.lp", "case/b.lp")}
    assert clingo_loads(Path("case/t.lp")) == expected
    assert included_sources(Program.read("case/t.lp")) == expected


def test_include_discovery_stops_at_a_cycle(tmp_path: Path) -> None:
    (tmp_path / "main.lp").write_text('#include "a.lp".\n')
    (tmp_path / "a.lp").write_text('#include "b.lp".\n')
    (tmp_path / "b.lp").write_text('#include "a.lp".\n#include "main.lp".\n')
    assert included_sources(Program.read(tmp_path / "main.lp")) == {
        tmp_path / name for name in ("main.lp", "a.lp", "b.lp")
    }


def test_a_file_clingo_finds_but_cannot_read_is_still_held_to_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "lib.lp").mkdir()
    (root / "case.lp").write_text('#include "lib.lp".\n% @expect sat\n')
    monkeypatch.chdir(tmp_path)
    refused = check(Program.read("root/case.lp"), root=root)
    assert isinstance(refused, Fault)
    assert f"loads {tmp_path / 'lib.lp'}, which is outside" in refused.diagnostics[0].message


def test_a_fault_in_a_file_found_by_a_relative_name_counts_that_files_characters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "main.lp").write_text('#include "sub/lib.lp".\n% @expect sat\n')
    (tmp_path / "sub/lib.lp").write_text('a("é"). p(X) :- q.\n')
    monkeypatch.chdir(tmp_path)
    program = Program.read("main.lp")
    refused = check(program)
    assert isinstance(refused, Fault)
    assert refused.diagnostics[0].span == Span("sub/lib.lp", Position(1, 9), Position(1, 19))
    rendered = render_run(Run((Entry(program.source, refused, program.text),)), PLAIN)
    assert 'a("é"). p(X) :- q.' in rendered.stderr


def test_a_file_found_from_a_working_directory_outside_the_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "lib.lp").write_text("p.\n")
    (tmp_path / "lib.lp").write_text("p.\n")
    (root / "case.lp").write_text('#include "lib.lp".\n% @expect sat\n')
    monkeypatch.chdir(tmp_path)
    refused = check(Program.read("root/case.lp"), root=root)
    assert isinstance(refused, Fault)
    assert f"loads {tmp_path / 'lib.lp'}, which is outside" in refused.diagnostics[0].message


def test_an_included_file_that_is_not_utf8_is_refused_not_loaded(tmp_path: Path) -> None:
    (tmp_path / "lib.lp").write_bytes(b"p(\xe9).\n")
    (tmp_path / "main.lp").write_text('#include "lib.lp".\n% @expect sat\n')
    refused = ground(Program.read(tmp_path / "main.lp"))
    assert isinstance(refused, Fault)
    assert refused.diagnostics[0].message == f"cannot read `{tmp_path / 'lib.lp'}`"
    (note,) = refused.diagnostics[0].children
    assert note.message == "not valid UTF-8 at line 1, column 3 (byte 3): invalid continuation byte"


def test_a_byte_that_is_not_utf8_after_a_first_empty_line_is_placed_on_the_second(
    tmp_path: Path,
) -> None:
    (tmp_path / "lib.lp").write_bytes(b"\np(\xe9).\n")
    (tmp_path / "main.lp").write_text('#include "lib.lp".\n% @expect sat\n')
    refused = ground(Program.read(tmp_path / "main.lp"))
    assert isinstance(refused, Fault)
    (note,) = refused.diagnostics[0].children
    assert note.message == "not valid UTF-8 at line 2, column 3 (byte 4): invalid continuation byte"


def test_a_library_and_its_includes_are_loaded_and_held_to_the_root(tmp_path: Path) -> None:
    (tmp_path / "case.lp").write_text("% @expect sat\n")
    (tmp_path / "base.lp").write_text('#include "leaf.lp".\n')
    (tmp_path / "leaf.lp").write_text("p.\n")
    program = Program.read(tmp_path / "case.lp", [tmp_path / "base.lp"])
    assert included_sources(program) == {
        tmp_path / name for name in ("case.lp", "base.lp", "leaf.lp")
    }
    assert loaded_libraries(program) == (tmp_path / "base.lp",)
    refused = check(program, root=tmp_path / "elsewhere")
    assert isinstance(refused, Fault)
    assert "the program loads" in refused.diagnostics[0].message


def test_a_library_already_loaded_is_given_to_clingo_once(tmp_path: Path) -> None:
    (tmp_path / "case.lp").write_text('#include "base.lp".\n')
    (tmp_path / "base.lp").write_text('#include "leaf.lp".\n#const n = 1.\n')
    (tmp_path / "leaf.lp").write_text("p.\n")
    (tmp_path / "other.lp").write_text("q.\n")
    named = [
        tmp_path / "leaf.lp",
        tmp_path / "other.lp",
        tmp_path / "base.lp",
        tmp_path / "other.lp",
    ]
    program = Program.read(tmp_path / "case.lp", named)
    assert loaded_libraries(program) == (tmp_path / "other.lp",)
    assert not isinstance(ground(program), Fault)


def test_a_library_of_a_program_without_a_path_is_loaded_after_its_text(tmp_path: Path) -> None:
    (tmp_path / "base.lp").write_text("#const n = 1.\nq :- p.\n")
    program = Program("p.\n", libraries=(tmp_path / "base.lp",))
    assert loaded_libraries(program) == (tmp_path / "base.lp",)
    found = check(
        Program(program.text + "% @expect sat\n% @cautious { q }\n", libraries=program.libraries)
    )
    assert isinstance(found, Report)
    assert found.verdict is Verdict.PASS
    assert loaded_libraries(Program("p.\n")) == ()


def test_a_library_that_is_the_program_itself_is_not_given_again(tmp_path: Path) -> None:
    (case := tmp_path / "case.lp").write_text("#const n = 1.\n% @expect sat\n")
    program = Program.read(case, [case])
    assert loaded_libraries(program) == ()
    assert isinstance(check(program), Report)


def test_a_library_found_on_clingopath_is_recorded_under_the_path_it_was_found_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "lib").mkdir()
    (base := tmp_path / "lib" / "base.lp").write_text("q.\n")
    monkeypatch.setenv("CLINGOPATH", f"{tmp_path}/lib/")
    monkeypatch.chdir(tmp_path)
    program = Program("p.\n", libraries=(Path("base.lp"),))
    assert loaded_libraries(program) == (base,)


def test_a_library_of_a_text_is_found_as_clingo_finds_it_and_dropped_if_the_text_loads_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "base.lp").write_text("#const n = 1.\n")
    monkeypatch.setenv("CLINGOPATH", str(tmp_path / "lib"))
    monkeypatch.chdir(tmp_path)
    program = Program('#include "base.lp".\n', libraries=(Path("base.lp"),))
    assert loaded_libraries(program) == ()


@pytest.mark.parametrize(
    "named", [("base.lp",), ("more.lp",), ("more.lp", "base.lp")], ids=["itself", "by", "both"]
)
def test_a_program_without_a_path_loads_a_file_it_and_a_library_include_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, named: tuple[str, ...]
) -> None:
    (tmp_path / "base.lp").write_text("#const n = 2.\nnum(1..n).\n")
    (tmp_path / "more.lp").write_text('#include "base.lp".\n')
    monkeypatch.chdir(tmp_path)
    text = '#include "base.lp".\n% @expect sat\n% @cautious { num(2) }\n'
    program = Program(text, libraries=tuple(map(Path, named)))
    assert loaded_libraries(program) == tuple(Path(name) for name in named if name != "base.lp")
    found = check(program)
    assert isinstance(found, Report)
    assert found.verdict is Verdict.PASS


def test_a_library_named_with_a_quote_or_backslash_loads_after_a_text(tmp_path: Path) -> None:
    library = tmp_path / 'say "hi" \\ there.lp'
    library.write_text("q :- p.\n")
    found = check(Program("p.\n% @expect sat\n% @cautious { q }\n", libraries=(library,)))
    assert isinstance(found, Report)
    assert found.verdict is Verdict.PASS


def test_an_include_of_a_program_without_a_path_is_held_to_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "secret.lp").write_text("secret(42).\n")
    (tmp_path / "root").mkdir()
    monkeypatch.chdir(tmp_path)
    refused = check(Program('#include "secret.lp".\n% @expect sat\n'), root=tmp_path / "root")
    assert isinstance(refused, Fault)
    assert f"loads {tmp_path / 'secret.lp'}, which is outside" in refused.diagnostics[0].message
    assert "secret(42)" not in str(refused)


def test_a_library_of_a_text_is_found_as_an_include_is_and_held_to_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shelf, root = tmp_path / "shelf", tmp_path / "root"
    for directory in (shelf, root):
        directory.mkdir()
    (shelf / "base.lp").write_text("q :- p.\n")
    monkeypatch.chdir(root)
    monkeypatch.setenv("CLINGOPATH", str(shelf))
    program = Program("p.\n% @expect sat\n% @cautious { q }\n", libraries=(Path("base.lp"),))
    assert included_sources(program) == {shelf / "base.lp"}
    refused = check(program, root=root)
    assert isinstance(refused, Fault)
    assert f"loads {shelf / 'base.lp'}, which is outside" in refused.diagnostics[0].message
    found = check(program, root=tmp_path)
    assert isinstance(found, Report)
    assert found.verdict is Verdict.PASS


def test_a_linked_program_is_held_by_default_to_the_directory_it_resolves_to(
    tmp_path: Path, link: Link
) -> None:
    real, alias = tmp_path / "real", tmp_path / "alias"
    for directory in (real, alias):
        directory.mkdir()
    (real / "case.lp").write_text("p.\n% @expect sat\n")
    link(alias / "case.lp", real / "case.lp")
    program = Program.read(alias / "case.lp")
    found = check(program)
    assert isinstance(found, Report)
    assert found.verdict is Verdict.PASS
    assert isinstance(ask(program, All((Literal("p"),))), Answered)
    assert isinstance(why(program, Literal("p"), index=1), Explanation)


def test_a_library_that_is_not_utf8_is_refused_not_loaded(tmp_path: Path) -> None:
    (tmp_path / "base.lp").write_bytes(b"p(\xe9).\n")
    (tmp_path / "case.lp").write_text("% @expect sat\n")
    refused = ground(Program.read(tmp_path / "case.lp", [tmp_path / "base.lp"]))
    assert isinstance(refused, Fault)
    assert refused.diagnostics[0].message == f"cannot read `{tmp_path / 'base.lp'}`"


def test_a_missing_include_loads_nothing_and_clingo_reports_it(tmp_path: Path) -> None:
    (tmp_path / "case.lp").write_text('#include "absent.lp".\n% @expect sat\n')
    program = Program.read(tmp_path / "case.lp")
    assert included_sources(program) == {tmp_path / "case.lp"}
    refused = ground(program)
    assert isinstance(refused, Fault)
    (diagnostic,) = refused.diagnostics
    assert diagnostic.message == "file could not be opened: `absent.lp`"
    assert diagnostic.children == ()


def test_a_program_without_a_path_and_without_libraries_never_reads_stdin() -> None:
    """Clingo reads stdin when it is given no file to parse; elenctic never asks it to."""
    ran = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from elenctic import Program, solve\n"
                "found = solve(Program('p.'))\n"
                "print(sorted(str(a) for s in found.evidence.all for a in s.atoms))\n"
            ),
        ],
        input="q.\n",
        capture_output=True,
        text=True,
        check=True,
    )
    assert ran.stdout == "['p']\n"


def test_a_program_is_held_by_default_to_the_directory_that_holds_it_and_its_libraries(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    for directory in ("scenarios", "encodings"):
        (project / directory).mkdir(parents=True)
    (project / "scenarios" / "case.lp").write_text("q :- p.\n% @expect sat\n% @cautious { q }\n")
    (project / "encodings" / "base.lp").write_text("p.\n")
    (tmp_path / "secret.lp").write_text("secret(42).\n")
    program = Program.read(project / "scenarios" / "case.lp", [project / "encodings" / "base.lp"])
    found = check(program)
    assert isinstance(found, Report)
    assert found.verdict is Verdict.PASS
    assert isinstance(ask(program, All((Literal("q"),))), Answered)
    assert isinstance(why(program, Literal("q"), index=1), Explanation)
    escaping = Program(
        '#include "../../secret.lp".\n' + program.text,
        program.source,
        program.path,
        program.libraries,
    )
    refused = check(escaping)
    assert isinstance(refused, Fault)
    assert f"which is outside the root {project}" in refused.diagnostics[0].message


def test_a_default_root_that_is_the_file_system_root_is_refused_by_the_library(
    tmp_path: Path,
) -> None:
    (tmp_path / "case.lp").write_text("% @expect sat\n")
    library = Path(Path.cwd().anchor, "dev", "null")
    program = Program.read(tmp_path / "case.lp", [library])
    for refused in (
        check(program),
        why(program, Literal("p"), index=1),
        ask(program, All((Literal("p"),))),
    ):
        assert isinstance(refused, Fault)
        (problem,) = refused.diagnostics
        assert problem.message == f"the default root {library.anchor} is too wide"
        reason, *_ = problem.children
        assert reason.message == "it is the root of the file system"


def test_the_library_does_not_read_the_home_directory_to_hold_a_program(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "case.lp").write_text("q :- p.\n% @expect sat\n% @cautious { q }\n")
    (tmp_path / "base.lp").write_text("p.\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    found = check(Program.read(tmp_path / "project" / "case.lp", [tmp_path / "base.lp"]))
    assert isinstance(found, Report)
    assert found.verdict is Verdict.PASS


def test_a_program_without_a_path_is_held_only_to_a_root_named_for_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for directory in ("encodings", "shared"):
        (tmp_path / directory).mkdir()
    (tmp_path / "encodings" / "base.lp").write_text("q :- p.\n")
    (tmp_path / "shared" / "p.lp").write_text("p.\n")
    monkeypatch.chdir(tmp_path)
    text = '#include "shared/p.lp".\n% @expect sat\n% @cautious { q }\n'
    program = Program(text, libraries=(tmp_path / "encodings" / "base.lp",))
    found = check(program)
    assert isinstance(found, Report)
    assert found.verdict is Verdict.PASS
    assert isinstance(check(program, root=tmp_path / "encodings"), Fault)


def test_a_program_is_lexed_once_however_many_readers_read_it(tmp_path: Path) -> None:
    path = tmp_path / "once.lp"
    path.write_text('% lexed once\np("once"). % one\n%* two *%\n')
    before = spans.lexemes.cache_info()
    assert not isinstance(ground(Program.read(path)), Fault)
    after = spans.lexemes.cache_info()
    assert (after.misses - before.misses, after.hits > before.hits) == (1, True)
