"""
EDITH Graph Memory — Knowledge Graph (GraphRAG)

Maintains a persistent entity-relationship graph using NetworkX.
Entities and relationships are extracted from conversations and stored
as a JSON graph file, enabling multi-hop reasoning queries.

Example: "What technologies am I using for AyurStock?"
→ Traverses: Vaibhav -> builds -> AyurStock -> uses -> [Next.js, Supabase, ...]
"""

import os
import json
import threading
import re
import networkx as nx
import datetime
from config import MEMORY_DB_PATH, get_logger
from smart_router import smart_call

log = get_logger("graph_memory")
_graph_lock = threading.Lock()

GRAPH_PATH = os.path.join(MEMORY_DB_PATH, "edith_graph.json")


def _load_graph() -> nx.DiGraph:
    """Load the knowledge graph from disk, or create a new one."""
    if os.path.exists(GRAPH_PATH):
        try:
            with open(GRAPH_PATH, "r") as f:
                data = json.load(f)
            G = nx.node_link_graph(data)
            log.info(f"Graph loaded: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
            return G
        except Exception as e:
            log.error(f"Failed to load graph, creating new: {e}")
    return nx.DiGraph()


def _save_graph(G: nx.DiGraph):
    """Save the knowledge graph to disk."""
    try:
        os.makedirs(os.path.dirname(GRAPH_PATH), exist_ok=True)
        data = nx.node_link_data(G)
        with open(GRAPH_PATH, "w") as f:
            json.dump(data, f, indent=2)
        log.info(f"Graph saved: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    except Exception as e:
        log.error(f"Failed to save graph: {e}")


# Singleton graph instance
_graph = _load_graph()


def extract_triples(text: str) -> list:
    """
    Extract (Subject, Relation, Object) triples from text using the LLM.

    Args:
        text: A block of text (e.g. session queries joined together).

    Returns:
        List of (subject, relation, object) tuples.
    """
    prompt = f"""Extract knowledge triples from the following text.
A triple is (Subject, Relation, Object). Extract ONLY concrete, factual relationships.

TEXT:
{text}

Rules:
- Extract 1-5 triples maximum.
- Use short, lowercase node names (e.g. "vaibhav", "ayurstock", "next.js").
- Use simple relation verbs (e.g. "builds", "uses", "wants", "is learning", "lives in").
- Do NOT extract opinions or vague statements.
- If no clear triples exist, respond with: NONE

Format your response as JSON array ONLY, no other text:
[["subject", "relation", "object"], ["subject", "relation", "object"]]

If no triples: []"""

    try:
        response = smart_call(prompt, intent="reason")
        # Parse the JSON from the response
        # Find the JSON array in the response
        response = response.strip()

        # Try to find JSON array in the response
        start = response.find("[")
        end = response.rfind("]") + 1
        if start == -1 or end == 0:
            return []

        json_str = response[start:end]
        triples = json.loads(json_str)

        # Validate structure
        valid = []
        for t in triples:
            if isinstance(t, list) and len(t) == 3:
                subj, rel, obj = [str(x).strip().lower() for x in t]
                if subj and rel and obj:
                    valid.append((subj, rel, obj))

        log.info(f"Extracted {len(valid)} triples from text")
        return valid

    except Exception as e:
        log.error(f"Triple extraction failed: {e}")
        return []


def add_triples(triples: list):
    """
    Add a list of (subject, relation, object) triples to the graph.
    """
    global _graph
    timestamp = datetime.datetime.now().isoformat()

    with _graph_lock:
        for subj, rel, obj in triples:
            _graph.add_node(subj, last_updated=timestamp)
            _graph.add_node(obj, last_updated=timestamp)
            _graph.add_edge(subj, obj, relation=rel, added=timestamp)
            log.info(f"  Triple added: {subj} --[{rel}]--> {obj}")

        if triples:
            _save_graph(_graph)


def ingest_text(text: str):
    """
    Full pipeline: extract triples from text and add them to the graph.
    """
    triples = extract_triples(text)
    if triples:
        add_triples(triples)
    return triples


def extract_and_store_triples(text: str) -> int:
    """
    Extract simple factual triples without an LLM and persist them to the graph.

    This lightweight path is used by scheduled background maintenance, where a
    deterministic best-effort extraction is safer than a cloud/model call.
    """
    if not text or not text.strip():
        return 0

    patterns = [
        r"\b(?P<subject>[A-Z][\w.-]*(?:\s+[A-Z][\w.-]*)?)\s+(?P<predicate>uses|builds|created|creates|runs|needs|wants|likes|learns|prefers|works on|depends on)\s+(?P<object>[A-Z]?[A-Za-z0-9_.-]+(?:\s+[A-Z]?[A-Za-z0-9_.-]+){0,4})",
        r"\b(?P<subject>[A-Z][\w.-]*(?:\s+[A-Z][\w.-]*)?)\s+is\s+(?P<predicate>using|building|learning|running|working on)\s+(?P<object>[A-Z]?[A-Za-z0-9_.-]+(?:\s+[A-Z]?[A-Za-z0-9_.-]+){0,4})",
        r"\b(?P<subject>[A-Z][\w.-]*(?:\s+[A-Z][\w.-]*)?)\s+(?P<predicate>for)\s+(?P<object>[A-Z]?[A-Za-z0-9_.-]+(?:\s+[A-Z]?[A-Za-z0-9_.-]+){0,4})",
    ]
    stop_words = {
        "for", "with", "because", "when", "while", "and", "but", "or", "today",
        "tomorrow", "yesterday", "now", "then",
    }

    triples = []
    seen = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            subj = match.group("subject").strip(" .,;:!?\"'").lower()
            rel = match.group("predicate").strip().lower()
            obj_words = []
            for word in match.group("object").strip(" .,;:!?\"'").split():
                if word.lower() in stop_words:
                    break
                obj_words.append(word)
            obj = " ".join(obj_words).strip(" .,;:!?\"'").lower()
            if not subj or not rel or not obj or subj == obj:
                continue
            key = (subj, rel, obj)
            if key not in seen:
                seen.add(key)
                triples.append(key)

    if not triples:
        return 0

    add_triples(triples)
    return len(triples)


def query_graph(topic: str, depth: int = 2) -> str:
    """
    Query the knowledge graph for information about a topic.

    Args:
        topic: The entity to look up (e.g. "ayurstock", "vaibhav").
        depth: How many hops away to search (default 2).

    Returns:
        A human-readable string of relationships.
    """
    global _graph
    topic_lower = topic.strip().lower()

    with _graph_lock:
        # Find matching nodes (fuzzy: partial match)
        matching = [n for n in _graph.nodes() if topic_lower in n or n in topic_lower]

        if not matching:
            return f"No knowledge about '{topic}' in the graph yet."

        lines = []
        visited = set()

        def _traverse(node, current_depth):
            if current_depth > depth or node in visited:
                return
            visited.add(node)

            # Outgoing edges
            for _, target, data in _graph.out_edges(node, data=True):
                rel = data.get("relation", "related to")
                lines.append(f"  {node} --[{rel}]--> {target}")
                _traverse(target, current_depth + 1)

            # Incoming edges
            for source, _, data in _graph.in_edges(node, data=True):
                rel = data.get("relation", "related to")
                lines.append(f"  {source} --[{rel}]--> {node}")
                _traverse(source, current_depth + 1)

        for node in matching:
            _traverse(node, 0)

    if not lines:
        return f"'{topic}' exists in the graph but has no connections."

    # Deduplicate
    unique_lines = list(dict.fromkeys(lines))
    header = f"🕸️ Knowledge Graph — '{topic}' ({len(unique_lines)} relations):"
    return header + "\n" + "\n".join(unique_lines)


def graph_stats() -> str:
    """Return a summary of the graph state."""
    global _graph
    with _graph_lock:
        nodes = _graph.number_of_nodes()
        edges = _graph.number_of_edges()
        if nodes == 0:
            return "Knowledge Graph: Empty (no data yet)"
        top_nodes = sorted(_graph.nodes(), key=lambda n: _graph.degree(n), reverse=True)[:5]
        top_str = ", ".join(f"{n}({_graph.degree(n)})" for n in top_nodes)
    return f"Knowledge Graph: {nodes} entities, {edges} relations | Top: {top_str}"


if __name__ == "__main__":
    print("[EDITH Graph Memory] Testing...")

    # Manual triple test
    test_triples = [
        ("vaibhav", "builds", "edith"),
        ("vaibhav", "builds", "ayurstock"),
        ("edith", "uses", "pywhispercpp"),
        ("edith", "uses", "piper tts"),
        ("edith", "uses", "chromadb"),
        ("ayurstock", "uses", "next.js"),
        ("ayurstock", "uses", "supabase"),
        ("vaibhav", "lives in", "fatehpur"),
    ]
    add_triples(test_triples)

    print(f"\n{graph_stats()}\n")
    print(query_graph("edith"))
    print()
    print(query_graph("vaibhav"))
    print("Done.")
