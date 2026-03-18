import networkx as nx
from app.services.parser import get_modified_functions
import logging

logger = logging.getLogger(__name__)


def build_dependency_graph(modified_functions: list[dict]) -> nx.DiGraph:
    """
    Build an in-memory NetworkX dependency graph from Tree-Sitter AST output.
    Each modified function becomes a node, and its internal calls become edges.
    """
    G = nx.DiGraph()

    for func in modified_functions:
        node_name = func["node_name"]
        G.add_node(node_name, **{
            "type": func["node_type"],
            "content": func["content"],
            "start_line": func["start_line"],
            "end_line": func["end_line"],
        })

        for dep in func.get("dependencies", []):
            G.add_edge(node_name, dep, type="CALLS")

    return G


def get_blast_radius_context(graph: nx.DiGraph, modified_names: list[str], max_depth: int = 2) -> str:
    """
    Walk the dependency graph to find all functions within `max_depth` hops
    of the modified code. Returns a formatted string for the LLM.
    """
    if graph.number_of_nodes() == 0:
        return ""

    blast_nodes = set()
    for name in modified_names:
        if name not in graph:
            continue
        # Callers (who calls this function?)
        try:
            ancestors = nx.single_source_shortest_path_length(graph.reverse(), name, cutoff=max_depth)
            blast_nodes.update(ancestors.keys())
        except nx.NodeNotFound:
            pass
        # Callees (what does this function call?)
        try:
            descendants = nx.single_source_shortest_path_length(graph, name, cutoff=max_depth)
            blast_nodes.update(descendants.keys())
        except nx.NodeNotFound:
            pass

    # Format context
    context_parts = []
    for node_name in blast_nodes:
        if node_name in modified_names:
            continue  # Skip the modified function itself
        data = graph.nodes.get(node_name, {})
        content = data.get("content", "")
        if content:
            context_parts.append(f"Dependency: {node_name}\n{content}")

    return "\n\n---\n\n".join(context_parts)
