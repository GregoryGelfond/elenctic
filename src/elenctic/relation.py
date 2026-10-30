"""Relations: the values that variables take together, as rows under named columns."""

from collections.abc import Iterable
from dataclasses import dataclass

from clingo import Symbol

from elenctic.terms import Variable

type Row = tuple[Symbol, ...]


def _pick(row: Row, at: Iterable[int]) -> Row:
    """Return the values of `row` at the positions `at`."""
    return tuple(row[i] for i in at)


@dataclass(frozen=True, slots=True)
class Relation:
    """Rows of ground symbols, one for each of some columns, which are variables."""

    columns: tuple[Variable, ...]
    rows: frozenset[Row]

    def grouped(self, by: tuple[Variable, ...]) -> dict[Row, list[Row]]:
        """Group the rows by what they hold in the columns `by`."""
        at = self.indices(by)
        groups: dict[Row, list[Row]] = {}
        for row in self.rows:
            groups.setdefault(_pick(row, at), []).append(row)
        return groups

    def indices(self, variables: Iterable[Variable]) -> list[int]:
        """Return where each of `variables` is among the columns."""
        return [self.columns.index(variable) for variable in variables]

    def join(self, other: Relation) -> Relation:
        """Return the rows of both that agree wherever they share a column, over all columns.

        The rows of `other` are grouped by the shared columns, so each row of `self` is paired
        only with those it agrees with.
        """
        shared = tuple(c for c in self.columns if c in other.columns)
        extra = tuple(c for c in other.columns if c not in self.columns)
        groups = other.grouped(shared)
        at, beyond = self.indices(shared), other.indices(extra)
        return Relation(
            (*self.columns, *extra),
            frozenset(
                (*row, *_pick(match, beyond))
                for row in self.rows
                for match in groups.get(_pick(row, at), ())
            ),
        )

    def union(self, other: Relation) -> Relation:
        """Return the rows of either, for two relations over the same columns in any order."""
        if set(self.columns) != set(other.columns):
            message = f"cannot unite columns {self.columns} with {other.columns}"
            raise ValueError(message)
        at = other.indices(self.columns)
        return Relation(self.columns, self.rows | frozenset(_pick(row, at) for row in other.rows))
