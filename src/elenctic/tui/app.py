"""The interactive view: a tree of what the library returned, and a pane for the selected step.

Display only. Going deeper, opening a claim's evidence and asking `why` of an answer set call the
library through the view's callables; nothing here finds evidence. Each call is made off the UI
thread, one at a time, so the keys answer while it runs and `esc` cancels it.
"""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from functools import partial
from threading import Event
from typing import ClassVar, Final, override

from rich.style import Style as Look
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Input, Static, Tree

from elenctic.explanation import Handle, Rule
from elenctic.glyphs import Glyphs
from elenctic.legend import (
    BENEATH,
    CANCELLED,
    FIND,
    KEYS,
    NO_STEP,
    NOT_FOUND,
    NOTHING_DEEPER,
    PAID,
    PENDING,
    PRESSED,
    SEARCHING,
    cited,
    keyed,
    paying,
    quoted,
    written,
)
from elenctic.paint import Color, Phrase, Piece, Role, plain
from elenctic.presentation import Style
from elenctic.search import Limit
from elenctic.tui.calls import call
from elenctic.tui.outline import Again, Asking, Block, Lines, Paying, Row, Step
from elenctic.tui.places import (
    Node,
    found_at,
    has_failed,
    holding,
    instead,
    is_beneath,
    place_of,
    stopping,
    walk,
)
from elenctic.tui.rows import lines, painted, text
from elenctic.tui.theme import NAME, theme

WIDE: Final = 100
"""The narrowest terminal the pane is shown in unless `s` asks for it."""
PANE: Final = range(24, 65)
"""The pane's narrowest and widest: it takes what the headings leave, up to 45% of the width."""
_MARGINS: Final = 4
"""The cells a heading takes beyond its text: its guide, and the scrollbar."""


@dataclass(slots=True)
class View:
    """What one screen shows: a title, a status, the rows, and how to find more.

    `evidence(block, depth)` finds the rows of an evidence block at a depth, by calling the library;
    `why(asking)` makes the view of `why` on an answer set a query was answered in.
    """

    title: Phrase
    status: Phrase
    rows: list[Row]
    lines_of: Lines
    max_depth: int | Limit
    evidence: Callable[[int, int | Limit], list[Row]]
    why: Callable[[Asking], View] | None = None
    claims: bool = False
    """The rows are sources and their claims, which `f` and `e` act on."""
    steps: bool = True
    """The rows can hold steps, which the pane shows and `+` takes deeper."""


def _citing(row: Row | None) -> tuple[Row, tuple[Rule, str]] | None:
    """Find the row, `row` or the first below it in reading order, whose step cites a rule."""
    pending = [] if row is None else [row]
    while pending:
        each = pending.pop()
        pending.extend(reversed(each.children))
        about = each.about
        named = cited(about.node.reason) if isinstance(about, Step) else None
        if named is not None:
            return each, named
    return None


_WAITING: Final = Row((), (Piece(SEARCHING, Role.ASIDE),))
"""The row shown beneath one whose rows the library is still finding."""


@dataclass(slots=True)
class _Search:
    """A library call not yet applied: what stops it, and what undoes the waiting it shows."""

    stop: Event
    undo: Callable[[], None]


class Viewer(App[None]):
    """The app: the first view, and those `why` opens over it; it makes each library call."""

    ENABLE_COMMAND_PALETTE = False
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+c", "quit", KEYS["quit"], show=False, priority=True),
    ]

    def __init__(self, view: View, style: Style) -> None:
        super().__init__(ansi_color=True)
        self.view = view
        self.style = style
        self.title = plain(view.title)
        self.searches: list[_Search] = []
        self._turn = asyncio.Lock()
        self.register_theme(theme(style.color))
        self.theme = NAME

    async def on_mount(self) -> None:
        await self.push_screen(Viewing(self.view, self.style, self))

    def search[Found](
        self,
        work: Callable[[], Found],
        found: Callable[[Found], Awaitable[None]],
        undo: Callable[[], None],
    ) -> None:
        """Call the library off the UI thread, after any call before it, and apply what it found.

        Nothing is applied once the call is cancelled; `undo` takes back the waiting it showed.
        """
        search = _Search(Event(), undo)
        self.searches.append(search)
        self._noted()
        self.run_worker(self._searched(search, work, found))

    async def _searched[Found](
        self, search: _Search, work: Callable[[], Found], found: Callable[[Found], Awaitable[None]]
    ) -> None:
        try:
            async with self._turn:
                if search.stop.is_set():
                    return
                result = await asyncio.to_thread(call, work, search.stop)
        except asyncio.CancelledError:
            search.stop.set()
            raise
        if search.stop.is_set():
            return
        self.searches.remove(search)
        self._noted()
        await found(result)

    def cancel(self) -> bool:
        """Stop each call not yet applied and take back its waiting; `False` if there was none."""
        if not self.searches:
            return False
        for search in reversed(self.searches):
            search.stop.set()
            search.undo()
        self.searches.clear()
        self._noted()
        self.notify(CANCELLED)
        return True

    def _noted(self) -> None:
        for screen in self.screen_stack:
            if isinstance(screen, Viewing):
                screen.titled()

    @override
    async def action_quit(self) -> None:
        """Quit, stopping any call first so that its thread ends with the view."""
        for search in self.searches:
            search.stop.set()
        self.exit()


class Outline(Tree[Row]):
    """The tree of rows, with the keys of the text view's reader."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("k", "cursor_up", KEYS["up"], show=False),
        Binding("j", "cursor_down", KEYS["down"], show=False),
        Binding("right,l", "open", KEYS["open"], key_display=PRESSED["open"]),
        Binding("left,h", "close", KEYS["close"], key_display=PRESSED["close"]),
        Binding("enter", "go", KEYS["go"], key_display=PRESSED["go"]),
    ]

    DEFAULT_CSS = """
    Outline > .tree--guides, Outline > .tree--guides-hover { color: $foreground; }
    Outline:focus > .tree--guides, Outline:focus > .tree--guides-hover { color: $foreground; }
    """

    def __init__(self, view: View, style: Style, viewer: Viewer) -> None:
        super().__init__("", id="outline")
        self.show_root = False
        self.guide_depth = 2
        self.auto_expand = False
        self.view = view
        self.style = style
        self.viewer = viewer
        self.depths: dict[int, int | Limit] = {}
        """The depth each evidence block shown was found at."""
        self.finding: set[int] = set()
        """The evidence blocks the library is finding."""
        self.asked = False
        """Whether the library is finding the view of `why` that ⏎ asked for."""

    def show(self, rows: list[Row], under: Node | None = None, before: Node | None = None) -> None:
        """Add rows beneath `under`, the root if none, with all their descendants.

        The rows go before `before`, a node beneath `under`, if it is given.
        """
        parent = under or self.root
        pending: list[tuple[Node, Row, Node | None]] = [(parent, row, before) for row in rows]
        pending.reverse()
        while pending:
            parent, row, ahead = pending.pop()
            expandable = bool(row.children) or isinstance(row.about, Block)
            label = text(row, self.style)
            node = parent.add(label, row, before=ahead, expand=row.opened, allow_expand=expandable)
            pending.extend((node, child, None) for child in reversed(row.children))

    def shown(self) -> Iterator[Node]:
        return walk(self.root)

    @override
    def render_label(self, node: Node, base_style: Look, style: Look) -> Text:
        """Write a row with the selected row's style beneath its own, so each piece keeps its role.

        Textual lays that style over the row, which would paint every piece in one colour.
        """
        shown = super().render_label(node, base_style, Look())
        shown.stylize_before(style, len(shown) - len(node.label))
        return shown

    def _waiting(self, node: Node, block: int) -> Callable[[], None]:
        """Show that `block` is being found beneath `node`; return what takes the waiting back."""
        self.finding.add(block)
        waiting = node.add_leaf(text(_WAITING, self.style))

        def undo() -> None:
            self.finding.discard(block)
            waiting.remove()

        return undo

    def load(self, node: Node) -> None:
        """Find the evidence of a claim's row that has none yet, and show it beneath the row."""
        row = node.data
        if row is None or not isinstance(row.about, Block) or row.children:
            return
        block = row.about.block
        if block in self.depths or block in self.finding:
            return
        depth = self.view.max_depth
        waited = self._waiting(node, block)

        def undo() -> None:
            waited()
            node.collapse()

        async def found(rows: list[Row]) -> None:
            waited()
            self.depths[block] = depth
            row.children = rows
            self.show(rows, node)
            self.recited()

        self.viewer.search(partial(self.view.evidence, block, depth), found, undo)

    def recited(self) -> None:
        """Show again what the selected row cites, now that rows have come in beneath it."""
        screen = self.screen
        node = self.cursor_node
        if isinstance(screen, Viewing) and node is not None:
            screen.cited(node.data)

    def action_open(self) -> None:
        node = self.cursor_node
        if node is not None:
            self.load(node)
            node.expand()

    def action_close(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.is_expanded and node.children:
            node.collapse()
        elif node.parent is not None and node.parent is not self.root:
            self.move_cursor(node.parent)

    def action_go(self) -> None:
        """Go to a shared step's first row, or ask `why` of an answer set; else open or close."""
        node = self.cursor_node
        if node is None:
            return
        about = None if node.data is None else node.data.about
        if isinstance(about, Again):
            self.reach(self._first(about.handle, about.block))
        elif isinstance(about, Asking):
            self.why(about)
        else:
            self.load(node)
            node.toggle()

    def why(self, asking: Asking) -> None:
        """Open the view of `why` on an answer set a query was answered in, over this one.

        Once: ⏎ again while it is being found asks nothing more.
        """
        made = self.view.why
        if made is None or self.asked:
            return
        self.asked = True

        def undo() -> None:
            self.asked = False

        async def found(view: View) -> None:
            undo()
            await self.viewer.push_screen(Viewing(view, self.style, self.viewer))

        self.viewer.search(partial(made, asking), found, undo)

    def _first(self, handle: str, block: int) -> Node | None:
        return next(
            (
                each
                for each in self.shown()
                if each.data is not None
                and isinstance(each.data.about, Step)
                and each.data.about.block == block
                and each.data.about.node.handle == handle
            ),
            None,
        )

    def reach(self, node: Node | None) -> None:
        """Open each row above `node`, and move to it once the tree is drawn again."""
        if node is None:
            return
        above = node.parent
        while above is not None:
            above.expand()
            above = above.parent
        self.call_after_refresh(self.move_cursor, node)

    def stay(self, holder: Node, place: tuple[Handle, ...] | None) -> None:
        """Keep the cursor on the row it was on, now shown again beneath `holder`, and open it.

        A row with no step of its own, or one gone from the rows shown again, gives way to `holder`.
        """
        kept = None if place is None else found_at(holder, place)
        if kept is None:
            self.reach(holder)
            return
        kept.expand()
        self.reach(kept)

    def deeper(self) -> bool:
        """Explain the selected step's block one step deeper; `False` if it has no further step."""
        node = self.cursor_node
        about = None if node is None or node.data is None else node.data.about
        if not isinstance(about, Step | Again):
            return False
        block = about.block
        holder = holding(node, block)
        if holder is None or holder.data is None or not stopping(holder):
            return False
        if block in self.finding:
            return True
        depth = self.depths.get(block, self.view.max_depth)
        further = depth + 1 if isinstance(depth, int) else depth
        row = holder.data
        undo = self._waiting(holder, block)

        async def found(rows: list[Row]) -> None:
            undo()
            at = self.cursor_node
            moved = at is not None and is_beneath(at, holder)
            place = None if at is None else place_of(holder, at)
            self.depths[block] = further
            holder.remove_children()
            row.children = rows
            self.show(rows, holder)
            self.recited()
            if moved:
                self.stay(holder, place)

        self.viewer.search(partial(self.view.evidence, block, further), found, undo)
        return True


class Keys(ModalScreen[None]):
    """The keys that apply to the view beneath, each with what it does, in the legend's words."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape,question_mark", "dismiss", KEYS["back"], show=False),
        Binding("q", "app.quit", KEYS["quit"], show=False),
    ]

    DEFAULT_CSS = """
    Keys { align: center middle; }
    #keys { width: auto; height: auto; border: round $border; padding: 0 1; }
    """

    def __init__(self, keys: tuple[Phrase, ...], style: Style) -> None:
        super().__init__()
        self.keys = keys
        self.style = style

    @override
    def compose(self) -> ComposeResult:
        shown = Static(lines(self.keys, self.style), id="keys")
        shown.border_title = KEYS["keys"]
        yield shown


class Viewing(Screen[None]):
    """A screen of one view: its title, its tree, the pane, and the search."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("s", "spans", KEYS["spans"], key_display=PRESSED["spans"]),
        Binding("plus", "deeper", KEYS["deeper"], key_display=PRESSED["deeper"]),
        Binding("slash", "find", KEYS["find"], key_display=PRESSED["find"]),
        Binding("n", "next", KEYS["next"], key_display=PRESSED["next"]),
        Binding("f", "failures", KEYS["failures"], key_display=PRESSED["failures"]),
        Binding("e", "every", KEYS["every"], key_display=PRESSED["every"]),
        Binding("question_mark", "keys", KEYS["keys"], key_display=PRESSED["keys"]),
        Binding("escape", "back", KEYS["back"], key_display=PRESSED["back"]),
        Binding("q", "app.quit", KEYS["quit"], key_display=PRESSED["quit"]),
    ]

    DEFAULT_CSS = """
    Viewing { layout: vertical; }
    #title { height: 1; }
    #body { height: 1fr; }
    #outline { width: 1fr; }
    #pane { height: 100%; border-left: solid $border; padding: 0 1; }
    #quote { text-wrap: nowrap; text-overflow: ellipsis; }
    #find { dock: bottom; display: none; }
    """

    def __init__(self, view: View, style: Style, viewer: Viewer) -> None:
        super().__init__()
        self.view = view
        self.style = style
        self.viewer = viewer
        self.title = plain(view.title)
        self.pane_asked: bool | None = None
        """`s` shows or hides the pane; until it is pressed, the width decides."""
        self.needle = ""
        self.failures_only = False

    @override
    def compose(self) -> ComposeResult:
        yield Static(id="title")
        with Horizontal(id="body"):
            yield Outline(self.view, self.style, self.viewer)
            with Vertical(id="pane"):
                yield Static(id="cited")
                yield Static(id="quote")
        yield Input(placeholder=FIND, id="find")
        yield Footer()

    @property
    def outline(self) -> Outline:
        return self.query_one(Outline)

    def on_mount(self) -> None:
        outline = self.outline
        outline.show(self.view.rows)
        outline.focus()
        outline.cursor_line = 0
        self.titled()
        self._place_pane(self.size.width)
        self.call_after_refresh(self._load_opened)

    def _load_opened(self) -> None:
        """Find the evidence of each claim open at the start, once the view is drawn."""
        outline = self.outline
        for node in list(outline.shown()):
            if node.is_expanded:
                outline.load(node)

    def titled(self) -> None:
        """Write the title bar: the title, then the status, or what the library is finding.

        The status is kept whole; a title too long for the rest is cut short, with an ellipsis,
        and left out where there is no room for even that.
        """
        width = self.size.width
        status = PENDING if self.viewer.searches else self.view.status
        left = text(Row((), self.view.title), self.style)
        right = text(Row((), status), self.style)
        room = width - right.cell_len - 1
        if room > 0:
            left.truncate(room, overflow="ellipsis")
        else:
            left = Text()
        left.pad_right(max(1, width - left.cell_len - right.cell_len))
        left.append_text(right)
        self.query_one("#title", Static).update(left)

    def on_screen_resume(self) -> None:
        """Title the window by this view, as `why` opened over `ask`, or `ask` again, is shown."""
        self.viewer.title = self.title or ""

    def on_resize(self, event: Resize) -> None:
        self.titled()
        self._place_pane(event.size.width)

    def _place_pane(self, width: int) -> None:
        """Show the pane as the width or `s` decides, leaving the headings of the rows whole."""
        pane = self.query_one("#pane", Vertical)
        shown = width >= WIDE if self.pane_asked is None else self.pane_asked
        pane.display = shown and self.view.steps
        headings = max((text(row, self.style).cell_len for row in self.view.rows), default=0)
        room = min(width * 45 // 100, PANE.stop - 1, width - headings - _MARGINS)
        pane.styles.width = max(PANE.start, room)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[Row]) -> None:
        self.cited(event.node.data)

    def cited(self, row: Row | None) -> None:
        """Show in the pane the rule the row cites, or else the first one cited in the rows below.

        A row of how the objective ranks a claim shows the weak constraints it is about, instead.

        The rule is written as `--spans` writes it, wrapped to the pane, and its line quoted whole.
        """
        rule_of, quote_of = self.query_one("#cited", Static), self.query_one("#quote", Static)
        if row is not None and isinstance(row.about, Paying):
            rule_of.update(lines(((Piece(PAID, Role.ASIDE),),), self.style))
            quote_of.update(lines(self._paid(row.about), self.style))
            return
        found = _citing(row)
        if found is None:
            rule_of.update(lines(((Piece(NO_STEP, Role.REFERENCE),),), self.style))
            quote_of.update("")
            return
        step, (rule, substitution) = found
        above = () if step is row else ((Piece(BENEATH, Role.ASIDE),),)
        rule_of.update(lines((*above, written(rule, substitution)), self.style))
        source = self.view.lines_of(rule.span)
        quote_of.update(lines(quoted(rule.span, source or (), Role.NOTE), self.style))

    def _paid(self, ranked: Paying) -> tuple[Phrase, ...]:
        """Quote each weak constraint a ranking row is about, as the text view quotes it."""
        return tuple(
            phrase
            for payment, more in ranked.payments
            for phrase in paying(payment, self.view.lines_of(payment.rule.span), more=more)
        )

    def on_tree_node_expanded(self, event: Tree.NodeExpanded[Row]) -> None:
        if event.node.data is not None:
            event.node.data.opened = True
        self.outline.load(event.node)

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed[Row]) -> None:
        if event.node.data is not None:
            event.node.data.opened = False

    def _offers(self, action: str) -> bool:
        """Whether an action applies to this view: `f` and `e` to claims, `s` and `+` to steps."""
        if action in {"failures", "every"}:
            return self.view.claims
        return self.view.steps or action not in {"spans", "deeper"}

    @override
    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        """Offer only the keys that apply: the others are neither in the footer nor in `?`."""
        del parameters
        return self._offers(action)

    def action_spans(self) -> None:
        pane = self.query_one("#pane", Vertical)
        self.pane_asked = not pane.display
        self._place_pane(self.size.width)

    def action_deeper(self) -> None:
        if not self.outline.deeper():
            self.notify(NOTHING_DEEPER)

    def action_find(self) -> None:
        found = self.query_one("#find", Input)
        found.display = True
        found.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.needle = event.value
        event.input.display = False
        self.outline.focus()
        self.action_next()

    def action_next(self) -> None:
        """Go to the next row, after the selected one and round again, whose text has the needle."""
        if not self.needle:
            return
        shown = list(self.outline.shown())
        at = self.outline.cursor_node
        start = shown.index(at) + 1 if at in shown else 0
        for node in shown[start:] + shown[:start]:
            if node.data is not None and self.needle in _plain(node.data):
                self.outline.reach(node)
                return
        self.notify(NOT_FOUND)

    def action_failures(self) -> None:
        """Show only the sources that did not pass, or each again; rows already shown stay."""
        self.failures_only = not self.failures_only
        if self.failures_only:
            self._only_failures()
        else:
            self._every_source()

    def _only_failures(self) -> None:
        """Leave out each source that passed; the cursor on one goes to the next that failed."""
        outline = self.outline
        tops = list(outline.root.children)
        moved = instead(tops, outline.cursor_node)
        for node in tops:
            if not has_failed(node.data):
                node.remove()
        if moved is not None:
            outline.reach(moved)

    def _every_source(self) -> None:
        """Show each source again, in its place among those shown."""
        outline = self.outline
        kept = {id(node.data): node for node in outline.root.children}
        ahead: Node | None = None
        for row in reversed(self.view.rows):
            if id(row) not in kept:
                outline.show([row], before=ahead)
            ahead = kept.get(id(row)) or next(
                node for node in outline.root.children if node.data is row
            )

    def action_every(self) -> None:
        """Find and open the evidence of every failed claim."""
        for node in list(self.outline.shown()):
            if node.data is not None and isinstance(node.data.about, Block):
                self.outline.load(node)
                node.expand()
                parent = node.parent
                if parent is not None:
                    parent.expand()

    async def action_keys(self) -> None:
        """Show the keys that apply to this view."""
        offered = [action for action in KEYS if self._offers(action)]
        await self.viewer.push_screen(Keys(keyed(offered), self.style))

    async def action_back(self) -> None:
        """Close the find box, else cancel what the library is finding; else go back, or quit."""
        found = self.query_one("#find", Input)
        app = self.viewer
        if found.display:
            found.display = False
            self.outline.focus()
        elif app.cancel():
            return
        elif len(app.screen_stack) > 2:  # noqa: PLR2004
            await app.pop_screen()
        else:
            app.exit()


_PLAIN: Final = Style(Color.OFF, Glyphs.PLAIN)


def _plain(row: Row) -> str:
    return painted(row, _PLAIN)
