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

    def topological_sort(
        self,
        subset_event_ids: list[int] | None = None,
        sort_keys: dict[int, int] | None = None,
    ) -> list[int]:
        """
        Returns topologically sorted event IDs.
        If sort_keys is provided ({event_id: sort_order}), nodes at the same topological level
        are ordered according to their sort_order preference.
        """
        target_graph = self._graph
        if subset_event_ids is not None:
            valid_ids = [eid for eid in subset_event_ids if self._graph.has_node(eid)]
            target_graph = self._graph.subgraph(valid_ids)

        if not sort_keys:
            return list(nx.topological_sort(target_graph))

        # Kahn's algorithm with priority ordering by sort_keys
        in_degree = dict(target_graph.in_degree())
        zero_in_degree = [node for node, deg in in_degree.items() if deg == 0]
        zero_in_degree.sort(key=lambda n: sort_keys.get(n, 0))

        result: list[int] = []
        while zero_in_degree:
            node = zero_in_degree.pop(0)
            result.append(node)
            new_zeros: list[int] = []
            for neighbor in target_graph.successors(node):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    new_zeros.append(neighbor)
            new_zeros.sort(key=lambda n: sort_keys.get(n, 0))
            zero_in_degree.extend(new_zeros)
            zero_in_degree.sort(key=lambda n: sort_keys.get(n, 0))

        return result
