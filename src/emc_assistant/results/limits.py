"""CISPR-like compliance limit lines — pre-compliance margin reference.

A *limit line* is the dBµV envelope a product's conducted emissions must
stay under, per an emission standard (CISPR 11 / 22 / 32 / 25 / …). This
module holds the limit **data** and the margin computation. It ships
**EN 55022 Class B** as the default and is structured so other standards
can be added — a standard is just a named, piecewise (frequency, dBµV)
curve per detector.

These are reference values, attributed to their standard — **not a
compliance verdict**. A reading inside the limit is not proof of
compliance; a reading above it is not proof of failure. The engineer is
responsible for selecting the standard, class and edition that apply.
No standard's text is reproduced — only the widely-published numeric
limit values.

Pure data + math.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LimitSegment:
    """One piecewise segment of a limit line: the limit varies
    log-linearly in frequency from ``(f_low, dbuv_low)`` to
    ``(f_high, dbuv_high)``. A flat segment has equal endpoints."""

    f_low: float
    f_high: float
    dbuv_low: float
    dbuv_high: float


@dataclass(frozen=True)
class ComplianceLimit:
    """A limit line for one detector (``quasi_peak`` or ``average``)."""

    standard: str
    equipment_class: str
    detector: str
    segments: tuple[LimitSegment, ...]

    @property
    def f_low(self) -> float:
        return self.segments[0].f_low

    @property
    def f_high(self) -> float:
        return self.segments[-1].f_high


@dataclass(frozen=True)
class ComplianceStandard:
    """A selectable compliance standard — a quasi-peak + average limit pair."""

    id: str
    name: str
    description: str
    quasi_peak: ComplianceLimit
    average: ComplianceLimit


def limit_dbuv(limit: ComplianceLimit, freq_hz: float) -> float | None:
    """The limit level (dBµV) at ``freq_hz`` — log-linear interpolation
    within the matching segment. ``None`` when the frequency is outside
    the limit's defined range. Segment boundaries are half-open (the
    higher-frequency segment owns a shared edge), so a step in the limit
    resolves to the upper band."""
    if freq_hz <= 0:
        return None
    n = len(limit.segments)
    for i, seg in enumerate(limit.segments):
        last = i == n - 1
        inside = (
            seg.f_low <= freq_hz <= seg.f_high
            if last
            else seg.f_low <= freq_hz < seg.f_high
        )
        if not inside:
            continue
        if seg.dbuv_low == seg.dbuv_high or seg.f_high == seg.f_low:
            return seg.dbuv_low
        frac = (math.log10(freq_hz) - math.log10(seg.f_low)) / (
            math.log10(seg.f_high) - math.log10(seg.f_low)
        )
        return seg.dbuv_low + frac * (seg.dbuv_high - seg.dbuv_low)
    return None


def margin_db(
    reading_dbuv: float, limit: ComplianceLimit, freq_hz: float
) -> float | None:
    """``reading − limit`` at ``freq_hz``, in dB. Negative = headroom
    below the limit; positive = above it. ``None`` when the frequency is
    outside the limit's range. A margin is a pre-compliance estimate, not
    a pass/fail verdict."""
    lim = limit_dbuv(limit, freq_hz)
    if lim is None:
        return None
    return reading_dbuv - lim


@dataclass(frozen=True)
class WorstMargin:
    """The worst (largest ``reading − limit``) point of a per-frequency
    detector reading against a limit line, and where it occurs."""

    margin_db: float
    freq_hz: float
    reading_dbuv: float
    limit_dbuv: float


def worst_margin(freqs_hz, readings_dbuv, limit: ComplianceLimit) -> WorstMargin | None:
    """Scan a per-frequency detector reading against ``limit`` and return
    the **worst** margin — the frequency where ``reading − limit`` is
    largest (most over the limit, or least headroom). ``None`` when no
    frequency falls inside the limit's range."""
    worst: WorstMargin | None = None
    for f, reading in zip(freqs_hz, readings_dbuv):
        lim = limit_dbuv(limit, float(f))
        if lim is None:
            continue
        m = float(reading) - lim
        if worst is None or m > worst.margin_db:
            worst = WorstMargin(
                margin_db=m, freq_hz=float(f),
                reading_dbuv=float(reading), limit_dbuv=lim,
            )
    return worst


# ── Standards ──────────────────────────────────────────────────────────────
#
# EN 55022 (CISPR 22) Class B — conducted emission, mains terminal
# disturbance voltage, 150 kHz – 30 MHz. Widely-published reference
# values; EN 55022 was superseded by EN 55032, with the same conducted
# limits. Add further standards (Class A, EN 55032, CISPR 25, …) here.

_EN55022_B_QP = ComplianceLimit(
    standard="EN 55022",
    equipment_class="B",
    detector="quasi_peak",
    segments=(
        LimitSegment(0.15e6, 0.50e6, 66.0, 56.0),  # log-linear 66 → 56
        LimitSegment(0.50e6, 5.0e6, 56.0, 56.0),   # flat 56
        LimitSegment(5.0e6, 30.0e6, 60.0, 60.0),   # flat 60 (step up at 5 MHz)
    ),
)

_EN55022_B_AVG = ComplianceLimit(
    standard="EN 55022",
    equipment_class="B",
    detector="average",
    segments=(
        LimitSegment(0.15e6, 0.50e6, 56.0, 46.0),  # log-linear 56 → 46
        LimitSegment(0.50e6, 5.0e6, 46.0, 46.0),   # flat 46
        LimitSegment(5.0e6, 30.0e6, 50.0, 50.0),   # flat 50 (step up at 5 MHz)
    ),
)

EN55022_CLASS_B = ComplianceStandard(
    id="en55022_class_b",
    name="EN 55022 Class B",
    description=(
        "ITE conducted emission, mains terminal disturbance voltage, "
        "150 kHz – 30 MHz (quasi-peak + average). Reference values; "
        "EN 55022 is superseded by EN 55032 with the same conducted limits."
    ),
    quasi_peak=_EN55022_B_QP,
    average=_EN55022_B_AVG,
)

# The registry of selectable standards (the norm can be changed).
STANDARDS: dict[str, ComplianceStandard] = {
    EN55022_CLASS_B.id: EN55022_CLASS_B,
}

# The default conducted-EMI standard for the MVP (DC/DC, residential/ITE).
DEFAULT_STANDARD_ID = EN55022_CLASS_B.id


def get_standard(standard_id: str | None) -> ComplianceStandard | None:
    """Look up a compliance standard by id. ``None``/empty → the default
    (EN 55022 Class B). Returns ``None`` for an unknown id."""
    return STANDARDS.get(standard_id or DEFAULT_STANDARD_ID)
