"""App-level settings store — global user preferences.

Distinct from per-project ``project.yaml``: this stores state that
travels with the user, not the project (the LTspice install path, the
cloud-LLM toggle, telemetry consent, plus any UI-side preferences the
front-end wants to persist). Lives at ``~/.emc-assistant/settings.json``
so it is shared across every project on the machine.

**Storage shape is a plain dict.** The backend "knows about" a handful
of fields (the :class:`AppSettings` dataclass) but the on-disk file is
arbitrary key / value JSON — any UI-only key (theme, density, accent
hue, etc.) round-trips untouched. This keeps the architecture open to
front-end changes: a new UI version can persist new keys without a
backend migration.

The UI bridge exposes :func:`load_settings_raw` and
:func:`save_settings` (the merging variant). Backend code that wants
typed access calls :func:`load_settings` -> :class:`AppSettings`.

Defaults are conservative — cloud-LLM off, telemetry off, no LTspice
path. The UI may always assume :func:`load_settings_raw` returns a
dict (corrupt or missing file -> ``{}``, never an exception).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SETTINGS_FILENAME = "settings.json"
_APP_DIR_NAME = ".emc-assistant"

# Backend-load-bearing field names (the keys :class:`AppSettings` knows).
# Anything else in the on-disk dict is UI-only state — preserved by the
# merge in :func:`save_settings`, ignored by the backend.
BACKEND_FIELDS: frozenset[str] = frozenset({
    "ltspice_path",
    "cloud_llm_enabled",
    "llm_model",
    "llm_budget_usd",
    "telemetry_enabled",
})


def settings_path() -> Path:
    """The cross-platform location of the settings file.

    The ``EMC_ASSISTANT_SETTINGS`` env var overrides — used by tests so
    they never touch the user's real settings file."""
    override = os.environ.get("EMC_ASSISTANT_SETTINGS")
    if override:
        return Path(override)
    return Path.home() / _APP_DIR_NAME / SETTINGS_FILENAME


@dataclass
class AppSettings:
    """Typed view of the backend-load-bearing subset of settings.

    Not the canonical storage form — that's the raw dict. Use this when
    backend code needs typed access; build it via :meth:`from_dict`."""

    ltspice_path: str = ""
    """Absolute path to the LTspice executable; empty -> use discovery."""

    cloud_llm_enabled: bool = False
    """Master switch for the optional cloud LLM. Off by default (local-first)."""

    llm_model: str = ""
    """Override for the OpenAI model. Empty -> provider's default."""

    llm_budget_usd: float = 1.0
    """Per-run cost cap for the LLM provider."""

    telemetry_enabled: bool = False
    """Whether the user has opted into telemetry. Off by default."""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "AppSettings":
        """Build from a (raw) settings dict; ignore unknown / UI-only keys."""
        if not isinstance(data, dict) or not data:
            return cls()
        clean: dict[str, Any] = {}
        for key in BACKEND_FIELDS:
            if key not in data:
                continue
            value = data[key]
            # Light-touch coercion — JSON may bring booleans as strings.
            if key == "cloud_llm_enabled" or key == "telemetry_enabled":
                clean[key] = bool(value)
            elif key == "llm_budget_usd":
                try:
                    clean[key] = float(value)
                except (TypeError, ValueError):
                    pass
            else:
                clean[key] = str(value) if value is not None else ""
        return cls(**clean)


# ---- raw-dict storage (the canonical form) ---------------------------------


def load_settings_raw(path: Path | None = None) -> dict:
    """Return the full settings dict (UI keys included), ``{}`` on
    missing / corrupt. Never raises — the UI must always have something
    to render."""
    p = path or settings_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(updates: dict, path: Path | None = None) -> dict:
    """Merge ``updates`` into the on-disk settings and write back; return
    the resulting raw dict. Unknown / UI-only keys present on disk are
    preserved unless explicitly overwritten by ``updates``.

    Creates the parent directory if missing."""
    if not isinstance(updates, dict):
        updates = {}
    p = path or settings_path()
    current = load_settings_raw(p)
    current.update(updates)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return current


# ---- typed view for backend code ------------------------------------------


def load_settings(path: Path | None = None) -> AppSettings:
    """Typed view of the backend-relevant fields. See
    :func:`load_settings_raw` if you need the UI-only keys too."""
    return AppSettings.from_dict(load_settings_raw(path))
