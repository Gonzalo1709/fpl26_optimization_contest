"""MCP server helper utilities for the FPGA optimizer."""

from collections.abc import Mapping
import os
from pathlib import Path
import shutil


def _resolve_java_home(
	base_env: Mapping[str, str],
	vivado_exec: str | None,
) -> Path | None:
	"""Resolve Java from the environment, PATH, or Vivado's bundled runtime."""
	configured_home = base_env.get("JAVA_HOME")
	if configured_home:
		return Path(configured_home).expanduser().resolve()

	java_executable = shutil.which("java", path=base_env.get("PATH"))
	if java_executable:
		return Path(java_executable).resolve().parent.parent

	configured_vivado = vivado_exec or base_env.get("VIVADO_EXEC")
	if configured_vivado:
		vivado_path = Path(configured_vivado).expanduser()
		if not vivado_path.is_absolute():
			resolved_vivado = shutil.which(str(vivado_path), path=base_env.get("PATH"))
			if not resolved_vivado:
				return None
			vivado_path = Path(resolved_vivado)
	else:
		resolved_vivado = shutil.which("vivado", path=base_env.get("PATH"))
		if not resolved_vivado:
			return None
		vivado_path = Path(resolved_vivado)

	vivado_root = vivado_path.resolve().parent.parent
	java_candidates = sorted(
		candidate
		for pattern in (
			"tps/lnx64/jre*/bin/java",
			"tps/lnx64/jre*/bin/java.exe",
		)
		for candidate in vivado_root.glob(pattern)
	)
	if not java_candidates:
		return None
	return java_candidates[0].resolve().parent.parent


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
	*,
	vivado_exec: str | None = None,
) -> dict[str, str]:
	"""Build the environment for the RapidWright MCP server."""
	env = dict(base_env or {})
	rapidwright_submodule = (script_dir / "RapidWright").resolve()
	if rapidwright_submodule.is_dir() and "RAPIDWRIGHT_PATH" not in env:
		env["RAPIDWRIGHT_PATH"] = str(rapidwright_submodule)
		env["CLASSPATH"] = os.pathsep.join(
			(
				str(rapidwright_submodule / "bin"),
				str(rapidwright_submodule / "jars" / "*"),
			)
		)

	java_home = _resolve_java_home(env, vivado_exec)
	if java_home is None:
		raise RuntimeError(
			"Unable to locate Java. Set JAVA_HOME, put java on PATH, or set "
			"VIVADO_EXEC to a Vivado installation with a bundled JRE."
		)
	env["JAVA_HOME"] = str(java_home)
	java_bin = str(java_home / "bin")
	path_entries = env.get("PATH", "").split(os.pathsep) if env.get("PATH") else []
	if java_bin not in path_entries:
		env["PATH"] = os.pathsep.join((java_bin, *path_entries))
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
