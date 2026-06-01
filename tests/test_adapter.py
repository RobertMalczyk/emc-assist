"""Tests for the local LTspice adapter (``emc_assistant.ltspice.adapter``).

``discover_ltspice`` has a four-step resolution order (configured path →
``LTSPICE_PATH`` env → common Windows paths → ``shutil.which``) that was
never asserted; a wrong branch would silently pick the wrong executable
or none at all. The autouse fixture neutralises machine-dependent
discovery so each test fully controls its own inputs.
"""

from __future__ import annotations

import pytest

from emc_assistant.ltspice import adapter
from emc_assistant.ltspice.adapter import LtspiceAdapter, discover_ltspice


@pytest.fixture(autouse=True)
def _no_ambient_ltspice(monkeypatch):
    """Strip out anything the host machine would contribute to discovery."""
    monkeypatch.delenv("LTSPICE_PATH", raising=False)
    monkeypatch.setattr(adapter, "COMMON_WINDOWS_PATHS", ())
    monkeypatch.setattr(adapter.shutil, "which", lambda name: None)


def _exe(path):
    path.write_text("", encoding="utf-8")
    return path


def test_discover_returns_none_when_nothing_found():
    assert discover_ltspice() is None


def test_discover_uses_configured_path_when_it_exists(tmp_path):
    exe = _exe(tmp_path / "LTspice.exe")
    assert discover_ltspice(str(exe)) == exe


def test_discover_ignores_a_configured_path_that_does_not_exist(tmp_path):
    assert discover_ltspice(str(tmp_path / "absent.exe")) is None


def test_discover_uses_ltspice_path_env_var(tmp_path, monkeypatch):
    exe = _exe(tmp_path / "env_ltspice.exe")
    monkeypatch.setenv("LTSPICE_PATH", str(exe))
    assert discover_ltspice() == exe


def test_discover_configured_path_wins_over_env(tmp_path, monkeypatch):
    configured = _exe(tmp_path / "configured.exe")
    monkeypatch.setenv("LTSPICE_PATH", str(_exe(tmp_path / "env.exe")))
    assert discover_ltspice(str(configured)) == configured


def test_discover_uses_common_windows_paths(tmp_path, monkeypatch):
    exe = _exe(tmp_path / "XVIIx64.exe")
    monkeypatch.setattr(adapter, "COMMON_WINDOWS_PATHS", (str(exe),))
    assert discover_ltspice() == exe


def test_discover_falls_back_to_path_lookup(tmp_path, monkeypatch):
    found = _exe(tmp_path / "LTspice")
    monkeypatch.setattr(
        adapter.shutil, "which",
        lambda name: str(found) if name == "LTspice" else None,
    )
    assert discover_ltspice() == found


def test_adapter_available_true_for_a_real_file(tmp_path):
    assert LtspiceAdapter(executable=_exe(tmp_path / "LTspice.exe")).available is True


def test_adapter_available_false_when_executable_none():
    assert LtspiceAdapter(executable=None).available is False


def test_adapter_available_false_when_file_missing(tmp_path):
    assert LtspiceAdapter(executable=tmp_path / "gone.exe").available is False


def test_build_command_is_batch_run(tmp_path):
    exe = tmp_path / "LTspice.exe"
    netlist = tmp_path / "tb.cir"
    cmd = LtspiceAdapter(executable=exe).build_command(netlist)
    assert cmd == [str(exe), "-b", "-Run", str(netlist)]


def test_build_command_without_executable_uses_a_placeholder(tmp_path):
    cmd = LtspiceAdapter(executable=None).build_command(tmp_path / "tb.cir")
    assert cmd[0] == "<ltspice-not-found>"
    assert cmd[1:3] == ["-b", "-Run"]
