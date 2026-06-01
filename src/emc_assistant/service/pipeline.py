"""End-to-end pipeline — service layer.

Resolves wiring / parasitics / signals once, then threads the decisions
into each sub-step (compose → variants → simulate → report) via
``CommandOptions.child(...)``.

Supports **cooperative cancel** between stages: the UI calls
:func:`request_cancel`; the pipeline checks the flag at six boundaries
and raises :class:`RunCancelled` (a :class:`ServiceError` subclass with
exit code 130). It does **not** kill an in-flight LTspice subprocess —
that would orphan partial ``.raw`` files — so a cancel takes effect
when the current stage finishes.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from emc_assistant.logging_setup import get_logger
from emc_assistant.service import parasitics as parasitics_service
from emc_assistant.service import report as report_service
from emc_assistant.service import resolve
from emc_assistant.service import simulate as simulate_service
from emc_assistant.service import testbench as testbench_service
from emc_assistant.service.context import build_default_parasitics, load_user_context
from emc_assistant.service.options import _UNSET, CommandOptions
from emc_assistant.service.project import require_project
from emc_assistant.service.results import ServiceError

_log = get_logger("pipeline")


# ---- cooperative cancel ----------------------------------------------------


class RunCancelled(ServiceError):
    """Raised between pipeline stages when the UI requested a cancel."""

    def __init__(self, stage: str):
        super().__init__(
            f"Pipeline cancelled by user before stage: {stage}",
            exit_code=130,
        )
        self.stage = stage


_cancel_event = threading.Event()


def request_cancel() -> None:
    """Mark the current run as cancel-requested. Thread-safe; idempotent —
    multiple calls before the next checkpoint coalesce into one cancel.
    Called by the UI bridge from a worker thread while the pipeline runs
    on another."""
    _cancel_event.set()


def _check_cancel(stage: str) -> None:
    """Raise :class:`RunCancelled` if a cancel was requested. Clears the
    flag on raise so the next pipeline call starts fresh."""
    if _cancel_event.is_set():
        _cancel_event.clear()
        raise RunCancelled(stage)


def _reset_cancel() -> None:
    """Drop any stale cancel flag — called at the top of every run."""
    _cancel_event.clear()


@dataclass
class PipelineResult:
    mode: str
    report: report_service.ReportResult


def run_pipeline(project_root, options: CommandOptions) -> PipelineResult:
    """One-shot: parasitics → testbench → variants → simulate → report.

    Honours cooperative cancel via :func:`request_cancel` — the run is
    checked at six boundaries; the UI thread can request cancel while
    the pipeline thread runs."""
    _reset_cancel()
    config, layout = require_project(project_root)
    mode = options.mode or "dry-run"
    user_context = load_user_context(layout)

    # Resolve wiring once for the whole pipeline; sub-steps inherit it.
    resolved_wiring, resolved_strip = resolve.resolve_wiring(
        user_context, options, layout=layout, config=config
    )

    netlist_rel = config.inputs.get("netlist_path", "")
    user_netlist_raw = (
        (layout.root / netlist_rel).resolve() if netlist_rel else None
    )
    rename_ground = "DUT_GND" if (
        resolved_wiring is not None
        and getattr(resolved_wiring, "lisn_mode", "dual") == "dual"
    ) else None
    user_fragment_for_topology = None
    resolved_series_nets: list = []
    resolved_series_plan: list = []
    if user_netlist_raw is not None and user_netlist_raw.is_file():
        try:
            (
                user_fragment_for_topology,
                resolved_series_nets,
                resolved_series_plan,
                _resolved_series_dropped,
            ) = resolve.prepare_user_fragment_with_splices(
                layout,
                user_netlist_raw,
                strip_sources=resolved_strip,
                config=config,
                rename_ground_to=rename_ground,
                user_context=user_context,
                options=options,
                inject_series=not options.parasitics_report_only,
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                f"[parasitics] could not prepare fragment for topology: {exc}"
            )
    resolved_injection_plan = resolve.resolve_parasitics_injection(
        user_context,
        options,
        parasitics=build_default_parasitics(user_context),
        user_fragment_path=user_fragment_for_topology,
    )
    resolved_shunt_plan = resolve.resolve_shunt_plan(
        user_context,
        options,
        user_fragment_path=user_fragment_for_topology,
        injection_plan=resolved_injection_plan,
        series_nets=tuple(resolved_series_nets),
    )
    if resolved_shunt_plan and options.resolved_shunt_plan is _UNSET:
        resolved_shunt_plan, _ = resolve.filter_negligible(
            resolved_shunt_plan, "shunt", options=options, layout=layout,
            config=config, user_context=user_context,
        )

    resolved_signals = resolve.resolve_signals(
        user_context, options, layout=layout, project_root_path=project_root,
    )

    child = options.child(
        resolved_wiring=resolved_wiring,
        resolved_strip=resolved_strip,
        resolved_injection_plan=list(resolved_injection_plan),
        resolved_shunt_plan=list(resolved_shunt_plan),
        resolved_series_plan=list(resolved_series_plan),
        resolved_signals=list(resolved_signals),
        mode=mode,
    )

    _check_cancel("parasitics")
    _log.info("[pipeline] 1/6 estimating parasitics…")
    parasitics_service.estimate_parasitics(project_root)
    _check_cancel("compose-testbench")
    _log.info("[pipeline] 2/6 composing testbench…")
    testbench_service.compose_testbench(project_root, child)
    _check_cancel("compose-variants")
    _log.info("[pipeline] 3/6 generating variants…")
    testbench_service.compose_variants(project_root, child)
    _check_cancel("run-variants")
    _log.info(f"[pipeline] 4/6 simulating variants ({mode})…")
    variants_run = simulate_service.run_variants(project_root, child)
    if not variants_run.ok:
        # Even on partial failure (e.g. no LTspice) we continue to the report.
        _log.warning("[pipeline]   warning: variants run finished with code 1")
    _check_cancel("run-testbench")
    _log.info("[pipeline] 5/6 single testbench.cir simulation…")
    simulate_service.run_testbench(project_root, child)
    _check_cancel("report")
    _log.info("[pipeline] 6/6 markdown report…")
    report = report_service.generate_report(project_root, child)
    return PipelineResult(mode=mode, report=report)
