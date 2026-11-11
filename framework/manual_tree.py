"""Project managed manual runs onto their source tree without altering run logs."""

from pathlib import Path


def manual_tree(root, jobs, present):
    root["sources"] = {}
    if root["imported"] or root["demo"]:
        return root
    # Identity is scoped by source run path AND admitted checkpoint checksum.
    identities = {(str(Path(root["path"]).resolve()), n["node_id"]):
                  (n["node_id"], n.get("checkpoint_sha256"))
                  for n in root["nodes"] if n["node_type"] == "candidate"}
    initial = next((n["fmax_mhz"] - n["fmax_improvement_mhz"] for n in root["nodes"]
                    if n.get("fmax_mhz") is not None and n.get("fmax_improvement_mhz") is not None), None)
    pending = sorted((j for j in jobs if j["config"].get("mode") == "manual"
                      and j["config"].get("parent_checkpoint")), key=lambda j: j["created"])
    while pending:
        remaining, changed = [], False
        for job in pending:
            source = job["config"]["parent_checkpoint"]
            if not isinstance(source, dict) or not isinstance(source.get("run_path"), str) or not isinstance(source.get("candidate_id"), str):
                continue
            origin = identities.get((str(Path(source["run_path"]).resolve()), source.get("candidate_id")))
            if not origin or not origin[1] or origin[1] != source.get("checkpoint_sha256"):
                remaining.append(job)
                continue
            changed = True
            parent, _ = origin
            head = f"manual:{job['id']}"
            run = Path(job["directory"]) / "run"
            plan = job["config"].get("manual_plan", [])
            strategy = plan[0]["strategy"] if plan else "Manual sequence"
            common = {"manual": True, "job_id": job["id"], "job_status": job["status"],
                      "job_error": job.get("error"), "in_beam": False, "is_best": False}
            data, error = None, None
            if (run / "events.jsonl").is_file():
                try:
                    data = present(run, job)
                    root["sources"][data["id"]] = data
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    error = str(exc)
            visible = []
            local = {}
            if data:
                for n in data["nodes"]:
                    if n["node_type"] == "candidate" and not n.get("parent_node_id"):
                        local[n["node_id"]] = parent
                        identities[(str(run.resolve()), n["node_id"])] = (parent, n.get("checkpoint_sha256"))
                    else:
                        visible.append(n)
                for index, n in enumerate(visible):
                    local[n["node_id"]] = head if index == 0 else f"{head}:{n.get('attempt_id') or n['node_id']}"
                for n in visible:
                    graph_id = local[n["node_id"]]
                    fmax = n.get("fmax_mhz")
                    root["nodes"].append(n | common | {
                        "node_id": graph_id, "local_node_id": n["node_id"], "source_run_key": data["id"],
                        "parent_node_id": local.get(n.get("parent_node_id"), parent),
                        "fmax_improvement_mhz": fmax - initial if fmax is not None and initial is not None else None,
                    })
                    if n["node_type"] == "candidate":
                        identities[(str(run.resolve()), n["node_id"])] = (graph_id, n.get("checkpoint_sha256"))
                for edge in data["edges"]:
                    if edge["target_id"] in local and local[edge["target_id"]] != parent:
                        root["edges"].append(edge | {"source_id": local.get(edge["source_id"], parent),
                                                    "target_id": local[edge["target_id"]], "manual": True})
            if not visible:
                state = "unknown" if error else "running" if job["status"] in {"starting", "running", "orphaned", "cancelling"} else job["status"]
                root["nodes"].append(common | {"node_id": head, "node_type": "manual_execution",
                    "parent_node_id": parent, "strategy": strategy, "state": state,
                    "can_run_from": False, "checkpoint_unavailable_reason": error or "No result checkpoint yet",
                    "fmax_mhz": None, "fmax_improvement_mhz": None, "wns_ns": None})
                root["edges"].append({"source_id": parent, "target_id": head, "strategy": strategy, "manual": True})
        if not changed:
            break
        pending = remaining
    return root


def watched_files(run, database, jobs):
    runs = [run, *(Path(j["directory"]) / "run" for j in jobs if j["config"].get("mode") == "manual")]
    return [database, *(folder / name for folder in runs
                        for name in ("events.jsonl", "run_summary.json", "published_artifact.json"))]
