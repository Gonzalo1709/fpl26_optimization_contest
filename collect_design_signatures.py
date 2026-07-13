#!/usr/bin/env python3
"""Collect analysis-only design signatures without calling OpenRouter."""

import argparse
import asyncio
import json
from pathlib import Path

from src.llm_optimizer import DCPOptimizer


async def collect(dcp_paths: list[Path], output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    for dcp_path in dcp_paths:
        run_dir = output_root / dcp_path.stem
        optimizer = DCPOptimizer(
            api_key="analysis-only",
            run_dir=run_dir,
            system_prompt="analysis-only",
        )
        await optimizer.start_servers(log_prefix=f"[{dcp_path.stem}]")
        try:
            await optimizer.perform_initial_analysis(dcp_path)
            signature_path = run_dir / "design_signature.json"
            signature_path.write_text(
                json.dumps(optimizer.design_signature.to_dict(), indent=2),
                encoding="utf-8",
            )
            print(f"SIGNATURE_PATH={signature_path}")
        finally:
            await optimizer.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("dcps", type=Path, nargs="+")
    args = parser.parse_args()
    asyncio.run(collect(args.dcps, args.output_root))


if __name__ == "__main__":
    main()
