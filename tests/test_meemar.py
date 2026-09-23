"""Offline regressions for the Meemar adaptation; no FPGA tools involved."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.meemar import CENSUS, density_regions, needs_rescue, preseed_output
from src.policy import EligibleAction, apply_action_cooldowns
from tools.meemar_timeline import command_events


def census(slicem=20):
    return "\n".join(f"MEEMAR_SITE={x},{y},{kind},{cap},{used}"
                     for x in range(2) for y in range(2)
                     for kind, cap, used in (("SLICEL", 100, 5), ("SLICEM", slicem, 3)))


class MeemarTests(unittest.TestCase):
    def test_density_uses_scarce_site_capacity(self):
        small = density_regions(census(20), .5)
        large = density_regions(census(10), .5)
        self.assertNotEqual(small["range"], large["range"])
        self.assertGreaterEqual(large["capacity"]["SLICEM"], 24)

    def test_bram_mode_names_share_compatible_unused_capacity(self):
        report = census() + "\n" + "\n".join(
            f"MEEMAR_SITE={x},{y},{kind},{cap},{used}"
            for x in range(2) for y in range(2)
            for kind, cap, used in (("RAMB36", 1, 1), ("RAMBFIFO36", 9, 0),
                                   ("RAMB180", 1, 1), ("RAMB181", 10, 0),
                                   ("RAMBFIFO18", 9, 0)))
        region = density_regions(report, .5)
        self.assertGreater(region["capacity"]["RAMBFIFO36"], 0)

    def test_bram_halves_and_whole_site_capacity_are_not_double_counted(self):
        report = census() + "\n" + "\n".join(
            f"MEEMAR_SITE={x},{y},{kind},{cap},{used}"
            for x in range(2) for y in range(2)
            for kind, cap, used in (("RAMB36", 10, 10), ("RAMBFIFO18", 20, 0)))
        with self.assertRaisesRegex(ValueError, "resource-feasible"):
            density_regions(report, .5)

    def test_missing_and_infeasible_census_fail_closed(self):
        for report in ("", "MEEMAR_SITE=0,0,SLICEL,10,10", "MEEMAR_SITE=0,0,SLICEL,10,11"):
            with self.subTest(report=report), self.assertRaises(ValueError):
                density_regions(report, .5)

    def test_density_cooldown_keeps_untried_variants(self):
        action = EligibleAction("DENSITY_REIMPLEMENTATION", {"density": .5}, {"density": [.5, .42, .58]})
        result = apply_action_cooldowns([action], [{"strategy": action.strategy, "args": {"density": .5},
                                                   "attempted_from_state": True}])
        self.assertEqual(result[0].default_args, {"density": .42})
        self.assertEqual(result[0].allowed_args["density"], [.42, .58])

    def test_startup_fallback_is_exact_and_unvalidated(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory)/"in.dcp", Path(directory)/"out.dcp"
            source.write_bytes(b"not a validated design")
            evidence = preseed_output(source, target)
            self.assertEqual(source.read_bytes(), target.read_bytes())
            self.assertEqual(evidence["validation"], "unknown")
            with self.assertRaises(ValueError):
                preseed_output(source, source)

    def test_rescue_requires_measured_neutral_cheap_work(self):
        self.assertFalse(needs_rescue([], .001))
        row = {"strategy": "PHYS_OPT", "implementation_passed": True, "delta_wns": 0}
        self.assertTrue(needs_rescue([row], .001))
        self.assertFalse(needs_rescue([row, {**row, "delta_wns": .1}], .001))

    def test_timeline_does_not_guess_from_duration(self):
        self.assertEqual(list(command_events("run_tcl completed after 300.1 seconds")), [])
        event = 'FPL26_COMMAND_EVENT={"command_id":"a","completion":"timeout_pending"}'
        self.assertEqual(list(command_events(event))[0]["completion"], "timeout_pending")


@unittest.skipUnless(shutil.which("tclsh"), "Tcl interpreter required")
class CensusBooleanTests(unittest.TestCase):
    def census_result(self, property_name="DONT_TOUCH", value=""):
        preamble = r'''
proc get_pblocks {args} {return {}}
proc get_sites {args} {return site0}
proc get_cells {args} {return cell0}
set props [dict create CLOCK_REGION X0Y0 SITE_TYPE SLICEL IS_USED 1 IS_LOC_FIXED 0 IS_BEL_FIXED 0 DONT_TOUCH {}]
proc get_property {property object} {global props; return [dict get $props $property]}
'''
        preamble += "dict set props " + property_name + " {" + value + "}\n"
        script = preamble + "if {[catch {\n" + CENSUS + "\n} result]} {puts stderr $result; exit 1}\n"
        return subprocess.run(["tclsh"], input=script, text=True, capture_output=True, timeout=5)

    def test_unset_and_false_properties_allow_movable_cells(self):
        for property_name in ("IS_LOC_FIXED", "IS_BEL_FIXED", "DONT_TOUCH"):
            for value in ("", "0", "false"):
                with self.subTest(property=property_name, value=value):
                    result = self.census_result(property_name, value)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("MEEMAR_TARGETS_HEX=", result.stdout)

    def test_each_protection_property_blocks_moving_cells(self):
        for property_name in ("IS_LOC_FIXED", "IS_BEL_FIXED", "DONT_TOUCH"):
            for value in ("1", "true"):
                with self.subTest(property=property_name, value=value):
                    result = self.census_result(property_name, value)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("cannot move protected fabric cells", result.stderr)

    def test_unexpected_property_values_fail_closed(self):
        result = self.census_result(value="unexpected")
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid boolean property", result.stderr)
