"""Read-only dashboard data and graph helpers."""

import json
from pathlib import Path


def discover_runs(root: Path) -> list[Path]:
    """Accept a run itself or immediate child runs, including custom names."""
    if (root / "events.jsonl").is_file():
        return [root]
    return sorted((path for path in root.iterdir()
                   if path.is_dir() and (path / "events.jsonl").is_file()),
                  key=lambda path: path.name, reverse=True)


def read_optional_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def search_dot(tables: dict, best_id=None) -> str:
    """Build an escaped candidate graph from the same tables as CSV exports."""
    quote = lambda value: json.dumps(str(value), ensure_ascii=False)
    beams = tables["beams"]
    selected = set(json.loads(beams[-1].get("candidate_ids", "[]"))) if beams else set()
    lines = ['digraph search { rankdir=LR; node [style=filled, fontname="Arial"];']
    for node in tables["tree_nodes"]:
        node_id = node["node_id"]
        label = f"{node_id}\n{node.get('strategy') or node['node_type']}"
        if node.get("wns_ns") is not None:
            label += f"\nWNS {node['wns_ns']:.3f} ns"
        fill = "palegreen" if node_id == best_id else "lightblue"
        border = "orange" if node_id in selected else "gray"
        style = "filled,dashed" if node["node_type"] != "candidate" else "filled"
        lines.append(f"{quote(node_id)} [label={quote(label)}, fillcolor={quote(fill)}, "
                     f"color={quote(border)}, style={quote(style)}];")
    for edge in tables["tree_edges"]:
        lines.append(f"{quote(edge['source_id'])} -> {quote(edge['target_id'])} "
                     f"[label={quote(edge.get('strategy') or 'attempt')}];")
    return "\n".join(lines + ["}"])
