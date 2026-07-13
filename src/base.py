"""Shared optimizer base class for FPGA design optimization workflows."""

import asyncio
import json
import logging
import os
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Optional

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from src.mcp import build_rapidwright_mcp_env

logger = logging.getLogger(__name__)


class DCPOptimizerBase:
    """Base class with shared functionality for FPGA optimization."""

    def __init__(self, debug: bool = False, run_dir: Optional[Path] = None):
        self.debug = debug

        if run_dir is None:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            self.run_dir = Path.cwd() / f"dcp_optimizer_run-{timestamp}"
            self.run_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created run directory: {self.run_dir}")
        else:
            self.run_dir = run_dir
            self.run_dir.mkdir(parents=True, exist_ok=True)

        self.exit_stack = AsyncExitStack()
        self.rapidwright_session: Optional[ClientSession] = None
        self.vivado_session: Optional[ClientSession] = None

        self.temp_dir = self.run_dir
        logger.info(f"Working directory: {self.temp_dir}")

        self.initial_wns = None
        self.initial_tns = None
        self.initial_failing_endpoints = None
        self.high_fanout_nets = []
        self.clock_period = None
        self.target_clock = None

        self._rw_log_file = None
        self._v_log_file = None

    async def start_servers(self, log_prefix: str = ""):
        """Start and connect to both MCP servers."""
        repo_root = Path(__file__).resolve().parent.parent

        rapidwright_log = self.run_dir / "rapidwright.log"
        rapidwright_mcp_log = self.run_dir / "rapidwright-mcp.log"
        vivado_log = self.run_dir / "vivado.log"
        vivado_journal = self.run_dir / "vivado.jou"
        vivado_mcp_log = self.run_dir / "vivado-mcp.log"

        if self.debug:
            self._rw_log_file = None
            self._v_log_file = None
            logger.info("Debug mode: MCP server output will be shown in console")
            if log_prefix:
                print(f"{log_prefix} Debug mode: MCP server output will be shown in console")
        else:
            self._rw_log_file = open(rapidwright_mcp_log, "w")
            self._v_log_file = open(vivado_mcp_log, "w")
            logger.info(f"RapidWright Java output: {rapidwright_log}")
            logger.info(f"RapidWright MCP output: {rapidwright_mcp_log}")
            logger.info(f"Vivado output: {vivado_log}")
            logger.info(f"Vivado journal: {vivado_journal}")
            logger.info(f"Vivado MCP output: {vivado_mcp_log}")
            print(
                f"Log files in {self.run_dir.name}/: {rapidwright_log.name}, {rapidwright_mcp_log.name}, "
                f"{vivado_log.name}, {vivado_journal.name}, {vivado_mcp_log.name}"
            )

        rapidwright_args = [str(repo_root / "RapidWrightMCP" / "server.py")]
        if not self.debug:
            rapidwright_args.extend([
                "--java-log", str(rapidwright_log),
                "--mcp-log", str(rapidwright_mcp_log),
            ])

        env = build_rapidwright_mcp_env(
            repo_root,
            os.environ,
            vivado_exec=os.environ.get("VIVADO_EXEC"),
        )

        rapidwright_config = {
            "command": sys.executable,
            "args": rapidwright_args,
            "cwd": str(self.run_dir),
            "env": env,
        }

        vivado_args = [str(repo_root / "VivadoMCP" / "vivado_mcp_server.py")]
        if not self.debug:
            vivado_args.extend([
                "--vivado-log", str(vivado_log),
                "--vivado-journal", str(vivado_journal),
            ])

        vivado_config = {
            "command": sys.executable,
            "args": vivado_args,
            "cwd": str(self.run_dir),
            "env": {**os.environ},
        }

        logger.info("Starting RapidWright MCP server...")
        if log_prefix:
            print(f"{log_prefix} Starting RapidWright MCP server...")
        start_time = time.time()

        rw_params = StdioServerParameters(**rapidwright_config)
        rw_errlog = self._rw_log_file or sys.stderr
        rw_transport = await self.exit_stack.enter_async_context(
            stdio_client(rw_params, errlog=rw_errlog)
        )
        rw_read, rw_write = rw_transport
        self.rapidwright_session = await self.exit_stack.enter_async_context(
            ClientSession(rw_read, rw_write)
        )
        await self.rapidwright_session.initialize()

        elapsed = time.time() - start_time
        logger.info(f"RapidWright MCP server started in {elapsed:.2f}s")
        if log_prefix:
            print(f"{log_prefix} RapidWright MCP server started in {elapsed:.2f}s")

        logger.info("Starting Vivado MCP server...")
        if log_prefix:
            print(f"{log_prefix} Starting Vivado MCP server...")
        start_time = time.time()

        vivado_params = StdioServerParameters(**vivado_config)
        v_errlog = self._v_log_file or sys.stderr
        vivado_transport = await self.exit_stack.enter_async_context(
            stdio_client(vivado_params, errlog=v_errlog)
        )
        v_read, v_write = vivado_transport
        self.vivado_session = await self.exit_stack.enter_async_context(
            ClientSession(v_read, v_write)
        )
        await self.vivado_session.initialize()

        elapsed = time.time() - start_time
        logger.info(f"Vivado MCP server started in {elapsed:.2f}s")
        if log_prefix:
            print(f"{log_prefix} Vivado MCP server started in {elapsed:.2f}s")

        logger.info("Both MCP servers connected")
        if log_prefix:
            print(f"{log_prefix} Both MCP servers connected successfully")

    async def cleanup(self):
        """Clean up resources."""
        await self.exit_stack.aclose()

        if self._rw_log_file:
            self._rw_log_file.close()
        if self._v_log_file:
            self._v_log_file.close()

        logger.info(f"Run directory preserved at: {self.run_dir}")

    def calculate_fmax(self, wns: Optional[float], clock_period: Optional[float]) -> Optional[float]:
        if clock_period is None or clock_period <= 0:
            return None
        if wns is None:
            return None

        achievable_period_ns = clock_period - wns
        if achievable_period_ns <= 0:
            return None

        return 1000.0 / achievable_period_ns

    async def get_clock_period(self, call_tool_fn) -> Optional[float]:
        tcl_cmd = (
            "set contest_clk [get_clocks -quiet clk_fpl26contest]; "
            "if {$contest_clk ne {}} { "
            "  puts \"CLOCK:clk_fpl26contest\"; "
            "  puts [get_property PERIOD $contest_clk]; "
            "} else { "
            "  set tp [get_timing_paths -max_paths 1 -setup]; "
            "  if {$tp ne {}} { "
            "    set clk [get_property ENDPOINT_CLOCK $tp]; "
            "    if {$clk ne {}} { "
            "      puts \"CLOCK:$clk\"; "
            "      puts [get_property PERIOD [get_clocks $clk]]; "
            "    } "
            "  } "
            "}"
        )
        try:
            result = await call_tool_fn("run_tcl", {"command": tcl_cmd})

            clock_name = None
            for token in result.strip().split():
                if token.startswith("CLOCK:"):
                    clock_name = token[len("CLOCK:"):]
                    continue
                if token.startswith("ERROR") or token.startswith("WARNING"):
                    continue
                try:
                    period = float(token)
                    if period > 0:
                        if clock_name:
                            self.target_clock = clock_name
                            logger.info(f"Target clock: {clock_name}, period: {period:.3f} ns")
                        else:
                            logger.info(f"Critical clock period: {period:.3f} ns")
                        return period
                except ValueError:
                    continue
        except Exception as e:
            logger.warning(f"Failed to get clock period: {e}")

        logger.warning("Could not determine clock period from Vivado")
        return None

    async def get_wns_for_target_clock(self, call_tool_fn) -> Optional[float]:
        if self.target_clock:
            tcl_cmd = (
                f"set clk_obj [get_clocks -quiet {{{self.target_clock}}}]; "
                f"if {{$clk_obj ne {{}}}} {{ "
                f"  set tp [get_timing_paths -max_paths 1 -setup -to $clk_obj]; "
                f"  if {{[llength $tp] > 0}} {{get_property SLACK $tp}} else {{puts 0.0}} "
                f"}} else {{ "
                f"  set tp [get_timing_paths -max_paths 1 -slack_lesser_than 999]; "
                f"  if {{[llength $tp] > 0}} {{get_property SLACK $tp}} else {{puts 0.0}} "
                f"}}"
            )
        else:
            tcl_cmd = (
                "set tp [get_timing_paths -max_paths 1 -slack_lesser_than 999]; "
                "if {[llength $tp] > 0} {get_property SLACK $tp} else {puts 0.0}"
            )

        try:
            result = await call_tool_fn("run_tcl", {"command": tcl_cmd})
            for token in result.strip().split("\n"):
                token = token.strip()
                if not token or token.startswith("ERROR") or token.startswith("WARNING"):
                    continue
                try:
                    wns = float(token)
                    clock_info = f" (clock: {self.target_clock})" if self.target_clock else ""
                    logger.info(f"WNS{clock_info}: {wns:.3f} ns")
                    return wns
                except ValueError:
                    continue
        except Exception as e:
            logger.warning(f"Failed to get WNS for target clock: {e}")

        return None

    def parse_high_fanout_nets(self, report: str) -> list[tuple[str, int, int]]:
        nets = []
        lines = report.split("\n")
        in_net_section = False

        for line in lines:
            if "Paths" in line and "Fanout" in line and "Parent Net Name" in line:
                in_net_section = True
                continue

            if in_net_section:
                if line.startswith("---") or not line.strip():
                    continue
                if line.startswith("==="):
                    break

                parts = line.split()
                if len(parts) >= 3:
                    try:
                        path_count = int(parts[0])
                        fanout = int(parts[1])
                        net_name = parts[2]

                        if (
                            net_name
                            and "/" in net_name
                            and not net_name.startswith("get_")
                            and not net_name.startswith("ERROR")
                            and not net_name.startswith("WARNING")
                        ):
                            nets.append((net_name, fanout, path_count))
                    except ValueError:
                        continue

        return nets

    def _format_fmax_results(
        self,
        clock_period: Optional[float],
        initial_wns: Optional[float],
        result_wns: Optional[float],
        result_label: str = "Final",
    ) -> list[str]:
        initial_fmax = self.calculate_fmax(initial_wns, clock_period)
        result_fmax = self.calculate_fmax(result_wns, clock_period)
        result_fmax_label = f"{result_label} Fmax:"
        result_wns_label = f"{result_label} WNS:"

        lines: list[str] = []
        if initial_fmax is not None and result_fmax is not None:
            assert clock_period is not None
            assert initial_wns is not None
            assert result_wns is not None
            target_fmax = 1000.0 / clock_period
            fmax_change = result_fmax - initial_fmax
            lines.append(f"  {'Target Fmax:':<21s}{target_fmax:8.2f} MHz  (clock period: {clock_period:.3f} ns)")
            lines.append(f"  {'Initial Fmax:':<21s}{initial_fmax:8.2f} MHz  (WNS: {initial_wns:.3f} ns)")
            lines.append(f"  {result_fmax_label:<21s}{result_fmax:8.2f} MHz  (WNS: {result_wns:.3f} ns)")
            lines.append(f"  {'Fmax Improvement:':<21s}{fmax_change:+8.2f} MHz  (WNS: {result_wns - initial_wns:+.3f} ns)")
        else:
            if clock_period is not None:
                target_fmax = 1000.0 / clock_period
                lines.append(f"  {'Clock period:':<21s}{clock_period:8.3f} ns (target: {target_fmax:.2f} MHz)")
            if initial_wns is not None:
                fmax_str = f"  (fmax: {initial_fmax:.2f} MHz)" if initial_fmax else ""
                lines.append(f"  {'Initial WNS:':<21s}{initial_wns:8.3f} ns{fmax_str}")
            if result_wns is not None:
                fmax_str = f"  (fmax: {result_fmax:.2f} MHz)" if result_fmax else ""
                lines.append(f"  {result_wns_label:<21s}{result_wns:8.3f} ns{fmax_str}")
            if initial_wns is not None and result_wns is not None:
                lines.append(f"  {'WNS Improvement:':<21s}{result_wns - initial_wns:+8.3f} ns")

        return lines

    def print_wns_change(
        self,
        initial_wns: Optional[float],
        final_wns: Optional[float],
        clock_period: Optional[float],
    ):
        if final_wns is None or initial_wns is None:
            return

        initial_fmax = self.calculate_fmax(initial_wns, clock_period)
        final_fmax = self.calculate_fmax(final_wns, clock_period)

        if initial_fmax is not None and final_fmax is not None:
            fmax_improvement = final_fmax - initial_fmax
            pct = (fmax_improvement / initial_fmax) * 100 if initial_fmax else 0
            print(f"\n*** Fmax: {initial_fmax:.2f} -> {final_fmax:.2f} MHz ({fmax_improvement:+.2f} MHz, {pct:+.1f}%) ***")
            print(f"*** WNS:  {initial_wns:.3f} -> {final_wns:.3f} ns ***")
            if fmax_improvement > 0:
                print(f"IMPROVEMENT: Fmax improved by {fmax_improvement:.2f} MHz")
            elif fmax_improvement < 0:
                print(f"REGRESSION: Fmax got worse by {-fmax_improvement:.2f} MHz")
            else:
                print("NO CHANGE: Fmax is the same")
        else:
            wns_improvement = final_wns - initial_wns
            print(f"\n*** WNS: {initial_wns:.3f} -> {final_wns:.3f} ns ({wns_improvement:+.3f} ns) ***")
            if wns_improvement > 0:
                print(f"IMPROVEMENT: WNS improved by {wns_improvement:.3f} ns")
            elif wns_improvement < 0:
                print(f"REGRESSION: WNS got worse by {-wns_improvement:.3f} ns")
            else:
                print("NO CHANGE")

    def print_fmax_status(self, label: str, wns: Optional[float]):
        if wns is None:
            print(f"*** {label}: WNS unknown ***")
            return
        fmax = self.calculate_fmax(wns, self.clock_period)
        clock_info = f" (clock: {self.target_clock})" if self.target_clock else ""
        if fmax is not None:
            print(f"*** {label} Fmax{clock_info}: {fmax:.2f} MHz (WNS: {wns:.3f} ns) ***")
        else:
            print(f"*** {label} WNS{clock_info}: {wns:.3f} ns ***")

    def print_test_summary(
        self,
        title: str,
        elapsed_seconds: float,
        initial_wns: Optional[float],
        final_wns: Optional[float],
        clock_period: Optional[float],
        extra_info: str = "",
    ):
        print("\n" + "=" * 70)
        print(title)
        print("=" * 70)
        print(f"Total runtime: {elapsed_seconds:.2f} seconds ({elapsed_seconds/60:.2f} minutes)")

        result_lines = self._format_fmax_results(clock_period, initial_wns, final_wns)
        if result_lines:
            print(f"\nFmax Results:")
            print("\n".join(result_lines))

        if extra_info:
            print(f"\n{extra_info}")
        print("=" * 70)
