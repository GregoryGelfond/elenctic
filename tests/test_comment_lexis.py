"""elenctic's reading of clingo's comment lexis, held against clingo itself.

The contract channel is comments, so ``_lex`` states clingo's comment grammar in elenctic's
own terms, and this is where that statement is checked. clingo is already a hard dependency of this
environment, so the oracle costs nothing; what it buys is that the grammar cannot drift silently,
which is the one risk of stating it here rather than calling clingo at collection time.

The criterion is deliberately not "identical":

    on every input clingo lexes **without error**, elenctic's reading and clingo's are identical.

On input clingo cannot lex, elenctic's reading is defined by the grammar and is total, while
clingo's is whatever its parser managed before giving up — measured, that is a comment whose text
begins back at the quote that failed. Error recovery is a specification of nothing, so the corners
below that clingo cannot lex assert *elenctic's* reading, written out, and assert that clingo
indeed cannot lex them, so neither corner set can quietly drift into the other.

The randomized half is the one that earns the criterion. A hand-built corner set only varies the
axes its author thought of: these corners passed a reading that then disagreed with clingo on a
generated program in the first four thousand, and the class it found — that a ``%`` inside a block
comment opens a line comment, so a ``*%`` after one does not close the block — is in no corner
anybody wrote by hand.
"""

import pathlib
import random

import clingo.ast as ast
import pytest

from elenctic.expectation import _lex

# One comment as (1-based opening line, the comment's whole text, delimiters included) — the shape
# clingo reports, so elenctic's reading is rendered back into it rather than compared field-wise.
type _Reading = list[tuple[int, str]]


def _clingo_reads(text: str) -> tuple[_Reading, bool]:
    """How clingo lexes ``text``'s comments, and whether it lexed the whole of it without error.

    ``message_limit`` is raised because the default of 20 makes clingo stop lexing silently after
    twenty diagnostics, which would quietly shrink the reading being compared against.
    """
    seen: _Reading = []
    errors: list[str] = []

    def visit(node: ast.AST) -> None:
        if node.ast_type == ast.ASTType.Comment and node.location.begin.filename == "<string>":
            seen.append((node.location.begin.line, node.value))

    try:
        ast.parse_string(
            text,
            visit,
            logger=lambda code, message: errors.append(message),
            message_limit=2**31 - 1,
        )
    except RuntimeError as exc:  # clingo raises once it has given up on the parse
        errors.append(str(exc))
    return seen, not errors


def _elenctic_reads(text: str) -> _Reading:
    """The same reading from ``_lex``, with the delimiters it strips put back — so what is
    compared is the span of text each side calls a comment, not a re-encoding of it."""
    return [(c.line, f"%*{c.body}*%" if c.block else f"%{c.body}") for c in _lex(text).comments]


# --- corners clingo lexes cleanly: elenctic's reading must be clingo's ---

_AGREES = {
    "plain": "% a\np(1).\n% b\n",
    "trailing": "p(1). % a\n",
    "block": "%* a\nb *%\np(1).\n",
    "nested block": "%* a %* b *% c *%\np(1).\n",
    "line comment inside a block eats a *%": "%*\n% *%\nx *%\n",
    "line comment inside a block eats a %*": "%* a % b %* c\nd *%\n",
    "string with %": 'p("100% x").\n% b\n',
    "string with %* *%": 'p("%* x *%").\n% b\n',
    "escaped quote": 'p("a\\"b % c").\n% d\n',
    "escaped backslash": 'p("a\\\\").\n% b\n',
    "quote inside a line comment": '% he said "hi\np(1).\n% b\n',
    "quote inside a block": '%* he said "hi *%\n% b\n',
    "script python": "#script (python)\n% x\n#end.\n% y\n",
    "script no space before the paren": "#script(python)\n% x\n#end.\n% y\n",
    # The membership half of `_SPACE`. Its non-membership half — `\v` and `\f` — is two corners
    # below; without both, the constant can be narrowed or widened with nothing noticing, and
    # narrowing it stops `#script` opening at all, which puts a script body's `%` lines back into
    # the contract.
    "tab before the paren": "#script\t(python)\n% x\n#end.\n% y\n",
    "carriage return before the paren": "#script\r(python)\n% x\n#end.\n% y\n",
    "script newline before the paren": "#script\n(python)\n% x\n#end.\n% y\n",
    "script lua": "#script (lua)\n-- x\n% y\n#end.\n% z\n",
    "#end then a space then the dot": "#script (python)\npass\n#end .\n% y\n",
    "#end then a comment then the dot": "#script (python)\npass\n#end % c\n.\n% y\n",
    "#end then a block comment then the dot": "#script (python)\n#end %* c *% .\n% y\n",
    "#end then a newline then the dot": "#script (python)\npass\n#end\n.\n% y\n",
    "script then a block comment": "#script (python)\n#end.\n%* a *%\n% b\n",
    "two scripts": "#script (python)\n#end.\n% a\n#script (lua)\n#end.\n% b\n",
    "an identifier ending in script": "myscript(1).\n% a\n",
    "block then line on one line": "%* a *% % b\np(1).\n",
    "empty %": "%\np(1).\n",
    "%% double": "%% a\np(1).\n",
    "% at end of input, no newline": "p(1).\n% tail",
    "mid-rule comment": "p(1) :-\n  % mid\n  q(2).\n",
    "CRLF": "% a\r\np(1).\r\n% b\r\n",
    "carriage return inside a comment": "% a\rb\np(1).\n",
    "carriage return at end of input": "% a\r",
    "CRLF inside a block": "%* a\r\nb *%\r\n% c\r\n",
    "block closes then a tag": "%* x *%\n% @expect sat\n",
    "percent star in a line comment": "% see %* this\n% b\n",
    "star percent in a line comment": "% see *% this\n% b\n",
    "hash that is not a script": "#show p/1.\n% a\n",
    "#external": "#external p(1).\n% a\n",
    "tab before %": "\t% a\np(1).\n",
    "spaces then %*": "   %* a *%\n% b\n",
    "empty file": "",
    "only newlines": "\n\n\n",
    "comment only": "% just a comment\n",
}


@pytest.mark.parametrize("text", _AGREES.values(), ids=list(_AGREES))
def test_a_program_clingo_lexes_cleanly_is_read_exactly_as_clingo_reads_it(text: str) -> None:
    theirs, clean = _clingo_reads(text)
    # Asserted, not assumed: a corner that stopped lexing cleanly would otherwise go on passing
    # while comparing against clingo's error recovery, which this suite deliberately does not pin.
    assert clean, "this corner belongs in _GRAMMAR_DECIDES — clingo no longer lexes it cleanly"
    assert _elenctic_reads(text) == theirs


# --- corners clingo cannot lex: elenctic's own reading, written out ---

# Each of these is a lexer error to clingo, so there is nothing to compare against: what clingo
# reports is what its parser reached before giving up. The grammar still has to answer, and these
# are the answers it gives — every one of them the faithful reading of an unterminated construct.
_GRAMMAR_DECIDES = {
    # An unterminated block runs to end of input and is no comment at all — clingo reports none
    # for it either, so a tag below one is not a contract in either reading.
    "unterminated block": ("%* a\np(1).\n% b\n", []),
    "tag after an unterminated block": (
        "% @expect sat\n%* open\n% @model { p(1) }\n",
        [(1, "% @expect sat")],
    ),
    "a *% closed by a line comment first": ("%* a % b *% c *%\n", []),
    "%% inside a block": ("%* a %% b *% c *%\n", []),
    # A string may not span a newline: clingo reports the error at the opening quote and resumes
    # right after it, so the rest of that line is ordinary input and a later % is a comment.
    "unterminated string": ('p("abc).\n% b\n', [(2, "% b")]),
    # The one that says where lexing resumes after an unclosed quote. Resuming at the newline
    # instead would lose this comment, and losing it makes the file a library — a contract the
    # author can see, silently never run.
    "unterminated string then a % on the same line": (
        'p("oops).  % @expect sat\n',
        [(1, "% @expect sat")],
    ),
    "backslash before a newline in a string": ('p("a\\\nb").\n% tail\n', [(3, "% tail")]),
    # The one that says which reading of the escape is meant: let the backslash carry the string
    # over the newline and the `%` below is inside a string rather than opening a comment.
    "backslash before a newline, then a % line": (
        'p("a\\\n% not a comment").\n% tail\n',
        [(2, '% not a comment").'), (3, "% tail")],
    ),
    # An unterminated script body is opaque to end of input, exactly as clingo takes it.
    "unterminated script": ("#script (python)\n% x\n", []),
    "#end at end of input without its dot": ("#script (python)\npass\n#end", []),
    # `#script` without the parenthesized language name opens nothing, so what follows is program
    # text and its comments are comments.
    "bare #script, no parens": ("#script\n% y\n", [(2, "% y")]),
    # clingo's whitespace is space, tab, carriage return and newline, and nothing else — measured,
    # and the reason the opener does not ask `str.isspace`, which would also take these two.
    "vertical tab before the paren": (
        "#script\v(python)\n% x\n#end.\n% y\n",
        [(2, "% x"), (4, "% y")],
    ),
    "form feed before the paren": (
        "#script\f(python)\n% x\n#end.\n% y\n",
        [(2, "% x"), (4, "% y")],
    ),
    "a comment between #script and its paren": (
        "#script % c\n(python)\npass\n#end.\n% y\n",
        [(1, "% c"), (5, "% y")],
    ),
    # The body is opaque, so an `#end` inside a string in the script's own language still closes it.
    "#end. inside a python string": (
        '#script (python)\ns = "#end."\n% x\n#end.\n% y\n',
        [(3, "% x"), (5, "% y")],
    ),
    "#endz": ("#script (python)\n#endz.\n% y\n", [(3, "% y")]),
    # A stray `*%` is nothing at top level: the `*` is program text and the `%` after it opens an
    # empty line comment. Only a `%*` makes a block, so only a `*%` inside one closes anything.
    "stray *%": ("*%\n% a\n", [(1, "%"), (2, "% a")]),
    "%*%": ("%*%\np(1).\n", []),
    "no trailing newline in a block": ("%* a", []),
    # An `#include` naming a file that is not there is a parse failure, not a lexer one: the
    # comments either side of it are still read, which is what lets collection answer for a
    # library that only makes sense inside the case including it.
    "unresolvable include": ('#include "x.lp".\n% a\n', [(2, "% a")]),
}


@pytest.mark.parametrize(
    ("text", "expected"), _GRAMMAR_DECIDES.values(), ids=list(_GRAMMAR_DECIDES)
)
def test_a_program_clingo_cannot_lex_is_read_as_the_grammar_says(
    text: str, expected: _Reading
) -> None:
    _, clean = _clingo_reads(text)
    assert not clean, "this corner belongs in _AGREES — clingo lexes it cleanly now"
    assert _elenctic_reads(text) == expected


# --- the randomized differential ---

# Fragments chosen so that concatenating them lands on the construct boundaries: an unterminated
# anything, a delimiter with no partner, a `#end` needing its dot from the next fragment. The last
# class is the one a previous alphabet lacked, and it hides three programs clingo lexes cleanly
# while a `#end.`-spelled closer misreads them.
#
# EVERY FRAGMENT MUST BE ASCII. A non-ASCII character in clingo program text terminates the
# process — clingo's diagnostic cuts the multi-byte character, its own logger binding fails to
# decode it, and the C++ layer aborts in a nothrow scope, so no handler here or anywhere else runs.
# Widening this alphabet past ASCII does not fail the test; it kills the run.
_FRAGMENTS = [
    "p(1).\n", "q(X) :- p(X).\n", ":- p(1), q(2).\n", "#show p/1.\n", ".", ".\n",
    "% a comment\n", "% @expect sat\n", "%% double\n", "%\n", "% no newline",
    "p(1). % trailing\n", "%* block *%\n", "%* multi\nline *%\n", "%* nest %* in *% out *%\n",
    '"str"', 'p("a % b").\n', 'p("a\\"b").\n', 'p("unterminated).\n', 'p("a\\\nb").\n',
    "#script (python)\n", "#end.\n", "#script(lua)\n", "-- lua comment\n",
    "#end % c\n", "#end\n", "#end ", "#endz", "#script\n(python)\n",
    "%*", "*%", '"', "\\", "\n", "   ", "\t", "\r\n", "#end", "#script",
    "{ a; b }\n", "1 { p(X) } 1 :- q(X).\n", "#minimize { 1@1 : p(1) }.\n",
    "% @model { p(1),\n", "%   p(2) }\n", '#include "x.lp".\n',
]  # fmt: skip

_PROGRAMS = 4_000
_SEED = 20260806
# Roughly a tenth of the generated programs lex cleanly, and only those are compared. Asserting a
# floor keeps the test from passing because it compared almost nothing: a fragment change that
# made every program a lexer error would otherwise look exactly like success.
_CLEANLY_LEXED_FLOOR = 300


def test_the_generated_alphabet_is_ascii() -> None:
    assert all(fragment.isascii() for fragment in _FRAGMENTS)


def test_every_generated_program_clingo_lexes_cleanly_is_read_exactly_as_clingo_reads_it() -> None:
    rng = random.Random(_SEED)
    compared = 0
    disagreements: list[tuple[str, _Reading, _Reading]] = []
    for _ in range(_PROGRAMS):
        text = "".join(rng.choice(_FRAGMENTS) for _ in range(rng.randint(1, 12)))
        theirs, clean = _clingo_reads(text)
        if not clean:
            # Read it anyway: the reading is total on every input, and that is half the point of
            # owning it. Its answer here is the grammar's, not clingo's recovery, so it is not
            # compared.
            _elenctic_reads(text)
            continue
        compared += 1
        if (mine := _elenctic_reads(text)) != theirs:
            disagreements.append((text, theirs, mine))

    assert compared >= _CLEANLY_LEXED_FLOOR, (
        f"only {compared} of {_PROGRAMS} generated programs lexed cleanly — the differential "
        f"compared almost nothing, so the alphabet, not the reading, is what needs looking at"
    )
    assert not disagreements, "\n".join(
        f"{text!r}\n  clingo: {theirs}\n  elenctic: {mine}"
        for text, theirs, mine in disagreements[:5]
    )


def test_the_projects_own_encodings_are_read_exactly_as_clingo_reads_them() -> None:
    # A real corpus: files written by hand rather than generated, which is the axis neither of the
    # two above varies. All of them lex cleanly on their own, so the criterion binds for each —
    # asserted rather than assumed, since a file that stopped doing so would otherwise be compared
    # against clingo's error recovery, which nothing here pins.
    encodings = sorted((pathlib.Path(__file__).parent / "krbook" / "encodings").rglob("*.lp"))
    assert encodings, "the dogfood corpus moved — this test is comparing nothing"
    read = 0
    for path in encodings:
        text = path.read_text(encoding="utf-8")
        theirs, clean = _clingo_reads(text)
        assert clean, f"{path} no longer lexes cleanly on its own"
        assert _elenctic_reads(text) == theirs, path
        read += len(theirs)
    assert read > 50, f"only {read} comments compared across {len(encodings)} encodings"
