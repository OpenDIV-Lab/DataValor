"""Dependency-free lineage graph and change-impact analysis.

The graph is deliberately small and portable: callers can populate it from
``MetadataRecord.lineage`` or from an external catalog, then use the same
algorithms locally and in a production adapter.  Node and edge identifiers are
stable, which makes the digest suitable for audit records and cache keys.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from datavalor.core import DataProduct, canonical_sha256

from .models import MetadataRecord


@dataclass(frozen=True)
class LineageNode:
    node_id: str
    kind: str
    label: str = ""
    version: str | None = None
    checksum: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LineageEdge:
    source_id: str
    target_id: str
    relation: str = "derived_from"
    metadata: Mapping[str, Any] = field(default_factory=dict)


class LineageGraph:
    """A directed acyclic (when valid) graph with field/artifact metadata."""

    def __init__(self, nodes: Iterable[LineageNode] = (), edges: Iterable[LineageEdge] = ()) -> None:
        self._nodes: dict[str, LineageNode] = {}
        self._edges: list[LineageEdge] = []
        for node in nodes:
            self.add_node(node)
        for edge in edges:
            self.add_edge(edge)

    @property
    def nodes(self) -> tuple[LineageNode, ...]:
        return tuple(self._nodes[key] for key in sorted(self._nodes))

    @property
    def edges(self) -> tuple[LineageEdge, ...]:
        return tuple(sorted(self._edges, key=lambda e: (e.source_id, e.target_id, e.relation)))

    def add_node(self, node: LineageNode) -> None:
        if not node.node_id:
            raise ValueError("lineage node_id cannot be empty")
        if node.node_id in self._nodes and self._nodes[node.node_id] != node:
            raise ValueError(f"duplicate lineage node: {node.node_id}")
        self._nodes[node.node_id] = node

    def add_edge(self, edge: LineageEdge) -> None:
        if edge.source_id not in self._nodes or edge.target_id not in self._nodes:
            raise KeyError(f"lineage edge references missing node: {edge.source_id}->{edge.target_id}")
        if edge.source_id == edge.target_id:
            raise ValueError("lineage self-cycle is not allowed")
        if edge not in self._edges:
            self._edges.append(edge)

    def _walk(self, start: str, upstream: bool) -> tuple[str, ...]:
        if start not in self._nodes:
            raise KeyError(f"unknown lineage node: {start}")
        adjacency: dict[str, list[str]] = {key: [] for key in self._nodes}
        for edge in self._edges:
            (adjacency[edge.target_id] if upstream else adjacency[edge.source_id]).append(
                edge.source_id if upstream else edge.target_id
            )
        seen: set[str] = set()
        queue = deque(adjacency[start])
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            queue.extend(adjacency[current])
        return tuple(sorted(seen))

    def trace_upstream(self, node_id: str) -> tuple[LineageNode, ...]:
        return tuple(self._nodes[key] for key in self._walk(node_id, True))

    def trace_downstream(self, node_id: str) -> tuple[LineageNode, ...]:
        return tuple(self._nodes[key] for key in self._walk(node_id, False))

    def topological_order(self) -> tuple[str, ...]:
        indegree = {key: 0 for key in self._nodes}
        outgoing: dict[str, list[str]] = {key: [] for key in self._nodes}
        for edge in self._edges:
            indegree[edge.target_id] += 1
            outgoing[edge.source_id].append(edge.target_id)
        queue = deque(sorted(key for key, degree in indegree.items() if degree == 0))
        result: list[str] = []
        while queue:
            current = queue.popleft()
            result.append(current)
            for target in sorted(outgoing[current]):
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        if len(result) != len(self._nodes):
            raise ValueError("lineage graph contains a cycle")
        return tuple(result)

    def affected_artifacts(self, changed_node: str, kinds: Iterable[str] = ()) -> tuple[LineageNode, ...]:
        allowed = set(kinds)
        downstream = self.trace_downstream(changed_node)
        return tuple(node for node in downstream if not allowed or node.kind in allowed)

    def lineage_digest(self) -> str:
        return canonical_sha256({"nodes": [node.__dict__ for node in self.nodes], "edges": [edge.__dict__ for edge in self.edges]})

    def validate(self) -> tuple[str, ...]:
        """Return non-fatal quality warnings (missing field/source annotations)."""
        warnings: list[str] = []
        for edge in self._edges:
            if edge.relation == "derived_from" and not edge.metadata.get("transformation"):
                warnings.append(f"edge {edge.source_id}->{edge.target_id} lacks transformation")
        return tuple(warnings)


def build_lineage_graph(
    products: Iterable[DataProduct] = (),
    metadata_records: Iterable[MetadataRecord] = (),
    edges: Iterable[LineageEdge] = (),
    artifact_nodes: Iterable[LineageNode] = (),
) -> LineageGraph:
    """Build a graph from DataGov products/metadata and optional catalog edges."""
    graph = LineageGraph(artifact_nodes)
    records = {record.product_id: record for record in metadata_records}
    for product in products:
        graph.add_node(LineageNode(product.product_id, "data_product", product.title, product.version, product.data.checksum, product.metadata))
        record = records.get(product.product_id)
        if record:
            for ref in record.lineage:
                if ref.artifact_id not in graph._nodes:
                    graph.add_node(LineageNode(ref.artifact_id, ref.kind, ref.artifact_id, checksum=ref.checksum, metadata={"uri": ref.uri}))
                graph.add_edge(LineageEdge(ref.artifact_id, product.product_id, "derived_from", {"source": record.source}))
    for edge in edges:
        graph.add_edge(edge)
    graph.topological_order()  # fail early on cycles
    return graph


def trace_upstream(graph: LineageGraph, node_id: str) -> tuple[LineageNode, ...]:
    return graph.trace_upstream(node_id)


def trace_downstream(graph: LineageGraph, node_id: str) -> tuple[LineageNode, ...]:
    return graph.trace_downstream(node_id)


def affected_artifacts(graph: LineageGraph, changed_node: str, kinds: Iterable[str] = ()) -> tuple[LineageNode, ...]:
    return graph.affected_artifacts(changed_node, kinds)


def compare_lineage(left: LineageGraph, right: LineageGraph) -> dict[str, tuple[str, ...]]:
    """Compare two snapshots and classify added/removed/changed nodes and edges."""
    ln, rn = {n.node_id: n for n in left.nodes}, {n.node_id: n for n in right.nodes}
    def edge_key(edge: LineageEdge) -> tuple[str, str, str, str]:
        return (edge.source_id, edge.target_id, edge.relation, canonical_sha256(edge.metadata))

    le, re = {edge_key(edge) for edge in left.edges}, {edge_key(edge) for edge in right.edges}
    changed = tuple(sorted(key for key in set(ln) & set(rn) if ln[key] != rn[key]))
    return {"nodes_added": tuple(sorted(set(rn) - set(ln))), "nodes_removed": tuple(sorted(set(ln) - set(rn))), "nodes_changed": changed, "edges_added": tuple(sorted(f"{e[0]}->{e[1]}:{e[2]}" for e in re - le)), "edges_removed": tuple(sorted(f"{e[0]}->{e[1]}:{e[2]}" for e in le - re))}
