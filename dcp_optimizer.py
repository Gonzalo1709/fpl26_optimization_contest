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
        "--branches",
        type=int,
        default=2,
        help="Number of child branches to try from each active candidate in generation mode (default: 2)",
    )
    parser.add_argument(
        "--beam-width",
        type=int,
        default=2,
        help="Number of best current candidates to keep for the next generation (default: 2)",
    )
    parser.add_argument(
        "--generations",
        type=int,
        default=3,
        help="Maximum number of search generations (default: 3)",
    )
    parser.add_argument(
        "--steps-per-branch",
        type=int,
        default=3,
        help="Maximum LLM steps to take along each branch before pruning (default: 3)",
    )
    parser.add_argument(
        "--steps-without-improvement",
        type=int,
        default=3,
        help="Stop a branch after this many steps without beating that branch's highest WNS (default: 3)",
    )
    parser.add_argument(
        "--max-llm-calls",
        type=int,
        default=50,
        help="Safety cap on total LLM calls in full agent mode (default: 50)",
    )
    parser.add_argument(
        "--min-wns-delta",
        type=float,
        default=0.001,
        help="Minimum WNS delta in ns counted as an improvement (default: 0.001)",
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

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = Path.cwd() / f"dcp_optimizer_run-{timestamp}"

    print("FPGA Design Optimization Agent")
    print("================================")
    print(f"Input:       {args.input_dcp.resolve()}")
    print(f"Output:      {args.output_dcp.resolve()}")
    print(f"Run dir:     {run_dir}")
    print(f"Model:       {args.model}")
    print(f"Search mode: {args.search_mode}")
    print(f"Wall clock:  {args.wall_clock_limit_seconds:.0f} seconds")
    if args.search_mode == "generations":
        print(f"Branches:    {args.branches}")
        print(f"Beam width:  {args.beam_width}")
        print(f"Generations: {args.generations}")
        print(f"Patience:    {args.steps_without_improvement} steps without branch-peak improvement")
    print()

    generation_config = GenerationSearchConfig(
        enabled=args.search_mode == "generations",
        branch_factor=max(1, args.branches),
        beam_width=max(1, args.beam_width),
        max_generations=max(1, args.generations),
        max_steps_per_branch=max(1, args.steps_per_branch),
        max_steps_without_improvement=max(1, args.steps_without_improvement),
        max_llm_calls=max(1, args.max_llm_calls),
        min_wns_delta=max(0.0, args.min_wns_delta),
        stop_when_timing_met=not args.continue_after_timing_met,
        wall_clock_limit_seconds=max(0.0, args.wall_clock_limit_seconds),
    )

    optimizer = DCPOptimizer(
        api_key=args.api_key,
        model=args.model,
        debug=args.debug,
        run_dir=run_dir,
        generation_config=generation_config,
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
