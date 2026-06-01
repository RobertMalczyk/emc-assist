"""Structured simulation / solver settings (M2.13).

The composer's simulation control used to be a single ``.tran`` string
(``user_context.simulation.tran_directive``). :class:`SimulationSettings`
replaces it with structured fields — transient stop time, max timestep,
recording start, integration method, extra ``.options`` — that the
composer turns into ``.tran`` and ``.options`` directives. The raw
``tran_directive`` string is kept as an advanced override and, when
present, wins over the structured fields.

This is the backend for the solver-settings UI panel (see
``docs/design/ui_design_brief.md`` → "Simulation / solver settings").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


_SPICE_SUFFIX: dict[str, float] = {
    "t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3,
    "m": 1e-3, "u": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15,
}
_NUM_RE = re.compile(r"^\s*([+-]?[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)\s*([a-zµ]*)\s*$")

_ALLOWED_METHODS = frozenset({"", "trap", "gear"})


def spice_to_float(value: str) -> float:
    """Parse a SPICE-style number (``5m``, ``100n``, ``1meg``, ``2.5e-3``).

    Classic SPICE suffixes; ``m`` is milli and ``meg`` is mega. Raises
    ``ValueError`` on anything unparseable.
    """
    m = _NUM_RE.match(str(value))
    if not m:
        raise ValueError(f"not a SPICE number: {value!r}")
    mant, suffix = m.group(1), m.group(2).lower()
    base = float(mant)
    if not suffix:
        return base
    # `meg` must be checked before the single-letter suffixes.
    if suffix.startswith("meg"):
        return base * 1e6
    mult = _SPICE_SUFFIX.get(suffix[0])
    if mult is None:
        raise ValueError(f"unknown SPICE suffix in {value!r}")
    return base * mult


@dataclass
class SimulationSettings:
    """Structured transient + solver settings for the composer.

    All time fields are SPICE-number strings (``"5m"``, ``"100n"``).
    ``raw_tran_directive``, when set, is used verbatim and the
    structured transient fields are ignored.
    """

    stop_time: str = "5m"
    max_timestep: str = "100n"
    record_start: str = "0"
    startup: bool = False
    integration_method: str = ""  # "" = LTspice default (trap) | "trap" | "gear"
    options: dict[str, str] = field(default_factory=dict)
    raw_tran_directive: str = ""

    def __post_init__(self) -> None:
        self.integration_method = (self.integration_method or "").strip().lower()
        if self.integration_method not in _ALLOWED_METHODS:
            raise ValueError(
                f"integration_method must be one of {sorted(_ALLOWED_METHODS)}; "
                f"got {self.integration_method!r} "
                "(use raw_tran_directive / a raw .options for anything else)"
            )
        if self.raw_tran_directive.strip():
            return  # structured transient fields are not used — skip their checks
        stop = spice_to_float(self.stop_time)
        step = spice_to_float(self.max_timestep)
        start = spice_to_float(self.record_start)
        if stop <= 0:
            raise ValueError(f"stop_time must be positive; got {self.stop_time!r}")
        if step <= 0 or step > stop:
            raise ValueError(
                f"max_timestep must be > 0 and <= stop_time; got "
                f"{self.max_timestep!r} vs {self.stop_time!r}"
            )
        if start < 0 or start >= stop:
            raise ValueError(
                f"record_start must be >= 0 and < stop_time; got "
                f"{self.record_start!r}"
            )

    @classmethod
    def from_user_context(cls, user_context: dict) -> "SimulationSettings":
        """Build from ``user_context.simulation`` (missing keys → defaults)."""
        sim = (user_context or {}).get("simulation")
        if not isinstance(sim, dict):
            return cls()
        opts_raw = sim.get("options")
        options = (
            {str(k): str(v) for k, v in opts_raw.items()}
            if isinstance(opts_raw, dict)
            else {}
        )
        # A non-string tran_directive is ignored (treated as absent).
        raw = sim.get("tran_directive")
        raw_tran = raw.strip() if isinstance(raw, str) else ""
        return cls(
            stop_time=str(sim.get("stop_time", "5m")),
            max_timestep=str(sim.get("max_timestep", "100n")),
            record_start=str(sim.get("record_start", "0")),
            startup=bool(sim.get("startup", False)),
            integration_method=str(sim.get("integration_method", "")),
            options=options,
            raw_tran_directive=raw_tran,
        )

    def tran_line(self) -> str:
        """The ``.tran`` directive — the raw override, or built from fields."""
        if self.raw_tran_directive.strip():
            return self.raw_tran_directive.strip()
        line = f".tran 0 {self.stop_time} {self.record_start} {self.max_timestep}"
        if self.startup:
            line += " startup"
        return line

    def options_line(self) -> str:
        """The ``.options`` directive, or ``""`` when nothing is set."""
        pairs: list[str] = []
        if self.integration_method:
            pairs.append(f"method={self.integration_method}")
        for k, v in self.options.items():
            pairs.append(f"{k}={v}")
        return (".options " + " ".join(pairs)) if pairs else ""

    def effective_times(self) -> tuple[float | None, float | None, float | None]:
        """``(stop_s, max_timestep_s, record_start_s)`` the run will actually
        use — parsed from the raw ``.tran`` directive when one is set, else
        from the structured fields. Any value that can't be determined from a
        raw directive (e.g. no explicit ``dTmax``) comes back ``None``.

        Raw form parsed: ``.tran Tstep Tstop [Tstart [dTmax]] [modifiers]``
        (the composer emits ``.tran 0 <stop> <record_start> <max_timestep>``).
        """
        if not self.raw_tran_directive.strip():
            return (
                spice_to_float(self.stop_time),
                spice_to_float(self.max_timestep),
                spice_to_float(self.record_start),
            )
        nums: list[float] = []
        for tok in self.raw_tran_directive.strip().split()[1:]:  # skip ".tran"
            try:
                nums.append(spice_to_float(tok))
            except ValueError:
                pass  # skip non-numeric modifiers like "startup" / "uic"
        stop = nums[1] if len(nums) >= 2 else None
        record_start = nums[2] if len(nums) >= 3 else 0.0
        max_timestep = nums[3] if len(nums) >= 4 else None
        return (stop, max_timestep, record_start)


# ---- simulation-setup integrity assessment (deterministic) -----------------

# CISPR conducted band B (the MVP's default analysis band).
_BAND_MIN_HZ = 150e3
_BAND_MAX_HZ = 30e6


@dataclass
class SimCheck:
    """One assessment finding about the simulation window / timestep."""

    id: str
    severity: str          # "high" | "medium" | "low" | "ok"
    message: str
    recommendation: str = ""


@dataclass
class SimAssessment:
    """Deterministic verdict on whether the ``.tran`` settings can capture
    the phenomena that matter for conducted EMI (band coverage + edges +
    frequency resolution), with concrete recommended values."""

    ok: bool               # no high-severity issues
    checks: list[SimCheck]
    stop_s: float | None
    max_timestep_s: float | None
    record_start_s: float | None
    recommended_max_timestep_s: float | None
    recommended_stop_time_s: float | None
    recommended_record_start_s: float | None


def _fmt_s(s: float | None) -> str:
    if s is None:
        return "—"
    for suf, mul in (("s", 1.0), ("ms", 1e-3), ("µs", 1e-6), ("ns", 1e-9), ("ps", 1e-12)):
        if abs(s) >= mul:
            return f"{s / mul:.3g} {suf}"
    return f"{s:.3g} s"


def _fmt_hz(h: float | None) -> str:
    if h is None:
        return "—"
    for suf, mul in (("GHz", 1e9), ("MHz", 1e6), ("kHz", 1e3)):
        if abs(h) >= mul:
            return f"{h / mul:.3g} {suf}"
    return f"{h:.3g} Hz"


def assess_simulation_setup(
    settings: SimulationSettings,
    *,
    switching_frequency_hz: float | None = None,
    band_max_hz: float = _BAND_MAX_HZ,
    band_min_hz: float = _BAND_MIN_HZ,
    edge_rise_time_s: float | None = None,
    oversample: int = 10,
    min_cycles: int = 20,
) -> SimAssessment:
    """Check the ``.tran`` window/timestep against what conducted-EMI
    analysis needs, deterministically (no LLM):

    * **Nyquist / band** — ``max_timestep`` must resolve up to ``band_max_hz``
      (≤ ``1/(2·f)``), and ideally oversample (≤ ``1/(oversample·f)``).
    * **Edge resolution** — if a device rise time is known, ``max_timestep``
      must resolve the switching edge (≤ ``t_rise/10``); the edge bandwidth
      ``0.35/t_rise`` is the real HF-EMI driver.
    * **Frequency resolution / cycles** — for a periodic converter the window
      must span enough switching cycles and give a fine enough FFT bin.
    * **Startup** — a periodic run should skip the turn-on transient.

    Returns a :class:`SimAssessment`; ``ok`` is False if any check is high.
    """
    stop, step, start = settings.effective_times()
    start = start if start is not None else 0.0
    checks: list[SimCheck] = []

    nyq_step = 1.0 / (2.0 * band_max_hz)
    rec_step_band = 1.0 / (oversample * band_max_hz)
    rec_step = rec_step_band

    # --- Δt vs band -----------------------------------------------------------
    if step is None:
        checks.append(SimCheck(
            "timestep_unset", "medium",
            "No explicit max timestep — LTspice chooses its own step, which can "
            "silently under-resolve the band and the switching edges.",
            f"Set a max timestep ≤ {_fmt_s(rec_step_band)} (oversamples {_fmt_hz(band_max_hz)}).",
        ))
    elif step > nyq_step:
        checks.append(SimCheck(
            "timestep_aliases_band", "high",
            f"Max timestep {_fmt_s(step)} → Nyquist {_fmt_hz(1.0 / (2.0 * step))}, "
            f"below the {_fmt_hz(band_max_hz)} band edge: the upper band aliases.",
            f"Reduce max timestep to ≤ {_fmt_s(rec_step_band)}.",
        ))
    elif step > rec_step_band:
        checks.append(SimCheck(
            "timestep_undersamples", "low",
            f"Max timestep {_fmt_s(step)} meets Nyquist but only "
            f"{1.0 / (step * band_max_hz):.1f}× oversamples {_fmt_hz(band_max_hz)}.",
            f"For a cleaner FFT use ≤ {_fmt_s(rec_step_band)} ({oversample}× oversample).",
        ))

    # --- Δt vs switching edge -------------------------------------------------
    if edge_rise_time_s and edge_rise_time_s > 0:
        edge_bw = 0.35 / edge_rise_time_s
        rec_step_edge = edge_rise_time_s / 10.0
        rec_step = min(rec_step, rec_step_edge)
        if step is None or step > rec_step_edge:
            checks.append(SimCheck(
                "timestep_misses_edge", "high",
                f"Switching edge ~{_fmt_s(edge_rise_time_s)} (bandwidth "
                f"~{_fmt_hz(edge_bw)}) needs max timestep ≤ {_fmt_s(rec_step_edge)} "
                f"to capture the gate transition; current {_fmt_s(step)} misses edge content.",
                f"Reduce max timestep to ≤ {_fmt_s(rec_step_edge)}.",
            ))
        if edge_bw > band_max_hz:
            checks.append(SimCheck(
                "edge_above_band", "low",
                f"Edge bandwidth ~{_fmt_hz(edge_bw)} exceeds the {_fmt_hz(band_max_hz)} "
                "conducted band — significant content sits above the band (radiated regime).",
            ))

    # --- frequency resolution / cycles (periodic converters only) ------------
    rec_stop = stop
    if switching_frequency_hz and switching_frequency_hz > 0 and stop is not None:
        usable = max(stop - start, 0.0)
        period = 1.0 / switching_frequency_hz
        cycles = usable * switching_frequency_hz
        bin_hz = (1.0 / usable) if usable > 0 else float("inf")
        bin_target = band_min_hz / 10.0     # resolve well below the band edge
        rec_usable = max(min_cycles * period, 1.0 / bin_target)
        rec_stop = start + rec_usable
        if cycles < min_cycles:
            checks.append(SimCheck(
                "too_few_cycles", "medium",
                f"Recorded window spans only {cycles:.0f} switching cycles "
                f"(f_sw {_fmt_hz(switching_frequency_hz)}); too few for a stable spectrum.",
                f"Extend stop time to ≥ {_fmt_s(rec_stop)} (≥ {min_cycles} cycles).",
            ))
        elif bin_hz > bin_target:
            checks.append(SimCheck(
                "coarse_bin", "low",
                f"FFT bin {_fmt_hz(bin_hz)} is coarse near the {_fmt_hz(band_min_hz)} "
                "band edge.",
                f"Extend the recorded window to ≥ {_fmt_s(rec_usable)} for ≤ {_fmt_hz(bin_target)} bins.",
            ))
        if start <= 0.0:
            checks.append(SimCheck(
                "startup_included", "low",
                "record_start = 0: the turn-on transient is in the FFT and can "
                "dominate the spectrum of a periodic converter.",
                "Set record_start past the converter's settling time.",
            ))

    if not checks:
        checks.append(SimCheck("ok", "ok", "Simulation window and timestep look adequate for the band."))
    ok = not any(c.severity == "high" for c in checks)
    return SimAssessment(
        ok=ok, checks=checks,
        stop_s=stop, max_timestep_s=step, record_start_s=start,
        recommended_max_timestep_s=rec_step,
        recommended_stop_time_s=rec_stop,
        recommended_record_start_s=start,
    )
