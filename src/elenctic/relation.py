"""Relations: the values that variables take together, as rows under named columns."""

from dataclasses import dataclass

from clingo import Symbol

from elenctic.terms import Variable

type Row = tuple[Symbol, ...]


@dataclass(frozen=True, slots=True)
class Relation:
    """Rows of ground symbols, one for each of some columns, which are variables."""

    columns: tuple[Variable, ...]
    rows: frozenset[Row]

    def grouped(self, by: tuple[Variable, ...]) -> dict[Row, list[Row]]:
        """Group the rows by what they hold in the columns `by`."""
        at = [self.columns.index(variable) for variable in by]
        groups: dict[Row, list[Row]] = {}
        for row in self.rows:
            groups.setdefault(tuple(row[i] for i in at), []).append(row)
        return groups

    def join(self, other: Relation) -> Relation:
        """Return the rows of both that agree wherever they share a column, over all columns.

        The rows of `other` are grouped by the shared columns, so each row of `self` is paired
        only with those it agrees with.
        """
        shared = tuple(c for c in self.columns if c in other.columns)
        extra = tuple(c for c in other.columns if c not in self.columns)
        groups = other.grouped(shared)
        at = [self.columns.index(variable) for variable in shared]
        beyond = [other.columns.index(variable) for variable in extra]
        return Relation(
            (*self.columns, *extra),
            frozenset(
                (*row, *(match[i] for i in beyond))
                for row in self.rows
                for match in groups.get(tuple(row[i] for i in at), ())
            ),
        )

    def union(self, other: Relation) -> Relation:
        """Return the rows of either, for two relations over the same columns in any order."""
        if set(self.columns) != set(other.columns):
            message = f"cannot unite columns {self.columns} with {other.columns}"
            raise ValueError(message)
        at = [other.columns.index(variable) for variable in self.columns]
        return Relation(
            self.columns, self.rows | frozenset(tuple(row[i] for i in at) for row in other.rows)
        )

    def assignments(self) -> list[dict[Variable, Symbol]]:
        """Return each row as the values its columns take."""
        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]
