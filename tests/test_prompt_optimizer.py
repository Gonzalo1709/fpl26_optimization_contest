import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from prompt_optimizer import (
    call_planner,
    examples_sha256,
    sanitize_action,
    write_utf8_text,
)


class PromptOptimizerTests(unittest.TestCase):
    def test_examples_hash_changes_with_corpus(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "examples.jsonl"
            path.write_text('{"name":"one"}\n', encoding="utf-8")
            first = examples_sha256(path)
            path.write_text('{"name":"two"}\n', encoding="utf-8")
            second = examples_sha256(path)

        self.assertEqual(len(first), 16)
        self.assertNotEqual(first, second)

    def test_sanitizer_understands_gated_portfolio_actions(self):
        strategy, args, issues = sanitize_action(
            {
                "strategy": "ROUTE_PRESERVE",
                "args": {"max_nets": 4, "min_net_delay_ns": 0.2},
            }
        )

        self.assertEqual(strategy, "ROUTE_PRESERVE")
        self.assertEqual(args, {"max_nets": 4, "min_net_delay_ns": 0.2})
        self.assertEqual(issues, [])

    def test_sanitizer_accepts_runtime_optimized_directive(self):
        strategy, args, issues = sanitize_action(
            {"strategy": "PHYS_OPT", "args": {"directive": "RuntimeOptimized"}}
        )

        self.assertEqual(strategy, "PHYS_OPT")
        self.assertEqual(args, {"directive": "RuntimeOptimized"})
        self.assertEqual(issues, [])

    def test_cell_relocate_invalid_values_fall_back_to_bounded_defaults(self):
        strategy, args, issues = sanitize_action(
            {
                "strategy": "CELL_RELOCATE",
                "args": {
                    "num_paths": "many",
                    "detour_threshold": None,
                    "max_cells": 100,
                    "max_move_distance": -4,
                },
            }
        )

        self.assertEqual(strategy, "CELL_RELOCATE")
        self.assertEqual(
            args,
            {
                "num_paths": 10,
                "detour_threshold": 2.0,
                "max_cells": 5,
                "max_move_distance": 5,
            },
        )
        self.assertTrue(issues)

    def test_offline_planner_uses_zero_temperature(self):
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"strategy":"NO_OP","args":{}}'))]
            )

        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )

        result = call_planner(client, "model", "prompt", {"available_strategies": {"NO_OP": {}}})

        self.assertEqual(result, '{"strategy":"NO_OP","args":{}}')
        self.assertEqual(captured["temperature"], 0)

    def test_prompt_artifacts_are_written_as_utf8(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "prompt.txt"
            write_utf8_text(path, "bounded — local\n")

            text = path.read_bytes().decode("utf-8")

        self.assertIn("—", text)


if __name__ == "__main__":
    unittest.main()
