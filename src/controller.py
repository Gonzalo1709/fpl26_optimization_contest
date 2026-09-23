"""Checkpoint transactions, adaptive portfolio, and shared search lifecycle."""

import asyncio
import json
import logging
import math
import os
import re
import shutil
import time
import uuid
from dataclasses import asdict, replace
from pathlib import Path

from src.admission import sha256_file, tcl_word, timing_constraint_digest
from src.analysis import DesignSignature
from src.economics import forecast_admission
from src.equivalence import prove_sequential_equivalence
from src.outcome_memory import OutcomeMemory, feature_vector, forecast
from src.policy import EligibleAction, should_attempt_reimplementation, apply_action_cooldowns
from src.search import SearchCandidate
from src.pact_search import EnablingPool, diverse_beam, physical_features
from src.submission import validate_submission
from src.meemar import DENSITIES, needs_rescue

logger = logging.getLogger(__name__)


class AdaptiveController:
    """Mixin: recipes operate on scratch state; only admission can update best."""

    def _init_controller(self):
        self._baseline_constraint_digest = None
        self._initial_port_digest = None
        self._baseline_candidate = None
        self._state_candidate = None
        self._loaded_sha256 = None
        self._candidate_evidence = {}
        self._attempts_by_state = {}
        self._outcomes = []
        self._memory = None
        self._run_id = uuid.uuid4().hex
        self._tool_version = None
        self._retiming_directives = ()
        self._part = None
        self._stop_reason = None
        self._golden_dcp = None
        self._policy_decisions = []
        cfg = self.generation_config
        self._enabling = EnablingPool(cfg.enabling_pool_size, cfg.enabling_max_depth,
                                     cfg.enabling_lifetime_seconds, cfg.enabling_regression_ns)
        self._enabling_seconds = 0.0
        self._action_evidence = None
        self._final_evidence = None
        self._delivered_candidate = None
        self._final_validation_ok = True
        self._admission_dir = self.run_dir / "admission"
        self._admission_dir.mkdir(parents=True, exist_ok=True)

    async def _constraint_digest(self) -> str:
        path = self._admission_dir / f"constraints-{uuid.uuid4().hex}.xdc"
        await self.v("run_tcl", {"command": f"write_xdc -force -type timing {tcl_word(str(path.resolve()))}", "timeout": 60})
        digest = timing_constraint_digest(path.read_text(encoding="utf-8"))
        if digest is None:
            raise ValueError("Timing constraint export contains no measurable clock definitions")
        return digest

    async def _port_digest(self) -> str:
        result = await self.v("run_tcl", {"command": """
set rows {}
foreach p [get_ports] {lappend rows [list [get_property NAME $p] [get_property DIRECTION $p]]}
puts "FPL26_PORTS_HEX=[binary encode hex [lsort $rows]]"
""", "timeout": 30})
        match = re.findall(r"(?m)^FPL26_PORTS_HEX=([0-9a-fA-F]+)\s*$", result)
        if not match:
            raise ValueError(
                "Port names and directions are unavailable: expected "
                f"FPL26_PORTS_HEX in Vivado response, received {result[:500]!r}"
            )
        return match[-1].lower()

    async def _refresh_current_evidence(self, candidate: SearchCandidate):
        """Re-measure physical evidence after a changed, admitted checkpoint.

        Optional failures clear the feature; they never reuse the previous
        topology. Timing and primitive counts remain tied to this checkpoint.
        """
        started = time.time()
        reports = {}

        async def optional(key, name, args):
            try:
                reports[key] = await self.v(name, args)
            except Exception as exc:
                if exc.__class__.__name__ == "WallClockLimitReached":
                    raise
                logger.warning("Evidence %s unavailable: %s", key, exc)
                reports[key] = None

        if self.generation_config.refresh_evidence:
            await optional("fanout", "get_critical_high_fanout_nets", {"num_paths": 50, "min_fanout": 100})
            await optional("anatomy", "run_tcl", {"command": "report_timing -to [get_clocks clk_fpl26contest] -max_paths 20 -nworst 1 -return_string", "timeout": 90})
            await optional("congestion", "run_tcl", {"command": "report_design_analysis -congestion -return_string", "timeout": 60})
            path = self._admission_dir / f"paths-{uuid.uuid4().hex}.json"
            try:
                await self.rw("read_checkpoint", {"dcp_path": str(candidate.dcp_path.resolve())})
                await self.v("extract_critical_path_cells", {"num_paths": 50, "output_file": str(path.resolve())})
                reports["paths"] = path.read_text(encoding="utf-8")
                reports["spread"] = await self.rw("analyze_critical_path_spread", {"input_file": str(path.resolve())})
            except Exception as exc:
                if exc.__class__.__name__ == "WallClockLimitReached":
                    raise
                logger.warning("Checkpoint spread unavailable: %s", exc)
                reports["paths"] = reports["spread"] = None
        await optional("cells", "run_tcl", {"command": 'puts "FPL26_PRIMITIVE_CELLS=[llength [get_cells -hier -filter {IS_PRIMITIVE}]]"', "timeout": 30})
        self.design_signature = DesignSignature.from_reports(
            target_clock="clk_fpl26contest", clock_period_ns=self.clock_period,
            wns_ns=candidate.wns, tns_ns=candidate.tns, failing_endpoints=candidate.failing_endpoints,
            high_fanout_report=reports.get("fanout") or "", spread_report=reports.get("spread"),
            critical_paths_report=reports.get("paths"), congestion_report=reports.get("congestion"),
            timing_anatomy_report=reports.get("anatomy"),
            primitive_cell_count=self._last_tagged_int(reports.get("cells") or "", "FPL26_PRIMITIVE_CELLS"),
            analysis_duration_seconds=time.time() - started,
        )
        self.critical_paths_report = reports.get("paths")
        self.high_fanout_nets = [(n.net_name, n.fanout, n.critical_path_count) for n in self.design_signature.high_fanout_candidates]
        candidate.evidence = self.design_signature.to_dict()
        self._candidate_evidence[candidate.candidate_id] = self.design_signature

    async def _restore_candidate_state(self, candidate: SearchCandidate):
        if not candidate.checkpoint_sha256 or sha256_file(candidate.dcp_path) != candidate.checkpoint_sha256:
            raise ValueError("Checkpoint hash differs from its admitted identity")
        if self._loaded_sha256 != candidate.checkpoint_sha256:
            await self.v("open_checkpoint", {"dcp_path": str(candidate.dcp_path.resolve()), "timeout": 120})
            # RapidWright is synchronized before every recipe that may inspect it.
            await self.rw("read_checkpoint", {"dcp_path": str(candidate.dcp_path.resolve())})
            self._loaded_sha256 = candidate.checkpoint_sha256
        self._state_candidate = candidate
        self.validation_status = candidate.validation
        self.design_signature = self._candidate_evidence.get(candidate.candidate_id)
        self._planning_history = self._attempts_by_state.setdefault(candidate.checkpoint_sha256, [])

    async def _snapshot_candidate(self, name: str, parent: SearchCandidate | None = None,
                                  *, retimed: bool = False) -> SearchCandidate:
        """Save, reopen, then attest the exact bytes that might be published."""
        self._loaded_sha256 = None
        path = self._admission_dir / f"{name}-{uuid.uuid4().hex}.dcp"
        await self._save_best_checkpoint(path)
        digest = sha256_file(path)
        await self.v("open_checkpoint", {"dcp_path": str(path.resolve()), "timeout": 120})
        metrics = await self._measure_current_metrics()
        if metrics["wns"] is None or not math.isfinite(metrics["wns"]):
            raise ValueError("Candidate lacks finite target-clock timing")
        constraints = await self._constraint_digest()
        if constraints != self._baseline_constraint_digest:
            raise ValueError("Candidate changed timing constraints")
        if await self._port_digest() != self._initial_port_digest:
            raise ValueError("Candidate changed port names or directions")
        status = await self._validate_current_publishable_design()
        if not status.implementation_passed:
            raise ValueError(f"Candidate implementation admission failed or is unknown: {asdict(status)}")
        proof = None
        if retimed or (parent and parent.equivalence_proof):
            # A new descendant is new bytes, so never reuse its parent's proof.
            golden = self._golden_dcp
            timeout = min(self.generation_config.equivalence_timeout_seconds,
                          self._current_budget_state().remaining_runtime_seconds - 30)
            proof = await prove_sequential_equivalence(
                self.generation_config.equivalence_command, golden, path,
                self._admission_dir / f"proof-{uuid.uuid4().hex}.json", timeout,
            )
        if sha256_file(path) != digest:
            raise ValueError("Candidate bytes changed during admission")
        candidate = SearchCandidate(
            candidate_id=name + "-" + uuid.uuid4().hex[:8], dcp_path=path,
            wns=metrics["wns"], tns=metrics["tns"], failing_endpoints=metrics["failing_endpoints"],
            peak_wns=max(metrics["wns"], parent.peak_wns) if parent and parent.peak_wns is not None else metrics["wns"],
            generation=parent.generation + 1 if parent else 0,
            parent_id=parent.candidate_id if parent else None, branch_index=0,
            steps_taken=parent.steps_taken + 1 if parent else 0, steps_since_peak=0,
            summary=name, checkpoint_sha256=digest, constraint_sha256=constraints,
            equivalence_proof=proof, **self._candidate_score_metadata(metrics["wns"], validation=status),
        )
        self.search_candidates.append(candidate)
        return candidate

    def _publish_admitted(self, candidate: SearchCandidate) -> bool:
        if not candidate.validation.implementation_passed or candidate.validation.failed:
            return False
        if self.best_candidate and not self._is_candidate_improvement(candidate, self.best_candidate):
            return False
        if candidate.constraint_sha256 != self._baseline_constraint_digest:
            return False
        if sha256_file(candidate.dcp_path) != candidate.checkpoint_sha256:
            raise ValueError("Refusing to publish an altered checkpoint")
        output = self.output_dcp
        if output is None:
            raise ValueError("Output path is not configured")
        if self.generation_config.strict_final_validation and candidate is not self._baseline_candidate:
            # Search incumbents are speculative until the final two-phase check.
            self.best_candidate = candidate
            self.best_wns = self._published_wns = candidate.wns
            self.validation_status = candidate.validation
            logger.info("Admitted search incumbent %s; final validation pending", candidate.candidate_id)
            return True
        output.parent.mkdir(parents=True, exist_ok=True)
        source = candidate.dcp_path
        digest = candidate.checkpoint_sha256
        if self.generation_config.strict_final_validation and candidate is self._baseline_candidate:
            source, digest = self._golden_dcp, self._input_sha256
        temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.wip")
        try:
            shutil.copyfile(source, temporary)
            with temporary.open("rb") as handle:
                os.fsync(handle.fileno())
            if sha256_file(temporary) != digest:
                raise ValueError("Checkpoint copy checksum failed")
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
        # No state assignment occurs before the atomic replacement succeeds.
        self.best_candidate = candidate
        self._delivered_candidate = replace(candidate, dcp_path=source, checkpoint_sha256=digest)
        self.best_wns = self._published_wns = candidate.wns
        self.validation_status = candidate.validation
        self._write_artifact_manifest()
        logger.info("Published %s: WNS %.4f ns", candidate.candidate_id, candidate.wns)
        return True

    def _write_artifact_manifest(self):
        if self.best_candidate is None:
            return
        candidate = self._delivered_candidate or self.best_candidate
        payload = {
            "schema_version": 1, "run_id": self._run_id, "candidate_id": candidate.candidate_id,
            "output_path": str(self.output_dcp), "sha256": candidate.checkpoint_sha256,
            "input_sha256": self._input_sha256, "constraint_sha256": candidate.constraint_sha256,
            "wns_ns": candidate.wns, "fmax_mhz": self.calculate_fmax(candidate.wns, self.clock_period),
            "target_clock": "clk_fpl26contest", "clock_period_ns": self.clock_period,
            "validation": asdict(candidate.validation), "equivalence_proof": candidate.equivalence_proof,
            "tool_version": self._tool_version, "part": self._part,
            "elapsed_seconds": (self.end_time or time.time()) - self.start_time,
            "llm_cost_usd": self.total_cost, "config": asdict(self.generation_config),
            "llm_cost_verified": not self._llm_cost_unknown,
            "stop_reason": self._stop_reason,
            "final_validation": self._final_evidence,
            "search_best_candidate_id": self.best_candidate.candidate_id,
        }
        target = self.run_dir / "published_artifact.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(target)

    def _adaptive_actions(self, actions):
        """Expand directive alternatives for predictions, then retain the best.

        Ineligible measured variants are removed from the actual schema, so the
        planner cannot resurrect them by supplying a non-default argument.
        """
        actions = list(actions)
        cfg = self.generation_config
        available = self._current_budget_state().remaining_runtime_seconds - cfg.validation_reserve_seconds
        sig = self.design_signature
        if (cfg.density_search and sig and self._state_candidate is self._baseline_candidate
                and self.validation_status.implementation_passed
                and sig.primitive_cell_count is not None
                and 0 < sig.primitive_cell_count <= cfg.density_max_cells
                and available >= max(cfg.density_min_seconds,
                                     self.measured_recipe_seconds.get("DENSITY_REIMPLEMENTATION", 0) * 1.2)
                and not any(a.strategy == "REIMPLEMENTATION" for a in actions)):
            actions.append(EligibleAction("DENSITY_REIMPLEMENTATION", {"density": .5},
                                          {"density": list(DENSITIES)},
                                          "resource-checked central region, fresh baseline placement, full routing"))
        if (cfg.targeted_actions and self.design_signature and self.validation_status.implementation_passed
                and not any(a.strategy == "REIMPLEMENTATION" for a in actions)):
            available = self._current_budget_state().remaining_runtime_seconds - cfg.validation_reserve_seconds
            if available >= 360 and (self.design_signature.timing_anatomy or {}).get("route_dominated"):
                actions.append(EligibleAction("CRITICAL_NET_REROUTE", {"max_nets": 4}, {},
                                              "current critical path terminal nets in a route-dominated design"))
                actions.append(EligibleAction("CRITICAL_BRANCH_REROUTE", {"max_pins": 4}, {},
                                              "bounded current critical sink branches, preserving other net branches"))
            spread = self.design_signature.path_spread
            if available >= 900 and spread and spread.paths_analyzed >= 3 and spread.avg_distance >= 30:
                actions.append(EligibleAction("PATH_LOCAL_REPLACE", {"max_cells": 20}, {},
                                              "movable terminal cells on spatially spread critical paths"))
                if cfg.meemar_rescue and needs_rescue(self._planning_history, cfg.min_wns_delta):
                    actions.append(EligibleAction("PATH_CLUSTER_REPLACE", {"max_cells": 80}, {},
                                                  "broader datapath rescue after neutral cheap physical optimization"))
            if any(a.strategy != "NO_OP" for a in actions):
                actions = [a for a in actions if a.strategy != "NO_OP"]
        actions = list(apply_action_cooldowns(actions, self._planning_history))
        signature = feature_vector(self.design_signature)
        budget = self._current_budget_state()
        elapsed = time.time() - self.start_time if self.start_time else 0
        penalty = 1 - 0.1 * (self.total_cost + elapsed / 3600)
        bank = max(0.0, (self.calculate_fmax(self._published_wns, self.clock_period) or 0)
                   - (self.calculate_fmax(self.initial_wns, self.clock_period) or 0))
        current_fmax = self.calculate_fmax(self._state_candidate.wns, self.clock_period) if self._state_candidate else None
        bank_fmax = self.calculate_fmax(self._published_wns, self.clock_period)
        deficit = max(0, bank_fmax - current_fmax) if bank_fmax is not None and current_fmax is not None else 0
        records = self._outcomes
        order = {name: index for index, name in enumerate((
            "TARGETED_REPLICATION", "SCOPED_PHYS_OPT", "PHYS_OPT", "GRANULAR_PHYS_OPT",
            "PARTIAL_REPLACE", "RETIME", "FULL_PLACE_ROUTE", "PLACEMENT_SHOT",
        ))}
        ranked = []
        for action in actions:
            if action.strategy == "NO_OP":
                continue
            key = next((k for k in ("directive", "flag", "density") if action.allowed_args.get(k)), None)
            variants = [{**action.default_args, key: value} for value in action.allowed_args[key]] if key else [action.default_args]
            retained = []
            for args in variants:
                estimate = forecast(records, signature, action.strategy, args, self._tool_version, self._part) if self._tool_version and self._part else None
                allowed, reason = (True, "score-based stopping disabled")
                if self.generation_config.score_aware_stopping:
                    allowed, reason = forecast_admission(
                        estimate, bank_gain_mhz=bank, penalty=penalty,
                        available_seconds=budget.remaining_runtime_seconds - budget.validation_reserve_seconds,
                        available_dollars=budget.remaining_cost_usd,
                        incumbent_deficit_mhz=deficit,
                    )
                self._policy_decisions.append({"state": self._state_candidate.candidate_id if self._state_candidate else None,
                                               "strategy": action.strategy, "args": args, "allowed": allowed,
                                               "reason": reason, "forecast": estimate})
                if allowed:
                    value = max(0, estimate["expected_gain_mhz"] - deficit) / max(1, estimate["seconds"]) if estimate else 0.0
                    retained.append((value, args))
            if retained:
                retained.sort(key=lambda pair: pair[0], reverse=True)
                default = retained[0][1]
                schema = {**action.allowed_args, key: [args[key] for _, args in retained]} if key else action.allowed_args
                prior = forecast(records, signature, action.strategy, default, self._tool_version, self._part) if self._tool_version and self._part else None
                reason = action.reason
                if prior:
                    reason = (f"{prior['samples']} similar outcomes: mean {prior['expected_gain_mhz']:.2f} MHz, "
                              f"p90 {prior['seconds']:.0f}s, success {prior['success_rate']:.0%}. {reason}")
                ranked.append((retained[0][0], -order.get(action.strategy, 100),
                               replace(action, default_args=default, allowed_args=schema, reason=reason)))
        ranked.sort(key=lambda item: item[:2], reverse=True)
        return tuple(item[2] for item in ranked) or (EligibleAction("NO_OP", reason="no admissible action has credible remaining value"),)

    async def _attempt(self, parent: SearchCandidate, strategy: str, args: dict, *, llm_cost: float = 0) -> SearchCandidate:
        await self._restore_candidate_state(parent)
        permitted = next((a for a in self._eligible_actions() if a.strategy == strategy), None)
        if (strategy == "REIMPLEMENTATION" and parent is self._baseline_candidate
                and should_attempt_reimplementation(self.design_signature, self._current_budget_state())):
            permitted = next((a for a in self._adaptive_actions((EligibleAction("REIMPLEMENTATION"),))
                              if a.strategy == strategy), None)
        if permitted is None:
            raise ValueError(f"Action {strategy} is no longer eligible on this exact seed")
        for key, values in permitted.allowed_args.items():
            if key in args and isinstance(values, (tuple, list)) and args[key] not in values:
                raise ValueError(f"Action parameter {key} is outside the current-seed contract")
        started = time.time()
        self._action_evidence = None
        before_features = feature_vector(self.design_signature)
        record = {"run_id": self._run_id, "state_sha256": parent.checkpoint_sha256,
                  "attempted_from_state": True,
                  "features": before_features, "strategy": strategy, "args": args,
                  "tool_version": self._tool_version, "part": self._part,
                  "llm_cost_usd": llm_cost, "previous_wns": parent.wns,
                  "implementation_passed": False, "delta_fmax_mhz": None}
        record["action_contract"] = {"seed_sha256": parent.checkpoint_sha256,
                                     "strategy": strategy, "args": args,
                                     "reason": permitted.reason,
                                     "physical_before": physical_features(parent)}
        record["search_context"] = {"incumbent_wns": self.best_candidate.wns,
                                    "seed_wns": parent.wns, "prior_attempts_on_seed": len(self._planning_history)}
        child = None
        try:
            self._loaded_sha256 = None
            await self._execute_strategy(strategy, args)
            child = await self._snapshot_candidate(strategy.lower(), parent, retimed=strategy == "RETIME")
            record.update(wns=child.wns, delta_wns=child.wns - parent.wns,
                          implementation_passed=True, validation=asdict(child.validation),
                          delta_fmax_mhz=self.calculate_fmax(child.wns, self.clock_period) - self.calculate_fmax(parent.wns, self.clock_period),
                          candidate_sha256=child.checkpoint_sha256, equivalence_proof=child.equivalence_proof)
            self._publish_admitted(child)
            neutral = abs(child.wns - parent.wns) <= self.generation_config.min_wns_delta
            if self._current_budget_state().remaining_runtime_seconds > self.generation_config.validation_reserve_seconds:
                await self._refresh_current_evidence(child)
            record["action_evidence"] = self._action_evidence
            record["physical_after"] = physical_features(child)
            if child.wns <= parent.wns + self.generation_config.min_wns_delta:
                record["enabling_retained"] = self._enabling.retain(parent, child, strategy, time.time())
            if neutral:
                # A no-op checkpoint has a different container hash after writing;
                # preserve the same search state so it cannot evade cooldowns.
                child = None
            await self._restore_candidate_state(child or parent)
        except Exception as exc:
            record.update(error=str(exc), wns=None, delta_wns=None)
            if exc.__class__.__name__ == "WallClockLimitReached" or isinstance(exc, asyncio.TimeoutError):
                raise
            logger.warning("Recipe %s rejected: %s", strategy, exc)
            child = None
            await self._restore_candidate_state(parent)
        finally:
            record["action_evidence"] = self._action_evidence
            record["runtime_attribution"] = "recipe_wall_total"
            record["tool_session_uncertain"] = self._tool_session_poisoned
            record["llm_cost_verified"] = not self._llm_cost_unknown
            record["elapsed_seconds"] = max(0.0, time.time() - started)
            self.history.append(record)
            self._attempts_by_state.setdefault(parent.checkpoint_sha256, []).append(record)
            self._outcomes.append(record)
            self.measured_recipe_seconds[strategy] = record["elapsed_seconds"]
            with (self.run_dir / "recipe_outcomes.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, allow_nan=False) + "\n")
            if self._memory:
                try:
                    self._memory.append(record)
                except Exception as exc:
                    logger.warning("Persistent memory unavailable; run-local outcomes retained: %s", exc)
        return child or parent

    async def _initialize_search(self, input_dcp: Path, output_dcp: Path) -> str:
        self.start_time = time.time()
        self.output_dcp = output_dcp.resolve()
        if self.output_dcp == input_dcp.resolve():
            raise ValueError("Output must differ from the original input checkpoint")
        self._input_sha256 = sha256_file(input_dcp)
        self._golden_dcp = self._admission_dir / f"golden-{self._run_id}.dcp"
        shutil.copyfile(input_dcp, self._golden_dcp)
        if sha256_file(self._golden_dcp) != self._input_sha256:
            raise ValueError("Golden checkpoint copy did not preserve the original bytes")
        if self.generation_config.outcome_memory_path:
            try:
                self._memory = OutcomeMemory(self.generation_config.outcome_memory_path)
                self._outcomes = self._memory.records()
            except Exception as exc:
                logger.warning("Starting with run-local memory: %s", exc)
        analysis = await self.perform_initial_analysis(input_dcp)
        original_evidence = self.design_signature
        result = await self.v("run_tcl", {"command": 'puts "FPL26_VERSION=[version -short]"; puts "FPL26_PART=[get_property PART [current_design]]"'})
        version = re.search(r"(?m)^FPL26_VERSION=(.+)$", result)
        part = re.search(r"(?m)^FPL26_PART=(.+)$", result)
        self._tool_version = version.group(1).strip() if version else None
        self._part = part.group(1).strip() if part else None
        if self.generation_config.enable_retiming:
            # The running Vivado installation is authoritative for directive
            # support. Unavailable help or a different device leaves it blocked.
            try:
                help_text = await self.v("run_tcl", {"command": "help -args phys_opt_design", "timeout": 30})
                if self._part and self._tool_version:
                    self._retiming_directives = tuple(name for name in ("AddRetime", "AlternateFlowWithRetiming") if name in help_text)
            except Exception as exc:
                logger.warning("Retiming capability unavailable: %s", exc)
        self._baseline_constraint_digest = await self._constraint_digest()
        self._initial_port_digest = await self._port_digest()
        self._initial_port_count = await self._current_port_count()
        baseline = await self._snapshot_candidate("baseline")
        self._baseline_candidate = baseline
        self.initial_wns, self.initial_tns, self.initial_failing_endpoints = baseline.wns, baseline.tns, baseline.failing_endpoints
        baseline.projected_score = 0.0
        if original_evidence is not None:
            unavailable = set(original_evidence.unavailable) - {"wns", "tns", "failing_endpoints"}
            if baseline.tns is None:
                unavailable.add("tns")
            if baseline.failing_endpoints is None:
                unavailable.add("failing_endpoints")
            original_evidence = replace(original_evidence, wns_ns=baseline.wns, tns_ns=baseline.tns,
                                        failing_endpoints=baseline.failing_endpoints,
                                        unavailable=tuple(sorted(unavailable)),
                                        fmax_mhz=self.calculate_fmax(baseline.wns, self.clock_period))
        self._candidate_evidence[baseline.candidate_id] = original_evidence
        baseline.evidence = original_evidence.to_dict() if original_evidence else None
        self._publish_admitted(baseline)
        await self._restore_candidate_state(baseline)
        return analysis

    async def optimize(self, input_dcp: Path, output_dcp: Path) -> bool:
        try:
            analysis = await self._initialize_search(input_dcp, output_dcp)
            remaining = self._current_budget_state().remaining_runtime_seconds
            search_seconds = remaining - self.generation_config.validation_reserve_seconds
            if search_seconds > 0:
                await asyncio.wait_for(self._search_portfolio(analysis, generations=self.generation_config.enabled),
                                       search_seconds)
        except Exception as exc:
            self._stop_reason = f"stopped: {exc}"
            if self.best_candidate is None:
                logger.exception("Optimizer stopped before any output was admitted")
            else:
                logger.exception("Optimizer stopped; retaining the admitted output")
        await self._finalize_submission()
        return self._finish_search()

    async def _finalize_submission(self):
        if not self.generation_config.strict_final_validation or self.best_candidate is None:
            return
        candidate = self.best_candidate
        try:
            if sha256_file(self._golden_dcp) != self._input_sha256:
                raise ValueError("Golden checkpoint changed after initialization")
            if candidate is self._baseline_candidate:
                self._final_evidence = {"method": "unchanged_input_identity", "sha256": self._input_sha256}
                source, digest = self._golden_dcp, self._input_sha256
            else:
                if sha256_file(candidate.dcp_path) != candidate.checkpoint_sha256:
                    raise ValueError("Selected checkpoint changed after admission")
                # Close search servers before spawning the validator's own tools.
                # MCP's AsyncExitStack owns task-local AnyIO cancel scopes:
                # close in the task that opened them, never via wait_for's task.
                await self.cleanup()
                timeout = min(self.generation_config.final_validation_timeout_seconds,
                              self.generation_config.wall_clock_limit_seconds - (time.time()-self.start_time) - 15)
                self._final_evidence = await validate_submission(
                    self._golden_dcp, candidate.dcp_path, self.run_dir, timeout,
                    self.generation_config.final_validation_vectors)
                source, digest = candidate.dcp_path, candidate.checkpoint_sha256
            candidate.validation = replace(candidate.validation, structural_passed=True, simulation_passed=True)
        except Exception as exc:
            logger.exception("Final candidate rejected; restoring original input")
            self._final_validation_ok = False
            self._stop_reason = f"final validation failed: {exc}"
            self._final_evidence = {"passed": False, "error": str(exc), "fallback": "unchanged_input_identity",
                                    "attempted_sha256": candidate.checkpoint_sha256,
                                    "golden_sha256": self._input_sha256}
            candidate = self._baseline_candidate
            source, digest = self._golden_dcp, self._input_sha256
            candidate.validation = replace(candidate.validation, structural_passed=True, simulation_passed=True)
        if sha256_file(source) != digest:
            raise ValueError("Final artifact changed before publication")
        temporary = self.output_dcp.with_name(f".{self.output_dcp.name}.{uuid.uuid4().hex}.wip")
        try:
            shutil.copyfile(source, temporary)
            if sha256_file(temporary) != digest:
                raise ValueError("Final artifact copy changed bytes")
            temporary.replace(self.output_dcp)
        finally:
            temporary.unlink(missing_ok=True)
        # Baseline fallback is the original bytes, rather than a rewritten DCP.
        if candidate is self._baseline_candidate:
            candidate = replace(candidate, dcp_path=self._golden_dcp, checkpoint_sha256=digest)
        self.best_candidate = self._delivered_candidate = candidate
        for key, value in self._candidate_score_metadata(candidate.wns, validation=candidate.validation).items():
            setattr(candidate, key, value)

    def _finish_search(self) -> bool:
        self.end_time = time.time()
        if self.best_candidate is None:
            self.best_wns = float("-inf")
            return False
        self.best_wns = self._published_wns = self.best_candidate.wns
        self.validation_status = self.best_candidate.validation
        valid_output = self.output_dcp.is_file() and sha256_file(self.output_dcp) == self.best_candidate.checkpoint_sha256
        if not valid_output:
            self._stop_reason = "output missing or changed since admission"
        self._write_artifact_manifest()
        (self.run_dir / "policy_decisions.json").write_text(json.dumps(self._policy_decisions, indent=2), encoding="utf-8")
        (self.run_dir / "enabling_moves.json").write_text(json.dumps(self._enabling.events, indent=2), encoding="utf-8")
        self._print_optimization_summary()
        return valid_output and self._final_validation_ok

    async def _search_portfolio(self, analysis: str, *, generations: bool):
        cfg = self.generation_config
        roots = [self._baseline_candidate]
        current = self._baseline_candidate
        if cfg.stop_when_timing_met and self.best_candidate.wns >= 0:
            self._stop_reason = "explicit timing-closure stop"
            return
        if (not cfg.meemar_rescue and not self.force_strategy and self.design_signature is not None
                and should_attempt_reimplementation(self.design_signature, self._current_budget_state())
                and self._adaptive_actions((EligibleAction("REIMPLEMENTATION"),))[0].strategy != "NO_OP"):
            # Preserve the original independent RQS/Explore lane. Its parent is
            # always the pristine baseline, not a previously optimized placement.
            self.iteration += 1
            reimplemented = await self._attempt(current, "REIMPLEMENTATION", {})
            if reimplemented is not current:
                roots.append(reimplemented)
            current = self.best_candidate
            if cfg.stop_when_timing_met and self.best_candidate.wns >= 0:
                self._stop_reason = "explicit timing-closure stop"
                return
        # Deterministic first moves spend no LLM calls. They use the same policy,
        # admission, cost forecast and outcome recording as the later branches.
        for _ in range(cfg.deterministic_steps):
            if self._should_stop_for_budget():
                break
            await self._restore_candidate_state(current)
            actions = self._eligible_actions()
            action = next((a for a in actions if a.strategy == self.force_strategy), None) if self.force_strategy else actions[0]
            if action is None:
                break
            if action.strategy == "NO_OP":
                break
            self.iteration += 1
            current = await self._attempt(current, action.strategy, dict(action.default_args))
            if cfg.stop_when_timing_met and self.best_candidate.wns >= 0:
                self._stop_reason = "explicit timing-closure stop"
                return
        if all(self.best_candidate is not root for root in roots):
            roots.append(self.best_candidate)
        # Independent density trials share the immutable baseline, not the
        # preceding trial's pblock or placement. Fresh policy/ROI checks apply.
        if cfg.density_search and not self.force_strategy:
            for density in DENSITIES:
                if self._should_stop_for_budget():
                    break
                await self._restore_candidate_state(self._baseline_candidate)
                action = next((a for a in self._eligible_actions()
                               if a.strategy == "DENSITY_REIMPLEMENTATION"), None)
                if action is None or density not in action.allowed_args["density"]:
                    continue
                self.iteration += 1
                result = await self._attempt(self._baseline_candidate, action.strategy, {"density": density})
                roots.append(result)
                if cfg.stop_when_timing_met and self.best_candidate.wns >= 0:
                    return
            roots = diverse_beam([*roots, self.best_candidate], cfg.beam_width if generations else 1,
                                 self._candidate_sort_key, cfg.physical_diversity)
        await self._restore_candidate_state(self._baseline_candidate)
        if (cfg.meemar_rescue and not self.force_strategy
                and self.best_candidate.wns <= self._baseline_candidate.wns + cfg.min_wns_delta
                and self.design_signature is not None
                and should_attempt_reimplementation(self.design_signature, self._current_budget_state())
                and self._adaptive_actions((EligibleAction("REIMPLEMENTATION"),))[0].strategy != "NO_OP"):
            # Preserve the original independent RQS/Explore lane. Its parent is
            # always the pristine baseline, not a previously optimized placement.
            self.iteration += 1
            reimplemented = await self._attempt(self._baseline_candidate, "REIMPLEMENTATION", {})
            if reimplemented is not current:
                roots.append(reimplemented)
            current = self.best_candidate
            if cfg.stop_when_timing_met and self.best_candidate.wns >= 0:
                self._stop_reason = "explicit timing-closure stop"
                return
        roots = diverse_beam([*roots, self.best_candidate], cfg.beam_width if generations else 1,
                             self._candidate_sort_key, cfg.physical_diversity)
        if not generations:
            roots = [self.best_candidate]
        max_generations = cfg.max_generations if generations else max(cfg.max_llm_calls, cfg.max_generations * cfg.max_steps_per_branch)
        for generation in range(max_generations):
            results = []
            for parent in roots:
                for branch in range(cfg.branch_factor if generations else 1):
                    current = parent
                    for step in range(cfg.max_steps_per_branch if generations else 1):
                        if self._should_stop_for_budget():
                            return
                        await self._restore_candidate_state(current)
                        actions = self._eligible_actions()
                        if actions[0].strategy == "NO_OP":
                            self._stop_reason = actions[0].reason
                            break
                        choice = None
                        cost_before = self.total_cost
                        if self.force_strategy:
                            requested = next((a for a in actions if a.strategy == self.force_strategy), None)
                            if requested is None:
                                break
                            choice = (requested.strategy, requested.default_args)
                        elif generation == 0 and branch > 0:
                            action = actions[min(branch, len(actions) - 1)]
                            choice = (action.strategy, action.default_args)
                        elif (not self._llm_cost_unknown and self.llm_call_count < cfg.max_llm_calls
                              and self._current_budget_state().remaining_cost_usd > 0):
                            payload = self._build_decision_input(analysis, current.steps_since_peak,
                                                                self._planning_history[-5:])
                            choice = self.sanitize_action(await self.choose_action_llm(payload))
                        else:
                            action = actions[0]
                            choice = (action.strategy, action.default_args)
                        strategy, args = choice
                        if strategy == "NO_OP":
                            break
                        self.iteration += 1
                        previous = current
                        current = await self._attempt(current, strategy, args, llm_cost=max(0, self.total_cost - cost_before))
                        if current is not previous:
                            current.steps_since_peak = 0 if current.wns > previous.peak_wns else previous.steps_since_peak + 1
                        # In economic mode, patience is diagnostic; only exhausted
                        # actions, measured ROI or the explicit search bounds stop.
                        elif not cfg.score_aware_stopping:
                            current = replace(current, steps_since_peak=current.steps_since_peak + 1)
                        if cfg.stop_when_timing_met and self.best_candidate.wns >= 0:
                            self._stop_reason = "explicit timing-closure stop"
                            return
                        if not cfg.score_aware_stopping and current.steps_since_peak >= cfg.max_steps_without_improvement:
                            break
                    results.append(current)
            if not results:
                break
            unique = {c.checkpoint_sha256: c for c in [*results, self.best_candidate]}
            roots = diverse_beam(unique.values(), cfg.beam_width if generations else 1,
                                 self._candidate_sort_key, cfg.physical_diversity)
            # One prescribed follow-up per retained state; consumes the ordinary
            # wall-clock reserve and a separate total enabling-work allowance.
            for move in self._enabling.take(time.time()):
                if time.time() >= move.deadline:
                    self._enabling.events.append({"state": move.candidate.checkpoint_sha256, "status": "expired_before_execution"})
                    continue
                if self._enabling_seconds >= cfg.enabling_budget_seconds or self._should_stop_for_budget():
                    break
                await self._restore_candidate_state(move.candidate)
                action = next((a for a in self._eligible_actions() if a.strategy == move.followup), None)
                if action is None:
                    continue
                if cfg.enabling_budget_seconds - self._enabling_seconds < 360:
                    break
                started = time.time()
                self.iteration += 1
                allowance = min(cfg.enabling_budget_seconds - self._enabling_seconds,
                                self._current_budget_state().remaining_runtime_seconds - cfg.validation_reserve_seconds)
                try:
                    result = await asyncio.wait_for(
                        self._attempt(move.candidate, action.strategy, dict(action.default_args)), allowance)
                finally:
                    self._enabling_seconds += time.time() - started
                roots = diverse_beam([*roots, result], cfg.beam_width if generations else 1,
                                     self._candidate_sort_key, cfg.physical_diversity)
            if all(not any(a.strategy != "NO_OP" for a in self._actions_for_candidate(c)) for c in roots):
                self._stop_reason = "all surviving states exhausted admissible actions"
                break
        self._stop_reason = self._stop_reason or "configured search bound reached"

    def _actions_for_candidate(self, candidate):
        saved = self.design_signature, self.validation_status, self._planning_history, self._state_candidate
        try:
            self.design_signature = self._candidate_evidence.get(candidate.candidate_id)
            self.validation_status = candidate.validation
            self._planning_history = self._attempts_by_state.get(candidate.checkpoint_sha256, [])
            self._state_candidate = candidate
            return self._eligible_actions()
        finally:
            self.design_signature, self.validation_status, self._planning_history, self._state_candidate = saved

    async def run_single_method(self, input_dcp: Path, output_dcp: Path, method: str,
                                *, top_n_nets: int = 5, phys_opt_directive: str = "Default") -> bool:
        try:
            await self._initialize_search(input_dcp, output_dcp)
            action = next((a for a in self._eligible_actions() if a.strategy == method), None)
            if action is None:
                raise ValueError(f"Single method {method} is not eligible for this state and budget")
            args = dict(action.default_args)
            if method == "FANOUT":
                args["top_n_nets"] = min(10, max(1, top_n_nets))
            if method in {"PHYS_OPT", "PHYS_OPT_REROUTE", "RETIME"} and phys_opt_directive in action.allowed_args.get("directive", []):
                args["directive"] = phys_opt_directive
            allowance = self._current_budget_state().remaining_runtime_seconds - self.generation_config.validation_reserve_seconds
            if allowance <= 0:
                raise TimeoutError("No transform budget beyond validation reserve")
            await asyncio.wait_for(self._attempt(self._baseline_candidate, method, args), allowance)
            self._stop_reason = "single method completed"
        except Exception as exc:
            self._stop_reason = f"single method stopped: {exc}"
            await self._finalize_submission()
            self._finish_search()
            return False
        await self._finalize_submission()
        return self._finish_search()
