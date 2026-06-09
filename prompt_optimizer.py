#!/usr/bin/env python3
# Copyright (C) 2026, Advanced Micro Devices, Inc. All rights reserved.
# Portions of this file consist of AI-generated content.
# SPDX-License-Identifier: Apache 2.0

"""Evaluate and optimize SYSTEM_PROMPT.TXT for planner decisions.

This harness optimizes the recipe-selection prompt offline against JSONL planner
examples. It does not invoke Vivado or RapidWright; full DCP runs remain the
final validation step for a candidate prompt.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from openai import OpenAI

from src.prompting import DEFAULT_SYSTEM_PROMPT_PATH, build_planner_system_prompt, load_system_prompt, prompt_sha256


DEFAULT_EXAMPLES_PATH = Path("prompt_eval_examples") / "planner_examples.jsonl"
DEFAULT_MODEL = "~openai/gpt-latest"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass
class EvalExample:
    name: str
    decision_input: dict[str, Any]
    expected_strategy: str
    allowed_directives: Optional[list[str]] = None
    min_top_n_nets: Optional[int] = None
    max_top_n_nets: Optional[int] = None
    feedback_hint: str = ""


@dataclass
class PromptEvalResult:
    prompt_path: Optional[Path]
    prompt_hash: str
    mean_score: float
    examples: list[dict[str, Any]]


def load_eval_examples(path: Path) -> list[EvalExample]:
    examples: list[EvalExample] = []
    with path.open() as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            payload = json.loads(line)
            examples.append(
                EvalExample(
                    name=payload.get("name", f"example_{line_number}"),
                    decision_input=payload["decision_input"],
                    expected_strategy=payload["expected_strategy"],
                    allowed_directives=payload.get("allowed_directives"),
                    min_top_n_nets=payload.get("min_top_n_nets"),
                    max_top_n_nets=payload.get("max_top_n_nets"),
                    feedback_hint=payload.get("feedback_hint", ""),
                )
            )
    if not examples:
        raise ValueError(f"No examples found in {path}")
    return examples


def strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def parse_action(raw_text: str) -> tuple[Optional[dict[str, Any]], str]:
    text = strip_code_fence(raw_text)
    try:
        action = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(action, dict):
        return None, "JSON root is not an object"
    return action, ""


def sanitize_action(action: dict[str, Any]) -> tuple[str, dict[str, Any], list[str]]:
    issues: list[str] = []
    strategy = action.get("strategy")
    args = action.get("args", {})
    if not isinstance(args, dict):
        issues.append("args must be an object")
        args = {}

    if strategy == "FANOUT":
        try:
            top_n = int(args.get("top_n_nets", 5))
        except (TypeError, ValueError):
            top_n = 5
            issues.append("FANOUT top_n_nets was not an integer")
        if top_n < 1 or top_n > 10:
            issues.append("FANOUT top_n_nets must be in 1..10")
        return "FANOUT", {"top_n_nets": max(1, min(10, top_n))}, issues

    if strategy == "PHYS_OPT":
        directive = args.get("directive", "Default")
        if directive not in ["Explore", "AggressiveExplore", "Default"]:
            issues.append("PHYS_OPT directive is not supported")
            directive = "Default"
        return "PHYS_OPT", {"directive": directive}, issues

    if strategy == "PBLOCK":
        if args:
            issues.append("PBLOCK args should be empty")
        return "PBLOCK", {}, issues

    issues.append(f"unknown strategy: {strategy}")
    return "INVALID", {}, issues


def score_action(action: Optional[dict[str, Any]], parse_error: str, example: EvalExample) -> tuple[float, str, dict[str, Any]]:
    if action is None:
        return 0.0, f"Failed to return planner JSON for {example.name}: {parse_error}", {}

    strategy, args, issues = sanitize_action(action)
    score = 0.35
    feedback: list[str] = []

    if issues:
        feedback.extend(issues)
        score -= min(0.2, 0.05 * len(issues))
    else:
        feedback.append("Output schema was valid.")

    if strategy == example.expected_strategy:
        score += 0.45
        feedback.append(f"Strategy matched expected {example.expected_strategy}.")
    else:
        feedback.append(f"Expected {example.expected_strategy}, got {strategy}.")

    if strategy == "FANOUT":
        top_n = args.get("top_n_nets")
        min_top = example.min_top_n_nets if example.min_top_n_nets is not None else 1
        max_top = example.max_top_n_nets if example.max_top_n_nets is not None else 10
        if isinstance(top_n, int) and min_top <= top_n <= max_top:
            score += 0.2
            feedback.append(f"FANOUT top_n_nets {top_n} was in the expected range.")
        else:
            feedback.append(f"FANOUT top_n_nets should be in {min_top}..{max_top}.")
    elif strategy == "PHYS_OPT":
        directive = args.get("directive")
        allowed = example.allowed_directives or ["Explore", "AggressiveExplore", "Default"]
        if directive in allowed:
            score += 0.2
            feedback.append(f"PHYS_OPT directive {directive} was allowed.")
        else:
            feedback.append(f"PHYS_OPT directive should be one of {allowed}.")
    elif strategy == "PBLOCK":
        score += 0.2
        feedback.append("PBLOCK requires no args.")

    if example.feedback_hint:
        feedback.append(example.feedback_hint)

    return max(0.0, min(1.0, score)), " ".join(feedback), {"strategy": strategy, "args": args}


def call_planner(
    client: OpenAI,
    model: str,
    planner_prompt: str,
    decision_input: dict[str, Any],
    max_tokens: int = 200,
) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": planner_prompt},
            {"role": "user", "content": json.dumps(decision_input)},
        ],
        max_tokens=max_tokens,
        extra_body={"usage": {"include": True}},
    )
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", "") if message else ""
    return content.strip() if isinstance(content, str) else str(content).strip()


def evaluate_prompt_text(
    client: OpenAI,
    model: str,
    base_prompt: str,
    examples: list[EvalExample],
    prompt_path: Optional[Path] = None,
) -> PromptEvalResult:
    planner_prompt = build_planner_system_prompt(base_prompt=base_prompt)
    per_example: list[dict[str, Any]] = []

    for example in examples:
        raw_output = call_planner(client, model, planner_prompt, example.decision_input)
        action, parse_error = parse_action(raw_output)
        score, feedback, sanitized = score_action(action, parse_error, example)
        per_example.append(
            {
                "name": example.name,
                "score": score,
                "expected_strategy": example.expected_strategy,
                "raw_output": raw_output,
                "sanitized_action": sanitized,
                "feedback": feedback,
            }
        )

    return PromptEvalResult(
        prompt_path=prompt_path,
        prompt_hash=prompt_sha256(planner_prompt),
        mean_score=statistics.mean(item["score"] for item in per_example),
        examples=per_example,
    )


def write_eval_result(result: PromptEvalResult, output_path: Optional[Path]) -> None:
    payload = {
        "prompt_path": str(result.prompt_path) if result.prompt_path else None,
        "prompt_hash": result.prompt_hash,
        "mean_score": result.mean_score,
        "examples": result.examples,
    }
    text = json.dumps(payload, indent=2)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n")
    else:
        print(text)


def collect_candidate_paths(candidate: Optional[Path], candidates_dir: Optional[Path]) -> list[Path]:
    paths: list[Path] = []
    if candidate:
        paths.append(candidate)
    if candidates_dir:
        paths.extend(sorted(path for path in candidates_dir.iterdir() if path.is_file() and path.suffix.lower() in {".txt", ".prompt"}))
    if not paths:
        paths.append(DEFAULT_SYSTEM_PROMPT_PATH)
    return paths


def summarize_feedback(result: PromptEvalResult) -> str:
    lines = [
        f"Prompt hash: {result.prompt_hash}",
        f"Mean score: {result.mean_score:.3f}",
    ]
    for item in result.examples:
        lines.append(
            f"- {item['name']}: score={item['score']:.3f}, expected={item['expected_strategy']}, "
            f"got={item.get('sanitized_action')}; feedback={item['feedback']}"
        )
    return "\n".join(lines)


def propose_gepa_lite_variant(
    client: OpenAI,
    model: str,
    current_prompt: str,
    feedback: str,
) -> str:
    mutation_prompt = """
You are improving the base SYSTEM_PROMPT for an FPGA optimization planner.

Rewrite the base prompt to improve the planner's recipe choices from the
evaluation feedback. Preserve correct FPGA domain constraints. Do not include
the JSON output contract because the application appends that separately.

Return only the rewritten base prompt.
""".strip()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": mutation_prompt},
            {
                "role": "user",
                "content": json.dumps({"current_prompt": current_prompt, "evaluation_feedback": feedback}),
            },
        ],
        max_tokens=2500,
    )
    choices = getattr(response, "choices", None) or []
    if not choices:
        return current_prompt
    content = getattr(choices[0].message, "content", "")
    return strip_code_fence(content) if isinstance(content, str) else current_prompt


def run_evaluate(args: argparse.Namespace) -> int:
    examples = load_eval_examples(args.examples)
    client = OpenAI(api_key=args.api_key, base_url=args.base_url)
    results: list[PromptEvalResult] = []

    for path in collect_candidate_paths(args.candidate, args.candidates_dir):
        result = evaluate_prompt_text(client, args.model, load_system_prompt(path), examples, prompt_path=path)
        results.append(result)
        print(f"{path}: mean_score={result.mean_score:.3f}, hash={result.prompt_hash}")

    best = max(results, key=lambda item: item.mean_score)
    if args.output:
        if len(results) == 1:
            write_eval_result(best, args.output)
        else:
            payload = [
                {
                    "prompt_path": str(result.prompt_path) if result.prompt_path else None,
                    "prompt_hash": result.prompt_hash,
                    "mean_score": result.mean_score,
                    "examples": result.examples,
                }
                for result in sorted(results, key=lambda item: item.mean_score, reverse=True)
            ]
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(payload, indent=2) + "\n")
    return 0


def run_gepa_lite(args: argparse.Namespace) -> int:
    examples = load_eval_examples(args.examples)
    client = OpenAI(api_key=args.api_key, base_url=args.base_url)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    current_prompt = load_system_prompt(args.seed_prompt)
    best_prompt = current_prompt
    best_result = evaluate_prompt_text(client, args.model, best_prompt, examples, prompt_path=args.seed_prompt)
    print(f"seed: mean_score={best_result.mean_score:.3f}, hash={best_result.prompt_hash}")

    for iteration in range(1, args.iterations + 1):
        feedback = summarize_feedback(best_result)
        candidate_prompt = propose_gepa_lite_variant(client, args.reflection_model or args.model, best_prompt, feedback)
        candidate_path = args.output_dir / f"candidate_{iteration:03d}.txt"
        candidate_path.write_text(candidate_prompt.rstrip() + "\n")

        result = evaluate_prompt_text(client, args.model, candidate_prompt, examples, prompt_path=candidate_path)
        print(f"{candidate_path}: mean_score={result.mean_score:.3f}, hash={result.prompt_hash}")
        write_eval_result(result, args.output_dir / f"candidate_{iteration:03d}.json")

        if result.mean_score >= best_result.mean_score:
            best_prompt = candidate_prompt
            best_result = result

    best_path = args.output_dir / "best_SYSTEM_PROMPT.TXT"
    best_path.write_text(best_prompt.rstrip() + "\n")
    write_eval_result(best_result, args.output_dir / "best_eval.json")
    print(f"best: mean_score={best_result.mean_score:.3f}, prompt={best_path}")
    return 0


def run_dspy_gepa(args: argparse.Namespace) -> int:
    try:
        import dspy
    except ImportError:
        print("DSPy is not installed. Install optional dependencies with: pip install -r requirements-prompt-opt.txt", file=sys.stderr)
        return 2

    examples = load_eval_examples(args.examples)
    seed_prompt = load_system_prompt(args.seed_prompt)

    lm_kwargs: dict[str, Any] = {}
    if args.api_key:
        lm_kwargs["api_key"] = args.api_key
    if args.dspy_api_base:
        lm_kwargs["api_base"] = args.dspy_api_base

    dspy.configure(lm=dspy.LM(args.dspy_lm or args.model, **lm_kwargs))

    class PlannerProgram(dspy.Module):
        def __init__(self, instructions: str):
            super().__init__()
            signature = dspy.Signature(
                "decision_input -> action_json",
                instructions=build_planner_system_prompt(base_prompt=instructions),
            )
            self.predict = dspy.Predict(signature)

        def forward(self, decision_input: str):
            return self.predict(decision_input=decision_input)

    def metric(example, pred, trace=None, pred_name=None, pred_trace=None):
        raw_example = EvalExample(
            name=example.name,
            decision_input=json.loads(example.decision_input),
            expected_strategy=example.expected_strategy,
            allowed_directives=json.loads(example.allowed_directives) if example.allowed_directives else None,
            min_top_n_nets=example.min_top_n_nets,
            max_top_n_nets=example.max_top_n_nets,
            feedback_hint=example.feedback_hint,
        )
        action, parse_error = parse_action(getattr(pred, "action_json", ""))
        score, feedback, _ = score_action(action, parse_error, raw_example)
        return dspy.Prediction(score=score, feedback=feedback)

    trainset = [
        dspy.Example(
            name=example.name,
            decision_input=json.dumps(example.decision_input),
            expected_strategy=example.expected_strategy,
            allowed_directives=json.dumps(example.allowed_directives) if example.allowed_directives else "",
            min_top_n_nets=example.min_top_n_nets,
            max_top_n_nets=example.max_top_n_nets,
            feedback_hint=example.feedback_hint,
        ).with_inputs("decision_input")
        for example in examples
    ]

    program = PlannerProgram(seed_prompt)
    gepa_kwargs: dict[str, Any] = {
        "metric": metric,
        "auto": args.auto,
        "track_stats": True,
    }
    if args.reflection_model:
        gepa_kwargs["reflection_lm"] = dspy.LM(args.reflection_model, **lm_kwargs)
    optimizer = dspy.GEPA(**gepa_kwargs)
    optimized = optimizer.compile(program, trainset=trainset, valset=trainset)

    optimized_prompt = optimized.predict.signature.instructions
    marker = "PLANNER OUTPUT CONTRACT:"
    if marker in optimized_prompt:
        optimized_prompt = optimized_prompt.split(marker, 1)[0].rstrip()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(optimized_prompt.rstrip() + "\n")
    print(f"Wrote DSPy GEPA optimized prompt to {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optimize SYSTEM_PROMPT.TXT planner behavior")
    parser.add_argument("--api-key", default=os.environ.get("OPENROUTER_API_KEY"), help="OpenRouter API key")
    parser.add_argument("--base-url", default=OPENROUTER_BASE_URL, help="OpenAI-compatible API base URL")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Planner/evaluator model (default: {DEFAULT_MODEL})")

    subparsers = parser.add_subparsers(dest="command", required=True)

    evaluate = subparsers.add_parser("evaluate", help="Score one or more candidate prompt files")
    evaluate.add_argument("--examples", type=Path, default=DEFAULT_EXAMPLES_PATH)
    evaluate.add_argument("--candidate", type=Path, default=None)
    evaluate.add_argument("--candidates-dir", type=Path, default=None)
    evaluate.add_argument("--output", type=Path, default=None)
    evaluate.set_defaults(func=run_evaluate)

    gepa_lite = subparsers.add_parser("gepa-lite", help="Run a lightweight reflective prompt search")
    gepa_lite.add_argument("--examples", type=Path, default=DEFAULT_EXAMPLES_PATH)
    gepa_lite.add_argument("--seed-prompt", type=Path, default=DEFAULT_SYSTEM_PROMPT_PATH)
    gepa_lite.add_argument("--reflection-model", default=None)
    gepa_lite.add_argument("--iterations", type=int, default=5)
    gepa_lite.add_argument(
        "--output-dir",
        type=Path,
        default=Path("prompt_optimization_runs") / time.strftime("%Y%m%d_%H%M%S"),
    )
    gepa_lite.set_defaults(func=run_gepa_lite)

    dspy_gepa = subparsers.add_parser("dspy-gepa", help="Run DSPy GEPA over the planner prompt")
    dspy_gepa.add_argument("--examples", type=Path, default=DEFAULT_EXAMPLES_PATH)
    dspy_gepa.add_argument("--seed-prompt", type=Path, default=DEFAULT_SYSTEM_PROMPT_PATH)
    dspy_gepa.add_argument("--output", type=Path, default=Path("optimized_SYSTEM_PROMPT.TXT"))
    dspy_gepa.add_argument("--auto", default="light", choices=["light", "medium", "heavy"])
    dspy_gepa.add_argument("--dspy-lm", default=None, help="DSPy LM name. Defaults to --model.")
    dspy_gepa.add_argument("--dspy-api-base", default=OPENROUTER_BASE_URL)
    dspy_gepa.add_argument("--reflection-model", default=None)
    dspy_gepa.set_defaults(func=run_dspy_gepa)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.api_key:
        print("Error: API key required. Set OPENROUTER_API_KEY or pass --api-key.", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
