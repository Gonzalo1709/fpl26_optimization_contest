"""Serializable, target-clock-specific design analysis records."""

from dataclasses import asdict, dataclass

from src.parsers import (
    parse_congestion_report,
    parse_critical_hard_block_topology,
    parse_critical_hard_block_types,
    parse_high_fanout_nets_report,
    parse_spread_analysis,
    parse_timing_anatomy_report,
)
from src.scoring import target_clock_fmax_mhz


def require_target_clock_wns(wns_ns: float | None) -> float:
    """Reject analysis that cannot authoritatively measure the contest clock."""
    if wns_ns is None:
        raise RuntimeError("Unable to measure WNS for required clock clk_fpl26contest")
    return wns_ns


@dataclass(frozen=True)
class HighFanoutCandidate:
    net_name: str
    fanout: int
    critical_path_count: int


@dataclass(frozen=True)
class PathSpread:
    max_distance: float
    avg_distance: float
    paths_analyzed: int


@dataclass(frozen=True)
class DesignSignature:
    """Bounded evidence used by deterministic recipe gates."""

    target_clock: str
    clock_period_ns: float | None
    wns_ns: float | None
    tns_ns: float | None
    failing_endpoints: int | None
    fmax_mhz: float | None
    high_fanout_candidates: tuple[HighFanoutCandidate, ...]
    path_spread: PathSpread | None
    critical_hard_block_types: tuple[str, ...]
    congestion: dict[str, int | bool] | None
    timing_anatomy: dict[str, float | int | bool] | None
    hard_block_topology: dict[str, int] | None
    primitive_cell_count: int | None
    analysis_duration_seconds: float
    unavailable: tuple[str, ...]

    @classmethod
    def from_reports(
        cls,
        *,
        target_clock: str,
        clock_period_ns: float | None,
        wns_ns: float | None,
        tns_ns: float | None,
        failing_endpoints: int | None,
        high_fanout_report: str,
        spread_report: str | None,
        analysis_duration_seconds: float,
        critical_paths_report: str | None = None,
        congestion_report: str | None = None,
        primitive_cell_count: int | None = None,
        timing_anatomy_report: str | None = None,
    ) -> "DesignSignature":
        fanout_candidates = tuple(
            HighFanoutCandidate(
                net_name=net_name,
                fanout=fanout,
                critical_path_count=path_count,
            )
            for net_name, fanout, path_count in parse_high_fanout_nets_report(
                high_fanout_report
            )
        )
        spread_payload = parse_spread_analysis(spread_report)
        path_spread = PathSpread(**spread_payload) if spread_payload else None
        hard_block_types = parse_critical_hard_block_types(critical_paths_report)
        congestion = parse_congestion_report(congestion_report)
        timing_anatomy = parse_timing_anatomy_report(timing_anatomy_report)
        hard_block_topology = parse_critical_hard_block_topology(critical_paths_report)

        unavailable = []
        if clock_period_ns is None:
            unavailable.append("clock_period")
        if wns_ns is None:
            unavailable.append("wns")
        if tns_ns is None:
            unavailable.append("tns")
        if failing_endpoints is None:
            unavailable.append("failing_endpoints")
        if spread_report is None or path_spread is None:
            unavailable.append("path_spread")
        if critical_paths_report is None:
            unavailable.append("critical_hard_blocks")
        if congestion is None:
            unavailable.append("congestion")
        if primitive_cell_count is None:
            unavailable.append("primitive_cell_count")
        if timing_anatomy is None:
            unavailable.append("timing_anatomy")
        if hard_block_topology is None:
            unavailable.append("hard_block_topology")

        fmax_mhz = None
        if clock_period_ns is not None and wns_ns is not None:
            fmax_mhz = target_clock_fmax_mhz(clock_period_ns, wns_ns)

        return cls(
            target_clock=target_clock,
            clock_period_ns=clock_period_ns,
            wns_ns=wns_ns,
            tns_ns=tns_ns,
            failing_endpoints=failing_endpoints,
            fmax_mhz=fmax_mhz,
            high_fanout_candidates=fanout_candidates,
            path_spread=path_spread,
            critical_hard_block_types=hard_block_types,
            congestion=congestion,
            timing_anatomy=timing_anatomy,
            hard_block_topology=hard_block_topology,
            primitive_cell_count=primitive_cell_count,
            analysis_duration_seconds=analysis_duration_seconds,
            unavailable=tuple(unavailable),
        )

    def to_dict(self) -> dict:
        return {
            "target_clock": self.target_clock,
            "clock_period_ns": self.clock_period_ns,
            "wns_ns": self.wns_ns,
            "tns_ns": self.tns_ns,
            "failing_endpoints": self.failing_endpoints,
            "fmax_mhz": self.fmax_mhz,
            "high_fanout_candidates": [
                asdict(candidate) for candidate in self.high_fanout_candidates
            ],
            "path_spread": asdict(self.path_spread) if self.path_spread else None,
            "critical_hard_block_types": list(self.critical_hard_block_types),
            "congestion": self.congestion,
            "timing_anatomy": self.timing_anatomy,
            "hard_block_topology": self.hard_block_topology,
            "primitive_cell_count": self.primitive_cell_count,
            "analysis_duration_seconds": self.analysis_duration_seconds,
            "unavailable": list(self.unavailable),
        }
