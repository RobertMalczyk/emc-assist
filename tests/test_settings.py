"""Tests for ``emc_assistant.service.settings`` — the app-level settings
store — and the matching ``Api`` bridge methods.

The settings file lives at ``~/.emc-assistant/settings.json`` by default,
but the ``EMC_ASSISTANT_SETTINGS`` env var redirects it. Every test in
this file uses that override (via an autouse fixture) so the user's real
settings file is never touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emc_assistant.service import settings as settings_service
from emc_assistant.service.settings import (
    AppSettings,
    load_settings,
    load_settings_raw,
    save_settings,
    settings_path,
)
from emc_assistant.ui.bridge import Api


@pytest.fixture(autouse=True)
def _isolated_settings_file(tmp_path, monkeypatch):
    """Point ``EMC_ASSISTANT_SETTINGS`` at a tmp file so the real
    settings file is never touched."""
    target = tmp_path / "settings.json"
    monkeypatch.setenv("EMC_ASSISTANT_SETTINGS", str(target))
    return target


# ---- settings_path / load_settings_raw -------------------------------------


def test_settings_path_honours_env_override(_isolated_settings_file):
    assert settings_path() == _isolated_settings_file


def test_load_raw_returns_empty_dict_when_file_missing():
    assert load_settings_raw() == {}


def test_load_raw_returns_empty_dict_on_malformed_json(_isolated_settings_file):
    _isolated_settings_file.write_text("not-json{", encoding="utf-8")
    assert load_settings_raw() == {}


def test_load_raw_returns_empty_dict_when_file_is_not_a_dict(
    _isolated_settings_file,
):
    _isolated_settings_file.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_settings_raw() == {}


def test_load_raw_returns_stored_dict(_isolated_settings_file):
    _isolated_settings_file.parent.mkdir(parents=True, exist_ok=True)
    _isolated_settings_file.write_text(
        json.dumps({"ltspice_path": "C:/x.exe", "theme": "light"}),
        encoding="utf-8",
    )
    assert load_settings_raw() == {"ltspice_path": "C:/x.exe", "theme": "light"}


# ---- save_settings (merge semantics) ---------------------------------------


def test_save_writes_and_creates_parent_directory():
    result = save_settings({"ltspice_path": "C:/LTspice.exe"})
    assert result == {"ltspice_path": "C:/LTspice.exe"}
    assert settings_path().is_file()


def test_save_merges_with_existing_keys_preserving_ui_state():
    """A second save must NOT erase keys it didn't touch — UI-only keys
    (theme / density / accent…) round-trip alongside backend fields."""
    save_settings({"theme": "dark", "density": "compact", "accentHue": 268})
    merged = save_settings({"ltspice_path": "D:/LTspice.exe"})
    assert merged == {
        "theme": "dark",
        "density": "compact",
        "accentHue": 268,
        "ltspice_path": "D:/LTspice.exe",
    }


def test_save_overwrites_a_field_passed_in_updates():
    save_settings({"cloud_llm_enabled": False})
    merged = save_settings({"cloud_llm_enabled": True})
    assert merged["cloud_llm_enabled"] is True


def test_save_tolerates_non_dict_updates():
    """A bad ``updates`` payload (None / list) is treated as ``{}``."""
    save_settings({"theme": "dark"})
    merged = save_settings(None)  # type: ignore[arg-type]
    assert merged == {"theme": "dark"}


# ---- AppSettings typed view ------------------------------------------------


def test_app_settings_defaults_are_local_first():
    s = AppSettings()
    assert s.ltspice_path == ""
    assert s.cloud_llm_enabled is False  # local-first
    assert s.telemetry_enabled is False  # off by default
    assert s.llm_budget_usd == 1.0


def test_app_settings_from_dict_ignores_unknown_keys():
    """UI-only keys must not crash the typed view — they're dropped."""
    s = AppSettings.from_dict({
        "ltspice_path": "C:/x.exe",
        "theme": "light",           # UI-only
        "accentHue": 268,           # UI-only
        "totally_made_up": "ok",    # forward-compat slop
    })
    assert s.ltspice_path == "C:/x.exe"
    assert s.to_dict()["ltspice_path"] == "C:/x.exe"


def test_app_settings_from_dict_coerces_loose_types():
    s = AppSettings.from_dict({
        "cloud_llm_enabled": 1,       # truthy non-bool
        "llm_budget_usd": "2.5",      # string number
        "ltspice_path": None,
    })
    assert s.cloud_llm_enabled is True
    assert s.llm_budget_usd == 2.5
    assert s.ltspice_path == ""


def test_load_settings_returns_typed_view():
    save_settings({"ltspice_path": "C:/x.exe", "cloud_llm_enabled": True})
    s = load_settings()
    assert isinstance(s, AppSettings)
    assert s.ltspice_path == "C:/x.exe"
    assert s.cloud_llm_enabled is True


# ---- bridge methods --------------------------------------------------------


def test_bridge_load_settings_returns_full_dict():
    save_settings({"ltspice_path": "C:/x.exe", "theme": "dark"})
    res = Api().load_settings()
    assert res["ok"] is True
    assert res["data"] == {"ltspice_path": "C:/x.exe", "theme": "dark"}


def test_bridge_load_settings_returns_empty_when_no_file():
    res = Api().load_settings()
    assert res["ok"] is True
    assert res["data"] == {}


def test_bridge_save_settings_merges_and_returns_full_dict():
    Api().save_settings({"theme": "dark"})
    res = Api().save_settings({"ltspice_path": "D:/LTspice.exe"})
    assert res["ok"] is True
    assert res["data"] == {"theme": "dark", "ltspice_path": "D:/LTspice.exe"}


def test_bridge_save_settings_tolerates_none():
    Api().save_settings({"theme": "dark"})
    res = Api().save_settings(None)
    assert res["ok"] is True
    assert res["data"] == {"theme": "dark"}


def test_bridge_detect_ltspice_uses_configured_path(tmp_path, monkeypatch):
    """When the user has saved an ``ltspice_path`` setting,
    ``detect_ltspice`` resolves to it."""
    fake_exe = tmp_path / "LTspice.exe"
    fake_exe.write_text("", encoding="utf-8")
    Api().save_settings({"ltspice_path": str(fake_exe)})
    # Make sure ambient discovery doesn't find a real LTspice and mask
    # the configured-path branch we're testing.
    monkeypatch.delenv("LTSPICE_PATH", raising=False)
    res = Api().detect_ltspice()
    assert res["ok"] is True
    assert res["data"]["path"] == str(fake_exe)


def test_bridge_detect_ltspice_returns_null_when_nothing_found(monkeypatch):
    """With no configured path, no env var, and discovery neutralised,
    the bridge returns ``{"path": null}``."""
    from emc_assistant.ltspice import adapter

    monkeypatch.delenv("LTSPICE_PATH", raising=False)
    monkeypatch.setattr(adapter, "COMMON_WINDOWS_PATHS", ())
    monkeypatch.setattr(adapter.shutil, "which", lambda name: None)
    res = Api().detect_ltspice()
    assert res["ok"] is True
    assert res["data"]["path"] is None


def test_bridge_pick_file_returns_error_envelope_outside_pywebview():
    """Without a live pywebview window, ``pick_file`` returns a
    structured error — never raises."""
    res = Api().pick_file()
    assert res["ok"] is False
    assert "message" in res["error"]
