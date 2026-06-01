"""Tests for the compliance limit-line module."""

from __future__ import annotations

from emc_assistant.results.limits import (
    DEFAULT_STANDARD_ID,
    EN55022_CLASS_B,
    STANDARDS,
    get_standard,
    limit_dbuv,
    margin_db,
    worst_margin,
)

_QP = EN55022_CLASS_B.quasi_peak
_AVG = EN55022_CLASS_B.average


def test_default_standard_is_en55022_class_b():
    assert DEFAULT_STANDARD_ID == "en55022_class_b"
    assert get_standard(None) is EN55022_CLASS_B
    assert get_standard("en55022_class_b") is EN55022_CLASS_B
    assert get_standard("does_not_exist") is None
    assert "en55022_class_b" in STANDARDS


def test_en55022_class_b_quasi_peak_breakpoints():
    # EN 55022 Class B conducted QP: 66 → 56 → 56 → 60 dBµV.
    assert limit_dbuv(_QP, 0.15e6) == 66.0
    assert limit_dbuv(_QP, 0.50e6) == 56.0   # half-open edge -> flat band
    assert limit_dbuv(_QP, 1.0e6) == 56.0
    assert limit_dbuv(_QP, 5.0e6) == 60.0    # step up to the 5-30 MHz band
    assert limit_dbuv(_QP, 30.0e6) == 60.0


def test_en55022_class_b_average_breakpoints():
    # Class B conducted average: 56 → 46 → 46 → 50 dBµV.
    assert limit_dbuv(_AVG, 0.15e6) == 56.0
    assert limit_dbuv(_AVG, 1.0e6) == 46.0
    assert limit_dbuv(_AVG, 10.0e6) == 50.0


def test_log_linear_interpolation_in_the_sloped_segment():
    # 0.15–0.50 MHz QP slopes 66 → 56 dBµV log-linearly. At 0.30 MHz the
    # log-fraction is log10(2)/log10(10/3) ≈ 0.5757 -> ≈ 60.2 dBµV.
    v = limit_dbuv(_QP, 0.30e6)
    assert v is not None
    assert 59.8 < v < 60.7
    # Monotonic decrease across the sloped segment.
    assert limit_dbuv(_QP, 0.15e6) > v > limit_dbuv(_QP, 0.50e6)


def test_frequency_outside_the_limit_range_returns_none():
    assert limit_dbuv(_QP, 100e3) is None    # below 150 kHz
    assert limit_dbuv(_QP, 50e6) is None     # above 30 MHz
    assert limit_dbuv(_QP, 0.0) is None


def test_margin_sign_and_value():
    # margin = reading − limit. At 1 MHz the QP limit is 56 dBµV.
    assert margin_db(70.0, _QP, 1.0e6) == 14.0   # 14 dB over the limit
    assert margin_db(50.0, _QP, 1.0e6) == -6.0   # 6 dB of headroom
    # Outside the limit range -> no margin.
    assert margin_db(70.0, _QP, 100e3) is None


def test_worst_margin_picks_the_largest_reading_minus_limit():
    # QP limit: 56 dBµV at 1 MHz, 60 dBµV at 10 MHz.
    freqs = [1.0e6, 10.0e6, 0.20e6]
    readings = [70.0, 65.0, 60.0]   # margins ≈ +14, +5, −3.6
    wm = worst_margin(freqs, readings, _QP)
    assert wm is not None
    assert wm.freq_hz == 1.0e6           # +14 dB is the worst
    assert abs(wm.margin_db - 14.0) < 0.01
    assert wm.reading_dbuv == 70.0


def test_worst_margin_is_none_when_all_frequencies_out_of_range():
    # Both below the 150 kHz limit floor.
    assert worst_margin([50e3, 100e3], [70.0, 70.0], _QP) is None
