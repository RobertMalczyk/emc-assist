"""Base class and dataclasses for specialist agents.

The shape mirrors ``schemas/agent_finding.schema.json``. Each per-area
agent subclass overrides:

- :attr:`name` — short stable identifier (``"dcdc"``, ``"filtering"``, …)
- :attr:`area_title` — human-readable title used in the report
- :attr:`prompt_path` — path to the per-agent prompt template
- :meth:`select_relevant` — slice ``AgentContext`` into per-agent inputs
- :meth:`deterministic_finding` — rule-based fallback when no LLM
- :meth:`parse_response` — parse the LLM JSON reply into ``AgentFinding``

The orchestrator picks the LLM or fallback path based on
``assistant.name`` and threads a single ``BudgetTracker`` across all
agents in one ``pipeline run``.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from emc_assistant.agents.injection import ParasiticInjection, from_dict as _injection_from_dict
from emc_assistant.llm.assistant import (
    LlmAssistant,
    ProblemContext,
    RedactedSnippet,
)
from emc_assistant.netlist.signals import Signal
from emc_assistant.netlist.topology import TopologyReport
from emc_assistant.parasitics.model import ParasiticEstimate
from emc_assistant.recommendations.engine import Recommendation


REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_AGENTS_DIR = REPO_ROOT / "prompts" / "agents"


@dataclass
class Finding:
    """One observation from an agent."""

    title: str
    detail: str
    severity: str = "info"

    def to_dict(self) -> dict:
        return {"title": self.title, "detail": self.detail, "severity": self.severity}


@dataclass
class Risk:
    """A specific risk the agent flagged."""

    title: str
    detail: str
    likelihood: str = "medium"

    def to_dict(self) -> dict:
        return {"title": self.title, "detail": self.detail, "likelihood": self.likelihood}


@dataclass
class SimulationRequest:
    """A follow-up simulation the agent recommends."""

    description: str
    kind: str = ""
    parameters: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        out: dict = {"description": self.description}
        if self.kind:
            out["kind"] = self.kind
        if self.parameters:
            out["parameters"] = dict(self.parameters)
        return out


@dataclass
class AgentFinding:
    """The agent's complete output for one pipeline run.

    Mirrors ``schemas/agent_finding.schema.json``. Built either by the
    LLM path (:meth:`Agent.parse_response`) or the deterministic
    fallback (:meth:`Agent.deterministic_finding`).
    """

    agent: str
    area: str
    confidence: float
    findings: list[Finding] = field(default_factory=list)
    risks: list[Risk] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)
    simulation_requests: list[SimulationRequest] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    llm_generated: bool = False
    injections: list[ParasiticInjection] = field(default_factory=list)
    """M2.10 parasitic-injection plan. Empty for every agent except the
    parasitics agent. Populated entries propose splicing
    composer-generated subcircuits (TRACE_RLC, VIA_L, CAP_ESR_ESL) into
    the testbench between the LISN/cable and the user fragment."""

    def to_schema_dict(self) -> dict:
        out = {
            "agent": self.agent,
            "area": self.area,
            "confidence": float(self.confidence),
            "findings": [f.to_dict() for f in self.findings],
            "risks": [r.to_dict() for r in self.risks],
            "recommendations": [r.to_schema_dict() for r in self.recommendations],
            "missing_data": list(self.missing_data),
            "simulation_requests": [s.to_dict() for s in self.simulation_requests],
            "sources": list(self.sources),
            "limitations": list(self.limitations),
            "llm_generated": bool(self.llm_generated),
        }
        if self.injections:
            out["injections"] = [inj.to_schema_dict() for inj in self.injections]
        return out


@dataclass
class AgentContext:
    """Full project context handed to the orchestrator.

    The orchestrator passes the same context to every agent; each agent
    decides what slice to use via :meth:`Agent.select_relevant`.
    """

    problem_context: ProblemContext
    parasitics: list[ParasiticEstimate] = field(default_factory=list)
    sim_metrics: dict[str, float] = field(default_factory=dict)
    snippets: list[RedactedSnippet] = field(default_factory=list)
    baseline_recs: list[Recommendation] = field(default_factory=list)
    topology: TopologyReport | None = None
    """M2.10: net-structure report from
    :func:`emc_assistant.netlist.topology.analyse_fragment`. Populated
    when the pipeline has access to the user fragment; the parasitics
    agent reads this to propose physically-meaningful injection points."""
    dut_supply_net: str = ""
    """M2.10: the user fragment's nominal supply net (from user_context
    testbench_wiring). The parasitics agent splices trace L between
    this net and the cable output."""
    dut_return_net: str = ""
    """M2.10: the user fragment's nominal return net (DUT_GND in dual-LISN)."""
    signals: list[Signal] = field(default_factory=list)
    """M2.10.1: resolved user signal map (after the deterministic
    deduction + the feature-keeper's interactive acceptance). The
    signal_map_agent reads this to propose LLM-driven refinements."""
    retrieve_fn: Callable[[list[str]], list[RedactedSnippet]] | None = None
    """M2.9.1: per-agent retrieval hook. When set, each agent calls it
    with its own ``keywords`` list to run a focused vector query against
    the knowledge index — instead of keyword-filtering the single
    problem-context retrieval shared in ``snippets``. The CLI builds
    this closure over the vector index + problem context."""


@dataclass
class AgentInputs:
    """Per-agent slice of :class:`AgentContext`.

    Each agent's :meth:`Agent.select_relevant` returns one of these,
    keeping only the snippets / parasitics / metrics that pertain to
    its area. The LLM prompt is built from this object.
    """

    problem_context: ProblemContext
    parasitics: list[ParasiticEstimate] = field(default_factory=list)
    sim_metrics: dict[str, float] = field(default_factory=dict)
    snippets: list[RedactedSnippet] = field(default_factory=list)
    baseline_recs: list[Recommendation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    """Free-form per-agent annotations passed to the prompt.

    For example, ``layout_risk_agent`` always emits a note about the
    layout being absent so the LLM doesn't fabricate layout knowledge.
    """
    topology: TopologyReport | None = None
    """M2.10: optional net-structure report forwarded from the context."""
    dut_supply_net: str = ""
    dut_return_net: str = ""
    signals: list[Signal] = field(default_factory=list)
    """M2.10.1: optional resolved user signal map forwarded from the context."""


def _snippet_tag_match(snippet: RedactedSnippet, keywords: list[str]) -> bool:
    """Return True if any keyword is a substring of summary or rule_id."""
    blob = " ".join([snippet.rule_id, snippet.source_id, snippet.summary, snippet.excerpt or ""]).lower()
    return any(kw.lower() in blob for kw in keywords)


def select_snippets_by_keywords(
    snippets: list[RedactedSnippet],
    keywords: list[str],
    *,
    fallback_top_k: int = 3,
) -> list[RedactedSnippet]:
    """Return the snippets whose summary mentions any keyword.

    When nothing matches, return the first ``fallback_top_k`` snippets
    so the agent has *some* context to work from. Order is preserved.
    """
    matched = [s for s in snippets if _snippet_tag_match(s, keywords)]
    if matched:
        return matched
    return snippets[:fallback_top_k]


def select_metrics_by_prefix(
    metrics: dict[str, float],
    prefixes: list[str],
) -> dict[str, float]:
    """Return metrics whose key starts with any of the prefixes.

    Returns the full dict when no prefix matches anything — agents
    should never lose all metrics due to a too-narrow filter.
    """
    out: dict[str, float] = {}
    for key, value in metrics.items():
        if any(key.startswith(p) for p in prefixes):
            out[key] = value
    return out or dict(metrics)


def build_minimal_deterministic_finding(
    *,
    agent_name: str,
    area_title: str,
    inputs: AgentInputs,
    focus: str,
    sweep_description: str | None = None,
    missing_when_no_layout: bool = True,
    missing_when_no_stackup: bool = False,
    confidence: float = 0.3,
) -> AgentFinding:
    """Build a generic deterministic fallback for non-primary agents.

    Used by the M2.9 agents that don't have a rich deterministic path:
    they emit a single info-level finding (the area was reached but no
    LLM was invoked), one engineering-estimate recommendation, the
    standard layout/stack-up missing-data notes, and an optional sweep
    request. Keeps every area non-empty in `--llm none` mode without
    fabricating area-specific claims.
    """
    ctx = inputs.problem_context
    findings = [
        Finding(
            title=f"{area_title} reached (deterministic fallback)",
            detail=(
                f"{focus} Without an LLM, this agent emits a placeholder so the "
                f"report has a {agent_name} subsection; run with --llm openai for "
                f"a topology-aware analysis."
            ),
            severity="info",
        )
    ]
    recs = [
        Recommendation(
            id="REC-001",
            area=agent_name,
            severity="info",
            confidence=confidence,
            problem=f"Deterministic fallback for the {area_title} agent.",
            evidence=[f"focus: {focus}"],
            proposed_change={
                "type": "investigate",
                "description": (
                    f"Re-run with --llm openai for {area_title.lower()} "
                    "recommendations grounded in the retrieved snippets."
                ),
            },
            simulation_required=False,
            user_action="Re-run with --llm openai.",
            limitations=["Deterministic fallback; no LLM was invoked."],
            sources=["engineering_estimate"],
        )
    ]
    sim_requests: list[SimulationRequest] = []
    if sweep_description:
        sim_requests.append(
            SimulationRequest(description=sweep_description, kind="sweep")
        )

    missing_data: list[str] = []
    limitations: list[str] = []
    if missing_when_no_layout and not ctx.has_layout:
        limitations.append(f"No layout — {area_title.lower()} claims are hypothesis-only.")
    if missing_when_no_stackup and not ctx.has_stackup:
        missing_data.append("PCB stack-up (layer count, dielectric, layer thicknesses)")

    return AgentFinding(
        agent=agent_name,
        area=area_title,
        confidence=confidence,
        findings=findings,
        risks=[],
        recommendations=recs,
        missing_data=missing_data,
        simulation_requests=sim_requests,
        sources=["engineering_estimate"],
        limitations=limitations,
        llm_generated=False,
    )


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_object(text: str) -> dict:
    """Parse the LLM response into a dict.

    Tolerates markdown code fences around the JSON. Raises ``ValueError``
    when the response is not a JSON object.
    """
    body = _FENCE_RE.sub("", text.strip()).strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM agent response was not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"LLM agent response was not a JSON object (got {type(data).__name__})."
        )
    return data


def _coerce_findings(items: Any) -> list[Finding]:
    if not isinstance(items, list):
        return []
    out: list[Finding] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        detail = str(item.get("detail") or "").strip()
        if not title and not detail:
            continue
        severity = str(item.get("severity") or "info")
        if severity not in {"info", "low", "medium", "high", "critical"}:
            severity = "info"
        out.append(Finding(title=title or "(untitled)", detail=detail, severity=severity))
    return out


def _coerce_risks(items: Any) -> list[Risk]:
    if not isinstance(items, list):
        return []
    out: list[Risk] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        detail = str(item.get("detail") or "").strip()
        if not title and not detail:
            continue
        likelihood = str(item.get("likelihood") or "medium")
        if likelihood not in {"low", "medium", "high"}:
            likelihood = "medium"
        out.append(Risk(title=title or "(untitled)", detail=detail, likelihood=likelihood))
    return out


def _coerce_recommendations(items: Any, *, default_area: str) -> list[Recommendation]:
    if not isinstance(items, list):
        return []
    out: list[Recommendation] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        rec_id = str(item.get("id") or f"REC-{idx + 1:03d}")
        if not re.match(r"^REC-\d{3,}$", rec_id):
            rec_id = f"REC-{idx + 1:03d}"
        severity = str(item.get("severity") or "info")
        if severity not in {"info", "low", "medium", "high", "critical"}:
            severity = "info"
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        proposed = item.get("proposed_change")
        if not isinstance(proposed, dict):
            proposed = {"type": "investigate", "description": ""}
        else:
            proposed = dict(proposed)
            proposed.setdefault("type", "investigate")
            proposed.setdefault("description", "")
        out.append(
            Recommendation(
                id=rec_id,
                area=str(item.get("area") or default_area),
                severity=severity,
                confidence=confidence,
                problem=str(item.get("problem") or ""),
                evidence=[str(x) for x in item.get("evidence") or []],
                proposed_change=proposed,
                simulation_required=bool(item.get("simulation_required", True)),
                user_action=str(item.get("user_action") or ""),
                limitations=[str(x) for x in item.get("limitations") or []],
                sources=[str(x) for x in item.get("sources") or []],
                llm_generated=True,
                citations=[str(x) for x in item.get("citations") or []],
            )
        )
    return out


def _coerce_injections(items: Any) -> list[ParasiticInjection]:
    if not isinstance(items, list):
        return []
    out: list[ParasiticInjection] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            out.append(_injection_from_dict(item))
        except (KeyError, ValueError):
            # Skip malformed entries silently — the rest of the plan
            # is still useful, and the report flags the partial parse.
            continue
    return out


def _coerce_simulation_requests(items: Any) -> list[SimulationRequest]:
    if not isinstance(items, list):
        return []
    out: list[SimulationRequest] = []
    for item in items:
        if isinstance(item, str):
            out.append(SimulationRequest(description=item))
            continue
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        params = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        out.append(
            SimulationRequest(
                description=description,
                kind=str(item.get("kind") or ""),
                parameters=dict(params or {}),
            )
        )
    return out


class Agent(ABC):
    """Base class for specialist agents.

    Subclasses set class attributes :attr:`name`, :attr:`area_title`,
    :attr:`prompt_filename` and implement :meth:`select_relevant` and
    :meth:`deterministic_finding`. The default
    :meth:`build_messages` and :meth:`parse_response` are usually fine
    — override them only when the per-agent prompt diverges from the
    standard contract.
    """

    name: str = "abstract"
    """Stable identifier: file name stem, area key in JSON findings,
    purpose tag in the privacy log."""

    area_title: str = "Abstract area"
    """Human-readable title used as the report subsection heading."""

    prompt_filename: str = ""
    """Filename under ``prompts/agents/`` for the per-agent template."""

    keywords: list[str] = []
    """Default keywords for snippet/metric selection. Subclasses may
    override :meth:`select_relevant` for finer-grained filtering."""

    metric_prefixes: list[str] = []
    """Default metric-key prefixes for the per-agent metric slice."""

    def __init__(self, *, prompt_path: Path | None = None) -> None:
        if prompt_path is not None:
            self.prompt_path = Path(prompt_path)
        else:
            if not self.prompt_filename:
                raise ValueError(
                    f"Agent {self.name!r} has no prompt_filename and no prompt_path."
                )
            self.prompt_path = PROMPTS_AGENTS_DIR / self.prompt_filename

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        ctx: AgentContext,
        assistant: LlmAssistant | None,
    ) -> AgentFinding:
        """Run the agent. Returns an :class:`AgentFinding`.

        When ``assistant`` is ``None`` or its ``name`` is
        ``"deterministic"``, the rule-based fallback runs. Otherwise the
        LLM path is used: build messages, call ``assistant.complete()``,
        parse the response.
        """
        inputs = self.select_relevant(ctx)
        if assistant is None or assistant.name == "deterministic":
            return self.deterministic_finding(inputs)
        messages = self.build_messages(inputs)
        try:
            response_text = assistant.complete(
                messages=messages,
                purpose=f"agent.{self.name}",
            )
        except Exception:
            # Budget exceeded, network error, etc. Propagate so the
            # orchestrator can decide whether to fail the run or skip
            # the agent.
            raise
        try:
            return self.parse_response(response_text, inputs)
        except ValueError:
            # Bad JSON / malformed response. Fall back to deterministic
            # so the run still produces something — but flag it.
            fallback = self.deterministic_finding(inputs)
            fallback.limitations.append(
                "LLM response was malformed; deterministic fallback was used."
            )
            return fallback

    # ------------------------------------------------------------------
    # Shared helpers for subclasses
    # ------------------------------------------------------------------

    def _select_snippets(self, ctx: AgentContext) -> list[RedactedSnippet]:
        """Pick this agent's knowledge snippets (M2.9.1).

        When the context carries a ``retrieve_fn`` (the CLI wires one
        over the vector index), issue a focused per-agent query seeded
        by this agent's :attr:`keywords` — so a ``decoupling`` agent
        gets decoupling-specific chunks, not the shared topology-level
        retrieval. Falls back to keyword-filtering the shared
        ``ctx.snippets`` pool when no ``retrieve_fn`` is set or the
        focused query returns nothing.
        """
        if ctx.retrieve_fn is not None:
            try:
                hits = ctx.retrieve_fn(self.keywords)
            except Exception:  # noqa: BLE001 — retrieval must never break an agent
                hits = []
            if hits:
                return hits
        return select_snippets_by_keywords(ctx.snippets, self.keywords)

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------

    @abstractmethod
    def select_relevant(self, ctx: AgentContext) -> AgentInputs:
        """Return the per-agent slice of the context."""

    @abstractmethod
    def deterministic_finding(self, inputs: AgentInputs) -> AgentFinding:
        """Rule-based fallback when no LLM is available."""

    def build_messages(self, inputs: AgentInputs) -> list[dict[str, Any]]:
        """Build the OpenAI ``messages`` array.

        Default behaviour: load the agent's prompt template as the system
        message, then format a structured user message with problem
        context, parasitics, simulation metrics, retrieved snippets,
        and per-agent notes. Override only when an agent needs a
        bespoke prompt shape.
        """
        template = self.prompt_path.read_text(encoding="utf-8")
        user_payload = self._format_user_payload(inputs)
        return [
            {"role": "system", "content": template},
            {"role": "user", "content": user_payload},
        ]

    def parse_response(self, response_text: str, inputs: AgentInputs) -> AgentFinding:
        """Parse the LLM JSON response into an :class:`AgentFinding`.

        Tolerant: missing fields default to empty arrays / 0.5
        confidence. Invalid JSON raises ``ValueError`` and the caller
        falls back to :meth:`deterministic_finding`.
        """
        data = parse_json_object(response_text)
        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        return AgentFinding(
            agent=self.name,
            area=self.area_title,
            confidence=confidence,
            findings=_coerce_findings(data.get("findings")),
            risks=_coerce_risks(data.get("risks")),
            recommendations=_coerce_recommendations(
                data.get("recommendations"), default_area=self.name
            ),
            missing_data=[str(x) for x in data.get("missing_data") or []],
            simulation_requests=_coerce_simulation_requests(
                data.get("simulation_requests")
            ),
            sources=[str(x) for x in data.get("sources") or []],
            limitations=[str(x) for x in data.get("limitations") or []],
            llm_generated=True,
            injections=_coerce_injections(data.get("injections")),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _format_user_payload(self, inputs: AgentInputs) -> str:
        ctx = inputs.problem_context
        ctx_lines = [
            f"project_id: {ctx.project_id}",
            f"analysis_scope: {ctx.analysis_scope}",
        ]
        if ctx.topology:
            ctx_lines.append(f"topology: {ctx.topology}")
        if ctx.input_voltage_v is not None:
            ctx_lines.append(f"input_voltage_v: {ctx.input_voltage_v}")
        if ctx.switching_frequency_hz is not None:
            ctx_lines.append(f"switching_frequency_hz: {ctx.switching_frequency_hz}")
        if ctx.load_current_a is not None:
            ctx_lines.append(f"load_current_a: {ctx.load_current_a}")
        if (
            ctx.frequency_range_min_hz is not None
            and ctx.frequency_range_max_hz is not None
        ):
            ctx_lines.append(
                f"frequency_range_hz: [{ctx.frequency_range_min_hz}, {ctx.frequency_range_max_hz}]"
            )
        if ctx.problem_hypothesis:
            ctx_lines.append(f"problem_hypothesis: {ctx.problem_hypothesis}")
        ctx_lines.append(f"has_layout: {ctx.has_layout}")
        ctx_lines.append(f"has_stackup: {ctx.has_stackup}")
        if ctx.missing_data:
            ctx_lines.append("missing_data: " + ", ".join(ctx.missing_data))

        if inputs.parasitics:
            par_lines = [
                f"- {p.id} | {p.structure}/{p.parasitic_type} | "
                f"min={p.min_value:.3g} typ={p.value:.3g} max={p.max_value:.3g} {p.unit}"
                for p in inputs.parasitics
            ]
            par_block = "\n".join(par_lines)
        else:
            par_block = "(none)"

        if inputs.sim_metrics:
            metric_lines = [f"- {k}: {v}" for k, v in sorted(inputs.sim_metrics.items())]
            metrics_block = "\n".join(metric_lines)
        else:
            metrics_block = "(none)"

        if inputs.snippets:
            snip_lines: list[str] = []
            for s in inputs.snippets:
                line = f"- [{s.rule_id} / {s.source_id}] {s.summary}"
                if s.excerpt:
                    line += f'\n    excerpt: "{s.excerpt}"'
                snip_lines.append(line)
            snippets_block = "\n".join(snip_lines)
        else:
            snippets_block = "(no snippets retrieved)"

        notes_block = "\n".join(f"- {n}" for n in inputs.notes) if inputs.notes else "(none)"

        topology_block = "(not supplied)"
        if inputs.topology is not None:
            t = inputs.topology
            topo_lines = [
                f"power_supply_candidates: {t.power_supply_candidates[:5]}",
                f"return_candidates: {t.return_candidates}",
                f"switching_node_candidates: {t.switching_node_candidates[:5]}",
                f"element_count_by_kind: {t.element_count_by_kind}",
            ]
            if inputs.dut_supply_net:
                topo_lines.append(f"dut_supply_net (from user_context): {inputs.dut_supply_net}")
            if inputs.dut_return_net:
                topo_lines.append(f"dut_return_net (from user_context): {inputs.dut_return_net}")
            topology_block = "\n".join(topo_lines)

        return (
            f"# Agent: {self.name} ({self.area_title})\n\n"
            f"# Problem context\n\n{chr(10).join(ctx_lines)}\n\n"
            f"# Parasitic estimates\n\n{par_block}\n\n"
            f"# Simulation metrics\n\n{metrics_block}\n\n"
            f"# Retrieved knowledge snippets (redacted)\n\n{snippets_block}\n\n"
            f"# Net topology (from parser, not simulated)\n\n{topology_block}\n\n"
            f"# Agent notes\n\n{notes_block}\n\n"
            f"Respond with ONE JSON object matching the schema in the system prompt. "
            f"Do not wrap the JSON in markdown fences."
        )
