"""Tests for the OpenAI provider: prompt construction, response parsing, mocked client."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emc_assistant.llm.assistant import (
    ProblemContext,
    RedactedSnippet,
)
from emc_assistant.llm.openai_provider import (
    DEFAULT_MODEL,
    OpenAiAssistant,
    _parse_response,
    build_prompt,
)
from emc_assistant.parasitics.calculators import (
    trace_inductance_no_plane,
    trace_resistance,
)
from emc_assistant.recommendations.engine import Recommendation


def _ctx() -> ProblemContext:
    return ProblemContext(
        project_id="case_001",
        analysis_scope="conducted_emi_dc_dc",
        topology="buck_converter",
        input_voltage_v=24.0,
        switching_frequency_hz=400_000.0,
        load_current_a=2.0,
        problem_hypothesis="conducted EMI near switching harmonics",
        has_layout=False,
        has_stackup=True,
        missing_data=["layout"],
    )


def _parasitics():
    return [
        trace_resistance(length_mm=20.0, width_mm=1.0),
        trace_inductance_no_plane(length_mm=20.0, width_mm=1.0),
    ]


_RESPONSES_JSON = """[
  {
    "id": "REC-001",
    "area": "input_filter",
    "severity": "medium",
    "confidence": 0.6,
    "problem": "Potential LC peaking.",
    "evidence": ["Rule R-005 — high-Q risk"],
    "proposed_change": {
      "type": "add_damping",
      "description": "Add RC damping",
      "values": {"R": "0.5-3.3 ohm", "C": "100 nF - 1 uF"}
    },
    "simulation_required": true,
    "limitations": ["No layout."],
    "sources": ["R-005"],
    "citations": ["SRC-021"]
  }
]"""


class _FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = type("M", (), {"content": content})()


class _FakeCompletion:
    def __init__(self, content: str, prompt_tokens: int = 100, completion_tokens: int = 50) -> None:
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage(prompt_tokens, completion_tokens)


class _FakeChat:
    def __init__(self, parent: "_FakeOpenAi") -> None:
        self._parent = parent

    @property
    def completions(self):
        return self

    def create(self, *, model: str, messages: list[dict]) -> _FakeCompletion:
        self._parent.last_model = model
        self._parent.last_messages = messages
        return _FakeCompletion(self._parent.response_text)


class _FakeOpenAi:
    """Minimal fake of the openai client surface used by OpenAiAssistant."""

    def __init__(self, response_text: str = _RESPONSES_JSON) -> None:
        self.response_text = response_text
        self.last_model: str | None = None
        self.last_messages: list[dict] | None = None
        self.chat = _FakeChat(self)


def test_default_model_is_gpt5_mini():
    assert DEFAULT_MODEL == "gpt-5-mini"


def test_build_prompt_includes_context_parasitics_snippets():
    snippets = [RedactedSnippet(rule_id="R-003", source_id="SRC-001", summary="LISN setup")]
    messages = build_prompt(
        problem_context=_ctx(),
        parasitics=_parasitics(),
        sim_metrics={"v_meas_peak": 3.41},
        snippets=snippets,
        mode="replace",
        baseline_recs=None,
        template="SYSTEM: be helpful",
    )
    assert messages[0]["role"] == "system"
    assert "SYSTEM:" in messages[0]["content"]
    user = messages[1]["content"]
    assert "case_001" in user
    assert "conducted_emi_dc_dc" in user
    assert "v_meas_peak" in user
    assert "R-003" in user
    assert "SRC-001" in user
    assert "Mode: replace" in user


def test_build_prompt_excludes_baseline_block_in_replace_mode():
    messages = build_prompt(
        problem_context=_ctx(),
        parasitics=_parasitics(),
        sim_metrics={},
        snippets=[],
        mode="replace",
        baseline_recs=None,
        template="SYS",
    )
    assert "(not used in replace mode)" in messages[1]["content"]


def test_build_prompt_includes_baseline_in_augment_mode():
    baseline = [
        Recommendation(
            id="REC-001",
            area="testbench",
            severity="info",
            confidence=0.6,
            problem="Need LISN",
            evidence=["existing baseline"],
            proposed_change={"type": "add_subcircuit", "description": "add LISN"},
            sources=["R-003"],
        )
    ]
    messages = build_prompt(
        problem_context=_ctx(),
        parasitics=_parasitics(),
        sim_metrics={},
        snippets=[],
        mode="augment",
        baseline_recs=baseline,
        template="SYS",
    )
    user = messages[1]["content"]
    assert "Mode: augment" in user
    assert "REC-001" in user
    assert "Need LISN" in user


def test_parse_response_plain_json_array():
    drafts = _parse_response(_RESPONSES_JSON)
    assert len(drafts) == 1
    d = drafts[0]
    assert d.id == "REC-001"
    assert d.llm_generated is True
    assert "R-005" in d.sources
    assert "SRC-021" in d.citations
    assert d.proposed_change["type"] == "add_damping"


def test_parse_response_tolerates_markdown_fences():
    wrapped = "```json\n" + _RESPONSES_JSON + "\n```"
    drafts = _parse_response(wrapped)
    assert len(drafts) == 1


def test_parse_response_rejects_non_array():
    with pytest.raises(ValueError):
        _parse_response('{"id": "REC-001"}')


def test_parse_response_rejects_invalid_json():
    with pytest.raises(ValueError):
        _parse_response("not json at all")


def test_openai_assistant_end_to_end_with_fake_client(tmp_path: Path):
    """End-to-end: assistant builds prompt, calls fake client, parses response, writes privacy log."""
    fake = _FakeOpenAi()
    log_path = tmp_path / "llm" / "run-xxx.jsonl"
    template_path = tmp_path / "tmpl.md"
    template_path.write_text("You are a test assistant.", encoding="utf-8")

    asst = OpenAiAssistant(
        model="gpt-5-mini",
        budget_usd=1.0,
        privacy_log_path=log_path,
        client=fake,
        template_path=template_path,
    )
    drafts = asst.explain_recommendations(
        problem_context=_ctx(),
        parasitics=_parasitics(),
        sim_metrics={"v_meas_peak": 3.41},
        snippets=[RedactedSnippet(rule_id="R-005", source_id="SRC-021", summary="damping")],
        mode="replace",
    )
    assert len(drafts) == 1
    assert drafts[0].llm_generated is True
    # Privacy log was written.
    assert log_path.is_file()
    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["model"] == "gpt-5-mini"
    assert entry["purpose"] == "recommendations.replace"
    assert entry["prompt_tokens"] == 100
    assert entry["completion_tokens"] == 50


def test_openai_assistant_budget_guard_aborts_before_call(tmp_path: Path):
    """`budget_usd` smaller than the estimated cost must abort with no client call."""
    from emc_assistant.llm.budget import BudgetExceeded

    fake = _FakeOpenAi()
    asst = OpenAiAssistant(
        model="gpt-5-mini",
        budget_usd=1e-12,  # impossibly small
        privacy_log_path=tmp_path / "x.jsonl",
        client=fake,
        template_path=None,
    )
    with pytest.raises(BudgetExceeded):
        asst.explain_recommendations(
            problem_context=_ctx(),
            parasitics=_parasitics(),
            sim_metrics={},
            snippets=[],
            mode="replace",
        )
    # The client should never have been called.
    assert fake.last_model is None


def test_openai_assistant_redacted_snippets_never_carry_raw_body(tmp_path: Path):
    """The full prompt sent to OpenAI must not contain a long verbatim body
    (the redaction layer is responsible upstream; this test guards the
    assistant against accidentally pulling in raw bodies via the wrong field)."""
    fake = _FakeOpenAi()
    snippet = RedactedSnippet(
        rule_id="R-003",
        source_id="SRC-001",
        summary="Our own summary",
        excerpt=None,  # restrictive source — no excerpt
    )
    asst = OpenAiAssistant(
        model="gpt-5-mini",
        budget_usd=1.0,
        privacy_log_path=tmp_path / "run.jsonl",
        client=fake,
        template_path=None,
    )
    asst.explain_recommendations(
        problem_context=_ctx(),
        parasitics=_parasitics(),
        sim_metrics={},
        snippets=[snippet],
        mode="replace",
    )
    full_prompt = json.dumps(fake.last_messages)
    # Source_ID + summary are present; nothing else from a hypothetical body.
    assert "SRC-001" in full_prompt
    assert "Our own summary" in full_prompt
    # The PROPRIETARY string from the redaction unit test must not be here.
    assert "PROPRIETARY VENDOR TEXT" not in full_prompt


def test_request_timeout_defaults_to_bounded_value():
    # The openai SDK default is 600 s — a network stall would hang the whole
    # run (and freeze the UI). The provider bounds it (generous enough for a
    # slow reasoning-model call).
    assert OpenAiAssistant().request_timeout_s == 120.0


def test_get_client_passes_bounded_timeout_and_retries(monkeypatch):
    """A constructed (non-injected) client gets a bounded per-attempt timeout
    (so a stall fails instead of hanging 600 s) while keeping the SDK's default
    retries so a transient blip still recovers."""
    import sys
    import types

    captured: dict = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = _FakeClient
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setattr(
        "emc_assistant.llm.openai_provider.resolve_api_key", lambda: "sk-test"
    )

    asst = OpenAiAssistant(request_timeout_s=12.5)  # no client → constructs one
    client = asst._get_client()
    assert isinstance(client, _FakeClient)
    assert captured["timeout"] == 12.5
    assert captured["max_retries"] == 2
    assert captured["api_key"] == "sk-test"
