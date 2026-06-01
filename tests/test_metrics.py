"""Tests for the metrics module."""

from __future__ import annotations

import math

import pytest

from emc_assistant.results.metrics import (
    compute_trace_metrics,
    max_in_band,
    pick_default_trace,
    summarize_default_metrics,
)
from emc_assistant.results.raw_parser import RawFile, RawHeader, RawVariable


def _make_raw(axis, traces, complex_flag=False):
    header = RawHeader(
        title="t",
        flags=["complex" if complex_flag else "real"],
        n_variables=len(traces) + 1,
        n_points=len(axis),
        variables=[
            RawVariable(0, "axis", "frequency" if complex_flag else "time"),
            *[RawVariable(i + 1, n, "voltage") for i, n in enumerate(traces.keys())],
        ],
        is_binary=True,
        is_complex=complex_flag,
    )
    all_traces = {"axis": list(axis), **{k: list(v) for k, v in traces.items()}}
    return RawFile(header=header, axis=list(axis), traces=all_traces)


def test_compute_trace_metrics_basic():
    m = compute_trace_metrics([0.0, 1.0, -2.0, 0.5])
    assert m.max == 1.0
    assert m.min == -2.0
    assert m.peak == 2.0
    assert m.peak_to_peak == 3.0
    assert m.rms == pytest.approx(math.sqrt((1 + 4 + 0.25) / 4))


def test_compute_trace_metrics_rejects_empty():
    with pytest.raises(ValueError):
        compute_trace_metrics([])


def test_max_in_band_inclusive():
    axis = [100.0, 1e3, 1e4, 1e5, 1e6]
    values = [0.1, 0.5, -0.7, 0.2, 0.05]
    assert max_in_band(axis, values, axis_min=500, axis_max=1e5) == pytest.approx(0.7)


def test_max_in_band_no_samples_returns_none():
    axis = [1.0, 2.0]
    values = [0.5, 0.6]
    assert max_in_band(axis, values, axis_min=10.0, axis_max=20.0) is None


def test_max_in_band_validates_lengths_and_bounds():
    with pytest.raises(ValueError):
        max_in_band([1, 2], [1.0], axis_min=0, axis_max=1)
    with pytest.raises(ValueError):
        max_in_band([1, 2], [1.0, 2.0], axis_min=1.0, axis_max=0.0)


def test_pick_default_trace_prefers_v_meas():
    raw = _make_raw([0.0, 1.0], {"V(in)": [0.0, 1.0], "V(meas)": [0.0, -0.5]})
    assert pick_default_trace(raw) == "V(meas)"


def test_pick_default_trace_first_voltage():
    raw = _make_raw([0.0, 1.0], {"V(in)": [0.0, 1.0], "V(out)": [0.0, 0.2]})
    assert pick_default_trace(raw) == "V(out)"


def test_summarize_default_metrics_keys():
    raw = _make_raw([0.0, 1e-6, 2e-6], {"V(meas)": [0.0, 1.0, -1.0]})
    out = summarize_default_metrics(raw)
    assert any(k.startswith("v_meas_") for k in out)
    assert "axis_min" in out and "axis_max" in out


def test_summarize_default_metrics_adds_conducted_emi_band_for_frequency_axis():
    axis = [1e3, 1e5, 5e6, 1e8]
    values = [0.1, 0.5, 0.7, 0.05]
    raw = _make_raw(axis, {"V(meas)": values}, complex_flag=True)
    out = summarize_default_metrics(raw)
    band_key = "v_meas_max_in_band_150000_30000000"
    assert band_key in out
    # Peak inside 150 kHz – 30 MHz is 0.7 at 5 MHz.
    assert out[band_key] == pytest.approx(0.7)


def test_summarize_default_metrics_skips_band_for_time_axis():
    raw = _make_raw([0.0, 1e-6, 2e-6], {"V(meas)": [0.0, 1.0, -1.0]})
    out = summarize_default_metrics(raw)
    assert not any("max_in_band" in k for k in out)


def test_summarize_default_metrics_accepts_custom_bands():
    axis = [1e3, 1e4, 1e5, 1e6]
    values = [0.1, 0.6, 0.4, 0.2]
    raw = _make_raw(axis, {"V(meas)": values}, complex_flag=True)
    out = summarize_default_metrics(raw, bands_hz=((1e3, 1e5),))
    assert "v_meas_max_in_band_1000_100000" in out
    assert out["v_meas_max_in_band_1000_100000"] == pytest.approx(0.6)
