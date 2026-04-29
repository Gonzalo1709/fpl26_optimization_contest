"""Pure parsing and file-loading helpers for the FPGA optimizer."""

from pathlib import Path
from typing import Any


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


def load_system_prompt() -> str:
	"""Load system prompt from SYSTEM_PROMPT.TXT file."""
	prompt_file = Path(__file__).resolve().parent.parent / "SYSTEM_PROMPT.TXT"

	try:
		return prompt_file.read_text()
	except FileNotFoundError:
		raise FileNotFoundError(f"System prompt file not found: {prompt_file}")
