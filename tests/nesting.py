"""Terms nested deeper than the interpreter's recursion limit, for code that must not recurse."""

DEEP_NESTING = 1_500


def nested(depth: int = DEEP_NESTING, *, innermost: str = "1") -> str:
    """Write `innermost` wrapped in `depth` calls of `f`."""
    return "f(" * depth + innermost + ")" * depth
