"""Current-checkpoint target extraction and bounded physical edits.

Operands are selected in Vivado immediately before mutation, never from LLM text.
"""

import re


PACT_STRATEGIES = ("CRITICAL_NET_REROUTE", "CRITICAL_BRANCH_REROUTE", "PATH_LOCAL_REPLACE", "PATH_CLUSTER_REPLACE")


def normalize_action(strategy, args):
    limits = {"CRITICAL_NET_REROUTE": ("max_nets", 4, 8),
              "CRITICAL_BRANCH_REROUTE": ("max_pins", 4, 8),
              "PATH_LOCAL_REPLACE": ("max_cells", 20, 50),
              "PATH_CLUSTER_REPLACE": ("max_cells", 80, 160)}
    key, default, maximum = limits[strategy]
    try:
        count = int(args.get(key, default))
    except (ValueError, TypeError, OverflowError):
        count = default
    return {key: min(maximum, max(1, count))}


async def execute_action(optimizer, strategy, args):
    args = normalize_action(strategy, args)
    # The controller has restored and hash-checked the seed before this call.
    selection = """
set paths [get_timing_paths -quiet -to [get_clocks clk_fpl26contest] -max_paths 50 -nworst 1]
if {![llength $paths]} {error {no current-seed critical paths}}
set pins {}
foreach p $paths {
    foreach prop {STARTPOINT_PIN ENDPOINT_PIN} {
        set pin [get_pins -quiet [get_property $prop $p]]
        if {[llength $pin]} {lappend pins {*}$pin}
    }
}
"""
    if strategy == "CRITICAL_NET_REROUTE":
        body = r"""
set selected {}
foreach net [lsort -unique [get_nets -quiet -of_objects $pins]] {
    if {![get_property IS_CLOCK $net] && ![get_property DONT_TOUCH $net] && ![get_property IS_ROUTE_FIXED $net]} {lappend selected $net}
}
set selected [lrange $selected 0 LIMIT]
if {![llength $selected]} {error {no eligible critical terminal nets}}
puts "PACT_TARGETS_HEX=[binary encode hex [join $selected \n]]"
route_design -unroute -nets $selected
route_design -delay -nets $selected
route_design -preserve
""".replace("LIMIT", str(args["max_nets"]-1))
        timeout = 360
    elif strategy == "CRITICAL_BRANCH_REROUTE":
        body = r"""
set selected {}
foreach p $paths {
    foreach pin [get_pins -quiet [get_property ENDPOINT_PIN $p]] {
        set nets [get_nets -quiet -of_objects $pin]
        if {[get_property DIRECTION $pin] ne "IN" || [llength $nets] != 1} {continue}
        set net [lindex $nets 0]
        if {![get_property IS_CLOCK $net] && ![get_property DONT_TOUCH $net] && ![get_property IS_ROUTE_FIXED $net]} {
            if {[lsearch -exact $selected $pin] < 0} {lappend selected $pin}
        }
    }
}
set selected [lrange $selected 0 LIMIT]
if {![llength $selected]} {error {no eligible critical sink branches}}
puts "PACT_TARGETS_HEX=[binary encode hex [join $selected \n]]"
route_design -unroute -pins $selected
route_design -delay -pins $selected
route_design -preserve
""".replace("LIMIT", str(args["max_pins"]-1))
        timeout = 360
    else:
        body = r"""
set selected {}
foreach cell [lsort -unique [get_cells -quiet -of_objects $pins]] {
    set ref [get_property REF_NAME $cell]
    if {([string match LUT* $ref] || [string match FD* $ref]) &&
        ![get_property IS_LOC_FIXED $cell] && ![get_property IS_BEL_FIXED $cell] &&
        ![get_property DONT_TOUCH $cell]} {lappend selected $cell}
}
set selected [lrange $selected 0 LIMIT]
if {![llength $selected]} {error {no movable critical terminal cells}}
puts "PACT_TARGETS_HEX=[binary encode hex [join $selected \n]]"
set selected_set [dict create]
foreach cell $selected {dict set selected_set $cell 1}
set locks {}
set code [catch {
    foreach cell [get_cells -hier -filter {IS_PRIMITIVE && IS_PLACED}] {
        if {![dict exists $selected_set $cell]} {
            lappend locks [list $cell [get_property IS_LOC_FIXED $cell] [get_property IS_BEL_FIXED $cell]]
            set_property IS_LOC_FIXED true $cell
            set_property IS_BEL_FIXED true $cell
        }
    }
    unplace_cell $selected
    place_design -directive Quick
} result options]
foreach lock $locks {
    lassign $lock cell loc_fixed bel_fixed
    set_property IS_LOC_FIXED $loc_fixed $cell
    set_property IS_BEL_FIXED $bel_fixed $cell
}
if {$code} {return -options $options $result}
route_design -directive Explore
""".replace("LIMIT", str(args["max_cells"]-1))
        timeout = 900
        if strategy == "PATH_CLUSTER_REPLACE":
            # Vivado supports cell extraction directly from timing-path objects;
            # keep the same LUT/FD exclusions and lock-restoration transaction.
            body = body.replace("get_cells -quiet -of_objects $pins", "get_cells -quiet -of_objects $paths")
    marker = 'puts "PACT_TARGETS_HEX=[binary encode hex [join $selected \\n]]"'
    select_body, separator, mutation = body.partition(marker)
    if not separator:
        raise ValueError("Targeted recipe lacks its operand certificate boundary")
    result = await optimizer.v("run_tcl", {"command": selection + select_body + marker, "timeout": 60})
    matches = re.findall(r"(?m)^PACT_TARGETS_HEX=([0-9a-fA-F]+)\s*$", result)
    if not matches:
        raise ValueError("Targeted action produced no operand evidence")
    operands = bytes.fromhex(matches[-1]).decode("utf-8").splitlines()
    optimizer._action_evidence = {"seed_sha256": optimizer._state_candidate.checkpoint_sha256,
                                  "strategy": strategy, "args": args,
                                  "selection": ("current target-clock datapath cells" if strategy == "PATH_CLUSTER_REPLACE"
                                                else "current target-clock path terminals"),
                                  "targets": operands, "target_count": len(operands)}
    # Freeze exact operands, not patterns. Do not depend on persistent Tcl locals
    # across MCP calls, and record evidence before any mutation can fail.
    from src.admission import tcl_word
    command = "set selected [list " + " ".join(tcl_word(n) for n in operands) + "]\n" + mutation
    await optimizer.v("run_tcl", {"command": command, "timeout": timeout})
    return await optimizer.v("report_timing_summary", {})
