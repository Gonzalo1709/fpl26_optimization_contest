import os
import tempfile
import unittest
from pathlib import Path

from src.mcp import build_rapidwright_mcp_env
from validate_dcps import is_clock_port_name, simulation_tool_timeout


class ValidationEnvironmentTests(unittest.TestCase):
    def test_recognizes_clock_word_in_port_name(self):
        self.assertTrue(is_clock_port_name("clock_uncore_clock"))

    def test_simulation_tool_timeouts_extend_elaboration_only(self):
        self.assertEqual(simulation_tool_timeout(["xvlog"]), 300)
        self.assertEqual(simulation_tool_timeout(["xelab"]), 900)
        self.assertEqual(simulation_tool_timeout(["xsim"]), 600)

    def test_builds_validator_environment_from_vivado_java(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = Path(temporary_directory) / "repo"
            rapidwright_root = repo_root / "RapidWright"
            rapidwright_root.mkdir(parents=True)

            vivado_root = Path(temporary_directory) / "Vivado"
            vivado_executable = vivado_root / "bin" / "vivado"
            vivado_executable.parent.mkdir(parents=True)
            vivado_executable.touch()
            java_home = vivado_root / "tps" / "lnx64" / "jre11.0.16_1"
            java_executable = java_home / "bin" / "java"
            java_executable.parent.mkdir(parents=True)
            java_executable.touch()

            environment = build_rapidwright_mcp_env(
                repo_root,
                {"PATH": ""},
                vivado_exec=str(vivado_executable),
            )

            self.assertEqual(environment["JAVA_HOME"], str(java_home.resolve()))
            self.assertEqual(
                environment["RAPIDWRIGHT_PATH"],
                str(rapidwright_root.resolve()),
            )
            self.assertEqual(
                environment["CLASSPATH"],
                os.pathsep.join(
                    (
                        str((rapidwright_root / "bin").resolve()),
                        str((rapidwright_root / "jars" / "*").resolve()),
                    )
                ),
            )
            self.assertEqual(
                environment["PATH"].split(os.pathsep)[0],
                str((java_home / "bin").resolve()),
            )


if __name__ == "__main__":
    unittest.main()
