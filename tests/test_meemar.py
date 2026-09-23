"""Offline regressions for the Meemar adaptation; no FPGA tools involved."""

import tempfile
import unittest
from pathlib import Path

from src.meemar import density_regions, needs_rescue, preseed_output
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
