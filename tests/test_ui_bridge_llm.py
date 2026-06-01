"""Cloud-LLM wiring in the bridge: key-gated status + run-option overlay.

The cloud LLM is usable only when the user opted in (persisted
``cloud_llm_enabled``) AND a key resolves — "proper key → on, otherwise
off". These tests isolate both: settings via ``EMC_ASSISTANT_SETTINGS``
and key presence by monkeypatching ``resolve_api_key``.
"""

from __future__ import annotations

import pytest

from emc_assistant.llm import openai_provider
from emc_assistant.service import settings as settings_service
from emc_assistant.ui.bridge import Api, _run_options


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("EMC_ASSISTANT_SETTINGS", str(tmp_path / "settings.json"))


def _set_key(monkeypatch, present: bool):
    monkeypatch.setattr(
        openai_provider, "resolve_api_key", lambda: ("sk-test" if present else None)
    )


def test_llm_status_off_by_default(isolated_settings, monkeypatch):
    _set_key(monkeypatch, True)
    data = Api().llm_status()["data"]
    assert data["key_present"] is True
    assert data["enabled"] is False        # not opted in
    assert data["effective"] is False


def test_llm_status_effective_requires_key_and_enabled(isolated_settings, monkeypatch):
    settings_service.save_settings({"cloud_llm_enabled": True})
    _set_key(monkeypatch, False)
    data = Api().llm_status()["data"]
    assert data["enabled"] is True and data["key_present"] is False
    assert data["effective"] is False      # enabled but no key → still off
    _set_key(monkeypatch, True)
    assert Api().llm_status()["data"]["effective"] is True


def test_run_options_overlays_openai_when_active(isolated_settings, monkeypatch):
    settings_service.save_settings({"cloud_llm_enabled": True, "llm_budget_usd": 2.5})
    _set_key(monkeypatch, True)
    opts = _run_options({"accept_parasitics": True})
    assert opts.llm == "openai"
    assert opts.llm_budget_usd == 2.5
    assert opts.accept_parasitics is True


def test_run_options_stays_none_without_key(isolated_settings, monkeypatch):
    settings_service.save_settings({"cloud_llm_enabled": True})
    _set_key(monkeypatch, False)
    assert _run_options({}).llm == "none"


def test_run_options_stays_none_when_disabled(isolated_settings, monkeypatch):
    _set_key(monkeypatch, True)            # key present but not opted in
    assert _run_options({}).llm == "none"


def test_run_options_respects_explicit_caller_choice(isolated_settings, monkeypatch):
    # An explicit non-none caller llm is preserved as-is — even with cloud
    # off — and is never double-overlaid. (Explicit "none" can't be told
    # apart from the default, so the overlay still applies there.)
    _set_key(monkeypatch, True)
    assert _run_options({"llm": "openai"}).llm == "openai"


def test_suggest_negligible_gate_errors_when_off(isolated_settings, monkeypatch, tmp_path):
    # Cloud off → the standalone endpoint errors before touching a project.
    _set_key(monkeypatch, False)
    res = Api().suggest_negligible(str(tmp_path / "nope"))
    assert res["ok"] is False
    assert "Cloud LLM is off" in res["error"]["message"]
