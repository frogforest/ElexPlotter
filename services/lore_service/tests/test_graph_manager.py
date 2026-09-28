import pytest
from lore_app.core.exceptions import ConflictException
from lore_app.services.graph_manager import DependencyGraphManager


def test_empty_graph() -> None:
    mgr = DependencyGraphManager()
    assert mgr.topological_sort() == []
    assert mgr.get_prerequisites(1) == set()


def test_linear_dependencies_and_sort() -> None:
    mgr = DependencyGraphManager()
    # 1 (Falk joined) -> 3 (Secret revealed)
    # 2 (Konrad appeared) -> 3 (Secret revealed)
    mgr.build_from_dependencies(
        event_ids=[1, 2, 3],
        dependencies=[(1, 3), (2, 3)],
    )

    prereqs = mgr.get_prerequisites(3)
    assert prereqs == {1, 2}

    descendants = mgr.get_descendants(1)
    assert descendants == {3}

    order = mgr.topological_sort()
    assert order.index(1) < order.index(3)
    assert order.index(2) < order.index(3)


def test_cycle_detection_on_build() -> None:
    mgr = DependencyGraphManager()
    with pytest.raises(ConflictException, match="Cycle detected"):
        mgr.build_from_dependencies(
            event_ids=[1, 2],
            dependencies=[(1, 2), (2, 1)],
        )


def test_cycle_detection_on_new_edge() -> None:
    mgr = DependencyGraphManager()
    mgr.build_from_dependencies(
        event_ids=[1, 2, 3],
        dependencies=[(1, 2), (2, 3)],
    )
    with pytest.raises(ConflictException, match="would introduce a cycle"):
        mgr.validate_new_edge(3, 1)

    with pytest.raises(ConflictException, match="cannot depend on itself"):
        mgr.validate_new_edge(1, 1)
