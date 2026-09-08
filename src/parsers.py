"""Pure parsing and file-loading helpers for the FPGA optimizer."""

import json
import re
from typing import Any

from src.prompting import load_system_prompt


def parse_critical_route_net_report(timing_report: str) -> list[dict]:
	"""Aggregate net-delay evidence from Vivado's text timing-path report."""
	aggregate = {}
	for path_section in re.split(r"Slack \(", timing_report)[1:]:
		seen_on_path = set()
		for line in path_section.splitlines():
			stripped = line.strip()
			if not (stripped.startswith("net (") or stripped.startswith("net(")):
				continue
			fields = stripped.split()
			if len(fields) < 3:
				continue
			net_name = fields[-1]
			numeric_tokens = []
			for token in fields[1:-1]:
				try:
					numeric_tokens.append(float(token))
				except ValueError:
					continue
			if not numeric_tokens:
				continue
			net_delay_ns = numeric_tokens[0]
			item = aggregate.setdefault(
				net_name,
				{
					"net_name": net_name,
					"critical_path_count": 0,
					"net_delay_ns": net_delay_ns,
					"is_route_fixed": False,
					"is_clock": False,
				},
			)
			item["net_delay_ns"] = max(item["net_delay_ns"], net_delay_ns)
			if net_name not in seen_on_path:
				item["critical_path_count"] += 1
				seen_on_path.add(net_name)
	return sorted(
		aggregate.values(),
		key=lambda item: (item["net_delay_ns"], item["critical_path_count"]),
		reverse=True,
	)


def parse_target_clock_report(report: str) -> tuple[str | None, float | None]:
	"""Parse the explicit clock marker and period returned by Vivado Tcl."""
	clock_name = None
	for token in report.split():
		if token.startswith("CLOCK:"):
			clock_name = token[len("CLOCK:"):]
			continue
		if token.startswith(("ERROR", "WARNING")):
			continue
		try:
			period_ns = float(token)
		except ValueError:
			continue
		if period_ns > 0:
			return clock_name, period_ns
	return clock_name, None


def parse_high_fanout_nets_report(report: str) -> list[tuple[str, int, int]]:
	"""Parse `(net name, fanout, critical path count)` rows from Vivado."""
	nets = []
	in_net_section = False
	for line in report.splitlines():
		if "Paths" in line and "Fanout" in line and "Parent Net Name" in line:
			in_net_section = True
			continue
		if not in_net_section:
			continue
		if line.startswith("==="):
			break
		if line.startswith("---") or not line.strip():
			continue

		parts = line.split()
		if len(parts) < 3:
			continue
		try:
			path_count = int(parts[0])
			fanout = int(parts[1])
		except ValueError:
			continue
		net_name = parts[2]
		if (
			net_name
			and "/" in net_name
			and not net_name.startswith(("get_", "ERROR", "WARNING"))
		):
			nets.append((net_name, fanout, path_count))
	return nets


def parse_spread_analysis(report: str | None) -> dict[str, float | int] | None:
	"""Parse the bounded RapidWright critical-path spread result."""
	if not report:
		return None
	try:
		payload = json.loads(report)
		return {
			"max_distance": float(payload.get("max_distance_found", 0)),
			"avg_distance": float(payload.get("avg_max_distance", 0)),
			"paths_analyzed": int(payload.get("paths_analyzed", 0)),
		}
	except (TypeError, ValueError, json.JSONDecodeError):
		return None


def spread_recommends_pblock(spread: dict[str, float | int] | None) -> bool:
	"""Return whether path spread clears the existing strong PBLOCK threshold."""
	if not spread:
		return False
	return spread["avg_distance"] > 70 and spread["paths_analyzed"] >= 5


def parse_critical_hard_block_types(report: str | None) -> tuple[str, ...]:
	"""Detect hard-block families named on target-clock critical paths."""
	if not report:
		return ()
	try:
		paths = json.loads(report)
	except (TypeError, json.JSONDecodeError):
		return ()

	families = set()
	for path in paths if isinstance(paths, list) else []:
		for cell in path if isinstance(path, list) else []:
			upper_cell = str(cell).upper()
			if "DSP48" in upper_cell or "/DSP" in upper_cell or "_DSP" in upper_cell:
				families.add("DSP")
			if "RAMB" in upper_cell or "BRAM" in upper_cell:
				families.add("BRAM")
			if "URAM" in upper_cell:
				families.add("URAM")
	return tuple(sorted(families))


def parse_congestion_report(report: str | None) -> dict[str, int | bool] | None:
	"""Extract the highest reported Vivado congestion level when available."""
	if not report or report.startswith(("ERROR", "WARNING")):
		return None
	levels = [
		int(match.group(1))
		for line in report.splitlines()
		if (match := re.search(r"congestion[^0-9\n]*([0-9]+)", line, re.IGNORECASE))
	]
	if not levels:
		return None
	max_level = max(levels)
	return {"max_level": max_level, "severe": max_level >= 5}


def parse_timing_anatomy_report(report: str | None) -> dict[str, float | int] | None:
    """Summarize logic-versus-route delay from ordinary Vivado timing text.

    Vivado has changed the surrounding report layout across releases, but the
    ``logic ... route`` parenthetical is stable.  Treat absent fields as
    unavailable instead of guessing from the total path delay.
    """
    if not report:
        return None
    matches = re.findall(
        r"logic\s+[-+]?\d+(?:\.\d+)?\s*ns\s*\(([-+]?\d+(?:\.\d+)?)%\).*?"
        r"route\s+[-+]?\d+(?:\.\d+)?\s*ns\s*\(([-+]?\d+(?:\.\d+)?)%\)",
        report,
        re.IGNORECASE | re.DOTALL,
    )
    if not matches:
        return None
    logic = [float(match[0]) for match in matches]
    route = [float(match[1]) for match in matches]
    return {
        "paths_analyzed": len(matches),
        "avg_logic_delay_pct": sum(logic) / len(logic),
        "avg_route_delay_pct": sum(route) / len(route),
        "route_dominated": (sum(route) / len(route)) >= 55.0,
    }


def parse_critical_hard_block_topology(report: str | None) -> dict[str, int] | None:
    """Measure resource transitions in extracted critical paths.

    This intentionally uses only resource-family names available in the DCP
    path extraction.  It is a conservative proxy for macro-boundary evidence;
    it does not infer dedicated-cascade connectivity that is not present.
    """
    if not report:
        return None
    try:
        paths = json.loads(report)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(paths, list):
        return None

    def family(cell: object) -> str:
        name = str(cell).upper()
        if "URAM" in name:
            return "URAM"
        if "RAMB" in name or "BRAM" in name:
            return "BRAM"
        if "DSP48" in name or "/DSP" in name or "_DSP" in name:
            return "DSP"
        return "LOGIC"

    hard_block_paths = 0
    boundary_transitions = 0
    same_family_hard_adjacencies = 0
    for path in paths:
        if not isinstance(path, list) or not path:
            continue
        families = [family(cell) for cell in path]
        if any(item != "LOGIC" for item in families):
            hard_block_paths += 1
        for left, right in zip(families, families[1:]):
            if left != right and (left != "LOGIC" or right != "LOGIC"):
                boundary_transitions += 1
            if left == right and left != "LOGIC":
                same_family_hard_adjacencies += 1
    return {
        "hard_block_paths": hard_block_paths,
        "boundary_transitions": boundary_transitions,
        "same_family_hard_adjacencies": same_family_hard_adjacencies,
    }


def parse_timing_summary_static(timing_report: str) -> dict:
	"""
	Parse timing summary report to extract WNS, TNS, and failing endpoints.
	Returns dict with keys: wns, tns, failing_endpoints.

	Parses the Design Timing Summary table:
		WNS(ns)      TNS(ns)  TNS Failing Endpoints  ...
		-------      -------  ---------------------  ...
		 -0.099       -1.449                     42  ...
	"""
	result: dict[str, Any] = {
		"wns": None,
		"tns": None,
		"failing_endpoints": None,
	}

	lines = timing_report.split("\n")

	header_idx = -1
	for i, line in enumerate(lines):
		if "WNS(ns)" in line and "TNS(ns)" in line:
			header_idx = i
			break

	if header_idx == -1:
		return result

	data_idx = header_idx + 2
	if data_idx >= len(lines):
		return result

	data_line = lines[data_idx].strip()
	if not data_line:
		return result

	parts = data_line.split()
	if len(parts) >= 3:
		try:
			result["wns"] = float(parts[0])
			result["tns"] = float(parts[1])
			result["failing_endpoints"] = int(parts[2])
		except (ValueError, IndexError):
			pass

	return result
