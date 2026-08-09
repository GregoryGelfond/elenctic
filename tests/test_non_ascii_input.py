"""A character clingo's lexer will not take must cost one case its verdict, not the whole run.

clingo reports a lexer error by quoting the *byte* it objected to. A lone UTF-8 lead byte does not
decode, so a Python logger handed the message already decoded — which is how clingo's binding calls
one — raises inside a C++ frame declared not to throw, and the process aborts: no report of any
kind, on either stream, for any case, and nothing elenctic can catch. Reading clingo's diagnostics
off the descriptor it writes them to puts that decode in elenctic's own frame, where a byte that
will not decode is a character in a diagnostic rather than the end of the run.

Two symptoms, one cause, and the second is not repaired by the first: the term parser reached from
*contract* text does not abort, it raises a ``UnicodeDecodeError`` whose text is a codec, a byte and
an offset into a message the author cannot see. That one gets a sentence elenctic writes itself.

Every case here runs elenctic **as a process**. It has to: the failure being guarded takes the
process down, so an in-process test would take the runner with it rather than reporting.
"""

from pathlib import Path

from support import run_cli

# A bare accented identifier. clingo rejects it — measured against clingo's own command line, which
# does not route through the Python binding — so this is a program fault and not a valid program
# elenctic is refusing on its own authority.
_LEXER_REJECTS = "% @elenctic solver clingo\n% @expect sat\np(é).\n"
# The same character where clingo *accepts* it. Both of these pass today and must keep passing: a
# testing tool that will not run a corpus written in German is not degraded, it is broken.
_IN_A_STRING = (
    '% @elenctic solver clingo\n% @expect sat\n% @model { p("café") }\np("café").\n#show p/1.\n'
)
_IN_A_NOTE = (
    "% @elenctic solver clingo\n% @expect sat\n% @note an em dash — here.\np(1).\n#show p/1.\n"
)
_IN_A_TERM = "% @elenctic solver clingo\n% @expect sat\n% @model { p(é) }\np(1).\n#show p/1.\n"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_character_the_lexer_rejects_costs_one_case_and_not_the_run(tmp_path: Path) -> None:
    # The whole of it: the run reaches its tally, and the case beside the offending one is still
    # decided. Before, standard output was empty, the status was 1, and the last thing on standard
    # error was a Python traceback followed by an abort from clingo's C++ layer.
    _write(tmp_path / "rejected.lp", _LEXER_REJECTS)
    _write(tmp_path / "fine.lp", _IN_A_NOTE)
    streams = run_cli(tmp_path)

    assert "1/2 passed" in streams.out, "the other case is decided, which is what the abort cost"
    assert streams.status == 2, "a case that could not be run, not a crash"
    assert "PROGRAM ERROR" in streams.err, "reported as the program fault it is"
    assert "rejected.lp" in streams.err, "and against the case it belongs to"
    assert "Traceback" not in streams.err, "never a stack trace"
    assert "PANIC" not in streams.err


def test_the_offending_byte_reaches_the_reader_as_a_character(tmp_path: Path) -> None:
    # What elenctic's own decode buys, beyond surviving: clingo quotes a byte that is not a
    # character, and it arrives as the replacement character inside an otherwise ordinary
    # diagnostic. Decoding strictly here would mean no diagnostic at all.
    _write(tmp_path / "rejected.lp", _LEXER_REJECTS)
    streams = run_cli(tmp_path)
    assert "lexer error" in streams.err, "clingo's own account of what is wrong, quoted"
    assert "rejected.lp:3" in streams.err, "with the coordinate an editor reads"


def test_a_contract_term_the_lexer_rejects_gets_a_sentence_and_not_a_codec(tmp_path: Path) -> None:
    # The second symptom. This route never aborted; it reported `'utf-8' codec can't decode byte
    # 0xc3 in position 39`, which names a codec the author never invoked and an offset into a
    # message they cannot see. The remedy is nameable, so it is named.
    _write(tmp_path / "term.lp", _IN_A_TERM)
    streams = run_cli(tmp_path)

    assert "CONTRACT ERROR" in streams.err
    assert "codec" not in streams.err, "the codec error is what this replaces"
    assert "position" not in streams.err, "nor an offset into a string the author cannot see"
    assert "double quotes" in streams.err, "a remedy the author can act on"
    assert "Traceback" not in streams.err


def test_valid_utf8_still_runs(tmp_path: Path) -> None:
    # The control, and without it every assertion above is satisfied by a tool that refuses all
    # non-ASCII input — which was the repair this design measured and rejected, because clingo
    # accepts both of these and elenctic passed them before any of this.
    _write(tmp_path / "string.lp", _IN_A_STRING)
    _write(tmp_path / "note.lp", _IN_A_NOTE)
    streams = run_cli(tmp_path)

    assert "2/2 passed" in streams.out, "a UTF-8 string literal and a UTF-8 note both still pass"
    assert streams.status == 0
    assert streams.err == "", "and nothing is said about either"


def test_two_diagnostics_are_framed_as_clingo_wrote_them(tmp_path: Path) -> None:
    # The one rendering this change moves, pinned here because the control harness cannot see it:
    # every fault in that corpus produces a single message, and a single message renders exactly as
    # it did before. Where clingo reports more than one, they used to be run together with `; `
    # between them; now they arrive in clingo's own framing, one blank line apart. What is NOT
    # claimed: that the boundary between them is recoverable — it is a blank line, and a directory
    # named with a newline in it can put one inside a single message, so nothing splits on it.
    _write(
        tmp_path / "two.lp",
        "% @elenctic solver clingo\n% @expect sat\nq(1).\np(X) :- q(Y).\nr(Z) :- q(W).\n",
    )
    streams = run_cli(tmp_path)
    assert "'X' is unsafe" in streams.err, "the first diagnostic"
    assert "'Z' is unsafe" in streams.err, "and the second"
    assert "unsafe\n\n" in streams.err, "one blank line apart, which is how clingo wrote them"
    assert "unsafe; " not in streams.err, "and not run together with a separator elenctic added"
