"""Invariants on failure messages, and clingo's byte columns versus Unicode scalars."""

import ast
import os
import platform
import re
from pathlib import Path
from typing import NamedTuple

import pytest
from clingo.ast import parse_string

from elenctic import tree
from elenctic.body import span_of
from elenctic.check import check
from elenctic.engine import sources
from elenctic.human import render_run
from elenctic.presentation import PLAIN
from elenctic.program import Fault, Locus, Program
from elenctic.reader import parse_contract
from elenctic.report import Entry, Run
from elenctic.spans import Diagnostic, Position, Severity, Span, char_column
from elenctic.verdicts import Report, Verdict
from elenctic.wellformed import wellformed

SRC = Path(__file__).resolve().parents[1] / "src" / "elenctic"
HELPISH = re.compile(r"\b(declare|install|name it)\b", re.IGNORECASE)
BANNED = re.compile(r"did you mean|illegal", re.IGNORECASE)


def _messages(maker: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        module = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            name = (
                callee.attr
                if isinstance(callee, ast.Attribute)
                else callee.id
                if isinstance(callee, ast.Name)
                else None
            )
            if name != maker or len(node.args) < 2:
                continue
            message = node.args[1]
            if isinstance(message, ast.Constant) and isinstance(message.value, str):
                found.append((path.name, message.value))
            elif isinstance(message, ast.JoinedStr):
                literal = "".join(
                    part.value
                    if isinstance(part, ast.Constant) and isinstance(part.value, str)
                    else "x"
                    for part in message.values
                )
                found.append((path.name, literal))
    return found


@pytest.mark.parametrize(("where", "message"), _messages("note"))
def test_no_note_asks_the_reader_a_question(where: str, message: str) -> None:
    assert not BANNED.search(message), (where, message)
    assert "?" not in message, (where, message)


@pytest.mark.parametrize(("where", "message"), _messages("failure"))
def test_every_failure_message_follows_the_rustc_shape(where: str, message: str) -> None:
    assert message, where
    assert not message.endswith("."), (where, message)
    assert ";" not in message, (where, message)
    assert not BANNED.search(message), (where, message)
    head = message.lstrip("`@")
    assert head[:1].islower() or head[:1].isdigit() or head[:1] == "_", (where, message)
    if message.startswith(
        (
            "expected",
            "unknown",
            "missing",
            "unclosed",
            "anonymous",
            "binding",
            "query",
            "assumption",
            "solver",
            "claim",
            "optimal",
            "clingo",
            "theory",
            "cannot",
            "`",
        )
    ):
        assert not HELPISH.search(message), (where, message)


def test_clingo_byte_columns_become_character_columns_on_non_ascii() -> None:
    text = 'p("café").'
    found: list[object] = []
    parse_string(text, found.append)
    function = found[1].head.atom.symbol  # type: ignore[attr-defined]
    argument = function.arguments[0]
    reported = tree.span(argument)
    assert reported.end.column - reported.start.column == len('"café"'.encode())
    converted = span_of(argument, text)
    assert converted.end.column - converted.start.column == len('"café"')
    assert char_column('p("café")', reported.end.column) == converted.end.column


def test_carets_match_the_primary_span_width() -> None:
    text = "p.\n% @expect sat\n% @count x\n"
    result = check(Program(text, "t.lp"))
    assert isinstance(result, Fault)
    (diagnostic,) = result.diagnostics
    assert diagnostic.span is not None
    width = diagnostic.span.end.column - diagnostic.span.start.column
    stderr = render_run(Run((Entry("t.lp", result, text),)), PLAIN).stderr
    assert "^" * width in stderr


def test_carets_sit_under_the_token_after_multibyte_text_on_the_same_line() -> None:
    """Reader spans count Unicode scalars: carets must not drift after `é`."""
    line = '% @cautious { p("café") } assuming x'
    text = "p.\n% @expect sat\n" + line + "\n"
    result = check(Program(text, "t.lp"))
    assert isinstance(result, Fault)
    diagnostic = next(d for d in result.diagnostics if d.span is not None)
    assert diagnostic.span is not None
    assert line[diagnostic.span.start.column - 1 : diagnostic.span.end.column - 1] == "assuming x"
    stderr = render_run(Run((Entry("t.lp", result, text),)), PLAIN).stderr
    width = diagnostic.span.end.column - diagnostic.span.start.column
    pad = " " * (diagnostic.span.start.column - 1)
    assert f"| {pad}{'^' * width}" in stderr


def test_clingo_reports_byte_columns_and_we_convert_them_before_carets() -> None:
    """Clingo's Location columns are UTF-8 bytes; span_of maps them to scalars for carets."""
    source = 'p("café").'
    found: list[object] = []
    parse_string(source, found.append)
    function = found[1].head.atom.symbol  # type: ignore[attr-defined]
    argument = function.arguments[0]
    reported = tree.span(argument)
    assert reported.end.column - reported.start.column == len('"café"'.encode())
    assert char_column(source, reported.start.column) == source.index('"') + 1
    text = 'q.\n% @expect sat\n% @query yes { p("café", 1..2) }\n'
    result = check(Program(text, "t.lp"))
    assert isinstance(result, Fault)
    diagnostic = next(d for d in result.diagnostics if d.span is not None)
    assert diagnostic.span is not None
    src_line = text.split("\n")[2]
    marked = src_line[diagnostic.span.start.column - 1 : diagnostic.span.end.column - 1]
    assert "1..2" in marked
    stderr = render_run(Run((Entry("t.lp", result, text),)), PLAIN).stderr
    width = max(1, diagnostic.span.end.column - diagnostic.span.start.column)
    assert "^" * width in stderr


def test_wellformed_reports_missing_expect_when_none_was_seen() -> None:
    found = wellformed([])
    assert [d.message for d in found] == ["missing `@expect`"]


def test_a_count_with_no_integer_points_at_the_end_of_the_tag() -> None:
    contract = parse_contract("% @expect sat\n% @count\n", "c.lp")
    (found,) = [d for d in contract.diagnostics if d.span is not None]
    assert found.message.startswith("expected a non-negative integer")
    assert found.span is not None
    assert found.span.start == found.span.end == Position(2, 9)


def test_a_zero_width_primary_span_still_draws_one_caret() -> None:
    text = "p.\n% @expect sat\n% @count\n"
    result = check(Program(text, "t.lp"))
    assert isinstance(result, Fault)
    diagnostic = next(d for d in result.diagnostics if d.span is not None)
    assert diagnostic.span is not None
    assert diagnostic.span.start == diagnostic.span.end
    stderr = render_run(Run((Entry("t.lp", result, text),)), PLAIN).stderr
    assert "  |         ^ expected a non-negative integer" in stderr


def test_a_snippet_includes_the_last_line_of_the_source() -> None:
    text = "p.\n% @expect sat\n% @count x\n"
    result = check(Program(text, "t.lp"))
    assert isinstance(result, Fault)
    stderr = render_run(Run((Entry("t.lp", result, text),)), PLAIN).stderr
    assert "3 | % @count x" in stderr
    assert "^" in stderr


def test_a_snippet_is_omitted_when_the_span_line_is_outside_the_source() -> None:
    where = Span("t.lp", Position(99, 1), Position(99, 2))
    result = Fault(Locus.REQUEST, (Diagnostic(where, Severity.ERROR, "gone"),))
    stderr = render_run(Run((Entry("t.lp", result, "one line\n"),)), PLAIN).stderr
    assert "gone" in stderr
    assert "99 |" not in stderr


THEORY = '#theory t { e { }; &a/0 : e, any }.\np("é"). &a { }.\n% @expect sat\n'


def located(result: object) -> list[Span | None]:
    assert isinstance(result, Fault)
    return [diagnostic.span for diagnostic in result.diagnostics]


@pytest.mark.parametrize(
    ("text", "spans"),
    [
        ('p("é"). q :- ).\n% @expect sat\n', [((1, 14), (1, 15))]),
        ('p("é"). q(X) :- p(Y).\n% @expect sat\n', [((1, 9), (1, 22)), ((1, 11), (1, 12))]),
        (THEORY, [((2, 9), (2, 16))]),
    ],
    ids=["syntax error", "unsafe variable", "theory atom"],
)
def test_clingo_places_a_problem_of_a_named_text_in_characters_after_non_ascii(
    text: str, spans: list[tuple[tuple[int, int], tuple[int, int]]]
) -> None:
    expected = [Span("t.lp", Position(*start), Position(*end)) for start, end in spans]
    assert located(check(Program(text, "t.lp"))) == expected


def test_a_theory_atom_in_a_file_one_it_includes_or_a_library_is_placed_in_characters(
    tmp_path: Path,
) -> None:
    case = tmp_path / "case.lp"
    case.write_text(THEORY, encoding="utf-8")
    assert located(check(Program.read(case))) == [Span(str(case), Position(2, 9), Position(2, 16))]
    shared = tmp_path / "shared.lp"
    shared.write_text('p("é"). &a { }.\n', encoding="utf-8")
    case.write_text('#theory t { e { }; &a/0 : e, any }.\n#include "shared.lp".\n% @expect sat\n')
    assert located(check(Program.read(case))) == [
        Span(str(shared), Position(1, 9), Position(1, 16))
    ]
    case.write_text("#theory t { e { }; &a/0 : e, any }.\n% @expect sat\n")
    assert located(check(Program.read(case, (shared,)))) == [
        Span(str(shared), Position(1, 9), Position(1, 16))
    ]


def test_a_theory_atom_in_an_include_clingo_names_as_written_is_placed_in_characters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "shared.lp").write_text('p("é"). &a { }.\n', encoding="utf-8")
    case = tmp_path / "case.lp"
    case.write_text('#theory t { e { }; &a/0 : e, any }.\n#include "shared.lp".\n% @expect sat\n')
    monkeypatch.chdir(tmp_path)
    assert located(check(Program.read("case.lp"))) == [
        Span("shared.lp", Position(1, 9), Position(1, 16))
    ]


DEFINED = "#theory t { e { }; &a/0 : e, any }.\n"
ATOM = 'p("é"). &a { }.\n'
GLIBC = platform.libc_ver()[0] == "glibc"


def layout(root: Path) -> None:
    """Lay out files holding `ATOM`, its theory atom at characters 9 to 16 of line 1."""
    for directory in ("elsewhere", "sub", "lib"):
        (root / directory).mkdir()
    for name in ("shared.lp", "sub/shared.lp", "sub/inner.lp", "lib/shared2.lp"):
        (root / name).write_text(ATOM, encoding="utf-8")


def atoms(*names: str) -> list[Span | None]:
    return [Span(name, Position(1, 9), Position(1, 16)) for name in names]


class Spelled(NamedTuple):
    """A case at `case`, read as `read_as` from `directory`, including `target` named `name`."""

    case: str
    read_as: str
    directory: str
    target: str
    name: str


@pytest.mark.parametrize(
    "spelled",
    [
        pytest.param(
            Spelled("case.lp", "{root}/case.lp", ".", "./shared.lp", "./shared.lp"),
            id="./ as written",
        ),
        pytest.param(
            Spelled("case.lp", "{root}/case.lp", ".", "sub//shared.lp", "sub//shared.lp"),
            id="// as written",
        ),
        pytest.param(
            Spelled("case.lp", "{root}/case.lp", ".", "sub/./shared.lp", "sub/./shared.lp"),
            id="/./ as written",
        ),
        pytest.param(
            Spelled("case.lp", "{root}/case.lp", "elsewhere", "./shared.lp", "{root}/./shared.lp"),
            id="./ beside the including file",
        ),
        pytest.param(
            Spelled(
                "case.lp", "{root}/case.lp", "elsewhere", "sub//shared.lp", "{root}/sub//shared.lp"
            ),
            id="// beside the including file",
        ),
        pytest.param(
            Spelled(
                "case.lp", "{root}/case.lp", "elsewhere", "{root}//shared.lp", "{root}//shared.lp"
            ),
            id="absolute with //",
        ),
        pytest.param(
            Spelled("case.lp", "./case.lp", ".", "./shared.lp", "./shared.lp"),
            id="file given as ./case.lp",
        ),
        pytest.param(
            Spelled("case.lp", "../case.lp", "elsewhere", "./shared.lp", ".././shared.lp"),
            id="file given relatively from elsewhere",
        ),
        pytest.param(
            Spelled("sub/case.lp", ".//sub//case.lp", ".", "./inner.lp", "sub/./inner.lp"),
            id="file given as .//sub//case.lp",
        ),
        pytest.param(
            Spelled("case.lp", "/{root}/case.lp", "elsewhere", "shared.lp", "/{root}/shared.lp"),
            id="file given with two leading slashes",
        ),
        pytest.param(
            Spelled("case.lp", "{root}/case.lp", ".", "sub/../shared.lp", "sub/../shared.lp"),
            id="dotdot as written",
        ),
        pytest.param(
            Spelled(
                "case.lp",
                "{root}/case.lp",
                "elsewhere",
                "sub/../shared.lp",
                "{root}/sub/../shared.lp",
            ),
            id="dotdot beside the including file",
        ),
        pytest.param(
            Spelled("case.lp", "case.lp", ".", "alias.lp", "alias.lp"),
            id="include through a link",
        ),
        pytest.param(
            Spelled("sub/case.lp", "link/case.lp", "elsewhere", "inner.lp", "link/inner.lp"),
            id="file given through a linked directory",
        ),
    ],
)
def test_an_include_is_placed_in_characters_under_the_name_clingo_gives_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spelled: Spelled
) -> None:
    layout(tmp_path)
    (tmp_path / "alias.lp").symlink_to(tmp_path / "shared.lp")
    (tmp_path / "elsewhere" / "link").symlink_to(tmp_path / "sub", target_is_directory=True)
    (tmp_path / spelled.case).write_text(
        f'{DEFINED}#include "{spelled.target.format(root=tmp_path)}".\n% @expect sat\n'
    )
    monkeypatch.chdir(tmp_path / spelled.directory)
    program = Program.read(spelled.read_as.format(root=tmp_path))
    assert located(check(program)) == atoms(spelled.name.format(root=tmp_path))


@pytest.mark.parametrize("path", [True, False], ids=["file", "text"])
def test_a_clingopath_include_is_placed_in_characters_under_the_name_clingo_gives_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: bool
) -> None:
    # Clingo splits `CLINGOPATH` at each colon, past empty entries, and joins each entry to the
    # target with a slash, even after one the entry ends with.
    layout(tmp_path)
    monkeypatch.setenv("CLINGOPATH", f"::{tmp_path}/lib/:")
    monkeypatch.chdir(tmp_path / "elsewhere")
    text = f'{DEFINED}#include "shared2.lp".\n% @expect sat\n'
    (case := tmp_path / "case.lp").write_text(text)
    program = Program.read(case) if path else Program(text)
    assert located(check(program)) == atoms(f"{tmp_path}/lib//shared2.lp")
    library = Program(f"{DEFINED}% @expect sat\n", libraries=(Path("shared2.lp"),))
    assert located(check(library)) == atoms(f"{tmp_path}/lib//shared2.lp")


def test_a_library_of_a_text_is_placed_in_characters_and_so_is_what_it_includes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout(tmp_path)
    (tmp_path / "lib.lp").write_text('#include "./shared.lp".\n')
    monkeypatch.chdir(tmp_path)
    assert located(check(Program(f'{DEFINED}#include "./shared.lp".\n% @expect sat\n'))) == (
        atoms("./shared.lp")
    )
    program = Program(f"{DEFINED}% @expect sat\n", libraries=(Path("./lib.lp"),))
    assert located(check(program)) == atoms("./shared.lp")


@pytest.mark.parametrize(
    ("own", "libraries", "name"),
    [
        ("./shared.lp", ("shared.lp",), "shared.lp"),
        ("shared.lp", ("./shared.lp",), "./shared.lp"),
        (None, ("./shared.lp", "shared.lp"), "shared.lp"),
        (None, ("shared.lp", "./shared.lp"), "./shared.lp"),
    ],
    ids=["file, then library", "library, then file", "two libraries", "two libraries reversed"],
)
def test_a_file_loaded_twice_is_named_as_clingo_reads_it_first_the_last_file_it_is_given(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    own: str | None,
    libraries: tuple[str, ...],
    name: str,
) -> None:
    layout(tmp_path)
    for index, target in enumerate(libraries):
        (tmp_path / f"lib{index}.lp").write_text(f'#include "{target}".\n')
    included = "" if own is None else f'#include "{own}".\n'
    (tmp_path / "case.lp").write_text(f"{DEFINED}{included}% @expect sat\n")
    monkeypatch.chdir(tmp_path)
    named = [tmp_path / f"lib{index}.lp" for index in range(len(libraries))]
    assert located(check(Program.read("case.lp", named))) == atoms(name)


def test_an_include_beside_a_file_named_with_a_doubled_slash_is_named_as_its_clingo_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Clingo built with glibc takes the directory with `dirname`, which drops the doubled slash.
    layout(tmp_path)
    (tmp_path / "sub" / "nested.lp").write_text('#include "inner.lp".\n')
    (tmp_path / "case.lp").write_text(f'{DEFINED}#include "sub//nested.lp".\n% @expect sat\n')
    monkeypatch.chdir(tmp_path / "elsewhere")
    name = f"{tmp_path}/sub/inner.lp" if GLIBC else f"{tmp_path}/sub//inner.lp"
    assert located(check(Program.read(tmp_path / "case.lp"))) == atoms(name)


def test_a_file_included_under_two_spellings_is_read_once_by_its_resolved_path_only_with_glibc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout(tmp_path)
    (tmp_path / "case.lp").write_text(
        f'{DEFINED}#include "shared.lp".\n#include "./shared.lp".\n% @expect sat\n'
    )
    monkeypatch.chdir(tmp_path)
    names = ("shared.lp",) if GLIBC else ("shared.lp", "./shared.lp")
    program = Program.read("case.lp")
    assert located(check(program)) == atoms(names[0])
    for name in names:
        assert sources(program).texts[name] == ATOM


def test_an_absolute_include_is_looked_for_beside_the_including_file_only_without_glibc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout(tmp_path)
    target = f"{tmp_path}/missing/shared.lp"
    beside = tmp_path / "sub" / target.lstrip("/")
    beside.parent.mkdir(parents=True)
    beside.write_text(ATOM, encoding="utf-8")
    (tmp_path / "sub" / "case.lp").write_text(f'{DEFINED}#include "{target}".\n% @expect sat\n')
    monkeypatch.chdir(tmp_path / "elsewhere")
    program = Program.read(tmp_path / "sub" / "case.lp")
    result = check(program)
    assert isinstance(result, Fault)
    if GLIBC:
        assert "file could not be opened" in result.diagnostics[0].message
        assert f"{tmp_path}/sub/{target}" not in sources(program).texts
    else:
        assert located(result) == atoms(f"{tmp_path}/sub/{target}")


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file whatever its permissions")
def test_an_include_found_but_unreadable_is_looked_for_further_only_without_glibc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout(tmp_path)
    (tmp_path / "elsewhere" / "sub").mkdir()
    (unreadable := tmp_path / "elsewhere" / "sub" / "shared.lp").write_text(ATOM)
    unreadable.chmod(0)
    (tmp_path / "case.lp").write_text(f'{DEFINED}#include "sub/shared.lp".\n% @expect sat\n')
    monkeypatch.chdir(tmp_path / "elsewhere")
    result = check(Program.read(tmp_path / "case.lp"))
    assert isinstance(result, Fault)
    if GLIBC:
        assert "file could not be opened" in result.diagnostics[0].message
    else:
        assert located(result) == atoms(f"{tmp_path}/sub/shared.lp")


def test_an_empty_include_is_looked_for_beside_its_file_not_in_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "root").mkdir()
    (tmp_path / "elsewhere").mkdir()
    (case := tmp_path / "root" / "case.lp").write_text('#include "".\n% @expect sat\n')
    monkeypatch.chdir(tmp_path / "elsewhere")
    result = check(Program.read(case), root=tmp_path / "root")
    assert isinstance(result, Report)
    assert result.verdict is Verdict.PASS


def test_an_empty_include_in_a_file_named_from_the_working_directory_opens_what_its_clingo_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Beside `./inner.lp`, clingo built with glibc finds no directory (`dirname` gives "."), so it
    # opens the `CLINGOPATH` directory, outside the root. Otherwise the directory is ".", and it
    # opens "./", the working directory, inside the root.
    (root := tmp_path / "root").mkdir()
    (outside := tmp_path / "outside").mkdir()
    (root / "inner.lp").write_text('#include "".\n')
    (root / "case.lp").write_text('#include "./inner.lp".\n% @expect sat\n')
    monkeypatch.setenv("CLINGOPATH", str(outside))
    monkeypatch.chdir(root)
    result = check(Program.read("case.lp"), root=root)
    if GLIBC:
        assert isinstance(result, Fault)
        assert "outside the root" in result.diagnostics[0].message
    else:
        assert isinstance(result, Report)
        assert result.verdict is Verdict.PASS


def test_an_include_naming_a_nul_is_refused_as_clingo_lexes_it() -> None:
    result = check(Program('#include "a\x00b".\n% @expect sat\n', "t.lp"))
    assert isinstance(result, Fault)
    assert result.diagnostics[0].message.startswith("lexer error")


def test_the_caret_of_a_theory_atom_after_non_ascii_text_sits_under_it() -> None:
    result = check(Program(THEORY, "t.lp"))
    assert isinstance(result, Fault)
    stderr = render_run(Run((Entry("t.lp", result, THEORY),)), PLAIN).stderr
    assert '2 | p("é"). &a { }.\n  |         ^^^^^^^ theory atom' in stderr
