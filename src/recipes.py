"""Bounded Vivado recipes executed inside the controller's checkpoint transaction.

No recipe publishes, alters timing exceptions, or accepts its own timing.
The controller reroutes, reloads, measures and validates before adoption.
"""

from src.admission import tcl_word


GRANULAR_FLAGS = ("critical_pin_opt", "placement_opt", "routing_opt", "equ_drivers_opt")
NEW_STRATEGIES = ("GRANULAR_PHYS_OPT", "SCOPED_PHYS_OPT", "PARTIAL_REPLACE", "TARGETED_REPLICATION", "RETIME")


def bounded_int(value, default: int, lower: int, upper: int) -> int:
    try:
        return max(lower, min(upper, int(value)))
    except (ValueError, TypeError, OverflowError):
        return default


def normalize_recipe(strategy: str, args: dict) -> dict:
    if strategy == "GRANULAR_PHYS_OPT":
        flag = args.get("flag", "critical_pin_opt")
        return {"flag": flag if flag in GRANULAR_FLAGS else "critical_pin_opt"}
    if strategy == "SCOPED_PHYS_OPT":
        return {"num_paths": bounded_int(args.get("num_paths"), 20, 1, 100)}
    if strategy == "PARTIAL_REPLACE":
        return {"num_paths": bounded_int(args.get("num_paths"), 50, 1, 200),
                "max_cells": bounded_int(args.get("max_cells"), 200, 1, 1000)}
    if strategy == "TARGETED_REPLICATION":
        return {"max_nets": bounded_int(args.get("max_nets"), 3, 1, 5)}
    if strategy == "RETIME":
        directive = args.get("directive", "AddRetime")
        return {"directive": directive if directive in ("AddRetime", "AlternateFlowWithRetiming") else "AddRetime"}
    raise ValueError(f"Unknown recipe: {strategy}")


async def execute_recipe(optimizer, strategy: str, args: dict) -> str:
    args = normalize_recipe(strategy, args)
    clock = "[get_clocks clk_fpl26contest]"
    if strategy == "GRANULAR_PHYS_OPT":
        await optimizer.v("phys_opt_design", {args["flag"]: True})
    elif strategy == "SCOPED_PHYS_OPT":
        # One named, temporary group. Remove it even if physical optimization
        # fails; the exported timing constraints must match the baseline again.
        command = f"""
if {{[llength [get_path_groups -quiet fpl26_scoped_recipe]]}} {{error {{recipe path group already exists}}}}
set paths [get_timing_paths -to {clock} -max_paths {args['num_paths']} -nworst 1]
if {{![llength $paths]}} {{error {{no measured endpoints for scoped optimization}}}}
set endpoints [get_property ENDPOINT_PIN $paths]
group_path -name fpl26_scoped_recipe -to $endpoints
set code [catch {{phys_opt_design -placement_opt -path_groups fpl26_scoped_recipe}} result options]
group_path -default -to $endpoints
if {{$code}} {{return -options $options $result}}
"""
        await optimizer.v("run_tcl", {"command": command, "timeout": 600})
    elif strategy == "PARTIAL_REPLACE":
        # Keep hard macros, fixed cells, clocks, carry chains and I/O in place.
        # Vivado selects the operands; no model-generated Tcl names enter here.
        command = f"""
set paths [get_timing_paths -to {clock} -max_paths {args['num_paths']} -nworst 1]
if {{![llength $paths]}} {{error {{no paths for partial replacement}}}}
set selected {{}}
foreach path $paths {{
    foreach point [get_property POINTS $path] {{
        set pin [get_property PIN $point]
        foreach cell [get_cells -quiet -of_objects $pin] {{
            set ref [get_property REF_NAME $cell]
            if {{([string match LUT* $ref] || [string match FD* $ref]) &&
                ![get_property IS_LOC_FIXED $cell] && ![get_property IS_BEL_FIXED $cell] &&
                ![get_property DONT_TOUCH $cell]}} {{lappend selected $cell}}
        }}
    }}
}}
set selected [lrange [lsort -unique $selected] 0 {args['max_cells'] - 1}]
if {{![llength $selected]}} {{error {{no movable fabric cells on measured paths}}}}
set selected_set [dict create]
foreach cell $selected {{dict set selected_set $cell 1}}
set locks {{}}
set code [catch {{
    foreach cell [get_cells -hier -filter {{IS_PRIMITIVE && IS_PLACED}}] {{
        if {{![dict exists $selected_set $cell]}} {{
            lappend locks [list $cell [get_property IS_LOC_FIXED $cell] [get_property IS_BEL_FIXED $cell]]
            set_property IS_LOC_FIXED true $cell
            set_property IS_BEL_FIXED true $cell
        }}
    }}
    unplace_cell $selected
    place_design -directive Quick
}} result options]
foreach lock $locks {{
    lassign $lock cell loc_fixed bel_fixed
    set_property IS_LOC_FIXED $loc_fixed $cell
    set_property IS_BEL_FIXED $bel_fixed $cell
}}
if {{$code}} {{return -options $options $result}}
"""
        await optimizer.v("run_tcl", {"command": command, "timeout": 900})
    elif strategy == "TARGETED_REPLICATION":
        candidates = optimizer.design_signature.high_fanout_candidates if optimizer.design_signature else ()
        names = [net.net_name for net in sorted(candidates, key=lambda net: (net.critical_path_count, net.fanout), reverse=True)
                 if net.net_name not in optimizer.fanout_blacklist][:args["max_nets"]]
        if not names:
            raise ValueError("No measured critical fanout nets for targeted replication")
        # -regexp with anchored escaped names prevents wildcard bus matching.
        import re
        expressions = " ".join(tcl_word("^" + re.escape(name) + "$") for name in names)
        command = f"""
set nets [get_nets -quiet -hierarchical -regexp [list {expressions}]]
set selected {{}}
foreach net $nets {{
    if {{![get_property IS_CLOCK $net] && ![get_property DONT_TOUCH $net]}} {{lappend selected $net}}
}}
if {{![llength $selected]}} {{error {{no eligible fanout nets remain}}}}
phys_opt_design -force_replication_on_nets $selected
"""
        await optimizer.v("run_tcl", {"command": command, "timeout": 600})
    elif strategy == "RETIME":
        if not optimizer.generation_config.enable_retiming or not optimizer.generation_config.equivalence_command:
            raise ValueError("Retiming requires explicit enablement and a sequential equivalence checker")
        # Retiming is a placed-design optimization. Start from an independent
        # snapshot and remove routing before invoking the documented directive.
        await optimizer.v("run_tcl", {"command": "route_design -unroute", "timeout": 120})
        await optimizer.v("phys_opt_design", {"directive": args["directive"], "timeout": 900})
    await optimizer.v("run_tcl", {"command": "route_design -directive Explore", "timeout": 1200})
    return await optimizer.v("report_timing_summary", {})
