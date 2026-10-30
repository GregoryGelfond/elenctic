from elenctic.partition import Partition


def partition_of(size: int) -> Partition:
    classes = Partition()
    for _ in range(size):
        classes.add()
    return classes


def test_each_element_starts_in_a_set_of_its_own() -> None:
    classes = partition_of(3)
    assert len(classes) == 3
    assert [classes.find(i) for i in range(3)] == [0, 1, 2]


def test_a_union_joins_two_sets_under_one_representative() -> None:
    classes = partition_of(4)
    joined = classes.union(0, 1)
    assert classes.find(0) == classes.find(1) == joined
    assert classes.find(2) != joined


def test_the_set_of_greater_rank_keeps_its_representative() -> None:
    classes = partition_of(3)
    classes.union(0, 1)
    top = classes.find(0)
    assert classes.union(top, 2) == top


def test_a_link_puts_one_set_beneath_another_whatever_their_ranks() -> None:
    classes = partition_of(2)
    classes.link(0, 1)
    assert classes.find(0) == 1


def test_finding_halves_the_path_and_leaves_the_sets_unchanged() -> None:
    classes = partition_of(6)
    for i in range(5):
        classes.link(i, i + 1)
    assert [classes.find(i) for i in range(6)] == [5] * 6
