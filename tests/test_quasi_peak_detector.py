"""Focused validation of the quasi-peak detector — regression suite.

The quasi-peak detector is a CISPR-like *pre-compliance diagnostic*
(see docs/concepts/quasi_peak_detector_concept.md), not a certified
measurement. These tests prove it behaves as a correct asymmetric
charge/discharge detector — fast charge, slow discharge — with the
EN 55016-1-1 ed. 3 band constants, and that it never produces a
misleading reading. They are deliberately narrow and numeric so a
regression is caught immediately.

The detector core is ``_charge_discharge`` — it returns the full meter
trajectory, so the charge and discharge time constants can be checked
directly rather than inferred.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from emc_assistant.cli import main
from emc_assistant.results.raw_parser import RawFile, RawHeader, RawVariable
from emc_assistant.service import ServiceError
from emc_assistant.service import raw as raw_service
from emc_assistant.results.detectors import (
    CISPR_BAND_A,
    CISPR_BAND_B,
    CISPR_BAND_C_D,
    CONDUCTED_BANDS,
    _charge_discharge,
    _qp_meter,
    _to_dbuv,
)

_INV_E = 1.0 / math.e        # ≈ 0.3679 — one time constant of decay
_ONE_MINUS_INV_E = 1.0 - _INV_E  # ≈ 0.6321 — one time constant of charge


# ── 1. band constants ──────────────────────────────────────────────────────


def test_band_constants_match_en55016_1_1():
    """Detector configs per EN 55016-1-1 ed. 3 (CISPR 16-1-1)."""
    # Band A — 9 kHz to 150 kHz.
    assert CISPR_BAND_A.f_low == 9e3 and CISPR_BAND_A.f_high == 150e3
    assert CISPR_BAND_A.rbw_hz == 200.0
    assert CISPR_BAND_A.qp_charge_s == 45e-3
    assert CISPR_BAND_A.qp_discharge_s == 500e-3
    assert CISPR_BAND_A.meter_s == 160e-3

    # Band B — 150 kHz to 30 MHz (the conducted-EMI band for DC/DC).
    assert CISPR_BAND_B.f_low == 150e3 and CISPR_BAND_B.f_high == 30e6
    assert CISPR_BAND_B.rbw_hz == 9e3
    assert CISPR_BAND_B.qp_charge_s == 1e-3
    assert CISPR_BAND_B.qp_discharge_s == 160e-3
    assert CISPR_BAND_B.meter_s == 160e-3

    # Band C/D — 30 MHz to 1 GHz.
    assert CISPR_BAND_C_D.f_low == 30e6 and CISPR_BAND_C_D.f_high == 1e9
    assert CISPR_BAND_C_D.rbw_hz == 120e3
    assert CISPR_BAND_C_D.qp_charge_s == 1e-3
    assert CISPR_BAND_C_D.qp_discharge_s == 550e-3
    assert CISPR_BAND_C_D.meter_s == 100e-3


def test_default_conducted_emi_band_is_band_b():
    assert CONDUCTED_BANDS == (CISPR_BAND_B,)


# ── 2. dBµV conversion ─────────────────────────────────────────────────────


def test_dbuv_conversion_reference_points():
    # dBµV = 20·log10(V / 1 µV).
    assert abs(float(_to_dbuv(1e-6)) - 0.0) < 1e-9     # 1 µV  -> 0 dBµV
    assert abs(float(_to_dbuv(1e-3)) - 60.0) < 1e-9    # 1 mV  -> 60 dBµV
    assert abs(float(_to_dbuv(2e-3)) - 66.0206) < 1e-3  # 2 mV  -> ≈ 66.02 dBµV


# ── 3. charge-time constant ────────────────────────────────────────────────


def test_charge_reaches_63_percent_after_one_charge_time_constant():
    """A 0→1 V envelope step: the detector core charges to ~1-1/e ≈ 0.632
    after exactly one charge time constant. Verifies the charge constant
    and that the sign is correct (it rises, not falls)."""
    dt, charge_s, discharge_s = 1e-6, 1e-3, 160e-3
    n = round(charge_s / dt)  # exactly one charge time constant of samples
    traj = _charge_discharge(np.ones(n), dt, charge_s, discharge_s)
    assert abs(traj[-1] - _ONE_MINUS_INV_E) < 0.02  # ~0.632 ± ~3 %
    # Monotonic rise toward the input — never overshoots it.
    assert traj[0] < traj[-1] <= 1.0


# ── 4. discharge-time constant ─────────────────────────────────────────────


def test_discharge_reaches_37_percent_after_one_discharge_time_constant():
    """Detector core seeded at 1 V, fed a 0 V envelope: it decays to
    ~1/e ≈ 0.368 after exactly one discharge time constant. Catches a
    wrong sign or a swapped charge/discharge constant."""
    dt, charge_s, discharge_s = 1e-4, 1e-3, 160e-3
    n = round(discharge_s / dt)  # exactly one discharge time constant
    traj = _charge_discharge(np.zeros(n), dt, charge_s, discharge_s, initial=1.0)
    assert abs(traj[-1] - _INV_E) < 0.02  # ~0.368 ± ~3 %
    # Monotonic decay toward zero — never goes negative.
    assert 0.0 <= traj[-1] < traj[0]


def test_charge_is_much_faster_than_discharge():
    """The defining asymmetry: with Band B constants the meter charges
    far more than it discharges in the same elapsed time."""
    dt, charge_s, discharge_s = 1e-5, 1e-3, 160e-3
    n = 200
    rose = _charge_discharge(np.ones(n), dt, charge_s, discharge_s)[-1]
    fell = _charge_discharge(np.zeros(n), dt, charge_s, discharge_s, initial=1.0)[-1]
    # Distance travelled toward the target: charge >> discharge.
    assert (rose - 0.0) > (1.0 - fell)


# ── 5. constant-envelope / CW sanity ───────────────────────────────────────


def test_constant_envelope_converges_to_that_level():
    """A constant (CW-like) envelope: the detector charges up to that
    level and settles there — peak and quasi-peak agree."""
    dt, charge_s, discharge_s = 1e-5, 1e-3, 160e-3
    level = 0.5
    n = round(8 * charge_s / dt)  # 8 charge constants — long enough to settle
    traj = _charge_discharge(np.full(n, level), dt, charge_s, discharge_s)
    assert abs(traj[-1] - level) < 0.01
    # Quasi-peak (running max) never exceeds the envelope peak.
    assert traj.max() <= level + 1e-9


def test_quasi_peak_never_exceeds_envelope_peak():
    """For any input the QP reading must not exceed the input peak —
    a QP that read above peak would be misleading."""
    rng = np.random.default_rng(1)
    envelope = np.abs(rng.standard_normal(2000))
    traj = _charge_discharge(envelope, dt=1e-5, charge_s=1e-3, discharge_s=160e-3)
    assert traj.max() <= envelope.max() + 1e-9


# ── 6. regression lock — Mode 1 detector vs the core ───────────────────────


def test_qp_meter_agrees_with_charge_discharge_core():
    """The Mode 1 ``_qp_meter`` (vectorised over frequency bins) must
    produce exactly the running max of the ``_charge_discharge`` core
    for a single-bin input — locks the two implementations together."""
    rng = np.random.default_rng(2)
    envelope = np.abs(rng.standard_normal(500))
    dt, charge_s, discharge_s = 1e-4, 1e-3, 20e-3
    core_max = _charge_discharge(envelope, dt, charge_s, discharge_s).max()
    meter_max = _qp_meter(
        envelope.reshape(1, -1), dt, charge_s, discharge_s
    )[0]
    assert abs(core_max - meter_max) < 1e-9


# ── 7. the `raw quasi-peak` CLI command (Mode 2) ───────────────────────────


def _make_cw_raw(freq_hz=1e6, amp=0.1, duration=2e-3, dt=1e-8) -> RawFile:
    """A synthetic single-tone transient .raw (trace ``V(meas)``)."""
    t = np.arange(0.0, duration, dt)
    v = amp * np.sin(2 * np.pi * freq_hz * t)
    header = RawHeader(
        title="synthetic",
        flags=["real"],
        n_variables=2,
        n_points=len(t),
        variables=[
            RawVariable(0, "time", "time"),
            RawVariable(1, "V(meas)", "voltage"),
        ],
        is_binary=True,
        is_complex=False,
    )
    return RawFile(
        header=header,
        axis=list(t),
        traces={"time": list(t), "V(meas)": list(v)},
    )


def test_cli_raw_quasi_peak_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(raw_service, "parse_raw", lambda _p: _make_cw_raw(1e6, 0.1))
    fake = tmp_path / "x.raw"
    fake.write_bytes(b"stub")  # _load_raw only checks the file exists
    rc = main(["raw", "quasi-peak", str(fake), "--frequency", "1e6"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Receiver-like quasi-peak" in out
    assert "quasi-peak" in out and "dBuV" in out
    assert "not a certified EMI-receiver measurement" in out


def test_quasi_peak_service_reads_on_band_tone(tmp_path, monkeypatch):
    monkeypatch.setattr(raw_service, "parse_raw", lambda _p: _make_cw_raw(1e6, 0.1))
    fake = tmp_path / "x.raw"
    fake.write_bytes(b"stub")
    report = raw_service.quasi_peak(str(fake), center_hz=1e6)
    r = report.reading
    assert report.trace == "V(meas)"
    assert r.usable and r.receiver_filtered is True
    # 0.1 V tone at the centre frequency -> ~100 dBµV.
    assert 94.0 <= r.peak_dbuv <= 104.0
    assert r.average_dbuv <= r.quasi_peak_dbuv <= r.peak_dbuv + 1e-6


def test_quasi_peak_service_rejects_unknown_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(raw_service, "parse_raw", lambda _p: _make_cw_raw())
    fake = tmp_path / "x.raw"
    fake.write_bytes(b"stub")
    with pytest.raises(ServiceError):
        raw_service.quasi_peak(str(fake), center_hz=1e6, trace="V(does_not_exist)")


# ── 8. compliance limit margin (EN 55022 Class B default) ──────────────────


def test_quasi_peak_service_computes_limit_margin(tmp_path, monkeypatch):
    monkeypatch.setattr(raw_service, "parse_raw", lambda _p: _make_cw_raw(1e6, 0.1))
    fake = tmp_path / "x.raw"
    fake.write_bytes(b"stub")
    report = raw_service.quasi_peak(str(fake), center_hz=1e6)
    assert report.standard_name == "EN 55022 Class B"
    # ~100 dBµV at 1 MHz vs the 56 dBµV QP limit -> ~+44 dB over.
    assert report.quasi_peak_margin_db is not None
    assert 40.0 < report.quasi_peak_margin_db < 48.0
    # The average limit (46 dBµV) is lower, so its margin is larger.
    assert report.average_margin_db > report.quasi_peak_margin_db


def test_quasi_peak_service_rejects_unknown_standard(tmp_path, monkeypatch):
    monkeypatch.setattr(raw_service, "parse_raw", lambda _p: _make_cw_raw())
    fake = tmp_path / "x.raw"
    fake.write_bytes(b"stub")
    with pytest.raises(ServiceError):
        raw_service.quasi_peak(str(fake), center_hz=1e6, standard_id="bogus_norm")


def test_cli_raw_quasi_peak_shows_limit_margin(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(raw_service, "parse_raw", lambda _p: _make_cw_raw(1e6, 0.1))
    fake = tmp_path / "x.raw"
    fake.write_bytes(b"stub")
    rc = main(["raw", "quasi-peak", str(fake), "--frequency", "1e6"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "EN 55022 Class B" in out
    assert "margin" in out and "over limit" in out


# ── 9. Canonical (Mode 3) worst-margin in metrics + report ─────────────────


def test_summarize_metrics_emits_worst_margin():
    from emc_assistant.results.metrics import summarize_default_metrics

    # The verdict/corner-table margin is now the canonical conducted-EMI
    # detector (Mode 3 receiver-like sweep — detectors.conducted_emi_spectrum).
    # Use a tone in the low conducted band (~switching-fundamental region),
    # which the receiver sweep samples adequately. NOTE: Mode 3's coarse
    # log sweep under-reads *narrow* tones that fall between swept points
    # (step > RBW at higher frequencies) — a documented limitation tracked in
    # tasks/detector_selectable.md.
    metrics = summarize_default_metrics(_make_cw_raw(160e3, 0.1))  # ~100 dBµV tone
    assert "v_meas_qp_worst_margin_db" in metrics
    assert "v_meas_qp_worst_margin_hz" in metrics
    assert "v_meas_avg_worst_margin_db" in metrics
    # ~100 dBµV vs the band-B QP limit (~66 dBµV at 160 kHz) — well over.
    assert metrics["v_meas_qp_worst_margin_db"] > 30.0


def test_report_emi_section_shows_compliance_margin():
    from emc_assistant.reports.markdown import _emi_detector_section

    measurements = [{
        "label": "baseline",
        "metrics": {
            "v_meas_band_quasi_peak_dbuv_150000_30000000": 75.0,
            "v_meas_qp_worst_margin_db": 19.0,
            "v_meas_qp_worst_margin_hz": 8.0e5,
            "v_meas_avg_worst_margin_db": 12.0,
            "v_meas_avg_worst_margin_hz": 8.0e5,
        },
    }]
    section = "\n".join(_emi_detector_section(measurements))
    assert "Compliance margin" in section
    assert "EN 55022 Class B" in section
    assert "+19.0 dB" in section
    assert "over the limit" in section


# ── 10. Mode 3 — the `raw quasi-peak-sweep` CLI command ────────────────────


def test_quasi_peak_sweep_service(tmp_path, monkeypatch):
    monkeypatch.setattr(raw_service, "parse_raw", lambda _p: _make_cw_raw(1e6, 0.1))
    fake = tmp_path / "x.raw"
    fake.write_bytes(b"stub")
    report = raw_service.quasi_peak_sweep(str(fake), n_points=32)
    assert report.trace == "V(meas)"
    assert report.sweep.usable
    assert report.sweep.freq_hz.size == 32
    assert report.standard_name == "EN 55022 Class B"
    # A worst margin is computed for both detectors.
    assert report.quasi_peak_worst is not None
    assert report.average_worst is not None
    # The average limit is lower than the QP limit, so its margin is larger.
    assert report.average_worst.margin_db > report.quasi_peak_worst.margin_db


def test_cli_raw_quasi_peak_sweep_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(raw_service, "parse_raw", lambda _p: _make_cw_raw(1e6, 0.1))
    fake = tmp_path / "x.raw"
    fake.write_bytes(b"stub")
    rc = main(["raw", "quasi-peak-sweep", str(fake), "--points", "32"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Receiver-like sweep" in out
    assert "worst quasi-peak margin" in out
    assert "EN 55022 Class B" in out
