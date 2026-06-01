"""LLM-assisted recommendation layer (M2.7+).

The runtime pipeline is deterministic by default (`DeterministicAssistant`).
Opting into `--llm openai` swaps in `OpenAiAssistant`, which sends a
strictly redacted prompt to OpenAI and writes every outbound payload
to a privacy log under `results/llm/<run-id>.jsonl`.

The LLM is priority 5 in the parasitic-suggestion chain
(`docs/08_decision_log.md` 2026-05-14 entry). It must never invent
precise values; every claim cites a `Rule_ID` or carries an
`engineering_estimate` tag.
"""

from emc_assistant.llm.assistant import (
    LlmAssistant,
    LlmMode,
    ProblemContext,
    RecommendationDraft,
    RedactedSnippet,
)
from emc_assistant.llm.budget import BudgetExceeded, estimate_cost_usd
from emc_assistant.llm.deterministic import DeterministicAssistant
from emc_assistant.llm.openai_provider import OpenAiAssistant
from emc_assistant.llm.privacy_log import write_privacy_log_entry
from emc_assistant.llm.stub import StubAssistant

__all__ = [
    "LlmAssistant",
    "LlmMode",
    "ProblemContext",
    "RecommendationDraft",
    "RedactedSnippet",
    "BudgetExceeded",
    "estimate_cost_usd",
    "DeterministicAssistant",
    "OpenAiAssistant",
    "StubAssistant",
    "write_privacy_log_entry",
]
