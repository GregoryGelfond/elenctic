"""Making corpus-controlled text safe to show.

Everything elenctic prints about a case is influenced by the case: its path, its ``@note`` prose,
the atoms in its answer sets, and the solver's own diagnostics about it. Running a corpus means
trusting it as code; showing its *text* is a separate question, and a terminal treats some of that
text as instructions rather than characters — an escape sequence moves the cursor, a carriage
return overwrites the line just printed, a line break starts a line of its own. Since elenctic
exists to produce a verdict a reader can act on, text that can rewrite the report is a defect in
the product rather than a cosmetic one.

So corpus-controlled text passes through :func:`legible` before it is shown, and what comes back is
**one line**. No elenctic dependencies, so every renderer reaches it — the human one, and the
machine-readable one, which needs the same guarantee for a related reason: text a parser would act
on can break the document it appears in as surely as text a terminal acts on can rewrite a report.

Which strings a corpus can reach is one question and how many lines a value may occupy is another,
and the two are answered in different places. This module answers the first for every string and
gives the second one answer: exactly one. Where several lines are legitimate *content* — a solver's
diagnostic, and nothing else that reaches a reader — it is the renderer with a layout that re-emits
the breaks, under a mark of its own, so the lines added are the report's structure and not the
corpus's.
"""

__all__ = ["legible"]


def legible(text: str) -> str:
    r"""``text`` as a single line, with everything a terminal would act on rendered as characters.

    Printable characters survive; anything else becomes a visible escape, and a backslash is
    doubled. Escaping rather than dropping keeps the fact that something was there — a reader
    should be able to see that a corpus tried something, not find text quietly missing.

    **Every character of what comes back is printable.** That is the postcondition, and it is stated
    as the codomain rather than as any one of its consequences: *holds no line break* follows from
    it, and so does *holds nothing else that splits a line either* — U+2028 among them, which one
    caller depends on, since it composes this with ``textwrap.indent`` and that splits on more than
    ``\n`` does. Naming the newline alone would leave the second question to be asked separately.

    A newline was once let through, on the reasoning that adding a line is harmless beside
    overwriting one: *a reader who cannot trust line counts can still trust every line's contents*.
    That was false. A report's structure **is** its line boundaries, so text that can add a line can
    write a row — measured, a file name carrying one printed a ``[PASS]`` directly above the
    ``[FAIL]`` its own case had just earned, the two contradicting each other and neither marked as
    to who wrote it. Where several lines are legitimate *content* — a solver's own diagnostic —
    the breaks belong to the renderer that has a layout, which re-emits them under a mark of its
    own.

    **Apply exactly once.** An injective encoding cannot also be idempotent: a second pass doubles
    the backslashes the first introduced, and shows a reader two where their path had one. Two
    frames in :mod:`elenctic.cli` carry a message raw rather than make it safe early, for this
    reason, and say so where they do it.

    ``str.isprintable`` is the whole of the predicate, with nothing disjoined to it: true for the
    ASCII space by that method's own definition, false for every C0 and C1 control and for every
    other separator — including the ones that split a line for Python but not for clingo or for a
    diff. The space was once disjoined here as well; over every codepoint there is, it changes no
    answer.

    **The escape says where it ends, and the encoding is injective.** Both halves are load-bearing:

    - The width is fixed by the codepoint — ``\xNN``, ``\uNNNN``, ``\UNNNNNNNN``, exactly two, four
      or eight hex digits. ``\x`` means *exactly two digits* wherever a reader has met it, so a
      single ``\x`` form for every codepoint would render U+2028 as ``\x2028``, which reads as
      U+0020 followed by a literal ``28``. A newline joins that alphabet as ``\x0a`` rather than
      bringing a mnemonic ``\n`` with it, which would be a fourth shape bought for familiarity
      alone — and one a reader would then have to be told the extent of.
    - The backslash is doubled, or two different strings render the same one: a path holding a real
      ESC and a path holding the four characters ``\``, ``x``, ``1``, ``b`` would be
      indistinguishable in the report and in the published document's ``source`` field. A consumer
      decoding the escapes to recover the real path would turn the second back into a real ESC and
      feed it to its own terminal, re-opening the hole this function exists to close.
    """
    return "".join(_shown(character) for character in text)


def _shown(character: str) -> str:
    r"""One character as itself, or as the escape that stands for it.

    The escape alphabet is a backslash followed by ``\``, ``x``, ``u`` or ``U``, and every backslash
    in the input is doubled, so no escape in the output can have come from the text: that is what
    makes reading one back unambiguous."""
    if character == "\\":
        return "\\\\"
    if character.isprintable():
        return character
    code = ord(character)
    if code <= 0xFF:
        return f"\\x{code:02x}"
    if code <= 0xFFFF:
        return f"\\u{code:04x}"
    return f"\\U{code:08x}"
