"""Tests for the `.asc` → `.cir` auto-conversion helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from emc_assistant.netlist.asc_converter import (
    AscConversionError,
    AscConversionResult,
    convert_asc_to_cir,
)


class _FakeProc:
    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = stderr


def _make_asc(tmp_path: Path) -> Path:
    asc = tmp_path / "demo.asc"
    asc.write_text("Version 4\nSHEET 1 880 680\n", encoding="utf-8")
    return asc


def _make_fake_exe(tmp_path: Path) -> Path:
    exe = tmp_path / "ltspice_stub.exe"
    exe.write_text("# fake LTspice", encoding="utf-8")
    return exe


def _make_runner(exit_code: int = 0, write_net: bool = True, stderr: str = ""):
    def _runner(cmd, *args, **kwargs):
        # cmd[-1] is the .asc path
        asc = Path(cmd[-1])
        if write_net and exit_code == 0:
            asc.with_suffix(".net").write_text(
                "* netlisted by fake LTspice\n"
                "Vin in 0 DC 24\n"
                "R1 in out 1k\n"
                ".tran 0 1m\n"
                ".end\n",
                encoding="utf-8",
            )
        return _FakeProc(returncode=exit_code, stderr=stderr)
    return _runner


def test_convert_asc_to_cir_happy_path(tmp_path: Path):
    asc = _make_asc(tmp_path)
    exe = _make_fake_exe(tmp_path)
    result = convert_asc_to_cir(asc, ltspice_exe=exe, subprocess_run=_make_runner())
    assert isinstance(result, AscConversionResult)
    assert result.used_cache is False
    assert result.cir_path == asc.with_suffix(".cir")
    assert result.cir_path.is_file()
    content = result.cir_path.read_text(encoding="utf-8")
    assert "Vin in 0 DC 24" in content


def test_convert_asc_to_cir_caches_when_cir_newer(tmp_path: Path):
    asc = _make_asc(tmp_path)
    exe = _make_fake_exe(tmp_path)
    # Pre-create a fresh .cir
    cir = asc.with_suffix(".cir")
    cir.write_text("* pre-existing cached netlist\n", encoding="utf-8")
    # Bump mtime so cir > asc
    import os
    asc_mtime = asc.stat().st_mtime
    os.utime(cir, (asc_mtime + 10, asc_mtime + 10))

    called = {"n": 0}

    def _runner_should_not_be_called(cmd, *args, **kwargs):
        called["n"] += 1
        return _FakeProc()

    result = convert_asc_to_cir(asc, ltspice_exe=exe, subprocess_run=_runner_should_not_be_called)
    assert result.used_cache is True
    assert called["n"] == 0
    # Cached content preserved
    assert "pre-existing" in cir.read_text(encoding="utf-8")


def test_convert_asc_to_cir_force_bypasses_cache(tmp_path: Path):
    asc = _make_asc(tmp_path)
    exe = _make_fake_exe(tmp_path)
    cir = asc.with_suffix(".cir")
    cir.write_text("# stale cached\n", encoding="utf-8")
    import os
    asc_mtime = asc.stat().st_mtime
    os.utime(cir, (asc_mtime + 10, asc_mtime + 10))
    result = convert_asc_to_cir(
        asc, ltspice_exe=exe, force=True, subprocess_run=_make_runner()
    )
    assert result.used_cache is False
    # Fresh content overrode the cache
    assert "netlisted by fake LTspice" in result.cir_path.read_text(encoding="utf-8")


def test_convert_asc_to_cir_raises_when_ltspice_missing(tmp_path: Path):
    asc = _make_asc(tmp_path)
    # No exe path supplied → friendly error
    with pytest.raises(AscConversionError, match="not configured"):
        convert_asc_to_cir(asc, ltspice_exe=None, subprocess_run=_make_runner())


def test_convert_asc_to_cir_raises_when_exe_path_missing_on_disk(tmp_path: Path):
    asc = _make_asc(tmp_path)
    fake_path = tmp_path / "does_not_exist.exe"
    with pytest.raises(AscConversionError, match="not found"):
        convert_asc_to_cir(asc, ltspice_exe=fake_path, subprocess_run=_make_runner())


def test_convert_asc_to_cir_raises_on_nonzero_exit(tmp_path: Path):
    asc = _make_asc(tmp_path)
    exe = _make_fake_exe(tmp_path)
    with pytest.raises(AscConversionError, match="exited with code"):
        convert_asc_to_cir(
            asc,
            ltspice_exe=exe,
            subprocess_run=_make_runner(exit_code=2, write_net=False, stderr="syntax error"),
        )


def test_convert_asc_to_cir_raises_when_no_output_produced(tmp_path: Path):
    asc = _make_asc(tmp_path)
    exe = _make_fake_exe(tmp_path)
    with pytest.raises(AscConversionError, match="did not produce"):
        convert_asc_to_cir(
            asc,
            ltspice_exe=exe,
            subprocess_run=_make_runner(exit_code=0, write_net=False),
        )


def test_convert_asc_to_cir_rejects_non_asc_input(tmp_path: Path):
    cir = tmp_path / "foo.cir"
    cir.write_text("* not an asc\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Expected .asc"):
        convert_asc_to_cir(cir, ltspice_exe=tmp_path / "x.exe")


def test_convert_asc_to_cir_missing_source_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        convert_asc_to_cir(tmp_path / "absent.asc", ltspice_exe=tmp_path / "x.exe")
