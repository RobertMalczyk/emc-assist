"""Diagnostic-narrative synthesiser (M2.11).

After the 11 specialist agents fan out (``agents/orchestrator.py``),
this module reads their findings + simulation metrics + variant
ranking + retrieved snippets and produces ONE diagnostic paragraph
that opens the report. Two paths:

- **LLM path** (`Synthesiser.synthesise`): builds a prompt using the
  workflow recipe (`prompts/workflows/conducted_emi_dcdc_workflow.md`),
  calls `LlmAssistant.complete()`, parses the JSON into a
  :class:`DiagnosticNarrative`.
- **Deterministic fallback** (`Synthesiser.deterministic_synthesise`):
  no LLM. Picks the top-3 highest-severity findings, names the most
  common topic, emits a templated paragraph. Used when `--llm none`
  or when the LLM response is malformed.

Aggregation: :func:`aggregate_findings` deterministically clusters
across agents by keyword-matching the finding titles + details into a
small set of canonical topics (DM dominance, hot loop, decoupling,
stability, layout, signal map). This pre-filter is what gets handed
to the LLM so it reasons over a structured summary rather than 11
raw JSONs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from emc_assistant.agents.base import (
    AgentFinding,
    parse_json_object,
)
from emc_assistant.llm.assistant import (
    LlmAssistant,
    ProblemContext,
    RedactedSnippet,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PROMPT_PATH = REPO_ROOT / "prompts" / "workflows" / "conducted_emi_dcdc_workflow.md"


@dataclass
class DiagnosticNarrative:
    """Mirrors ``schemas/diagnostic_narrative.schema.json``."""

    title: str
    narrative: str
    dominant_issue: str
    confidence: float = 0.5
    llm_generated: bool = False
    cited_findings: list[str] = field(default_factory=list)
    cited_variants: list[str] = field(default_factory=list)
    cited_rule_ids: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_schema_dict(self) -> dict:
        return {
            "title": self.title,
            "narrative": self.narrative,
            "dominant_issue": self.dominant_issue,
            "confidence": float(self.confidence),
            "llm_generated": bool(self.llm_generated),
            "cited_findings": list(self.cited_findings),
            "cited_variants": list(self.cited_variants),
            "cited_rule_ids": list(self.cited_rule_ids),
            "limitations": list(self.limitations),
        }


@dataclass
class FindingCluster:
    """A group of findings across agents that converged on the same topic."""

    topic: str
    agents: list[str] = field(default_factory=list)
    """Agent names that contributed at least one finding to this cluster."""
    sample_titles: list[str] = field(default_factory=list)
    """First finding title from each contributing agent (for the prompt)."""
    max_severity: str = "info"
    """Highest severity seen in this cluster."""


# Canonical clustering topics with keyword tags. Each topic catches a
# common cross-agent theme observed in the buck + case_002 smoke tests.
_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "dm_dominance": ("dm domin", "differential mode domin", "dm peak", "dm-peak"),
    "input_filter_stability": ("filter stability", "regulator instability", "damping", "undamped"),
    "hot_loop": ("hot loop", "switch-node", "switch node", "ringing", "dv/dt"),
    "decoupling_antiresonance": ("antiresonance", "anti-resonance", "srf", "bulk and ceramic"),
    "parasitic_loop_resonance": ("loop resonance", "parasitic resonance", "lc resonance"),
    "rail_impedance": ("rail impedance", "z(f)", "input impedance"),
    "no_layout": ("no layout", "layout not supplied", "layout-dependent", "without layout"),
    "no_stackup": ("no stack-up", "stackup not supplied", "stack-up missing"),
    "missing_datasheet": ("datasheet missing", "no datasheet", "no vendor", "vendor reference"),
    "signal_map_gap": ("signal map", "iout", "current probe", "target band"),
}


_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def _match_topic(text: str) -> str | None:
    n = _normalise(text)
    for topic, keywords in _TOPIC_KEYWORDS.items():
        if any(k in n for k in keywords):
            return topic
    return None


def aggregate_findings(findings: list[AgentFinding]) -> list[FindingCluster]:
    """Deterministic cross-agent clustering.

    Each agent finding contributes to one topic (the first matching
    keyword tag). Findings that don't match any topic are skipped from
    the cluster output — they're still in the per-area subsections, but
    the synthesiser only sees clustered themes. Sorted by:

    1. Number of contributing agents (descending).
    2. Highest severity in the cluster (descending).
    """
    clusters: dict[str, FindingCluster] = {}
    for ag_finding in findings:
        agent = ag_finding.agent
        for f in ag_finding.findings:
            topic = _match_topic(f.title + " " + f.detail)
            if not topic:
                continue
            cluster = clusters.get(topic)
            if cluster is None:
                cluster = FindingCluster(topic=topic)
                clusters[topic] = cluster
            if agent not in cluster.agents:
                cluster.agents.append(agent)
                cluster.sample_titles.append(f.title)
            if _SEVERITY_RANK.get(f.severity, 0) > _SEVERITY_RANK.get(cluster.max_severity, 0):
                cluster.max_severity = f.severity
    return sorted(
        clusters.values(),
        key=lambda c: (-len(c.agents), -_SEVERITY_RANK.get(c.max_severity, 0)),
    )


# ---- Synthesiser -----------------------------------------------------------


def _format_problem(ctx: ProblemContext) -> str:
    parts = [f"project_id: {ctx.project_id}", f"analysis_scope: {ctx.analysis_scope}"]
    if ctx.topology:
        parts.append(f"topology: {ctx.topology}")
    if ctx.input_voltage_v is not None:
        parts.append(f"input_voltage_v: {ctx.input_voltage_v}")
    if ctx.switching_frequency_hz is not None:
        parts.append(f"switching_frequency_hz: {ctx.switching_frequency_hz}")
    if ctx.load_current_a is not None:
        parts.append(f"load_current_a: {ctx.load_current_a}")
    parts.append(f"has_layout: {ctx.has_layout}")
    parts.append(f"has_stackup: {ctx.has_stackup}")
    if ctx.missing_data:
        parts.append("missing_data: " + ", ".join(ctx.missing_data))
    return "\n".join(parts)


def _format_metrics(metrics: dict[str, float]) -> str:
    if not metrics:
        return "(none)"
    return "\n".join(f"- {k}: {v}" for k, v in sorted(metrics.items()))


def _format_ranking(ranking: list[dict] | None, metric_key: str | None) -> str:
    if not ranking:
        return "(no ranking available)"
    out = []
    metric_name = metric_key or "metric"
    out.append(f"Ranked by {metric_name}:")
    for r in ranking[:5]:
        label = r.get("label", "?")
        m = r.get("metric")
        d = r.get("delta")
        dp = r.get("delta_pct")
        out.append(
            f"  rank {r.get('rank','?')}: {label}  {metric_name}={m}  Δ={d}  Δ%={dp}"
        )
    return "\n".join(out)


def _format_clusters(clusters: list[FindingCluster]) -> str:
    if not clusters:
        return "(no convergent themes detected across agents)"
    out = []
    for c in clusters:
        out.append(
            f"- topic={c.topic} | severity={c.max_severity} | "
            f"agents=[{', '.join(c.agents)}]"
        )
        for title in c.sample_titles[:3]:
            out.append(f"    • {title}")
    return "\n".join(out)


def _format_snippets(snippets: list[RedactedSnippet]) -> str:
    if not snippets:
        return "(no snippets retrieved)"
    return "\n".join(
        f"- [{s.rule_id} / {s.source_id}] {s.summary}" for s in snippets[:10]
    )


def _format_signals(signals_list: list | None) -> str:
    if not signals_list:
        return "(no tracked signals)"
    parts = []
    for s in signals_list:
        # s is a Signal dataclass with .name, .kind, .expr
        parts.append(f"- {s.name} ({s.kind}) = {s.expr}")
    return "\n".join(parts)


def _build_user_payload(
    *,
    problem_ctx: ProblemContext,
    sim_metrics: dict[str, float],
    ranking: list[dict] | None,
    ranking_metric_key: str | None,
    clusters: list[FindingCluster],
    snippets: list[RedactedSnippet],
    signals: list | None,
) -> str:
    return (
        "# Problem context\n\n"
        f"{_format_problem(problem_ctx)}\n\n"
        "# Simulation metrics\n\n"
        f"{_format_metrics(sim_metrics)}\n\n"
        "# Variant ranking\n\n"
        f"{_format_ranking(ranking, ranking_metric_key)}\n\n"
        "# Aggregated findings (cross-agent clusters)\n\n"
        f"{_format_clusters(clusters)}\n\n"
        "# Retrieved knowledge snippets (redacted)\n\n"
        f"{_format_snippets(snippets)}\n\n"
        "# Tracked user signals\n\n"
        f"{_format_signals(signals)}\n\n"
        "Respond with ONE JSON object matching the schema in the system prompt. "
        "Start with `{` and end with `}`."
    )


def _load_workflow_prompt() -> str:
    return WORKFLOW_PROMPT_PATH.read_text(encoding="utf-8")


class Synthesiser:
    """Diagnostic-narrative synthesiser."""

    name = "synthesiser"

    def __init__(self, *, prompt_path: Path | None = None) -> None:
        self.prompt_path = prompt_path or WORKFLOW_PROMPT_PATH

    def synthesise(
        self,
        *,
        problem_ctx: ProblemContext,
        findings: list[AgentFinding],
        sim_metrics: dict[str, float],
        ranking: list[dict] | None,
        ranking_metric_key: str | None,
        snippets: list[RedactedSnippet],
        signals: list | None,
        assistant: LlmAssistant,
    ) -> DiagnosticNarrative:
        """LLM path. Falls back to deterministic on malformed JSON."""
        clusters = aggregate_findings(findings)
        system_prompt = self.prompt_path.read_text(encoding="utf-8")
        user_payload = _build_user_payload(
            problem_ctx=problem_ctx,
            sim_metrics=sim_metrics,
            ranking=ranking,
            ranking_metric_key=ranking_metric_key,
            clusters=clusters,
            snippets=snippets,
            signals=signals,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ]
        try:
            response = assistant.complete(
                messages=messages,
                purpose="synthesis.diagnostic",
                expected_output_tokens=900,
            )
        except Exception:
            # BudgetExceeded or network failure — surface to the orchestrator.
            raise
        try:
            return self._parse_response(response, clusters=clusters)
        except ValueError:
            fallback = self.deterministic_synthesise(
                findings=findings, ranking=ranking, sim_metrics=sim_metrics,
            )
            fallback.limitations.append(
                "LLM response was malformed; deterministic stub was used."
            )
            return fallback

    def deterministic_synthesise(
        self,
        *,
        findings: list[AgentFinding],
        ranking: list[dict] | None,
        sim_metrics: dict[str, float],
    ) -> DiagnosticNarrative:
        """No-LLM path. Names the dominant cluster + top-severity findings."""
        clusters = aggregate_findings(findings)
        if clusters:
            top = clusters[0]
            agents_str = ", ".join(top.agents)
            title = f"{top.topic.replace('_', ' ').title()} (deterministic synthesis)"
            dominant = (
                f"{len(top.agents)} agents converged on '{top.topic}' "
                f"(max severity: {top.max_severity})"
            )
            narrative = (
                f"Deterministic synthesis: {len(top.agents)} agents "
                f"({agents_str}) flagged a convergent theme around "
                f"'{top.topic.replace('_', ' ')}' with severity {top.max_severity}. "
                "This is the leading hypothesis pending LLM-assisted analysis. "
                "Run with `--llm openai` for a narrative grounded in the "
                "retrieved knowledge snippets and the variant ranking."
            )
            cited_findings = list(top.agents)
            confidence = min(0.6, 0.2 + 0.1 * len(top.agents))
        else:
            title = "Pending diagnosis"
            dominant = "No cross-agent convergent themes detected."
            narrative = (
                "Deterministic synthesis: the 11 specialist agents produced "
                "findings but no theme was matched by the deterministic "
                "topic clusterer. Re-run with `--llm openai` for a free-form "
                "synthesis of the per-area sections."
            )
            cited_findings = []
            confidence = 0.2

        # Top variant by metric, if ranking exists
        cited_variants: list[str] = []
        if ranking:
            for r in ranking[:2]:
                lbl = r.get("label")
                if lbl:
                    cited_variants.append(str(lbl))

        return DiagnosticNarrative(
            title=title,
            narrative=narrative,
            dominant_issue=dominant,
            confidence=confidence,
            llm_generated=False,
            cited_findings=cited_findings,
            cited_variants=cited_variants,
            cited_rule_ids=[],
            limitations=["Deterministic stub; no LLM was invoked."],
        )

    def _parse_response(
        self, response_text: str, *, clusters: list[FindingCluster]
    ) -> DiagnosticNarrative:
        data = parse_json_object(response_text)
        title = str(data.get("title") or "").strip()
        narrative = str(data.get("narrative") or "").strip()
        dominant = str(data.get("dominant_issue") or "").strip()
        if not (title and narrative and dominant):
            raise ValueError(
                "LLM diagnostic narrative is missing one of title / narrative / dominant_issue."
            )
        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        return DiagnosticNarrative(
            title=title,
            narrative=narrative,
            dominant_issue=dominant,
            confidence=confidence,
            llm_generated=True,
            cited_findings=[str(x) for x in data.get("cited_findings") or []],
            cited_variants=[str(x) for x in data.get("cited_variants") or []],
            cited_rule_ids=[str(x) for x in data.get("cited_rule_ids") or []],
            limitations=[str(x) for x in data.get("limitations") or []],
        )
