"""Report generation — service layer.

Runs the specialist-agent orchestrator, the M2.11 synthesiser, and
renders the Markdown / HTML report + the recommendations JSON.
"""

from __future__ import annotations

import json
import uuid as _uuid
from dataclasses import dataclass
from pathlib import Path

from emc_assistant.agents.base import AgentContext
from emc_assistant.agents.orchestrator import run_agents
from emc_assistant.knowledge.retrieve import retrieve_redacted
from emc_assistant.llm import BudgetExceeded, RecommendationDraft
from emc_assistant.logging_setup import get_logger
from emc_assistant.ltspice import LtspiceAdapter, discover_ltspice
from emc_assistant.recommendations.decisions import DecisionLog
from emc_assistant.recommendations.engine import (
    Recommendation,
    build_baseline_recommendations,
)
from emc_assistant.reports.markdown import ReportContext, render_markdown_report
from emc_assistant.results import rank_variants
from emc_assistant.results.limits import get_standard
from emc_assistant.schemas import SchemaValidationError, require_all_valid, require_valid
from emc_assistant.service import resolve
from emc_assistant.service.context import (
    build_default_parasitics,
    build_problem_context,
    load_user_context,
)
from emc_assistant.service.options import CommandOptions
from emc_assistant.service.project import require_project
from emc_assistant.service.results import ServiceError
from emc_assistant.testbench.generators import CableSpec, LisnSpec
from emc_assistant.testbench.variants import Variant

_log = get_logger("report")


def _load_baseline_metrics(layout) -> dict[str, float]:
    """Return the baseline variant's metrics, or {} if not run yet."""
    baseline_path = layout.results_dir / "variants" / "baseline.json"
    if not baseline_path.is_file():
        return {}
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    metrics = payload.get("metrics") or {}
    return {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}


def _draft_to_recommendation(draft: RecommendationDraft) -> Recommendation:
    """Convert an LLM-or-fallback draft into the dataclass the report consumes."""
    return Recommendation(
        id=draft.id,
        area=draft.area,
        severity=draft.severity,
        confidence=float(draft.confidence),
        problem=draft.problem,
        evidence=list(draft.evidence),
        proposed_change=dict(draft.proposed_change),
        simulation_required=bool(draft.simulation_required),
        user_action=draft.user_action,
        limitations=list(draft.limitations),
        sources=list(draft.sources),
        llm_generated=bool(draft.llm_generated),
        citations=list(draft.citations),
    )


def _load_variants_for_report(layout, parasitics) -> list[Variant] | None:
    """Load variants from ``generated/variants/variants.json`` if present."""
    path = layout.generated_dir / "variants" / "variants.json"
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: list[Variant] = []
    base_by_id = {p.id: p for p in parasitics}
    for entry in raw:
        v_parasitics = []
        for pid, corner in entry.get("overrides", {}).items():
            base = base_by_id.get(pid)
            if base is None:
                continue
            v_parasitics.append(base.at_corner(corner) if corner != "typ" else base)
        out.append(
            Variant(
                label=entry["label"],
                description=entry.get("description", ""),
                overrides=dict(entry.get("overrides", {})),
                parasitics=v_parasitics,
            )
        )
    return out


def _load_measurements_for_report(layout) -> list[dict] | None:
    """Read ``results/variants/*.json`` and return a list of {label, metrics}."""
    var_dir = layout.results_dir / "variants"
    if not var_dir.is_dir():
        return None
    out: list[dict] = []
    for run_path in sorted(var_dir.glob("*.json")):
        payload = json.loads(run_path.read_text(encoding="utf-8"))
        label = payload.get("variant_label") or run_path.stem
        metrics = payload.get("metrics") or {}
        out.append({"label": label, "metrics": metrics})
    return out


def _load_ranking_for_report(layout, options: CommandOptions):
    """Build a ranking from ``results/variants/*.json`` if a metric key was given."""
    metric_key = options.rank_metric
    if not metric_key:
        return None, None
    var_dir = layout.results_dir / "variants"
    if not var_dir.is_dir():
        return None, metric_key
    pairs: list[tuple[str, dict[str, float]]] = []
    for run_path in sorted(var_dir.glob("*.json")):
        payload = json.loads(run_path.read_text(encoding="utf-8"))
        label = (
            payload.get("variant_label")
            or payload.get("project_id")
            or run_path.stem
        )
        metrics = payload.get("metrics", {}) or {}
        pairs.append((label, metrics))
    ranking = rank_variants(
        pairs, metric_key=metric_key, lower_is_better=bool(options.lower_is_better),
    )
    return ranking, metric_key


_PEAK_KEY = "v_meas_band_peak_dbuv_150000_30000000"
_QP_KEY = "v_meas_band_quasi_peak_dbuv_150000_30000000"
_MARGIN_DB = "v_meas_qp_worst_margin_db"
_MARGIN_HZ = "v_meas_qp_worst_margin_hz"


@dataclass
class ResultsView:
    """Aggregated view of a completed run for the Results screen."""
    diagnostic: dict | None
    rank_metric: str
    has_metrics: bool
    ranking: list[dict]
    baseline: dict


def load_results(project_root, rank_metric: str | None = None) -> ResultsView:
    """Aggregate a completed run's artifacts for the Results screen: the
    diagnostic narrative (``results/diagnostic.json``) + the corner-variant
    ranking and headline metrics (from ``results/variants/*.json``).

    Degrades gracefully: ``has_metrics`` is False before a local-run (the
    variant metrics are empty in dry-run), and ``diagnostic`` is None if the
    synthesiser hasn't written yet.
    """
    _config, layout = require_project(project_root)

    diag_path = layout.results_dir / "diagnostic.json"
    diagnostic: dict | None = None
    if diag_path.is_file():
        try:
            diagnostic = json.loads(diag_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            diagnostic = None

    measurements = _load_measurements_for_report(layout) or []
    pairs = [(m["label"], m.get("metrics") or {}) for m in measurements]
    has_metrics = any(bool(m) for _label, m in pairs)
    metric_key = rank_metric or _PEAK_KEY

    def _num(m: dict, k: str):
        v = m.get(k)
        return float(v) if isinstance(v, (int, float)) else None

    ranking: list[dict] = []
    if has_metrics:
        ranked = rank_variants(pairs, metric_key=metric_key, lower_is_better=False)
        by_label = {lbl: m for lbl, m in pairs}
        for r in ranked:
            m = by_label.get(r.label, {})
            ranking.append({
                "rank": r.rank, "label": r.label, "metric": r.metric,
                "delta": r.delta, "delta_pct": r.delta_pct,
                "peak_dbuv": _num(m, _PEAK_KEY), "qp_dbuv": _num(m, _QP_KEY),
                "margin_db": _num(m, _MARGIN_DB), "margin_hz": _num(m, _MARGIN_HZ),
                "dm_peak": _num(m, "dm_peak"), "cm_peak": _num(m, "cm_peak"),
            })

    base = next((m for lbl, m in pairs if lbl == "baseline"), {})
    peaks = [r["peak_dbuv"] for r in ranking if r["peak_dbuv"] is not None]
    baseline = {
        "peak_dbuv": _num(base, _PEAK_KEY),
        "qp_dbuv": _num(base, _QP_KEY),
        "margin_db": _num(base, _MARGIN_DB),
        "margin_hz": _num(base, _MARGIN_HZ),
        "vout_rms": _num(base, "vout_rms"),
        "dm_peak": _num(base, "dm_peak"),
        "cm_peak": _num(base, "cm_peak"),
        "span_db": (max(peaks) - min(peaks)) if len(peaks) >= 2 else None,
    }
    return ResultsView(
        diagnostic=diagnostic, rank_metric=metric_key,
        has_metrics=has_metrics, ranking=ranking, baseline=baseline,
    )


def _render_detector_plots(layout) -> list[tuple[str, str]]:
    """Render the CISPR detector-vs-limit plots from
    ``generated/testbench.raw`` into ``reports/``. Returns
    ``[(caption, image_filename), …]`` for the plots that rendered —
    empty when the run cannot be plotted (no ``.raw``, a timestep too
    coarse for band B, or matplotlib absent). A plot failure is logged,
    never raised — it must not abort the report."""
    raw_path = layout.generated_dir / "testbench.raw"
    if not raw_path.is_file():
        return []
    from emc_assistant.reports.detector_plot import render_detector_plot

    std_name = get_standard(None).name
    layout.reports_dir.mkdir(parents=True, exist_ok=True)
    specs = [
        ("diagnostic", "detector_plot_diagnostic.png",
         f"CISPR band-B detectors — diagnostic (Mode 1) vs {std_name} limits"),
        ("receiver", "detector_plot_receiver.png",
         f"CISPR band-B detectors — receiver-like sweep (Mode 3) vs "
         f"{std_name} limits"),
    ]
    plots: list[tuple[str, str]] = []
    for mode, fname, caption in specs:
        ok, detail = render_detector_plot(
            raw_path, layout.reports_dir / fname, mode=mode,
        )
        if ok:
            plots.append((caption, fname))
        else:
            _log.info(f"[detector-plot] {mode}: skipped — {detail}")
    return plots


@dataclass
class ReportResult:
    report_path: Path
    html_path: Path | None
    pdf_path: Path | None
    recommendations_path: Path
    ltspice_available: bool


def generate_report(project_root, options: CommandOptions) -> ReportResult:
    """Run the agents + synthesiser, render the report + recommendations JSON."""
    config, layout = require_project(project_root)
    user_context = load_user_context(layout)

    parasitics = build_default_parasitics(user_context)
    from emc_assistant.testbench.generators import (
        generate_cable_fragment,
        generate_lisn_subckt,
    )

    lisn = generate_lisn_subckt(LisnSpec())
    cable_length = (
        float(user_context.get("cable_length_m", 1.0))
        if isinstance(user_context, dict) else 1.0
    )
    cable = generate_cable_fragment(CableSpec(length_m=cable_length))

    has_stackup = bool(user_context.get("pcb", {}).get("layers"))
    baseline_recs = build_baseline_recommendations(
        parasitics, has_layout=False, has_stackup=has_stackup,
    )

    problem_context = build_problem_context(config, user_context, parasitics)
    sim_metrics = _load_baseline_metrics(layout)
    snippets = retrieve_redacted(problem_context, k=int(options.llm_top_k))

    run_id = f"rep-{_uuid.uuid4().hex[:8]}"
    assistant, log_path = resolve.make_assistant(options, layout=layout, run_id=run_id)
    llm_mode = options.llm_mode or "replace"
    if llm_mode not in ("replace", "augment"):
        raise ServiceError(f"Invalid --llm-mode: {llm_mode}")

    try:
        drafts = assistant.explain_recommendations(
            problem_context=problem_context,
            parasitics=parasitics,
            sim_metrics=sim_metrics,
            snippets=snippets,
            mode=llm_mode,
            baseline_recs=baseline_recs,
        )
    except BudgetExceeded as exc:
        raise ServiceError(f"LLM call aborted: {exc}", exit_code=2) from exc

    recs = [_draft_to_recommendation(d) for d in drafts]
    if assistant.name != "deterministic":
        _log.info(
            f"  LLM ({assistant.name}) wrote {len(drafts)} recommendation(s) "
            f"in mode={llm_mode}"
        )
        if log_path:
            _log.info(f"  privacy log: {log_path}")

    resolved_signals = resolve.resolve_signals(
        user_context, options, layout=layout, project_root_path=project_root,
    )

    # Forward topology + DUT net names to the agent context so the
    # parasitics_agent + signal_map_agent see concrete net strings.
    agent_topology = None
    per_net_estimates = None
    fragment_for_topo = layout.generated_dir / "user_circuit_fragment.cir"
    if fragment_for_topo.is_file():
        try:
            from emc_assistant.netlist.topology import analyse_fragment

            agent_topology = analyse_fragment(fragment_for_topo)
        except Exception as exc:  # noqa: BLE001
            _log.warning(f"[agents] topology analysis failed: {exc}")
    if agent_topology is not None:
        try:
            from emc_assistant.parasitics.per_net import estimate_all_nets

            per_net_estimates = estimate_all_nets(agent_topology)
            n_inj = sum(1 for n in per_net_estimates if n.injectable)
            _log.info(
                f"[parasitics] per-net estimate: {len(per_net_estimates)} nets "
                f"({n_inj} injectable 2-element)"
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning(f"[parasitics] per-net estimation failed: {exc}")
    agent_supply_net = ""
    agent_return_net = ""
    wiring_cfg = (user_context or {}).get("testbench_wiring")
    if isinstance(wiring_cfg, dict):
        agent_supply_net = str(wiring_cfg.get("dut_supply_net", ""))
        agent_return_net = str(wiring_cfg.get("dut_return_net", ""))
        lisn_mode = str(wiring_cfg.get("lisn_mode", "dual")).strip().lower() or "dual"
        if lisn_mode == "dual" and agent_return_net in {"0", ""}:
            agent_return_net = "DUT_GND"

    # M2.9.1: per-agent retrieval.
    agent_retrieve_fn = None
    if assistant.name != "deterministic":
        retrieval_embedder = options.stub_embedder
        if retrieval_embedder is None and options.stub_assistant is not None:
            from emc_assistant.knowledge.embedder import EmbedderStub

            retrieval_embedder = EmbedderStub()
        if retrieval_embedder is None:
            try:
                from emc_assistant.knowledge.embedder import make_embedder

                retrieval_embedder = make_embedder()
            except Exception as exc:  # noqa: BLE001 — [embeddings] extra may be absent
                _log.warning(
                    f"[retrieval] real embedder unavailable ({type(exc).__name__}); "
                    "per-agent retrieval will use the keyword fallback."
                )

        from emc_assistant.knowledge.retrieve import retrieve_for_keywords

        _top_k = int(options.llm_top_k)

        def agent_retrieve_fn(keywords: list[str]):  # noqa: E306
            return retrieve_for_keywords(
                keywords, problem_context, k=_top_k, embedder=retrieval_embedder,
            )

    agent_ctx = AgentContext(
        problem_context=problem_context,
        parasitics=list(parasitics),
        sim_metrics=dict(sim_metrics),
        snippets=list(snippets),
        baseline_recs=list(baseline_recs),
        signals=list(resolved_signals),
        topology=agent_topology,
        dut_supply_net=agent_supply_net,
        dut_return_net=agent_return_net,
        retrieve_fn=agent_retrieve_fn,
    )
    try:
        orch_result = run_agents(
            agent_ctx, assistant=assistant, output_dir=layout.results_dir,
        )
    except BudgetExceeded as exc:
        raise ServiceError(
            f"Agent orchestration aborted: {exc}", exit_code=2
        ) from exc

    _log.info(
        f"  agents: {len(orch_result.findings)} findings written to "
        f"{layout.results_dir / 'findings'}"
    )
    if orch_result.failed_agents:
        _log.info(
            "  agents with LLM failures (fell back to deterministic): "
            + ", ".join(orch_result.failed_agents)
        )
    if orch_result.budget_exhausted:
        _log.info(
            "  agents: LLM budget exhausted mid-run; remaining agents used "
            "deterministic fallback"
        )

    configured = str(config.ltspice.get("executable_path") or "")
    executable = discover_ltspice(configured or None)
    adapter = LtspiceAdapter(
        executable=executable,
        timeout_seconds=int(config.ltspice.get("timeout_seconds", 120)),
    )
    netlist_rel = config.inputs.get("netlist_path", "")
    netlist_for_cmd = (
        (layout.root / netlist_rel).resolve()
        if netlist_rel else layout.generated_dir / "main.cir"
    )
    command = adapter.build_command(netlist_for_cmd)

    actual_injection_plan = resolve.resolve_parasitics_injection(
        user_context, options, parasitics=parasitics, user_fragment_path=None,
    )

    # M2.11: synthesise a top-level diagnostic narrative.
    from emc_assistant.agents.synthesiser import Synthesiser

    synth = Synthesiser()
    ranking_payload: list[dict] = []
    raw_ranking, ranking_key_for_synth = _load_ranking_for_report(layout, options)
    if raw_ranking:
        ranking_payload = [
            {
                "rank": r.rank,
                "label": r.label,
                "metric": r.metric,
                "delta": r.delta,
                "delta_pct": r.delta_pct,
            }
            for r in raw_ranking
        ]
    if assistant.name == "deterministic":
        diagnostic = synth.deterministic_synthesise(
            findings=list(orch_result.findings),
            ranking=ranking_payload,
            sim_metrics=dict(sim_metrics),
        )
    else:
        try:
            diagnostic = synth.synthesise(
                problem_ctx=problem_context,
                findings=list(orch_result.findings),
                sim_metrics=dict(sim_metrics),
                ranking=ranking_payload,
                ranking_metric_key=ranking_key_for_synth,
                snippets=list(snippets),
                signals=list(resolved_signals),
                assistant=assistant,
            )
        except BudgetExceeded:
            _log.warning(
                "Synthesiser: budget exhausted; falling back to deterministic stub."
            )
            diagnostic = synth.deterministic_synthesise(
                findings=list(orch_result.findings),
                ranking=ranking_payload,
                sim_metrics=dict(sim_metrics),
            )
            diagnostic.limitations.append(
                "Run-level LLM budget exhausted before the synthesis call."
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                f"Synthesiser: LLM call failed ({type(exc).__name__}); "
                "using deterministic stub."
            )
            diagnostic = synth.deterministic_synthesise(
                findings=list(orch_result.findings),
                ranking=ranking_payload,
                sim_metrics=dict(sim_metrics),
            )
            diagnostic.limitations.append(
                f"LLM synthesis failed ({type(exc).__name__}); "
                "deterministic stub used."
            )
    diag_dict = diagnostic.to_schema_dict()
    require_valid("diagnostic_narrative.schema.json", diag_dict)
    (layout.results_dir / "diagnostic.json").write_text(
        json.dumps(diag_dict, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    tag = "LLM" if diagnostic.llm_generated else "fallback"
    _log.info(
        f"  synthesis ({tag}): {diagnostic.title[:80]} "
        f"(conf {diagnostic.confidence:.2f})"
    )

    # Deterministic sim-setup integrity → report limitations (band coverage,
    # switching-edge resolution, frequency resolution).
    from emc_assistant.service.testbench import _assess_sim
    from emc_assistant.testbench.sim_settings import SimulationSettings

    _extra_lims: list[str] = []
    if not adapter.available:
        _extra_lims.append("LTspice was not detected locally — no simulation was run.")
    for _c in _assess_sim(SimulationSettings.from_user_context(user_context), user_context).checks:
        if _c.severity in ("high", "medium"):
            _extra_lims.append(
                "Simulation setup: " + _c.message
                + (f" {_c.recommendation}" if _c.recommendation else "")
            )

    # M2.17: per-net value provenance, read from the re-evaluation audit (if a
    # `parasitics reevaluate` pass has run). Nets absent from it default to the
    # calculator in the report's per-net table.
    per_net_value_source: dict[str, str] | None = None
    _reeval_path = layout.generated_dir / "parasitics_reevaluated.json"
    if _reeval_path.is_file():
        _prov = {
            "llm_rag": "LLM-refined (RAG)",
            "engineering_estimate": "LLM (uncited est.)",
            "rule_of_thumb": "calculator (rule-of-thumb)",
        }
        try:
            _reeval = json.loads(_reeval_path.read_text(encoding="utf-8"))
            per_net_value_source = {
                n["net"]: _prov.get(n.get("value_source", ""), "calculator (rule-of-thumb)")
                for n in _reeval.get("nets", []) if n.get("net")
            }
        except (OSError, json.JSONDecodeError):
            per_net_value_source = None

    ctx = ReportContext(
        project=config,
        parasitics=parasitics,
        recommendations=recs,
        lisn_spice=lisn,
        cable_spice=cable,
        ltspice_available=adapter.available,
        ltspice_command=command,
        extra_limitations=_extra_lims or None,
        agent_findings=list(orch_result.findings),
        injection_plan=list(actual_injection_plan),
        signals=list(resolved_signals),
        diagnostic=diagnostic,
        per_net_parasitics=per_net_estimates,
        per_net_value_source=per_net_value_source,
        decision_log=DecisionLog.load(layout.decisions_dir),
    )

    rec_payload = [r.to_schema_dict() for r in recs]
    try:
        require_all_valid("recommendation.schema.json", rec_payload)
    except SchemaValidationError as exc:
        raise ServiceError(
            f"Recommendations violate the schema:\n{exc}"
        ) from exc

    variants_list = _load_variants_for_report(layout, parasitics)
    measurements = _load_measurements_for_report(layout)
    ranking, ranking_key = _load_ranking_for_report(layout, options)
    ctx.variants = variants_list
    ctx.measurements = measurements
    ctx.ranking = ranking
    ctx.ranking_metric_key = ranking_key
    ctx.ranking_lower_is_better = bool(options.lower_is_better)
    ctx.detector_plots = _render_detector_plots(layout)

    markdown = render_markdown_report(ctx)
    layout.reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = layout.reports_dir / "report.md"
    out_path.write_text(markdown, encoding="utf-8")

    html_path = None
    if options.html:
        from emc_assistant.reports.html import markdown_to_html

        html_path = layout.reports_dir / "report.html"
        html_path.write_text(
            markdown_to_html(markdown, title=f"EMC report — {config.project_id}"),
            encoding="utf-8",
        )
        _log.info(f"HTML report written: {html_path}")

    pdf_path = None
    if options.pdf:
        from emc_assistant.reports.pdf import markdown_to_pdf

        pdf_path = layout.reports_dir / "report.pdf"
        markdown_to_pdf(
            markdown, pdf_path, title=f"EMC report — {config.project_id}",
        )
        _log.info(f"PDF report written: {pdf_path}")

    layout.generated_dir.mkdir(parents=True, exist_ok=True)
    rec_path = layout.generated_dir / "recommendations.json"
    rec_path.write_text(json.dumps(rec_payload, indent=2), encoding="utf-8")
    _log.info(f"Report written: {out_path}")
    _log.info(f"Recommendations JSON: {rec_path}")
    _log.info(f"LTspice available locally: {adapter.available}")
    return ReportResult(
        report_path=out_path,
        html_path=html_path,
        pdf_path=pdf_path,
        recommendations_path=rec_path,
        ltspice_available=adapter.available,
    )
