"""MCP server helper utilities for the FPGA optimizer."""

from collections.abc import Mapping
from pathlib import Path


def convert_mcp_tool_to_openai(tool, server_prefix: str) -> dict:
	"""Convert MCP tool definition to OpenAI-compatible format with server prefix."""
	schema = tool.inputSchema or {"type": "object", "properties": {}}
	return {
		"type": "function",
		"function": {
			"name": f"{server_prefix}_{tool.name}",
			"description": tool.description or "",
			"parameters": {
				"type": "object",
				"properties": schema.get("properties", {}),
				"required": schema.get("required", []),
			},
		},
	}


def build_rapidwright_mcp_env(
	script_dir: Path,
	base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
	"""Build the environment for the RapidWright MCP server."""
	env = dict(base_env or {})
	rapidwright_submodule = script_dir / "RapidWright"
	if rapidwright_submodule.is_dir() and "RAPIDWRIGHT_PATH" not in env:
		env["RAPIDWRIGHT_PATH"] = str(rapidwright_submodule)
		env["CLASSPATH"] = f"{rapidwright_submodule}/bin:{rapidwright_submodule}/jars/*"
	return env


def build_rapidwright_mcp_args(script_dir: Path, debug: bool) -> list[str]:
	"""Build command-line args for the RapidWright MCP server."""
	args = [str(script_dir / "RapidWrightMCP" / "server.py")]
	if not debug:
		# Log paths are added by the caller when running in non-debug mode.
		pass
	return args


def build_vivado_mcp_args(script_dir: Path, debug: bool) -> list[str]:
	"""Build command-line args for the Vivado MCP server."""
	args = [str(script_dir / "VivadoMCP" / "vivado_mcp_server.py")]
	if not debug:
		# Log paths are added by the caller when running in non-debug mode.
		pass
	return args
