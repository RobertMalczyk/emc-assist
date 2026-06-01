"""pytest configuration — add src/ to sys.path and gate live-LLM tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _isolate_app_settings(tmp_path_factory, monkeypatch):
    """Point ``EMC_ASSISTANT_SETTINGS`` at a fresh temp file for every test.

    Two reasons: (1) tests must never read or write the developer's real
    ``~/.emc-assistant/settings.json``; (2) the bridge's ``_run_options``
    overlays the saved cloud-LLM setting onto every run call, so without
    isolation a machine with ``cloud_llm_enabled`` + a key turns the
    "dry-run, no-LLM" e2e tests into slow, paid, non-deterministic OpenAI
    runs. An empty settings file → cloud LLM OFF → deterministic & free.

    Tests that need a specific settings file just call ``monkeypatch.setenv``
    again (the later set wins). Key resolution is unaffected — it reads the
    env var / key file, not this settings path, so live_llm tests still work.
    """
    settings = tmp_path_factory.mktemp("app_settings") / "settings.json"
    monkeypatch.setenv("EMC_ASSISTANT_SETTINGS", str(settings))


def pytest_collection_modifyitems(config, items):
    """Auto-skip ``@pytest.mark.live_llm`` tests when they can't / shouldn't run.

    Live tests make a real (paid) OpenAI call, so we run them only when a key
    is resolvable (env var or key file — see ``resolve_api_key``) and the
    explicit off-switch ``EMC_ASSISTANT_SKIP_LIVE_LLM`` is not set. This keeps
    keyless CI green while letting a developer with a key exercise the real
    LLM features locally on every run.
    """
    import pytest  # local import: pytest is always available under a run

    live_items = [it for it in items if "live_llm" in it.keywords]
    if not live_items:
        return

    if os.environ.get("EMC_ASSISTANT_SKIP_LIVE_LLM"):
        reason = "EMC_ASSISTANT_SKIP_LIVE_LLM is set"
    else:
        from emc_assistant.llm.openai_provider import resolve_api_key

        reason = (
            None if resolve_api_key()
            else "no OpenAI API key resolvable (set OPENAI_API_KEY or a key file)"
        )
    if reason:
        skip = pytest.mark.skip(reason=reason)
        for it in live_items:
            it.add_marker(skip)
