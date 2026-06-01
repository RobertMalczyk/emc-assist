"""OpenAI provider for `LlmAssistant`.

Wraps the `openai` SDK. Honours the budget guard and writes a privacy
log entry before the API call returns. Live calls need an API key, which
:func:`resolve_api_key` reads from ``OPENAI_API_KEY`` or a key file
(``~/.emc-assistant/openai_key`` or the repo-root ``.openai_key``).

The provider is intentionally narrow — one method, one model, no
streaming, no tools. The agent layer in M2.9+ adds more sophistication.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from emc_assistant.llm.assistant import (
    LlmAssistant,
    LlmMode,
    ProblemContext,
    RecommendationDraft,
    RedactedSnippet,
)
from emc_assistant.llm.budget import (
    BudgetTracker,
    CostEstimate,
    assert_within_budget,
    estimate_cost_usd,
)
from emc_assistant.llm.privacy_log import write_privacy_log_entry
from emc_assistant.parasitics.model import ParasiticEstimate
from emc_assistant.recommendations.engine import Recommendation


DEFAULT_MODEL = "gpt-5-mini"

# Where the user can drop their OpenAI key as a plain-text file when they
# would rather not export OPENAI_API_KEY (the simple "for now" path until a
# proper UI Settings field / OS keyring lands). The file holds just the key.
_KEY_FILENAME = "openai_key"
_APP_DIR_NAME = ".emc-assistant"


def _read_key_file(path: Path) -> str | None:
    """Return the stripped key from ``path``, or ``None`` if absent/empty."""
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None
    return None


def candidate_key_files() -> list[Path]:
    """Key-file locations searched, in priority order.

    1. ``EMC_ASSISTANT_OPENAI_KEY_FILE`` (explicit override; used by tests),
    2. ``~/.emc-assistant/openai_key`` (the app config dir, next to
       ``settings.json``) — the recommended place,
    3. ``<repo-root>/.openai_key`` (dev convenience; already gitignored).
    """
    paths: list[Path] = []
    override = os.environ.get("EMC_ASSISTANT_OPENAI_KEY_FILE")
    if override:
        paths.append(Path(override))
    paths.append(Path.home() / _APP_DIR_NAME / _KEY_FILENAME)
    # parents: [0]=llm [1]=emc_assistant [2]=src [3]=repo root.
    paths.append(Path(__file__).resolve().parents[3] / ".openai_key")
    return paths


def resolve_api_key() -> str | None:
    """Resolve the OpenAI API key from the environment or a key file.

    ``OPENAI_API_KEY`` in the environment wins; otherwise the first
    existing file in :func:`candidate_key_files` is read. Returns ``None``
    when no key is configured anywhere.
    """
    env = os.environ.get("OPENAI_API_KEY")
    if env and env.strip():
        return env.strip()
    for path in candidate_key_files():
        key = _read_key_file(path)
        if key:
            return key
    return None


def _load_prompt_template(template_path: Path | None = None) -> str:
    """Return the prompt template body.

    Defaults to ``prompts/recommendations_v1.md`` in the repo.
    """
    if template_path is None:
        repo_root = Path(__file__).resolve().parents[3]
        template_path = repo_root / "prompts" / "recommendations_v1.md"
    return template_path.read_text(encoding="utf-8")


def _format_problem_context(ctx: ProblemContext) -> str:
    parts = [f"project_id: {ctx.project_id}", f"analysis_scope: {ctx.analysis_scope}"]
    if ctx.topology:
        parts.append(f"topology: {ctx.topology}")
    if ctx.input_voltage_v is not None:
        parts.append(f"input_voltage_v: {ctx.input_voltage_v}")
    if ctx.switching_frequency_hz is not None:
        parts.append(f"switching_frequency_hz: {ctx.switching_frequency_hz}")
    if ctx.load_current_a is not None:
        parts.append(f"load_current_a: {ctx.load_current_a}")
    if ctx.frequency_range_min_hz is not None and ctx.frequency_range_max_hz is not None:
        parts.append(
            f"frequency_range_hz: [{ctx.frequency_range_min_hz}, {ctx.frequency_range_max_hz}]"
        )
    if ctx.problem_hypothesis:
        parts.append(f"problem_hypothesis: {ctx.problem_hypothesis}")
    parts.append(f"has_layout: {ctx.has_layout}")
    parts.append(f"has_stackup: {ctx.has_stackup}")
    if ctx.missing_data:
        parts.append("missing_data: " + ", ".join(ctx.missing_data))
    return "\n".join(parts)


def _format_parasitics(parasitics: list[ParasiticEstimate]) -> str:
    if not parasitics:
        return "(none)"
    lines: list[str] = []
    for p in parasitics:
        lines.append(
            f"- {p.id} | {p.structure}/{p.parasitic_type} | "
            f"min={p.min_value:.3g} typ={p.value:.3g} max={p.max_value:.3g} {p.unit} | "
            f"sources={', '.join(p.source_ids) or '(none)'}"
        )
    return "\n".join(lines)


def _format_metrics(metrics: dict[str, float]) -> str:
    if not metrics:
        return "(none)"
    return "\n".join(f"- {k}: {v}" for k, v in sorted(metrics.items()))


def _format_snippets(snippets: list[RedactedSnippet]) -> str:
    if not snippets:
        return "(no snippets retrieved)"
    lines: list[str] = []
    for s in snippets:
        line = f"- [{s.rule_id} / {s.source_id}] {s.summary}"
        if s.excerpt:
            line += f"\n    excerpt: \"{s.excerpt}\""
        lines.append(line)
    return "\n".join(lines)


def _format_baseline(recs: list[Recommendation] | None) -> str:
    if not recs:
        return "(none)"
    payload = [
        {
            "id": r.id,
            "area": r.area,
            "severity": r.severity,
            "problem": r.problem,
            "evidence": r.evidence,
            "limitations": r.limitations,
            "sources": r.sources,
        }
        for r in recs
    ]
    return json.dumps(payload, indent=2, ensure_ascii=False)


def build_prompt(
    *,
    problem_context: ProblemContext,
    parasitics: list[ParasiticEstimate],
    sim_metrics: dict[str, float],
    snippets: list[RedactedSnippet],
    mode: LlmMode,
    baseline_recs: list[Recommendation] | None,
    template: str,
) -> list[dict[str, Any]]:
    """Return the OpenAI ``messages`` array for the recommendations call."""
    user_payload = (
        "# Problem context\n\n"
        f"{_format_problem_context(problem_context)}\n\n"
        "# Parasitic estimates\n\n"
        f"{_format_parasitics(parasitics)}\n\n"
        "# Simulation metrics\n\n"
        f"{_format_metrics(sim_metrics)}\n\n"
        "# Retrieved knowledge snippets (redacted)\n\n"
        f"{_format_snippets(snippets)}\n\n"
        f"# Mode: {mode}\n\n"
        f"# Baseline recommendations (mode=augment only)\n\n"
        f"{_format_baseline(baseline_recs) if mode == 'augment' else '(not used in replace mode)'}\n\n"
        "Respond with ONLY a JSON array of recommendation objects, following the schema "
        "described in the system prompt. Do not wrap in markdown fences."
    )
    return [
        {"role": "system", "content": template},
        {"role": "user", "content": user_payload},
    ]


def _parse_response(response_text: str) -> list[RecommendationDraft]:
    """Parse the LLM response into RecommendationDraft objects.

    Tolerates markdown code fences around the JSON; raises ValueError
    when the response is not a JSON array of recommendation objects.
    """
    text = response_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM did not return JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("LLM response was not a JSON array of recommendations.")
    drafts: list[RecommendationDraft] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Recommendation #{i} is not an object.")
        drafts.append(
            RecommendationDraft(
                id=str(item.get("id") or f"REC-{i + 1:03d}"),
                area=str(item.get("area", "general")),
                severity=str(item.get("severity", "info")),
                confidence=float(item.get("confidence", 0.5)),
                problem=str(item.get("problem", "")),
                evidence=[str(x) for x in item.get("evidence", [])],
                proposed_change=dict(item.get("proposed_change") or {"type": "investigate", "description": ""}),
                limitations=[str(x) for x in item.get("limitations", [])],
                sources=[str(x) for x in item.get("sources", [])],
                citations=[str(x) for x in item.get("citations", [])],
                llm_generated=True,
                simulation_required=bool(item.get("simulation_required", True)),
                user_action=str(item.get("user_action", "")),
            )
        )
    return drafts


class OpenAiAssistant(LlmAssistant):
    """OpenAI-backed `LlmAssistant`.

    Constructor parameters:

    - ``model``: defaults to :data:`DEFAULT_MODEL` (``gpt-5-mini``).
    - ``budget_usd``: hard cap; the call aborts with ``BudgetExceeded``
      before any network I/O if the estimated cost is higher.
    - ``privacy_log_path``: where to append the audit log entry.
    - ``client``: optional pre-built ``openai.OpenAI`` instance. When
      ``None``, the provider constructs one from the key resolved by
      :func:`resolve_api_key` (env var or key file).
    - ``template_path``: optional override for the prompt template file.

    The provider does not own the run-id; the caller passes
    ``privacy_log_path`` already shaped as
    ``results/llm/<run-id>.jsonl``.
    """

    name = "openai"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        budget_usd: float = 1.0,
        privacy_log_path: Path | None = None,
        client: Any | None = None,
        template_path: Path | None = None,
        budget_tracker: BudgetTracker | None = None,
        request_timeout_s: float = 120.0,
    ) -> None:
        self.model = model
        self.budget_usd = float(budget_usd)
        self.privacy_log_path = Path(privacy_log_path) if privacy_log_path else None
        self._client = client
        self._template_path = template_path
        self.request_timeout_s = float(request_timeout_s)
        """Per-request network timeout (seconds). The openai SDK defaults to
        600 s, so a stalled connection hangs the whole run — and, from the UI,
        freezes the Run screen since the pipeline never returns. A bounded
        timeout turns a stall into a normal error the agent / report layer
        already fails-safe to the deterministic path on."""
        self._last_estimate: CostEstimate | None = None
        self._last_response_text: str | None = None
        self.budget_tracker = budget_tracker
        """Run-level cumulative tracker. When set, each ``complete()`` call
        also checks the cumulative cap. Per-call cap (``budget_usd``)
        continues to apply independently."""

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "openai package not installed; pip install openai"
            ) from exc
        api_key = resolve_api_key()
        if not api_key:
            raise RuntimeError(
                "No OpenAI API key found. Set OPENAI_API_KEY, or save the key "
                "in ~/.emc-assistant/openai_key (or .openai_key in the repo "
                "root), or pass --llm none."
            )
        # Bounded per-attempt timeout so a network stall fails instead of
        # hanging the run for the SDK's 600 s default — but generous enough for
        # a slow reasoning-model call, and keeping the SDK's default 2 retries
        # so a transient blip still recovers. The report/agent layers fall back
        # to deterministic if it ultimately errors.
        self._client = OpenAI(
            api_key=api_key,
            timeout=self.request_timeout_s,
            max_retries=2,
        )
        return self._client

    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        purpose: str,
        expected_output_tokens: int = 1500,
    ) -> str:
        """Send messages to OpenAI, return the response text.

        Enforces per-call budget AND cumulative run-level budget (when a
        ``budget_tracker`` was supplied). Records every call in the
        privacy log when ``privacy_log_path`` is set.
        """
        prompt_text = "\n\n".join(m["content"] for m in messages)
        estimate = estimate_cost_usd(
            prompt_text,
            model=self.model,
            expected_output_tokens=expected_output_tokens,
        )
        self._last_estimate = estimate
        assert_within_budget(estimate, budget_usd=self.budget_usd)
        if self.budget_tracker is not None:
            self.budget_tracker.assert_can_afford(estimate)

        client = self._get_client()
        completion = client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        choice = completion.choices[0]
        response_text = choice.message.content or ""
        self._last_response_text = response_text
        usage = getattr(completion, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        completion_tokens = getattr(usage, "completion_tokens", None) if usage else None

        if self.budget_tracker is not None:
            self.budget_tracker.record(estimate.total_usd)

        if self.privacy_log_path is not None:
            write_privacy_log_entry(
                log_path=self.privacy_log_path,
                model=self.model,
                prompt_messages=messages,
                response_text=response_text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_estimate_usd=estimate.total_usd,
                purpose=purpose,
            )

        return response_text

    def explain_recommendations(
        self,
        *,
        problem_context: ProblemContext,
        parasitics: list[ParasiticEstimate],
        sim_metrics: dict[str, float],
        snippets: list[RedactedSnippet],
        mode: LlmMode = "replace",
        baseline_recs: list[Recommendation] | None = None,
    ) -> list[RecommendationDraft]:
        template = _load_prompt_template(self._template_path)
        messages = build_prompt(
            problem_context=problem_context,
            parasitics=parasitics,
            sim_metrics=sim_metrics,
            snippets=snippets,
            mode=mode,
            baseline_recs=baseline_recs,
            template=template,
        )
        response_text = self.complete(
            messages=messages,
            purpose=f"recommendations.{mode}",
        )
        return _parse_response(response_text)
