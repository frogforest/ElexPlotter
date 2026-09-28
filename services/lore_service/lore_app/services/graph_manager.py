import networkx as nx
from lore_app.core.exceptions import ConflictException


class DependencyGraphManager:
    """Manages the Directed Acyclic Graph (DAG) of canon event dependencies."""

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()

    @property
    def graph(self) -> nx.DiGraph:
        return self._graph

    def build_from_dependencies(
        self, event_ids: list[int], dependencies: list[tuple[int, int]]
    ) -> None:
        """
        Build or reset graph from event IDs and (parent_id, child_id) dependency tuples.
        An edge parent -> child means child requires parent.
        """
        self._graph.clear()
        for eid in event_ids:
            self._graph.add_node(eid)

        for parent, child in dependencies:
            if not self._graph.has_node(parent):
                self._graph.add_node(parent)
            if not self._graph.has_node(child):
                self._graph.add_node(child)
            self._graph.add_edge(parent, child)

        if not nx.is_directed_acyclic_graph(self._graph):
            cycles = list(nx.simple_cycles(self._graph))
            raise ConflictException(f"Cycle detected in event dependencies: {cycles}")

    def validate_new_edge(self, parent_id: int, child_id: int) -> None:
        """Ensures that adding parent -> child does not introduce a cycle."""
        if parent_id == child_id:
            raise ConflictException("An event cannot depend on itself.")

        # If child already reaches parent, adding parent -> child would create a cycle
        if (
            self._graph.has_node(child_id)
            and self._graph.has_node(parent_id)
            and nx.has_path(self._graph, child_id, parent_id)
        ):
            raise ConflictException(
                f"Dependency from event {parent_id} to {child_id} would introduce a cycle."
            )

    def get_prerequisites(self, event_id: int) -> set[int]:
        """Returns all ancestor event IDs that must occur before event_id."""
        if not self._graph.has_node(event_id):
            return set()
        return set(nx.ancestors(self._graph, event_id))

    def get_descendants(self, event_id: int) -> set[int]:
        """Returns all event IDs that depend on event_id directly or indirectly."""
        if not self._graph.has_node(event_id):
            return set()
        return set(nx.descendants(self._graph, event_id))

    def topological_sort(self, subset_event_ids: list[int] | None = None) -> list[int]:
        """
        Returns topologically sorted event IDs.
        If subset_event_ids is provided, sorts only the subgraph induced by those IDs.
        """
        target_graph = self._graph
        if subset_event_ids is not None:
            valid_ids = [eid for eid in subset_event_ids if self._graph.has_node(eid)]
            target_graph = self._graph.subgraph(valid_ids)

        return list(nx.topological_sort(target_graph))
