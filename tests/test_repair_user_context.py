"""Tests for scripts/repair_user_context.py — the one-shot migration that
repairs user_context.json files corrupted by the pre-fix import-screen
save bug (switching_frequency_hz blank->0; stripped signal metadata)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repair_user_context.py"


@pytest.fixture(scope="module")
def repair():
    """Import the script as a module (it lives outside the package)."""
    spec = importlib.util.spec_from_file_location("repair_user_context", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["repair_user_context"] = mod
    spec.loader.exec_module(mod)
    return mod


_ASC = (
    "Version 4\n"
    "SHEET 1 880 680\n"
    "FLAG 100 200 VIN\n"
    "FLAG 300 400 VOUT\n"
)


def _corrupt_ctx() -> dict:
    return {
        "input_voltage_v": 12,
        "switching_frequency_hz": 0,          # blank -> 0 corruption
        "load_current_a": 0.5,
        "signals": [
            # Vin / Vout match FLAG labels -> restorable.
            {"name": "Vin", "kind": "voltage", "expr": "V(Vin)", "source": "user", "confidence": 0.8},
            {"name": "Vout", "kind": "voltage", "expr": "V(Vout)", "source": "user", "confidence": 0.8},
            # Genuine user-added name, no FLAG -> must be left untouched.
            {"name": "Vsense", "kind": "voltage", "expr": "V(Vsense)", "source": "user", "confidence": 0.8},
        ],
    }


def _project(tmp_path: Path) -> Path:
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "dut.asc").write_text(_ASC, encoding="utf-8")
    (inp / "user_context.json").write_text(json.dumps(_corrupt_ctx()), encoding="utf-8")
    return inp


def test_detect_zero_numerics_flags_switching_freq(repair):
    zeros = repair.detect_zero_numerics(_corrupt_ctx())
    paths = [p for p, _v in zeros]
    assert "switching_frequency_hz" in paths
    # Non-zero numerics are not flagged.
    assert "input_voltage_v" not in paths
    assert "load_current_a" not in paths


def test_detect_degraded_signals_lists_all_low_confidence(repair):
    degraded = repair.detect_degraded_signals(_corrupt_ctx())
    names = [s.get("name") for _i, s in degraded]
    assert names == ["Vin", "Vout", "Vsense"]


def test_report_mode_does_not_mutate(repair, tmp_path):
    inp = _project(tmp_path)
    original = (inp / "user_context.json").read_text(encoding="utf-8")
    ctx = json.loads(original)
    _ctx, findings, changes = repair.diagnose_and_repair(ctx, inp, fix=False)
    assert changes == []                                  # report-only
    assert any("switching_frequency_hz" in f for f in findings)
    assert (inp / "user_context.json").read_text(encoding="utf-8") == original


def test_fix_restores_flag_signals_and_nulls_switching_freq(repair, tmp_path):
    inp = _project(tmp_path)
    ctx = json.loads((inp / "user_context.json").read_text(encoding="utf-8"))
    ctx, _findings, changes = repair.diagnose_and_repair(ctx, inp, fix=True)

    # switching frequency repaired to null.
    assert ctx["switching_frequency_hz"] is None

    by_name = {s["name"]: s for s in ctx["signals"]}
    # FLAG-matched signals get their provenance + expr + confidence back.
    assert by_name["Vin"]["from_label"] == "VIN"
    assert by_name["Vin"]["expr"] == "V(VIN)"
    assert by_name["Vin"]["confidence"] == 1.0
    assert "FLAG" in by_name["Vin"]["rationale"]
    assert by_name["Vout"]["from_label"] == "VOUT"

    # The genuine user-added name is left exactly as it was.
    assert "from_label" not in by_name["Vsense"]
    assert by_name["Vsense"]["confidence"] == 0.8
    assert by_name["Vsense"]["expr"] == "V(Vsense)"

    assert len(changes) == 3  # switching freq + Vin + Vout


def test_main_writes_backup_and_repairs_file(repair, tmp_path, capsys):
    inp = _project(tmp_path)
    ctx_path = inp / "user_context.json"
    before = ctx_path.read_text(encoding="utf-8")

    rc = repair.main(["--fix", str(ctx_path)])
    assert rc == 0

    backup = Path(str(ctx_path) + ".bak")
    assert backup.is_file()
    assert backup.read_text(encoding="utf-8") == before        # backup is the pre-fix copy

    repaired = json.loads(ctx_path.read_text(encoding="utf-8"))
    assert repaired["switching_frequency_hz"] is None
    assert {s["name"]: s for s in repaired["signals"]}["Vin"]["from_label"] == "VIN"


def test_main_report_mode_returns_nonzero_when_corrupt(repair, tmp_path):
    inp = _project(tmp_path)
    rc = repair.main([str(inp / "user_context.json")])
    assert rc == 1                                              # findings present, no --fix


def test_main_clean_file_returns_zero(repair, tmp_path):
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "dut.asc").write_text(_ASC, encoding="utf-8")
    clean = {
        "input_voltage_v": 12,
        "switching_frequency_hz": None,
        "signals": [
            {"name": "Vin", "kind": "voltage", "expr": "V(VIN)", "source": "user",
             "unit": "V", "confidence": 1.0, "from_label": "VIN",
             "rationale": "LTspice .asc FLAG label `VIN`"},
        ],
    }
    (inp / "user_context.json").write_text(json.dumps(clean), encoding="utf-8")
    assert repair.main([str(inp / "user_context.json")]) == 0
