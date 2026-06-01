# ANALYSIS 03 — Algorithm Deep Dive (EMC/LTspice Assistant)

> `codebase-analysis` skill, Phase 4. Each algorithm is analysed against the
> actual implementation with an inline `VERIFY` tag (`path:line`). Code excerpts
> are quoted from the cited lines. Re-run after code changes (line numbers drift).

## Table of contents
- [1. Quasi-peak meter](#1-quasi-peak-meter)
- [2. Average meter](#2-average-meter)
- [3. Uniform resampling](#3-uniform-resampling)
- [4. Limit interpolation & margin](#4-limit-interpolation--margin)
- [5. Per-net parasitic estimation](#5-per-net-parasitic-estimation)
- [6. Corner-variant enumeration](#6-corner-variant-enumeration)
- [7. Variant ranking](#7-variant-ranking)
- [8. Verification report](#8-verification-report)

---

## 1. Quasi-peak meter

`_qp_meter` runs the CISPR charge/discharge meter over an STFT envelope and
returns the per-bin running maximum  [VERIFY: src/emc_assistant/results/detectors.py:214].

```python
alpha_c = 1.0 - math.exp(-dt_frame / charge_s)     # fast attack
alpha_d = 1.0 - math.exp(-dt_frame / discharge_s)  # slow release
...
charging = x > meter
meter = meter + np.where(charging, (x - meter) * alpha_c, (x - meter) * alpha_d)
meter_max = np.maximum(meter_max, meter)
```

- The two time constants become exponential smoothing coefficients
  ([VERIFY: src/emc_assistant/results/detectors.py:220],
  [VERIFY: src/emc_assistant/results/detectors.py:221]). Because `charge_s` ≪
  `discharge_s` (Band B: 1 ms vs 160 ms
  [VERIFY: src/emc_assistant/results/detectors.py:123]), `alpha_c` ≫ `alpha_d`,
  so the meter rises quickly on peaks and decays slowly — the defining QP
  weighting (bursts weighted toward their peak).
- Per frame: pick attack vs release by whether the input exceeds the meter
  [VERIFY: src/emc_assistant/results/detectors.py:226], integrate
  [VERIFY: src/emc_assistant/results/detectors.py:227], and max-hold the
  indicator  [VERIFY: src/emc_assistant/results/detectors.py:228].

This is a meter-time-constant model, not a calibrated receiver — exactly the
honest framing the report uses.

---

## 2. Average meter

`_avg_meter` is a single linear τ_meter low-pass with max-hold
[VERIFY: src/emc_assistant/results/detectors.py:232].

```python
alpha = 1.0 - math.exp(-dt_frame / tau)
meter = envelopes.mean(axis=1).astype(np.float64)   # seed with the mean
...
meter = meter + (envelopes[:, frame] - meter) * alpha
meter_max = np.maximum(meter_max, meter)
```

- One smoothing coefficient from the meter constant
  [VERIFY: src/emc_assistant/results/detectors.py:241].
- **Key design choice:** each bin's meter is *seeded with that bin's mean*
  [VERIFY: src/emc_assistant/results/detectors.py:242], so a simulation far
  shorter than τ degrades gracefully to the steady-state mean rather than
  under-reading from a cold (zero) start — a real correctness fix for short
  `.tran` windows.

---

## 3. Uniform resampling

Both meters need a uniform time grid; `_resample` provides it
[VERIFY: src/emc_assistant/results/detectors.py:182].

- It uses the **last monotonic run** of the axis, because LTspice `.step` raw
  axes reset (the parser concatenates steps)
  [VERIFY: src/emc_assistant/results/detectors.py:189].
- It skips a configurable startup fraction, derives `dt` from the median sample
  spacing, and caps the point count (~4M) to bound memory
  [VERIFY: src/emc_assistant/results/detectors.py:208], returning `None` for
  degenerate traces. Volts→dBµV conversion floors tiny values before the log
  [VERIFY: src/emc_assistant/results/detectors.py:175].

---

## 4. Limit interpolation & margin

`limit_dbuv` interpolates the piecewise limit line **log-linearly in frequency**
within the matching segment  [VERIFY: src/emc_assistant/results/limits.py:67]:

```python
frac = (math.log10(freq_hz) - math.log10(seg.f_low)) /
       (math.log10(seg.f_high) - math.log10(seg.f_low))
return seg.dbuv_low + frac * (seg.dbuv_high - seg.dbuv_low)
```
[VERIFY: src/emc_assistant/results/limits.py:87]. Segment boundaries are
half-open so a step resolves to the upper band. `margin_db` is reading − limit
[VERIFY: src/emc_assistant/results/limits.py:94]; `worst_margin` scans the
spectrum for the least-headroom frequency
[VERIFY: src/emc_assistant/results/limits.py:118].

---

## 5. Per-net parasitic estimation

`RuleOfThumbValueSource.estimate` maps a net's role → default geometry → three
deterministic trace calculators (R, L, C)
[VERIFY: src/emc_assistant/parasitics/per_net.py:142].
`estimate_all_nets` walks every net in the topology
[VERIFY: src/emc_assistant/parasitics/per_net.py:153], and applies the
**injectability rule** — a net is injectable only if it is a clean 2-element net
*and* not ground:

```python
injectable = nu.is_two_element and not nu.is_ground
```
[VERIFY: src/emc_assistant/parasitics/per_net.py:169]. Ground/return nets are
still estimated (return-path parasitics / ground bounce) but never spliced; 3+-
element star/bus nets are estimated but flagged layout-dependent.

---

## 6. Corner-variant enumeration

`enumerate_corner_variants` builds the sweep
[VERIFY: src/emc_assistant/testbench/variants.py:36]:
1. a `baseline` variant with every parasitic at `typ`
   [VERIFY: src/emc_assistant/testbench/variants.py:48];
2. for each R/L/C parasitic, one `min` and one `max` variant with that parasitic
   moved and all others held at typ
   [VERIFY: src/emc_assistant/testbench/variants.py:55].

So for *N* swept parasitics the set is `1 + 2N` variants — a one-at-a-time
sensitivity sweep, not a full factorial (cheap, isolates each parasitic's effect).

---

## 7. Variant ranking

`rank_variants` is deterministic and operates on dicts (no LTspice)
[VERIFY: src/emc_assistant/results/ranking.py:25]:
- keep only variants that carry `metric_key`
  [VERIFY: src/emc_assistant/results/ranking.py:39];
- sort by the metric (`reverse = not lower_is_better`)
  [VERIFY: src/emc_assistant/results/ranking.py:53];
- compute `delta` / `delta_pct` against the `baseline` entry
  [VERIFY: src/emc_assistant/results/ranking.py:60].

---

## 8. Verification report

| Algorithm | Key property | Evidence | Status |
|---|---|---|---|
| QP meter | fast charge / slow discharge + max-hold | [VERIFY: src/emc_assistant/results/detectors.py:214] | ✓ |
| Avg meter | mean-seeded τ low-pass | [VERIFY: src/emc_assistant/results/detectors.py:242] | ✓ |
| Resample | last-monotonic-run handling | [VERIFY: src/emc_assistant/results/detectors.py:189] | ✓ |
| Limit interp | log-linear in frequency | [VERIFY: src/emc_assistant/results/limits.py:87] | ✓ |
| Injectability | 2-element AND not ground | [VERIFY: src/emc_assistant/parasitics/per_net.py:169] | ✓ |
| Variant set | 1 + 2N one-at-a-time | [VERIFY: src/emc_assistant/testbench/variants.py:55] | ✓ |
| Ranking | metric sort + baseline delta | [VERIFY: src/emc_assistant/results/ranking.py:53] | ✓ |

This completes Phases 1–4 (overview → structures → flow → algorithms).
