"""Tests for the Python-JS bridge (ui/bridge.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emc_assistant.ui.bridge import Api, _jsonable


def test_ping():
    res = Api().ping()
    assert res["ok"] is True
    assert res["data"]["pong"] is True
    assert isinstance(res["data"]["version"], str)


def test_jsonable_nulls_non_finite_floats():
    # JS `JSON.parse` rejects NaN / Infinity. The bridge must never ship them
    # (a single NaN in a waveform/spectrum payload would blank the whole chart).
    out = _jsonable({"lo": float("nan"), "hi": float("inf"), "neg": float("-inf"),
                     "ok": 1.5, "n": 3, "s": "x"})
    assert out == {"lo": None, "hi": None, "neg": None, "ok": 1.5, "n": 3, "s": "x"}
    # The whole payload must serialise as *strict* JSON (no bare NaN tokens).
    assert json.loads(json.dumps(out, allow_nan=False)) == out


def test_create_validate_status_round_trip(tmp_path: Path):
    api = Api()
    project = str(tmp_path / "proj")

    created = api.create_project(project)
    assert created["ok"] is True
    assert created["data"]["project_id"] == "proj"

    validated = api.validate_project(project)
    assert validated["ok"] is True
    assert validated["data"]["project_id"] == "proj"

    status = api.project_status(project)
    assert status["ok"] is True
    assert "stages" in status["data"] and "llm" in status["data"]


def test_create_project_refuses_overwrite(tmp_path: Path):
    api = Api()
    project = str(tmp_path / "proj")
    assert api.create_project(project)["ok"] is True
    again = api.create_project(project)
    assert again["ok"] is False
    assert "Refusing to overwrite" in again["error"]["message"]
    assert again["error"]["exit_code"] == 1


def test_service_error_carries_details(tmp_path: Path):
    # A non-existent project fails validation -> structured error envelope.
    res = Api().validate_project(str(tmp_path / "nope"))
    assert res["ok"] is False
    assert "message" in res["error"] and "details" in res["error"]


def test_save_and_load_context(tmp_path: Path):
    api = Api()
    project = str(tmp_path / "proj")
    api.create_project(project)

    payload = {"input_voltage_v": 24.0, "load_current_a": 3.0}
    saved = api.save_context(project, payload)
    assert saved["ok"] is True

    loaded = api.load_context(project)
    assert loaded["ok"] is True
    assert loaded["data"] == payload


def test_list_projects(tmp_path: Path):
    api = Api()
    api.create_project(str(tmp_path / "alpha"))
    api.create_project(str(tmp_path / "beta"))
    res = api.list_projects(str(tmp_path))
    assert res["ok"] is True
    names = {p["name"] for p in res["data"]}
    assert names == {"alpha", "beta"}


def test_read_artifact_reads_json(tmp_path: Path):
    api = Api()
    project = tmp_path / "proj"
    api.create_project(str(project))
    artifact = project / "generated" / "x.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps({"k": 1}), encoding="utf-8")

    res = api.read_artifact(str(project), "generated/x.json")
    assert res["ok"] is True
    assert res["data"] == {"k": 1}


def test_read_artifact_rejects_path_traversal(tmp_path: Path):
    api = Api()
    project = tmp_path / "proj"
    api.create_project(str(project))
    (tmp_path / "secret.json").write_text("{}", encoding="utf-8")

    res = api.read_artifact(str(project), "../secret.json")
    assert res["ok"] is False
    assert "escapes" in res["error"]["message"]


def test_read_artifact_missing_file(tmp_path: Path):
    api = Api()
    project = tmp_path / "proj"
    api.create_project(str(project))
    res = api.read_artifact(str(project), "generated/nope.json")
    assert res["ok"] is False
    assert "not found" in res["error"]["message"]


def test_load_spectrum_graceful_without_raw(tmp_path: Path):
    api = Api()
    project = str(tmp_path / "proj")
    api.create_project(project)
    res = api.load_spectrum(project)
    assert res["ok"] is True            # never throws at the UI
    assert res["data"]["available"] is False
    assert "note" in res["data"]


def test_load_waveform_graceful_without_raw(tmp_path: Path):
    api = Api()
    project = str(tmp_path / "proj")
    api.create_project(project)
    res = api.load_waveform(project)
    assert res["ok"] is True            # never throws at the UI
    assert res["data"]["available"] is False
    assert "note" in res["data"]


def _write_tran_raw(path: Path, n: int, spike_at: int, spike_v: float) -> None:
    """Synthetic ASCII transient .raw: time + one voltage trace, with a
    single sharp spike so we can prove the envelope decimation keeps it."""
    import math

    lines = [
        "Title: * synthetic tran\n",
        "Date: 2026-05-22\n",
        "Plotname: Transient Analysis\n",
        "Flags: real\n",
        "No. Variables: 2\n",
        f"No. Points: {n}\n",
        "Offset: 0\n",
        "Command: synthetic\n",
        "Variables:\n",
        "\t0\ttime\ttime\n",
        "\t1\tV(meas)\tvoltage\n",
        "Values:\n",
    ]
    body = []
    for i in range(n):
        t = i * 1e-8                       # 10 ns step
        v = 0.1 * math.sin(2 * math.pi * 1e6 * t)
        if i == spike_at:
            v = spike_v
        body += [f"{i}\t{t}", f"\t{v}"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines) + "\n".join(body) + "\n", encoding="utf-8")


def test_load_waveform_returns_envelope_and_keeps_spikes(tmp_path: Path):
    api = Api()
    project = tmp_path / "proj"
    api.create_project(str(project))
    n, spike_at, spike_v = 3000, 1500, 99.0
    _write_tran_raw(project / "generated" / "testbench.raw", n, spike_at, spike_v)

    res = api.load_waveform(str(project))
    assert res["ok"] is True
    data = res["data"]
    assert data["available"] is True
    assert data["trace"] == "V(meas)"
    assert data["unit"] == "V"
    assert data["n_raw"] == n
    pts = data["points"]
    # Downsampled to <= the bucket cap, far fewer than the raw points.
    assert 2 <= len(pts) < n
    assert all(p["hi"] >= p["lo"] for p in pts)
    # The spike must survive min/max decimation (a naive stride would drop it).
    assert max(p["hi"] for p in pts) >= spike_v - 1e-6
    assert data["t_min"] == 0.0
    assert data["t_max"] > data["t_min"]


def test_load_waveform_named_current_trace_aligns_with_primary(tmp_path: Path):
    api = Api()
    project = tmp_path / "proj"
    api.create_project(str(project))
    _write_tran_raw_2(project / "generated" / "testbench.raw", 2000)

    primary = api.load_waveform(str(project))["data"]
    cur = api.load_waveform(str(project), "I(Rload)")["data"]
    assert cur["available"] is True
    assert cur["trace"] == "I(Rload)"
    assert cur["unit"] == "A"            # current trace -> amps
    # Same axis + bucket edges -> the two envelopes line up on the time axis.
    assert cur["t_min"] == primary["t_min"]
    assert cur["t_max"] == primary["t_max"]
    assert len(cur["points"]) == len(primary["points"])


def test_load_waveform_unknown_trace_is_graceful(tmp_path: Path):
    api = Api()
    project = tmp_path / "proj"
    api.create_project(str(project))
    _write_tran_raw_2(project / "generated" / "testbench.raw", 500)
    res = api.load_waveform(str(project), "V(nope)")
    assert res["ok"] is True
    assert res["data"]["available"] is False


def test_suggest_waveform_traces_graceful_without_raw(tmp_path: Path):
    api = Api()
    project = str(tmp_path / "proj")
    api.create_project(project)
    res = api.suggest_waveform_traces(project)
    assert res["ok"] is True
    assert res["data"]["available"] is False
    assert "note" in res["data"]


def test_suggest_waveform_traces_default_and_four(tmp_path: Path):
    api = Api()
    project = tmp_path / "proj"
    api.create_project(str(project))
    _write_tran_raw_2(project / "generated" / "testbench.raw", 800)
    res = api.suggest_waveform_traces(str(project))
    assert res["ok"] is True
    data = res["data"]
    assert data["available"] is True
    assert data["primary"] == "V(meas)"
    assert data["default"]["trace"] == "I(Rload)"
    assert len(data["suggestions"]) >= 1
    # the selector list leads with the default
    assert data["options"][0]["trace"] == "I(Rload)"


def _write_tran_raw_2(path: Path, n: int) -> None:
    """ASCII transient .raw with a richer inventory (V(meas), V(cm), I(Rload),
    I(V_RAIL), I(L1)) so the suggester has real candidates to choose from."""
    import math

    cols = [
        ("time", "time"),
        ("V(meas)", "voltage"),
        ("V(cm)", "voltage"),
        ("I(Rload)", "device_current"),
        ("I(V_RAIL)", "device_current"),
        ("I(L1)", "device_current"),
    ]
    header = [
        "Title: * synthetic tran\n", "Date: 2026-05-22\n",
        "Plotname: Transient Analysis\n", "Flags: real\n",
        f"No. Variables: {len(cols)}\n", f"No. Points: {n}\n",
        "Offset: 0\n", "Command: synthetic\n", "Variables:\n",
    ]
    for i, (nm, kind) in enumerate(cols):
        header.append(f"\t{i}\t{nm}\t{kind}\n")
    header.append("Values:\n")
    body = []
    for i in range(n):
        t = i * 1e-8
        body.append(f"{i}\t{t}")
        for k in range(1, len(cols)):
            body.append(f"\t{0.1 * math.sin(2 * math.pi * 1e6 * t + k)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(header) + "\n".join(body) + "\n", encoding="utf-8")


def test_load_simulation_settings_defaults(tmp_path: Path):
    api = Api()
    project = str(tmp_path / "proj")
    api.create_project(project)
    res = api.load_simulation_settings(project)
    assert res["ok"] is True
    d = res["data"]
    assert d["stop_time"] == "5m" and d["max_timestep"] == "100n"
    assert d["has_raw_directive"] is False
    assert d["effective"]["stop_s"] == pytest.approx(0.005)
    assert d["effective"]["max_timestep_s"] == pytest.approx(100e-9)


def test_save_simulation_settings_round_trips(tmp_path: Path):
    api = Api()
    project = str(tmp_path / "proj")
    api.create_project(project)
    saved = api.save_simulation_settings(project, {
        "stop_time": "0.002", "max_timestep": "5e-9", "record_start": "0",
        "integration_method": "trap",
    })
    assert saved["ok"] is True
    eff = saved["data"]["effective"]
    assert eff["stop_s"] == pytest.approx(0.002) and eff["max_timestep_s"] == pytest.approx(5e-9)
    # round-trips through a fresh load
    again = api.load_simulation_settings(project)["data"]
    assert again["effective"]["stop_s"] == pytest.approx(0.002)
    # and it's persisted in user_context.simulation
    uc = api.load_context(project)["data"]
    assert uc["simulation"]["stop_time"] == "0.002"


def test_save_simulation_settings_rejects_invalid(tmp_path: Path):
    api = Api()
    project = str(tmp_path / "proj")
    api.create_project(project)
    res = api.save_simulation_settings(project, {"stop_time": "0.001", "max_timestep": "0.01"})
    assert res["ok"] is False                       # step > stop
    assert "Invalid" in res["error"]["message"]


def test_save_simulation_promotes_raw_directive_to_structured(tmp_path: Path):
    api = Api()
    project = str(tmp_path / "proj")
    api.create_project(project)
    # a project that uses a raw .tran override
    api.save_context(project, {"simulation": {"tran_directive": ".tran 0 1m 0 5n"}})
    loaded = api.load_simulation_settings(project)["data"]
    assert loaded["has_raw_directive"] is True
    assert loaded["effective"]["stop_s"] == pytest.approx(0.001) and loaded["effective"]["max_timestep_s"] == pytest.approx(5e-9)
    # saving from the panel writes structured fields and drops the raw override
    api.save_simulation_settings(project, {"stop_time": "0.001", "max_timestep": "5e-9", "record_start": "0"})
    after = api.load_simulation_settings(project)["data"]
    assert after["has_raw_directive"] is False
    assert after["effective"]["stop_s"] == pytest.approx(0.001)


def test_assess_simulation_overrides_flags_coarse_timestep(tmp_path: Path):
    api = Api()
    project = str(tmp_path / "proj")
    api.create_project(project)
    # proposed coarse step → cannot resolve 30 MHz → high severity
    res = api.assess_simulation(project, {"stop_time": "0.001", "max_timestep": "1e-6", "record_start": "0"})
    assert res["ok"] is True
    assert res["data"]["ok"] is False
    ids = {c["id"] for c in res["data"]["checks"]}
    assert "timestep_aliases_band" in ids
    # a fine proposed step is adequate
    res2 = api.assess_simulation(project, {"stop_time": "0.002", "max_timestep": "5e-9", "record_start": "0"})
    assert res2["data"]["ok"] is True


def test_inspect_netlist_without_netlist_is_structured_error(tmp_path: Path):
    api = Api()
    project = str(tmp_path / "proj")
    api.create_project(project)  # skeleton has an empty netlist_path
    res = api.inspect_netlist(project)
    assert res["ok"] is False
    assert "netlist" in res["error"]["message"].lower()
