"""Testbench + variant ``.cir`` composition — service layer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from emc_assistant.logging_setup import get_logger
from emc_assistant.service import resolve
from emc_assistant.service.context import build_default_parasitics, load_user_context
from emc_assistant.service.options import CommandOptions, _UNSET
from emc_assistant.service.project import require_project
from emc_assistant.service.results import ServiceError
from emc_assistant.testbench.composer import TestbenchPlan, compose_testbench_cir
from emc_assistant.testbench.generators import CableSpec, LisnSpec
from emc_assistant.testbench.variants import enumerate_corner_variants

_log = get_logger("testbench")


@dataclass
class ComposeResult:
    testbench_path: Path
    asc_path: Path | None
    injection_count: int
    series_count: int
    shunt_count: int
    dropped_count: int


def _assess_sim(settings, user_context: dict):
    """Run the deterministic sim-setup check from a project's user_context
    (switching frequency, device edge rise time, conducted-band max)."""
    from emc_assistant.testbench.sim_settings import assess_simulation_setup

    uc = user_context or {}

    def _f(key):
        v = uc.get(key)
        try:
            return float(v) if v else None
        except (TypeError, ValueError):
            return None

    band_max = 30e6
    fr = uc.get("frequency_range")
    if isinstance(fr, dict):
        try:
            band_max = float(fr.get("max_hz") or band_max)
        except (TypeError, ValueError):
            pass
    return assess_simulation_setup(
        settings,
        switching_frequency_hz=_f("switching_frequency_hz"),
        band_max_hz=band_max,
        edge_rise_time_s=_f("edge_rise_time_s"),
    )


_SIM_TIME_KEYS = ("stop_time", "max_timestep", "record_start")


def _sim_block(overrides: dict) -> dict:
    """Pick the recognised simulation keys out of a UI payload into a
    ``user_context.simulation`` block (string-coerced, like the schema
    expects). Unknown keys are ignored."""
    block: dict = {}
    for k in _SIM_TIME_KEYS:
        v = (overrides or {}).get(k)
        if v not in (None, ""):
            block[k] = str(v)
    if "startup" in (overrides or {}):
        block["startup"] = bool(overrides["startup"])
    if (overrides or {}).get("integration_method") is not None:
        block["integration_method"] = str(overrides["integration_method"])
    opts = (overrides or {}).get("options")
    if isinstance(opts, dict):
        kept = {str(k): str(v) for k, v in opts.items() if str(v).strip() != ""}
        if kept:
            block["options"] = kept
    # Advanced raw override — only when explicitly supplied (the structured
    # panel does not send this, so saving from it promotes raw → structured).
    if (overrides or {}).get("tran_directive"):
        block["tran_directive"] = str(overrides["tran_directive"])
    return block


def assess_simulation(project_root, overrides: dict | None = None):
    """Assess ``.tran`` settings against conducted-EMI needs (band coverage,
    switching-edge resolution, frequency resolution).

    ``overrides`` None → assess the project's *saved* settings (the Run
    screen surfaces this as pre-run warnings; the composer logs it).
    ``overrides`` set → assess the *proposed* settings the user is editing,
    against the project's switching frequency / edge / band — the
    review-before-apply path. Malformed proposed settings come back as a
    single high-severity finding instead of raising."""
    from emc_assistant.testbench.sim_settings import (
        SimAssessment,
        SimCheck,
        SimulationSettings,
    )

    _config, layout = require_project(project_root)
    user_context = load_user_context(layout)
    if overrides:
        try:
            settings = SimulationSettings.from_user_context(
                {"simulation": _sim_block(overrides)}
            )
        except ValueError as exc:
            return SimAssessment(
                ok=False,
                checks=[SimCheck("invalid_settings", "high", f"Invalid settings: {exc}")],
                stop_s=None, max_timestep_s=None, record_start_s=None,
                recommended_max_timestep_s=None, recommended_stop_time_s=None,
                recommended_record_start_s=None,
            )
    else:
        settings = SimulationSettings.from_user_context(user_context)
    return _assess_sim(settings, user_context)


def load_simulation_settings(project_root) -> dict:
    """The project's effective simulation settings, for the Run-screen panel
    to populate from. ``effective`` carries the seconds the run will actually
    use (parsed from a raw ``.tran`` override when present)."""
    from emc_assistant.testbench.sim_settings import SimulationSettings

    _config, layout = require_project(project_root)
    s = SimulationSettings.from_user_context(load_user_context(layout))
    stop, step, start = s.effective_times()
    return {
        "stop_time": s.stop_time,
        "max_timestep": s.max_timestep,
        "record_start": s.record_start,
        "startup": s.startup,
        "integration_method": s.integration_method,
        "options": dict(s.options),
        "raw_tran_directive": s.raw_tran_directive,
        "has_raw_directive": bool(s.raw_tran_directive),
        "effective": {"stop_s": stop, "max_timestep_s": step, "record_start_s": start},
    }


def save_simulation_settings(project_root, settings: dict) -> dict:
    """Persist the Run-screen panel's structured simulation settings into
    ``user_context.simulation``, validating first. The structured fields
    are written verbatim (no raw ``tran_directive`` unless one is passed),
    so saving from the panel always takes effect. Returns the reloaded
    settings (incl. the new effective times)."""
    from emc_assistant.testbench.sim_settings import SimulationSettings

    _config, layout = require_project(project_root)
    block = _sim_block(settings or {})
    try:
        SimulationSettings.from_user_context({"simulation": block})
    except ValueError as exc:
        raise ServiceError(f"Invalid simulation settings: {exc}")
    uc = dict(load_user_context(layout))
    uc["simulation"] = block
    from emc_assistant.service.context import save_user_context

    save_user_context(project_root, uc)
    _log.info(f"Saved simulation settings: {SimulationSettings.from_user_context({'simulation': block}).tran_line()}")
    return load_simulation_settings(project_root)


def compose_testbench(project_root, options: CommandOptions) -> ComposeResult:
    """Compose ``generated/testbench.cir`` (and, by default, its ``.asc``
    visualisation) for a project."""
    config, layout = require_project(project_root)
    user_context = load_user_context(layout)
    parasitics = build_default_parasitics(user_context)
    wiring, strip_sources = resolve.resolve_wiring(
        user_context, options, layout=layout, config=config
    )

    netlist_rel = config.inputs.get("netlist_path", "")
    user_netlist_raw = (layout.root / netlist_rel).resolve() if netlist_rel else None
    rename_ground = "DUT_GND" if (
        wiring is not None and getattr(wiring, "lisn_mode", "dual") == "dual"
    ) else None
    report_only = options.parasitics_report_only
    user_fragment, series_nets, series_plan, series_dropped = (
        resolve.prepare_user_fragment_with_splices(
            layout, user_netlist_raw,
            strip_sources=strip_sources, config=config,
            rename_ground_to=rename_ground, user_context=user_context,
            options=options, inject_series=not report_only,
        )
    )
    cable_length = (
        float(user_context.get("cable_length_m", 1.0))
        if isinstance(user_context, dict) else 1.0
    )

    injection_plan = resolve.resolve_parasitics_injection(
        user_context, options, parasitics=parasitics, user_fragment_path=user_fragment,
    )
    shunt_plan = resolve.resolve_shunt_plan(
        user_context, options, user_fragment_path=user_fragment,
        injection_plan=injection_plan, series_nets=tuple(series_nets),
    )
    shunt_dropped: list = []
    if shunt_plan and options.resolved_shunt_plan is _UNSET:
        shunt_plan, shunt_dropped = resolve.filter_negligible(
            shunt_plan, "shunt", options=options, layout=layout,
            config=config, user_context=user_context,
        )
    signals_map = resolve.resolve_signals(
        user_context, options, layout=layout, project_root_path=project_root,
    )

    sim_settings = resolve.resolve_simulation_settings(user_context)
    if sim_settings is None:
        raise ServiceError("")  # invalid sim settings — already logged
    plan_kwargs = dict(
        title=f"EMC testbench for {config.project_id}",
        parasitics=parasitics,
        user_netlist=user_fragment,
        lisn=LisnSpec(),
        cable=CableSpec(length_m=cable_length),
        wiring=wiring,
        injection_plan=injection_plan,
        series_plan=[] if report_only else series_plan,
        shunt_plan=[] if report_only else shunt_plan,
        signals=signals_map,
        tran_directive=sim_settings.tran_line(),
        options_directive=sim_settings.options_line(),
    )
    _log.info(
        f"  simulation: {sim_settings.tran_line()}"
        + (f" | {sim_settings.options_line()}" if sim_settings.options_line() else "")
    )
    # Deterministic sim-setup integrity check — warn (never block) if the
    # window/timestep can't capture the band or the switching edges.
    for c in _assess_sim(sim_settings, user_context).checks:
        if c.severity in ("high", "medium"):
            _log.warning(
                f"  sim-setup [{c.severity}] {c.message}"
                + (f" → {c.recommendation}" if c.recommendation else "")
            )
    plan = TestbenchPlan(**plan_kwargs)
    cir = compose_testbench_cir(plan)
    layout.generated_dir.mkdir(parents=True, exist_ok=True)
    out_path = layout.generated_dir / "testbench.cir"
    out_path.write_text(cir, encoding="utf-8")
    _log.info(f"Wrote testbench: {out_path}")
    if injection_plan:
        audit_path = layout.generated_dir / "parasitics_wiring.json"
        audit_path.write_text(
            json.dumps(
                [inj.to_schema_dict() for inj in injection_plan],
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        _log.info(f"Wrote injection-plan audit: {audit_path}")
    if series_plan:
        series_audit = layout.generated_dir / "parasitics_series.json"
        series_audit.write_text(
            json.dumps(
                [se.to_schema_dict() for se in series_plan],
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        _log.info(f"Wrote per-net series-plan audit: {series_audit}")
    if shunt_plan:
        shunt_audit = layout.generated_dir / "parasitics_shunt.json"
        shunt_audit.write_text(
            json.dumps(
                [sh.to_schema_dict() for sh in shunt_plan],
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        _log.info(f"Wrote per-net shunt-plan audit: {shunt_audit}")
    dropped = list(series_dropped) + list(shunt_dropped)
    if dropped:
        dropped_audit = layout.generated_dir / "parasitics_dropped.json"
        dropped_audit.write_text(
            json.dumps(dropped, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        _log.info(
            f"Wrote negligibility-screen audit ({len(dropped)} dropped): "
            f"{dropped_audit}"
        )

    asc_path = None
    # M2.10.3: also emit an LTspice .asc visualisation of the testbench.
    if not options.no_asc_export:
        from emc_assistant.testbench.asc_writer import build_asc, write_asc_bundle
        from emc_assistant.netlist.topology import analyse_fragment

        dut_pins = [wiring.dut_supply_net if wiring else "in"]
        dut_pins.append("DUT_GND")
        if user_fragment and user_fragment.is_file():
            try:
                topo = analyse_fragment(user_fragment)
                for sw in topo.switching_node_candidates[:1]:
                    if sw not in dut_pins:
                        dut_pins.append(sw)
            except Exception:  # noqa: BLE001
                pass
        first_inj = injection_plan[0] if injection_plan else None
        asc = build_asc(
            title=f"EMC testbench for {config.project_id}",
            v_rail_value=f"DC {wiring.external_supply_v if wiring else 24}",
            dut_pins=dut_pins,
            injection=first_inj,
            user_cir_include=str(out_path.resolve()).replace("\\", "/"),
        )
        asc_path = write_asc_bundle(layout.generated_dir, asc)
        _log.info(f"Wrote LTspice .asc visualisation: {asc_path}")
    return ComposeResult(
        testbench_path=out_path,
        asc_path=asc_path,
        injection_count=len(injection_plan),
        series_count=len(series_plan),
        shunt_count=len(shunt_plan),
        dropped_count=len(dropped),
    )


@dataclass
class VariantsComposeResult:
    out_dir: Path
    variant_count: int


def compose_variants(project_root, options: CommandOptions) -> VariantsComposeResult:
    """Compose one ``.cir`` per parasitic corner variant."""
    config, layout = require_project(project_root)
    user_context = load_user_context(layout)
    parasitics = build_default_parasitics(user_context)
    variants = enumerate_corner_variants(parasitics)
    wiring, strip_sources = resolve.resolve_wiring(
        user_context, options, layout=layout, config=config
    )

    netlist_rel = config.inputs.get("netlist_path", "")
    user_netlist_raw = (layout.root / netlist_rel).resolve() if netlist_rel else None
    rename_ground = "DUT_GND" if (
        wiring is not None and getattr(wiring, "lisn_mode", "dual") == "dual"
    ) else None
    report_only = options.parasitics_report_only
    user_fragment, series_nets, series_plan, _series_dropped = (
        resolve.prepare_user_fragment_with_splices(
            layout, user_netlist_raw,
            strip_sources=strip_sources, config=config,
            rename_ground_to=rename_ground, user_context=user_context,
            options=options, inject_series=not report_only,
        )
    )
    cable_length = (
        float(user_context.get("cable_length_m", 1.0))
        if isinstance(user_context, dict) else 1.0
    )

    out_dir = layout.generated_dir / "variants"
    out_dir.mkdir(parents=True, exist_ok=True)
    sim_settings = resolve.resolve_simulation_settings(user_context)
    if sim_settings is None:
        raise ServiceError("")  # invalid sim settings — already logged
    injection_plan = resolve.resolve_parasitics_injection(
        user_context, options, parasitics=parasitics, user_fragment_path=user_fragment,
    )
    shunt_plan = resolve.resolve_shunt_plan(
        user_context, options, user_fragment_path=user_fragment,
        injection_plan=injection_plan, series_nets=tuple(series_nets),
    )
    if shunt_plan and options.resolved_shunt_plan is _UNSET:
        shunt_plan, _ = resolve.filter_negligible(
            shunt_plan, "shunt", options=options, layout=layout,
            config=config, user_context=user_context,
        )
    composer_series = [] if report_only else series_plan
    composer_shunt = [] if report_only else shunt_plan
    signals_map = resolve.resolve_signals(
        user_context, options, layout=layout, project_root_path=project_root,
    )
    manifest: list[dict] = []
    for v in variants:
        plan_kwargs = dict(
            title=f"Variant {v.label} ({config.project_id})",
            parasitics=v.parasitics,
            user_netlist=user_fragment,
            lisn=LisnSpec(),
            cable=CableSpec(length_m=cable_length),
            sweep_corners=False,  # one file = one sweep point
            wiring=wiring,
            injection_plan=injection_plan,
            series_plan=composer_series,
            shunt_plan=composer_shunt,
            signals=signals_map,
            tran_directive=sim_settings.tran_line(),
            options_directive=sim_settings.options_line(),
        )
        plan = TestbenchPlan(**plan_kwargs)
        cir_path = out_dir / f"{v.short_id()}.cir"
        cir_path.write_text(compose_testbench_cir(plan), encoding="utf-8")
        manifest.append(
            {
                "label": v.label,
                "description": v.description,
                "overrides": v.overrides,
                "cir": str(cir_path),
            }
        )
    manifest_path = out_dir / "variants.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _log.info(f"Wrote {len(variants)} variants to {out_dir}")
    return VariantsComposeResult(out_dir=out_dir, variant_count=len(variants))
