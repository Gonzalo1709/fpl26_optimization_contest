"""Deterministic test modes for the FPGA optimizer."""

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from src.base import DCPOptimizerBase
from src.parsers import parse_timing_summary_static

logger = logging.getLogger(__name__)


class FPGAOptimizerTest(DCPOptimizerBase):
    """Test mode for FPGA Design Optimization without LLM."""

    def __init__(self, debug: bool = False, run_dir: Optional[Path] = None):
        super().__init__(debug=debug, run_dir=run_dir)
        self.final_wns = None

    async def start_servers(self, log_prefix: str = ""):
        await super().start_servers(log_prefix=log_prefix or "[TEST]")

    async def call_vivado_tool(self, tool_name: str, arguments: dict, timeout: float = 300.0) -> str:
        logger.info(f"[VIVADO] Calling {tool_name} with args: {json.dumps(arguments)[:200]}...")
        print(f"[TEST] Calling vivado_{tool_name}...")
        start_time = time.time()

        try:
            result = await asyncio.wait_for(self.vivado_session.call_tool(tool_name, arguments), timeout=timeout)
            elapsed = time.time() - start_time
            logger.info(f"[VIVADO] {tool_name} completed in {elapsed:.2f}s")
            print(f"[TEST] vivado_{tool_name} completed in {elapsed:.2f}s")
            if result.content:
                text_parts = [c.text for c in result.content if hasattr(c, "text")]
                return "\n".join(text_parts)
            return "(no output)"
        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            logger.error(f"[VIVADO] {tool_name} TIMED OUT after {elapsed:.2f}s")
            print(f"[TEST] ERROR: vivado_{tool_name} TIMED OUT after {elapsed:.2f}s")
            raise
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"[VIVADO] {tool_name} FAILED after {elapsed:.2f}s: {e}")
            print(f"[TEST] ERROR: vivado_{tool_name} failed after {elapsed:.2f}s: {e}")
            raise

    async def call_rapidwright_tool(self, tool_name: str, arguments: dict, timeout: float = 300.0) -> str:
        logger.info(f"[RAPIDWRIGHT] Calling {tool_name} with args: {json.dumps(arguments)[:200]}...")
        print(f"[TEST] Calling rapidwright_{tool_name}...")
        start_time = time.time()

        try:
            result = await asyncio.wait_for(self.rapidwright_session.call_tool(tool_name, arguments), timeout=timeout)
            elapsed = time.time() - start_time
            logger.info(f"[RAPIDWRIGHT] {tool_name} completed in {elapsed:.2f}s")
            print(f"[TEST] rapidwright_{tool_name} completed in {elapsed:.2f}s")
            if result.content:
                text_parts = [c.text for c in result.content if hasattr(c, "text")]
                return "\n".join(text_parts)
            return "(no output)"
        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            logger.error(f"[RAPIDWRIGHT] {tool_name} TIMED OUT after {elapsed:.2f}s")
            print(f"[TEST] ERROR: rapidwright_{tool_name} TIMED OUT after {elapsed:.2f}s")
            raise
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"[RAPIDWRIGHT] {tool_name} FAILED after {elapsed:.2f}s: {e}")
            print(f"[TEST] ERROR: rapidwright_{tool_name} failed after {elapsed:.2f}s: {e}")
            raise

    def parse_wns_from_timing_report(self, timing_report: str) -> Optional[float]:
        return parse_timing_summary_static(timing_report)["wns"]

    async def _call_vivado_for_clock(self, tool_name: str, arguments: dict) -> str:
        return await self.call_vivado_tool(tool_name, arguments, timeout=60.0)

    async def fetch_clock_period(self) -> Optional[float]:
        period = await super().get_clock_period(self._call_vivado_for_clock)
        if period is not None:
            clock_info = f" (target clock: {self.target_clock})" if self.target_clock else ""
            print(f"[TEST] Clock period: {period:.3f} ns{clock_info}")
        else:
            print("[TEST] WARNING: Could not parse clock period from Vivado")
        return period

    async def run_test(self, input_dcp: Path, output_dcp: Path, max_nets_to_optimize: int = 5) -> bool:
        print("\n" + "=" * 70)
        print("FPGA OPTIMIZER TEST MODE")
        print("=" * 70)
        print(f"Input DCP:  {input_dcp}")
        print(f"Output DCP: {output_dcp}")
        print(f"Temp dir:   {self.temp_dir}")
        print(f"Max nets to optimize: {max_nets_to_optimize}")
        print("=" * 70 + "\n")

        overall_start = time.time()

        try:
            print("\n" + "-" * 60)
            print("STEP 0: Initialize RapidWright")
            print("-" * 60)
            result = await self.call_rapidwright_tool("initialize_rapidwright", {"jvm_max_memory": "8G"}, timeout=120.0)
            print(f"RapidWright init result:\n{result[:500]}...")
            logger.info(f"RapidWright init result: {result}")

            print("\n" + "-" * 60)
            print("STEP 1: Open input DCP in Vivado")
            print("-" * 60)
            result = await self.call_vivado_tool("open_checkpoint", {"dcp_path": str(input_dcp.resolve())}, timeout=600.0)
            print(f"Open checkpoint result:\n{result}")
            logger.info(f"Open checkpoint result: {result}")

            print("\n" + "-" * 60)
            print("STEP 2: Report timing in Vivado")
            print("-" * 60)
            result = await self.call_vivado_tool("report_timing_summary", {}, timeout=300.0)
            print(f"Timing summary (first 2000 chars):\n{result[:2000]}...")
            logger.info(f"Initial timing summary: {result}")

            self.clock_period = await self.fetch_clock_period()
            target_wns = await self.get_wns_for_target_clock(self._call_vivado_for_clock)
            self.initial_wns = target_wns if target_wns is not None else self.parse_wns_from_timing_report(result)

            self.print_fmax_status("Initial", self.initial_wns)
            logger.info(f"Initial WNS: {self.initial_wns} ns")
            print()

            print("\n" + "-" * 60)
            print("STEP 3: Get critical high fanout nets")
            print("-" * 60)
            result = await self.call_vivado_tool("get_critical_high_fanout_nets", {
                "num_paths": 50,
                "min_fanout": 100,
                "exclude_clocks": True,
            }, timeout=600.0)
            print(f"High fanout nets report:\n{result}")
            logger.info(f"High fanout nets: {result}")

            self.high_fanout_nets = self.parse_high_fanout_nets(result)
            print(f"\nParsed {len(self.high_fanout_nets)} high fanout nets")
            if not self.high_fanout_nets:
                print("WARNING: No high fanout nets found to optimize!")
                logger.warning("No high fanout nets found to optimize")

            nets_to_optimize = self.high_fanout_nets[:max_nets_to_optimize]
            print(f"Will optimize {len(nets_to_optimize)} nets:")
            for net_name, fanout, path_count in nets_to_optimize:
                print(f"  - {net_name} (fanout={fanout}, paths={path_count})")

            print("\n" + "-" * 60)
            print("STEP 4: Open DCP in RapidWright")
            print("-" * 60)
            result = await self.call_rapidwright_tool("read_checkpoint", {"dcp_path": str(input_dcp.resolve())}, timeout=600.0)
            print(f"RapidWright read checkpoint result:\n{result}")
            logger.info(f"RapidWright read checkpoint: {result}")

            print("\n" + "-" * 60)
            print("STEP 5: Apply fanout optimizations in RapidWright")
            print("-" * 60)
            successful_optimizations = 0
            for i, (net_name, fanout, path_count) in enumerate(nets_to_optimize):
                print(f"\n[{i+1}/{len(nets_to_optimize)}] Optimizing net: {net_name}")
                print(f"    Fanout: {fanout}, Critical paths: {path_count}")
                split_factor = max(2, min(8, fanout // 100))
                print(f"    Split factor: {split_factor}")
                try:
                    result = await self.call_rapidwright_tool("optimize_fanout", {
                        "net_name": net_name,
                        "split_factor": split_factor,
                    }, timeout=300.0)
                    print(f"    Result: {result[:500]}...")
                    logger.info(f"Optimize fanout {net_name}: {result}")
                    if "error" not in result.lower() or "success" in result.lower():
                        successful_optimizations += 1
                except Exception as e:
                    print(f"    FAILED: {e}")
                    logger.error(f"Failed to optimize {net_name}: {e}")

            print(f"\nSuccessfully optimized {successful_optimizations}/{len(nets_to_optimize)} nets")

            print("\n" + "-" * 60)
            print("STEP 6: Write DCP from RapidWright")
            print("-" * 60)
            rapidwright_dcp = Path(self.temp_dir) / "rapidwright_optimized.dcp"
            result = await self.call_rapidwright_tool("write_checkpoint", {
                "dcp_path": str(rapidwright_dcp),
                "overwrite": True,
            }, timeout=600.0)
            print(f"Write checkpoint result:\n{result}")
            logger.info(f"RapidWright write checkpoint: {result}")

            if rapidwright_dcp.exists():
                print(f"DCP file created: {rapidwright_dcp} ({rapidwright_dcp.stat().st_size} bytes)")
            else:
                print("WARNING: DCP file was not created!")
                logger.warning("RapidWright DCP file not created")

            print("\n" + "-" * 60)
            print("STEP 7: Read RapidWright DCP into Vivado")
            print("-" * 60)
            rapidwright_dcp_timeout = 300.0
            tcl_script = rapidwright_dcp.with_suffix('.tcl')
            if tcl_script.exists():
                print(f"Found Tcl script for encrypted IP: {tcl_script}")
                print("Note: This may take 10-30 minutes for large designs...")
                result = await self.call_vivado_tool("run_tcl", {"command": f"source {{{tcl_script}}}"}, timeout=rapidwright_dcp_timeout)
                print(f"Source Tcl script result:\n{result}")
            else:
                result = await self.call_vivado_tool("open_checkpoint", {"dcp_path": str(rapidwright_dcp)}, timeout=rapidwright_dcp_timeout)
                print(f"Open RapidWright DCP result:\n{result}")
            logger.info(f"Open RapidWright DCP: {result}")

            print("\n" + "-" * 60)
            print("STEP 8: Route design in Vivado")
            print("-" * 60)
            result = await self.call_vivado_tool("report_route_status", {
                "show_unrouted": True,
                "show_errors": True,
                "max_nets": 20,
            }, timeout=300.0)
            print(f"Route status before routing:\n{result[:1500]}...")
            logger.info(f"Route status before routing: {result}")

            result = await self.call_vivado_tool("route_design", {"directive": "Default"}, timeout=600.0)
            print(f"Route design result:\n{result}")
            logger.info(f"Route design: {result}")

            result = await self.call_vivado_tool("report_route_status", {
                "show_unrouted": True,
                "show_errors": True,
                "max_nets": 20,
            }, timeout=300.0)
            print(f"Route status after routing:\n{result[:1500]}...")
            logger.info(f"Route status after routing: {result}")

            print("\n" + "-" * 60)
            print("STEP 9: Report final timing")
            print("-" * 60)
            result = await self.call_vivado_tool("report_timing_summary", {}, timeout=300.0)
            print(f"Final timing summary (first 2000 chars):\n{result[:2000]}...")
            logger.info(f"Final timing summary: {result}")

            target_wns = await self.get_wns_for_target_clock(self._call_vivado_for_clock)
            self.final_wns = target_wns if target_wns is not None else self.parse_wns_from_timing_report(result)

            self.print_fmax_status("Final", self.final_wns)
            logger.info(f"Final WNS: {self.final_wns} ns")
            print()

            self.print_wns_change(self.initial_wns, self.final_wns, self.clock_period)

            print(f"\nWriting final DCP to: {output_dcp}")
            result = await self.call_vivado_tool("write_checkpoint", {
                "dcp_path": str(output_dcp.resolve()),
                "force": True,
            }, timeout=600.0)
            print(f"Write final DCP result:\n{result}")

            elapsed = time.time() - overall_start
            self.print_test_summary(
                title="TEST SUMMARY",
                elapsed_seconds=elapsed,
                initial_wns=self.initial_wns,
                final_wns=self.final_wns,
                clock_period=self.clock_period,
                extra_info=f"Nets optimized: {successful_optimizations}/{len(nets_to_optimize)}",
            )
            return True

        except Exception as e:
            logger.exception(f"Test failed with exception: {e}")
            print(f"\n*** TEST FAILED ***")
            print(f"Exception: {type(e).__name__}: {e}")
            return False

    async def run_test_logicnets(self, input_dcp: Path, output_dcp: Path) -> bool:
        pblock_ranges = "SLICE_X55Y60:SLICE_X111Y254"

        print("\n" + "=" * 70)
        print("FPGA OPTIMIZER TEST MODE - LOGICNETS PBLOCK FLOW")
        print("=" * 70)
        print(f"Input DCP:  {input_dcp}")
        print(f"Output DCP: {output_dcp}")
        print(f"Temp dir:   {self.temp_dir}")
        print("=" * 70 + "\n")

        overall_start = time.time()

        try:
            print("\n" + "-" * 60)
            print("STEP 0: Initialize RapidWright")
            print("-" * 60)
            result = await self.call_rapidwright_tool("initialize_rapidwright", {"jvm_max_memory": "8G"}, timeout=120.0)
            print(f"RapidWright init result:\n{result[:500]}...")
            logger.info(f"RapidWright init result: {result}")

            print("\n" + "-" * 60)
            print("STEP 1: Open input DCP in Vivado")
            print("-" * 60)
            result = await self.call_vivado_tool("open_checkpoint", {"dcp_path": str(input_dcp.resolve())}, timeout=600.0)
            print(f"Open checkpoint result:\n{result}")
            logger.info(f"Open checkpoint result: {result}")

            print("\n" + "-" * 60)
            print("STEP 2: Report initial timing in Vivado")
            print("-" * 60)
            result = await self.call_vivado_tool("report_timing_summary", {}, timeout=300.0)
            print(f"Timing summary (first 2000 chars):\n{result[:2000]}...")
            logger.info(f"Initial timing summary: {result}")

            self.clock_period = await self.fetch_clock_period()
            target_wns = await self.get_wns_for_target_clock(self._call_vivado_for_clock)
            self.initial_wns = target_wns if target_wns is not None else self.parse_wns_from_timing_report(result)

            self.print_fmax_status("Initial", self.initial_wns)
            logger.info(f"Initial WNS: {self.initial_wns} ns")
            print()

            print("\n" + "-" * 60)
            print("STEP 3: Extract critical path cells")
            print("-" * 60)
            critical_paths_file = Path(self.temp_dir) / "critical_paths.json"
            result = await self.call_vivado_tool("extract_critical_path_cells", {
                "num_paths": 50,
                "output_file": str(critical_paths_file),
            }, timeout=600.0)
            print(f"Extract critical paths result:\n{result[:2000]}...")
            logger.info(f"Extract critical paths: {result}")

            print("\n" + "-" * 60)
            print("STEP 4: Analyze critical path spread in RapidWright")
            print("-" * 60)
            result = await self.call_rapidwright_tool("read_checkpoint", {"dcp_path": str(input_dcp.resolve())}, timeout=600.0)
            print(f"RapidWright read checkpoint result:\n{result}")
            logger.info(f"RapidWright read checkpoint: {result}")

            result = await self.call_rapidwright_tool("analyze_critical_path_spread", {"input_file": str(critical_paths_file)}, timeout=300.0)
            print(f"Critical path spread analysis:\n{result[:3000] if isinstance(result, str) else str(result)[:3000]}...")
            logger.info(f"Critical path spread: {result}")

            spread_result = result if isinstance(result, str) else str(result)
            pblock_recommended = "spread-out" in spread_result.lower() or "pblock" in spread_result.lower()
            print(f"\n*** Pblock optimization {'RECOMMENDED' if pblock_recommended else 'may not be needed'} ***")

            print("\n" + "-" * 60)
            print("STEP 5: Apply pblock for LogicNets")
            print("-" * 60)
            print(f"Using pblock range: {pblock_ranges}")

            print("\n" + "-" * 60)
            print("STEP 6: Unplace the design in Vivado")
            print("-" * 60)
            result = await self.call_vivado_tool("run_tcl", {"command": "place_design -unplace"}, timeout=300.0)
            print(f"Unplace result:\n{result}")
            logger.info(f"Unplace result: {result}")

            print("\n" + "-" * 60)
            print("STEP 7: Create and apply pblock to entire design")
            print("-" * 60)
            result = await self.call_vivado_tool("create_and_apply_pblock", {
                "pblock_name": "pblock_opt",
                "ranges": pblock_ranges,
                "apply_to": "current_design",
                "is_soft": False,
            }, timeout=300.0)
            print(f"Create and apply pblock result:\n{result}")
            logger.info(f"Create pblock result: {result}")

            print("\n" + "-" * 60)
            print("STEP 8: Place the design in Vivado")
            print("-" * 60)
            result = await self.call_vivado_tool("place_design", {"directive": "Default"}, timeout=3600.0)
            print(f"Place design result:\n{result}")
            logger.info(f"Place design: {result}")

            print("\n" + "-" * 60)
            print("STEP 9: Route the design in Vivado")
            print("-" * 60)
            result = await self.call_vivado_tool("route_design", {"directive": "Default"}, timeout=3600.0)
            print(f"Route design result:\n{result}")
            logger.info(f"Route design: {result}")

            result = await self.call_vivado_tool("report_route_status", {}, timeout=300.0)
            print(f"Route status after routing:\n{result[:1500]}...")
            logger.info(f"Route status after routing: {result}")

            print("\n" + "-" * 60)
            print("STEP 10: Report final timing")
            print("-" * 60)
            result = await self.call_vivado_tool("report_timing_summary", {}, timeout=300.0)
            print(f"Final timing summary (first 2000 chars):\n{result[:2000]}...")
            logger.info(f"Final timing summary: {result}")

            target_wns = await self.get_wns_for_target_clock(self._call_vivado_for_clock)
            self.final_wns = target_wns if target_wns is not None else self.parse_wns_from_timing_report(result)

            self.print_fmax_status("Final", self.final_wns)
            logger.info(f"Final WNS: {self.final_wns} ns")
            print()

            self.print_wns_change(self.initial_wns, self.final_wns, self.clock_period)
            print(f"\nWriting final DCP to: {output_dcp}")
            result = await self.call_vivado_tool("write_checkpoint", {
                "dcp_path": str(output_dcp.resolve()),
                "force": True,
            }, timeout=600.0)
            print(f"Write final DCP result:\n{result}")

            elapsed = time.time() - overall_start
            self.print_test_summary(
                title="TEST SUMMARY - LOGICNETS PBLOCK OPTIMIZATION",
                elapsed_seconds=elapsed,
                initial_wns=self.initial_wns,
                final_wns=self.final_wns,
                clock_period=self.clock_period,
                extra_info=f"Pblock applied: {pblock_ranges}",
            )
            return True
        except Exception as e:
            logger.exception(f"LogicNets test failed with exception: {e}")
            print(f"\n*** TEST FAILED ***")
            print(f"Exception: {type(e).__name__}: {e}")
            return False

    async def run_test_vexriscv(self, input_dcp: Path, output_dcp: Path) -> bool:
        overall_start = time.time()

        try:
            print("=" * 60)
            print("Step 1  Vivado baseline")
            print("=" * 60)

            result = await self.call_vivado_tool("open_checkpoint", {"dcp_path": str(input_dcp.resolve())}, timeout=600.0)
            logger.info(f"Open checkpoint result: {result}")

            self.clock_period = await self.fetch_clock_period()
            target_wns = await self.get_wns_for_target_clock(self._call_vivado_for_clock)
            if target_wns is not None:
                self.initial_wns = target_wns
            else:
                ts = await self.call_vivado_tool("report_timing_summary", {}, timeout=300.0)
                self.initial_wns = self.parse_wns_from_timing_report(ts)

            baseline_fmax = self.calculate_fmax(self.initial_wns, self.clock_period)
            print(f"  Clock period:   {self.clock_period} ns")
            print(f"  Baseline WNS:   {self.initial_wns} ns")
            if baseline_fmax is not None:
                print(f"  Baseline Fmax:  {baseline_fmax:.2f} MHz")

            pins_file = Path(self.temp_dir) / "critical_path_pins.json"
            result = await self.call_vivado_tool("extract_critical_path_pins", {
                "num_paths": 10,
                "output_file": str(pins_file),
            }, timeout=600.0)

            critical_paths = json.loads(Path(pins_file).read_text()) if pins_file.exists() else json.loads(result)
            print(f"  Extracted {len(critical_paths)} critical path pin lists")

            print("\n" + "=" * 60)
            print("Step 2  RapidWright analysis")
            print("=" * 60)

            result = await self.call_rapidwright_tool("initialize_rapidwright", {"jvm_max_memory": "8G"}, timeout=120.0)
            logger.info(f"RapidWright init: {result}")

            result = await self.call_rapidwright_tool("read_checkpoint", {"dcp_path": str(input_dcp.resolve())}, timeout=600.0)
            logger.info(f"RapidWright read checkpoint: {result}")

            result = await self.call_rapidwright_tool("analyze_net_detour", {
                "input_file": str(pins_file),
                "detour_threshold": 2.0,
            }, timeout=300.0)
            logger.info(f"analyze_net_detour: {result}")

            analysis = json.loads(result) if isinstance(result, str) else result
            if "error" in analysis:
                raise RuntimeError(f"analyze_net_detour failed: {analysis['error']}")
            candidates = analysis.get("candidates", [])
            print(f"  Cells analyzed: {analysis.get('cells_analyzed', '?')}")
            print(f"  Candidates (detour > 2.0): {len(candidates)}")
            for c in candidates[:5]:
                print(f"    {str(c['cell']):55s}  ratio={c['max_detour_ratio']}")

            if not candidates:
                print("\n  No candidates found — nothing to optimize")
                self.final_wns = self.initial_wns
                return True

            worst_path_cells = list(set(str(c["cell"]) for c in candidates if c.get("path", 0) <= 2))
            if not worst_path_cells:
                worst_path_cells = [str(candidates[0]["cell"])]

            print(f"\n  Targeting {len(worst_path_cells)} cells on paths 1-2:")
            for name in worst_path_cells:
                print(f"    {name}")

            print("\n" + "=" * 60)
            print("Step 3  RapidWright optimization")
            print("=" * 60)

            result = await self.call_rapidwright_tool("optimize_cell_placement", {"cell_names": worst_path_cells}, timeout=300.0)
            logger.info(f"optimize_cell_placement: {result}")

            opt_result = json.loads(result) if isinstance(result, str) else result
            for r in opt_result.get("results", []):
                print(f"  {r['cell']}: {r['status']} — {r['message']}")

            rw_output = Path(self.temp_dir) / "vexriscv_rw_optimized.dcp"
            result = await self.call_rapidwright_tool("write_checkpoint", {"dcp_path": str(rw_output)}, timeout=600.0)
            print(f"  Wrote {rw_output.name}")

            print("\n" + "=" * 60)
            print("Step 4  Vivado verification")
            print("=" * 60)

            result = await self.call_vivado_tool("open_checkpoint", {"dcp_path": str(rw_output)}, timeout=600.0)
            logger.info(f"Open optimized checkpoint: {result}")

            result = await self.call_vivado_tool("route_design", {"directive": "Default"}, timeout=3600.0)
            logger.info(f"Route design: {result}")

            route_result = await self.call_vivado_tool("report_route_status", {}, timeout=300.0)
            error_match = re.search(r"# of nets with routing errors.*?:\s+(\d+)", route_result)
            error_count = int(error_match.group(1)) if error_match else -1

            target_wns = await self.get_wns_for_target_clock(self._call_vivado_for_clock)
            if target_wns is not None:
                self.final_wns = target_wns
            else:
                ts = await self.call_vivado_tool("report_timing_summary", {}, timeout=300.0)
                self.final_wns = self.parse_wns_from_timing_report(ts)

            new_fmax = self.calculate_fmax(self.final_wns, self.clock_period)

            print(f"  Routing errors:  {error_count}")
            if baseline_fmax is not None and new_fmax is not None:
                print(f"  Baseline WNS:    {self.initial_wns} ns  →  Fmax {baseline_fmax:.2f} MHz")
                print(f"  Optimized WNS:   {self.final_wns} ns  →  Fmax {new_fmax:.2f} MHz")
                delta = new_fmax - baseline_fmax
                print(f"  Fmax improvement: {delta:+.2f} MHz")
            else:
                print(f"  Baseline WNS:  {self.initial_wns} ns")
                print(f"  Optimized WNS: {self.final_wns} ns")

            print(f"\nWriting final DCP to: {output_dcp}")
            await self.call_vivado_tool("write_checkpoint", {"dcp_path": str(output_dcp.resolve()), "force": True}, timeout=600.0)

            elapsed = time.time() - overall_start
            cells_info = ", ".join(worst_path_cells)
            self.print_test_summary(
                title="TEST SUMMARY - VEXRISCV CELL RE-PLACEMENT",
                elapsed_seconds=elapsed,
                initial_wns=self.initial_wns,
                final_wns=self.final_wns,
                clock_period=self.clock_period,
                extra_info=f"Cells re-placed: {cells_info}",
            )
            return True
        except Exception as e:
            logger.exception(f"VexRiscv test failed with exception: {e}")
            print(f"\n*** TEST FAILED ***")
            print(f"Exception: {type(e).__name__}: {e}")
            return False

    async def cleanup(self):
        print("\n[TEST] Cleaning up...")
        await super().cleanup()
        print(f"[TEST] Run directory preserved at: {self.run_dir}")


async def run_test_mode(input_dcp: Path, output_dcp: Path, debug: bool = False, max_nets: int = 5, run_dir: Optional[Path] = None):
    dcp_name = input_dcp.name.lower()

    if "logicnets" in dcp_name:
        design_type = "logicnets"
        print(f"[TEST] Detected LogicNets design - using pblock optimization flow")
    elif "vexriscv" in dcp_name:
        design_type = "vexriscv"
        print(f"[TEST] Detected VexRiscv design - using cell re-placement flow")
    else:
        print(f"\n[TEST] ERROR: Unsupported DCP file: {input_dcp.name}")
        print(f"[TEST] Test mode supports these benchmark DCPs:")
        print(f"[TEST]   - fpl26_contest_benchmarks/logicnets_jscl_2025.1.dcp")
        print(f"[TEST]   - fpl26_contest_benchmarks/vexriscv_re-place_2025.1.dcp")
        print(f"[TEST]")
        print(f"[TEST] For custom DCPs, run without --test to use the LLM-guided optimizer.")
        return 1

    tester = FPGAOptimizerTest(debug=debug, run_dir=run_dir)

    try:
        await tester.start_servers()

        if design_type == "logicnets":
            success = await tester.run_test_logicnets(input_dcp, output_dcp)
        else:
            success = await tester.run_test_vexriscv(input_dcp, output_dcp)

        if success:
            print("\n[TEST] Test completed successfully")
            print(f"\n[TEST] Output files:")
            print(f"[TEST]   Optimized DCP: {output_dcp}")
            print(f"[TEST]   Run directory: {tester.run_dir}")
            return 0
        else:
            print("\n[TEST] Test failed")
            print(f"[TEST] Run directory: {tester.run_dir}")
            return 1
    except KeyboardInterrupt:
        print("\n[TEST] Interrupted by user")
        print(f"[TEST] Run directory: {tester.run_dir}")
        return 130
    except Exception as e:
        logger.exception(f"Test mode fatal error: {e}")
        print(f"\n[TEST] Fatal error: {e}")
        print(f"[TEST] Run directory: {tester.run_dir}")
        return 1
    finally:
        await tester.cleanup()