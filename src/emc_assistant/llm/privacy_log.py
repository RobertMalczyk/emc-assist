"""Privacy log writer — records every outbound LLM payload locally.

Each `--llm openai` run appends one JSON object per LLM call to
`results/llm/<run-id>.jsonl`. Tests assert the file exists and contains
exactly the prompts that were sent.

The log is the user's audit trail of what left the local machine — a
requirement from `docs/09_security_privacy_licensing.md` ("a report of
what data was sent to the LLM").
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_privacy_log_entry(
    *,
    log_path: Path,
    model: str,
    prompt_messages: list[dict[str, Any]],
    response_text: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cost_estimate_usd: float,
    purpose: str,
) -> Path:
    """Append a single JSON object to the privacy log.

    The log uses JSONL so multiple calls in the same run land cleanly.
    Creates parent directories on demand.
    """
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": _now_iso(),
        "model": model,
        "purpose": purpose,
        "prompt_messages": prompt_messages,
        "response_text": response_text,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "estimated_cost_usd": float(cost_estimate_usd),
    }
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return log_path
