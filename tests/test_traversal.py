from dataclasses import dataclass

from elenctic.traversal import fold


@dataclass(frozen=True)
class Tree:
    label: str
    below: tuple[Tree, ...] = ()


def test_a_fold_assembles_each_node_from_the_results_of_its_children_in_order() -> None:
    tree = Tree("a", (Tree("b", (Tree("c"),)), Tree("d")))
    shown = fold(tree, lambda t: t.below, lambda t, kids: f"{t.label}({','.join(kids)})")
    assert shown == "a(b(c()),d())"


def test_a_leaf_is_assembled_from_no_results() -> None:
    assert fold(Tree("x"), lambda t: t.below, lambda _t, kids: len(kids)) == 0


def test_a_fold_does_not_run_out_of_stack_on_a_tree_far_deeper_than_the_interpreter_allows() -> (
    None
):
    depth = 100_000
    chain = [Tree("leaf")]
    for _ in range(depth):
        chain.append(Tree("node", (chain[-1],)))
    assert fold(chain[-1], lambda t: t.below, lambda _t, kids: 1 + sum(kids)) == depth + 1


def test_a_shared_node_is_folded_each_time_it_is_met() -> None:
    shared = Tree("s")
    tree = Tree("r", (shared, shared))
    assert fold(tree, lambda t: t.below, lambda _t, kids: 1 + sum(kids)) == 3
