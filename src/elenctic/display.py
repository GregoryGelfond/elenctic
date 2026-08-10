"""Making corpus-controlled text safe to show.

Everything elenctic prints about a case is influenced by the case: its path, its ``@note`` prose,
the atoms in its answer sets, and the solver's own diagnostics about it. Running a corpus means
trusting it as code; showing its *text* is a separate question, and a terminal treats some of that
text as instructions rather than characters — an escape sequence moves the cursor, a carriage
return overwrites the line just printed. Since elenctic exists to produce a verdict a reader can
act on, text that can rewrite the report is a defect in the product rather than a cosmetic one.

So corpus-controlled text passes through :func:`legible` before it is shown. No elenctic
dependencies, so every renderer reaches it — the human one, and the machine-readable one, which
needs the same guarantee for a related reason: text a parser would act on can break the document
it appears in as surely as text a terminal acts on can rewrite a report.
"""

__all__ = ["legible"]


def legible(text: str) -> str:
    r"""``text`` with everything a terminal would act on rendered as characters instead.

    Printable characters, spaces and newlines survive; anything else becomes a visible escape, and
    a backslash is doubled. Escaping rather than dropping keeps the fact that something was there —
    a reader should be able to see that a corpus tried something, not find text quietly missing.

    **Newlines are deliberately kept.** A solver diagnostic is legitimately multi-line, and mangling
    the most common error a user will ever see costs more than the one thing a newline still allows:
    adding a line. It cannot overwrite a line already printed, conceal one, or move the cursor. A
    reader who cannot trust line *counts* can still trust every line's contents.

    ``str.isprintable`` is the exact predicate wanted: false for every C0 and C1 control and for
    every separator except the space, including the ones that split a line for Python but not for
    clingo or for a diff.

    **The escape says where it ends, and the encoding is injective.** Both halves are load-bearing:

    - The width is fixed by the codepoint — ``\xNN``, ``\uNNNN``, ``\UNNNNNNNN``, exactly two, four
      or eight hex digits. ``\x`` means *exactly two digits* wherever a reader has met it, so a
      single ``\x`` form for every codepoint would render U+2028 as ``\x2028``, which reads as
      U+0020 followed by a literal ``28``.
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
    if character.isprintable() or character in " \n":
        return character
    code = ord(character)
    if code <= 0xFF:
        return f"\\x{code:02x}"
    if code <= 0xFFFF:
        return f"\\u{code:04x}"
    return f"\\U{code:08x}"
