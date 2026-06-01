"""Analysis-input assembly — shared by the knowledge, parasitics, report
and pipeline service modules.

These helpers turn a project's ``project.yaml`` + ``user_context.json``
into the structured inputs the downstream stages consume. None of them
include the schematic itself — only structured summaries leave for the
LLM (see the copyright-redaction rule).
"""

from __future__ import annotations

import json

from emc_assistant.llm import ProblemContext
from emc_assistant.parasitics.calculators import (
    lc_resonance,
    polygon_plane_capacitance,
    trace_capacitance_from_z0_delay,
    trace_inductance_no_plane,
    trace_resistance,
    via_inductance,
)
from emc_assistant.parasitics.model import ParasiticEstimate


def load_user_context(layout) -> dict:
    """Read ``input/user_context.json`` for a project, or ``{}``."""
    path = layout.input_dir / "user_context.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_user_context(project_root, data: dict):
    """Write ``input/user_context.json`` for a project — the UI's one
    write path (the context form). Returns the written path."""
    # Imported here to avoid an import cycle at module load.
    from emc_assistant.service.project import require_project
    from emc_assistant.service.results import ServiceError

    if not isinstance(data, dict):
        raise ServiceError("user_context must be a JSON object.")
    _config, layout = require_project(project_root)
    layout.input_dir.mkdir(parents=True, exist_ok=True)
    path = layout.input_dir / "user_context.json"
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path


def build_default_parasitics(user_context: dict) -> list[ParasiticEstimate]:
    """Build the default parasitic estimate list for the MVP."""
    pcb = user_context.get("pcb", {}) if isinstance(user_context, dict) else {}
    trace_length_mm = float(pcb.get("trace_length_mm", 20.0))
    trace_width_mm = float(pcb.get("trace_width_mm", 1.0))
    copper_oz = float(pcb.get("copper_oz", 1.0))
    dielectric_h_mm = float(pcb.get("dielectric_height_to_plane_mm", 0.2))

    parasitics: list[ParasiticEstimate] = [
        trace_resistance(
            length_mm=trace_length_mm,
            width_mm=trace_width_mm,
            copper_oz=copper_oz,
        ),
        trace_inductance_no_plane(
            length_mm=trace_length_mm,
            width_mm=trace_width_mm,
            copper_oz=copper_oz,
        ),
        trace_capacitance_from_z0_delay(
            length_mm=trace_length_mm,
            z0_ohm=50.0,
            delay_ps_per_mm=6.7,
        ),
        polygon_plane_capacitance(
            area_mm2=max(trace_length_mm * trace_width_mm * 4.0, 100.0),
            dielectric_height_mm=dielectric_h_mm,
        ),
        via_inductance(height_mm=1.6, drill_diameter_mm=0.3),
    ]
    res_l = parasitics[1].value
    res_c = parasitics[2].value
    parasitics.append(lc_resonance(inductance_h=res_l, capacitance_f=res_c))
    return parasitics


def _opt_float(value):
    try:
        if isinstance(value, str):
            value = value.strip().split()[0]
        return float(value)
    except (ValueError, TypeError, IndexError):
        return None


def build_problem_context(
    config, user_context: dict, parasitics: list[ParasiticEstimate]
) -> ProblemContext:
    """Build a compact :class:`ProblemContext` for the LLM from project +
    ``user_context``.

    The schematic is NOT included. Only structured summaries are sent
    (see the copyright-redaction rule and docs/09).
    """
    uc = user_context or {}
    pcb = uc.get("pcb", {}) if isinstance(uc, dict) else {}
    has_layout = bool(pcb.get("layout_path"))
    has_stackup = bool(pcb.get("layers"))
    missing: list[str] = []
    if not has_layout:
        missing.append("layout")
    if not has_stackup:
        missing.append("stackup")
    if not uc.get("known_issue"):
        missing.append("known_issue")

    freq_range = uc.get("frequency_range") if isinstance(uc, dict) else None
    f_min = f_max = None
    if isinstance(freq_range, str) and "-" in freq_range:
        parts = freq_range.split("-", 1)
        f_min, f_max = _opt_float(parts[0]), _opt_float(parts[1])
    elif isinstance(freq_range, dict):
        f_min = _opt_float(freq_range.get("min_hz"))
        f_max = _opt_float(freq_range.get("max_hz"))
    if f_min is None:
        f_min = 150_000.0  # default conducted EMI band low
    if f_max is None:
        f_max = 30_000_000.0  # default conducted EMI band high

    return ProblemContext(
        project_id=config.project_id,
        analysis_scope=config.analysis_scope,
        topology=str(uc.get("project_type") or uc.get("topology") or ""),
        input_voltage_v=_opt_float(uc.get("input_voltage_v") or uc.get("input_voltage")),
        switching_frequency_hz=_opt_float(
            uc.get("switching_frequency_hz") or uc.get("switching_frequency")
        ),
        load_current_a=_opt_float(uc.get("load_current_a") or uc.get("load_current")),
        frequency_range_min_hz=f_min,
        frequency_range_max_hz=f_max,
        problem_hypothesis=str(
            uc.get("problem_hypothesis") or uc.get("known_issue") or ""
        ),
        has_layout=has_layout,
        has_stackup=has_stackup,
        missing_data=missing,
    )
