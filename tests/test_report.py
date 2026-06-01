"""Tests for the Markdown report generator."""

from __future__ import annotations

from emc_assistant.parasitics.calculators import (
    trace_inductance_no_plane,
    trace_resistance,
)
from emc_assistant.project.model import ProjectConfig
from emc_assistant.recommendations.engine import build_baseline_recommendations
from emc_assistant.reports.markdown import (
    PRECOMPLIANCE_DISCLAIMER,
    ReportContext,
    render_markdown_report,
)
from emc_assistant.testbench.generators import (
    CableSpec,
    LisnSpec,
    generate_cable_fragment,
    generate_lisn_subckt,
)


def _project() -> ProjectConfig:
    return ProjectConfig(
        project_id="test",
        name="Test project",
        version="0.0.1",
        created_at="2026-05-13",
        analysis_scope="conducted_emi_dc_dc",
        inputs={"netlist_path": "input/x.cir"},
        privacy={"allow_cloud_llm": False},
        ltspice={"mode": "dry-run"},
    )


def test_report_contains_disclaimer_and_sections():
    parasitics = [
        trace_resistance(length_mm=10.0, width_mm=0.5),
        trace_inductance_no_plane(length_mm=10.0, width_mm=0.5),
    ]
    recs = build_baseline_recommendations(parasitics)
    ctx = ReportContext(
        project=_project(),
        parasitics=parasitics,
        recommendations=recs,
        lisn_spice=generate_lisn_subckt(LisnSpec()),
        cable_spice=generate_cable_fragment(CableSpec()),
        ltspice_available=False,
        ltspice_command=None,
    )
    md = render_markdown_report(ctx)

    assert "# EMC pre-compliance report" in md
    assert "Disclaimer (pre-compliance)" in md
    assert PRECOMPLIANCE_DISCLAIMER in md
    assert "Estimated parasitics" in md
    assert "Recommendations" in md
    assert "Generated SPICE fragments" in md
    # Every recommendation should carry a REC-NNN identifier.
    assert "REC-001" in md
    for p in parasitics:
        assert p.id in md


def test_report_promises_no_emc_pass():
    parasitics = [trace_resistance(length_mm=5.0, width_mm=0.3)]
    recs = build_baseline_recommendations(parasitics)
    md = render_markdown_report(
        ReportContext(
            project=_project(),
            parasitics=parasitics,
            recommendations=recs,
            lisn_spice="",
            cable_spice="",
        )
    )
    # Guardrail — never promise EMC pass.
    forbidden = ["design will pass emc", "passes emc", "guaranteed pass"]
    lower = md.lower()
    for phrase in forbidden:
        assert phrase not in lower
