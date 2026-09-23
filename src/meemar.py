"""Meemar-inspired startup fallback and resource-aware density experiments."""

import json
import math
import re
import shutil
import uuid
from pathlib import Path

from src.admission import sha256_file, tcl_word


DENSITIES = (0.50, 0.42, 0.58)


def needs_rescue(history, min_gain):
    cheap = [r for r in history if r.get("strategy") in
             {"PHYS_OPT", "GRANULAR_PHYS_OPT", "SCOPED_PHYS_OPT", "ROUTE_PRESERVE"}
             and r.get("implementation_passed") is True and isinstance(r.get("delta_wns"), (int, float))]
    return bool(cheap) and not any(r["delta_wns"] > min_gain for r in cheap)


def preseed_output(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output:
        raise ValueError("Output must differ from the input checkpoint")
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = sha256_file(source)
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.wip")
    try:
        shutil.copyfile(source, temporary)
        if sha256_file(temporary) != digest:
            raise ValueError("Startup fallback checksum mismatch")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    evidence = {"kind": "unchanged_input", "snapshot_at_startup": True, "sha256": digest,
                "validation": "unknown", "input": str(source), "output": str(output)}
    manifest = output.with_suffix(output.suffix + ".startup.json")
    temporary = manifest.with_name(f".{manifest.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        temporary.replace(manifest)
    finally:
        temporary.unlink(missing_ok=True)
    return evidence


def density_regions(report, density):
    """Choose the smallest central rectangle with sufficient measured resources.

    Require a complete region grid, per-site-type capacity, and combined BRAM
    capacity. SLICEM is never interchangeable with SLICEL in this conservative fit.
    """
    if density not in DENSITIES:
        raise ValueError("Unsupported density")
    regions, demand = {}, {}
    for x, y, kind, capacity, used in re.findall(
            r"(?m)^MEEMAR_SITE=(\d+),(\d+),([A-Z0-9_]+),(\d+),(\d+)\s*$", report):
        point = (int(x), int(y))
        cap, count = int(capacity), int(used)
        if count > cap or kind in regions.get(point, {}):
            raise ValueError("Invalid or duplicated resource census")
        regions.setdefault(point, {})[kind] = cap
        demand[kind] = demand.get(kind, 0) + count
    if not regions or not any(v for k, v in demand.items() if k.startswith("SLICE")):
        raise ValueError("No occupied SLICE resource evidence")
    xs = sorted({p[0] for p in regions})
    ys = sorted({p[1] for p in regions})
    if len(xs) > 32 or len(ys) > 64:
        raise ValueError("Device exceeds bounded region search")

    def bram_units(counts, capacity=False):
        small = sum(v for k, v in counts.items() if k.startswith(("RAMB18", "FIFO18")))
        large = sum(v * 2 for k, v in counts.items() if k.startswith(("RAMB36", "FIFO36")))
        # RAMB/FIFO aliases can share physical sites: never sum their capacities.
        if capacity:
            groups = [sum(v * (2 if "36" in k else 1) for k, v in counts.items()
                          if k.startswith(prefix)) for prefix in ("RAMB18", "RAMB36", "FIFO18", "FIFO36")]
            return max(groups, default=0)
        return small + large

    choices = []
    for width in range(1, len(xs) + 1):
        for height in range(1, len(ys) + 1):
            # The two central offsets cover even/odd parity without a broad sweep.
            for ix in {(len(xs)-width)//2, (len(xs)-width+1)//2}:
                for iy in {(len(ys)-height)//2, (len(ys)-height+1)//2}:
                    xx, yy = xs[ix:ix+width], ys[iy:iy+height]
                    if xx[-1]-xx[0]+1 != width or yy[-1]-yy[0]+1 != height:
                        continue
                    if any((x, y) not in regions for x in xx for y in yy):
                        continue
                    capacity = {}
                    for x in xx:
                        for y in yy:
                            for kind, count in regions[x, y].items():
                                capacity[kind] = capacity.get(kind, 0) + count
                    if any(capacity.get(k, 0) < math.ceil(v / (density if k.startswith("SLICE") else .8))
                           for k, v in demand.items() if v):
                        continue
                    if bram_units(capacity, True) < math.ceil(bram_units(demand) / .8):
                        continue
                    bounds = (xx[0], yy[0], xx[-1], yy[-1])
                    choices.append(((width*height, width/height, bounds), bounds, capacity))
    if not choices:
        raise ValueError("No central resource-feasible density region")
    _, bounds, capacity = min(choices)
    x0, y0, x1, y1 = bounds
    return {"range": f"CLOCKREGION_X{x0}Y{y0}:CLOCKREGION_X{x1}Y{y1}",
            "density": density, "demand": demand, "capacity": capacity}


CENSUS = r'''
if {[llength [get_pblocks -quiet]]} {error {density search preserves existing pblocks; action skipped}}
set sites [get_sites -filter {SITE_TYPE =~ SLICE* || SITE_TYPE =~ DSP* || SITE_TYPE =~ RAMB* || SITE_TYPE =~ FIFO* || SITE_TYPE =~ URAM*}]
set counts [dict create]
set used [dict create]
foreach s $sites {
    set cr [get_property CLOCK_REGION $s]
    if {![regexp {X([0-9]+)Y([0-9]+)$} $cr -> x y]} {error {resource site has no clock region}}
    set kind [get_property SITE_TYPE $s]
    set key "$x,$y,$kind"
    dict incr counts $key
    if {[get_property IS_USED $s]} {dict incr used $key}
}
foreach key [lsort [dict keys $counts]] {
    set n 0
    if {[dict exists $used $key]} {set n [dict get $used $key]}
    puts "MEEMAR_SITE=$key,[dict get $counts $key],$n"
}
set targets [get_cells -quiet -of_objects $sites]
if {![llength $targets]} {error {density search has no fabric targets}}
foreach cell $targets {
    if {[get_property IS_LOC_FIXED $cell] || [get_property IS_BEL_FIXED $cell] || [get_property DONT_TOUCH $cell]} {
        error {density search cannot move protected fabric cells}
    }
}
puts "MEEMAR_TARGETS_HEX=[binary encode hex [join $targets \n]]"
'''


async def execute_density(optimizer, args):
    density = args.get("density", .5)
    report = await optimizer.v("run_tcl", {"command": CENSUS, "timeout": 120})
    region = density_regions(report, density)
    matches = re.findall(r"(?m)^MEEMAR_TARGETS_HEX=([0-9a-fA-F]+)\s*$", report)
    if not matches:
        raise ValueError("Missing exact density target evidence")
    targets = bytes.fromhex(matches[-1]).decode("utf-8").splitlines()
    seed = optimizer._state_candidate.checkpoint_sha256
    key = (seed, region["range"])
    seen = getattr(optimizer, "_density_regions_seen", set())
    optimizer._density_regions_seen = seen
    if key in seen:
        raise ValueError("Equivalent density region already attempted on this seed")
    seen.add(key)
    optimizer._action_evidence = {"seed_sha256": seed, "strategy": "DENSITY_REIMPLEMENTATION",
                                  **region, "targets": targets, "target_count": len(targets)}
    name = "meemar_" + uuid.uuid4().hex
    command = "set targets [list " + " ".join(tcl_word(n) for n in targets) + "]\n"
    command += f"create_pblock {name}\nresize_pblock {name} -add {tcl_word(region['range'])}\n"
    command += f"add_cells_to_pblock {name} $targets\nunplace_cell $targets\nplace_design\nroute_design\n"
    await optimizer.v("run_tcl", {"command": command, "timeout": 1200})
    return await optimizer.v("report_timing_summary", {})
