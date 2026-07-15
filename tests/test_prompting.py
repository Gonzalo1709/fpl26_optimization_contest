import unittest

from src.prompting import load_system_prompt


class PromptLoadingTests(unittest.TestCase):
    def test_repository_prompt_loads_as_utf8(self):
        prompt = load_system_prompt()

        self.assertIn("FPGA", prompt)
        self.assertIn("clk_fpl26contest", prompt)
        self.assertNotIn("\ufffd", prompt)


if __name__ == "__main__":
    unittest.main()
