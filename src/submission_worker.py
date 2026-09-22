"""Isolated strict wrapper around the existing two-phase validator."""

import asyncio
import json
import sys
from pathlib import Path

from src.admission import sha256_file


async def main():
    from validate_dcps import DCPValidator
    golden, revised, report = map(Path, sys.argv[1:4])
    identity = {"golden_sha256": sha256_file(golden), "revised_sha256": sha256_file(revised)}
    result = {"schema_version": 1, **identity, "structural_passed": False,
              "simulation_passed": False, "simulation_skipped": False, "infrastructure_failure": False}
    validator = DCPValidator(golden, revised, num_vectors=int(sys.argv[4]))
    try:
        await validator.start_servers()
        await validator.validate()
        result.update(structural_passed=validator.phase1_passed,
                      simulation_passed=validator.phase2_passed,
                      simulation_skipped=validator.phase2_skipped,
                      detail_directory=str(validator.temp_dir))
    except Exception as exc:
        result.update(infrastructure_failure=True, error=str(exc))
    finally:
        try:
            await validator.cleanup()
        except Exception as exc:
            result.update(infrastructure_failure=True, error=str(exc))
    if sha256_file(golden) != identity["golden_sha256"] or sha256_file(revised) != identity["revised_sha256"]:
        result.update(infrastructure_failure=True, error="validator input bytes changed")
    temporary = report.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2), encoding="utf-8")
    temporary.replace(report)
    return 0 if (result["structural_passed"] is True and result["simulation_passed"] is True
                 and result["simulation_skipped"] is False and result["infrastructure_failure"] is False) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
