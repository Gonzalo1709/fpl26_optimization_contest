"""Data-only recipe extensions and strict manual-plan argument contracts."""

import json
import math
import re
from pathlib import Path


def integer(default, low, high):
    return {"type": "integer", "default": default, "minimum": low, "maximum": high}


def choice(default, *values):
    return {"type": "choice", "default": default, "choices": list(values)}


# These bounds mirror the controller's supported strategies. Recipe files may
# compose these operations, but cannot add executable code or relax contracts.
PARAMETERS = {
    "PHYS_OPT": {"directive": choice("RuntimeOptimized", "RuntimeOptimized", "CriticalPin", "PlacementRouting", "Default", "Explore", "AggressiveExplore")},
    "PHYS_OPT_REROUTE": {"directive": choice("RuntimeOptimized", "RuntimeOptimized", "Default", "Explore", "AggressiveExplore")},
    "FANOUT": {"top_n_nets": integer(5, 1, 10)},
    "PBLOCK": {},
    "CELL_RELOCATE": {"num_paths": integer(10, 3, 20), "detour_threshold": {"type": "number", "default": 2.0, "minimum": 1.2, "maximum": 4.0},
                      "max_cells": integer(3, 1, 5), "max_move_distance": integer(30, 5, 80)},
    "HARD_BLOCK": {"hard_block_types": {"type": "multi_choice", "default": ["DSP", "BRAM", "URAM"], "choices": ["DSP", "BRAM", "URAM"]}},
    "PLACEMENT_SHOT": {"directive": choice("ExtraNetDelay_low", "ExtraNetDelay_low", "AltSpreadLogic_medium", "WLDrivenBlockPlacement", "ExtraTimingOpt", "EarlyBlockPlacement")},
    "FULL_PLACE_ROUTE": {},
    "CRITICAL_PIN": {},
    "ROUTE_PRESERVE": {"max_nets": integer(4, 1, 8), "min_net_delay_ns": {"type": "number", "default": 0.2, "minimum": 0.05, "maximum": 2.0}},
    "GRANULAR_PHYS_OPT": {"flag": choice("critical_pin_opt", "critical_pin_opt", "placement_opt", "routing_opt", "equ_drivers_opt")},
    "SCOPED_PHYS_OPT": {"num_paths": integer(20, 1, 100)},
    "PARTIAL_REPLACE": {"num_paths": integer(50, 1, 200), "max_cells": integer(200, 1, 1000)},
    "TARGETED_REPLICATION": {"max_nets": integer(3, 1, 5)},
    "RETIME": {"directive": choice("AddRetime", "AddRetime", "AlternateFlowWithRetiming")},
}


def validate_plan(plan):
    if not isinstance(plan, list) or not 1 <= len(plan) <= 32:
        raise ValueError("Choose between 1 and 32 manual steps")
    normalized = []
    for step in plan:
        if not isinstance(step, dict) or set(step) - {"strategy", "args"}:
            raise ValueError("Each step must contain only strategy and args")
        strategy = step.get("strategy")
        if not isinstance(strategy, str) or strategy not in PARAMETERS:
            raise ValueError(f"Unsupported manual strategy: {strategy}")
        schema, supplied = PARAMETERS[strategy], step.get("args", {})
        if not isinstance(supplied, dict) or set(supplied) - schema.keys():
            raise ValueError(f"Unknown arguments for {strategy}")
        args = {}
        for name, spec in schema.items():
            value = supplied.get(name, spec["default"])
            kind = spec["type"]
            if kind in {"integer", "number"}:
                valid = type(value) in ((int,) if kind == "integer" else (int, float))
                valid = valid and spec["minimum"] <= value <= spec["maximum"] and math.isfinite(value)
            elif kind == "multi_choice":
                valid = isinstance(value, list) and bool(value) and all(isinstance(v, str) and v in spec["choices"] for v in value)
            else:
                valid = isinstance(value, str) and value in spec["choices"]
            if not valid:
                raise ValueError(f"Invalid {strategy}.{name}: {value!r}")
            args[name] = value
        normalized.append({"strategy": strategy, "args": args})
    return normalized


def load_catalog(folder: Path):
    recipes, errors, ids = [], [], set()
    for path in sorted(folder.glob("*.json")):
        try:
            if path.is_symlink() or path.stat().st_size > 64 * 1024:
                raise ValueError("Recipe must be a regular JSON file under 64 KiB")
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or set(value) - {"schema_version", "id", "name", "description", "steps"}:
                raise ValueError("Unknown recipe fields")
            identity = value.get("id", "")
            if value.get("schema_version") != 1 or not isinstance(identity, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", identity):
                raise ValueError("Expected schema_version 1 and a stable lowercase id")
            if identity in ids:
                raise ValueError(f"Duplicate recipe id: {identity}")
            if not isinstance(value.get("name"), str) or not 1 <= len(value["name"]) <= 100:
                raise ValueError("Recipe name must contain 1 to 100 characters")
            if not isinstance(value.get("description", ""), str):
                raise ValueError("Recipe description must be text")
            steps = validate_plan(value.get("steps"))
            recipes.append(value | {"steps": steps, "file": path.name})
            ids.add(identity)
        except (ValueError, TypeError, OSError) as exc:
            errors.append({"file": path.name, "error": str(exc)})
    return {"recipes": recipes, "errors": errors, "parameters": PARAMETERS}
