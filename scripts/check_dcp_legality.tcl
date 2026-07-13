set dcp_path [lindex $argv 0]
if {$dcp_path eq ""} {
  error "usage: vivado -mode batch -source task10-final-legality.tcl -tclargs <dcp>"
}

open_checkpoint $dcp_path

set unplaced [get_cells -quiet -filter {IS_PRIMITIVE && LOC == "" && REF_NAME != VCC && REF_NAME != GND}]
set route_report [report_route_status -return_string]
set drc_report [report_drc -return_string]
set error_drcs [get_drc_violations -quiet -filter {SEVERITY == Error}]
set hold_paths [get_timing_paths -quiet -hold -max_paths 1]
set hold_slack "UNAVAILABLE"
if {[llength $hold_paths] > 0} {
  set hold_slack [get_property SLACK [lindex $hold_paths 0]]
}
set pulse_report [report_pulse_width -all_violators -return_string]

puts "FPL26_LEGALITY_UNPLACED=[llength $unplaced]"
puts "FPL26_LEGALITY_UNPLACED_CELLS=[join $unplaced ,]"
puts "FPL26_LEGALITY_ERROR_DRCS=[llength $error_drcs]"
puts "FPL26_LEGALITY_WORST_HOLD_SLACK=$hold_slack"
puts "FPL26_ROUTE_STATUS_BEGIN"
puts $route_report
puts "FPL26_ROUTE_STATUS_END"
puts "FPL26_PULSE_WIDTH_BEGIN"
puts $pulse_report
puts "FPL26_PULSE_WIDTH_END"

if {[llength $unplaced] > 0} {
  error "design contains unplaced primitive cells"
}
if {[llength $error_drcs] > 0} {
  error "design contains error-severity DRC violations"
}
if {$hold_slack ne "UNAVAILABLE" && $hold_slack < 0.0} {
  error "design has negative hold slack"
}

close_design
exit 0
