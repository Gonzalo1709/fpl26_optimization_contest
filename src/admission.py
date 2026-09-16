"""Affirmative implementation evidence and artifact identity helpers."""

import hashlib
import math
import re
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tcl_word(value: str) -> str:
    """Quote one literal Tcl word, including bus indices and Windows paths."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace(
        "$", "\\$"
    ).replace("[", "\\[").replace("]", "\\]").replace("\n", "\\n").replace("\r", "\\r") + '"'


def tagged_number(text: str, tag: str) -> float | None:
    matches = re.findall(r"(?m)^\s*" + re.escape(tag) + r"\s*=\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*$", text)
    if not matches:
        return None
    value = float(matches[-1])
    return value if math.isfinite(value) else None


def route_admission(report: str) -> bool | None:
    """Missing counters are unknown, never equivalent to zero errors."""
    def count(label):
        values = re.findall(label + r"[ .\t]*[:=]\s*(\d+)", report, re.I)
        return int(values[-1]) if values else None

    prefix = r"(?:Number|#) of "
    failed = count(prefix + r"(?:Failed Nets|nets with routing errors)")
    counts = [failed] + [count(prefix + label + " Nets") for label in
                        ("Unrouted", "Partially Routed", "Fully Routed", "Routable")]
    if any(value is not None and value > 0 for value in counts[:3]):
        return False
    if any(counts[index] is None for index in (0, 3, 4)):
        return None
    failed, unrouted, partial, routed, routable = counts
    # Full coverage plus zero routing errors is affirmative evidence even on
    # versions that omit the zero-valued unrouted/partial subcategories.
    return failed == 0 and routed == routable and routed > 0


def pulse_admission(summary: str) -> bool | None:
    """Read WPWS and failing endpoints from the full Design Timing Summary.

    Vivado's standard summary has twelve columns: four each for setup, hold,
    and pulse width. Empty/N/A/changed report formats remain unverified.
    """
    lines = summary.splitlines()
    for index, line in enumerate(lines):
        if not all(header in line for header in ("WNS(ns)", "WHS(ns)", "WPWS(ns)")):
            continue
        for row in lines[index + 1:index + 7]:
            columns = row.split()
            if len(columns) != 12:
                continue
            try:
                values = [float(value) for value in columns]
            except ValueError:
                continue
            if not all(math.isfinite(value) for value in values):
                return None
            worst, total, failing, endpoints = values[8:12]
            if failing < 0 or endpoints <= 0 or failing != int(failing) or endpoints != int(endpoints):
                return None
            return worst >= 0 and total >= 0 and failing == 0
    return None


def timing_constraint_digest(xdc: str) -> str | None:
    """Hash exported timing XDC, ignoring only comments and blank lines.

    Order and command arguments remain significant. This deliberately prefers
    rejecting an unexpected export change to normalizing away a real change.
    """
    commands = [line.rstrip() for line in xdc.splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    if not any(re.search(r"\bcreate_(?:generated_)?clock\b", line) for line in commands):
        return None
    return hashlib.sha256("\n".join(commands).encode("utf-8")).hexdigest()
