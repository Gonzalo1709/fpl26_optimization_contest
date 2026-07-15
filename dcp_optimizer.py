#!/usr/bin/env python3
# Copyright (C) 2026, Advanced Micro Devices, Inc. All rights reserved.
# Portions of this file consist of AI-generated content.
# SPDX-License-Identifier: Apache 2.0

"""FPGA Design Optimization Agent CLI."""

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

from openai import OpenAI

from src.llm_optimizer import DCPOptimizer, DEFAULT_MODEL, SUPPORTED_SINGLE_METHODS
from src.search import GenerationSearchConfig
from src.test_modes import run_test_mode

SEARCH_PROFILE_DEFAULTS = {
    "fast": {
        "branches": 1,
        "beam_width": 1,
        "generations": 2,
        "steps_per_branch": 1,
        "steps_without_improvement": 1,
        "max_llm_calls": 8,
        "min_wns_delta": 0.02,
        "min_wns_per_minute": 0.0,
        "strategy_effort": "fast",
    },
    "balanced": {
        "branches": 2,
        "beam_width": 2,
        "generations": 3,
        "steps_per_branch": 3,
        "steps_without_improvement": 3,
        "max_llm_calls": 50,
        "min_wns_delta": 0.001,
        "min_wns_per_minute": 0.0,
        "strategy_effort": "balanced",
    },
    "cost": {
        "branches": 1,
        "beam_width": 1,
        "generations": 2,
        "steps_per_branch": 2,
        "steps_without_improvement": 1,
        "max_llm_calls": 6,
        "min_wns_delta": 0.01,
        "min_wns_per_minute": 0.001,
        "strategy_effort": "fast",
    },
    "quality": {
        "branches": 3,
        "beam_width": 2,
        "generations": 4,
        "steps_per_branch": 3,
        "steps_without_improvement": 3,
        "max_llm_calls": 80,
        "min_wns_delta": 0.001,
        "min_wns_per_minute": 0.0,
        "strategy_effort": "thorough",
    },
}


def resolve_profile_value(args, profile_defaults: dict, attr: str):
    value = getattr(args, attr)
    return profile_defaults[attr] if value is None else value


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)


async def main():
    parser = argparse.ArgumentParser(
        description="FPGA Design Optimization Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python dcp_optimizer.py input.dcp
  python dcp_optimizer.py input.dcp --output output.dcp
  python dcp_optimizer.py input.dcp --model anthropic/claude-sonnet-4
  python dcp_optimizer.py input.dcp --branches 3 --beam-width 2 --generations 4 --steps-without-improvement 3
  python dcp_optimizer.py input.dcp --budget-profile fast
  python dcp_optimizer.py input.dcp --budget-profile cost --max-runtime-minutes 45
  python dcp_optimizer.py input.dcp --search-mode linear
  python dcp_optimizer.py input.dcp --single-method PBLOCK
  python dcp_optimizer.py input.dcp --single-method FANOUT --top-n-nets 3
  python dcp_optimizer.py input.dcp --single-method PHYS_OPT --phys-opt-directive Explore
  python dcp_optimizer.py input.dcp --debug
  python dcp_optimizer.py fpl26_contest_benchmarks/logicnets_jscl_2025.1.dcp --test
  python dcp_optimizer.py fpl26_contest_benchmarks/vexriscv_re-place_2025.1.dcp --test
        """,
    )
    parser.add_argument("input_dcp", type=Path, help="Input design checkpoint (.dcp)")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        dest="output_dcp",
        help="Output optimized checkpoint (.dcp). Default: <input_name>_optimized-<timestamp>.dcp in same directory as input",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=os.environ.get("OPENROUTER_API_KEY"),
        help="OpenRouter API key (default: OPENROUTER_API_KEY env var)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"LLM model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--system-prompt",
        type=Path,
        default=None,
        help="Path to the base system prompt to use for planner decisions (default: SYSTEM_PROMPT.TXT)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode (verbose logging, save intermediate checkpoints)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test mode: run without LLM. Pblock for LogicNets, cell re-placement for VexRiscv (see docs/optimization_example.md).",
    )
    parser.add_argument(
        "--max-nets",
        type=int,
        default=5,
        help="Maximum number of high fanout nets to optimize in test mode (default: 5)",
    )
    parser.add_argument(
        "--search-mode",
        choices=["generations", "linear"],
        default="generations",
        help="LLM search controller to use in full agent mode (default: generations)",
    )
    parser.add_argument(
        "--budget-profile",
        choices=["fast", "balanced", "cost", "quality"],
        default="fast",
        help=(
            "Default search/recipe budget profile. fast prioritizes wall-clock time, "
            "cost limits LLM/tool spend, quality broadens search (default: fast)"
        ),
    )
    parser.add_argument(
        "--strategy-effort",
        choices=["fast", "balanced", "thorough"],
        default=None,
        help="Override how many internal Vivado/RapidWright attempts each recipe may run",
    )
    parser.add_argument(
        "--branches",
        type=int,
        default=None,
        help="Number of child branches to try from each active candidate in generation mode (profile default)",
    )
    parser.add_argument(
        "--beam-width",
        type=int,
        default=None,
        help="Number of best current candidates to keep for the next generation (profile default)",
    )
    parser.add_argument(
        "--generations",
        type=int,
        default=None,
        help="Maximum number of search generations (profile default)",
    )
    parser.add_argument(
        "--steps-per-branch",
        type=int,
        default=None,
        help="Maximum LLM steps to take along each branch before pruning (profile default)",
    )
    parser.add_argument(
        "--steps-without-improvement",
        type=int,
        default=None,
        help="Stop a branch after this many steps without beating that branch's highest WNS (profile default)",
    )
    parser.add_argument(
        "--max-llm-calls",
        type=int,
        default=None,
        help="Safety cap on total LLM calls in full agent mode (profile default)",
    )
    parser.add_argument(
        "--min-wns-delta",
        type=float,
        default=None,
        help="Minimum WNS delta in ns counted as a search-continuing improvement (profile default)",
    )
    parser.add_argument(
        "--min-wns-per-minute",
        type=float,
        default=None,
        help=(
            "Minimum WNS improvement in ns per elapsed recipe minute needed to reset search patience "
            "(profile default)"
        ),
    )
    parser.add_argument(
        "--max-runtime-minutes",
        type=float,
        default=None,
        help="Stop starting new search steps after this wall-clock runtime budget",
    )
    parser.add_argument(
        "--max-cost",
        type=float,
        default=None,
        help="Stop starting new LLM-guided search steps after this OpenRouter cost in USD",
    )
    parser.add_argument(
        "--continue-after-timing-met",
        action="store_true",
        help="Keep searching after WNS reaches 0 instead of stopping at timing closure",
    )
    parser.add_argument(
        "--wall-clock-limit-seconds",
        type=float,
        default=3600.0,
        help="Wall-clock runtime limit in seconds for optimizer search (default: 3600)",
    )
    parser.add_argument(
        "--single-method",
        choices=SUPPORTED_SINGLE_METHODS,
        help="Run exactly one selected optimization method once, without LLM search.",
    )
    parser.add_argument(
        "--top-n-nets",
        type=int,
        default=5,
        help="When using --single-method FANOUT, optimize this many high-fanout nets (default: 5)",
    )
    parser.add_argument(
        "--phys-opt-directive",
        choices=["Default", "Explore", "AggressiveExplore"],
        default="Default",
        help="When using --single-method PHYS_OPT, use this phys_opt_design directive (default: Default)",
    )
    force_group = parser.add_mutually_exclusive_group()
    force_group.add_argument(
        "--force-pblock",
        action="store_true",
        help="Force the PBLOCK recipe every iteration",
    )
    force_group.add_argument(
        "--force-fanout",
        action="store_true",
        help="Force the FANOUT recipe every iteration",
    )
    force_group.add_argument(
        "--force-cell-relocate",
        action="store_true",
        help="Force the detour-aware CELL_RELOCATE recipe every iteration",
    )
    force_group.add_argument(
        "--force-phys-opt",
        action="store_true",
        help="Force the PHYS_OPT recipe every iteration",
    )
    force_group.add_argument(
        "--force-critical-pin",
        action="store_true",
        help="Force the bounded CRITICAL_PIN recipe every iteration",
    )
    force_group.add_argument(
        "--force-route-preserve",
        action="store_true",
        help="Force the bounded ROUTE_PRESERVE recipe every iteration",
    )
    force_group.add_argument(
        "--force-hard-block",
        action="store_true",
        help="Force the gated HARD_BLOCK relocation recipe every iteration",
    )

    args = parser.parse_args()

    if not args.input_dcp.exists():
        print(f"Error: Input file not found: {args.input_dcp}", file=sys.stderr)
        sys.exit(1)

    if args.output_dcp is None:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        args.output_dcp = args.input_dcp.parent / f"{args.input_dcp.stem}_optimized-{timestamp}.dcp"

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    args.output_dcp.parent.mkdir(parents=True, exist_ok=True)

    if args.test:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        run_dir = Path.cwd() / f"dcp_optimizer_run-{timestamp}"

        print("FPGA Design Optimization - TEST MODE")
        print("=====================================")
        print(f"Input:       {args.input_dcp.resolve()}")
        print(f"Output:      {args.output_dcp.resolve()}")
        print(f"Run dir:     {run_dir}")
        print(f"Max nets to optimize: {args.max_nets}")
        print()

        exit_code = await run_test_mode(
            args.input_dcp,
            args.output_dcp,
            debug=args.debug,
            max_nets=args.max_nets,
            run_dir=run_dir,
        )
        sys.exit(exit_code)

    if args.single_method:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        run_dir = Path.cwd() / f"dcp_optimizer_run-{timestamp}"

        print("FPGA Design Optimization - SINGLE METHOD MODE")
        print("==============================================")
        print(f"Input:        {args.input_dcp.resolve()}")
        print(f"Output:       {args.output_dcp.resolve()}")
        print(f"Run dir:      {run_dir}")
        print(f"Method:       {args.single_method}")
        if args.single_method == "FANOUT":
            print(f"Top nets:     {args.top_n_nets}")
        elif args.single_method == "PHYS_OPT":
            print(f"Directive:    {args.phys_opt_directive}")
        print()

        generation_config = GenerationSearchConfig(
            enabled=False,
            wall_clock_limit_seconds=max(0.0, args.wall_clock_limit_seconds),
        )
        optimizer = DCPOptimizer(
            api_key=args.api_key or "",
            model=args.model,
            debug=args.debug,
            run_dir=run_dir,
            generation_config=generation_config,
        )

        try:
            await optimizer.start_servers()
            success = await optimizer.run_single_method(
                args.input_dcp,
                args.output_dcp,
                args.single_method,
                top_n_nets=max(1, args.top_n_nets),
                phys_opt_directive=args.phys_opt_directive,
            )

            if success:
                print("\n✓ Single-method optimization completed successfully")
                print("\nOutput files:")
                print(f"  Optimized DCP: {args.output_dcp.name}")
                sys.exit(0)

            print("\n✗ Single-method optimization did not complete successfully")
            print(f"\nRun directory preserved at: {run_dir}")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
            print(f"Run directory preserved at: {run_dir}")
            sys.exit(130)
        except Exception as exc:
            logging.exception("Fatal error")
            print(f"\n✗ Fatal error: {exc}")
            print(f"Run directory preserved at: {run_dir}")
            sys.exit(1)
        finally:
            await optimizer.cleanup()

    if not args.api_key:
        print("Error: OpenRouter API key required. Set OPENROUTER_API_KEY or use --api-key", file=sys.stderr)
        print("       Use --test flag to run in test mode without LLM", file=sys.stderr)
        sys.exit(1)

    if OpenAI is None:
        print("Error: openai package not installed. Run: pip install openai", file=sys.stderr)
        sys.exit(1)

    force_strategy = None
    if args.force_pblock:
        force_strategy = "PBLOCK"
    elif args.force_fanout:
        force_strategy = "FANOUT"
    elif args.force_cell_relocate:
        force_strategy = "CELL_RELOCATE"
    elif args.force_phys_opt:
        force_strategy = "PHYS_OPT"
    elif args.force_critical_pin:
        force_strategy = "CRITICAL_PIN"
    elif args.force_route_preserve:
        force_strategy = "ROUTE_PRESERVE"
    elif args.force_hard_block:
        force_strategy = "HARD_BLOCK"

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = Path.cwd() / f"dcp_optimizer_run-{timestamp}"
    profile_defaults = SEARCH_PROFILE_DEFAULTS[args.budget_profile]
    branches = resolve_profile_value(args, profile_defaults, "branches")
    beam_width = resolve_profile_value(args, profile_defaults, "beam_width")
    generations = resolve_profile_value(args, profile_defaults, "generations")
    steps_per_branch = resolve_profile_value(args, profile_defaults, "steps_per_branch")
    steps_without_improvement = resolve_profile_value(args, profile_defaults, "steps_without_improvement")
    max_llm_calls = resolve_profile_value(args, profile_defaults, "max_llm_calls")
    min_wns_delta = resolve_profile_value(args, profile_defaults, "min_wns_delta")
    min_wns_per_minute = resolve_profile_value(args, profile_defaults, "min_wns_per_minute")
    strategy_effort = args.strategy_effort or profile_defaults["strategy_effort"]

    print("FPGA Design Optimization Agent")
    print("================================")
    print(f"Input:       {args.input_dcp.resolve()}")
    print(f"Output:      {args.output_dcp.resolve()}")
    print(f"Run dir:     {run_dir}")
    print(f"Model:       {args.model}")
    if args.system_prompt:
        print(f"Prompt:      {args.system_prompt.resolve()}")
    print(f"Search mode: {args.search_mode}")
    print(f"Wall clock:  {args.wall_clock_limit_seconds:.0f} seconds")
    print(f"Budget:      {args.budget_profile} (recipe effort: {strategy_effort})")
    if args.max_runtime_minutes is not None:
        print(f"Runtime cap: {args.max_runtime_minutes:.1f} minutes")
    if args.max_cost is not None:
        print(f"Cost cap:    ${args.max_cost:.4f}")
    if args.search_mode == "generations":
        print(f"Branches:    {branches}")
        print(f"Beam width:  {beam_width}")
        print(f"Generations: {generations}")
        print(f"Patience:    {steps_without_improvement} steps without branch-peak improvement")
    print(f"Min WNS gain:{min_wns_delta:.3f} ns")
    if min_wns_per_minute > 0:
        print(f"Min ROI:     {min_wns_per_minute:.4f} ns/minute")
    if force_strategy:
        print(f"Forced recipe: {force_strategy}")
    print()

    generation_config = GenerationSearchConfig(
        enabled=args.search_mode == "generations",
        budget_profile=args.budget_profile,
        strategy_effort=strategy_effort,
        branch_factor=max(1, branches),
        beam_width=max(1, beam_width),
        max_generations=max(1, generations),
        max_steps_per_branch=max(1, steps_per_branch),
        max_steps_without_improvement=max(1, steps_without_improvement),
        max_llm_calls=max(1, max_llm_calls),
        min_wns_delta=max(0.0, min_wns_delta),
        min_wns_per_minute=max(0.0, min_wns_per_minute),
        max_runtime_minutes=args.max_runtime_minutes if args.max_runtime_minutes and args.max_runtime_minutes > 0 else None,
        max_cost=args.max_cost if args.max_cost and args.max_cost > 0 else None,
        stop_when_timing_met=not args.continue_after_timing_met,
        wall_clock_limit_seconds=max(0.0, args.wall_clock_limit_seconds),
    )

    optimizer = DCPOptimizer(
        api_key=args.api_key,
        model=args.model,
        debug=args.debug,
        run_dir=run_dir,
        generation_config=generation_config,
        system_prompt_path=args.system_prompt,
        force_strategy=force_strategy,
    )

    try:
        await optimizer.start_servers()
        success = await optimizer.optimize(args.input_dcp, args.output_dcp)

        if success:
            print("\n✓ Optimization completed successfully")
            print("\nOutput files:")
            print(f"  Optimized DCP: {args.output_dcp.name}")
            sys.exit(0)

        print("\n✗ Optimization did not complete successfully")
        print(f"\nRun directory preserved at: {run_dir}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        print(f"Run directory preserved at: {run_dir}")
        sys.exit(130)
    except Exception as exc:
        logging.exception("Fatal error")
        print(f"\n✗ Fatal error: {exc}")
        print(f"Run directory preserved at: {run_dir}")
        sys.exit(1)
    finally:
        await optimizer.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
