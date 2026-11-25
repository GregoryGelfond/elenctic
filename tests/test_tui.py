"""The interactive view: the same rows as the text view, the keys, and the choice of `--format`."""

import asyncio
import re
import sys
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from importlib.metadata import version
from pathlib import Path
from typing import Final

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from rich.style import Style as Look

from elenctic import cli
from elenctic.cli import main
from elenctic.contract import Solver
from elenctic.determination import Consistent
from elenctic.evidence_view import explanation_lines
from elenctic.explanation import Counterexample
from elenctic.glyphs import Glyphs
from elenctic.human import source_lines
from elenctic.inquiry import AskExit, WhyExit
from elenctic.legend import (
    BENEATH,
    CANCELLED,
    KEYS,
    NO_STEP,
    NOTHING_DEEPER,
    PAID,
    PENDING,
    PRESSED,
    SEARCHING,
)
from elenctic.literals import Literal
from elenctic.paint import Color, Piece, Role, plain
from elenctic.presentation import Style
from elenctic.program import Program
from elenctic.report import Entry, Exit, Internal
from elenctic.search import Limit
from elenctic.session import Session, session
from test_explain_properties import ATOMS, RULES

textual = pytest.importorskip("textual")

from textual.pilot import Pilot  # noqa: E402
from textual.widgets import Static  # noqa: E402

from elenctic import tui  # noqa: E402
from elenctic.tui import outline  # noqa: E402
from elenctic.tui.app import PANE, Keys, Outline, View, Viewer, Viewing  # noqa: E402
from elenctic.tui.calls import Calls, call  # noqa: E402
from elenctic.tui.outline import Again, Asking, Block, Row, Step  # noqa: E402
from elenctic.tui.rows import painted  # noqa: E402
from elenctic.tui.theme import NAME as THEME  # noqa: E402
from elenctic.tui.theme import _colored, theme  # noqa: E402

ROOT = Path(__file__).parent.parent
EXAMPLES = Path("docs/examples")
PLAIN = Style(Color.OFF, Glyphs.PLAIN)
EVIDENCE = ("absent.lp", "chain.lp", "laptop.lp", "late.lp", "team.lp")
GUIDES = re.compile(r"[│├└─]")


@pytest.fixture(autouse=True)
def _at_the_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paths are named as the documentation names them, so each row reads the same anywhere."""
    monkeypatch.chdir(ROOT)


def viewed(monkeypatch: pytest.MonkeyPatch, *argv: str) -> tuple[int, View, Style]:
    """Run a command with `--format tui` on a terminal, keeping the view it would show."""
    shown: list[tuple[View, Style]] = []
    monkeypatch.setattr(cli, "interactive", lambda *_a, **_k: True)
    monkeypatch.setattr(tui, "show", lambda view, style: shown.append((view, style)))
    code = main([*argv, "--format", "tui"])
    ((view, style),) = shown
    return int(code), view, style


def flat(rows: list[Row]) -> Iterator[Row]:
    pending = list(reversed(rows))
    while pending:
        row = pending.pop()
        yield row
        pending.extend(reversed(row.children))


def _normal(line: str) -> str:
    return " ".join(GUIDES.sub(" ", line).split())


def follows_the_text_view(rows: list[Row], style: Style, text: str) -> bool:
    """Say whether each row, in order, is a line of the text view, its guides and gaps aside."""
    lines = iter(_normal(line) for line in text.splitlines())
    return all(any(_normal(painted(row, style)) == line for line in lines) for row in flat(rows))


def drive(
    view: View,
    style: Style,
    act: Callable[[Pilot[None]], Awaitable[None]],
    size: tuple[int, int] = (120, 40),
) -> Viewer:
    """Run the app headless on a view, once what it finds at the start is shown, and act on it."""
    app = Viewer(view, style)

    async def run() -> None:
        async with app.run_test(size=size) as pilot:
            await settled(pilot)
            await act(pilot)

    asyncio.run(run())
    return app


async def settled(pilot: Pilot[None]) -> None:
    """Wait until each library call the view made is applied and drawn."""
    await pilot.pause()
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def loaded(view: View) -> list[Row]:
    """Find the evidence of each claim the view opens at the start, as the view finds it."""
    for row in flat(view.rows):
        if row.opened and isinstance(row.about, Block) and not row.children:
            row.children = view.evidence(row.about.block, view.max_depth)
    return view.rows


def outline_of(app: Viewer) -> Outline:
    return app.screen.query_one(Outline)


def selected(app: Viewer) -> Row:
    node = outline_of(app).cursor_node
    assert node is not None
    assert node.data is not None
    return node.data


COMMANDS = [
    ("explain", str(EXAMPLES / "chain.lp")),
    ("explain", str(EXAMPLES / "laptop.lp")),
    ("explain", str(EXAMPLES / "why-not.lp")),
    ("explain", str(EXAMPLES / "consequences.lp")),
    ("why", str(EXAMPLES / "absent.lp"), "not access(ann,db)", "--answer-set", "1"),
    ("why", str(EXAMPLES / "chain.lp"), "reach(d)", "--answer-set", "1"),
    ("ask", str(EXAMPLES / "team.lp"), "team(ann)"),
    ("ask", str(EXAMPLES / "team.lp"), "{ team(X) }"),
    ("ask", str(EXAMPLES / "team.lp"), "{ team(ann), team(bob) }"),
    ("ask", str(EXAMPLES / "team.lp"), "{ nobody(X) }"),
    ("ask", str(EXAMPLES / "team.lp"), "team(ann)", "--max-answer-sets", "2"),
    ("why", str(EXAMPLES / "team.lp"), "balanced"),
    ("why", str(EXAMPLES / "team.lp"), "{ team(X) }", "--binding", "X = ann", "--mode", "brave"),
    ("why", str(EXAMPLES / "team.lp"), "zz", "--mode", "brave"),
    ("why", str(EXAMPLES / "team.lp"), "zz"),
    ("why", str(EXAMPLES / "team.lp"), "{ team(ann), not balanced }", "--mode", "brave"),
    ("why", str(EXAMPLES / "team.lp"), "balanced", "--assuming", "team(bob), team(cy)"),
]


# One source: each row is the text view's line.


@pytest.mark.parametrize("argv", COMMANDS)
@pytest.mark.parametrize("icons", ["never", "always"])
def test_every_row_is_the_text_views_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
    icons: str,
) -> None:
    code, view, style = viewed(monkeypatch, f"--icons={icons}", *argv)
    capsys.readouterr()
    assert main([f"--icons={icons}", *argv, "--format", "text"]) == code
    assert follows_the_text_view(loaded(view), style, capsys.readouterr().out)


@pytest.mark.parametrize("name", ["chain.lp", "team.lp", "late.lp"])
def test_every_claim_test_lists_is_a_row(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    _, view, style = viewed(monkeypatch, "test", str(EXAMPLES / name))
    capsys.readouterr()
    main(["test", str(EXAMPLES / name), "--verbose"])
    text = capsys.readouterr().out
    assert follows_the_text_view(view.rows, style, text)
    assert len(list(flat(view.rows))) == text.count("[PASS]") + text.count("[FAIL]") + 1


def test_a_warrants_witness_holds_its_derivation(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "why", str(EXAMPLES / "team.lp"), "balanced")
    (top,) = view.rows
    witness = top.children[1]
    assert _normal(painted(witness, style)).startswith("= neither balanced nor -balanced in")
    assert _normal(painted(witness.children[0], style)).startswith("not balanced no rule fires")


def test_a_pattern_nothing_binds_still_says_it_has_no_yes_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, view, style = viewed(monkeypatch, "ask", str(EXAMPLES / "team.lp"), "{ nobody(X) }")
    rows = [painted(row, style) for row in flat(view.rows)]
    assert rows == [
        "ask: { nobody(X) }",
        "= bindings: 0 yes, 0 no, 0 unknown",
        "= no more bindings",
    ]


def test_a_source_that_could_not_be_checked_starts_closed_with_its_one_reason() -> None:
    reason = "elenctic: internal error: ValueError: boom"
    row = outline.entry(
        Entry("x.lp", Internal("ValueError", "boom")),
        Glyphs.PLAIN,
        source_lines(None),
        lambda _refusal, _text, _source: reason,
        lambda _finding: 0,
        every=True,
        opened=True,
    )
    assert plain(row.phrase) == "x.lp — ERROR (1 diagnostic)"
    assert not row.opened
    assert [child.ansi for child in row.children] == [reason]


def _explained(rules: list[str]) -> tuple[Session, Counterexample] | None:
    opened = session(Program("\n".join(rules), "t.lp"), Solver.CLINGO)
    assert isinstance(opened, Session)
    found = opened.solve()
    if not isinstance(found, Consistent):
        return None
    return opened, Counterexample(found.evidence.first, 1, None)


@settings(max_examples=40, deadline=None)
@given(
    st.lists(st.sampled_from(RULES), min_size=1, max_size=8, unique=True),
    st.sampled_from([1, 2, Limit.UNBOUNDED]),
    st.sampled_from(list(Glyphs)),
)
def test_every_row_of_any_explanation_is_the_text_views_line(
    rules: list[str], depth: int | Limit, glyphs: Glyphs
) -> None:
    explained = _explained(rules)
    if explained is None:
        return
    opened, found = explained
    explanation = opened.explain(ATOMS, found, max_depth=depth)
    style = Style(Color.OFF, glyphs)
    text = "\n".join(explanation_lines(explanation, style, spans=False, own="t.lp"))
    rows = outline.explained(explanation, glyphs, 0, own="t.lp", over=None)
    assert follows_the_text_view(rows, style, text)


def test_a_row_that_is_not_the_text_views_line_is_caught() -> None:
    row = Row((), ())
    row.ansi = "not a line"
    assert not follows_the_text_view([row], PLAIN, "a line\n")


# Choosing the view.


def test_tui_is_a_fault_off_a_terminal(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["explain", str(EXAMPLES / "chain.lp"), "--format", "tui"])
    err = capsys.readouterr().err
    assert code == Exit.FAULT
    assert err.splitlines()[0] == "error: `--format tui` needs a terminal on stdin and stdout"
    assert "= help: write `--format text` to a pipe or a file" in err


VIEWING = ("elenctic.tui", "elenctic.tui.app", "elenctic.tui.rows", "elenctic.tui.theme")
"""The view's package and its modules that import Textual or Rich.

Dropping only these makes importing the view meet Textual and Rich again, while the modules kept
are not made twice, so no class of theirs has a second copy once the test ends.
"""


def _unimported(monkeypatch: pytest.MonkeyPatch) -> None:
    """Import as if the view had not been imported yet."""
    for name in VIEWING:
        monkeypatch.delitem(sys.modules, name)


def _without(monkeypatch: pytest.MonkeyPatch, package: str) -> None:
    """Import as if `package` were not installed, and the view not yet imported."""
    _unimported(monkeypatch)
    for name in list(sys.modules):
        if name.startswith(f"{package}.") or name == package:
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, package, None)


@pytest.mark.parametrize(
    ("argv", "fault"),
    [
        (("explain", str(EXAMPLES / "chain.lp")), Exit.FAULT),
        (("why", str(EXAMPLES / "chain.lp"), "reach(d)", "--answer-set", "1"), WhyExit.FAULT),
        (("ask", str(EXAMPLES / "chain.lp"), "reach(d)"), AskExit.FAULT),
    ],
)
def test_tui_without_the_extra_is_a_fault_naming_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
    fault: int,
) -> None:
    _without(monkeypatch, "textual")
    monkeypatch.setattr(cli, "interactive", lambda *_a, **_k: True)
    assert main([*argv, "--format", "tui"]) == fault
    err = capsys.readouterr().err
    assert err.splitlines()[0] == "error: `--format tui` needs the optional `elenctic[tui]` extra"
    assert "= help: pip install 'elenctic[tui]'" in err


def test_without_the_extra_the_default_is_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _without(monkeypatch, "rich")
    monkeypatch.setattr(cli, "interactive", lambda *_a, **_k: True)
    assert main(["explain", str(EXAMPLES / "chain.lp")]) == Exit.CLAIM_UNMET
    assert "evidence: @query no { reach(c), reach(d) }" in capsys.readouterr().out


def test_an_import_error_of_elenctic_itself_is_not_taken_for_a_missing_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _unimported(monkeypatch)
    monkeypatch.setitem(sys.modules, "elenctic.tui.rows", None)
    with pytest.raises(ModuleNotFoundError):
        cli._installed()  # noqa: SLF001


@pytest.mark.parametrize("command", ["explain", "why", "ask"])
def test_on_a_terminal_with_the_extra_the_evidence_commands_default_to_tui(
    monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    shown: list[View] = []
    monkeypatch.setattr(cli, "interactive", lambda *_a, **_k: True)
    monkeypatch.setattr(tui, "show", lambda view, _style: shown.append(view))
    rest = {"explain": [], "why": ["reach(d)"], "ask": ["reach(d)"]}[command]
    main([command, str(EXAMPLES / "chain.lp"), *rest])
    assert len(shown) == 1


def test_test_defaults_to_text_even_on_a_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "interactive", lambda *_a, **_k: True)
    assert main(["test", str(EXAMPLES / "chain.lp")]) == Exit.CLAIM_UNMET
    assert capsys.readouterr().out.endswith("0/1 passed, 1 fail\n")


@pytest.mark.parametrize(
    ("stdin", "stdout", "term", "expected"),
    [
        (True, True, "xterm", True),
        (False, True, "xterm", False),
        (True, False, "xterm", False),
        (True, True, "dumb", False),
    ],
)
def test_a_view_takes_the_terminal_only_when_stdin_and_stdout_are_live_ones(
    stdin: bool, stdout: bool, term: str, expected: bool
) -> None:
    from elenctic.presentation import Environment, Stream, interactive  # noqa: PLC0415

    def stream(tty: bool) -> Stream:
        return Stream.TERMINAL if tty else Stream.REDIRECTED

    environment = Environment.of({"TERM": term})
    assert interactive(environment, stdin=stream(stdin), stdout=stream(stdout)) is expected


@pytest.mark.parametrize(("old", "new"), [("full", ()), ("short", ("--short",))])
def test_a_format_1_0_took_is_its_new_spelling_with_a_note(
    capsys: pytest.CaptureFixture[str], old: str, new: tuple[str, ...]
) -> None:
    path = str(EXAMPLES / "no-objective.lp")
    main(["test", path, "--format", "text", *new])
    expected = capsys.readouterr()
    main(["test", path, "--format", old])
    found = capsys.readouterr()
    assert found.out == expected.out
    spelled = "--format text" + (" --short" if new else "")
    note = f"warning: `--format {old}` is deprecated and removed in 2.0; write `{spelled}`\n"
    assert found.err == note + expected.err


def test_short_writes_one_line_per_diagnostic(capsys: pytest.CaptureFixture[str]) -> None:
    main(["test", str(EXAMPLES / "no-objective.lp"), "--short"])
    err = capsys.readouterr().err
    assert err.splitlines()[0].startswith("docs/examples/no-objective.lp:4:3-14: error:")
    assert "  |" not in err


def test_a_format_that_is_none_of_them_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["test", str(EXAMPLES / "chain.lp"), "--format", "html"])
    assert "'html' is not text, json or tui" in capsys.readouterr().err


def test_help_names_only_the_new_formats(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["explain", "--help"])
    out = capsys.readouterr().out
    assert "text|json|tui" in out
    assert "full" not in out


# The keys.


def test_the_command_exits_with_its_own_code_after_the_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, _, _ = viewed(monkeypatch, "explain", str(EXAMPLES / "chain.lp"))
    assert code == Exit.CLAIM_UNMET


def test_q_quits(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "chain.lp"))

    async def act(pilot: Pilot[None]) -> None:
        await pilot.press("q")

    app = drive(view, style, act)
    assert not app.is_running


def test_moving_opening_and_closing(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "chain.lp"))
    seen: list[str] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        await pilot.press("j", "j")
        seen.append(painted(selected(app), style))
        await pilot.press("h")
        await pilot.pause()
        seen.append(painted(selected(app), style))
        node = outline_of(app).cursor_node
        assert node is not None
        await pilot.press("h")
        await pilot.pause()
        seen.append(str(node.is_expanded))
        await pilot.press("l")
        await pilot.pause()
        seen.append(str(node.is_expanded))
        await pilot.press("k")
        seen.append(painted(selected(app), style))

    drive(view, style, act)
    assert seen[0] == "evidence: @query no { reach(c), reach(d) }"
    assert seen[1].startswith("[FAIL] @query no")
    assert seen[2:4] == ["False", "True"]
    assert seen[4] == "docs/examples/chain.lp — FAIL"


def _cursor_to(app: Viewer, wanted: Callable[[Row], bool]) -> None:
    tree = outline_of(app)
    node = next(n for n in tree.shown() if n.data is not None and wanted(n.data))
    tree.reach(node)


def test_enter_on_a_step_shown_above_goes_to_its_first_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "chain.lp"))
    at: list[Row] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        _cursor_to(app, lambda row: isinstance(row.about, Again))
        await pilot.pause()
        assert isinstance(selected(app).about, Again)
        await pilot.press("enter")
        await pilot.pause()
        at.append(selected(app))

    drive(view, style, act)
    (row,) = at
    assert isinstance(row.about, Step)
    assert row.about.node.handle == "1/reach(c)"


def _counting(view: View) -> list[tuple[int, int | Limit]]:
    calls: list[tuple[int, int | Limit]] = []
    found = view.evidence

    def counted(block: int, depth: int | Limit) -> list[Row]:
        calls.append((block, depth))
        return found(block, depth)

    view.evidence = counted
    return calls


def test_plus_asks_the_library_one_step_deeper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "deep.lp"
    path.write_text("{ x }.\na :- b.\nb :- c.\nc :- x.\n")
    _, view, style = viewed(
        monkeypatch, "why", str(path), "a", "--answer-set", "1", "--max-depth", "1"
    )
    calls = _counting(view)
    texts: list[str] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        _cursor_to(app, lambda row: isinstance(row.about, Step))
        await pilot.pause()
        await pilot.press("plus")
        await pilot.pause()
        texts.extend(_normal(painted(n.data, style)) for n in outline_of(app).shown() if n.data)

    drive(view, style, act)
    assert calls == [(0, 2)]
    assert "not b no rule fires (1 candidate)" in texts
    assert "... not c not expanded (depth 2); `--max-depth` goes further" in texts


@pytest.mark.parametrize("name", EVIDENCE)
@pytest.mark.parametrize("depth", [1, 2])
def test_going_deeper_shows_what_the_text_view_shows_a_step_deeper(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], name: str, depth: int
) -> None:
    """`+` asks again a step deeper: the same counterexample, the text view's rows at that depth."""
    argv = ("explain", str(EXAMPLES / name))
    _, view, style = viewed(monkeypatch, *argv, "--max-depth", str(depth))
    blocks = [row.about.block for row in flat(view.rows) if isinstance(row.about, Block)]
    deeper = [
        row
        for block in blocks
        for row in (view.evidence(block, depth), view.evidence(block, depth + 1))[1]
    ]
    capsys.readouterr()
    main([*argv, "--max-depth", str(depth + 1), "--format", "text"])
    text = capsys.readouterr().out
    assert follows_the_text_view(deeper, style, text)
    assert [
        _normal(painted(row, style)) for row in flat(deeper) if "answer set" in painted(row, style)
    ] == [_normal(line) for line in text.splitlines() if "answer set" in line]


def test_plus_keeps_the_counterexample_it_deepens(monkeypatch: pytest.MonkeyPatch) -> None:
    """team.lp stops at depth 1; after `+` its counterexample is still answer set 1."""
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "team.lp"), "--max-depth", "1")
    shown: list[list[str]] = []

    def counterexamples(app: Viewer) -> list[str]:
        rows = (_normal(painted(n.data, style)) for n in outline_of(app).shown() if n.data)
        return [row for row in rows if "counterexample" in row]

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        shown.append(counterexamples(app))
        _cursor_to(app, lambda row: "not expanded" in painted(row, style))
        await pilot.pause()
        await pilot.press("plus")
        await settled(pilot)
        shown.append(counterexamples(app))

    drive(view, style, act)
    assert shown == [["= counterexample: answer set 1: { team(cy), team(dee) }"]] * 2


def _shows(row: Row) -> tuple[str, object]:
    """Say what a row shows: a step by its handle, as its first row or again; else its text."""
    about = row.about
    if isinstance(about, Step):
        return "step", about.node.handle
    if isinstance(about, Again):
        return "again", about.handle
    return "row", plain(row.phrase)


DEEP = "{ x }.\ne :- b.\ne :- c.\nb :- c.\nc :- x.\n"
"""Two branches that stop at depth 1; a step deeper, the first comes to `not c` too."""


@pytest.mark.parametrize(
    ("argv", "last", "stops"),
    [
        (("explain", str(EXAMPLES / "team.lp")), False, False),
        (("why", "DEEP", "e", "--answer-set", "1"), False, False),
        # The second `not c` still stops a step deeper; the cursor stays on it, not on the first.
        (("why", "DEEP", "e", "--answer-set", "1"), True, True),
        (("why", "DEEP", "b", "--answer-set", "1"), False, False),
    ],
)
def test_plus_keeps_the_cursor_on_the_step_it_deepens_with_its_rows_beneath(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    argv: tuple[str, ...],
    *,
    last: bool,
    stops: bool,
) -> None:
    path = tmp_path / "deep.lp"
    path.write_text(DEEP)
    named = tuple(str(path) if each == "DEEP" else each for each in argv)
    _, view, style = viewed(monkeypatch, *named, "--max-depth", "1")
    seen: list[object] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        tree = outline_of(app)
        stops = [n for n in tree.shown() if n.data and "not expanded" in painted(n.data, style)]
        tree.reach(stops[-1 if last else 0])
        await pilot.pause()
        before = _shows(selected(app))
        ahead = _ahead(app)
        rows = _texts(app)
        await pilot.press("plus")
        await settled(pilot)
        node = outline_of(app).cursor_node
        assert node is not None
        assert node.data is not None
        seen.extend([_shows(node.data) == before, _ahead(app) == ahead, _texts(app) != rows])
        seen.append("not expanded" in painted(node.data, style))
        shown = _pane(app)
        screen = app.screen
        assert isinstance(screen, Viewing)
        screen.cited(node.data)
        seen.append(shown == _pane(app))

    drive(view, style, act, size=(142, 37))
    assert seen == [True, True, True, stops, True]


def _ahead(app: Viewer) -> object:
    """Say what the row just above the cursor shows."""
    shown = [node for node in outline_of(app).shown() if node.line >= 0]
    at = outline_of(app).cursor_node
    above = shown[shown.index(at) - 1] if at in shown else None
    return None if above is None or above.data is None else _shows(above.data)


def _held(monkeypatch: pytest.MonkeyPatch, gate: Gate, *argv: str) -> tuple[View, Style]:
    """Keep the view's evidence from coming in until `gate` lets it through, with a row more."""
    _, view, style = viewed(monkeypatch, *argv)

    def evidence(block: int, depth: int | Limit) -> list[Row]:
        return [*gate.evidence(block, depth), Row((), (Piece("more"),))]

    view.evidence = evidence
    return view, style


def _later(monkeypatch: pytest.MonkeyPatch, gate: Gate, *argv: str) -> tuple[View, Style]:
    """Find what the view opens with at once; keep what is asked after until `gate` lets it."""
    _, view, style = viewed(monkeypatch, *argv)
    found = view.evidence
    first = [True]

    def evidence(block: int, depth: int | Limit) -> list[Row]:
        if first:
            first.clear()
        else:
            gate.evidence(block, depth)
        return found(block, depth)

    view.evidence = evidence
    return view, style


def test_the_cursor_stays_on_its_row_while_rows_arrive_above_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(EXAMPLES)
    gate = Gate(heeds=True)
    view, style = _held(monkeypatch, gate, "test", "chain.lp", "absent.lp")
    seen: list[object] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        await pilot.press("l", "j", "j", "l")
        await _started(gate)
        _cursor_to(app, lambda row: plain(row.phrase).startswith("absent.lp"))
        await pilot.pause()
        at = outline_of(app).cursor_node
        line = outline_of(app).cursor_line
        gate.through.set()
        await settled(pilot)
        seen.extend([outline_of(app).cursor_node is at, outline_of(app).cursor_line == line + 1])
        seen.append("found" in _texts(app))

    drive(view, style, act)
    assert seen == [True, True, True]


def test_a_cursor_moved_above_the_claim_while_plus_goes_deeper_is_left_there(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = Gate(heeds=True)
    view, style = _later(
        monkeypatch, gate, "explain", str(EXAMPLES / "team.lp"), "--max-depth", "1"
    )
    seen: list[object] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        _cursor_to(app, lambda row: "not expanded" in painted(row, style))
        await pilot.pause()
        await pilot.press("plus")
        await _started(gate)
        await pilot.press("home")
        at = outline_of(app).cursor_node
        gate.through.set()
        await settled(pilot)
        seen.extend([outline_of(app).cursor_node is at, outline_of(app).cursor_line])

    drive(view, style, act)
    assert seen == [True, 0]


@pytest.mark.parametrize("moved", ["searching", "= note"])
def test_a_cursor_moved_beneath_the_claim_to_a_row_not_of_a_step_goes_to_the_claim(
    monkeypatch: pytest.MonkeyPatch, moved: str
) -> None:
    gate = Gate(heeds=True)
    view, style = _later(
        monkeypatch, gate, "explain", str(EXAMPLES / "team.lp"), "--max-depth", "1"
    )
    seen: list[object] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        _cursor_to(app, lambda row: "not expanded" in painted(row, style))
        await pilot.pause()
        await pilot.press("plus")
        await _started(gate)
        tree = outline_of(app)
        tree.reach(next(n for n in tree.shown() if str(n.label).startswith(moved)))
        await pilot.pause()
        gate.through.set()
        await settled(pilot)
        seen.append(selected(app).about)

    drive(view, style, act)
    assert seen == [Block(0)]


THREE = ("optimum.lp", "absent.lp", "chain.lp")


@pytest.mark.parametrize(
    ("order", "at", "keys", "then"),
    [
        (THREE, "chain.lp", (), "chain.lp"),
        (THREE, "absent.lp", (), "absent.lp"),
        (THREE, "optimum.lp", (), "absent.lp"),
        (THREE, "optimum.lp", ("l", "j"), "absent.lp"),
        (("absent.lp", "chain.lp", "optimum.lp"), "optimum.lp", (), "chain.lp"),
        (("absent.lp", "chain.lp", "optimum.lp"), "optimum.lp", ("l", "j"), "chain.lp"),
    ],
)
def test_f_keeps_the_cursor_on_its_source_or_moves_it_to_the_next_that_failed(
    monkeypatch: pytest.MonkeyPatch,
    order: tuple[str, ...],
    at: str,
    keys: tuple[str, ...],
    then: str,
) -> None:
    monkeypatch.chdir(EXAMPLES)
    _, view, style = viewed(monkeypatch, "test", *order)
    seen: list[str] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        _cursor_to(app, lambda row: plain(row.phrase).startswith(at))
        await pilot.pause()
        await pilot.press(*keys)
        await pilot.press("f")
        await pilot.pause()
        seen.append(plain(selected(app).phrase).split()[0])
        await pilot.press("f")
        await pilot.pause()
        seen.append(plain(selected(app).phrase).split()[0])

    drive(view, style, act)
    assert seen == [then, then]


def test_e_keeps_the_cursor_on_its_row_as_every_claim_is_found_and_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(EXAMPLES)
    _, view, style = viewed(monkeypatch, "test", *THREE)
    seen: list[object] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        _cursor_to(app, lambda row: plain(row.phrase).startswith("chain.lp"))
        await pilot.pause()
        at = outline_of(app).cursor_node
        await pilot.press("e")
        await settled(pilot)
        seen.extend([outline_of(app).cursor_node is at, outline_of(app).cursor_line])
        seen.append(sum(1 for node in outline_of(app).shown() if node.is_expanded) > len(THREE))

    drive(view, style, act)
    assert seen[0] is True
    assert seen[2] is True
    assert isinstance(seen[1], int)
    assert seen[1] > len(THREE) - 1


def test_plus_on_a_complete_explanation_says_there_is_nothing_deeper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, view, style = viewed(
        monkeypatch, "why", str(EXAMPLES / "chain.lp"), "reach(d)", "--answer-set", "1"
    )
    calls = _counting(view)

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        _cursor_to(app, lambda row: isinstance(row.about, Step))
        await pilot.pause()
        await pilot.press("plus")
        await pilot.pause()

    app = drive(view, style, act)
    assert calls == []
    assert app._notifications  # noqa: SLF001


def test_test_finds_a_claims_evidence_only_when_it_is_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, view, style = viewed(monkeypatch, "test", str(EXAMPLES / "chain.lp"))
    calls = _counting(view)
    before: list[int] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        await pilot.press("l", "j", "j")
        before.append(len(calls))
        assert isinstance(selected(app).about, Block)
        await pilot.press("l")
        await pilot.pause()

    drive(view, style, act)
    claim = next(row for row in flat(view.rows) if isinstance(row.about, Block))
    assert isinstance(claim.about, Block)
    assert before == [0]
    assert calls == [(claim.about.block, cli.DEFAULT_MAX_DEPTH)]
    assert painted(claim.children[0], style) == "evidence: @query no { reach(c), reach(d) }"


def test_e_finds_every_failed_claims_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "test", str(EXAMPLES))
    calls = _counting(view)

    async def act(pilot: Pilot[None]) -> None:
        await pilot.press("e")
        await settled(pilot)

    drive(view, style, act)
    claims = [row.about.block for row in flat(view.rows) if isinstance(row.about, Block)]
    assert sorted(block for block, _ in calls) == claims
    assert len(claims) > 1


def test_esc_closes_the_find_box_and_then_quits(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "chain.lp"))
    states: list[tuple[bool, bool]] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        await pilot.press("slash", "escape")
        await pilot.pause()
        states.append((app.is_running, app.screen.query_one("#find").display))
        await pilot.press("escape")
        await pilot.pause()
        states.append((app.is_running, False))

    drive(view, style, act)
    assert states == [(True, False), (False, False)]


def test_f_and_e_are_offered_only_where_the_rows_are_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, view, style = viewed(
        monkeypatch, "why", str(EXAMPLES / "absent.lp"), "access(ann,db)", "--answer-set", "1"
    )
    offered: list[set[str]] = []
    counts: list[int] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        offered.append({binding.action for _, binding, *_ in app.active_bindings.values()})
        counts.append(len(list(outline_of(app).shown())))
        await pilot.press("f", "e")
        await pilot.pause()
        counts.append(len(list(outline_of(app).shown())))

    drive(view, style, act)
    assert not offered[0] & {"failures", "every"}
    assert {"spans", "find"} <= offered[0]
    assert counts[0] == counts[1]


def test_f_shows_only_the_sources_that_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "test", str(EXAMPLES))
    counts: list[int] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        for _ in range(2):
            counts.append(len(outline_of(app).root.children))
            await pilot.press("f")
            await pilot.pause()
        counts.append(len(outline_of(app).root.children))

    drive(view, style, act)
    passed = sum(1 for row in view.rows if painted(row, style).endswith("PASS"))
    assert counts == [len(view.rows), len(view.rows) - passed, len(view.rows)]


def test_slash_finds_a_literal_and_n_the_next(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "chain.lp"))
    found: list[str] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        await pilot.press("slash", *"edge(", "enter")
        await pilot.pause()
        found.append(painted(selected(app), style))
        await pilot.press("n")
        await pilot.pause()
        found.append(painted(selected(app), style))

    drive(view, style, act)
    assert found[0].startswith("open(a,b) :- edge(a,b)")
    assert found[1].startswith("edge(a,b)")


def test_a_needle_found_nowhere_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "chain.lp"))

    async def act(pilot: Pilot[None]) -> None:
        await pilot.press("slash", *"zzz", "enter")
        await pilot.pause()

    assert drive(view, style, act)._notifications  # noqa: SLF001


@pytest.mark.parametrize(("width", "shown"), [(99, False), (100, True)])
def test_the_pane_shows_from_100_columns_and_s_toggles_it(
    monkeypatch: pytest.MonkeyPatch, width: int, shown: bool
) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "chain.lp"))
    states: list[bool] = []

    async def act(pilot: Pilot[None]) -> None:
        pane = pilot.app.screen.query_one("#pane")
        states.append(pane.display)
        await pilot.press("s")
        states.append(pane.display)

    drive(view, style, act, size=(width, 30))
    assert states == [shown, not shown]


def test_the_pane_shows_the_selected_steps_rule_as_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "chain.lp"))
    content: list[list[str]] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        _cursor_to(app, lambda row: isinstance(row.about, Step))
        await pilot.pause()
        content.append(_pane(app))

    drive(view, style, act)
    assert content[0] == [
        "= docs/examples/chain.lp:8: reach(Y) :- reach(X), open(X,Y). {X=b, Y=c}",
        "  |",
        "8 | reach(Y) :- reach(X), open(X,Y).",
        "  | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^",
    ]


def _pane(app: Viewer) -> list[str]:
    """Read the pane: the rule as written, then its line quoted."""
    parts = (app.screen.query_one(f"#{part}", Static) for part in ("cited", "quote"))
    return [line for part in parts for line in str(part.render()).splitlines()]


def _spans_line(capsys: pytest.CaptureFixture[str], *argv: str) -> list[str]:
    """Write the evidence as the text view does with `--spans`, keeping each rule as written."""
    capsys.readouterr()
    main([*argv, "--spans", "--format", "text"])
    return [
        line.split("= ", 1)[1] for line in capsys.readouterr().out.splitlines() if " = " in line
    ]


def test_the_pane_on_a_step_is_the_rule_the_text_view_writes_beneath_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ("why", str(EXAMPLES / "absent.lp"), "not access(ann,db)", "--answer-set", "1")
    _, view, style = viewed(monkeypatch, *argv)
    seen: list[list[str]] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        _cursor_to(app, lambda row: isinstance(row.about, Step) and "blocked" in plain(row.words))
        await pilot.pause()
        seen.append(_pane(app))

    drive(view, style, act)
    (content,) = seen
    written = next(line for line in _spans_line(capsys, *argv) if line.startswith("docs/"))
    rule = "access(U,R) :- role(U,X), permits(X,R), not suspended(U)."
    assert content == [f"= {written}", "  |", f"6 | {rule}", f"  | {'^' * len(rule)}"]


def test_the_pane_on_a_heading_shows_the_first_rule_cited_beneath_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "chain.lp"))
    seen: list[list[str]] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        seen.append(_pane(app))
        _cursor_to(app, lambda row: plain(row.phrase).startswith("= note"))
        await pilot.pause()
        seen.append(_pane(app))

    drive(view, style, act)
    content, below = seen
    assert content[:2] == [
        BENEATH,
        "= docs/examples/chain.lp:8: reach(Y) :- reach(X), open(X,Y). {X=b, Y=c}",
    ]
    assert below == [NO_STEP]


def _starting(word: str) -> Callable[[Row], bool]:
    """Pick the row whose phrase starts with `word`, after any number it is listed by."""
    return lambda row: re.match(rf"[\d ]*{re.escape(word)}", plain(row.phrase)) is not None


def test_the_pane_on_how_the_objective_ranks_a_claim_quotes_the_weak_constraints_it_pays(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The cost rows cite no rule: the pane quotes each weak constraint paid, as the text does."""
    argv = ("explain", str(EXAMPLES / "laptop.lp"))
    _, view, style = viewed(monkeypatch, *argv)
    capsys.readouterr()
    main([*argv, "--format", "text"])
    text = capsys.readouterr().out.splitlines()
    start = next(at for at, line in enumerate(text) if line.strip().endswith(PAID))
    quotes = text[start + 1 : start + 9]
    seen: list[list[str]] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        for wanted in ("cost", "optimum", "-->"):
            _cursor_to(app, _starting(wanted))
            await pilot.pause()
            seen.append(_pane(app))

    drive(view, style, act, size=(160, 40))
    cost, optimum, first = seen
    assert cost == optimum == [PAID, *(line.rstrip() for line in quotes)]
    assert first == [PAID, *(line.rstrip() for line in quotes[:4])]


def test_the_pane_takes_in_the_evidence_once_it_is_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = Gate(heeds=True)
    _, view, style = viewed(monkeypatch, "test", str(EXAMPLES / "chain.lp"))
    found = view.evidence

    def evidence(block: int, depth: int | Limit) -> list[Row]:
        gate.started.set()
        gate.through.wait(5)
        return found(block, depth)

    view.evidence = evidence
    seen: list[str] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        await pilot.press("l", "j", "j", "l")
        await _started(gate)
        seen.append(_pane(app)[0])
        gate.through.set()
        await settled(pilot)
        seen.append(_pane(app)[1])

    drive(view, style, act)
    assert seen[0] == NO_STEP
    assert seen[1].startswith("= docs/examples/chain.lp:8: reach(Y)")


def test_enter_on_an_answer_set_asks_why_and_escape_comes_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, view, style = viewed(monkeypatch, "ask", str(EXAMPLES / "team.lp"), "team(ann)")
    titles: list[str] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        await pilot.press("j", "j", "enter")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, Viewing)
        titles.append(_normal(painted(screen.view.rows[0], style)))
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, Viewing)
        titles.append(_normal(painted(app.screen.view.rows[0], style)))

    drive(view, style, act)
    assert titles == ["why: team(ann)", "ask: { team(ann) }"]


def test_enter_on_an_answer_set_a_warrant_names_asks_why_under_its_assumptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv = ("why", str(EXAMPLES / "team.lp"), "team(ann)", "--assuming", "not team(dee)")
    _, view, style = viewed(monkeypatch, *argv)
    seen: list[str] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        await pilot.press("j", "j", "enter")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, Viewing)
        seen.extend(_normal(painted(row, style)) for row in flat(screen.view.rows))

    drive(view, style, act)
    assert seen[0] == "why: team(ann)"
    assert not any("dee" in line for line in seen if "answer set" in line)


@pytest.mark.parametrize(
    ("argv", "absent"),
    [
        (("explain", str(EXAMPLES / "chain.lp")), set[str]()),
        (("why", str(EXAMPLES / "absent.lp"), "access(ann,db)", "--answer-set", "1"), {"f", "e"}),
        (("ask", str(EXAMPLES / "team.lp"), "team(ann)"), {"f", "e", "s", "+"}),
    ],
)
def test_question_mark_shows_the_keys_that_apply_in_the_legends_words(
    monkeypatch: pytest.MonkeyPatch, argv: tuple[str, ...], absent: set[str]
) -> None:
    _, view, style = viewed(monkeypatch, *argv)
    shown: list[list[str]] = []
    keys: list[set[str]] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        await pilot.press("question_mark")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, Keys)
        lines = str(screen.query_one("#keys", Static).render()).splitlines()
        keys.append({line[: max(len(key) for key in PRESSED.values())].strip() for line in lines})
        shown.append([line.split("  ", 1)[1].strip() for line in lines])
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, Viewing)

    drive(view, style, act)
    offered = [action for action in KEYS if PRESSED[action] not in absent]
    assert shown == [[KEYS[action] for action in offered]]
    assert keys == [{PRESSED[action] for action in offered}]


def test_the_window_is_titled_by_the_command_and_its_file(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "chain.lp"))
    titles: list[str] = []

    async def act(pilot: Pilot[None]) -> None:
        titles.extend([pilot.app.title, pilot.app.screen.title or ""])

    drive(view, style, act)
    assert titles == ["elenctic explain · docs/examples/chain.lp"] * 2


def test_the_window_is_titled_by_the_view_shown(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "ask", str(EXAMPLES / "team.lp"), "team(ann)")
    titles: list[str] = []

    async def act(pilot: Pilot[None]) -> None:
        await pilot.press("j", "j", "enter")
        await settled(pilot)
        titles.append(pilot.app.title)
        await pilot.press("escape")
        await pilot.pause()
        titles.append(pilot.app.title)

    drive(view, style, act)
    assert titles == [
        "elenctic why · docs/examples/team.lp",
        "elenctic ask · docs/examples/team.lp",
    ]


def test_q_quits_from_the_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "chain.lp"))

    async def act(pilot: Pilot[None]) -> None:
        await pilot.press("question_mark", "q")

    assert not drive(view, style, act).is_running


@pytest.mark.parametrize(
    ("color", "quiet"), [(Color.ON, "ansi_bright_black"), (Color.OFF, "ansi_default")]
)
def test_the_views_own_parts_take_the_legends_roles(color: Color, quiet: str) -> None:
    built = theme(color)
    assert built.ansi, "the view keeps the terminal's own palette, as the text view does"
    assert built.variables["footer-key-foreground"] == (
        "ansi_cyan" if color is Color.ON else "ansi_default"
    )
    assert built.variables["border"] == ("ansi_blue" if color is Color.ON else "ansi_default")
    assert built.variables["scrollbar"] == quiet
    assert (built.error, built.warning, built.success) == (
        ("ansi_red", "ansi_yellow", "ansi_green") if color is Color.ON else ("ansi_default",) * 3
    )


def test_each_role_takes_the_colour_the_text_view_paints_it_in() -> None:
    assert {role: _colored(role) for role in Role} == {
        Role.ERROR: "ansi_red",
        Role.WARNING: "ansi_yellow",
        Role.NOTE: "ansi_green",
        Role.HELP: "ansi_cyan",
        Role.MARGIN: "ansi_blue",
        Role.EMPHASIS: "ansi_default",
        Role.ASIDE: "ansi_default",
        Role.REFERENCE: "ansi_default",
    }


def test_the_app_wears_the_legends_theme(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "--color", "always", "explain", str(EXAMPLES / "chain.lp"))
    themes: list[str] = []

    async def act(pilot: Pilot[None]) -> None:
        themes.append(pilot.app.theme)

    drive(view, style, act)
    assert themes == [THEME]


def test_f_keeps_the_rows_it_does_not_hide_as_they_are(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "test", str(EXAMPLES))
    kept: list[bool] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        tree = outline_of(app)
        failed = next(n for n in tree.root.children if n.data and n.data.opened is False)
        failed.expand()
        await pilot.pause()
        before = list(tree.root.children)
        await pilot.press("f", "f")
        await pilot.pause()
        after = list(tree.root.children)
        kept.append(failed in after and failed.is_expanded)
        kept.append([n.data for n in before] == [n.data for n in after])

    drive(view, style, act)
    assert kept == [True, True]


# The library calls, off the UI thread.


class Gate:
    """A library call that takes as long as the test says: until it is let through, or stopped."""

    def __init__(self, *, heeds: bool) -> None:
        self.through = threading.Event()
        self.started = threading.Event()
        self.ended = threading.Event()
        self.heeds = heeds
        """Whether the call ends when it is stopped, as a search does, or only when let through."""
        self.calls = 0

    def evidence(self, _block: int, _depth: int | Limit) -> list[Row]:
        self.calls += 1
        self.started.set()
        while not self.through.wait(0.01):
            if self.heeds and Calls().pulled:
                break
        self.ended.set()
        return [Row((), (Piece("found"),))]


async def _started(gate: Gate) -> None:
    await asyncio.to_thread(gate.started.wait)


def _gated(monkeypatch: pytest.MonkeyPatch, gate: Gate) -> tuple[View, Style]:
    _, view, style = viewed(monkeypatch, "test", str(EXAMPLES / "chain.lp"))
    view.evidence = gate.evidence
    return view, style


def _texts(app: Viewer) -> list[str]:
    return [str(node.label) for node in outline_of(app).shown()]


def test_the_keys_answer_while_the_library_is_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = Gate(heeds=True)
    view, style = _gated(monkeypatch, gate)
    seen: list[object] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        await pilot.press("l", "j", "j", "l")
        await _started(gate)
        line = outline_of(app).cursor_line
        await pilot.press("k")
        seen.extend([outline_of(app).cursor_line == line - 1, gate.ended.is_set()])
        seen.append(SEARCHING in _texts(app))
        seen.append(plain(PENDING) in str(app.screen.query_one("#title", Static).render()))
        gate.through.set()
        await settled(pilot)
        seen.append("found" in _texts(app))
        seen.append(SEARCHING in _texts(app))

    drive(view, style, act)
    assert seen == [True, False, True, True, True, False]


def test_esc_cancels_the_call_and_nothing_it_found_is_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = Gate(heeds=True)
    view, style = _gated(monkeypatch, gate)
    seen: list[object] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        await pilot.press("l", "j", "j", "l")
        await _started(gate)
        await pilot.press("escape")
        await settled(pilot)
        seen.extend([app.is_running, gate.ended.is_set(), gate.through.is_set()])
        seen.extend([any(t in _texts(app) for t in ("found", SEARCHING)), app.searches])
        seen.append([n.message for n in app._notifications])  # noqa: SLF001

    drive(view, style, act)
    assert seen == [True, True, False, False, [], [CANCELLED]]
    claim = next(row for row in flat(view.rows) if isinstance(row.about, Block))
    assert claim.children == []


def test_a_call_cancelled_before_it_ends_is_never_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = Gate(heeds=False)
    view, style = _gated(monkeypatch, gate)
    seen: list[object] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        await pilot.press("l", "j", "j", "l")
        await _started(gate)
        await pilot.press("escape")
        await pilot.pause()
        gate.through.set()
        await settled(pilot)
        seen.extend([gate.ended.is_set(), "found" in _texts(app)])
        await pilot.press("l")
        await settled(pilot)
        seen.extend([gate.calls, "found" in _texts(app)])

    drive(view, style, act)
    assert seen == [True, False, 2, True]


def test_ctrl_c_quits_while_the_library_is_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = Gate(heeds=True)
    view, style = _gated(monkeypatch, gate)

    async def act(pilot: Pilot[None]) -> None:
        await pilot.press("l", "j", "j", "l")
        await _started(gate)
        await pilot.press("ctrl+c")

    started = time.monotonic()
    app = drive(view, style, act)
    assert not app.is_running
    assert gate.ended.wait(1)
    assert not gate.through.is_set()
    assert time.monotonic() - started < 5


def test_explain_finds_the_evidence_of_each_claim_it_opens_once_it_is_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "chain.lp"))
    claim = next(row for row in flat(view.rows) if isinstance(row.about, Block))
    assert claim.children == []
    calls = _counting(view)

    async def act(pilot: Pilot[None]) -> None:
        del pilot

    drive(view, style, act)
    assert calls == [(0, cli.DEFAULT_MAX_DEPTH)]
    assert painted(claim.children[0], style) == "evidence: @query no { reach(c), reach(d) }"


def test_explain_finds_evidence_with_the_libraries_the_case_was_checked_with(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The view finds evidence again; it must load what `--with` loaded, as the check did."""
    lines = (EXAMPLES / "chain.lp").read_text().splitlines(keepends=True)
    base, case = tmp_path / "base.lp", tmp_path / "case.lp"
    base.write_text("".join(lines[:-2]))
    case.write_text("".join(lines[-2:]))
    shown: list[list[str]] = []
    for argv in (
        ["explain", str(case), "--with", str(base)],
        ["explain", str(EXAMPLES / "chain.lp")],
    ):
        _, view, style = viewed(monkeypatch, *argv)
        claim = next(row for row in flat(view.rows) if isinstance(row.about, Block))

        async def act(pilot: Pilot[None]) -> None:
            del pilot

        drive(view, style, act)
        shown.append([painted(row, style) for row in flat(claim.children)])
    with_base, whole = shown
    assert with_base == [re.sub(r"\bline (\d+)", rf"{base}:\1", line) for line in whole]
    assert "reach(c) :- reach(b), open(b,c).  line 8" in whole
    assert f"reach(c) :- reach(b), open(b,c).  {base}:8" in with_base


def test_why_from_an_answer_finds_it_with_the_libraries_and_root_ask_was_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    (project / "encodings").mkdir(parents=True)
    (project / "scenarios").mkdir()
    (tmp_path / "shared.lp").write_text("big :- num(2).\n")
    base = project / "encodings" / "base.lp"
    base.write_text("num(1..2).\n")
    case = project / "scenarios" / "case.lp"
    case.write_text('#include "../../shared.lp".\n')
    argv = ["ask", str(case), "num(2)", "--with", str(base), "--root", str(tmp_path)]
    _, view, style = viewed(monkeypatch, *argv)
    made = view.why
    assert made is not None
    explained = made(Asking(Literal.parse("num(2)"), 1))
    shown = [painted(row, style) for row in flat(explained.rows)]
    assert f"num(2)  fact, {base}:1" in shown, shown


def test_enter_again_while_why_is_being_found_asks_nothing_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, view, style = viewed(monkeypatch, "ask", str(EXAMPLES / "team.lp"), "team(ann)")
    made = view.why
    assert made is not None
    gate = threading.Event()
    asked: list[Asking] = []

    def slow(asking: Asking) -> View:
        asked.append(asking)
        gate.wait(5)
        return made(asking)

    view.why = slow
    screens: list[int] = []

    async def act(pilot: Pilot[None]) -> None:
        await pilot.press("j", "j", "enter", "enter")
        gate.set()
        await settled(pilot)
        screens.append(len(pilot.app.screen_stack))
        await pilot.press("escape")
        await pilot.pause()
        screens.append(len(pilot.app.screen_stack))
        await pilot.press("enter")
        await settled(pilot)
        screens.append(len(pilot.app.screen_stack))

    drive(view, style, act)
    assert len(asked) == 2
    assert screens == [3, 2, 3]


def test_a_call_stops_only_the_search_its_own_thread_makes() -> None:
    interrupt = Calls()
    stop = threading.Event()
    seen: list[bool] = []

    def asked() -> None:
        seen.append(interrupt.pulled)

    stop.set()
    call(asked, stop)
    asked()
    worker = threading.Thread(target=call, args=(asked, threading.Event()))
    worker.start()
    worker.join()
    interrupt.pull()
    asked()
    assert seen == [True, False, False, True]


# The layout, as snapshots.

SNAPSHOTS = [
    *(("explain", str(EXAMPLES / name)) for name in EVIDENCE),
    ("why", str(EXAMPLES / "absent.lp"), "not access(ann,db)", "--answer-set", "1"),
    ("ask", str(EXAMPLES / "team.lp"), "team(ann)"),
]
"""The five examples of evidence, and a `why` and an `ask`."""


WRITTEN_BY: Final = (1, 1)
"""The pytest-textual-snapshot that wrote the snapshots. PyPI's 1.1 pins syrupy 4.8, which predates
pytest 9, so uv resolves 1.0, which names and writes snapshots its own way; conda-forge has 1.1."""


@pytest.mark.skipif(
    tuple(map(int, version("pytest-textual-snapshot").split(".")[:2])) < WRITTEN_BY,
    reason="the snapshots are written by pytest-textual-snapshot 1.1",
)
@pytest.mark.parametrize("argv", SNAPSHOTS, ids=lambda argv: "-".join(argv[:2]).replace("/", "_"))
@pytest.mark.parametrize("color", ["never", "always"])
def test_the_layout_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    snap_compare: Callable[..., bool],
    argv: tuple[str, ...],
    color: str,
) -> None:
    if argv[1].endswith("late.lp"):
        pytest.importorskip("clingcon")
    _, view, style = viewed(monkeypatch, "--color", color, *argv)
    if color == "never":
        monkeypatch.setenv("NO_COLOR", "1")
    assert snap_compare(Viewer(view, style), terminal_size=(110, 32), run_before=settled)


@pytest.mark.skipif(
    tuple(map(int, version("pytest-textual-snapshot").split(".")[:2])) < WRITTEN_BY,
    reason="the snapshots are written by pytest-textual-snapshot 1.1",
)
def test_the_pane_on_a_step_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, snap_compare: Callable[..., bool]
) -> None:
    _, view, style = viewed(
        monkeypatch, "--color", "always", "explain", str(EXAMPLES / "laptop.lp")
    )

    async def on_a_step(pilot: Pilot[None]) -> None:
        await settled(pilot)
        app = pilot.app
        assert isinstance(app, Viewer)
        _cursor_to(app, lambda row: isinstance(row.about, Step) and "chosen" in plain(row.words))
        await pilot.pause()

    assert snap_compare(Viewer(view, style), terminal_size=(140, 32), run_before=on_a_step)


# What each key leaves behind.

PASSES = "p.\n% @expect sat\n"
FAILS = "p.\n% @expect unsat\n"


def _sources(tmp_path: Path, programs: dict[str, str]) -> Path:
    for name, program in programs.items():
        (tmp_path / name).write_text(program)
    return tmp_path


def _messages(app: Viewer) -> list[str]:
    return [str(each.message) for each in app._notifications]  # noqa: SLF001


def test_plus_brings_the_deeper_rows_to_the_block_they_belong_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "deep.lp"
    path.write_text("{ x }.\na :- b.\nb :- c.\nc :- x.\n")
    _, view, style = viewed(
        monkeypatch, "why", str(path), "a", "--answer-set", "1", "--max-depth", "1"
    )
    seen: list[object] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        _cursor_to(app, lambda row: isinstance(row.about, Step))
        await pilot.pause()
        before = _shows(selected(app))
        await pilot.press("plus")
        await settled(pilot)
        seen.extend([_shows(selected(app)) == before, _messages(app)])
        (top,) = outline_of(app).root.children
        seen.append(
            [child.data for child in top.children] == top.data.children if top.data else None
        )

    drive(view, style, act)
    assert seen == [True, [], True]


def test_plus_again_while_the_library_goes_deeper_asks_it_nothing_more(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "deep.lp"
    path.write_text("{ x }.\na :- b.\nb :- c.\nc :- x.\n")
    _, view, style = viewed(
        monkeypatch, "why", str(path), "a", "--answer-set", "1", "--max-depth", "1"
    )
    gate = Gate(heeds=True)
    view.evidence = gate.evidence
    seen: list[object] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        _cursor_to(app, lambda row: isinstance(row.about, Step))
        await pilot.pause()
        await pilot.press("plus")
        await _started(gate)
        await pilot.press("plus")
        await pilot.pause()
        seen.extend([gate.calls, _messages(app)])
        gate.through.set()
        await settled(pilot)

    drive(view, style, act)
    assert seen == [1, []]


def test_plus_where_no_step_is_selected_says_there_is_nothing_deeper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    passing = str(_sources(tmp_path, {"a.lp": PASSES}))
    for argv, keys in (
        (("why", str(EXAMPLES / "chain.lp"), "reach(d)", "--answer-set", "1"), ("plus",)),
        (("test", passing), ("f", "plus")),
    ):
        _, view, style = viewed(monkeypatch, *argv)
        calls = _counting(view)
        said: list[list[str]] = []

        async def act(
            pilot: Pilot[None], keys: tuple[str, ...] = keys, said: list[list[str]] = said
        ) -> None:
            app = pilot.app
            assert isinstance(app, Viewer)
            await pilot.press(*keys)
            await pilot.pause()
            said.append(_messages(app))

        drive(view, style, act)
        assert (calls, said) == ([], [[NOTHING_DEEPER]])


def test_h_on_a_closed_source_stays_on_it(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "chain.lp"))
    seen: list[object] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        await pilot.press("h", "h")
        await pilot.pause()
        seen.extend([outline_of(app).cursor_line, painted(selected(app), style)])

    drive(view, style, act)
    assert seen == [0, "docs/examples/chain.lp — FAIL"]


def test_e_leaves_a_step_closed_where_it_was_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "chain.lp"))
    seen: list[bool] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        _cursor_to(app, lambda row: isinstance(row.about, Step) and bool(row.children))
        await pilot.pause()
        await pilot.press("h")
        await pilot.pause()
        node = outline_of(app).cursor_node
        assert node is not None
        await pilot.press("e")
        await settled(pilot)
        seen.append(node.is_expanded)

    drive(view, style, act)
    assert seen == [False]


def test_f_twice_puts_back_each_source_in_its_place_open_or_closed_as_it_was(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    names = {"a.lp": PASSES, "b.lp": PASSES, "c.lp": FAILS, "d.lp": PASSES, "e.lp": PASSES}
    _, view, style = viewed(monkeypatch, "test", str(_sources(tmp_path, names)))
    seen: list[object] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        tree = outline_of(app)
        first, second = tree.root.children[0], tree.root.children[1]
        await pilot.press("l", "j", "j", "l")
        await pilot.pause()
        await pilot.press("h")
        await pilot.pause()
        seen.append([first.is_expanded, second.is_expanded])
        await pilot.press("f", "f")
        await pilot.pause()
        seen.append([n.data for n in tree.root.children] == view.rows)
        again = tree.root.children
        seen.append([again[0].is_expanded, again[1].is_expanded])

    drive(view, style, act)
    assert seen == [[True, False], True, [True, False]]


def test_the_find_box_closes_once_its_needle_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "chain.lp"))
    shown: list[bool] = []

    async def act(pilot: Pilot[None]) -> None:
        await pilot.press("slash")
        shown.append(pilot.app.screen.query_one("#find").display)
        await pilot.press(*"edge(", "enter")
        await pilot.pause()
        shown.append(pilot.app.screen.query_one("#find").display)

    drive(view, style, act)
    assert shown == [True, False]


def test_a_click_selects_a_row_and_leaves_opening_it_to_the_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, view, style = viewed(monkeypatch, "test", str(EXAMPLES / "chain.lp"))
    seen: list[bool] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        (source,) = outline_of(app).root.children
        seen.append(source.is_expanded)
        await pilot.click(Outline, offset=(12, 0))
        await pilot.pause()
        seen.append(source.is_expanded)

    drive(view, style, act)
    assert seen == [False, False]


def _pane_width(view: View, style: Style, size: tuple[int, int]) -> int:
    widths: list[int] = []

    async def act(pilot: Pilot[None]) -> None:
        width = pilot.app.screen.query_one("#pane").styles.width
        assert width is not None
        widths.append(int(width.value))

    drive(view, style, act, size=size)
    return widths[0]


def test_the_pane_is_at_most_its_widest_on_a_wide_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "laptop.lp"))
    assert _pane_width(view, style, (160, 40)) == PANE.stop - 1


@pytest.mark.parametrize(
    ("name", "pane"), [("h" * 63 + ".lp", 120 - 73 - 4), ("h" * 150 + ".lp", PANE.start)]
)
def test_the_pane_gives_way_to_a_long_heading_down_to_its_least(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, pane: int
) -> None:
    monkeypatch.chdir(tmp_path)
    Path(name).write_text(FAILS)
    _, view, style = viewed(monkeypatch, "explain", name)
    assert [len(painted(row, style)) for row in view.rows] == [len(name) + len(" — FAIL")]
    assert _pane_width(view, style, (120, 40)) == pane


def test_a_narrow_title_keeps_a_space_before_its_status(monkeypatch: pytest.MonkeyPatch) -> None:
    _, view, style = viewed(monkeypatch, "explain", str(EXAMPLES / "laptop.lp"))
    titles: list[str] = []

    async def act(pilot: Pilot[None]) -> None:
        titles.append(str(pilot.app.screen.query_one("#title", Static).render()))

    drive(view, style, act, size=(50, 20))
    assert titles[0].endswith("… 0/1 passed, 1 fail")


@pytest.mark.parametrize(
    ("asked", "heading"),
    [("not access(ann,db)", "why: not access(ann,db)"), ("access(ann,db)", "why: access(ann,db)")],
)
def test_why_is_headed_by_the_atom_as_it_was_asked(
    monkeypatch: pytest.MonkeyPatch, asked: str, heading: str
) -> None:
    _, view, style = viewed(
        monkeypatch, "why", str(EXAMPLES / "absent.lp"), asked, "--answer-set", "1"
    )
    assert painted(view.rows[0], style) == heading


@pytest.mark.parametrize("color", ["always", "never"])
def test_the_selected_row_is_reversed_and_each_piece_keeps_its_roles_colour(
    monkeypatch: pytest.MonkeyPatch, color: str
) -> None:
    """A bar of one colour hid a piece of that colour; reversed, each reads as it did."""
    _, view, style = viewed(monkeypatch, "--color", color, "explain", str(EXAMPLES / "chain.lp"))
    found: list[tuple[str, str | None, bool | None]] = []

    async def act(pilot: Pilot[None]) -> None:
        app = pilot.app
        assert isinstance(app, Viewer)
        outline = outline_of(app)
        node = outline.cursor_node
        assert node is not None
        selected = outline.get_component_rich_style("tree--cursor", partial=False)
        label = outline.render_label(node, Look(), selected)
        found.extend(
            (each.text, each.style.color and each.style.color.name, each.style.reverse)
            for each in label.render(app.console)
            if each.text.strip() and each.style is not None
        )

    drive(view, style, act)
    pieces = {text: (hue, reverse) for text, hue, reverse in found if text != "▼ "}
    assert pieces
    assert all(reverse for _, reverse in pieces.values())
    painted_in = {hue for hue, _ in pieces.values()}
    assert painted_in == ({"default", "color(1)"} if color == "always" else {"default"})


FIVE = ("chain.lp", "absent.lp", "laptop.lp", "team.lp", "optimum.lp")


@pytest.mark.parametrize("width", [20, 30, 60, 78, 142])
def test_a_title_too_long_is_cut_short_and_the_tally_kept_whole(
    monkeypatch: pytest.MonkeyPatch, width: int
) -> None:
    monkeypatch.chdir(EXAMPLES)
    _, view, style = viewed(monkeypatch, "test", *FIVE)
    titles: list[str] = []

    async def act(pilot: Pilot[None]) -> None:
        titles.append(str(pilot.app.screen.query_one("#title", Static).render()))

    drive(view, style, act, size=(width, 20))
    (title,) = titles
    whole = "elenctic test · " + " ".join(FIVE)
    tally = "1/5 passed, 4 fail"
    assert title.endswith(f" {tally}")
    assert len(title) == width
    head = title.removesuffix(tally).rstrip()
    assert head == whole if len(whole) + 1 + len(tally) <= width else head.endswith("…")
    assert whole.startswith(head.removesuffix("…"))


@pytest.mark.parametrize("width", [12, 19])
def test_a_title_with_no_room_beside_the_tally_is_left_out(
    monkeypatch: pytest.MonkeyPatch, width: int
) -> None:
    monkeypatch.chdir(EXAMPLES)
    _, view, style = viewed(monkeypatch, "test", *FIVE)
    titles: list[str] = []

    async def act(pilot: Pilot[None]) -> None:
        titles.append(str(pilot.app.screen.query_one("#title", Static).render()))

    drive(view, style, act, size=(width, 20))
    assert [title.strip() for title in titles] == ["1/5 passed, 4 fail"]
