"""Where this suite reaches past a module's declared surface, and whether it says why.

Testing a library from outside its public API is not a defect — a great deal of what is worth
pinning has no public path to it, and a unit test of a derivation reaches the derivation. What *is*
a defect is reaching past the surface for no stated reason, because that is the reach nobody can
tell from a convenience: the next person refactoring ``solvers.py`` meets a test coupled to an
internal and has no way to know whether the coupling was necessary or merely easy.

So the rule is not "do not reach" — it is:

    Every internal name a test module reaches must say why, somewhere in that module.

**The unit is the coupling, not the keystroke.** ``test_solve_exhaustion.py`` imports
``_solve_under_budget`` and then calls it four more times; the reason is the same one, and
demanding it five times would turn a reason into a decoration. What is worth holding is that a
reader of *this file* can find out why *this name* is reached — so the obligation is one statement
per module per name, and a module is not asked about a name it does not touch.

**"Internal" is derived, not assumed from a spelling.** Every module of this package declares
``__all__``, so the package has already written down what each one offers. The leading-underscore
convention mostly coincides with that and is not the same thing — they part company at
``discovery.ORPHAN_LIBRARY``, ``discovery.UNDECLARED_SOLVER`` and ``expectation.sited``, each a name
written without an underscore that its own module does not export. Reading the convention instead
would miss all three. ``__all__`` is a statement; the underscore is a habit.

**"Defines" is load-bearing.** ``corpus.py`` imports ``run_plan`` and ``time.monotonic`` for its own
use, and ``monkeypatch.setattr(corpus, "run_plan", …)`` patches the binding *where it is looked up*
— the documented idiom, not a reach into internals. A module that never defined a name is not
declining to offer it, so its ``__all__`` says nothing about it. Without this clause the sweep
reported ``corpus.monotonic``, ``discovery.find_spec`` and ``json_report.files`` as reaches into
this package, which are ``time``'s, ``importlib``'s and ``importlib.resources``'s.

**An import is one of four ways to reach a name**, and a check reading only imports would report a
population rather than the class. ``discovery._installed`` is the case that shows it: patched in
three test modules to make clingcon absent, called outright in one of them, and imported by none.

**What this holds and what it cannot.** It holds that a reason is *present*. It cannot hold that the
reason is true, or that it is a good one — that is a reading, and the same limit the counting gate
in ``test_documentation.py`` carries for the same cause. What it does buy is that the next bare
reach cannot arrive in silence.
"""

import ast
import importlib
import io
import re
import subprocess
import tokenize
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PACKAGE = "elenctic"

type _Surfaces = dict[str, tuple[frozenset[str], frozenset[str]]]
"""Each module of the package → the names it offers, and the names it defines. Both are needed:
what a module withholds is what it defines and does not offer, and neither half answers alone."""


@dataclass(frozen=True)
class _Reach:
    """One evaluation of one internal name, and where the source spells it."""

    name: str
    owner: str
    path: Path
    line: int

    @property
    def qualified(self) -> str:
        return f"{self.owner}.{self.name}"


def _dunder(name: str) -> bool:
    """A name the language owns rather than the module. No ``__all__`` lists one."""
    return name.startswith("__") and name.endswith("__")


def _listed(*patterns: str) -> list[Path]:
    """The files git lists for ``patterns``, which is the authority on what this repository ships.

    ``.gitignore`` is the list of what is not shipped, it is already written, and this is how to
    read it — the same move ``test_documentation.py`` makes for the same reason. A filesystem walk
    wide enough to find every test also finds the caches and the environment.
    """
    listed = subprocess.run(
        ["git", "-C", str(_ROOT), "ls-files", "-z", *patterns],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(_ROOT / name for name in listed.split("\0") if name)


def _defined_by(source: str) -> frozenset[str]:
    """The names a module binds at its top level *by defining them*, imports excluded.

    ``ast`` rather than ``symtable``, and the difference is the whole point: ``symtable`` answers
    what a source *binds*, which includes everything it imported, and the question here is what a
    source *defines*. The limit that leaves is the mirror of it — a name defined conditionally
    inside an ``if`` at module level is not seen, and this package writes none.
    """
    defines: set[str] = set()
    for node in ast.parse(source).body:
        match node:
            case (
                ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
            ):
                defines.add(name)
            case ast.Assign(targets=targets):
                defines.update(t.id for t in targets if isinstance(t, ast.Name))
            case ast.AnnAssign(target=ast.Name(id=name)) | ast.TypeAlias(name=ast.Name(id=name)):
                defines.add(name)
    return frozenset(defines)


def _surfaces() -> _Surfaces:
    """Every module this package ships → what it offers, and what it defines.

    Two authorities, each for what it is the authority on. Git says which modules exist, so
    ``solvers`` is a module because ``src/elenctic/solvers.py`` is tracked — which is also what
    tells a module's internal surface apart from a *class*'s private attribute, a different class
    with a different remedy. The module then says what it offers, by declaring ``__all__``.
    """
    found: _Surfaces = {}
    for path in _listed(f"src/{_PACKAGE}/*.py", f"src/{_PACKAGE}/**/*.py"):
        parts = path.relative_to(_ROOT / "src").with_suffix("").parts
        dotted = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        declared = getattr(importlib.import_module(dotted), "__all__", None)
        assert declared is not None, (
            f"{dotted} declares no __all__, so this check has no authority to read it by and "
            f"every name in it would be reported as withheld"
        )
        found[dotted] = (frozenset(declared), _defined_by(path.read_text(encoding="utf-8")))
    return found


def _dotted(node: ast.expr) -> str | None:
    """``a.b.c`` as a string, or ``None`` for anything that is not a chain of plain names."""
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=ast.expr() as value, attr=attr):
            prefix = _dotted(value)
            return f"{prefix}.{attr}" if prefix else None
        case _:
            return None


def _module_aliases(tree: ast.Module) -> dict[str, str]:
    """Local name → the package path it is bound to, for every import in ``tree``.

    ``import elenctic.solvers`` binds **``elenctic``**, not ``elenctic.solvers``: the submodule is
    reached through the package name. Following the statement's spelling instead is what makes a
    dotted reach like ``elenctic.solvers._drive`` invisible, so the language's binding rule is what
    is followed here.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        match node:
            case ast.Import(names=names):
                for alias in names:
                    if alias.name != _PACKAGE and not alias.name.startswith(f"{_PACKAGE}."):
                        continue
                    bound = alias.asname or alias.name.split(".")[0]
                    aliases[bound] = alias.name if alias.asname else bound
            case ast.ImportFrom(module=str(module), names=names, level=0) if (
                module == _PACKAGE or module.startswith(f"{_PACKAGE}.")
            ):
                for alias in names:
                    aliases.setdefault(alias.asname or alias.name, f"{module}.{alias.name}")
    return aliases


def _reaches(tree: ast.Module, path: Path, surfaces: _Surfaces) -> list[_Reach]:
    """Every internal name ``tree`` evaluates, one entry per evaluation rather than per name.

    Four forms, because an import is only one of them:

    * ``from elenctic.solvers import _drive`` — the name is bound in the test module;
    * ``solvers._drive(...)`` — an attribute of a module the file imported;
    * ``monkeypatch.setattr(solvers, "_drive", …)`` and ``getattr``, including the dotted spelling
      ``setattr("elenctic.solvers._drive", …)``, which no AST walk over ``Attribute`` nodes sees;
    * ``import elenctic._private_module`` — the module itself, which no ``__all__`` governs, so the
      convention is all there is to read it by.
    """
    aliases = _module_aliases(tree)
    found: list[_Reach] = []

    def internal(module: str, name: str) -> bool:
        """Whether ``module`` withholds ``name``: its ``__all__`` omits it and it is its to offer,
        either because the module defines it or because it is spelled private — which an imported
        name being patched at its point of use never is.

        The second arm is what keeps the root package readable: ``elenctic/__init__.py`` resolves
        its surface lazily rather than defining it, so asking only "is it defined here" would
        answer no for every name it offers.
        """
        declared, defined = surfaces.get(module, (frozenset(), frozenset()))
        if _dunder(name) or name in declared:
            return False
        return name in defined or name.startswith("_")

    def resolve(owner: str) -> str | None:
        """The package path ``owner`` names, or ``None`` if it is not this package's."""
        head, *rest = owner.split(".")
        target = aliases.get(head)
        if target is None:
            return None
        full = ".".join([target, *rest])
        return full if full == _PACKAGE or full.startswith(f"{_PACKAGE}.") else None

    for node in ast.walk(tree):
        match node:
            case ast.ImportFrom(module=str(module), names=names, level=0) if module in surfaces:
                for alias in names:
                    # `from elenctic import corpus` names a submodule, not a name it withholds.
                    if f"{module}.{alias.name}" in surfaces:
                        continue
                    if internal(module, alias.name):
                        found.append(_Reach(alias.name, module, path, alias.lineno))
            case ast.Import(names=names):
                # A module's own name is governed by no ``__all__``, so the convention is the only
                # thing there is to read it by. This package writes no private module today.
                found.extend(
                    _Reach(alias.name, alias.name, path, node.lineno)
                    for alias in names
                    if alias.name.startswith(f"{_PACKAGE}.")
                    and any(
                        part.startswith("_") and not _dunder(part) for part in alias.name.split(".")
                    )
                )
            case ast.Attribute(value=ast.expr() as value, attr=str(attr)) if not _dunder(attr):
                spelled = _dotted(value)
                full = resolve(spelled) if spelled else None
                # `elenctic.solvers` inside `elenctic.solvers._x` is a submodule, not a name.
                if full is None or f"{full}.{attr}" in surfaces:
                    continue
                if full in surfaces and internal(full, attr):
                    found.append(_Reach(attr, full, path, node.lineno))
            case ast.Call(func=ast.expr() as func, args=args):
                call = _dotted(func) or ""
                if not call.endswith(("setattr", "getattr")):
                    continue
                for argument in args:
                    if not isinstance(argument, ast.Constant):
                        continue
                    if not isinstance(argument.value, str):
                        continue
                    owner, _, attr = argument.value.rpartition(".")
                    if owner in surfaces and internal(owner, attr):
                        found.append(_Reach(attr, owner, path, node.lineno))
                    elif not owner and len(args) > 1 and not _dunder(argument.value):
                        spelled = _dotted(args[0])
                        full = resolve(spelled) if spelled else None
                        if full in surfaces and internal(str(full), argument.value):
                            found.append(_Reach(argument.value, str(full), path, node.lineno))
    return found


def _comment_lines(source: str) -> dict[int, str]:
    """Every comment in ``source``, keyed by the line it sits on.

    From ``tokenize`` rather than by matching ``#``, so a hash inside a string literal — of which
    this suite writes a great many, being full of ``.lp`` fixtures — is not mistaken for one.
    """
    return {
        token.start[0]: token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    }


def _scopes(tree: ast.Module) -> dict[int, str]:
    """Line → the name of the innermost function containing it. Module level is absent.

    This is what keeps a reason *near* what it explains. Without it, prose anywhere in the file
    discharges the claim, and that is not a hypothetical: ``test_documentation.py`` writes
    ``_lex`` as an incidental example inside an unrelated function eight hundred lines from the
    only place that reaches it, and that mention alone satisfied this check until it was measured.
    Innermost wins, so a nested helper's comment is that helper's rather than its parent's.
    """
    spans: list[tuple[int, int, str]] = [
        (node.lineno, node.end_lineno or node.lineno, node.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    found: dict[int, str] = {}
    for start, end, name in sorted(spans, key=lambda span: span[0] - span[1]):
        found.update(dict.fromkeys(range(start, end + 1), name))
    return found


# A comment that opens with a tool directive. It sits where a reason would sit and is not one, so a
# `# type: ignore[arg-type]` after an internal import must not discharge the claim.
#
# The colon is what makes this a directive rather than a word: every one of these spellings is
# `<tool>:` or a bare `noqa`, whereas `# type of search this drives` is a sentence that starts
# with one of the words. Written the looser way first, and the control caught it.
_PRAGMA = re.compile(r"^#\s*(type|noqa|fmt|pragma|ruff|mypy|isort)\s*(:|$)")


def _names(name: str, text: str) -> bool:
    """Whether ``text`` writes ``name`` as a whole word rather than inside a longer one.

    A plain substring test is wrong here and this package is why: ``_parse`` is a proper prefix of
    ``_parse_faults``, ``_parse_goal`` and ``_parse_answer``, ``_check`` of two more, ``_outcome``
    of ``_outcome_unless_satisfiable`` — fifteen such pairs among its internal names. Under a
    substring test a comment about one of them silently discharges the obligation for the other.
    """
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) is not None


def _says_why(
    reach: _Reach,
    comments: dict[int, str],
    scopes: dict[int, str],
    docstring: str,
    crowded: set[int],
) -> bool:
    """Whether the module states a reason for ``reach``, by any of the three things that can be it.

    **A comment on the reach's own line**, which needs no naming because the position already says
    which name it is about — but only where that line carries **one** internal name. Two names
    imported on one line share any comment after them, so a single sentence would discharge two
    obligations whose reasons differ, which is how a reason becomes a decoration. The remedy is the
    parenthesised import, a name to a line, and then the comment is unambiguous again. A comment
    that is only a tool directive is not a reason and does not count.

    **A comment naming it, in the reach's own scope.** Where the sentence sits is still the
    author's judgement — above the import, or at the head of the test body, which is where this
    suite writes most of its reasons — but it has to be somewhere a reader of the reach is already
    looking. **A module-level comment is not global prose**: it belongs to whatever it sits above,
    so it is in scope for a module-level reach and not for one inside a function.

    That distinction was measured rather than reasoned. ``test_documentation.py`` writes ``_lex``
    in a module-level comment about a *regex*, purely as an example of a spelling, eight hundred
    lines from the function that reaches ``_lex`` — and under every looser rule tried here, that
    mention alone discharged the obligation.

    **Or the module docstring naming it**, which every reader of the module has passed.

    The limit that leaves, stated rather than left to be found: within its scope, a passing mention
    counts as much as an argument does. This holds that a reason is present, never that it is a
    good one — the same limit the counting gate carries, and for the same cause.
    """
    on_the_line = comments.get(reach.line)
    if on_the_line and reach.line not in crowded and not _PRAGMA.match(on_the_line):
        return True
    if _names(reach.name, docstring):
        return True
    here = scopes.get(reach.line)
    return any(
        _names(reach.name, text) for line, text in comments.items() if scopes.get(line) == here
    )


def test_every_internal_name_this_suite_reaches_says_why() -> None:
    # The whole suite at once, and asserted whole rather than a file at a time, so a reader of a
    # failure sees every bare reach rather than the first — the same shape the documentation sweeps
    # use, and for the same reason: this is a list to work through, not a single thing to fix.
    surfaces = _surfaces()
    assert surfaces, (
        "git listed no package modules, so every name below would be read as offered and this "
        "check would pass by knowing nothing"
    )
    tests = _listed("tests/*.py", "tests/**/*.py")
    assert tests, "git listed no test modules; this is not a checkout and this sweep is vacuous"

    bare: list[str] = []
    couplings = 0
    for path in tests:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        found = _reaches(tree, path, surfaces)
        if not found:
            continue
        comments = _comment_lines(source)
        scopes = _scopes(tree)
        docstring = ast.get_docstring(tree) or ""
        crowded = {
            line for line in {r.line for r in found} if sum(r.line == line for r in found) > 1
        }
        by_name: dict[str, list[_Reach]] = {}
        for reach in found:
            by_name.setdefault(reach.qualified, []).append(reach)
        couplings += len(by_name)
        # Any one of a name's reaches may carry the reason — a reader of this file meets it either
        # way, and which line it sits on is the author's judgement rather than this check's.
        bare += [
            f"{path.relative_to(_ROOT)}:{reaches[0].line} {qualified}"
            for qualified, reaches in sorted(by_name.items())
            if not any(_says_why(reach, comments, scopes, docstring, crowded) for reach in reaches)
        ]

    assert couplings, (
        "no test reaches any internal name at all, which this suite certainly does — the reader "
        "has stopped reading and every reach below is unheld"
    )
    assert not bare, (
        f"{len(bare)} of {couplings} module-and-name couplings past a declared surface say "
        f"nothing about why: {bare}. Each is either a seam the surface has no path to — say so, "
        f"in a comment on the line — or a convenience, and then the public name is the one to use"
    )
