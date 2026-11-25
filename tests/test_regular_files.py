"""Pin that a file which is not a regular file is refused before elenctic or clingo reads it."""

import errno
import os
import platform
import socket
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

import elenctic
from conftest import Link
from elenctic.check import check
from elenctic.cli import main
from elenctic.engine import loaded_libraries, sources
from elenctic.program import Fault, Locus, Program
from elenctic.report import Exit

CASE = "% @expect sat\n"
NULL = Path("/dev/null")

type Pipe = Callable[[Path], Path]


@pytest.fixture
def pipe() -> Iterator[Pipe]:
    """Make FIFOs; a reader still waiting on one after ten seconds is let go, and the test fails."""
    made: list[Path] = []
    done, waited = threading.Event(), threading.Event()

    def release() -> None:
        if done.wait(10):
            return
        while not done.wait(0.1):
            for path in made:
                try:
                    os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
                except OSError:
                    continue
                waited.set()

    watcher = threading.Thread(target=release, daemon=True)
    watcher.start()

    def make(path: Path) -> Path:
        os.mkfifo(path)
        made.append(path)
        return path

    yield make
    done.set()
    watcher.join()
    assert not waited.is_set(), "a FIFO was opened and waited on"


def special(kind: str, at: Path, pipe: Pipe) -> Path:
    """Return a file at `at` of `kind` that is not a regular file; the device is `/dev/null`."""
    match kind:
        case "FIFO":
            return pipe(at)
        case "directory":
            at.mkdir()
            return at
        case "socket":  # bound by a short, relative name, as a socket's name is short
            with socket.socket(socket.AF_UNIX) as bound:
                bound.bind(str(at))
            return at
        case _:
            return NULL


KINDS = ("FIFO", "directory", "device")


def refused_as(result: object, name: str, kind: str, locus: Locus) -> None:
    assert isinstance(result, Fault)
    assert result.locus is locus
    (refusal,) = result.diagnostics
    assert refusal.message == f"cannot read `{name}`"
    assert [child.message for child in refusal.children] == [f"it is a {kind}, not a regular file"]


@pytest.mark.parametrize("kind", KINDS)
def test_a_program_is_not_read_from_a_file_that_is_not_regular(
    tmp_path: Path, pipe: Pipe, kind: str
) -> None:
    path = special(kind, tmp_path / "case.lp", pipe)
    with pytest.raises(OSError, match=f"^it is a {kind}, not a regular file$"):
        Program.read(path)


@pytest.mark.parametrize("kind", KINDS)
def test_the_refusal_of_a_file_that_is_not_regular_names_it_with_an_errno(
    tmp_path: Path, pipe: Pipe, kind: str
) -> None:
    path = special(kind, tmp_path / "case.lp", pipe)
    with pytest.raises(elenctic.IrregularFileError) as raised:
        Program.read(path)
    expected = errno.EISDIR if kind == "directory" else errno.EINVAL
    assert (raised.value.filename, raised.value.errno) == (str(path), expected)


def test_a_directory_read_as_a_program_is_also_an_is_a_directory_error(tmp_path: Path) -> None:
    with pytest.raises(IsADirectoryError) as raised:
        Program.read(tmp_path)
    assert isinstance(raised.value, elenctic.IrregularFileError)
    assert (raised.value.filename, raised.value.errno) == (str(tmp_path), errno.EISDIR)
    assert str(raised.value) == "it is a directory, not a regular file"


@pytest.mark.parametrize("kind", KINDS)
def test_a_program_named_by_a_file_that_is_not_regular_is_refused(
    tmp_path: Path, pipe: Pipe, kind: str
) -> None:
    path = special(kind, tmp_path / "case.lp", pipe)
    result = check(Program(CASE, str(path), path), root=Path("/"))
    refused_as(result, str(path), kind, Locus.REQUEST)


@pytest.mark.parametrize("kind", ["FIFO", "device"])  # a directory named is walked
def test_a_case_named_on_the_command_line_that_is_not_regular_is_refused(
    tmp_path: Path, pipe: Pipe, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    path = special(kind, tmp_path / "case.lp", pipe)
    code = main([str(path)])
    err = capsys.readouterr().err
    assert code == Exit.FAULT
    assert err.splitlines()[0] == f"error: cannot read `{path}`"
    assert f"note: it is a {kind}, not a regular file" in err


def test_a_fifo_found_in_a_walked_directory_is_refused_and_the_rest_still_run(
    tmp_path: Path, pipe: Pipe, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "good.lp").write_text(CASE)
    path = pipe(tmp_path / "pipe.lp")
    code = main([str(tmp_path)])
    captured = capsys.readouterr()
    assert code == Exit.FAULT
    assert f"error: cannot read `{path}`" in captured.err
    assert captured.out == "1/2 passed, 1 error\n"


def test_standard_input_named_as_a_case_is_refused_when_it_is_a_pipe() -> None:
    shown = subprocess.run(
        [sys.executable, "-m", "elenctic", "/dev/stdin"],
        input=CASE,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert shown.returncode == Exit.FAULT
    assert shown.stderr.splitlines()[0] == "error: cannot read `/dev/stdin`"
    assert "note: it is a FIFO, not a regular file" in shown.stderr


@pytest.mark.parametrize("kind", KINDS)
def test_a_library_that_is_not_regular_is_refused(tmp_path: Path, pipe: Pipe, kind: str) -> None:
    (case := tmp_path / "case.lp").write_text(CASE)
    library = special(kind, tmp_path / "base.lp", pipe)
    program = Program.read(case, [library])
    assert loaded_libraries(program) == (library,)
    refused_as(check(program, root=Path("/")), str(library), kind, Locus.PROGRAM)


def test_a_library_named_on_the_command_line_that_is_a_fifo_is_refused_and_no_case_runs(
    tmp_path: Path, pipe: Pipe, capsys: pytest.CaptureFixture[str]
) -> None:
    (case := tmp_path / "case.lp").write_text(CASE)
    library = pipe(tmp_path / "base.lp")
    code = main([str(case), "--with", str(library)])
    captured = capsys.readouterr()
    assert code == Exit.FAULT
    assert f"error: cannot read `{library}`" in captured.err
    assert "note: it is a FIFO, not a regular file" in captured.err
    assert captured.out == "0/1 passed, 1 error\n"  # the refusal; no case ran


@pytest.mark.parametrize(
    ("kind", "target"),
    [("FIFO", "./pipe.lp"), ("directory", "sub"), ("socket", "sock.lp"), ("device", str(NULL))],
)
def test_an_include_that_is_not_regular_is_refused_under_the_name_clingo_gives_it(
    tmp_path: Path, pipe: Pipe, monkeypatch: pytest.MonkeyPatch, kind: str, target: str
) -> None:
    monkeypatch.chdir(tmp_path)
    special(kind, Path(Path(target).name), pipe)
    Path("case.lp").write_text(f'#include "{target}".\n{CASE}')
    program = Program.read("case.lp")
    assert target not in sources(program).texts
    result = check(program, root=Path("/"))
    if kind == "socket" and platform.libc_ver()[0] != "glibc":
        # Without glibc, clingo tries to open a socket and fails; it does not load it.
        assert isinstance(result, Fault)
        assert result.diagnostics[0].message == f"file could not be opened: `{target}`"
    else:
        refused_as(result, target, kind, Locus.PROGRAM)


def test_an_include_linked_to_a_fifo_is_refused_under_the_name_of_the_link(
    tmp_path: Path, pipe: Pipe, link: Link, monkeypatch: pytest.MonkeyPatch
) -> None:
    link(tmp_path / "alias.lp", pipe(tmp_path / "pipe.lp"))
    (tmp_path / "case.lp").write_text(f'#include "alias.lp".\n{CASE}')
    monkeypatch.chdir(tmp_path)
    refused_as(check(Program.read("case.lp")), "alias.lp", "FIFO", Locus.PROGRAM)


def test_an_include_found_on_clingopath_that_is_a_fifo_is_refused_under_the_name_joined(
    tmp_path: Path, pipe: Pipe, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "lib").mkdir()
    (tmp_path / "elsewhere").mkdir()
    pipe(tmp_path / "lib" / "pipe.lp")
    monkeypatch.setenv("CLINGOPATH", f"{tmp_path}/lib/")
    monkeypatch.chdir(tmp_path / "elsewhere")
    program = Program(f'#include "pipe.lp".\n{CASE}')
    refused_as(check(program, root=tmp_path), f"{tmp_path}/lib//pipe.lp", "FIFO", Locus.PROGRAM)


def test_a_program_whose_file_is_not_there_is_left_for_clingo_to_report(tmp_path: Path) -> None:
    absent = tmp_path / "absent.lp"
    refused = check(Program(CASE, str(absent), absent))
    assert isinstance(refused, Fault)
    assert refused.diagnostics[0].message == f"file could not be opened: `{absent}`"


def _refused_include(result: object) -> None:
    assert isinstance(result, Fault)
    (refusal,) = result.diagnostics
    assert refusal.message == "expected a literal, found `#include`"


@pytest.mark.parametrize(
    "tag",
    [
        '% @query yes {{ p. #include "{0}" }}',
        '% @cautious {{ p }} assuming {{ p. #include "{0}" }}',
    ],
)
def test_an_include_in_a_tag_is_refused_before_its_file_is_opened(
    tmp_path: Path, pipe: Pipe, tag: str
) -> None:
    fifo = pipe(tmp_path / "fifo")
    found = check(Program(f"{CASE}p.\n{tag.format(fifo)}\n", str(tmp_path / "case.lp")))
    _refused_include(found)


@pytest.mark.parametrize(
    "arguments",
    [
        ["ask", "{case}", 'p. #include "{fifo}".'],
        ["why", "{case}", 'p. #include "{fifo}".', "--answer-set", "1"],
        ["why", "{case}", "p(X)", "--binding", 'X = 1. #include "{fifo}".'],
        ["why", "{case}", "p(1)", "--assuming", 'p(1). #include "{fifo}".'],
    ],
)
def test_an_include_in_an_argument_is_refused_at_it_before_its_file_is_opened(
    tmp_path: Path,
    pipe: Pipe,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
) -> None:
    fifo, case = pipe(tmp_path / "fifo"), tmp_path / "case.lp"
    case.write_text("p(1). p.\n")
    given = [each.format(case=case, fifo=fifo) for each in arguments]
    assert main([*given, "--format", "text"]) == Exit.FAULT
    assert "expected a literal, found `#include`" in capsys.readouterr().err


def test_an_include_after_a_first_empty_line_is_placed_on_its_own_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = tmp_path / "case.lp"
    case.write_text("p.\n")
    assert main(["ask", str(case), '\n#include "x.lp"', "--format", "text"]) == Exit.FAULT
    assert "--> QUERY:2:1\n" in capsys.readouterr().err


def test_an_include_in_a_query_of_a_file_outside_the_root_is_refused_at_the_query(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, outside = tmp_path / "root", tmp_path / "outside.lp"
    root.mkdir()
    (root / "case.lp").write_text("p(1).\n")
    outside.write_text("zz zz zz\n")
    query = f'p(1), #include "{outside}"'
    assert main(["ask", str(root / "case.lp"), query, "--format", "text"]) == Exit.FAULT
    err = capsys.readouterr().err
    assert "expected a literal, found `#include`" in err
    assert "QUERY:1:7" in err
