"""Disjoint sets over the integers 0, 1, 2, ..., as a union-find."""


class Partition:
    """Elements added one at a time, each starting in a set of its own, and merged by `union`.

    `find` halves the path it walks and `union` joins by rank, so a run of `m` operations over
    `n` elements costs `O(m a(n))` for `a` the inverse of Ackermann's function, nearly linear.
    """

    def __init__(self) -> None:
        self._parent: list[int] = []
        self._rank: list[int] = []

    def add(self) -> int:
        """Add an element in a set of its own, and return it."""
        element = len(self._parent)
        self._parent.append(element)
        self._rank.append(0)
        return element

    def __len__(self) -> int:
        return len(self._parent)

    def find(self, element: int) -> int:
        """Return the representative of the set holding `element`."""
        parent = self._parent
        while parent[element] != element:
            parent[element] = parent[parent[element]]
            element = parent[element]
        return element

    def link(self, child: int, root: int) -> None:
        """Put the set represented by `child` under the one represented by `root`."""
        self._parent[child] = root

    def union(self, first: int, second: int) -> int:
        """Merge two sets by their representatives, and return the representative of the result."""
        low, high = sorted((first, second), key=self._rank.__getitem__)
        self.link(low, high)
        self._rank[high] += self._rank[low] == self._rank[high]
        return high
