"""Markdown report generator for the first iteration.

The report contains:
- a project header,
- the mandatory pre-compliance disclaimer,
- the assumptions table,
- the parasitics table (min/typ/max + sources),
- generated SPICE fragments (LISN, cable),
- variants and measurements,
- ranking (if a metric key was provided),
- recommendations,
- limitations and risks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from emc_assistant.agents.base import AgentFinding
from emc_assistant.agents.injection import ParasiticInjection
from emc_assistant.agents.synthesiser import DiagnosticNarrative
from emc_assistant.netlist.signals import Signal
from emc_assistant.parasitics.per_net import NetParasitics
from emc_assistant.parasitics.model import ParasiticEstimate
from emc_assistant.project.model import ProjectConfig
from emc_assistant.recommendations.decisions import DecisionLog
from emc_assistant.recommendations.engine import Recommendation
from emc_assistant.results.detectors import (
    CISPR_BAND_B,
    DIAGNOSTIC_LIMITATION,
    GENERAL_DISCLAIMER,
    MODE_TIME_DOMAIN_DIAGNOSTIC,
)
from emc_assistant.results.limits import get_standard
from emc_assistant.results.ranking import RankedVariant
from emc_assistant.testbench.variants import Variant


PRECOMPLIANCE_DISCLAIMER = (
    "> **Disclaimer (pre-compliance):** This report is an *engineering aid* / "
    "*risk-reduction* artefact and does NOT constitute proof of EMC compliance. "
    "Simulation results do not replace measurements in an accredited laboratory. "
    "Every recommendation is an engineering hypothesis that requires verification."
)


@dataclass
class ReportContext:
    project: ProjectConfig
    parasitics: list[ParasiticEstimate]
    recommendations: list[Recommendation]
    lisn_spice: str = ""
    cable_spice: str = ""
    ltspice_available: bool = False
    ltspice_command: list[str] | None = None
    extra_limitations: list[str] | None = None
    generated_at: str | None = None
    variants: list[Variant] | None = None
    ranking: list[RankedVariant] | None = None
    ranking_metric_key: str | None = None
    ranking_lower_is_better: bool = True
    measurements: list[dict] | None = None
    """Per-variant measurements: ``[{label, metrics: {k: v}}, ...]``."""
    agent_findings: list[AgentFinding] | None = None
    """Per-area specialist-agent findings (M2.9). When set, the report
    grows a "Specialist findings" section with one subsection per agent."""
    injection_plan: list[ParasiticInjection] | None = None
    """M2.10 parasitic-injection plan actually spliced into the testbench
    this run. Empty / None when --no-parasitics or no plan was resolved."""
    signals: list[Signal] | None = None
    """M2.10.1 resolved user signal map. When set, the report grows a
    "Tracked signals" section listing per-signal expr, kind, target band
    (if any), and the observed peak/rms metrics from the .meas log."""
    diagnostic: DiagnosticNarrative | None = None
    """M2.11 diagnostic narrative. When set, the report opens with a
    "Diagnostic" section right after the disclaimer."""
    per_net_parasitics: list[NetParasitics] | None = None
    """M2.10.4 per-net parasitic estimates. When set, the report grows
    a "Per-net parasitic estimate" table after the parasitics section."""
    per_net_value_source: dict[str, str] | None = None
    """M2.17 per-net value provenance: ``net -> label`` (e.g.
    "calculator (rule-of-thumb)", "LLM-refined (RAG)", "LLM (uncited est.)").
    When set, the per-net table shows a ``source`` column disclosing how each
    value was derived. Nets absent from the map default to the calculator."""
    decision_log: "DecisionLog | None" = None
    """M2.12 accept/reject decisions. When set, each recommendation in
    the report carries an accepted / rejected / proposed status badge."""
    detector_plots: list[tuple[str, str]] | None = None
    """M2.15 CISPR detector-vs-limit plots embedded in the EMI-detector
    section — a list of ``(caption, image_filename)``. The filenames are
    siblings of ``report.md`` in ``reports/``. Empty / None when no plot
    could be rendered (no testbench.raw, coarse timestep, matplotlib
    absent)."""


def _fmt_value(v: float, unit: str) -> str:
    return f"{v:.3g} {unit}"


def _table(headers: list[str], rows: Iterable[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def _fmt_margin(margin_db, freq_hz) -> str:
    """Human-readable worst-margin string for the report."""
    if margin_db is None:
        return "n/a"
    where = f" at {freq_hz / 1e6:.3g} MHz" if freq_hz else ""
    side = "over the limit" if margin_db > 0 else "headroom below the limit"
    return f"{margin_db:+.1f} dB{where} ({side})"


def _pick_worst_margin(measurements: list[dict] | None) -> dict | None:
    """The worst QP / average margin from the baseline variant — or the
    first variant that carries margin metrics. ``None`` if none do."""
    entries = sorted(
        measurements or [],
        key=lambda e: 0 if str(e.get("label", "")).lower() == "baseline" else 1,
    )
    for entry in entries:
        metrics = entry.get("metrics") or {}
        for key in metrics:
            if key.endswith("_qp_worst_margin_db"):
                prefix = key[: -len("_qp_worst_margin_db")]
                return {
                    "label": entry.get("label", "?"),
                    "qp_db": metrics.get(f"{prefix}_qp_worst_margin_db"),
                    "qp_hz": metrics.get(f"{prefix}_qp_worst_margin_hz"),
                    "avg_db": metrics.get(f"{prefix}_avg_worst_margin_db"),
                    "avg_hz": metrics.get(f"{prefix}_avg_worst_margin_hz"),
                }
    return None


def _emi_detector_section(
    measurements: list[dict] | None,
    detector_plots: list[tuple[str, str]] | None = None,
) -> list[str]:
    """The EMI-detector metadata block — detector mode + constants + the
    worst compliance margin + mandatory disclaimers (quasi-peak concept
    note §11/§12). Rendered only when the run produced band readings."""
    has_readings = any(
        "_band_quasi_peak_dbuv_" in k or "_band_peak_dbuv_" in k
        for entry in (measurements or [])
        for k in (entry.get("metrics") or {})
    )
    if not has_readings:
        return []
    b = CISPR_BAND_B
    lines = [
        "## EMI detector",
        "",
        "The peak / quasi-peak / average band readings above are produced "
        "by EMC-Assist's CISPR-like detector.",
        "",
        f"- Detector mode: `{MODE_TIME_DOMAIN_DIAGNOSTIC}` (Mode 1) — the "
        "quasi-peak weighting is applied directly to the selected waveform.",
        "- Receiver-bandwidth filter applied: **no**.",
        "- Average detector: the envelope through a linear meter-time-constant "
        "low-pass, then max-held (seeded with the envelope mean, so a run "
        "shorter than the meter constant degrades to the steady-state mean).",
        f"- Band: CISPR Band {b.name} — "
        f"{b.f_low / 1e3:.0f} kHz – {b.f_high / 1e6:.0f} MHz.",
        f"- Detector constants (EN 55016-1-1 ed. 3): "
        f"RBW {b.rbw_hz / 1e3:.0f} kHz · charge {b.qp_charge_s * 1e3:.0f} ms · "
        f"discharge {b.qp_discharge_s * 1e3:.0f} ms · "
        f"meter {b.meter_s * 1e3:.0f} ms.",
        "- Calibration: none — uncalibrated relative diagnostic.",
    ]
    worst = _pick_worst_margin(measurements)
    if worst is not None:
        standard = get_standard(None)
        lines += [
            "",
            f"**Compliance margin** — worst per-frequency margin vs "
            f"{standard.name} (variant `{worst['label']}`):",
            "",
            f"- Quasi-peak: {_fmt_margin(worst['qp_db'], worst['qp_hz'])}",
            f"- Average: {_fmt_margin(worst['avg_db'], worst['avg_hz'])}",
            "",
            "Margin = reading − limit; a positive margin is *over* the limit. "
            "A pre-compliance estimate, not a pass/fail verdict.",
        ]
    for caption, image in detector_plots or ():
        lines += ["", f"**{caption}**", "", f"![{caption}]({image})"]
    lines += [
        "",
        f"> {DIAGNOSTIC_LIMITATION}",
        "",
        f"> {GENERAL_DISCLAIMER}",
        "",
    ]
    return lines


def render_markdown_report(ctx: ReportContext) -> str:
    project = ctx.project
    generated_at = (
        ctx.generated_at
        or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )

    parts: list[str] = []
    parts.append(f"# EMC pre-compliance report — {project.name}")
    parts.append("")
    parts.append(f"- **Project ID:** `{project.project_id}`")
    parts.append(f"- **Version:** {project.version}")
    parts.append(f"- **Analysis scope:** `{project.analysis_scope}`")
    parts.append(f"- **Generated at:** {generated_at}")
    parts.append("")
    parts.append(PRECOMPLIANCE_DISCLAIMER)
    parts.append("")

    if ctx.diagnostic is not None:
        d = ctx.diagnostic
        tag = "LLM-written" if d.llm_generated else "deterministic stub"
        parts.append("## Diagnostic (M2.11)")
        parts.append("")
        parts.append(
            f"**{d.title}** _(confidence: {d.confidence:.2f}, {tag})_"
        )
        parts.append("")
        parts.append(d.narrative)
        parts.append("")
        parts.append(f"**Dominant issue:** {d.dominant_issue}")
        parts.append("")
        meta = []
        if d.cited_findings:
            meta.append(f"_Cited agents:_ {', '.join(d.cited_findings)}")
        if d.cited_variants:
            meta.append(f"_Cited variants:_ {', '.join(d.cited_variants)}")
        if d.cited_rule_ids:
            meta.append(f"_Cited rules:_ {', '.join(d.cited_rule_ids)}")
        for line in meta:
            parts.append(line)
            parts.append("")
        if d.limitations:
            parts.append("**Limitations of this diagnosis:**")
            for lim in d.limitations:
                parts.append(f"- {lim}")
            parts.append("")

    parts.append("## Project assumptions")
    parts.append("")
    parts.append(
        _table(
            ["Field", "Value"],
            [
                ["analysis_scope", project.analysis_scope],
                ["inputs.netlist_path", str(project.inputs.get("netlist_path", ""))],
                ["inputs.schematic_path", str(project.inputs.get("schematic_path", ""))],
                ["privacy.allow_cloud_llm", str(project.privacy.get("allow_cloud_llm", False))],
                ["ltspice.mode", str(project.ltspice.get("mode", "dry-run"))],
            ],
        )
    )
    parts.append("")

    parts.append("## Estimated parasitics (min/typ/max)")
    parts.append("")
    if ctx.parasitics:
        rows: list[list[str]] = []
        for p in ctx.parasitics:
            rows.append(
                [
                    p.id,
                    p.structure,
                    p.parasitic_type,
                    _fmt_value(p.min_value, p.unit),
                    _fmt_value(p.value, p.unit),
                    _fmt_value(p.max_value, p.unit),
                    p.confidence,
                    ", ".join(p.source_ids) or "engineering_estimate",
                ]
            )
        parts.append(
            _table(
                ["ID", "Structure", "Type", "min", "typ", "max", "confidence", "sources"],
                rows,
            )
        )
    else:
        parts.append("_No parasitics estimated._")
    parts.append("")

    if ctx.per_net_parasitics:
        parts.append("## Per-net parasitic estimate (M2.10.4)")
        parts.append("")
        parts.append(
            "Rule-of-thumb R/L/C for every net in the user fragment, from role-tuned "
            "default trace geometry (no layout — each value is an `engineering_estimate` "
            "pending 3D extraction). `injectable` marks clean 2-element point-to-point "
            "nets where a series parasitic splice is unambiguous; 3+-element star/bus "
            "nets are estimated but need layout to place the splice."
        )
        parts.append("")
        vsrc = ctx.per_net_value_source or {}
        rows = []
        for np_ in ctx.per_net_parasitics:
            r = np_.rlc.resistance
            l = np_.rlc.inductance
            c = np_.rlc.capacitance
            rows.append(
                [
                    np_.net,
                    np_.role,
                    vsrc.get(np_.net, "calculator (rule-of-thumb)"),
                    f"{r.value:.3g} {r.unit}",
                    f"{l.value:.3g} {l.unit}",
                    f"{c.value:.3g} {c.unit}",
                    "yes" if np_.injectable else "no",
                    ", ".join(np_.rlc.cited_sources()) or "engineering_estimate",
                ]
            )
        parts.append(
            _table(
                ["net", "role", "source", "R typ", "L typ", "C typ", "injectable", "rules"],
                rows,
            )
        )
        if ctx.per_net_value_source:
            parts.append("")
            parts.append(
                "*Value provenance (`source`): "
                "**calculator (rule-of-thumb)** = first-order trace calculators on "
                "role-tuned default geometry; "
                "**LLM-refined (RAG)** = M2.17 LLM re-evaluation with a cited "
                "knowledge source; "
                "**LLM (uncited est.)** = LLM-proposed with no supporting source "
                "(kept as an `engineering_estimate`). The min/typ/max bands and "
                "citations behind a re-evaluation live in "
                "`generated/parasitics_reevaluated.json`.*"
            )
        parts.append("")

    parts.append("## Generated SPICE fragments")
    parts.append("")
    if ctx.lisn_spice:
        parts.append("### LISN")
        parts.append("```spice")
        parts.append(ctx.lisn_spice.rstrip())
        parts.append("```")
        parts.append("")
    if ctx.cable_spice:
        parts.append("### Power cable")
        parts.append("```spice")
        parts.append(ctx.cable_spice.rstrip())
        parts.append("```")
        parts.append("")

    parts.append("## LTspice runner (local)")
    parts.append("")
    if ctx.ltspice_available and ctx.ltspice_command:
        parts.append("Local LTspice installation detected. Batch command:")
        parts.append("")
        parts.append("```bash")
        parts.append(" ".join(ctx.ltspice_command))
        parts.append("```")
    else:
        parts.append(
            "LTspice was not detected locally or the project is in `dry-run` mode. "
            "Set `ltspice.executable_path` in `project.yaml` to enable simulation."
        )
    parts.append("")

    if ctx.variants:
        parts.append("## Variants (min/typ/max sweep)")
        parts.append("")
        rows = []
        for v in ctx.variants:
            overrides = ", ".join(
                f"{pid}={corner}"
                for pid, corner in sorted(v.overrides.items())
                if corner != "typ"
            ) or "—"
            rows.append([v.label, v.description, overrides])
        parts.append(_table(["label", "description", "deviations from typ"], rows))
        parts.append("")

    if ctx.measurements:
        parts.append("## Measurements (from `.raw` / `simulation_run.json`)")
        parts.append("")
        # Collect unique metric keys.
        all_keys: list[str] = []
        seen: set[str] = set()
        for entry in ctx.measurements:
            for k in (entry.get("metrics") or {}):
                if k not in seen:
                    seen.add(k)
                    all_keys.append(k)
        if all_keys:
            headers = ["variant", *all_keys]
            rows = []
            for entry in ctx.measurements:
                label = str(entry.get("label", "?"))
                metrics = entry.get("metrics") or {}
                row = [label]
                for k in all_keys:
                    v = metrics.get(k)
                    row.append("—" if v is None else f"{float(v):.4g}")
                rows.append(row)
            parts.append(_table(headers, rows))
        else:
            parts.append("_No metrics — no `.raw` files detected (dry-run or no LTspice)._")
        parts.append("")

    parts.extend(_emi_detector_section(ctx.measurements, ctx.detector_plots))

    if ctx.ranking:
        metric = ctx.ranking_metric_key or "metric"
        direction = "lower is better" if ctx.ranking_lower_is_better else "higher is better"
        parts.append(f"## Variant ranking by `{metric}` ({direction})")
        parts.append("")
        rows = []
        for r in ctx.ranking:
            delta_str = "—" if r.delta is None else f"{r.delta:+.3g}"
            pct_str = "—" if r.delta_pct is None else f"{r.delta_pct:+.1f}%"
            rows.append([str(r.rank), r.label, f"{r.metric:.3g}", delta_str, pct_str])
        parts.append(
            _table(["rank", "label", metric, "Δ vs baseline", "Δ%"], rows)
        )
        parts.append("")

    parts.append("## Recommendations")
    parts.append("")
    if ctx.recommendations:
        for rec in ctx.recommendations:
            status = (
                ctx.decision_log.status_of(rec.area, rec.id)
                if ctx.decision_log is not None
                else "proposed"
            )
            badge = {"accepted": "  `[ACCEPTED]`", "rejected": "  `[REJECTED]`"}.get(
                status, ""
            )
            parts.append(
                f"### {rec.id} — {rec.area} (severity: **{rec.severity}**, "
                f"confidence: {rec.confidence:.2f}){badge}"
            )
            parts.append("")
            if status != "proposed" and ctx.decision_log is not None:
                dec = ctx.decision_log.get(rec.area, rec.id)
                note = f" — {dec.reason}" if dec and dec.reason else ""
                parts.append(f"**Decision (M2.12):** {status}{note}")
                parts.append("")
            parts.append(f"**Problem:** {rec.problem}")
            parts.append("")
            if rec.evidence:
                parts.append("**Evidence:**")
                for e in rec.evidence:
                    parts.append(f"- {e}")
                parts.append("")
            if rec.proposed_change:
                parts.append("**Proposed change:**")
                for k, v in rec.proposed_change.items():
                    parts.append(f"- `{k}`: {v}")
                parts.append("")
            if rec.user_action:
                parts.append(f"**User action:** {rec.user_action}")
                parts.append("")
            if rec.limitations:
                parts.append("**Limitations:**")
                for lim in rec.limitations:
                    parts.append(f"- {lim}")
                parts.append("")
            if rec.sources:
                parts.append(f"**Sources:** {', '.join(rec.sources)}")
                parts.append("")
    else:
        parts.append("_No recommendations._")
    parts.append("")

    if ctx.signals:
        parts.append("## Tracked user signals (M2.10.1)")
        parts.append("")
        parts.append(
            "User-meaningful signals maintained across pipeline transformations. "
            "Each emits `.meas TRAN <name>_peak / _rms / _avg` directives so the simulation "
            "log carries metrics in the user's vocabulary alongside the canonical "
            "`v_meas_*` / `dm_*` / `cm_*` keys. Override or extend in "
            "`user_context.signals[]`."
        )
        parts.append("")
        rows = []
        for s in ctx.signals:
            band = "—"
            if s.target_band is not None:
                vals = []
                for k in ("min", "typ", "max"):
                    v = getattr(s.target_band, k)
                    if v is not None:
                        vals.append(f"{k}={v}")
                if vals:
                    band = " ".join(vals)
            rows.append(
                [
                    s.name,
                    s.kind,
                    s.expr,
                    s.unit or "—",
                    band,
                    s.source,
                    f"{s.confidence:.2f}",
                ]
            )
        parts.append(
            _table(
                ["name", "kind", "expr", "unit", "target band", "source", "confidence"],
                rows,
            )
        )
        parts.append("")

    if ctx.injection_plan:
        parts.append("## Parasitic injection plan (M2.10)")
        parts.append("")
        parts.append(
            "Parasitic X-instances spliced into the auto-generated testbench between the "
            "LISN/cable and the user fragment. The user's `.cir` is never modified; the "
            "splice lives in `generated/testbench.cir` and is audited in "
            "`generated/parasitics_wiring.json`. Use `--no-parasitics` to skip this layer."
        )
        parts.append("")
        rows = []
        for inj in ctx.injection_plan:
            rows.append(
                [
                    inj.instance_name,
                    inj.subckt_name,
                    " → ".join(inj.nets),
                    inj.corner,
                    inj.parasitic_id or "—",
                    inj.rule_id or "—",
                ]
            )
        parts.append(
            _table(
                ["instance", "subckt", "nets", "corner", "parasitic id", "rule"],
                rows,
            )
        )
        parts.append("")
        for inj in ctx.injection_plan:
            parts.append(f"**{inj.instance_name}** — _rationale_: {inj.rationale}")
        parts.append("")

    if ctx.agent_findings:
        parts.append("## Specialist findings (per area)")
        parts.append("")
        parts.append(
            "Each subsection below is one specialist agent's analysis of the project. "
            "The orchestrator (M2.11) will synthesise these into a single diagnostic "
            "narrative; today they are surfaced individually."
        )
        parts.append("")
        for finding in ctx.agent_findings:
            tag = "LLM-written" if finding.llm_generated else "deterministic fallback"
            parts.append(
                f"### {finding.area} — `{finding.agent}` "
                f"(confidence: {finding.confidence:.2f}, {tag})"
            )
            parts.append("")
            if finding.findings:
                parts.append("**Findings:**")
                for f in finding.findings:
                    parts.append(f"- _{f.severity}_ — **{f.title}** — {f.detail}")
                parts.append("")
            if finding.risks:
                parts.append("**Risks:**")
                for r in finding.risks:
                    parts.append(f"- _{r.likelihood}_ — **{r.title}** — {r.detail}")
                parts.append("")
            if finding.recommendations:
                parts.append("**Recommendations:**")
                for rec in finding.recommendations:
                    parts.append(
                        f"- **{rec.id}** _(severity {rec.severity}, "
                        f"confidence {rec.confidence:.2f})_: {rec.problem}"
                    )
                    if rec.proposed_change.get("description"):
                        parts.append(
                            f"  - proposed: {rec.proposed_change.get('description')}"
                        )
                    if rec.sources:
                        parts.append(f"  - sources: {', '.join(rec.sources)}")
                parts.append("")
            if finding.simulation_requests:
                parts.append("**Simulation requests:**")
                for s in finding.simulation_requests:
                    line = f"- {s.description}"
                    if s.kind:
                        line += f" _(kind: {s.kind})_"
                    parts.append(line)
                parts.append("")
            if finding.missing_data:
                parts.append("**Missing data:**")
                for md in finding.missing_data:
                    parts.append(f"- {md}")
                parts.append("")
            if finding.sources:
                parts.append(f"**Cited rule IDs:** {', '.join(finding.sources)}")
                parts.append("")
            if finding.limitations:
                parts.append("**Limitations:**")
                for lim in finding.limitations:
                    parts.append(f"- {lim}")
                parts.append("")

    parts.append("## Limitations and risks")
    parts.append("")
    limitations: list[str] = []
    if ctx.extra_limitations:
        limitations.extend(ctx.extra_limitations)
    limitations.append(
        "Peak / quasi-peak / average band readings are STFT-based engineering "
        "estimates, not certified EMI-receiver measurements; the quasi-peak "
        "estimate is conservative for runs shorter than the detector's "
        "discharge time constant."
    )
    limitations.append("Parasitic values are first-order estimates only.")
    limitations.append("EMC compliance cannot be confirmed without physical measurement.")
    for lim in limitations:
        parts.append(f"- {lim}")
    parts.append("")
    parts.append(PRECOMPLIANCE_DISCLAIMER)
    parts.append("")
    return "\n".join(parts)
