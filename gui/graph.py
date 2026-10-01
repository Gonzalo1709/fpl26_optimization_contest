"""Interactive candidate ancestry figure with selectable nodes."""

import json


def search_figure(tables, best_id=None):
    import plotly.graph_objects as go

    nodes = tables["tree_nodes"]
    parents = {edge["target_id"]: edge["source_id"] for edge in tables["tree_edges"]}
    depth = {}

    def level(node_id, visiting=None):
        visiting = set() if visiting is None else visiting
        if node_id in depth:
            return depth[node_id]
        if node_id in visiting:
            return 0
        visiting.add(node_id)
        parent = parents.get(node_id)
        depth[node_id] = level(parent, visiting) + 1 if parent else 0
        return depth[node_id]

    rows = {}
    positions = {}
    for node in nodes:
        column = level(node["node_id"])
        row = rows.get(column, 0)
        rows[column] = row + 1
        positions[node["node_id"]] = (column, -row)
    xs, ys = [], []
    for edge in tables["tree_edges"]:
        if edge["source_id"] in positions and edge["target_id"] in positions:
            start, end = positions[edge["source_id"]], positions[edge["target_id"]]
            xs.extend([start[0], end[0], None])
            ys.extend([start[1], end[1], None])
    beams = tables["beams"]
    beam = set(json.loads(beams[-1].get("candidate_ids", "[]"))) if beams else set()
    figure = go.Figure()
    figure.add_scatter(x=xs, y=ys, mode="lines", line={"color": "#94a3b8"}, hoverinfo="skip")
    figure.add_scatter(x=[positions[node["node_id"]][0] for node in nodes],
                       y=[positions[node["node_id"]][1] for node in nodes],
                       customdata=[node["node_id"] for node in nodes],
                       text=[f"{node['node_id']}<br>{node.get('strategy') or node['node_type']}<br>WNS: {node.get('wns_ns')} ns" for node in nodes],
                       mode="markers", hovertemplate="%{text}<extra></extra>",
                       marker={"size": 18, "color": ["#22c55e" if node["node_id"] == best_id else "#60a5fa" for node in nodes],
                               "symbol": ["circle" if node["node_type"] == "candidate" else "x" for node in nodes],
                               "line": {"width": 3, "color": ["#f97316" if node["node_id"] in beam else "#334155" for node in nodes]}})
    figure.update_layout(showlegend=False, clickmode="event+select", height=450,
                         xaxis={"title": "Ancestry depth", "dtick": 1}, yaxis={"visible": False},
                         margin={"l": 20, "r": 20, "t": 20, "b": 40})
    return figure
