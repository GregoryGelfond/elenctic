"""Sets of literals indexed by signature, so that those a pattern can match are found by search."""

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Iterator, Sequence

from elenctic.literals import Literal, Signature


def _signature(literal: Literal) -> Signature:
    return literal.signature


class Extension:
    """The literals of an answer set, or of the consequences of several, ordered by signature.

    The literals of one signature are adjacent, so those a pattern can match are found by two
    binary searches, in `O(log n)` for `n` literals, and are then read off as a slice, `O(k)`
    for the `k` that share the signature.
    """

    def __init__(self, literals: Iterable[Literal]) -> None:
        self._ordered: tuple[Literal, ...] = tuple(sorted(frozenset(literals), key=_signature))

    def __len__(self) -> int:
        return len(self._ordered)

    def __iter__(self) -> Iterator[Literal]:
        return iter(self._ordered)

    def with_signature(self, signature: Signature) -> Sequence[Literal]:
        """Return the literals having `signature`."""
        start = bisect_left(self._ordered, signature, key=_signature)
        end = bisect_right(self._ordered, signature, key=_signature)
        return self._ordered[start:end]
