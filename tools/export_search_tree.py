"""Export one run's candidate lineage and unsuccessful attempts as SVG, DOT, or Mermaid.

Usage: python -m tools.export_search_tree RUN_DIR --out search_tree.svg
"""

import argparse
import json
from html import escape
from pathlib import Path

from tools.export_run_tables import build_tables


def _quoted(value) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def build_dot(run_dir: Path) -> str:
    tables = build_tables([run_dir])
    summary_path = run_dir / "run_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    best_id = summary.get("best_candidate_id")
    lines = ["digraph search_tree {", "  rankdir=LR;", "  node [fontname=Arial];"]
    for node in tables["tree_nodes"]:
        node_id = node["node_id"]
        if node["node_type"] == "candidate":
            wns = node.get("wns_ns")
            metric = f"\nWNS {wns:.3f} ns" if isinstance(wns, (int, float)) else ""
            label = f"{node_id}{metric}"
            color = "palegreen" if node_id == best_id else "lightblue"
            lines.append(f"  {_quoted(node_id)} [label={_quoted(label)}, style=filled, fillcolor={_quoted(color)}];")
        else:
            label = f"{node.get('strategy') or 'attempt'}\n{node.get('recipe_status')}"
            lines.append(f"  {_quoted(node_id)} [label={_quoted(label)}, shape=box, style=dashed];")
    for edge in tables["tree_edges"]:
        strategy = edge.get("strategy") or "unknown"
        delta = edge.get("delta_wns_ns")
        label = f"{strategy} ({delta:+.3f} ns)" if isinstance(delta, (int, float)) else strategy
        lines.append(f"  {_quoted(edge['source_id'])} -> {_quoted(edge['target_id'])} "
                     f"[label={_quoted(label)}];")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _mermaid_text(value) -> str:
    """Keep arbitrary logged values inside a quoted Mermaid label."""
    entities = {"#": "#35;", '"': "#quot;", "|": "#124;", "&": "#38;",
                "<": "#60;", ">": "#62;", "\n": "#10;"}
    return "".join(entities.get(char, char) for char in str(value))


def build_mermaid(run_dir: Path) -> str:
    """Show every exported node field in square nodes for schema inspection."""
    tables = build_tables([run_dir])
    summary_path = run_dir / "run_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    best_id = summary.get("best_candidate_id")
    latest_beam = tables["beams"][-1] if tables["beams"] else None
    retained = set(json.loads(latest_beam["candidate_ids"])) if latest_beam else set()
    node_aliases = {node["node_id"]: f"n{index}" for index, node in enumerate(tables["tree_nodes"])}
    preferred = ("candidate_id", "parent_id", "strategy", "selection_source", "generation",
                 "search_generation", "search_branch", "search_step", "wns_ns", "tns_ns",
                 "failing_endpoints", "delta_wns_ns", "projected_score", "validated_score",
                 "recipe_status", "recipe_seconds", "decision_id", "attempt_id")
    lines = ["flowchart LR"]
    for node in tables["tree_nodes"]:
        node_id = node["node_id"]
        fields = [key for key in preferred if key in node]
        fields.extend(sorted(node.keys() - set(fields) - {"node_id", "run_dir"}))
        details = [f"{_mermaid_text(node['node_type'])}: {_mermaid_text(node_id)}"]
        details.extend(f"{_mermaid_text(key)}: {_mermaid_text(node[key])}"
                       for key in fields if node[key] is not None)
        lines.append(f'    {node_aliases[node_id]}["' + "<br/>".join(details) + '"]')
    for edge in tables["tree_edges"]:
        source = node_aliases.get(edge["source_id"])
        target = node_aliases.get(edge["target_id"])
        if source and target:
            delta = edge.get("delta_wns_ns")
            label = edge.get("strategy") or "attempt"
            if isinstance(delta, (int, float)):
                label += f" {delta:+.3f} ns"
            lines.append(f"    {source} -->|{_mermaid_text(label)}| {target}")
    lines.extend(["    classDef best fill:#c8edca,stroke:#38683c;",
                  "    classDef beam stroke:#db8323,stroke-width:3px;",
                  "    classDef attempt fill:#f3f3f3,stroke:#777,stroke-dasharray:5 4;"])
    for node in tables["tree_nodes"]:
        alias = node_aliases[node["node_id"]]
        if node["node_type"] == "attempt_without_candidate":
            lines.append(f"    class {alias} attempt;")
        if node["node_id"] == best_id:
            lines.append(f"    class {alias} best;")
        if node["node_id"] in retained:
            lines.append(f"    class {alias} beam;")
    return "\n".join(lines) + "\n"


def build_svg(run_dir: Path) -> str:
    """Draw a dependency-free debug view; hover over nodes for full IDs."""
    tables = build_tables([run_dir])
    nodes = {node["node_id"]: node for node in tables["tree_nodes"]}
    children = {node_id: [] for node_id in nodes}
    for edge in tables["tree_edges"]:
        if edge["source_id"] in children and edge["target_id"] in nodes:
            children[edge["source_id"]].append(edge["target_id"])
    for descendants in children.values():
        descendants.sort(key=lambda node_id: nodes[node_id].get("timestamp_utc") or "")
    roots = sorted((node_id for node_id, node in nodes.items()
                    if node.get("parent_node_id") not in nodes),
                   key=lambda node_id: nodes[node_id].get("timestamp_utc") or "")
    positions = {}
    leaf_index = 0

    def place(node_id, depth):
        nonlocal leaf_index
        descendants = children[node_id]
        if descendants:
            for child_id in descendants:
                place(child_id, depth + 1)
            y = (positions[descendants[0]][1] + positions[descendants[-1]][1]) / 2
        else:
            y = 90 + leaf_index * 100
            leaf_index += 1
        positions[node_id] = (30 + depth * 280, y)

    for root in roots:
        place(root, 0)
    width = max((x for x, _ in positions.values()), default=30) + 230
    height = max((y for _, y in positions.values()), default=90) + 80
    summary_path = run_dir / "run_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    best_id = summary.get("best_candidate_id")
    latest_beam = next((event for event in reversed(tables["beams"])), None)
    retained = set(json.loads(latest_beam["candidate_ids"])) if latest_beam else set()
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
           f'width="{width}" height="{height}">',
           '<style>text{font:12px Arial,sans-serif;fill:#17212b} '
           '.small{font-size:10px;fill:#435466} .edge{stroke:#8092a4;stroke-width:1.5;fill:none} '
           '.box{stroke:#46647f;stroke-width:1.5}</style>',
           f'<text x="30" y="28" style="font-size:17px;font-weight:bold">'
           f'{escape(run_dir.name)} exploration tree</text>',
           '<text x="30" y="46" class="small">Green: final best · Orange border: last beam · '
           'Dashed: attempt without candidate · Edge label: strategy and WNS change</text>']
    for edge in tables["tree_edges"]:
        if edge["source_id"] not in positions or edge["target_id"] not in positions:
            continue
        sx, sy = positions[edge["source_id"]]
        tx, ty = positions[edge["target_id"]]
        x1, x2 = sx + 200, tx
        svg.append(f'<path class="edge" d="M{x1},{sy} C{x1+35},{sy} {x2-35},{ty} {x2},{ty}"/>')
        delta = edge.get("delta_wns_ns")
        label = edge.get("strategy") or "unknown"
        if isinstance(delta, (int, float)):
            label += f" {delta:+.3f} ns"
        svg.append(f'<text x="{(x1+x2)/2}" y="{(sy+ty)/2-7}" class="small" '
                   f'text-anchor="middle">{escape(label)}</text>')
    for node_id, node in nodes.items():
        x, y = positions[node_id]
        candidate = node["node_type"] == "candidate"
        fill = "#c8edca" if node_id == best_id else "#dceeff" if candidate else "#f3f3f3"
        stroke = "#db8323" if node_id in retained else "#46647f"
        dash = '' if candidate else ' stroke-dasharray="5 4"'
        wns = node.get("wns_ns")
        detail = f"WNS {wns:.3f} ns" if isinstance(wns, (int, float)) else node.get("recipe_status") or ""
        short_id = node_id if len(node_id) <= 25 else node_id[:22] + "..."
        svg.append(f'<g><title>{escape(json.dumps(node, ensure_ascii=False, default=str))}</title>'
                   f'<rect class="box" x="{x}" y="{y-30}" width="200" height="60" rx="7" '
                   f'fill="{fill}" stroke="{stroke}"{dash}/>'
                   f'<text x="{x+9}" y="{y-7}">{escape(short_id)}</text>'
                   f'<text x="{x+9}" y="{y+13}" class="small">{escape(str(detail))}</text></g>')
    svg.append('</svg>')
    return "\n".join(svg) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.suffix.lower() == ".svg":
        content = build_svg(args.run_dir)
    elif args.out.suffix.lower() == ".dot":
        content = build_dot(args.run_dir)
    elif args.out.suffix.lower() == ".mmd":
        content = build_mermaid(args.run_dir)
    else:
        parser.error("output file must end in .svg, .dot, or .mmd")
    args.out.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
