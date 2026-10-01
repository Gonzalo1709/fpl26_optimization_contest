"""Versioned, validated run settings shared by CLI, workers, and dashboards."""

import hashlib
import itertools
import json
import math
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROFILES = ("fast", "balanced", "cost", "quality")
METHODS = ("PHYS_OPT", "PHYS_OPT_REROUTE", "FANOUT", "PBLOCK", "CELL_RELOCATE", "HARD_BLOCK",
           "PLACEMENT_SHOT", "FULL_PLACE_ROUTE", "CRITICAL_PIN", "ROUTE_PRESERVE",
           "GRANULAR_PHYS_OPT", "SCOPED_PHYS_OPT", "PARTIAL_REPLACE", "TARGETED_REPLICATION", "RETIME")
INTEGER_OPTIONS = {"branches", "beam_width", "generations", "steps_per_branch",
                   "steps_without_improvement", "max_llm_calls", "top_n_nets", "max_nets"}
NONNEGATIVE_OPTIONS = {"min_wns_delta", "min_wns_per_minute", "validation_reserve_seconds",
                       "deterministic_steps"}
CHOICE_OPTIONS = {"search_mode": ("generations", "linear"),
                  "strategy_effort": ("fast", "balanced", "thorough"),
                  "phys_opt_directive": ("Default", "RuntimeOptimized", "Explore", "AggressiveExplore",
                                         "AddRetime", "AlternateFlowWithRetiming")}
BOOLEAN_OPTIONS = {"debug", "stop_when_timing_met", "no_outcome_memory", "no_score_aware_stopping", "enable_retiming"}
PATH_OPTIONS = {"system_prompt", "equivalence_command", "outcome_memory"}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class RunConfig:
    input_dcp: str
    python: str = sys.executable
    mode: str = "deterministic"
    profile: str = "fast"
    model: str = ""
    max_runtime_minutes: float = 60.0
    max_cost: float | None = None
    method: str = "PHYS_OPT"
    advanced: dict = field(default_factory=dict)
    schema_version: int = 1

    def validate(self, *, check_files=True):
        if not isinstance(self.advanced, dict):
            raise ValueError("Advanced settings must be a JSON object")
        if not isinstance(self.input_dcp, str) or not isinstance(self.python, str) or not isinstance(self.model, str):
            raise ValueError("Checkpoint, executable, and model must be strings")
        if self.schema_version != 1:
            raise ValueError("Unsupported configuration schema")
        if self.mode not in {"llm", "deterministic", "test", "single"}:
            raise ValueError("Unknown run mode")
        if self.profile not in PROFILES or self.method not in METHODS:
            raise ValueError("Unknown profile or optimization method")
        if self.mode == "llm" and not self.model.strip():
            raise ValueError("Select a model for LLM mode")
        for name, value in [("runtime", self.max_runtime_minutes), ("cost", self.max_cost)]:
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be positive and finite")
        if self.max_runtime_minutes is None:
            raise ValueError("A runtime budget is required")
        for name, value in self.advanced.items():
            if name in INTEGER_OPTIONS:
                valid = type(value) is int and value >= 1
            elif name in NONNEGATIVE_OPTIONS:
                valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
                if name == "deterministic_steps":
                    valid = type(value) is int and value >= 0
            elif name in CHOICE_OPTIONS:
                valid = value in CHOICE_OPTIONS[name]
            elif name in BOOLEAN_OPTIONS:
                valid = type(value) is bool
            elif name in PATH_OPTIONS:
                valid = isinstance(value, str) and bool(value.strip())
            else:
                raise ValueError(f"Unsupported advanced setting: {name}")
            if not valid:
                raise ValueError(f"Invalid value for {name}")
        if check_files:
            source = Path(self.input_dcp).expanduser()
            if source.suffix.lower() != ".dcp" or not source.is_file():
                raise ValueError("Input must be an existing .dcp file")
            if not (Path(self.python).is_file() or shutil.which(self.python)):
                raise ValueError("Python executable not found")
            for name in PATH_OPTIONS - {"outcome_memory"}:
                if name in self.advanced and not Path(self.advanced[name]).expanduser().is_file():
                    raise ValueError(f"File not found for {name}")
        if self.advanced.get("enable_retiming") and not self.advanced.get("equivalence_command"):
            raise ValueError("Retiming requires an equivalence command file")
        return self

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        return cls(**value).validate(check_files=False)

    def argv(self, repository: Path, output: Path) -> list[str]:
        self.validate()
        args = [self.python, "-u", str(repository / "dcp_optimizer.py"),
                str(Path(self.input_dcp).expanduser().resolve()), "--output", str(output.resolve()),
                "--run-dir", str(output.parent / "run"),
                "--budget-profile", self.profile, "--max-runtime-minutes", str(self.max_runtime_minutes),
                "--wall-clock-limit-seconds", str(self.max_runtime_minutes * 60)]
        if self.mode == "deterministic":
            args.append("--no-llm")
        elif self.mode == "test":
            args.append("--test")
        elif self.mode == "single":
            args.extend(["--single-method", self.method])
        if self.model:
            args.extend(["--model", self.model])
        if self.max_cost is not None:
            args.extend(["--max-cost", str(self.max_cost)])
        for name, value in sorted(self.advanced.items()):
            flag = "--" + name.replace("_", "-")
            if name in BOOLEAN_OPTIONS:
                if value:
                    args.append(flag)
            else:
                args.extend([flag, str(Path(value).expanduser().resolve()) if name in PATH_OPTIONS else str(value)])
        return args


def expand_sweep(base: RunConfig, designs: list[str], axes: dict, limit=256) -> list[RunConfig]:
    """Bound the Cartesian product before creating any queue records."""
    allowed = {"profile", "model", "mode", "method", "max_runtime_minutes", "max_cost"} | INTEGER_OPTIONS | NONNEGATIVE_OPTIONS | CHOICE_OPTIONS.keys() | BOOLEAN_OPTIONS | PATH_OPTIONS
    if not isinstance(axes, dict) or not designs or any(key not in allowed or not isinstance(values, list) or not values
                          for key, values in axes.items()):
        raise ValueError("Choose designs and nonempty lists of supported sweep settings")
    count = len(designs) * math.prod(len(values) for values in axes.values())
    if count > limit:
        raise ValueError(f"Sweep exceeds {limit} jobs")
    configs = []
    for design in designs:
        for values in itertools.product(*axes.values()):
            payload = base.to_dict()
            payload["input_dcp"] = design
            payload["advanced"] = dict(base.advanced)
            for key, value in zip(axes, values):
                if key in payload:
                    payload[key] = value
                else:
                    payload["advanced"][key] = value
            configs.append(RunConfig.from_dict(payload).validate())
    return configs


def check_environment(python: str, repository: Path) -> dict:
    """Probe the selected runtime, without loading FPGA tools or exposing secrets."""
    script = """import importlib.util,json,os,shutil,sys
print(json.dumps({'python':sys.version.split()[0], 'modules':{n:importlib.util.find_spec(n) is not None for n in ['openai','mcp','pexpect','rapidwright']}, 'vivado':shutil.which(os.environ.get('VIVADO_EXEC','vivado')), 'java':shutil.which('java'), 'java_home':bool(os.environ.get('JAVA_HOME')), 'api_key_present':bool(os.environ.get('OPENROUTER_API_KEY'))}))"""
    result = subprocess.run([python, "-c", script], capture_output=True, text=True,
                            timeout=15, cwd=repository)
    if result.returncode:
        raise ValueError("Selected Python could not run the environment probe")
    return json.loads(result.stdout)
