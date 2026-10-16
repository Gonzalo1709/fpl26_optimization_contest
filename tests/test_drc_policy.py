import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from src.llm_optimizer import DCPOptimizer
from src.scoring import ValidationStatus


class DRCPolicyTests(unittest.TestCase):
    def test_drc_findings_do_not_block_implementation_when_ignored(self):
        for drc in (False, None, True):
            with self.subTest(drc=drc):
                status = ValidationStatus(
                    par_routed=True, par_drc_clean=drc, drc_ignored=True,
                    hold_passed=True, pulse_width_passed=True,
                )
                self.assertTrue(status.implementation_passed)
                self.assertFalse(status.failed)

    def test_other_failures_still_block_admission(self):
        status = ValidationStatus(
            par_routed=True, drc_ignored=True,
            hold_passed=True, pulse_width_passed=True,
        )
        for field in ('par_routed', 'hold_passed', 'pulse_width_passed'):
            with self.subTest(field=field):
                failed = replace(status, **{field: False})
                self.assertFalse(failed.implementation_passed)
                self.assertTrue(failed.failed)

    def test_skipped_drc_is_not_certified_as_clean(self):
        status = ValidationStatus(
            par_routed=True, drc_ignored=True,
            hold_passed=True, pulse_width_passed=True,
            structural_passed=True, simulation_passed=True,
        )
        self.assertTrue(status.implementation_passed)
        self.assertFalse(status.complete)
        self.assertFalse(status.passed)


class DRCAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_baseline_and_candidate_publish_without_drc_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            optimizer = DCPOptimizer(
                api_key='test-key', run_dir=root, system_prompt='test prompt',
            )
            optimizer._admission_dir = root
            optimizer.output_dcp = root / 'published.dcp'
            optimizer.initial_wns = -1.0
            optimizer.clock_period = 2.0
            optimizer._baseline_constraint_digest = 'constraints'
            optimizer._initial_port_digest = 'ports'
            optimizer._constraint_digest = AsyncMock(return_value='constraints')
            optimizer._port_digest = AsyncMock(return_value='ports')
            optimizer._write_artifact_manifest = Mock()
            optimizer._measure_current_metrics = AsyncMock(side_effect=[
                {'wns': -1.0, 'tns': -1.0, 'failing_endpoints': 1},
                {'wns': -0.5, 'tns': -0.5, 'failing_endpoints': 1},
            ])

            async def save(path):
                path.write_bytes(path.name.encode())

            async def vivado(tool, args):
                if tool == 'open_checkpoint':
                    return 'opened'
                if tool == 'report_route_status':
                    return ('Number of Failed Nets = 0\n'
                            'Number of Fully Routed Nets = 10\n'
                            'Number of Routable Nets = 10')
                command = args['command']
                if 'FPL26_HOLD_WNS' in command:
                    return 'FPL26_HOLD_WNS=0.1'
                if 'report_timing_summary' in command:
                    return ('WNS(ns) WHS(ns) WPWS(ns)\n'
                            '-1 -1 1 10 0.1 0 0 10 0.1 0 0 10')
                raise AssertionError(f'Unexpected command: {command}')

            optimizer._save_best_checkpoint = AsyncMock(side_effect=save)
            optimizer.v = AsyncMock(side_effect=vivado)
            baseline = await optimizer._snapshot_candidate('baseline')
            self.assertTrue(optimizer._publish_admitted(baseline))
            improved = await optimizer._snapshot_candidate('improved', baseline)
            self.assertTrue(optimizer._publish_admitted(improved))
            self.assertEqual(optimizer.output_dcp.read_bytes(), improved.dcp_path.read_bytes())
            self.assertTrue(improved.validation.drc_ignored)
            self.assertIsNone(improved.validation.par_drc_clean)


if __name__ == '__main__':
    unittest.main()
