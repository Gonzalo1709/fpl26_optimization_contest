"""Create labelled synthetic runs for exploring the dashboard without FPGA tools."""

import argparse
from pathlib import Path
from types import SimpleNamespace

from src.run_logging import RunRecorder


def create_demo(root: Path):
    root = root.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("Demo destination must be empty or new")
    root.mkdir(parents=True, exist_ok=True)
    for index in range(2):
        run = root / f"demo-run-{index + 1}"
        recorder = RunRecorder(run, "generations", root / "demo-input.dcp", root / "demo-output.dcp",
                               {"demo": True, "budget_profile": "fast" if index == 0 else "quality"})
        recorder.record("candidate_admitted", candidate_id="baseline", parent_id=None, metrics={"wns": -0.5})
        for step, wns in enumerate([-0.3, -0.15 - index * 0.05], 1):
            attempt, decision, candidate = f"a{step}", f"d{step}", f"c{step}"
            recorder.record("action_selected", decision_id=decision, attempt_id=attempt,
                            seed_candidate_id="baseline" if step == 1 else "c1", strategy="PHYS_OPT",
                            generation=step, branch=0, source="demo",
                            budget={"remaining_runtime_seconds": 3600 - step * 60, "remaining_cost_usd": 0.9},
                            args={"directive": "Explore"}, alternatives_ref=recorder.capture({"note": "Synthetic policy evidence for the dashboard demo"}))
            recorder.record("tool_call_finished", decision_id=decision, attempt_id=attempt, call_id=f"tool-{step}",
                            tool="vivado_phys_opt_design", result_ref=recorder.capture("Synthetic tool result", "text"))
            recorder.record("candidate_admitted", candidate_id=candidate, parent_id="baseline" if step == 1 else "c1",
                            attempt_id=attempt, decision_id=decision, metrics={"wns": wns})
            recorder.record("recipe_attempt", attempt_id=attempt, decision_id=decision, strategy="PHYS_OPT",
                            status="measured", wns_ns=wns, delta_wns_ns=0.2, recipe_seconds=60)
        recorder.record("action_selected", decision_id="d3", attempt_id="a3", seed_candidate_id="baseline", strategy="FANOUT")
        recorder.record("attempt_aborted", decision_id="d3", attempt_id="a3", error_type="SyntheticFailure")
        recorder.record("beam_selected", candidate_ids=["c2"], considered_candidate_ids=["c1", "c2"], generation=2)
        recorder.record("publish_rejected", candidate_id="c1", reason="Synthetic validation rejection")
        recorder.record("llm_call_finished", usage={"cost": 0.02}, cost_verified=True)
        optimizer = SimpleNamespace(initial_wns=-0.5, best_wns=-0.15 - index * 0.05, clock_period=2.5,
                                    total_cost=0.02, llm_call_count=1,
                                    calculate_fmax=lambda wns, period: 1000 / (period - wns),
                                    best_candidate=SimpleNamespace(candidate_id="c2", checkpoint_sha256=None,
                                                                   projected_score=None, validated_score=None))
        recorder.finish("completed", optimizer)
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(create_demo(args.destination))
