# Quasi-peak detector — conceptual design note

> **Status: concept only.** This note defines *how quasi-peak detection
> should be handled* in EMC-Assist. It proposes no code, no schemas, no
> CLI commands, no tests, and no pipeline changes. It is a design
> reference for later, scoped implementation work.

## 1. Purpose

EMC-Assist is a local-first CLI tool for LTspice-assisted **conducted-EMI
pre-compliance** analysis of DC/DC converters. It builds LISN / cable /
parasitic-aware testbenches, runs LTspice locally, parses `.raw` / `.log`,
ranks variants, and generates reports. Every result is a pre-compliance
diagnostic.

Conducted-emission limits are written against an **EMI receiver with a
quasi-peak detector**. A peak-only metric therefore does not speak the
same language as the limit. This note defines, conceptually, how
EMC-Assist should treat quasi-peak (QP) detection so that:

- the tool produces a QP-like figure useful for **variant comparison and
  engineering insight**, and
- the tool never overstates what that figure means — it is a
  **CISPR-like pre-compliance diagnostic**, not a certified measurement.

## 2. Background — what quasi-peak detection is

The quasi-peak detector originated as an indicator of the *subjective
annoyance* of impulsive radio interference to a listener: sharp,
infrequent pulses are less annoying than the same-amplitude pulses
arriving rapidly. The detector was designed to imitate that dependence on
pulse repetition rate, and it is now the reference detector for most
conducted-emission limits.

A QP detector is a **weighted envelope detector**: it charges quickly
toward the input and discharges slowly away from it, followed by a meter
(indicator) stage that smooths the result. Its parameters — resolution
bandwidth, charge time, discharge time, meter time — are defined per
frequency band in **CISPR 16-1-1 / EN 55016-1-1 ed. 3**. The constants in
section 6 of this note have been checked against that standard.

## 3. Why quasi-peak matters for conducted EMI

A switching converter does not emit a clean tone. It emits a **repetitive,
impulsive** disturbance — switching edges and their harmonics, plus
intermittent events such as a hot-swap inrush. Conducted-emission limits
are specified largely as **quasi-peak limits** (and sometimes average).

Consequently:

- A **peak** metric is conservative — it always reads at or above QP and
  can over-predict risk.
- An **average** metric reads below QP and can under-predict risk.
- The **quasi-peak** figure is the one the limit line was drawn against,
  so it is the most decision-relevant single number for conducted EMI.

For EMC-Assist, a QP-like figure lets the engineer compare design
variants on the axis the standard actually uses.

## 4. Why quasi-peak differs from peak and average

For the same receiver-filtered input the three detectors are ordered:

```
average  ≤  quasi-peak  ≤  peak
```

- **Peak** — the maximum of the envelope. Independent of repetition rate.
- **Average** — the envelope smoothed by a meter-time-constant low-pass.
  For a steady emission this equals the mean of the envelope; for sparse
  / intermittent emissions it reads well below the peak. See section 10
  for how EMC-Assist models it.
- **Quasi-peak** — sits between them, and its position depends on the
  **pulse repetition rate**: frequent pulses charge the detector close to
  the peak; rare pulses or a single event let it discharge, so QP drops
  well below peak.

Calibration corollaries (from CISPR 16-1-1, confirmed against the
reference document):

- For an **unmodulated sine wave** all detectors read (after calibration)
  the same value: `peak ≈ quasi-peak ≈ average`.
- For **pulses** the ordering is strict: `peak > quasi-peak > average`.

## 5. Why quasi-peak is a receiver chain, not a simple max/decay

A QP reading is **not** "take a maximum and let it decay." It is the
output of an **EMI-receiver chain**, and every stage shapes the result:

```
input  →  preselection / attenuator
       →  IF / resolution-bandwidth filter   (e.g. 9 kHz for Band B)
       →  envelope detector
       →  quasi-peak weighting (charge / discharge)
       →  meter / indicator (its own time constant)
       →  indicated level
```

Two stages are essential and easy to overlook:

- **The resolution-bandwidth (RBW) filter.** A receiver measures the
  emission *at one frequency, within a defined bandwidth*. The RBW filter
  is what makes "the level at frequency f" a meaningful quantity and what
  limits how much broadband energy reaches the detector. Without it, a
  charge/discharge operation is being applied to the *entire broadband
  waveform at once*, not to a per-frequency emission.
- **The meter / indicator stage.** After the charge/discharge weighting, a
  meter with its own time constant (160 ms for Bands A/B) further smooths
  the output. The indicated QP value is the meter output, not the raw
  detector output.

So a faithful QP estimate is a *cascade model*; a bare max-with-decay is
only a loose caricature of one stage of it.

## 6. CISPR-like detector constants

Detector parameter groups per frequency band (CISPR 16-1-1 /
EN 55016-1-1 ed. 3). These are detector *parameters* — not limit lines and
not normative pass/fail data.

| Band | Frequency range | RBW (−6 dB) | Charge | Discharge | Meter |
|---|---|---|---|---|---|
| A | 9 kHz – 150 kHz | 200 Hz | 45 ms | 500 ms | 160 ms |
| **B** *(default)* | **150 kHz – 30 MHz** | **9 kHz** | **1 ms** | **160 ms** | **160 ms** |
| C / D | 30 MHz – 1 GHz | 120 kHz | 1 ms | 550 ms | 100 ms |

**Band B is the default conceptual band for EMC-Assist**, because the
conducted-EMI scope for DC/DC converters is the 150 kHz – 30 MHz range.
Bands A and C/D are listed for context; they are not the working band of
the current MVP.

## 7. Detector modes

EMC-Assist should treat quasi-peak as **three conceptual modes**, of
increasing fidelity. Only Mode 1 is in scope for near-term thinking;
Modes 2 and 3 are future.

### Mode 1 — `time_domain_diagnostic`

A quasi-peak-like weighting applied **directly to a selected LTspice
waveform** (for example `V(MEAS)`), with **no receiver bandwidth filter**.

- Purpose: a fast, repeatable figure for **comparing variants** processed
  identically, and for engineering insight.
- It is **not** equivalent to a CISPR receiver QP measurement, because no
  receiver bandwidth was applied — see section 8.

### Mode 2 — `receiver_like_single_frequency` *(future)*

The waveform is first passed through a **receiver-bandwidth filter**
centered at a chosen frequency, then envelope detection and quasi-peak
detection are applied.

- Purpose: a result that is **closer to EMI-receiver behaviour** at one
  frequency of interest.
- Still a pre-compliance estimate unless independently validated.

### Mode 3 — `receiver_like_sweep` *(implemented — the canonical verdict detector; see §16)*

A frequency **sweep over the conducted-emission band**, conceptually
similar to an EMI-receiver scan — Mode 2 repeated across many centre
frequencies to produce a spectrum of QP values.

> **Current state (2026-05-24).** Mode 3 is implemented (`receiver_sweep`)
> and is now the **canonical detector** for the conducted-EMI verdict —
> see §16. Mode 1 remains available as a gap-free diagnostic; Mode 2
> (single frequency) is also implemented (`receiver_quasi_peak`).

## 8. Why direct QP on a raw switching waveform is only a diagnostic metric

Applying a charge/discharge weighting straight to `V(MEAS)` (Mode 1)
yields a number, but that number is a **diagnostic metric**, not a
receiver prediction, because:

- **No receiver bandwidth was applied.** The weighting sees the whole
  broadband waveform, so the result is dominated by the largest
  time-domain excursions (switching edges) regardless of *which*
  frequency they belong to. It is not "QP at a frequency."
- **It is not absolutely calibrated** to the CISPR impulse-area
  calibration that anchors a real receiver's reading.
- Its value therefore only carries meaning **relative to another result
  produced by the identical processing** — i.e. variant A vs variant B.

This makes Mode 1 genuinely useful (variant ranking, trend detection,
"did this filter help?") while being honestly **not** a substitute for a
receiver measurement.

## 9. Conceptual signal chains

**Diagnostic mode (Mode 1):**

```
LTspice waveform
  → selected trace
  → envelope or absolute-value interpretation
  → quasi-peak-like weighting
  → diagnostic metric
  → report
```

**Receiver-like mode (Mode 2):**

```
LTspice waveform
  → receiver bandwidth filter, e.g. 9 kHz RBW for Band B
  → envelope detector
  → quasi-peak detector
  → meter model / indication
  → dBµV result
  → report
```

## 10. The average detector

The **average detector** is the second detector most conducted-emission
limits are written against, alongside quasi-peak (see section 3). CISPR
16-1-1 / EN 55016-1-1 defines it as indicating the **average value of the
envelope**; the band's **meter (indicator) time constant** (160 ms for
Bands A/B — section 6) sets how that average is formed.

EMC-Assist models it as the meter-time-constant counterpart of the
quasi-peak chain — the same stages, with the charge/discharge weighting
replaced by a single linear low-pass:

```
LTspice waveform
  → receiver bandwidth filter (Mode 2/3) or STFT bin (Mode 1)
  → envelope detector
  → linear low-pass with the meter time constant   (the averaging stage)
  → max-hold indication
  → dBµV result
  → report
```

It runs in the same three modes as quasi-peak (section 7): Mode 1 over
the short-time spectrum, Modes 2 and 3 over the receiver-bandwidth
envelope.

**The simulation-length problem, and the mean-seed.** The meter constant
(160 ms for Band B) is far longer than a feasible transient simulation
(often only a few milliseconds). A low-pass starting from zero would
never charge over so short a run and would grossly **under-read** —
reporting near-zero for a real emission. EMC-Assist therefore **seeds
the averaging low-pass with the mean of the envelope**:

- For a **steady emission** the meter simply stays at that mean — which
  *is* the correct steady-state average-detector reading. A run shorter
  than the meter constant degrades gracefully to the mean instead of
  collapsing toward zero.
- For a **longer run that captures an intermittent burst**, the meter
  rises above the whole-window mean toward the burst's local average,
  and the max-hold records that rise — so an intermittent event is not
  diluted away by the surrounding quiet time.

This keeps the `average ≤ quasi-peak ≤ peak` ordering (section 4) and
makes the average reading meaningful on the short runs the tool actually
produces. As with quasi-peak, the meter time constant is **not** applied
as a literal 160 ms filter on the raw run — the mean-seeded low-pass is
the pre-compliance estimate of it.

The average reading is compared against the standard's **average limit
line** (EN 55022 Class B by default, norm-selectable) — the companion of
the quasi-peak limit. It remains a **pre-compliance diagnostic** under
all the section 13 disclaimers, not a certified average-detector
measurement.

## 11. What a more receiver-like quasi-peak estimate would require

To move from Mode 1 toward Mode 2/3, conceptually the following are
needed (no implementation proposed here):

- A **receiver-bandwidth filter** (9 kHz for Band B) centred at the
  frequency of interest.
- An **envelope detector** following that filter.
- The **quasi-peak charge/discharge weighting** with the Band-B constants.
- A **meter / indicator model** with its own time constant.
- A **calibration assumption** (e.g. an impulse-area or CW reference) so a
  dBµV figure is meaningful rather than purely relative.
- Awareness of a **fundamental simulation-length limit**: a transient
  simulation is far shorter than the discharge (160 ms) and meter
  (160 ms) constants and far shorter than a real receiver's per-frequency
  dwell. Low pulse-repetition-rate behaviour therefore cannot be
  faithfully reproduced from a short simulation; any QP estimate is
  conservative and pre-compliance by construction.

## 12. What reports should show

Report output must make the detector's nature explicit. Every quasi-peak
result should be accompanied by metadata so a reader can see exactly what
was computed and under which assumptions.

Recommended report metadata (conceptual field list, not a schema):

- detector type
- detector mode (`time_domain_diagnostic` / `receiver_like_single_frequency`
  / `receiver_like_sweep`)
- band
- RBW
- charge time
- discharge time
- meter time
- selected trace
- calibration assumption
- result in volts
- result in dBµV (if applicable)
- whether receiver filtering was applied
- limitations

A quasi-peak figure shown **without** this metadata — in particular
without the detector mode and the "receiver filtering applied?" flag —
should be considered incomplete.

## 13. Limitations and disclaimers

The following statements must be present wherever quasi-peak results
appear.

EMC-Assist quasi-peak results:

- are **CISPR-like pre-compliance diagnostics**;
- are **not a substitute for a certified EMI receiver**;
- are **not proof of EMC compliance**;
- should be used for **variant comparison and engineering insight**.

**When no receiver bandwidth filter is used (Mode 1)**, the report must
state:

> "This is a time-domain diagnostic quasi-peak-like metric applied
> directly to the selected waveform. It is not equivalent to a CISPR
> receiver quasi-peak measurement because no receiver bandwidth filter
> was applied."

**General disclaimer** (all modes):

> "Quasi-peak results are CISPR-like pre-compliance diagnostics only.
> They are not a substitute for a certified EMI receiver or accredited
> EMC laboratory measurement."

## 14. Verification principles

These are principles for checking a future implementation — *what correct
behaviour looks like*, not how to implement or test it:

- **Step response** should match the **charge-time** behaviour — the
  detector rises toward a newly-applied level on the charge time scale.
- **Discharge response** should match the **discharge-time** behaviour —
  the detector falls away from a removed input on the (slower) discharge
  time scale.
- A **continuous-wave input** should produce **similar peak and
  quasi-peak readings after calibration** (sine wave: PK ≈ QP ≈ AV).
- The quasi-peak reading should **increase with pulse repetition rate** —
  faster pulse trains read higher, approaching peak; sparse pulses read
  lower, approaching average.
- The quasi-peak reading should **not exceed a correctly calibrated peak**
  for the same receiver-filtered input (`QP ≤ peak`).
- The **average detector** should read the **mean of the envelope** for a
  steady emission and stay **below quasi-peak** for an intermittent one
  (`average ≤ quasi-peak ≤ peak`).
- **Band B constants** (section 6) should be the **default** for the
  150 kHz – 30 MHz conducted-EMI range.

## 15. Scope and non-goals

This note is **conceptual only**. It deliberately does not:

- implement code, Python APIs, or file-level designs;
- modify or propose schemas;
- add CLI commands or options;
- add or change tests;
- change the existing pipeline;
- implement receiver-bandwidth filters;
- implement a certified CISPR receiver.

It defines the concept so that any later, separately-scoped
implementation of quasi-peak detection in EMC-Assist starts from a clear,
honest, standard-aware design — and never lets a pre-compliance diagnostic
be mistaken for a compliance result.

## 16. Canonical verdict detector (implemented 2026-05-24)

Historically two code paths computed the quasi-peak margin **differently**
and disagreed by ~40 dB: the verdict pill / corner table used **Mode 1 with
`skip_fraction = 0.1`** (read `~-26 dB`, "within limit"), while the spectrum
chart used **Mode 3 with `skip_fraction = 0.0`** (read `~+13 dB`, "over
limit") — for the same trace. A user could see a green "within" verdict above
a chart that visibly breached the limit.

**Fix.** All consumer-facing quasi-peak / average readings — the verdict pill,
the corner-variant table (`results/metrics.py`), the UI spectrum chart
(`service/raw.py`), and the report's margin text + plot
(`reports/detector_plot.py`) — now go through **one** helper,
`results.detectors.conducted_emi_spectrum`, governed by the `VERDICT_*`
constants. They agree by construction.

**Canonical choice (user decision).** **Mode 3** (receiver-like sweep, the
realistic per-frequency RBW emulation), **`skip_fraction = 0.0`** (full
window), `n_points = 128`.

**Alternatives kept for future selectability** (see
`tasks/detector_selectable.md`):

- **mode** — Mode 1 (`time_domain_diagnostic`: gap-free, no RBW, reads lower)
  vs Mode 3 (canonical).
- **skip_fraction** — `0.0` (canonical) vs `>0` (steady-state-only). *Caveat:*
  on case_003, raising skip *raised* the Mode-3 reading — non-intuitive; root-
  cause before exposing it.
- **n_points** — Mode 3's coarse log sweep under-reads **narrow tones between
  swept points** (step > 9 kHz RBW above ~211 kHz), an under-reporting risk for
  switching harmonics. Gap-free coverage needs thousands of points (infeasible
  per variant), so this is a real accuracy caveat to weigh when exposing the
  control.
