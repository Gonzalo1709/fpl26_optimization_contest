"""LLM-driven optimization mode for the FPGA optimizer."""

import json
import logging
import re
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from openai import OpenAI

from src.base import DCPOptimizerBase
from src.parsers import load_system_prompt, parse_timing_summary_static
from src.search import GenerationSearchConfig, SearchCandidate

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "~openai/gpt-latest"


class ToolExecutionError(RuntimeError):
    """Raised when an MCP tool call fails or returns an error payload."""


class DCPOptimizer(DCPOptimizerBase):
    """FPGA Design Optimization Agent using recipe selection plus generation search."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        debug: bool = False,
        run_dir: Optional[Path] = None,
        generation_config: Optional[GenerationSearchConfig] = None,
    ):
        super().__init__(debug=debug, run_dir=run_dir)

        self.api_key = api_key
        self.model = model
        self.generation_config = generation_config or GenerationSearchConfig()
        self.openai = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )

        self.iteration = 0
        self.best_wns = float("-inf")
        self.no_improvement_count = 0
        self.llm_call_count = 0

        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.total_cost = 0.0
        self.api_call_details: list[dict] = []
        self.tool_call_details: list[dict] = []

        self.search_candidates: list[SearchCandidate] = []
        self.best_candidate: Optional[SearchCandidate] = None

        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

        self.history: list[dict] = []
        self.fanout_blacklist: dict[str, str] = {}

    def _extract_llm_text(self, response) -> str:
        """Best-effort extraction of text content from a chat completion response."""
        choices = getattr(response, "choices", None) or []
        if not choices:
            logger.warning("LLM response had no choices")
            return ""

        message = getattr(choices[0], "message", None)
        if message is None:
            logger.warning("LLM response choice had no message")
            return ""

        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text" and part.get("text"):
                        text_parts.append(part["text"])
                else:
                    part_type = getattr(part, "type", None)
                    part_text = getattr(part, "text", None)
                    if part_type == "text" and part_text:
                        text_parts.append(part_text)
            if text_parts:
                return "\n".join(text_parts).strip()

        refusal = getattr(message, "refusal", None)
        if refusal:
            logger.warning("LLM response returned refusal text instead of content: %s", refusal)
            return str(refusal).strip()

        finish_reason = getattr(choices[0], "finish_reason", None)
        logger.warning(
            "LLM response had empty content (finish_reason=%s, content_type=%s)",
            finish_reason,
            type(content).__name__ if content is not None else "None",
        )
        return ""

    def _raise_if_tool_reported_error(self, tool_name: str, result_text: str) -> None:
        """Raise when a tool encodes failure in its textual payload."""
        try:
            payload = json.loads(result_text)
        except json.JSONDecodeError:
            return

        if isinstance(payload, dict):
            error_message = payload.get("error")
            if error_message:
                error_category = payload.get("error_category")
                category_prefix = f"[{error_category}] " if error_category else ""
                raise ToolExecutionError(f"{tool_name} failed: {category_prefix}{error_message}")
            if payload.get("status") == "error":
                message = payload.get("message") or result_text
                raise ToolExecutionError(f"{tool_name} failed: {message}")

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool call on the appropriate MCP server."""
        if tool_name.startswith("rapidwright_"):
            session = self.rapidwright_session
            actual_name = tool_name[len("rapidwright_"):]
        elif tool_name.startswith("vivado_"):
            session = self.vivado_session
            actual_name = tool_name[len("vivado_"):]
        else:
            raise ToolExecutionError(f"Unknown tool prefix in: {tool_name}")

        start_time = time.time()
        wns_measured = None

        try:
            logger.info("Calling %s with args: %s...", tool_name, json.dumps(arguments)[:200])
            result = await session.call_tool(actual_name, arguments)

            if result.content:
                text_parts = [chunk.text for chunk in result.content if hasattr(chunk, "text")]
                result_text = "\n".join(text_parts)
            else:
                result_text = "(no output)"

            self._raise_if_tool_reported_error(tool_name, result_text)

            if tool_name == "vivado_report_timing_summary":
                if self.target_clock:
                    try:
                        clock_wns = await super().get_wns_for_target_clock(self._call_vivado_tool)
                        if clock_wns is not None:
                            wns_measured = clock_wns
                            self._update_best_wns(clock_wns, source=f"clock: {self.target_clock}")
                    except Exception as exc:
                        logger.warning("Failed to get clock-specific WNS, falling back to overall: %s", exc)
                        self.target_clock = None

                if not self.target_clock or wns_measured is None:
                    timing_info = parse_timing_summary_static(result_text)
                    if timing_info["wns"] is not None:
                        wns_measured = timing_info["wns"]
                        self._update_best_wns(wns_measured)
            elif tool_name == "vivado_get_wns":
                try:
                    wns_measured = float(result_text.strip())
                    self._update_best_wns(wns_measured, source="get_wns")
                except (ValueError, AttributeError):
                    logger.warning("Could not parse WNS from get_wns output: %s", result_text[:100])

            elapsed_time = time.time() - start_time
            self.tool_call_details.append(
                {
                    "tool_name": tool_name,
                    "iteration": self.iteration,
                    "elapsed_time": elapsed_time,
                    "wns": wns_measured,
                    "error": False,
                }
            )
            return result_text
        except ToolExecutionError as exc:
            elapsed_time = time.time() - start_time
            self.tool_call_details.append(
                {
                    "tool_name": tool_name,
                    "iteration": self.iteration,
                    "elapsed_time": elapsed_time,
                    "wns": None,
                    "error": True,
                    "error_message": str(exc),
                }
            )
            logger.error("Tool call failed: %s", exc)
            raise
        except Exception as exc:
            elapsed_time = time.time() - start_time
            self.tool_call_details.append(
                {
                    "tool_name": tool_name,
                    "iteration": self.iteration,
                    "elapsed_time": elapsed_time,
                    "wns": None,
                    "error": True,
                    "error_message": str(exc),
                }
            )
            logger.error("Tool call failed: %s", exc)
            raise ToolExecutionError(f"{tool_name} failed: {exc}") from exc

    def _update_best_wns(self, current_wns: float, source: str = "timing_summary"):
        current_fmax = self.calculate_fmax(current_wns, self.clock_period)
        fmax_str = f", fmax: {current_fmax:.2f} MHz" if current_fmax is not None else ""
        if current_wns > self.best_wns:
            logger.info(
                "New best WNS (%s): %.3f ns%s (improved from %.3f ns)",
                source,
                current_wns,
                fmax_str,
                self.best_wns,
            )
            self.best_wns = current_wns
        else:
            logger.info(
                "Current WNS (%s): %.3f ns%s (best is still %.3f ns)",
                source,
                current_wns,
                fmax_str,
                self.best_wns,
            )

    async def _call_vivado_tool(self, tool_name: str, arguments: dict) -> str:
        """Helper to call Vivado tools for base-class methods."""
        return await self.call_tool(f"vivado_{tool_name}", arguments)

    async def perform_initial_analysis(self, input_dcp: Path) -> str:
        """Perform deterministic startup analysis before the optimization loop begins."""
        logger.info("Performing initial design analysis...")
        print("\n=== Initial Design Analysis ===\n")

        print("Initializing RapidWright...")
        result = await self.call_tool("rapidwright_initialize_rapidwright", {})
        if "error" in result.lower() and "success" not in result.lower():
            raise RuntimeError(f"Failed to initialize RapidWright: {result}")
        print("✓ RapidWright initialized\n")

        print(f"Opening checkpoint: {input_dcp.name}")
        result = await self.call_tool("vivado_open_checkpoint", {"dcp_path": str(input_dcp.resolve())})
        if "error" in result.lower() and "opened successfully" not in result.lower():
            raise RuntimeError(f"Failed to open checkpoint: {result}")
        print("✓ Checkpoint opened in Vivado\n")

        print("Analyzing timing...")
        timing_report = await self.call_tool("vivado_report_timing_summary", {})
        timing_info = parse_timing_summary_static(timing_report)
        self.initial_tns = timing_info["tns"]
        self.initial_failing_endpoints = timing_info["failing_endpoints"]

        self.clock_period = await super().get_clock_period(self._call_vivado_tool)
        target_wns = await super().get_wns_for_target_clock(self._call_vivado_tool)
        self.initial_wns = target_wns if target_wns is not None else timing_info["wns"]
        self.best_wns = self.initial_wns if self.initial_wns is not None else float("-inf")

        clock_info = f" (clock: {self.target_clock})" if self.target_clock else ""
        print("✓ Timing analyzed:")
        if self.clock_period is not None:
            target_fmax = 1000.0 / self.clock_period
            print(f"  - Clock period: {self.clock_period:.3f} ns (target fmax: {target_fmax:.2f} MHz)")
        if self.target_clock:
            print(f"  - Target clock: {self.target_clock}")
        if self.initial_wns is not None:
            print(f"  - WNS{clock_info}: {self.initial_wns:.3f} ns")
            initial_fmax = self.calculate_fmax(self.initial_wns, self.clock_period)
            if initial_fmax is not None:
                print(f"  - Achievable fmax: {initial_fmax:.2f} MHz")
        if self.initial_tns is not None:
            print(f"  - TNS: {self.initial_tns:.3f} ns")
        if self.initial_failing_endpoints is not None:
            print(f"  - Failing endpoints: {self.initial_failing_endpoints}")
        print()

        print("Identifying critical high fanout nets...")
        nets_report = await self.call_tool(
            "vivado_get_critical_high_fanout_nets",
            {"num_paths": 50, "min_fanout": 100},
        )
        self.high_fanout_nets = self.parse_high_fanout_nets(nets_report)
        print(f"✓ Found {len(self.high_fanout_nets)} high fanout nets (>100 fanout)\n")

        critical_path_spread_info = None

        print("Loading design in RapidWright for spread analysis...")
        result = await self.call_tool("rapidwright_read_checkpoint", {"dcp_path": str(input_dcp.resolve())})
        if "error" in result.lower() and "success" not in result.lower():
            print(f"⚠ Warning: Could not load design in RapidWright: {result}")
        else:
            print("✓ Design loaded in RapidWright\n")
            print("Analyzing critical path spread...")
            temp_path = Path(self.temp_dir) / "initial_critical_paths.json"
            await self.call_tool(
                "vivado_extract_critical_path_cells",
                {"num_paths": 50, "output_file": str(temp_path)},
            )
            spread_result = await self.call_tool(
                "rapidwright_analyze_critical_path_spread",
                {"input_file": str(temp_path)},
            )

            try:
                spread_data = json.loads(spread_result)
                critical_path_spread_info = {
                    "max_distance": spread_data.get("max_distance_found", 0),
                    "avg_distance": spread_data.get("avg_max_distance", 0),
                    "paths_analyzed": spread_data.get("paths_analyzed", 0),
                }
                print("✓ Critical path spread analyzed:")
                print(f"  - Max distance: {critical_path_spread_info['max_distance']} tiles")
                print(f"  - Avg distance: {critical_path_spread_info['avg_distance']:.1f} tiles")
                print(f"  - Paths analyzed: {critical_path_spread_info['paths_analyzed']}")
                print()
            except (json.JSONDecodeError, KeyError) as exc:
                print(f"⚠ Warning: Could not parse spread results: {exc}")

        summary = ["=== Initial Design Analysis ===\n", "TIMING STATUS:"]
        if self.clock_period is not None:
            target_fmax = 1000.0 / self.clock_period
            summary.append(f"  Clock period: {self.clock_period:.3f} ns (target fmax: {target_fmax:.2f} MHz)")
        if self.initial_wns is not None:
            if self.initial_wns >= 0:
                summary.append(f"  WNS: {self.initial_wns:.3f} ns - TIMING MET ✓")
            else:
                summary.append(f"  WNS: {self.initial_wns:.3f} ns - TIMING VIOLATED")
            initial_fmax = self.calculate_fmax(self.initial_wns, self.clock_period)
            if initial_fmax is not None:
                summary.append(f"  Achievable fmax: {initial_fmax:.2f} MHz")
        if self.initial_tns is not None:
            summary.append(f"  TNS: {self.initial_tns:.3f} ns")
        if self.initial_failing_endpoints is not None:
            summary.append(f"  Failing endpoints: {self.initial_failing_endpoints}")
        summary.append("")

        if critical_path_spread_info:
            summary.append("CRITICAL PATH SPREAD ANALYSIS:")
            summary.append(f"  Max cell distance: {critical_path_spread_info['max_distance']} tiles")
            summary.append(f"  Avg cell distance: {critical_path_spread_info['avg_distance']:.1f} tiles")
            summary.append(f"  Paths analyzed: {critical_path_spread_info['paths_analyzed']}")
            if critical_path_spread_info["avg_distance"] > 70 and critical_path_spread_info["paths_analyzed"] >= 5:
                summary.append("  ⚠ RECOMMENDATION: Use PBLOCK strategy (high spread detected)")
            summary.append("")

        if self.high_fanout_nets:
            summary.append("CRITICAL HIGH FANOUT NETS (top 10):")
            for index, (net_name, fanout, path_count) in enumerate(self.high_fanout_nets[:10], start=1):
                summary.append(f"  {index}. {net_name}")
                summary.append(f"     Fanout: {fanout}, Critical paths: {path_count}")
            if len(self.high_fanout_nets) > 10:
                summary.append(f"  ... and {len(self.high_fanout_nets) - 10} more nets")
        else:
            summary.append("CRITICAL HIGH FANOUT NETS: None found")

        summary.append("")
        summary.append(f"Total nets available for optimization: {len(self.high_fanout_nets)}")

        summary_text = "\n".join(summary)
        print(summary_text)
        print()
        return summary_text

    async def choose_action_llm(self, decision_input: dict) -> dict:
        """Choose a recipe and its arguments using a single LLM call."""
        prompt = """
You are an FPGA optimization planner.

Choose the next optimization recipe.

Return JSON:
{
  "strategy": "PBLOCK | FANOUT | PHYS_OPT",
  "args": { ... }
}

Rules:
- You do not have direct access to Vivado or RapidWright tools.
- You must choose only among the provided recipes.
- Do not reason in terms of tool calls, tool names, or command sequences.
- Prefer PBLOCK when the analysis shows spread-out critical paths or explicitly recommends PBLOCK.
- Prefer FANOUT when critical high-fanout nets are present, not blacklisted, and placement spread is not the main issue.
- Prefer PHYS_OPT when placement spread is low, after PBLOCK/FANOUT changed the design, or when earlier steps stagnate.
- Avoid repeating strategies that the recent history shows were ineffective from the current state.
- If stagnation >= 2, switch strategy if possible.
- If a FANOUT net previously failed, do not pick FANOUT just to retry the same exhausted net set.
- Use timing metrics holistically: WNS first, then TNS, then failing endpoints.
- FANOUT means: choose how many top candidate nets the controller should try within the FANOUT recipe.
- PBLOCK means: choose the PBLOCK recipe when spread reduction is the main bet.
- PHYS_OPT means: choose the PHYS_OPT recipe when local fine-tuning is the main bet.
- FANOUT: choose top_n_nets (1-10)
- PHYS_OPT: choose directive from ["Explore", "AggressiveExplore", "Default"]
- PBLOCK: args can be empty

Recipe intent reference:
- FANOUT is best for shared enable/valid/control nets on many failing paths.
- PBLOCK is best for spread-out critical paths and large physical distance.
- PHYS_OPT is best for local cleanup and fine-tuning after structure/placement is already reasonable.

Return ONLY JSON.
"""

        response = self.openai.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(decision_input)},
            ],
            max_tokens=200,
            extra_body={"usage": {"include": True}},
        )

        self.llm_call_count += 1

        usage = getattr(response, "usage", None)
        if usage:
            prompt_tokens = getattr(usage, "prompt_tokens", 0)
            completion_tokens = getattr(usage, "completion_tokens", 0)
            total_tokens = getattr(usage, "total_tokens", 0)
            self.total_prompt_tokens += prompt_tokens
            self.total_completion_tokens += completion_tokens
            self.total_tokens += total_tokens

            call_cost = 0.0
            if hasattr(usage, "cost") and usage.cost is not None:
                call_cost = float(usage.cost)
                self.total_cost += call_cost
            else:
                logger.warning("OpenRouter did not provide cost information")

            cached_tokens = 0
            reasoning_tokens = 0
            if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
                cached_tokens = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
            if hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
                reasoning_tokens = getattr(usage.completion_tokens_details, "reasoning_tokens", 0) or 0

            self.api_call_details.append(
                {
                    "call_number": self.llm_call_count,
                    "iteration": self.iteration,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "cost": call_cost,
                    "cached_tokens": cached_tokens,
                    "reasoning_tokens": reasoning_tokens,
                }
            )

            cache_info = f", Cached: {cached_tokens:,}" if cached_tokens > 0 else ""
            reasoning_info = f", Reasoning: {reasoning_tokens:,}" if reasoning_tokens > 0 else ""
            cost_info = f" | Cost: ${call_cost:.4f}" if call_cost > 0 else ""
            print(
                f"[API Call #{self.llm_call_count}] Tokens: {total_tokens:,} "
                f"(Prompt: {prompt_tokens:,}, Completion: {completion_tokens:,}{cache_info}{reasoning_info}){cost_info}"
            )

        content = self._extract_llm_text(response)
        if not content:
            logger.warning("Planner returned no text, falling back to PHYS_OPT")
            return {"strategy": "PHYS_OPT", "args": {"directive": "Default"}}

        try:
            return json.loads(content)
        except Exception:
            logger.warning("Could not parse planner JSON, falling back to PHYS_OPT. Raw content: %s", content)
            return {"strategy": "PHYS_OPT", "args": {"directive": "Default"}}

    def sanitize_action(self, action: dict) -> tuple[str, dict]:
        """Validate strategy output from the LLM."""
        strategy = action.get("strategy", "PHYS_OPT")
        args = action.get("args", {})

        if strategy == "FANOUT":
            top_n = int(args.get("top_n_nets", 5))
            top_n = max(1, min(10, top_n))
            return strategy, {"top_n_nets": top_n}

        if strategy == "PHYS_OPT":
            directive = args.get("directive", "Default")
            if directive not in ["Explore", "AggressiveExplore", "Default"]:
                directive = "Default"
            return strategy, {"directive": directive}

        if strategy == "PBLOCK":
            return strategy, {}

        return "PHYS_OPT", {"directive": "Default"}

    async def v(self, name: str, args: Optional[dict] = None) -> str:
        """Call a Vivado MCP tool."""
        return await self.call_tool(f"vivado_{name}", args or {})

    async def rw(self, name: str, args: Optional[dict] = None) -> str:
        """Call a RapidWright MCP tool."""
        return await self.call_tool(f"rapidwright_{name}", args or {})

    async def _reload_rapidwright_from_vivado_checkpoint(self, dcp_path: Path) -> None:
        """Load a freshly written Vivado checkpoint into RapidWright."""
        await self.rw("read_checkpoint", {"dcp_path": str(dcp_path.resolve())})

    async def _reroute_and_measure(self) -> tuple[str, Optional[float]]:
        """Route the current Vivado design and return timing plus measured WNS."""
        timing_report = await self.v("route_design")
        timing_report = await self.v("report_timing_summary")
        return timing_report, await self._measure_current_wns(timing_report)

    def _extract_timing_metrics(self, timing_report: str) -> dict:
        """Parse WNS/TNS/failing endpoints from a timing report."""
        metrics = parse_timing_summary_static(timing_report)
        return {
            "wns": metrics.get("wns"),
            "tns": metrics.get("tns"),
            "failing_endpoints": metrics.get("failing_endpoints"),
        }

    def _metrics_sort_key(self, metrics: Optional[dict]) -> tuple[float, float, float]:
        """Sort timing metrics from best to worst."""
        if not metrics:
            return (float("-inf"), float("-inf"), float("-inf"))
        wns = metrics.get("wns")
        tns = metrics.get("tns")
        failing_endpoints = metrics.get("failing_endpoints")
        return (
            wns if wns is not None else float("-inf"),
            tns if tns is not None else float("-inf"),
            -(failing_endpoints if failing_endpoints is not None else float("inf")),
        )

    def _is_metrics_improvement(self, new_metrics: Optional[dict], old_metrics: Optional[dict]) -> bool:
        """Return True if timing metrics show a meaningful improvement."""
        if not new_metrics:
            return False
        if not old_metrics:
            return True

        new_wns = new_metrics.get("wns")
        old_wns = old_metrics.get("wns")
        if self._is_wns_improvement(new_wns, old_wns):
            return True

        if new_wns is not None and old_wns is not None and abs(new_wns - old_wns) <= self.generation_config.min_wns_delta:
            new_tns = new_metrics.get("tns")
            old_tns = old_metrics.get("tns")
            if new_tns is not None and old_tns is not None and new_tns > old_tns + 0.01:
                return True

            new_fe = new_metrics.get("failing_endpoints")
            old_fe = old_metrics.get("failing_endpoints")
            if (
                new_fe is not None
                and old_fe is not None
                and new_tns is not None
                and old_tns is not None
                and abs(new_tns - old_tns) <= 0.01
                and new_fe < old_fe
            ):
                return True

        return False

    async def _measure_current_metrics(self, timing_report: Optional[str] = None) -> dict:
        """Measure current timing metrics from the current Vivado state."""
        report = timing_report
        if report is None:
            report = await self.v("report_timing_summary")
        metrics = self._extract_timing_metrics(report)

        if metrics["wns"] is None:
            metrics["wns"] = await super().get_wns_for_target_clock(self._call_vivado_tool)

        if metrics["wns"] is not None and metrics["wns"] > self.best_wns:
            self.best_wns = metrics["wns"]
        return metrics

    def _forced_branch_strategy(
        self,
        generation: int,
        parent: SearchCandidate,
        branch_index: int,
        step: int,
    ) -> Optional[tuple[str, dict]]:
        """Force recipe diversity for the first generation from the root candidate."""
        if generation != 1 or parent.candidate_id != "root" or step != 1:
            return None

        forced_strategies = [
            ("FANOUT", {"top_n_nets": 3}),
            ("PBLOCK", {}),
            ("PHYS_OPT", {"directive": "Explore"}),
        ]
        strategy_index = min(branch_index - 1, len(forced_strategies) - 1)
        return forced_strategies[strategy_index]

    async def run_pblock_flow(self) -> str:
        """Execute a staged PBLOCK recipe with progressively stronger constraints."""
        baseline_checkpoint = Path(self.temp_dir) / "pblock_baseline.dcp"
        await self.v("write_checkpoint", {"dcp_path": str(baseline_checkpoint.resolve()), "force": True})
        baseline_report = await self.v("report_timing_summary")
        baseline_metrics = await self._measure_current_metrics(baseline_report)

        util_report = await self.v("report_utilization_for_pblock")
        util = self.parse_utilization(util_report)

        fabric = await self.rw(
            "analyze_fabric_for_pblock",
            {
                "target_lut_count": int(util["lut"] * 1.5),
                "target_ff_count": int(util["ff"] * 1.5),
            },
        )

        fabric_data = json.loads(fabric)
        if "recommended_region" not in fabric_data:
            raise ValueError(f"No recommended_region in response: {fabric_data}")

        region = fabric_data["recommended_region"]
        pblock = await self.rw(
            "convert_fabric_region_to_pblock",
            {
                "col_min": region["col_min"],
                "col_max": region["col_max"],
                "row_min": region["row_min"],
                "row_max": region["row_max"],
                "use_clock_regions": False,
            },
        )
        pblock_ranges = json.loads(pblock)["pblock_ranges"]

        attempt_plans = [
            {"suffix": "soft", "is_soft": True, "place_directive": "Default", "phys_opt_directive": "Default"},
            {"suffix": "balanced", "is_soft": False, "place_directive": "Explore", "phys_opt_directive": "Explore"},
            {
                "suffix": "aggressive",
                "is_soft": False,
                "place_directive": "Quick",
                "phys_opt_directive": "AggressiveExplore",
            },
        ]

        best_report: Optional[str] = baseline_report
        best_metrics = baseline_metrics
        best_checkpoint = baseline_checkpoint

        for attempt_index, plan in enumerate(attempt_plans, start=1):
            checkpoint_path = Path(self.temp_dir) / f"pblock_attempt_{attempt_index:02d}.dcp"
            await self.v("write_checkpoint", {"dcp_path": str(checkpoint_path.resolve()), "force": True})
            await self.v("open_checkpoint", {"dcp_path": str(checkpoint_path.resolve())})

            await self.v("create_and_apply_pblock", {
                "pblock_name": f"opt_pblock_{plan['suffix']}",
                "ranges": pblock_ranges,
                "is_soft": plan["is_soft"],
            })
            await self.v("run_tcl", {"command": "place_design -unplace"})
            await self.v("place_design", {"directive": plan["place_directive"]})
            await self.v("phys_opt_design", {"directive": plan["phys_opt_directive"]})
            report, _ = await self._reroute_and_measure()
            current_metrics = await self._measure_current_metrics(report)

            if self._is_metrics_improvement(current_metrics, best_metrics):
                best_metrics = current_metrics
                best_report = report
                best_checkpoint = Path(self.temp_dir) / f"pblock_best_{attempt_index:02d}.dcp"
                await self.v("write_checkpoint", {"dcp_path": str(best_checkpoint.resolve()), "force": True})

        await self.v("open_checkpoint", {"dcp_path": str(best_checkpoint.resolve())})
        return best_report

    async def run_fanout_flow(self, top_n_nets: int = 5) -> str:
        """Execute high-fanout optimization with per-net reroute feedback."""
        nets_report = await self.v(
            "get_critical_high_fanout_nets",
            {
                "num_paths": 50,
                "min_fanout": 100,
                "exclude_clocks": True,
            },
        )
        self.high_fanout_nets = self.parse_high_fanout_nets(nets_report)
        nets_to_optimize = [
            net_info for net_info in self.high_fanout_nets if net_info[0] not in self.fanout_blacklist
        ][:top_n_nets]
        if not nets_to_optimize:
            raise ValueError("No critical high-fanout nets are available in the current design state.")

        best_report = await self.v("report_timing_summary")
        best_metrics = await self._measure_current_metrics(best_report)

        for net_index, (net_name, fanout, _) in enumerate(nets_to_optimize, start=1):
            baseline_checkpoint = Path(self.temp_dir) / f"fanout_before_{net_index:02d}.dcp"
            await self.v("write_checkpoint", {"dcp_path": str(baseline_checkpoint.resolve()), "force": True})
            await self._reload_rapidwright_from_vivado_checkpoint(baseline_checkpoint)

            split_factor = max(3, min(8, fanout // 100))
            try:
                await self.rw(
                    "optimize_fanout",
                    {
                        "net_name": net_name,
                        "split_factor": split_factor,
                    },
                )
            except ToolExecutionError as exc:
                self.fanout_blacklist[net_name] = str(exc)
                logger.warning("Blacklisting fanout net %s after tool failure: %s", net_name, exc)
                continue

            temp_dcp = Path(self.temp_dir) / f"fanout_opt_{net_index:02d}.dcp"
            await self.rw(
                "write_checkpoint",
                {
                    "dcp_path": str(temp_dcp.resolve()),
                    "overwrite": True,
                },
            )

            await self.v("open_checkpoint", {"dcp_path": str(temp_dcp.resolve())})
            report, _ = await self._reroute_and_measure()
            current_metrics = await self._measure_current_metrics(report)

            if self._is_metrics_improvement(current_metrics, best_metrics):
                best_metrics = current_metrics
                best_report = report
            else:
                await self.v("open_checkpoint", {"dcp_path": str(baseline_checkpoint.resolve())})

        return best_report

    async def run_phys_opt_flow(self, directive: str = "Default") -> str:
        """Execute a multi-pass Vivado phys_opt recipe."""
        baseline_checkpoint = Path(self.temp_dir) / "phys_opt_baseline.dcp"
        await self.v("write_checkpoint", {"dcp_path": str(baseline_checkpoint.resolve()), "force": True})
        baseline_report = await self.v("report_timing_summary")
        baseline_metrics = await self._measure_current_metrics(baseline_report)

        directive_sequence = [directive]
        if directive == "Default":
            directive_sequence.extend(["Explore", "AggressiveExplore"])
        elif directive == "Explore":
            directive_sequence.append("AggressiveExplore")

        best_report: Optional[str] = baseline_report
        best_metrics = baseline_metrics
        best_checkpoint = baseline_checkpoint

        for pass_index, current_directive in enumerate(directive_sequence, start=1):
            checkpoint_path = Path(self.temp_dir) / f"phys_opt_before_{pass_index:02d}.dcp"
            await self.v("write_checkpoint", {"dcp_path": str(checkpoint_path.resolve()), "force": True})
            await self.v("phys_opt_design", {"directive": current_directive})
            report = await self.v("report_timing_summary")
            current_metrics = await self._measure_current_metrics(report)

            if self._is_metrics_improvement(current_metrics, best_metrics):
                best_metrics = current_metrics
                best_report = report
                best_checkpoint = Path(self.temp_dir) / f"phys_opt_best_{pass_index:02d}.dcp"
                await self.v("write_checkpoint", {"dcp_path": str(best_checkpoint.resolve()), "force": True})
                continue

            await self.v("open_checkpoint", {"dcp_path": str(checkpoint_path.resolve())})

        await self.v("open_checkpoint", {"dcp_path": str(best_checkpoint.resolve())})
        return best_report

    def parse_utilization(self, report: str) -> dict:
        """Extract LUT and FF counts from the pblock utilization report."""
        lut = None
        ff = None
        in_base_section = False

        for line in report.splitlines():
            line = line.strip()
            if "Design Resource Utilization" in line:
                in_base_section = True
                continue
            if "1.5x Multiplier" in line:
                break
            if not in_base_section:
                continue

            if line.startswith("LUTs:"):
                match = re.search(r"([\d,]+)", line)
                if match:
                    lut = int(match.group(1).replace(",", ""))
            elif line.startswith("FFs:"):
                match = re.search(r"([\d,]+)", line)
                if match:
                    ff = int(match.group(1).replace(",", ""))

        if lut is None or ff is None:
            raise ValueError(f"Could not parse utilization:\n{report[:500]}")

        return {"lut": lut, "ff": ff}

    async def _execute_strategy(self, strategy: str, args: dict) -> tuple[str, Optional[float]]:
        """Run a chosen recipe and return the timing report plus measured WNS."""
        if strategy == "PBLOCK":
            result = await self.run_pblock_flow()
        elif strategy == "FANOUT":
            result = await self.run_fanout_flow(**args)
        else:
            result = await self.run_phys_opt_flow(**args)

        current_wns = await self._measure_current_wns(result)
        return result, current_wns

    def _build_decision_input(
        self,
        analysis_summary: str,
        stagnation: int,
        recent_history: list[dict],
        branch_context: str = "",
        tried_summaries: str = "",
    ) -> dict:
        """Assemble the planner input for one recipe-selection decision."""
        return {
            "analysis": analysis_summary,
            "history": recent_history,
            "best_wns": self.best_wns,
            "stagnation": stagnation,
            "branch_context": branch_context,
            "recent_candidates": tried_summaries,
            "fanout_blacklist": self.fanout_blacklist,
            "search_settings": asdict(self.generation_config),
            "available_strategies": {
                "PBLOCK": {},
                "FANOUT": {"top_n_nets": "int (1-10)"},
                "PHYS_OPT": {"directive": ["Explore", "AggressiveExplore", "Default"]},
            },
        }

    def _is_wns_improvement(self, new_wns: Optional[float], old_wns: Optional[float]) -> bool:
        """Return True if new_wns beats old_wns by the configured threshold."""
        if new_wns is None:
            return False
        if old_wns is None:
            return True
        return new_wns > old_wns + self.generation_config.min_wns_delta

    async def _measure_current_wns(self, timing_report: Optional[str] = None) -> Optional[float]:
        """Measure current Vivado WNS and update the global best scalar."""
        wns = await super().get_wns_for_target_clock(self._call_vivado_tool)
        if wns is None:
            report = timing_report
            if report is None:
                report = await self.v("report_timing_summary")
            timing_info = parse_timing_summary_static(report)
            wns = timing_info["wns"]

        if wns is not None and wns > self.best_wns:
            self.best_wns = wns
        return wns

    async def _save_best_checkpoint(self, dcp_path: Path) -> Path:
        """Persist the current Vivado design and return the saved checkpoint path."""
        if not await self._save_vivado_checkpoint(dcp_path):
            raise RuntimeError(f"Failed to save checkpoint: {dcp_path}")
        return dcp_path

    async def _save_vivado_checkpoint(self, dcp_path: Path) -> bool:
        """Save the currently-open Vivado design as a branch checkpoint."""
        result = await self.v(
            "write_checkpoint",
            {
                "dcp_path": str(dcp_path.resolve()),
                "force": True,
                "timeout": 900,
            },
        )
        if "error" in result.lower() and "wrote checkpoint" not in result.lower():
            logger.warning("Failed to save branch checkpoint %s: %s", dcp_path, result[:500])
            return False
        return dcp_path.exists()

    async def _restore_candidate_state(self, candidate: SearchCandidate) -> None:
        """Restore a candidate checkpoint into Vivado and RapidWright."""
        print(f"\n[SEARCH] Restoring candidate {candidate.candidate_id} (WNS: {self._format_wns(candidate.wns)})")
        result = await self.v(
            "open_checkpoint",
            {
                "dcp_path": str(candidate.dcp_path.resolve()),
                "timeout": 900,
            },
        )
        if "error" in result.lower():
            raise RuntimeError(f"Could not restore Vivado checkpoint {candidate.dcp_path}: {result}")

        result = await self.rw("read_checkpoint", {"dcp_path": str(candidate.dcp_path.resolve())})
        if "error" in result.lower() and "success" not in result.lower():
            logger.warning(
                "RapidWright could not load restored candidate %s. Vivado-only branches can still continue. Result: %s",
                candidate.candidate_id,
                result[:500],
            )

    def _format_wns(self, wns: Optional[float]) -> str:
        """Format WNS for logs."""
        return f"{wns:.3f} ns" if wns is not None else "unknown"

    def _candidate_sort_key(self, candidate: SearchCandidate) -> tuple[tuple[float, float, float], float]:
        """Score candidates for beam pruning. Current leaf score is primary."""
        current = self._metrics_sort_key(
            {
                "wns": candidate.wns,
                "tns": candidate.tns,
                "failing_endpoints": candidate.failing_endpoints,
            }
        )
        peak = candidate.peak_wns if candidate.peak_wns is not None else float("-inf")
        return current, peak

    async def optimize(self, input_dcp: Path, output_dcp: Path) -> bool:
        """Run the optimization workflow."""
        self.start_time = time.time()

        try:
            initial_analysis = await self.perform_initial_analysis(input_dcp)
        except Exception as exc:
            logger.exception("Initial analysis failed: %s", exc)
            print(f"\n✗ Initial analysis failed: {exc}\n")
            self.end_time = time.time()
            return False

        if self.initial_wns is not None and self.initial_wns >= 0:
            print("✓ Design already meets timing! No optimization needed.\n")
            await self.v(
                "write_checkpoint",
                {
                    "dcp_path": str(output_dcp.resolve()),
                    "force": True,
                },
            )
            print(f"Saved design to: {output_dcp}\n")

            self.end_time = time.time()
            total_runtime = self.end_time - self.start_time

            print("\n=== No Optimization Required ===")
            initial_fmax = self.calculate_fmax(self.initial_wns, self.clock_period)
            if initial_fmax is not None:
                print(f"Design already meets timing - Fmax: {initial_fmax:.2f} MHz (WNS: {self.initial_wns:.3f} ns)")
            else:
                print(f"Design already meets timing (WNS: {self.initial_wns:.3f} ns)")
            print(f"Total runtime: {total_runtime:.2f} seconds ({total_runtime / 60:.2f} minutes)")
            print("LLM API calls: 0 (analysis performed without LLM)")
            print("Estimated cost: $0.00")
            print("=" * 70 + "\n")
            return True

        if self.generation_config.enabled:
            return await self._optimize_generational(input_dcp, output_dcp, initial_analysis)
        return await self._optimize_linear(input_dcp, output_dcp, initial_analysis)

    async def _optimize_linear(self, input_dcp: Path, output_dcp: Path, initial_analysis: str) -> bool:
        """Run the recipe-driven linear optimization workflow."""
        print("=== Starting LLM-Driven Optimization ===\n")

        best_wns = self.initial_wns
        best_metrics = {
            "wns": self.initial_wns,
            "tns": self.initial_tns,
            "failing_endpoints": self.initial_failing_endpoints,
        }
        stagnation = 0
        best_dcp_path = await self._save_best_checkpoint(Path(self.temp_dir) / "best_iter_000.dcp")
        last_best_iteration = 0

        max_iterations = self.generation_config.max_llm_calls

        for index in range(max_iterations):
            self.iteration += 1
            print(f"\n=== Iteration {index + 1} ===")

            if best_dcp_path.exists() and last_best_iteration != index:
                await self.v("open_checkpoint", {"dcp_path": str(best_dcp_path)})
                await self.rw("read_checkpoint", {"dcp_path": str(best_dcp_path)})

            decision_input = self._build_decision_input(
                initial_analysis,
                stagnation,
                self.history[-5:],
            )
            action = await self.choose_action_llm(decision_input)
            strategy, args = self.sanitize_action(action)
            print(f"Chosen: {strategy} with args {args}")
            previous_metrics = await self._measure_current_metrics()
            previous_wns = previous_metrics["wns"]

            try:
                result_report, current_wns = await self._execute_strategy(strategy, args)
            except Exception as exc:
                logger.exception("Error during linear iteration %s", index + 1)
                self.history.append(
                    {
                        "iteration": index + 1,
                        "strategy": strategy,
                        "args": args,
                        "wns": None,
                        "error": str(exc),
                        "stagnation_count": stagnation,
                    }
                )
                print(f"Iteration failed: {exc}")
                stagnation += 1

                if stagnation >= self.generation_config.max_steps_without_improvement:
                    print("No improvement. Stopping.")
                    break
                continue

            current_metrics = await self._measure_current_metrics(result_report)
            delta = current_wns - previous_wns if (current_wns is not None and previous_wns is not None) else None
            self.history.append(
                {
                    "iteration": index + 1,
                    "strategy": strategy,
                    "args": args,
                    "wns": current_wns,
                    "tns": current_metrics.get("tns"),
                    "failing_endpoints": current_metrics.get("failing_endpoints"),
                    "delta_wns": delta,
                    "previous_wns": previous_wns,
                    "delta_tns": (
                        current_metrics.get("tns") - previous_metrics["tns"]
                        if current_metrics.get("tns") is not None and previous_metrics["tns"] is not None
                        else None
                    ),
                    "delta_failing_endpoints": (
                        current_metrics.get("failing_endpoints") - previous_metrics["failing_endpoints"]
                        if current_metrics.get("failing_endpoints") is not None
                        and previous_metrics["failing_endpoints"] is not None
                        else None
                    ),
                    "stagnation_count": stagnation,
                }
            )

            print(f"WNS: {self._format_wns(current_wns)}")

            if self._is_metrics_improvement(current_metrics, best_metrics):
                best_wns = current_wns
                best_metrics = current_metrics
                stagnation = 0
                best_dcp_path = await self._save_best_checkpoint(
                    Path(self.temp_dir) / f"best_iter_{index + 1:03d}.dcp"
                )
                last_best_iteration = index + 1
            else:
                stagnation += 1

            if best_wns is not None and best_wns >= 0:
                print("Timing met.")
                break

            if stagnation >= self.generation_config.max_steps_without_improvement:
                print("No improvement. Stopping.")
                break

        shutil.copy2(best_dcp_path, output_dcp)

        self.end_time = time.time()
        self._print_optimization_summary(max_iterations_reached=False)
        return True

    async def _optimize_generational(self, input_dcp: Path, output_dcp: Path, initial_analysis: str) -> bool:
        """Run branch-and-generation search over recipe choices."""
        cfg = self.generation_config
        search_dir = self.run_dir / "generation_search"
        search_dir.mkdir(parents=True, exist_ok=True)

        print("=== Starting Generation Search Optimization ===")
        print(json.dumps(asdict(cfg), indent=2))

        root_path = search_dir / "root.dcp"
        if not await self._save_vivado_checkpoint(root_path):
            raise RuntimeError(f"Could not save root checkpoint: {root_path}")

        root = SearchCandidate(
            candidate_id="root",
            dcp_path=root_path,
            wns=self.initial_wns,
            tns=self.initial_tns,
            failing_endpoints=self.initial_failing_endpoints,
            peak_wns=self.initial_wns,
            generation=0,
            parent_id=None,
            branch_index=0,
            steps_taken=0,
            steps_since_peak=0,
            summary="Initial analyzed checkpoint",
        )
        self.search_candidates = [root]
        self.best_candidate = root
        active_candidates = [root]

        for generation in range(1, cfg.max_generations + 1):
            if self.llm_call_count >= cfg.max_llm_calls:
                print(f"[SEARCH] Reached max LLM calls ({cfg.max_llm_calls}); stopping search.")
                break

            print(f"\n{'=' * 70}")
            print(f"GENERATION {generation}/{cfg.max_generations}")
            print(f"{'=' * 70}")

            branch_results: list[SearchCandidate] = []
            tried_summaries = "\n".join(
                f"- {candidate.candidate_id}: WNS {self._format_wns(candidate.wns)}; {candidate.summary}"
                for candidate in self.search_candidates[-12:]
            )

            for parent in active_candidates:
                for branch_index in range(1, cfg.branch_factor + 1):
                    if self.llm_call_count >= cfg.max_llm_calls:
                        break

                    candidate = await self._run_generation_branch(
                        initial_analysis=initial_analysis,
                        search_dir=search_dir,
                        parent=parent,
                        generation=generation,
                        branch_index=branch_index,
                        tried_summaries=tried_summaries,
                    )
                    if candidate is None:
                        continue

                    branch_results.append(candidate)

                    candidate_metrics = {
                        "wns": candidate.wns,
                        "tns": candidate.tns,
                        "failing_endpoints": candidate.failing_endpoints,
                    }
                    best_metrics = (
                        {
                            "wns": self.best_candidate.wns,
                            "tns": self.best_candidate.tns,
                            "failing_endpoints": self.best_candidate.failing_endpoints,
                        }
                        if self.best_candidate
                        else None
                    )
                    if self._is_metrics_improvement(candidate_metrics, best_metrics):
                        self.best_candidate = candidate
                        print(f"[SEARCH] New global best: {candidate.candidate_id} ({self._format_wns(candidate.wns)})")

                    if cfg.stop_when_timing_met and candidate.wns is not None and candidate.wns >= 0:
                        print("[SEARCH] Timing met; stopping search because stop_when_timing_met is enabled.")
                        active_candidates = [candidate]
                        branch_results = [candidate]
                        break

                if cfg.stop_when_timing_met and self.best_candidate and self.best_candidate.wns is not None and self.best_candidate.wns >= 0:
                    break

            if not branch_results:
                print("[SEARCH] No viable branches produced this generation; stopping.")
                break

            expandable_results = [
                candidate for candidate in branch_results if candidate.steps_since_peak < cfg.max_steps_without_improvement
            ]
            if not expandable_results:
                print("[SEARCH] All branches reached patience from their peak; stopping.")
                break

            active_candidates = sorted(expandable_results, key=self._candidate_sort_key, reverse=True)[: cfg.beam_width]

            print("\n[SEARCH] Beam for next generation:")
            for candidate in active_candidates:
                print(
                    f"  - {candidate.candidate_id}: current {self._format_wns(candidate.wns)}, "
                    f"peak {self._format_wns(candidate.peak_wns)}, "
                    f"steps since peak {candidate.steps_since_peak}"
                )

            if cfg.stop_when_timing_met and self.best_candidate and self.best_candidate.wns is not None and self.best_candidate.wns >= 0:
                break

        if self.best_candidate is None:
            self.end_time = time.time()
            self._print_optimization_summary(max_iterations_reached=True)
            return False

        output_dcp.parent.mkdir(parents=True, exist_ok=True)
        if self.best_candidate.dcp_path.resolve() != output_dcp.resolve():
            shutil.copy2(self.best_candidate.dcp_path, output_dcp)
        self.best_wns = self.best_candidate.wns if self.best_candidate.wns is not None else self.best_wns
        self.end_time = time.time()

        print(f"\n[SEARCH] Best candidate: {self.best_candidate.candidate_id}")
        print(f"[SEARCH] Best WNS: {self._format_wns(self.best_candidate.wns)}")
        print(f"[SEARCH] Copied best checkpoint to: {output_dcp}")

        self._print_optimization_summary()
        return True

    async def _run_generation_branch(
        self,
        initial_analysis: str,
        search_dir: Path,
        parent: SearchCandidate,
        generation: int,
        branch_index: int,
        tried_summaries: str,
    ) -> Optional[SearchCandidate]:
        """Expand one branch from a parent candidate across recipe decisions."""
        cfg = self.generation_config
        branch_id = f"g{generation:02d}_p{parent.candidate_id}_b{branch_index:02d}"
        print(f"\n[SEARCH] Branch {branch_id} from {parent.candidate_id}")

        try:
            await self._restore_candidate_state(parent)
        except Exception as exc:
            logger.exception("Could not restore parent candidate %s", parent.candidate_id)
            print(f"[SEARCH] Skipping branch {branch_id}: restore failed: {exc}")
            return None

        peak_wns = parent.peak_wns
        peak_metrics = {
            "wns": parent.peak_wns,
            "tns": parent.tns,
            "failing_endpoints": parent.failing_endpoints,
        }
        current_wns = parent.wns
        steps_since_peak = parent.steps_since_peak
        latest_candidate = parent
        branch_history: list[dict] = []

        for step in range(1, cfg.max_steps_per_branch + 1):
            if self.llm_call_count >= cfg.max_llm_calls:
                break

            self.iteration += 1
            logger.info("=== Generation %s Branch %s Step %s ===", generation, branch_id, step)
            print(f"\n[SEARCH] {branch_id} step {step}/{cfg.max_steps_per_branch}")

            branch_context = (
                f"Branch id: {branch_id}\n"
                f"Parent candidate: {parent.candidate_id}\n"
                f"Parent current WNS: {self._format_wns(parent.wns)}\n"
                f"Parent peak WNS along this line: {self._format_wns(parent.peak_wns)}\n"
                "Use one recipe decision for this step, then let the controller score it."
            )
            decision_input = self._build_decision_input(
                initial_analysis,
                steps_since_peak,
                branch_history[-5:],
                branch_context=branch_context,
                tried_summaries=tried_summaries,
            )

            forced_action = self._forced_branch_strategy(generation, parent, branch_index, step)
            if forced_action is not None:
                strategy, args = forced_action
                print(f"[SEARCH] Forced diversity choice: {strategy} with args {args}")
            else:
                action = await self.choose_action_llm(decision_input)
                strategy, args = self.sanitize_action(action)
                print(f"[SEARCH] Chosen: {strategy} with args {args}")
            previous_wns = current_wns
            previous_metrics = {
                "wns": current_wns,
                "tns": latest_candidate.tns,
                "failing_endpoints": latest_candidate.failing_endpoints,
            }

            try:
                result_report, current_wns = await self._execute_strategy(strategy, args)
            except Exception as exc:
                logger.exception("Error during branch %s step %s", branch_id, step)
                branch_history.append(
                    {
                        "step": step,
                        "strategy": strategy,
                        "args": args,
                        "wns": None,
                        "error": str(exc),
                    }
                )
                steps_since_peak += 1
                continue

            current_metrics = await self._measure_current_metrics(result_report)
            branch_history.append(
                {
                    "step": step,
                    "strategy": strategy,
                    "args": args,
                    "wns": current_wns,
                    "tns": current_metrics.get("tns"),
                    "failing_endpoints": current_metrics.get("failing_endpoints"),
                    "delta_wns": (
                        current_wns - previous_wns if current_wns is not None and previous_wns is not None else None
                    ),
                    "previous_wns": previous_wns,
                    "delta_tns": (
                        current_metrics.get("tns") - previous_metrics["tns"]
                        if current_metrics.get("tns") is not None and previous_metrics["tns"] is not None
                        else None
                    ),
                    "delta_failing_endpoints": (
                        current_metrics.get("failing_endpoints") - previous_metrics["failing_endpoints"]
                        if current_metrics.get("failing_endpoints") is not None
                        and previous_metrics["failing_endpoints"] is not None
                        else None
                    ),
                    "delta_vs_parent": (
                        current_wns - parent.wns if current_wns is not None and parent.wns is not None else None
                    ),
                }
            )

            checkpoint_path = search_dir / f"{branch_id}_step{step:02d}.dcp"
            saved = await self._save_vivado_checkpoint(checkpoint_path)
            if not saved:
                print(f"[SEARCH] Branch {branch_id} step {step}: checkpoint save failed; stopping branch.")
                break

            if self._is_metrics_improvement(current_metrics, peak_metrics):
                peak_wns = current_wns
                peak_metrics = current_metrics
                steps_since_peak = 0
            else:
                steps_since_peak += 1

            latest_candidate = SearchCandidate(
                candidate_id=f"{branch_id}_s{step:02d}",
                dcp_path=checkpoint_path,
                wns=current_wns,
                tns=current_metrics.get("tns"),
                failing_endpoints=current_metrics.get("failing_endpoints"),
                peak_wns=peak_wns,
                generation=generation,
                parent_id=parent.candidate_id,
                branch_index=branch_index,
                steps_taken=step,
                steps_since_peak=steps_since_peak,
                summary=f"{strategy} {args}",
            )
            self.search_candidates.append(latest_candidate)

            print(
                f"[SEARCH] {latest_candidate.candidate_id}: current {self._format_wns(current_wns)}, "
                f"peak {self._format_wns(peak_wns)}, steps since peak {steps_since_peak}"
            )

            if self._is_metrics_improvement(
                current_metrics,
                (
                    {
                        "wns": self.best_candidate.wns,
                        "tns": self.best_candidate.tns,
                        "failing_endpoints": self.best_candidate.failing_endpoints,
                    }
                    if self.best_candidate
                    else None
                ),
            ):
                self.best_candidate = latest_candidate
                print(f"[SEARCH] New global best inside branch: {latest_candidate.candidate_id}")

            if cfg.stop_when_timing_met and current_wns is not None and current_wns >= 0:
                break

            if steps_since_peak >= cfg.max_steps_without_improvement:
                print(
                    f"[SEARCH] Stopping {branch_id}: no improvement over branch peak for "
                    f"{steps_since_peak} step(s)."
                )
                break

        return latest_candidate if latest_candidate is not parent else None

    def save_token_usage_report(self, output_path: Path):
        """Save detailed token usage report to JSON."""
        total_cached = sum(detail.get("cached_tokens", 0) for detail in self.api_call_details)
        total_reasoning = sum(detail.get("reasoning_tokens", 0) for detail in self.api_call_details)
        total_tool_time = sum(detail["elapsed_time"] for detail in self.tool_call_details)

        tool_counts: dict[str, int] = {}
        for detail in self.tool_call_details:
            tool_name = detail["tool_name"]
            tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

        total_runtime = None
        if self.start_time is not None:
            total_runtime = (self.end_time or time.time()) - self.start_time

        initial_fmax = self.calculate_fmax(self.initial_wns, self.clock_period)
        best_fmax = self.calculate_fmax(self.best_wns, self.clock_period) if self.best_wns > float("-inf") else None
        fmax_improvement = (best_fmax - initial_fmax) if (initial_fmax is not None and best_fmax is not None) else None

        report = {
            "model": self.model,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "generation_search": {
                "config": asdict(self.generation_config),
                "best_candidate_id": self.best_candidate.candidate_id if self.best_candidate else None,
                "candidates": [
                    {
                        "candidate_id": candidate.candidate_id,
                        "dcp_path": str(candidate.dcp_path),
                        "wns": candidate.wns,
                        "peak_wns": candidate.peak_wns,
                        "generation": candidate.generation,
                        "parent_id": candidate.parent_id,
                        "branch_index": candidate.branch_index,
                        "steps_taken": candidate.steps_taken,
                        "steps_since_peak": candidate.steps_since_peak,
                        "summary": candidate.summary,
                    }
                    for candidate in self.search_candidates
                ],
            },
            "summary": {
                "total_runtime_seconds": total_runtime,
                "total_llm_calls": self.llm_call_count,
                "total_iterations": self.iteration,
                "total_prompt_tokens": self.total_prompt_tokens,
                "total_completion_tokens": self.total_completion_tokens,
                "total_tokens": self.total_tokens,
                "total_cached_tokens": total_cached,
                "total_reasoning_tokens": total_reasoning,
                "total_cost": self.total_cost,
                "clock_period_ns": self.clock_period,
                "initial_wns": self.initial_wns,
                "best_wns": self.best_wns,
                "wns_improvement": self.best_wns - self.initial_wns if self.initial_wns is not None else None,
                "initial_fmax_mhz": initial_fmax,
                "best_fmax_mhz": best_fmax,
                "fmax_improvement_mhz": fmax_improvement,
                "total_tool_calls": len(self.tool_call_details),
                "total_tool_time_seconds": total_tool_time,
                "tool_call_counts": tool_counts,
            },
            "per_llm_call_details": self.api_call_details,
            "per_tool_call_details": self.tool_call_details,
        }

        with output_path.open("w") as handle:
            json.dump(report, handle, indent=2)

        logger.info("Token usage report saved to %s", output_path)

    def _print_optimization_summary(self, max_iterations_reached: bool = False):
        """Print a detailed optimization summary including token usage."""
        title = "Optimization Summary (Max Iterations Reached)" if max_iterations_reached else "Optimization Summary"
        print(f"\n{'=' * 70}")
        print(title)
        print(f"{'=' * 70}")

        if self.start_time is not None:
            total_runtime = (self.end_time or time.time()) - self.start_time
            print(f"\nTOTAL RUNTIME: {total_runtime:.2f} seconds ({total_runtime / 60:.2f} minutes)")

        best_wns = self.best_wns if self.best_wns > float("-inf") else None
        result_lines = self._format_fmax_results(self.clock_period, self.initial_wns, best_wns, result_label="Best")
        if result_lines:
            print("\nFMAX RESULTS:")
            print("\n".join(result_lines))

        print("\nITERATION STATS:")
        print(f"  Total iterations:    {self.iteration}")
        print(f"  LLM API calls:       {self.llm_call_count}")

        if self.generation_config.enabled:
            print("\nGENERATION SEARCH:")
            print(f"  Branches/parent:     {self.generation_config.branch_factor}")
            print(f"  Beam width:          {self.generation_config.beam_width}")
            print(f"  Max generations:     {self.generation_config.max_generations}")
            print(f"  Steps/branch:        {self.generation_config.max_steps_per_branch}")
            print(f"  Patience from peak:  {self.generation_config.max_steps_without_improvement}")
            print(f"  Candidates saved:    {len(self.search_candidates)}")
            if self.best_candidate:
                print(f"  Best candidate:      {self.best_candidate.candidate_id}")
                print(f"  Best checkpoint:     {self.best_candidate.dcp_path}")

        print("\nTOKEN USAGE:")
        print(f"  Prompt tokens:       {self.total_prompt_tokens:,}")
        print(f"  Completion tokens:   {self.total_completion_tokens:,}")
        print(f"  Total tokens:        {self.total_tokens:,}")

        total_cached = sum(detail.get("cached_tokens", 0) for detail in self.api_call_details)
        total_reasoning = sum(detail.get("reasoning_tokens", 0) for detail in self.api_call_details)

        if total_cached > 0:
            print(f"  Cached tokens:       {total_cached:,} (saved cost)")
        if total_reasoning > 0:
            print(f"  Reasoning tokens:    {total_reasoning:,}")

        print("\nCOST:")
        print(f"  Model:               {self.model}")
        if self.total_cost > 0:
            print(f"  Total cost:          ${self.total_cost:.4f}")
        else:
            print("  Total cost:          Not available")

        if self.tool_call_details:
            print("\nTOOL CALLS SUMMARY:")
            print(f"  Total tool calls:    {len(self.tool_call_details)}")
            total_tool_time = sum(detail["elapsed_time"] for detail in self.tool_call_details)
            print(f"  Total tool time:     {total_tool_time:.2f}s")

            tool_counts: dict[str, int] = {}
            for detail in self.tool_call_details:
                tool_name = detail["tool_name"]
                tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

            print("\n  Tool call breakdown:")
            for tool_name, count in sorted(tool_counts.items(), key=lambda item: -item[1]):
                print(f"    {tool_name}: {count}")

            print("\n  Detailed tool call log:")
            print(f"  {'#':<5} {'Iter':<6} {'Tool':<40} {'Time (s)':<12} {'WNS (ns)':<12} {'Status':<10}")
            print(f"  {'-' * 5} {'-' * 6} {'-' * 40} {'-' * 12} {'-' * 12} {'-' * 10}")
            for index, detail in enumerate(self.tool_call_details, start=1):
                tool_name = detail["tool_name"]
                iteration = detail.get("iteration", 0)
                elapsed = detail["elapsed_time"]
                wns = detail.get("wns")
                error = detail.get("error", False)
                wns_str = f"{wns:.3f}" if wns is not None else "-"
                status_str = "ERROR" if error else "OK"
                print(f"  {index:<5} {iteration:<6} {tool_name:<40} {elapsed:<12.2f} {wns_str:<12} {status_str:<10}")
                if error and "error_message" in detail:
                    print(f"        Error: {detail['error_message'][:80]}")

        if self.debug and self.api_call_details:
            print("\nPER-CALL BREAKDOWN:")
            has_cached = any(detail.get("cached_tokens", 0) > 0 for detail in self.api_call_details)
            has_reasoning = any(detail.get("reasoning_tokens", 0) > 0 for detail in self.api_call_details)
            has_cost = any(detail.get("cost", 0) > 0 for detail in self.api_call_details)

            header = f"  {'Call':<6} {'Iter':<6} {'Prompt':<10} {'Completion':<12}"
            if has_cached:
                header += f" {'Cached':<10}"
            if has_reasoning:
                header += f" {'Reasoning':<10}"
            header += f" {'Total':<10}"
            if has_cost:
                header += f" {'Cost':<12}"
            print(header)

            separator = f"  {'-' * 6} {'-' * 6} {'-' * 10} {'-' * 12}"
            if has_cached:
                separator += f" {'-' * 10}"
            if has_reasoning:
                separator += f" {'-' * 10}"
            separator += f" {'-' * 10}"
            if has_cost:
                separator += f" {'-' * 12}"
            print(separator)

            for detail in self.api_call_details:
                line = f"  {detail['call_number']:<6} {detail['iteration']:<6} {detail['prompt_tokens']:<10,} {detail['completion_tokens']:<12,}"
                if has_cached:
                    line += f" {detail.get('cached_tokens', 0):<10,}"
                if has_reasoning:
                    line += f" {detail.get('reasoning_tokens', 0):<10,}"
                line += f" {detail['total_tokens']:<10,}"
                if has_cost:
                    cost = detail.get("cost", 0)
                    line += f" ${cost:<11.4f}" if cost > 0 else f" {'N/A':<12}"
                print(line)

        print(f"\n{'=' * 70}\n")

        try:
            report_path = self.run_dir / "token_usage.json"
            self.save_token_usage_report(report_path)
            print(f"Detailed token usage report saved to: {report_path}\n")
        except Exception as exc:
            logger.warning("Failed to save token usage report: %s", exc)
