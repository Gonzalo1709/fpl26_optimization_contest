"""LLM-driven optimization mode for the FPGA optimizer."""

import asyncio
import hashlib
import json
import logging
import math
import re
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from openai import OpenAI

from src.analysis import DesignSignature, require_target_clock_wns
from src.base import DCPOptimizerBase
from src.parsers import parse_spread_analysis, parse_timing_summary_static, spread_recommends_pblock
from src.policy import (
    BudgetState,
    EligibleAction,
    gate_actions,
    plan_neutral_phys_opt_fallback,
    rank_fanout_candidates,
    select_route_preserve_nets,
)
from src.prompting import DEFAULT_SYSTEM_PROMPT_PATH, build_planner_system_prompt, prompt_sha256
from src.scoring import ContestScoreInput, ValidationStatus, calculate_contest_score
from src.search import GenerationSearchConfig, SearchCandidate, should_stop_fast_search

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "~openai/gpt-latest"
SUPPORTED_SINGLE_METHODS = ("PBLOCK", "FANOUT", "CELL_RELOCATE", "PHYS_OPT", "HARD_BLOCK")
PLANNER_MAX_TOKENS = 320
PLANNER_RETRY_MAX_TOKENS = 512


class ToolExecutionError(RuntimeError):
    """Raised when an MCP tool call fails or returns an error payload."""


class WallClockLimitReached(RuntimeError):
    """Raised when the optimizer reaches its configured wall-clock budget."""


class DCPOptimizer(DCPOptimizerBase):
    """FPGA Design Optimization Agent using recipe selection plus generation search."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        debug: bool = False,
        run_dir: Optional[Path] = None,
        generation_config: Optional[GenerationSearchConfig] = None,
        force_strategy: Optional[str] = None,
        system_prompt: Optional[str] = None,
        system_prompt_path: Optional[Path] = None,
    ):
        super().__init__(debug=debug, run_dir=run_dir)

        self.api_key = api_key
        self.model = model
        self.generation_config = generation_config or GenerationSearchConfig()
        self.system_prompt_path = system_prompt_path or DEFAULT_SYSTEM_PROMPT_PATH
        self.planner_system_prompt = build_planner_system_prompt(
            base_prompt=system_prompt,
            prompt_path=self.system_prompt_path,
        )
        self.system_prompt_hash = prompt_sha256(self.planner_system_prompt)
        self.system_prompt = self.planner_system_prompt
        self.force_strategy = force_strategy
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
        self.validation_status = ValidationStatus()
        self.design_signature: Optional[DesignSignature] = None

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

    @staticmethod
    def _get_finish_reason(response) -> Optional[str]:
        """Extract the finish reason from the first choice if present."""
        choices = getattr(response, "choices", None) or []
        if not choices:
            return None
        return getattr(choices[0], "finish_reason", None)

    @staticmethod
    def _extract_first_json_object(text: str) -> Optional[str]:
        """Extract the first top-level JSON object from free-form text."""
        start = text.find("{")
        if start < 0:
            return None

        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]

        return None

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

    def _remaining_wall_clock_seconds(self) -> Optional[float]:
        """Return remaining runtime budget in seconds, or None if unbounded."""
        if self.start_time is None:
            return None
        limit = self.generation_config.wall_clock_limit_seconds
        if limit <= 0:
            return None
        return limit - (time.time() - self.start_time)

    def _wall_clock_message(self, context: str = "") -> str:
        """Build a consistent wall-clock exhaustion message."""
        limit = self.generation_config.wall_clock_limit_seconds
        context_suffix = f" {context}" if context else ""
        return f"Wall-clock limit reached after {limit:.0f}s{context_suffix}."

    @staticmethod
    def _display_name(path: Path | str) -> str:
        """Render a filesystem path as just its filename for console summaries."""
        return Path(path).name

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        """Trim verbose text fields to a bounded size for planner prompts."""
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip() + "..."

    def _compact_analysis_summary(self, analysis_summary: str) -> str:
        """Keep only the most decision-relevant parts of the initial analysis."""
        kept_lines: list[str] = []
        high_fanout_count = 0
        for raw_line in analysis_summary.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                if kept_lines and kept_lines[-1] != "":
                    kept_lines.append("")
                continue
            if stripped.startswith("Clock period:") or stripped.startswith("WNS:") or stripped.startswith("TNS:"):
                kept_lines.append(line)
            elif stripped.startswith("Failing endpoints:") or stripped.startswith("Achievable fmax:"):
                kept_lines.append(line)
            elif stripped.startswith("Max cell distance:") or stripped.startswith("Avg cell distance:"):
                kept_lines.append(line)
            elif stripped.startswith("RECOMMENDATION:"):
                kept_lines.append(line)
            elif re.match(r"^\d+\.\s", stripped):
                if high_fanout_count < 3:
                    kept_lines.append(line)
                    high_fanout_count += 1
            elif stripped.startswith("Fanout:") and high_fanout_count <= 3:
                kept_lines.append(line)
            elif stripped.startswith("Total nets available for optimization:"):
                kept_lines.append(line)

        compact = "\n".join(kept_lines).strip()
        return self._truncate_text(compact or analysis_summary, 1400)

    def _compact_history(self, recent_history: list[dict]) -> list[dict]:
        """Reduce planner history to the fields needed for next-step choice."""
        compact_history: list[dict] = []
        for entry in recent_history[-4:]:
            compact_entry = {
                "iteration": entry.get("iteration") or entry.get("step"),
                "strategy": entry.get("strategy"),
                "wns": entry.get("wns"),
                "delta_wns": entry.get("delta_wns"),
                "error": self._truncate_text(str(entry["error"]), 120) if entry.get("error") else None,
            }
            args = entry.get("args")
            if args:
                compact_entry["args"] = args
            if entry.get("delta_vs_best") is not None:
                compact_entry["delta_vs_best"] = entry.get("delta_vs_best")
            compact_history.append({key: value for key, value in compact_entry.items() if value is not None})
        return compact_history

    def _compact_branch_context(self, branch_context: str) -> str:
        """Shorten branch context to a compact summary."""
        return self._truncate_text(branch_context.strip(), 260) if branch_context else ""

    def _compact_candidate_summaries(self, tried_summaries: str) -> str:
        """Keep only the most recent candidate summaries."""
        if not tried_summaries:
            return ""
        lines = [line for line in tried_summaries.splitlines() if line.strip()]
        return self._truncate_text("\n".join(lines[-6:]), 500)

    @staticmethod
    def _planner_user_message(decision_input: dict, retry: bool = False) -> str:
        """Build a compact planner prompt that strongly requests raw JSON only."""
        retry_line = (
            "Previous attempt was truncated or malformed. Reply with shorter JSON only.\n"
            if retry
            else ""
        )
        return (
            "Choose one optimization action.\n"
            "Return one JSON object only.\n"
            'Schema: {"strategy":"PBLOCK|FANOUT|CELL_RELOCATE|PHYS_OPT|HARD_BLOCK","args":{...}}\n'
            "Keep args minimal. No markdown or explanation.\n"
            f"{retry_line}"
            "Decision input:\n"
            f"{json.dumps(decision_input, separators=(',', ':'))}"
        )

    @staticmethod
    def _short_candidate_token(candidate_id: str) -> str:
        """Generate a short stable token for candidate IDs used in branch naming."""
        return hashlib.sha1(candidate_id.encode("utf-8")).hexdigest()[:8]

    def _raise_if_wall_clock_expired(self, context: str = "") -> None:
        """Stop search once the configured wall-clock budget has been exhausted."""
        remaining = self._remaining_wall_clock_seconds()
        if remaining is not None and remaining <= 0:
            raise WallClockLimitReached(self._wall_clock_message(context))

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
            if tool_name != "vivado_write_checkpoint":
                self._raise_if_wall_clock_expired(f"before {tool_name}")

            remaining = self._remaining_wall_clock_seconds()
            if remaining is not None and tool_name != "vivado_write_checkpoint":
                result = await asyncio.wait_for(session.call_tool(actual_name, arguments), timeout=max(0.1, remaining))
            else:
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
        except asyncio.TimeoutError as exc:
            elapsed_time = time.time() - start_time
            message = self._wall_clock_message(f"during {tool_name}")
            self.tool_call_details.append(
                {
                    "tool_name": tool_name,
                    "iteration": self.iteration,
                    "elapsed_time": elapsed_time,
                    "wns": None,
                    "error": True,
                    "error_message": message,
                }
            )
            logger.error("Tool call stopped by wall-clock limit: %s", message)
            raise WallClockLimitReached(message) from exc
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
        analysis_started = time.time()
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
        self.initial_wns = require_target_clock_wns(target_wns)
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
        spread_result = None
        critical_paths_report = None

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
            try:
                critical_paths_report = temp_path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("Could not read critical-path analysis file: %s", exc)
            spread_result = await self.call_tool(
                "rapidwright_analyze_critical_path_spread",
                {"input_file": str(temp_path)},
            )

            try:
                critical_path_spread_info = parse_spread_analysis(spread_result)
                if critical_path_spread_info is None:
                    raise ValueError("spread report was unavailable or malformed")
                print("✓ Critical path spread analyzed:")
                print(f"  - Max distance: {critical_path_spread_info['max_distance']} tiles")
                print(f"  - Avg distance: {critical_path_spread_info['avg_distance']:.1f} tiles")
                print(f"  - Paths analyzed: {critical_path_spread_info['paths_analyzed']}")
                print()
            except (KeyError, ValueError) as exc:
                print(f"⚠ Warning: Could not parse spread results: {exc}")

        congestion_report = None
        try:
            congestion_report = await self.call_tool(
                "vivado_run_tcl",
                {
                    "command": "report_design_analysis -congestion -return_string",
                    "timeout": 60,
                },
            )
        except Exception as exc:
            logger.warning("Optional congestion analysis unavailable: %s", exc)

        self.design_signature = DesignSignature.from_reports(
            target_clock=self.target_clock or "clk_fpl26contest",
            clock_period_ns=self.clock_period,
            wns_ns=self.initial_wns,
            tns_ns=self.initial_tns,
            failing_endpoints=self.initial_failing_endpoints,
            high_fanout_report=nets_report,
            spread_report=spread_result,
            analysis_duration_seconds=time.time() - analysis_started,
            critical_paths_report=critical_paths_report,
            congestion_report=congestion_report,
        )

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
            if spread_recommends_pblock(critical_path_spread_info):
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
        summary.append("")
        summary.append("DESIGN SIGNATURE:")
        summary.append(json.dumps(self.design_signature.to_dict(), sort_keys=True))

        summary_text = "\n".join(summary)
        print(summary_text)
        print()
        return summary_text

    async def choose_action_llm(self, decision_input: dict) -> dict:
        """Choose a recipe and its arguments using a single LLM call."""
        attempt_max_tokens = [PLANNER_MAX_TOKENS, PLANNER_RETRY_MAX_TOKENS]
        last_content = ""
        last_finish_reason = None

        for attempt_index, max_tokens in enumerate(attempt_max_tokens, start=1):
            response = self.openai.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.planner_system_prompt},
                    {"role": "user", "content": self._planner_user_message(decision_input, retry=attempt_index > 1)},
                ],
                max_tokens=max_tokens,
                temperature=0,
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
                        "attempt": attempt_index,
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
                retry_info = f", Attempt: {attempt_index}" if attempt_index > 1 else ""
                print(
                    f"[API Call #{self.llm_call_count}] Tokens: {total_tokens:,} "
                    f"(Prompt: {prompt_tokens:,}, Completion: {completion_tokens:,}{cache_info}{reasoning_info}{retry_info}){cost_info}"
                )

            content = self._extract_llm_text(response)
            finish_reason = self._get_finish_reason(response)
            last_content = content
            last_finish_reason = finish_reason

            if content:
                try:
                    return json.loads(content)
                except Exception:
                    json_text = self._extract_first_json_object(content)
                    if json_text:
                        try:
                            return json.loads(json_text)
                        except Exception:
                            pass

                logger.warning(
                    "Could not parse planner JSON on attempt %s (finish_reason=%s). Raw content: %s",
                    attempt_index,
                    finish_reason,
                    content,
                )
            else:
                logger.warning(
                    "Planner returned no text on attempt %s (finish_reason=%s).",
                    attempt_index,
                    finish_reason,
                )

            if finish_reason != "length" and attempt_index == 1:
                break

            if attempt_index < len(attempt_max_tokens):
                logger.warning(
                    "Retrying planner with a larger output budget after attempt %s (finish_reason=%s).",
                    attempt_index,
                    finish_reason,
                )

        logger.warning(
            "Planner could not produce valid JSON after retries (last_finish_reason=%s). Falling back to PHYS_OPT. Raw content: %s",
            last_finish_reason,
            last_content,
        )
        return {"strategy": "PHYS_OPT", "args": {"directive": "Default"}}

    def _sanitize_action_shape(self, action: dict) -> tuple[str, dict]:
        """Normalize the shape and bounded arguments of one proposed action."""
        strategy = action.get("strategy", "PHYS_OPT")
        args = action.get("args", {})
        if not isinstance(args, dict):
            args = {}

        if strategy == "FANOUT":
            top_n = int(args.get("top_n_nets", 5))
            top_n = max(1, min(10, top_n))
            return strategy, {"top_n_nets": top_n}

        if strategy == "CELL_RELOCATE":
            try:
                num_paths = int(args.get("num_paths", 10))
            except (TypeError, ValueError):
                num_paths = 10
            num_paths = max(3, min(20, num_paths))

            try:
                detour_threshold = float(args.get("detour_threshold", 2.0))
            except (TypeError, ValueError):
                detour_threshold = 2.0
            detour_threshold = max(1.2, min(4.0, detour_threshold))

            try:
                max_cells = int(args.get("max_cells", 3))
            except (TypeError, ValueError):
                max_cells = 3
            max_cells = max(1, min(5, max_cells))

            try:
                max_move_distance = int(args.get("max_move_distance", 30))
            except (TypeError, ValueError):
                max_move_distance = 30
            max_move_distance = max(5, min(80, max_move_distance))

            return strategy, {
                "num_paths": num_paths,
                "detour_threshold": detour_threshold,
                "max_cells": max_cells,
                "max_move_distance": max_move_distance,
            }

        if strategy == "PHYS_OPT":
            directive = args.get("directive", "RuntimeOptimized")
            if directive not in [
                "RuntimeOptimized",
                "CriticalPin",
                "PlacementRouting",
                "Default",
                "Explore",
                "AggressiveExplore",
            ]:
                directive = "RuntimeOptimized"
            return strategy, {"directive": directive}

        if strategy == "CRITICAL_PIN":
            return strategy, {}

        if strategy == "ROUTE_PRESERVE":
            try:
                max_nets = int(args.get("max_nets", 4))
            except (TypeError, ValueError):
                max_nets = 4
            max_nets = max(1, min(8, max_nets))
            try:
                min_net_delay_ns = float(args.get("min_net_delay_ns", 0.2))
            except (TypeError, ValueError):
                min_net_delay_ns = 0.2
            min_net_delay_ns = max(0.05, min(2.0, min_net_delay_ns))
            return strategy, {
                "max_nets": max_nets,
                "min_net_delay_ns": min_net_delay_ns,
            }

        if strategy == "HARD_BLOCK":
            hard_block_types = args.get("hard_block_types") or ["DSP", "BRAM", "URAM"]
            if isinstance(hard_block_types, str):
                hard_block_types = [hard_block_types]
            return strategy, {"hard_block_types": [str(item) for item in hard_block_types]}

        if strategy == "PBLOCK":
            return strategy, {}

        if strategy == "NO_OP":
            return strategy, {}

        return "PHYS_OPT", {"directive": "RuntimeOptimized"}

    def _current_budget_state(self) -> BudgetState:
        """Translate configured run limits into the recipe policy budget model."""
        remaining_runtime = math.inf
        if self.start_time is not None:
            elapsed_seconds = time.time() - self.start_time
            configured_limits = []
            if self.generation_config.max_runtime_minutes is not None:
                configured_limits.append(self.generation_config.max_runtime_minutes * 60.0)
            if self.generation_config.wall_clock_limit_seconds > 0:
                configured_limits.append(self.generation_config.wall_clock_limit_seconds)
            if configured_limits:
                remaining_runtime = min(configured_limits) - elapsed_seconds

        remaining_cost = math.inf
        if self.generation_config.max_cost is not None:
            remaining_cost = self.generation_config.max_cost - self.total_cost

        return BudgetState(
            remaining_runtime_seconds=remaining_runtime,
            remaining_cost_usd=remaining_cost,
        )

    def _eligible_actions(self) -> tuple[EligibleAction, ...]:
        """Return the single authoritative allow-list for the current state."""
        if self.design_signature is None:
            return (
                EligibleAction(
                    strategy="PHYS_OPT",
                    default_args={"directive": "RuntimeOptimized"},
                    allowed_args={"directive": ["RuntimeOptimized"]},
                    reason="design signature is unavailable; use the conservative fallback",
                ),
            )
        actions = gate_actions(
            self.design_signature,
            budget=self._current_budget_state(),
            history=self.history,
            validation=self.validation_status,
        )
        if self.fanout_blacklist:
            available_fanout_names = {
                candidate.net_name
                for candidate in self.design_signature.high_fanout_candidates
                if candidate.net_name not in self.fanout_blacklist
            }
            if not available_fanout_names:
                actions = tuple(action for action in actions if action.strategy != "FANOUT")
        return actions

    def sanitize_action(self, action: dict) -> tuple[str, dict]:
        """Normalize a proposed action and enforce deterministic eligibility gates."""
        strategy, args = self._sanitize_action_shape(action)
        eligible = {item.strategy: item for item in self._eligible_actions()}
        if strategy not in eligible:
            fallback = next(iter(eligible.values()))
            logger.info(
                "Rejected ineligible strategy %s; using %s (%s)",
                strategy,
                fallback.strategy,
                fallback.reason,
            )
            return self._sanitize_action_shape(
                {"strategy": fallback.strategy, "args": fallback.default_args}
            )

        if strategy == "HARD_BLOCK":
            allowed_types = set(eligible[strategy].default_args.get("hard_block_types", []))
            requested_types = [item for item in args["hard_block_types"] if item in allowed_types]
            args["hard_block_types"] = requested_types or sorted(allowed_types)
        elif strategy == "PHYS_OPT":
            allowed_directives = eligible[strategy].allowed_args.get("directive", [])
            if args["directive"] not in allowed_directives:
                args = dict(eligible[strategy].default_args)
        return strategy, args

    def _canonicalize_action_args(self, strategy: str, args: dict) -> dict:
        """Normalize strategy args so equivalent choices map to one signature."""
        normalized = dict(args)
        if strategy == "HARD_BLOCK" and "hard_block_types" in normalized:
            types = normalized.get("hard_block_types") or []
            normalized["hard_block_types"] = sorted(str(item) for item in types)
        return normalized

    def _action_signature(self, strategy: str, args: dict) -> str:
        """Create a stable signature for deduplicating recipe choices."""
        normalized_args = self._canonicalize_action_args(strategy, args)
        return json.dumps({"strategy": strategy, "args": normalized_args}, sort_keys=True)

    def _fallback_action_candidates(self, preferred_strategy: str, preferred_args: dict) -> list[tuple[str, dict]]:
        """Return a small ordered list of alternative actions to avoid branch-local repeats."""
        candidates = [(preferred_strategy, preferred_args)]
        for eligible in self._eligible_actions():
            candidates.append((eligible.strategy, eligible.default_args))
            if eligible.strategy == "FANOUT":
                candidates.extend([("FANOUT", {"top_n_nets": 3}), ("FANOUT", {"top_n_nets": 5})])
            elif eligible.strategy == "PHYS_OPT":
                candidates.extend(
                    ("PHYS_OPT", {"directive": directive})
                    for directive in eligible.allowed_args.get("directive", [])
                )

        seen: set[str] = set()
        ordered: list[tuple[str, dict]] = []
        for strategy, args in candidates:
            sanitized_strategy, sanitized_args = self.sanitize_action({"strategy": strategy, "args": args})
            signature = self._action_signature(sanitized_strategy, sanitized_args)
            if signature in seen:
                continue
            seen.add(signature)
            ordered.append((sanitized_strategy, sanitized_args))
        return ordered

    def _fanout_candidates_available(self) -> bool:
        """Return True when at least one non-blacklisted fanout net is currently available."""
        return any(net_name not in self.fanout_blacklist for net_name, _, _ in self.high_fanout_nets)

    def _dedupe_action_choice(
        self,
        strategy: str,
        args: dict,
        used_signatures: set[str],
    ) -> tuple[str, dict, bool]:
        """Swap repeated actions for an unused fallback when possible."""
        signature = self._action_signature(strategy, args)
        if signature not in used_signatures:
            return strategy, args, False

        for candidate_strategy, candidate_args in self._fallback_action_candidates(strategy, args):
            candidate_signature = self._action_signature(candidate_strategy, candidate_args)
            if candidate_signature not in used_signatures:
                return candidate_strategy, candidate_args, True

        return strategy, args, False

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

        # Keep all improvement comparisons aligned to the same WNS source used by
        # branch scoring/logging: prefer the target clock's WNS when available.
        target_wns = await super().get_wns_for_target_clock(self._call_vivado_tool)
        if target_wns is not None:
            metrics["wns"] = target_wns

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
        if self.generation_config.strategy_effort == "fast" or self.generation_config.branch_factor < 2:
            return None
        if generation != 1 or parent.candidate_id != "root" or step != 1:
            return None

        eligible = {action.strategy: action for action in self._eligible_actions()}
        preferred_order = ("FANOUT", "PBLOCK", "CELL_RELOCATE", "HARD_BLOCK", "PHYS_OPT")
        forced_strategies = []
        for strategy in preferred_order:
            if strategy not in eligible:
                continue
            args = eligible[strategy].default_args
            if strategy == "FANOUT":
                args = {"top_n_nets": 3}
            forced_strategies.append((strategy, args))
        if not forced_strategies:
            return None
        strategy_index = min(branch_index - 1, len(forced_strategies) - 1)
        strategy, args = forced_strategies[strategy_index]
        return self.sanitize_action({"strategy": strategy, "args": args})

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

        attempt_plans_by_effort = {
            "fast": [
                {"suffix": "fast", "is_soft": False, "place_directive": "Quick", "phys_opt_directive": None},
            ],
            "balanced": [
                {"suffix": "soft", "is_soft": True, "place_directive": "Default", "phys_opt_directive": "Default"},
                {"suffix": "balanced", "is_soft": False, "place_directive": "Explore", "phys_opt_directive": "Explore"},
                {
                    "suffix": "aggressive",
                    "is_soft": False,
                    "place_directive": "Quick",
                    "phys_opt_directive": "AggressiveExplore",
                },
            ],
            "thorough": [
                {"suffix": "soft", "is_soft": True, "place_directive": "Default", "phys_opt_directive": "Default"},
                {"suffix": "balanced", "is_soft": False, "place_directive": "Explore", "phys_opt_directive": "Explore"},
                {
                    "suffix": "aggressive",
                    "is_soft": False,
                    "place_directive": "Quick",
                    "phys_opt_directive": "AggressiveExplore",
                },
                {
                    "suffix": "default_hard",
                    "is_soft": False,
                    "place_directive": "Default",
                    "phys_opt_directive": "AggressiveExplore",
                },
            ],
        }
        attempt_plans = attempt_plans_by_effort.get(self.generation_config.strategy_effort, attempt_plans_by_effort["balanced"])

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
            if plan["phys_opt_directive"]:
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
        if self.generation_config.strategy_effort == "fast":
            top_n_nets = min(top_n_nets, 1)
        elif self.generation_config.strategy_effort == "balanced":
            top_n_nets = min(top_n_nets, 5)

        nets_report = ""
        self.high_fanout_nets = []
        nets_report = await self.v(
            "get_critical_high_fanout_nets",
            {"num_paths": 50, "min_fanout": 100, "exclude_clocks": True},
        )
        self.high_fanout_nets = self.parse_high_fanout_nets(nets_report)

        geography_by_name = {}
        if self.high_fanout_nets:
            geography_report = await self.rw(
                "analyze_fanout_geography",
                {"net_names": [net_name for net_name, _, _ in self.high_fanout_nets]},
            )
            try:
                geography_payload = json.loads(geography_report)
                geography_by_name = {
                    item["net_name"]: item
                    for item in geography_payload.get("nets", [])
                    if "net_name" in item
                }
            except (TypeError, json.JSONDecodeError):
                logger.warning("Could not parse fanout geography; using timing evidence only")

        ranked_evidence = rank_fanout_candidates(
            [
                {
                    "net_name": net_name,
                    "fanout": fanout,
                    "critical_path_count": path_count,
                    "is_clock": geography_by_name.get(net_name, {}).get("is_clock", False),
                    "sink_span": geography_by_name.get(net_name, {}).get("sink_span", 0),
                }
                for net_name, fanout, path_count in self.high_fanout_nets
            ],
            blacklist=self.fanout_blacklist,
        )
        nets_to_optimize = [
            (
                item["net_name"],
                int(item["fanout"]),
                int(item["critical_path_count"]),
            )
            for item in ranked_evidence[:top_n_nets]
        ]
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
                if self.generation_config.strategy_effort == "fast":
                    break
            else:
                await self.v("open_checkpoint", {"dcp_path": str(baseline_checkpoint.resolve())})

        return best_report

    async def run_cell_relocation_flow(
        self,
        num_paths: int = 10,
        detour_threshold: float = 2.0,
        max_cells: int = 3,
        max_move_distance: int = 30,
    ) -> str:
        """Relocate detour-heavy cells identified on critical paths."""
        baseline_checkpoint = Path(self.temp_dir) / f"cell_relocate_before_{self.iteration}.dcp"
        await self.v(
            "write_checkpoint",
            {"dcp_path": str(baseline_checkpoint.resolve()), "force": True},
        )
        baseline_report = await self.v("report_timing_summary")
        baseline_metrics = await self._measure_current_metrics(baseline_report)
        pins_file = Path(self.temp_dir) / f"critical_path_pins_iter_{self.iteration}.json"

        await self.v(
            "extract_critical_path_pins",
            {
                "num_paths": num_paths,
                "output_file": str(pins_file),
            },
        )

        detour_report = await self.rw(
            "analyze_net_detour",
            {
                "input_file": str(pins_file),
                "detour_threshold": detour_threshold,
            },
        )
        detour_data = json.loads(detour_report)
        if "error" in detour_data:
            raise RuntimeError(f"analyze_net_detour failed: {detour_data['error']}")

        candidates = detour_data.get("candidates", [])
        if not candidates:
            print("No detour-heavy critical cells found; measuring without relocation.")
            return baseline_report

        prioritized_candidates = sorted(
            candidates,
            key=lambda candidate: (
                candidate.get("path", float("inf")),
                -float(candidate.get("max_detour_ratio", 0.0)),
            ),
        )

        prioritized_cells: list[str] = []
        seen_cells: set[str] = set()
        for candidate in prioritized_candidates:
            cell_name = str(candidate.get("cell", "")).strip()
            if not cell_name or cell_name in seen_cells:
                continue
            prioritized_cells.append(cell_name)
            seen_cells.add(cell_name)
            if len(prioritized_cells) >= max_cells:
                break

        if not prioritized_cells:
            print("Detour analysis returned candidates, but no valid cells were selected.")
            return baseline_report

        print("Relocating detour-heavy cells: " + ", ".join(prioritized_cells))
        relocation_report = await self.rw(
            "optimize_cell_placement",
            {
                "cell_names": prioritized_cells,
                "max_candidates": max_cells,
                "max_move_distance": max_move_distance,
            },
        )
        relocation_data = json.loads(relocation_report)
        if "error" in relocation_data:
            raise RuntimeError(f"optimize_cell_placement failed: {relocation_data['error']}")

        for cell_result in relocation_data.get("results", []):
            print(
                f"  {cell_result.get('cell')}: "
                f"{cell_result.get('status')} - {cell_result.get('message')}"
            )

        temp_dcp = Path(self.temp_dir) / f"cell_relocate_iter_{self.iteration}.dcp"
        await self.rw("write_checkpoint", {"dcp_path": str(temp_dcp.resolve())})

        await self.v("open_checkpoint", {"dcp_path": str(temp_dcp.resolve())})
        report, _ = await self._reroute_and_measure()
        current_metrics = await self._measure_current_metrics(report)
        if self._is_metrics_improvement(current_metrics, baseline_metrics):
            return report

        await self.v("open_checkpoint", {"dcp_path": str(baseline_checkpoint.resolve())})
        return baseline_report

    async def run_phys_opt_flow(self, directive: str = "RuntimeOptimized") -> str:
        """Execute one independently measured phys-opt portfolio attempt."""
        baseline_checkpoint = Path(self.temp_dir) / "phys_opt_baseline.dcp"
        await self.v("write_checkpoint", {"dcp_path": str(baseline_checkpoint.resolve()), "force": True})
        baseline_report = await self.v("report_timing_summary")
        baseline_metrics = await self._measure_current_metrics(baseline_report)

        tool_args_by_mode = {
            "RuntimeOptimized": {"directive": "RuntimeOptimized"},
            "CriticalPin": {"critical_pin_opt": True},
            "PlacementRouting": {"placement_opt": True, "routing_opt": True},
            "Default": {"directive": "Default"},
            "Explore": {"directive": "Explore"},
            "AggressiveExplore": {"directive": "AggressiveExplore"},
        }
        tool_args = tool_args_by_mode.get(directive, tool_args_by_mode["RuntimeOptimized"])
        await self.v("phys_opt_design", tool_args)
        report = await self.v("report_timing_summary")
        current_metrics = await self._measure_current_metrics(report)

        if self._is_metrics_improvement(current_metrics, baseline_metrics):
            return report

        await self.v("open_checkpoint", {"dcp_path": str(baseline_checkpoint.resolve())})
        return baseline_report

    async def run_critical_pin_flow(self) -> str:
        """Run only Vivado's target-timing critical pin-swapping optimization."""
        return await self.run_phys_opt_flow(directive="CriticalPin")

    async def run_route_preserve_flow(
        self,
        max_nets: int = 4,
        min_net_delay_ns: float = 0.2,
    ) -> str:
        """Reroute a bounded critical-net set, then preserve it while routing."""
        baseline_checkpoint = Path(self.temp_dir) / "route_preserve_baseline.dcp"
        await self.v(
            "write_checkpoint",
            {"dcp_path": str(baseline_checkpoint.resolve()), "force": True},
        )
        baseline_report = await self.v("report_timing_summary")
        baseline_metrics = await self._measure_current_metrics(baseline_report)

        evidence_report = await self.v(
            "extract_critical_route_nets",
            {"num_paths": 20, "max_nets": 8},
        )
        try:
            evidence = json.loads(evidence_report)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Could not parse critical route-net evidence") from exc
        if isinstance(evidence, dict) and evidence.get("error"):
            raise RuntimeError(evidence["error"])
        if not isinstance(evidence, list):
            raise RuntimeError("Critical route-net evidence was not a list")

        net_names = select_route_preserve_nets(
            evidence,
            max_nets=max_nets,
            min_net_delay_ns=min_net_delay_ns,
        )
        if not net_names:
            logger.info("No unlocked target-clock nets met the preserved-reroute evidence gate.")
            return baseline_report

        await self.v(
            "route_design",
            {"nets": list(net_names), "auto_delay": True},
        )
        await self.v("route_design", {"preserve": True})
        report = await self.v("report_timing_summary")
        current_metrics = await self._measure_current_metrics(report)
        if self._is_metrics_improvement(current_metrics, baseline_metrics):
            return report

        await self.v("open_checkpoint", {"dcp_path": str(baseline_checkpoint.resolve())})
        return baseline_report

    async def run_hard_block_flow(
        self,
        hard_block_types: Optional[list[str]] = None,
        min_score_improvement: float = 5.0,
        validate_in_vivado: bool = True,
    ) -> str:
        """Execute the hard-block column/cascade relocation recipe once."""
        baseline_checkpoint = Path(self.temp_dir) / "hard_block_baseline.dcp"
        await self.v("write_checkpoint", {"dcp_path": str(baseline_checkpoint.resolve()), "force": True})
        baseline_report = await self.v("report_timing_summary")
        baseline_metrics = await self._measure_current_metrics(baseline_report)

        await self._reload_rapidwright_from_vivado_checkpoint(baseline_checkpoint)
        result = await self.rw(
            "hard_block_column_cascade_relocation",
            {
                "hard_block_types": hard_block_types or ["DSP", "BRAM", "URAM"],
                "min_score_improvement": min_score_improvement,
                "dry_run": False,
            },
        )

        relocation_data = json.loads(result)
        if relocation_data.get("error"):
            raise RuntimeError(relocation_data["error"])

        if relocation_data.get("status") == "no_improvement":
            logger.info("Hard-block flow found no improving legal move; keeping baseline placement.")
            await self.v("open_checkpoint", {"dcp_path": str(baseline_checkpoint.resolve())})
            return baseline_report

        temp_dcp = Path(self.temp_dir) / "hard_block_opt.dcp"
        await self.rw(
            "write_checkpoint",
            {
                "dcp_path": str(temp_dcp.resolve()),
                "overwrite": True,
            },
        )

        await self.v("open_checkpoint", {"dcp_path": str(temp_dcp.resolve())})
        if validate_in_vivado:
            validation_ok, validation_summary = await self._validate_hard_block_candidate_in_vivado()
            if not validation_ok:
                logger.warning("Rejecting hard-block candidate after Vivado validation: %s", validation_summary)
                await self.v("open_checkpoint", {"dcp_path": str(baseline_checkpoint.resolve())})
                return baseline_report
        report, _ = await self._reroute_and_measure()
        current_metrics = await self._measure_current_metrics(report)

        if self._is_metrics_improvement(current_metrics, baseline_metrics):
            return report

        await self.v("open_checkpoint", {"dcp_path": str(baseline_checkpoint.resolve())})
        return baseline_report

    async def _validate_hard_block_candidate_in_vivado(self) -> tuple[bool, dict]:
        """Run lightweight Vivado checks before accepting a hard-block candidate."""
        validation = {
            "open_clean": True,
            "unplaced_cells": None,
            "route_status_excerpt": "",
            "drc_excerpt": "",
            "log_keywords_found": [],
        }

        unplaced_result = await self.v(
            "run_tcl",
            {
                "command": (
                    "set unplaced [get_cells -quiet -filter {IS_PRIMITIVE && IS_LOC_FIXED == 0 && LOC == \"\"}]; "
                    "puts [llength $unplaced]"
                )
            },
        )
        try:
            validation["unplaced_cells"] = int(unplaced_result.strip().splitlines()[-1])
        except Exception:
            validation["unplaced_cells"] = None

        route_status = await self.v("report_route_status", {})
        validation["route_status_excerpt"] = route_status[:2000]

        drc_result = await self.v(
            "run_tcl",
            {
                "command": "report_drc -return_string"
            },
        )
        validation["drc_excerpt"] = drc_result[:2000]

        vivado_log = self.run_dir / "vivado.log"
        if vivado_log.exists():
            log_text = vivado_log.read_text(errors="ignore")
            for needle in [
                "failed to restore",
                "partially restored",
                "unplaced non vcc/gnd instance",
                "design is not fully placed",
            ]:
                if needle.lower() in log_text.lower():
                    validation["log_keywords_found"].append(needle)

        failed_nets_match = re.search(r"Number of Failed Nets\s*=\s*(\d+)", route_status)
        unrouted_match = re.search(r"Number of Unrouted Nets\s*=\s*(\d+)", route_status)
        partial_match = re.search(r"Number of Partially Routed Nets\s*=\s*(\d+)", route_status)
        failed_nets = int(failed_nets_match.group(1)) if failed_nets_match else 0
        unrouted_nets = int(unrouted_match.group(1)) if unrouted_match else 0
        partial_nets = int(partial_match.group(1)) if partial_match else 0
        route_status_has_errors = failed_nets > 0 or unrouted_nets > 0 or partial_nets > 0

        validation_ok = (
            (validation["unplaced_cells"] in (0, None))
            and not validation["log_keywords_found"]
            and not route_status_has_errors
        )
        return validation_ok, validation

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
        if strategy == "NO_OP":
            result = await self.v("report_timing_summary")
        elif strategy == "PBLOCK":
            result = await self.run_pblock_flow()
        elif strategy == "FANOUT":
            result = await self.run_fanout_flow(**args)
        elif strategy == "CELL_RELOCATE":
            result = await self.run_cell_relocation_flow(**args)
        elif strategy == "HARD_BLOCK":
            result = await self.run_hard_block_flow(**args)
        elif strategy == "CRITICAL_PIN":
            result = await self.run_critical_pin_flow()
        elif strategy == "ROUTE_PRESERVE":
            result = await self.run_route_preserve_flow(**args)
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
        eligible_actions = self._eligible_actions()
        schemas = {
            "PBLOCK": {},
            "FANOUT": {"top_n_nets": "int (1-10)"},
            "CELL_RELOCATE": {
                "num_paths": "int (3-20)",
                "detour_threshold": "float (1.2-4.0)",
                "max_cells": "int (1-5)",
                "max_move_distance": "int (5-80 tiles)",
            },
            "PHYS_OPT": {"directive": ["RuntimeOptimized"]},
            "HARD_BLOCK": {"hard_block_types": ["DSP", "BRAM", "URAM"]},
            "CRITICAL_PIN": {},
            "ROUTE_PRESERVE": {
                "max_nets": "int (1-8)",
                "min_net_delay_ns": "float (0.05-2.0)",
            },
            "NO_OP": {},
        }
        available_strategies = {}
        for action in eligible_actions:
            schema = dict(schemas[action.strategy])
            if action.strategy == "HARD_BLOCK":
                schema["hard_block_types"] = action.default_args["hard_block_types"]
            elif action.strategy == "PHYS_OPT":
                schema["directive"] = action.allowed_args["directive"]
            available_strategies[action.strategy] = schema
        return {
            "analysis": self._compact_analysis_summary(analysis_summary),
            "design_signature": self.design_signature.to_dict() if self.design_signature else None,
            "history": self._compact_history(recent_history),
            "best_wns": self.best_wns,
            "stagnation": stagnation,
            "branch_context": self._compact_branch_context(branch_context),
            "recent_candidates": self._compact_candidate_summaries(tried_summaries),
            "fanout_blacklist": {
                "count": len(self.fanout_blacklist),
                "examples": list(self.fanout_blacklist.keys())[:3],
            },
            "search_settings": {
                "branch_factor": self.generation_config.branch_factor,
                "beam_width": self.generation_config.beam_width,
                "max_generations": self.generation_config.max_generations,
                "max_steps_per_branch": self.generation_config.max_steps_per_branch,
                "max_steps_without_improvement": self.generation_config.max_steps_without_improvement,
            },
            "available_strategies": available_strategies,
            "eligibility_reasons": {
                action.strategy: action.reason for action in eligible_actions
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

    def _candidate_score_metadata(
        self,
        wns: Optional[float],
        validation: Optional[ValidationStatus] = None,
    ) -> dict:
        """Calculate cumulative score metadata for a saved candidate."""
        elapsed_seconds = (
            max(0.0, time.time() - self.start_time)
            if self.start_time is not None
            else 0.0
        )
        initial_fmax = self.calculate_fmax(self.initial_wns, self.clock_period)
        candidate_fmax = self.calculate_fmax(wns, self.clock_period)
        delta_fmax = (
            candidate_fmax - initial_fmax
            if candidate_fmax is not None and initial_fmax is not None
            else 0.0
        )
        status = validation or ValidationStatus()
        score = calculate_contest_score(
            ContestScoreInput(
                delta_fmax_mhz=delta_fmax,
                llm_cost_usd=self.total_cost,
                runtime_seconds=elapsed_seconds,
                validation=status,
            )
        )
        return {
            "elapsed_seconds": elapsed_seconds,
            "llm_cost_usd": self.total_cost,
            "projected_score": score.projected_score,
            "validation": status,
            "validated_score": score.validated_score,
        }

    @staticmethod
    def _candidate_validation_rank(candidate: SearchCandidate) -> int:
        """Order passed, speculative, and failed candidates conservatively."""
        if candidate.validation.passed:
            return 2
        if candidate.validation.complete:
            return 0
        return 1

    def _candidate_sort_key(
        self, candidate: SearchCandidate
    ) -> tuple[int, float, tuple[float, float, float], float, float, float]:
        """Rank candidates by validation and contest score, then timing and cost."""
        current = self._metrics_sort_key(
            {
                "wns": candidate.wns,
                "tns": candidate.tns,
                "failing_endpoints": candidate.failing_endpoints,
            }
        )
        peak = candidate.peak_wns if candidate.peak_wns is not None else float("-inf")
        effective_score = (
            candidate.validated_score
            if candidate.validated_score is not None
            else candidate.projected_score
        )
        return (
            self._candidate_validation_rank(candidate),
            effective_score,
            current,
            peak,
            -candidate.elapsed_seconds,
            -candidate.llm_cost_usd,
        )

    def _is_candidate_improvement(
        self,
        candidate: SearchCandidate,
        incumbent: Optional[SearchCandidate],
    ) -> bool:
        """Return whether one candidate clears the score-aware promotion gate."""
        return incumbent is None or self._candidate_sort_key(candidate) > self._candidate_sort_key(incumbent)

    def _budget_stop_reason(self) -> Optional[str]:
        """Return a human-readable stop reason when configured budgets are exhausted."""
        cfg = self.generation_config
        if cfg.max_runtime_minutes is not None and self.start_time is not None:
            elapsed_minutes = (time.time() - self.start_time) / 60.0
            if elapsed_minutes >= cfg.max_runtime_minutes:
                return f"runtime budget reached ({elapsed_minutes:.1f}/{cfg.max_runtime_minutes:.1f} minutes)"

        if cfg.max_cost is not None and self.total_cost >= cfg.max_cost:
            return f"OpenRouter cost budget reached (${self.total_cost:.4f}/${cfg.max_cost:.4f})"

        return None

    def _should_stop_for_budget(self, prefix: str = "[BUDGET]") -> bool:
        """Print and return True when no new expensive search step should start."""
        reason = self._budget_stop_reason()
        if reason:
            print(f"{prefix} {reason}; stopping before starting another search step.")
            return True
        return False

    def _is_step_roi_acceptable(self, delta_wns: Optional[float], elapsed_seconds: float) -> bool:
        """Return whether a step improvement is large enough for its elapsed runtime."""
        threshold = self.generation_config.min_wns_per_minute
        if threshold <= 0:
            return True
        if delta_wns is None or delta_wns <= 0:
            return False
        elapsed_minutes = max(elapsed_seconds / 60.0, 1.0 / 60.0)
        return (delta_wns / elapsed_minutes) >= threshold

    def _format_step_roi(self, delta_wns: Optional[float], elapsed_seconds: float) -> str:
        """Format elapsed step cost and WNS-per-minute ROI for logs."""
        elapsed_minutes = elapsed_seconds / 60.0
        if delta_wns is None or elapsed_minutes <= 0:
            return f"elapsed {elapsed_minutes:.2f} min, WNS ROI unknown"
        return f"elapsed {elapsed_minutes:.2f} min, WNS ROI {delta_wns / max(elapsed_minutes, 1e-9):.4f} ns/min"

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
            print(f"Saved design to: {self._display_name(output_dcp)}\n")

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

    async def run_single_method(
        self,
        input_dcp: Path,
        output_dcp: Path,
        method: str,
        *,
        top_n_nets: int = 5,
        phys_opt_directive: str = "Default",
    ) -> bool:
        """Run one selected optimization method exactly once, without LLM search."""
        self.start_time = time.time()
        method = method.upper()
        if method not in SUPPORTED_SINGLE_METHODS:
            raise ValueError(
                f"Unsupported single method '{method}'. Supported methods: {', '.join(SUPPORTED_SINGLE_METHODS)}"
            )

        try:
            await self.perform_initial_analysis(input_dcp)

            if method == "PBLOCK":
                strategy_args = {}
            elif method == "FANOUT":
                strategy_args = {"top_n_nets": top_n_nets}
            elif method == "CELL_RELOCATE":
                strategy_args = {"num_paths": 10, "detour_threshold": 2.0, "max_cells": 3}
            elif method == "HARD_BLOCK":
                strategy_args = {"hard_block_types": ["DSP", "BRAM", "URAM"]}
            else:
                strategy_args = {"directive": phys_opt_directive}

            print(f"=== Running Single Method: {method} ===\n")
            timing_report, _ = await self._execute_strategy(method, strategy_args)
            final_metrics = await self._measure_current_metrics(timing_report)

            await self.v(
                "write_checkpoint",
                {
                    "dcp_path": str(output_dcp.resolve()),
                    "force": True,
                },
            )

            self.end_time = time.time()
            total_runtime = self.end_time - self.start_time
            self.final_wns = final_metrics.get("wns")

            print("=== Single-Method Summary ===")
            print(f"Method: {method}")
            if self.initial_wns is not None:
                print(f"Initial WNS: {self.initial_wns:.3f} ns")
            if self.final_wns is not None:
                print(f"Final WNS:   {self.final_wns:.3f} ns")
            if self.clock_period is not None and self.initial_wns is not None and self.final_wns is not None:
                initial_fmax = self.calculate_fmax(self.initial_wns, self.clock_period)
                final_fmax = self.calculate_fmax(self.final_wns, self.clock_period)
                if initial_fmax is not None and final_fmax is not None:
                    print(f"Fmax:        {initial_fmax:.2f} -> {final_fmax:.2f} MHz")
            print(f"Runtime:     {total_runtime:.2f} seconds")
            print(f"Saved DCP:   {self._display_name(output_dcp)}")
            print("=" * 70 + "\n")
            return True
        except Exception as exc:
            logger.exception("Single-method run failed: %s", exc)
            print(f"\n✗ Single-method run failed: {exc}\n")
            self.end_time = time.time()
            return False

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
        used_action_signatures: set[str] = set()

        max_iterations = self.generation_config.max_llm_calls
        hit_wall_clock_limit = False

        for index in range(max_iterations):
            if self._should_stop_for_budget():
                hit_wall_clock_limit = True
                break

            try:
                self._raise_if_wall_clock_expired("before starting the next iteration")
            except WallClockLimitReached as exc:
                print(f"{exc} Stopping search and keeping the best checkpoint saved so far.")
                hit_wall_clock_limit = True
                break

            self.iteration += 1
            print(f"\n=== Iteration {index + 1} ===")

            try:
                if best_dcp_path.exists() and last_best_iteration != index:
                    await self.v("open_checkpoint", {"dcp_path": str(best_dcp_path)})
                    await self.rw("read_checkpoint", {"dcp_path": str(best_dcp_path)})

                decision_input = self._build_decision_input(
                    initial_analysis,
                    stagnation,
                    self.history[-5:],
                )
                if self.force_strategy:
                    strategy, args = self.sanitize_action({"strategy": self.force_strategy, "args": {}})
                    print(f"Forced strategy: {strategy} with args {args}")
                else:
                    action = await self.choose_action_llm(decision_input)
                    strategy, args = self.sanitize_action(action)
                strategy, args, deduped = self._dedupe_action_choice(strategy, args, used_action_signatures)
                if deduped:
                    print(f"Chosen action repeated in current search state; using fallback: {strategy} with args {args}")
                print(f"Chosen: {strategy} with args {args}")
                previous_metrics = await self._measure_current_metrics()
                previous_wns = previous_metrics["wns"]

                try:
                    step_start_time = time.time()
                    result_report, current_wns = await self._execute_strategy(strategy, args)
                    step_elapsed_time = time.time() - step_start_time
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
                    used_action_signatures.add(self._action_signature(strategy, args))
                    stagnation += 1

                    if stagnation >= self.generation_config.max_steps_without_improvement:
                        print("No improvement. Stopping.")
                        break
                    continue

                current_metrics = await self._measure_current_metrics(result_report)
                delta = current_wns - previous_wns if (current_wns is not None and previous_wns is not None) else None
                delta_vs_best = (
                    current_wns - best_metrics["wns"]
                    if current_wns is not None and best_metrics.get("wns") is not None
                    else None
                )
                roi_accepted = self._is_step_roi_acceptable(delta_vs_best, step_elapsed_time)
                self.history.append(
                    {
                        "iteration": index + 1,
                        "strategy": strategy,
                        "args": args,
                        "wns": current_wns,
                        "tns": current_metrics.get("tns"),
                        "failing_endpoints": current_metrics.get("failing_endpoints"),
                        "delta_wns": delta,
                        "delta_vs_best": delta_vs_best,
                        "elapsed_seconds": step_elapsed_time,
                        "roi_accepted": roi_accepted,
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
                print(f"Step cost: {self._format_step_roi(delta_vs_best, step_elapsed_time)}")
                used_action_signatures.add(self._action_signature(strategy, args))

                if self._is_metrics_improvement(current_metrics, best_metrics):
                    best_wns = current_wns
                    best_metrics = current_metrics
                    best_dcp_path = await self._save_best_checkpoint(
                        Path(self.temp_dir) / f"best_iter_{index + 1:03d}.dcp"
                    )
                    last_best_iteration = index + 1
                    used_action_signatures.clear()
                    if roi_accepted:
                        stagnation = 0
                    else:
                        stagnation += 1
                        print("Improvement saved, but below configured WNS/runtime ROI; patience was not reset.")
                else:
                    stagnation += 1

                if best_wns is not None and best_wns >= 0:
                    print("Timing met.")
                    break

                if stagnation >= self.generation_config.max_steps_without_improvement:
                    print("No improvement. Stopping.")
                    break
            except WallClockLimitReached as exc:
                print(f"{exc} Stopping search and keeping the best checkpoint saved so far.")
                hit_wall_clock_limit = True
                break

        shutil.copy2(best_dcp_path, output_dcp)

        self.end_time = time.time()
        self._print_optimization_summary(max_iterations_reached=hit_wall_clock_limit)
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
            **self._candidate_score_metadata(self.initial_wns),
        )
        self.search_candidates = [root]
        self.best_candidate = root
        active_candidates = [root]
        hit_wall_clock_limit = False
        fast_search_stopped = False

        for generation in range(1, cfg.max_generations + 1):
            if self._should_stop_for_budget("[SEARCH]"):
                break

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
                    if self._should_stop_for_budget("[SEARCH]"):
                        break

                    if self.llm_call_count >= cfg.max_llm_calls:
                        break
            try:
                self._raise_if_wall_clock_expired("before starting the next generation")
                if self.llm_call_count >= cfg.max_llm_calls:
                    print(f"[SEARCH] Reached max LLM calls ({cfg.max_llm_calls}); stopping search.")
                    break

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

                        if self._is_candidate_improvement(candidate, self.best_candidate):
                            self.best_candidate = candidate
                            print(f"[SEARCH] New global best: {candidate.candidate_id} ({self._format_wns(candidate.wns)})")

                        should_stop_fast = bool(
                            self.best_candidate
                            and should_stop_fast_search(cfg, root, self.best_candidate)
                        )

                        if cfg.stop_when_timing_met and candidate.wns is not None and candidate.wns >= 0:
                            print("[SEARCH] Timing met; stopping search because stop_when_timing_met is enabled.")
                            active_candidates = [candidate]
                            branch_results = [candidate]
                            break

                        if should_stop_fast and self.best_candidate:
                            print(
                                f"[SEARCH] Candidate {self.best_candidate.candidate_id} has projected score "
                                f"{self.best_candidate.projected_score:.6f}; later fast-profile expansion is skipped."
                            )
                            fast_search_stopped = True
                            break

                    if fast_search_stopped:
                        break

                    if cfg.stop_when_timing_met and self.best_candidate and self.best_candidate.wns is not None and self.best_candidate.wns >= 0:
                        break

                if fast_search_stopped:
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
            except WallClockLimitReached as exc:
                print(f"[SEARCH] {exc} Stopping search and keeping the best checkpoint saved so far.")
                hit_wall_clock_limit = True
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
        print(f"[SEARCH] Copied best checkpoint to: {self._display_name(output_dcp)}")

        self._print_optimization_summary(max_iterations_reached=hit_wall_clock_limit)
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
        parent_token = self._short_candidate_token(parent.candidate_id)
        branch_id = f"g{generation:02d}_p{parent_token}_b{branch_index:02d}"
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
        used_action_signatures: set[str] = set()

        for step in range(1, cfg.max_steps_per_branch + 1):
            if self._should_stop_for_budget("[SEARCH]"):
                break

            self._raise_if_wall_clock_expired(f"before starting branch step {step}")
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
            if self.force_strategy:
                strategy, args = self.sanitize_action({"strategy": self.force_strategy, "args": {}})
                print(f"[SEARCH] Forced CLI choice: {strategy} with args {args}")
            elif forced_action is not None:
                strategy, args = forced_action
                print(f"[SEARCH] Forced diversity choice: {strategy} with args {args}")
            else:
                action = await self.choose_action_llm(decision_input)
                strategy, args = self.sanitize_action(action)
            strategy, args, deduped = self._dedupe_action_choice(strategy, args, used_action_signatures)
            if deduped:
                print(f"[SEARCH] Repeated action avoided; using fallback: {strategy} with args {args}")
            else:
                print(f"[SEARCH] Chosen: {strategy} with args {args}")
            previous_wns = current_wns
            previous_metrics = {
                "wns": current_wns,
                "tns": latest_candidate.tns,
                "failing_endpoints": latest_candidate.failing_endpoints,
            }

            try:
                step_start_time = time.time()
                result_report, current_wns = await self._execute_strategy(strategy, args)
                step_elapsed_time = time.time() - step_start_time
            except Exception as exc:
                logger.exception("Error during branch %s step %s", branch_id, step)
                failed_step = {
                    "step": step,
                    "strategy": strategy,
                    "args": args,
                    "wns": None,
                    "error": str(exc),
                }
                branch_history.append(failed_step)
                self.history.append(failed_step)
                used_action_signatures.add(self._action_signature(strategy, args))
                steps_since_peak += 1
                continue

            current_metrics = await self._measure_current_metrics(result_report)
            delta_vs_peak = (
                current_wns - peak_metrics["wns"]
                if current_wns is not None and peak_metrics.get("wns") is not None
                else None
            )
            roi_accepted = self._is_step_roi_acceptable(delta_vs_peak, step_elapsed_time)
            used_action_signatures.add(self._action_signature(strategy, args))
            completed_step = {
                "step": step,
                "strategy": strategy,
                "args": args,
                "wns": current_wns,
                "tns": current_metrics.get("tns"),
                "failing_endpoints": current_metrics.get("failing_endpoints"),
                "delta_wns": (
                    current_wns - previous_wns if current_wns is not None and previous_wns is not None else None
                ),
                "delta_vs_peak": delta_vs_peak,
                "elapsed_seconds": step_elapsed_time,
                "roi_accepted": roi_accepted,
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
            branch_history.append(completed_step)
            self.history.append(completed_step)

            neutral_fallback = (
                plan_neutral_phys_opt_fallback(
                    self.design_signature,
                    self._current_budget_state(),
                    history=self.history,
                    validation=self.validation_status,
                )
                if self.design_signature is not None
                else ()
            )
            if neutral_fallback:
                fallback_args = {"directive": neutral_fallback[0].name}
                fallback_previous_wns = current_wns
                fallback_previous_metrics = current_metrics
                fallback_start_time = time.time()
                try:
                    result_report, current_wns = await self._execute_strategy(
                        "PHYS_OPT", fallback_args
                    )
                    fallback_elapsed_time = time.time() - fallback_start_time
                    current_metrics = await self._measure_current_metrics(result_report)
                except Exception as exc:
                    fallback_elapsed_time = time.time() - fallback_start_time
                    logger.exception(
                        "Error during bounded neutral PHYS_OPT fallback in branch %s step %s",
                        branch_id,
                        step,
                    )
                    fallback_restore_confirmed = True
                    try:
                        baseline_checkpoint = Path(self.temp_dir) / "phys_opt_baseline.dcp"
                        restore_result = await self.v(
                            "open_checkpoint",
                            {"dcp_path": str(baseline_checkpoint.resolve())},
                        )
                        self._raise_if_tool_reported_error(
                            "vivado_open_checkpoint", restore_result
                        )
                    except Exception:
                        fallback_restore_confirmed = False
                        logger.exception(
                            "Could not restore neutral PHYS_OPT fallback baseline"
                        )
                    fallback_failed_step = {
                        "step": step,
                        "strategy": "PHYS_OPT",
                        "args": fallback_args,
                        "wns": None,
                        "error": str(exc),
                        "elapsed_seconds": fallback_elapsed_time,
                    }
                    branch_history.append(fallback_failed_step)
                    self.history.append(fallback_failed_step)
                    used_action_signatures.add(
                        self._action_signature("PHYS_OPT", fallback_args)
                    )
                    current_wns = fallback_previous_wns
                    current_metrics = fallback_previous_metrics
                    if not fallback_restore_confirmed:
                        print(
                            f"[SEARCH] Branch {branch_id} step {step}: neutral PHYS_OPT "
                            "baseline restore was not confirmed; stopping branch."
                        )
                        return None
                else:
                    fallback_delta_vs_peak = (
                        current_wns - peak_metrics["wns"]
                        if current_wns is not None and peak_metrics.get("wns") is not None
                        else None
                    )
                    fallback_step = {
                        "step": step,
                        "strategy": "PHYS_OPT",
                        "args": fallback_args,
                        "wns": current_wns,
                        "tns": current_metrics.get("tns"),
                        "failing_endpoints": current_metrics.get("failing_endpoints"),
                        "delta_wns": (
                            current_wns - fallback_previous_wns
                            if current_wns is not None and fallback_previous_wns is not None
                            else None
                        ),
                        "delta_vs_peak": fallback_delta_vs_peak,
                        "elapsed_seconds": fallback_elapsed_time,
                        "roi_accepted": self._is_step_roi_acceptable(
                            fallback_delta_vs_peak, fallback_elapsed_time
                        ),
                        "previous_wns": fallback_previous_wns,
                        "delta_tns": (
                            current_metrics.get("tns") - fallback_previous_metrics["tns"]
                            if current_metrics.get("tns") is not None
                            and fallback_previous_metrics.get("tns") is not None
                            else None
                        ),
                        "delta_failing_endpoints": (
                            current_metrics.get("failing_endpoints")
                            - fallback_previous_metrics["failing_endpoints"]
                            if current_metrics.get("failing_endpoints") is not None
                            and fallback_previous_metrics.get("failing_endpoints") is not None
                            else None
                        ),
                        "delta_vs_parent": (
                            current_wns - parent.wns
                            if current_wns is not None and parent.wns is not None
                            else None
                        ),
                    }
                    branch_history.append(fallback_step)
                    self.history.append(fallback_step)
                    used_action_signatures.add(
                        self._action_signature("PHYS_OPT", fallback_args)
                    )
                    strategy = "PHYS_OPT"
                    args = fallback_args
                    delta_vs_peak = fallback_delta_vs_peak
                    step_elapsed_time += fallback_elapsed_time
                    roi_accepted = fallback_step["roi_accepted"]

            checkpoint_path = search_dir / f"{branch_id}_step{step:02d}.dcp"
            saved = await self._save_vivado_checkpoint(checkpoint_path)
            if not saved:
                print(f"[SEARCH] Branch {branch_id} step {step}: checkpoint save failed; stopping branch.")
                break

            if self._is_metrics_improvement(current_metrics, peak_metrics):
                peak_wns = current_wns
                peak_metrics = current_metrics
                if roi_accepted:
                    steps_since_peak = 0
                else:
                    steps_since_peak += 1
                    print(
                        "[SEARCH] Improvement saved, but below configured WNS/runtime ROI; "
                        "branch patience was not reset."
                    )
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
                **self._candidate_score_metadata(current_wns),
            )
            self.search_candidates.append(latest_candidate)

            print(
                f"[SEARCH] {latest_candidate.candidate_id}: current {self._format_wns(current_wns)}, "
                f"peak {self._format_wns(peak_wns)}, steps since peak {steps_since_peak}"
            )
            print(f"[SEARCH] Step cost: {self._format_step_roi(delta_vs_peak, step_elapsed_time)}")

            if self._is_candidate_improvement(latest_candidate, self.best_candidate):
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
        contest_score = None
        if fmax_improvement is not None and total_runtime is not None:
            contest_score = calculate_contest_score(
                ContestScoreInput(
                    delta_fmax_mhz=fmax_improvement,
                    llm_cost_usd=self.total_cost,
                    runtime_seconds=total_runtime,
                    validation=self.validation_status,
                )
            )

        validation_summary = asdict(self.validation_status)
        validation_summary.update(
            {
                "complete": self.validation_status.complete,
                "passed": self.validation_status.passed,
            }
        )

        report = {
            "model": self.model,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "system_prompt": {
                "path": str(self.system_prompt_path),
                "sha256_16": self.system_prompt_hash,
            },
            "design_signature": self.design_signature.to_dict() if self.design_signature else None,
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
                        "elapsed_seconds": candidate.elapsed_seconds,
                        "llm_cost_usd": candidate.llm_cost_usd,
                        "projected_score": candidate.projected_score,
                        "validation": asdict(candidate.validation),
                        "validated_score": candidate.validated_score,
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
                "total_llm_cost": self.total_cost,
                "target_clock": self.target_clock,
                "clock_period_ns": self.clock_period,
                "initial_wns": self.initial_wns,
                "best_wns": self.best_wns,
                "wns_improvement": self.best_wns - self.initial_wns if self.initial_wns is not None else None,
                "initial_fmax_mhz": initial_fmax,
                "best_fmax_mhz": best_fmax,
                "final_fmax_mhz": best_fmax,
                "fmax_improvement_mhz": fmax_improvement,
                "delta_fmax_mhz": fmax_improvement,
                "score_runtime_hours": contest_score.runtime_hours if contest_score else None,
                "score_penalty_multiplier": contest_score.penalty_multiplier if contest_score else None,
                "projected_contest_score": contest_score.projected_score if contest_score else None,
                "validated_contest_score": contest_score.validated_score if contest_score else None,
                "score_status": contest_score.score_status if contest_score else None,
                "validation": validation_summary,
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
        initial_fmax = self.calculate_fmax(self.initial_wns, self.clock_period)
        final_fmax = self.calculate_fmax(best_wns, self.clock_period) if best_wns is not None else None
        delta_fmax = (final_fmax - initial_fmax) if (initial_fmax is not None and final_fmax is not None) else None
        if initial_fmax is not None or final_fmax is not None or delta_fmax is not None:
            print("\nFMAX RESULTS:")
            print(f"  Initial Fmax:        {f'{initial_fmax:.2f} MHz' if initial_fmax is not None else 'N/A'}")
            print(f"  Final Fmax:          {f'{final_fmax:.2f} MHz' if final_fmax is not None else 'N/A'}")
            print(f"  Delta Fmax:          {f'{delta_fmax:.2f} MHz' if delta_fmax is not None else 'N/A'}")

        print("\nITERATION STATS:")
        print(f"  Total iterations:    {self.iteration}")
        print(f"  LLM API calls:       {self.llm_call_count}")

        print("\nSEARCH BUDGET:")
        print(f"  Budget profile:      {self.generation_config.budget_profile}")
        print(f"  Strategy effort:     {self.generation_config.strategy_effort}")
        print(f"  Min WNS improvement: {self.generation_config.min_wns_delta:.3f} ns")
        if self.generation_config.min_wns_per_minute > 0:
            print(f"  Min WNS ROI:         {self.generation_config.min_wns_per_minute:.4f} ns/min")
        if self.generation_config.max_runtime_minutes is not None:
            print(f"  Runtime budget:      {self.generation_config.max_runtime_minutes:.1f} min")
        if self.generation_config.max_cost is not None:
            print(f"  Cost budget:         ${self.generation_config.max_cost:.4f}")

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
                print(f"  Best checkpoint:     {self._display_name(self.best_candidate.dcp_path)}")

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
            print(f"  Total LLM cost:      ${self.total_cost:.4f}")
        else:
            print("  Total LLM cost:      Not available")

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
