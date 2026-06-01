# EMC pre-compliance report — Buck conducted EMI starter case

- **Project ID:** `case_001_buck_conducted_emi`
- **Version:** 0.1.0
- **Analysis scope:** `conducted_emi_dc_dc`
- **Generated at:** 2026-05-14T17:01:25Z

> **Disclaimer (pre-compliance):** This report is an *engineering aid* / *risk-reduction* artefact and does NOT constitute proof of EMC compliance. Simulation results do not replace measurements in an accredited laboratory. Every recommendation is an engineering hypothesis that requires verification.

## Project assumptions

| Field | Value |
| --- | --- |
| analysis_scope | conducted_emi_dc_dc |
| inputs.netlist_path | input/buck_demo.cir |
| inputs.schematic_path |  |
| privacy.allow_cloud_llm | False |
| ltspice.mode | dry-run |

## Estimated parasitics (min/typ/max)

| ID | Structure | Type | min | typ | max | confidence | sources |
| --- | --- | --- | --- | --- | --- | --- | --- |
| par-trace-R-20x1-1oz | trace | R | 0.00808 ohm | 0.0101 ohm | 0.0126 ohm | high | R001 |
| par-trace-L-iso-20x1 | trace | L | 8.33e-09 H | 1.67e-08 H | 2.5e-08 H | medium | R002 |
| par-trace-C-Z0-20-50 | trace | C | 1.88e-12 F | 2.68e-12 F | 3.48e-12 F | high | R004, R005 |
| par-poly-C-100mm2-h0.2 | plane_pair | C | 1.52e-11 F | 1.9e-11 F | 2.38e-11 F | medium | R012 |
| par-via-L-h1.6-d0.3 | via | L | 9.1e-10 H | 1.3e-09 H | 1.82e-09 H | medium | R010 |
| par-LC-fres-1.6665e-08-2.68e-12 | loop | frequency | 6.02e+08 Hz | 7.53e+08 Hz | 9.41e+08 Hz | high | R030 |

## Generated SPICE fragments

### LISN
```spice
* --- LISN subcircuit (LISN50UH) ---
* Educational 50 uH / 0.1 uF / 50 Ohm topology. Not a normative model.
* Ports: HV_IN DUT MEAS 0
.SUBCKT LISN50UH HV_IN DUT MEAS 0
L_lisn  HV_IN DUT   5e-05
C_couple DUT n_meas 1e-07
C_block  HV_IN 0     1e-06
R_meas   n_meas MEAS 50
R_bleed  MEAS 0      1000
.ENDS LISN50UH
```

### Power cable
```spice
* --- Cable subcircuit (CABLE_PWR) ---
* Length 1.0 m, LC ladder segments = 5 (L_seg=1.6e-07 H, C_seg=1e-11 F, R_seg=0.01 Ohm)
.SUBCKT CABLE_PWR IN OUT 0
R_seg1 IN n_c1 0.01
L_seg1 n_c1 n_c1o 1.6e-07
C_seg1 n_c1o 0 1e-11
R_seg2 n_c1o n_c2 0.01
L_seg2 n_c2 n_c2o 1.6e-07
C_seg2 n_c2o 0 1e-11
R_seg3 n_c2o n_c3 0.01
L_seg3 n_c3 n_c3o 1.6e-07
C_seg3 n_c3o 0 1e-11
R_seg4 n_c3o n_c4 0.01
L_seg4 n_c4 n_c4o 1.6e-07
C_seg4 n_c4o 0 1e-11
R_seg5 n_c4o n_c5 0.01
L_seg5 n_c5 OUT 1.6e-07
C_seg5 OUT 0 1e-11
.ENDS CABLE_PWR
```

## LTspice runner (local)

Local LTspice installation detected. Batch command:

```bash
C:\Users\<you>\AppData\Local\Programs\ADI\LTspice\LTspice.exe -b -Run C:\path\to\EMC-Assist\examples\case_001_buck_conducted_emi\input\buck_demo.cir
```

## Variants (min/typ/max sweep)

| label | description | deviations from typ |
| --- | --- | --- |
| baseline | All parasitics held at their typical value. | — |
| par-trace-R-20x1-1oz-min | Parasitic par-trace-R-20x1-1oz set to min; others at typ. | par-trace-R-20x1-1oz=min |
| par-trace-R-20x1-1oz-max | Parasitic par-trace-R-20x1-1oz set to max; others at typ. | par-trace-R-20x1-1oz=max |
| par-trace-L-iso-20x1-min | Parasitic par-trace-L-iso-20x1 set to min; others at typ. | par-trace-L-iso-20x1=min |
| par-trace-L-iso-20x1-max | Parasitic par-trace-L-iso-20x1 set to max; others at typ. | par-trace-L-iso-20x1=max |
| par-trace-C-Z0-20-50-min | Parasitic par-trace-C-Z0-20-50 set to min; others at typ. | par-trace-C-Z0-20-50=min |
| par-trace-C-Z0-20-50-max | Parasitic par-trace-C-Z0-20-50 set to max; others at typ. | par-trace-C-Z0-20-50=max |
| par-poly-C-100mm2-h0.2-min | Parasitic par-poly-C-100mm2-h0.2 set to min; others at typ. | par-poly-C-100mm2-h0.2=min |
| par-poly-C-100mm2-h0.2-max | Parasitic par-poly-C-100mm2-h0.2 set to max; others at typ. | par-poly-C-100mm2-h0.2=max |
| par-via-L-h1.6-d0.3-min | Parasitic par-via-L-h1.6-d0.3 set to min; others at typ. | par-via-L-h1.6-d0.3=min |
| par-via-L-h1.6-d0.3-max | Parasitic par-via-L-h1.6-d0.3 set to max; others at typ. | par-via-L-h1.6-d0.3=max |

## Measurements (from `.raw` / `simulation_run.json`)

| variant | v_meas_max | v_meas_min | v_meas_peak | v_meas_peak_to_peak | v_meas_rms | v_meas_n_points | axis_min | axis_max | v_meas_spectrum_nyquist_hz | v_meas_spectrum_sample_count | v_meas_band_peak_dbuv_150000_30000000 | tnom | temp | vpeak | vmin | vp2p | vrms | dm_peak | dm_p2p | dm_rms | cm_peak | cm_p2p | cm_rms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 1.824 | -2.214 | 2.214 | 4.038 | 0.413 | 8.002e+04 | 0 | 0.005 | 5e+06 | 4.5e+04 | 66.2 | 27 | 27 | 1.824 | -2.214 | 4.038 | 0.4131 | 3.649 | 8.076 | 0.8262 | 2.314e-07 | 2.914e-07 | 2.203e-10 |
| par-poly-C-100mm2-h0.2-max | 1.824 | -2.214 | 2.214 | 4.038 | 0.413 | 8.002e+04 | 0 | 0.005 | 5e+06 | 4.5e+04 | 66.2 | 27 | 27 | 1.824 | -2.214 | 4.038 | 0.4131 | 3.649 | 8.076 | 0.8262 | 2.314e-07 | 2.914e-07 | 2.203e-10 |
| par-poly-C-100mm2-h0.2-min | 1.824 | -2.214 | 2.214 | 4.038 | 0.413 | 8.002e+04 | 0 | 0.005 | 5e+06 | 4.5e+04 | 66.2 | 27 | 27 | 1.824 | -2.214 | 4.038 | 0.4131 | 3.649 | 8.076 | 0.8262 | 2.314e-07 | 2.914e-07 | 2.203e-10 |
| par-trace-C-Z0-20-50-max | 1.824 | -2.214 | 2.214 | 4.038 | 0.413 | 8.002e+04 | 0 | 0.005 | 5e+06 | 4.5e+04 | 66.2 | 27 | 27 | 1.824 | -2.214 | 4.038 | 0.4131 | 3.649 | 8.076 | 0.8262 | 2.314e-07 | 2.914e-07 | 2.203e-10 |
| par-trace-C-Z0-20-50-min | 1.824 | -2.214 | 2.214 | 4.038 | 0.413 | 8.002e+04 | 0 | 0.005 | 5e+06 | 4.5e+04 | 66.2 | 27 | 27 | 1.824 | -2.214 | 4.038 | 0.4131 | 3.649 | 8.076 | 0.8262 | 2.314e-07 | 2.914e-07 | 2.203e-10 |
| par-trace-L-iso-20x1-max | 1.824 | -2.214 | 2.214 | 4.038 | 0.413 | 8.002e+04 | 0 | 0.005 | 5e+06 | 4.5e+04 | 66.2 | 27 | 27 | 1.824 | -2.214 | 4.038 | 0.4131 | 3.649 | 8.076 | 0.8262 | 2.314e-07 | 2.914e-07 | 2.203e-10 |
| par-trace-L-iso-20x1-min | 1.824 | -2.214 | 2.214 | 4.038 | 0.413 | 8.002e+04 | 0 | 0.005 | 5e+06 | 4.5e+04 | 66.2 | 27 | 27 | 1.824 | -2.214 | 4.038 | 0.4131 | 3.649 | 8.076 | 0.8262 | 2.314e-07 | 2.914e-07 | 2.203e-10 |
| par-trace-R-20x1-1oz-max | 1.824 | -2.214 | 2.214 | 4.038 | 0.413 | 8.002e+04 | 0 | 0.005 | 5e+06 | 4.5e+04 | 66.2 | 27 | 27 | 1.824 | -2.214 | 4.038 | 0.4131 | 3.649 | 8.076 | 0.8262 | 2.314e-07 | 2.914e-07 | 2.203e-10 |
| par-trace-R-20x1-1oz-min | 1.824 | -2.214 | 2.214 | 4.038 | 0.413 | 8.002e+04 | 0 | 0.005 | 5e+06 | 4.5e+04 | 66.2 | 27 | 27 | 1.824 | -2.214 | 4.038 | 0.4131 | 3.649 | 8.076 | 0.8262 | 2.314e-07 | 2.914e-07 | 2.203e-10 |
| par-via-L-h1.6-d0.3-max | 1.824 | -2.214 | 2.214 | 4.038 | 0.413 | 8.002e+04 | 0 | 0.005 | 5e+06 | 4.5e+04 | 66.2 | 27 | 27 | 1.824 | -2.214 | 4.038 | 0.4131 | 3.649 | 8.076 | 0.8262 | 2.314e-07 | 2.914e-07 | 2.203e-10 |
| par-via-L-h1.6-d0.3-min | 1.824 | -2.214 | 2.214 | 4.038 | 0.413 | 8.002e+04 | 0 | 0.005 | 5e+06 | 4.5e+04 | 66.2 | 27 | 27 | 1.824 | -2.214 | 4.038 | 0.4131 | 3.649 | 8.076 | 0.8262 | 2.314e-07 | 2.914e-07 | 2.203e-10 |

## Variant ranking by `v_meas_peak` (lower is better)

| rank | label | v_meas_peak | Δ vs baseline | Δ% |
| --- | --- | --- | --- | --- |
| 1 | baseline | 2.21 | +0 | +0.0% |
| 2 | par-poly-C-100mm2-h0.2-max | 2.21 | +0 | +0.0% |
| 3 | par-poly-C-100mm2-h0.2-min | 2.21 | +0 | +0.0% |
| 4 | par-trace-C-Z0-20-50-max | 2.21 | +0 | +0.0% |
| 5 | par-trace-C-Z0-20-50-min | 2.21 | +0 | +0.0% |
| 6 | par-trace-L-iso-20x1-max | 2.21 | +0 | +0.0% |
| 7 | par-trace-L-iso-20x1-min | 2.21 | +0 | +0.0% |
| 8 | par-trace-R-20x1-1oz-max | 2.21 | +0 | +0.0% |
| 9 | par-trace-R-20x1-1oz-min | 2.21 | +0 | +0.0% |
| 10 | par-via-L-h1.6-d0.3-max | 2.21 | +0 | +0.0% |
| 11 | par-via-L-h1.6-d0.3-min | 2.21 | +0 | +0.0% |

## Recommendations

### REC-001 — input_damping (severity: **medium**, confidence: 0.60)

**Problem:** The input network can form a lightly-damped LC that converts switching energy into conducted emission peaks near the switching harmonics.

**Evidence:**
- R-002: guidance on conducted EMI mitigation for power converters (recommend using damping/filtering at input nodes).
- engineering_estimate: measured simulation band peak (v_meas_band_peak_dbuv_150000_30000000 = 66.20 dBμV) indicates significant conducted energy in the 150 kHz–30 MHz band that input damping may reduce.

**Proposed change:**
- `type`: add_damping
- `description`: Add a small RC damping branch at the converter input (across or in series with input capacitor banks) to damp high-frequency resonances between input inductance/traces and input capacitance.
- `values`: {'R': '0.5-3.3 ohm', 'C': '100 nF - 1 uF'}

**User action:** Simulate the input network with the suggested RC values (sweep R and C) and compare the 150 kHz–30 MHz conducted spectrum; verify changes in a lab LISN measurement.

**Limitations:**
- No layout available — the effectiveness depends on actual trace/plane inductances and cable routing.
- Component ESR/ESL curves were not provided and will affect optimal R/C choices.

**Sources:** R-002

### REC-002 — common_mode_filter (severity: **high**, confidence: 0.50)

**Problem:** Common‑mode currents generated by the switching node can couple onto input/output cabling and show up as large conducted peaks.

**Evidence:**
- SRC-028: note that inductance for differential currents can be low while common‑mode impedance remains high (useful property of CM chokes to block CM currents).
- R-010: guidance about cables and board traces indicates that cable routing and insertion of CM impedance is effective at reducing conducted currents on wiring harnesses.

**Proposed change:**
- `type`: add_filter
- `description`: Add a dedicated input common‑mode choke (or increase CM impedance) ahead of the converter input to raise common‑mode impedance seen by cable currents while preserving differential power transfer.
- `values`: {'Lcm': '10-200 uH (start coarse sweep)', 'I_rated': '>= 2 A DC (with margin)'}

**User action:** Model a CM choke in the input path (sweep Lcm across the given range) and measure conducted CM spectrum; validate choke nonlinearities and saturation with expected DC current.

**Limitations:**
- No layout available — coupling to nearby conductors and cable routing will change CM impedance in practice.
- Datasheet nonlinearity and inter-winding capacitance of candidate chokes were not available and must be considered during selection.

**Sources:** R-010

### REC-003 — switch_node_snubber (severity: **medium**, confidence: 0.55)

**Problem:** Switch-node ringing and high dv/dt at the switching node can generate high-frequency harmonics that increase conducted emission peaks.

**Evidence:**
- R-001: general schematic/EMC guidance for switching converters recommends local damping at switching nodes (snubbers/suppression networks) to reduce high‑frequency content.
- R-002: conducted EMI guidance supports damping of switching-node resonances to lower emissions coupled to the input.

**Proposed change:**
- `type`: add_damping
- `description`: Add a snubber on the switch node (RC or RCD style) to damp switching-edge ringing and reduce high-frequency spectral content.
- `values`: {'R': '10-100 ohm', 'C': '100 pF - 10 nF'}

**User action:** Simulate the switch-node waveform and spectral density while sweeping snubber R and C over the given ranges to find the best trade-off between damping, switching losses, and conducted spectrum.

**Limitations:**
- No layout available — snubber placement relative to the switch node critically affects performance.
- Switching-device parasitics and datasheet capacitances were not provided; these will affect snubber sizing.

**Sources:** R-001, R-002

### REC-004 — layout (severity: **high**, confidence: 0.40)

**Problem:** Large switching loop area and poor return routing will increase loop inductance and conducted/coupled emissions.

**Evidence:**
- R-010: guidance on cabling and traces emphasises minimizing switching loop area and keeping return paths close to reduce loop inductance and emissions.
- R-008: stack-up recommendations indicate that a proper plane pair and controlled return reduce loop inductance and provide a low-impedance return at high frequencies.

**Proposed change:**
- `type`: layout_change
- `description`: Re-route power and return traces to minimize the high‑di/dt switching loop (place input caps close to the switch, use a dedicated return plane, and keep hot loop area as small as possible).

**User action:** When a PCB layout is available, re-run EMC-coupled simulations with the updated loop geometry and re-evaluate conducted spectrum; verify in hardware with controlled cabling.

**Limitations:**
- No layout available — this recommendation is layout-dependent and cannot be fully validated without board geometry.
- Stack-up was provided but component placement/trace widths/heights are unknown, so predicted loop inductances are estimates.

**Sources:** R-010, R-008

### REC-005 — parametric_sweep (severity: **info**, confidence: 0.65)

**Problem:** Sensitivity of the conducted spectrum to parasitic variations is unknown; single-point sims may miss worst-case emission scenarios.

**Evidence:**
- engineering_estimate: parasitic trace/plane/via values are provided in the analysis (trace L/C and plane pair C) and should be swept to find worst-case peaks.
- R-002: general conducted-EMI guidance suggests varying parasitics and component tolerances during pre-compliance simulation to find sensitive resonances.

**Proposed change:**
- `type`: sweep
- `description`: Perform parametric sweeps of key parasitics (trace inductance, plane-pair capacitance, via inductance) and damping/filter values to identify worst-case spectral peaks and effective mitigations.
- `values`: {'trace/L': '8.33e-9 - 2.5e-8 H', 'trace/C': '1.88e-12 - 3.48e-12 F', 'plane_pair/C': '1.52e-11 - 2.38e-11 F', 'via/L': '9.1e-10 - 1.82e-9 H', 'series_R_sweep': '0 - 5 ohm'}

**User action:** Run the recommended sweeps in LTspice (or equivalent) and plot the 150 kHz–30 MHz conducted spectrum for each case to locate sensitive resonances and quantify mitigation benefit.

**Limitations:**
- No layout available — parasitic ranges are estimates and actual board geometry may fall outside these ranges.
- Component parasitic models (ESL/ESR frequency dependence) were not supplied and should be added for higher-fidelity sweeps.

**Sources:** R-002

### REC-006 — testbench_measurement (severity: **medium**, confidence: 0.60)

**Problem:** Simulation-only results need verification with a LISN-style testbench and replicated cable conditions to evaluate real conducted emissions.

**Evidence:**
- R-002: recommends lab-style conducted emission test setups (LISN/cable conditions) for verification after pre-compliance simulation.
- engineering_estimate: current simulated band peak (66.20 dBμV) motivates adding a LISN model to the testbench to compare simulated vs measured behavior.

**Proposed change:**
- `type`: include_in_testbench
- `description`: Include a LISN or equivalent input impedance model and representative cable models in the simulation testbench and plan lab LISN measurements with the same cable harness topology.

**User action:** Add a LISN input model and cable impedance into the simulation, rerun spectral scans 150 kHz–30 MHz, and then perform equivalent hardware LISN measurements for correlation.

**Limitations:**
- No layout available — LISN/cable coupling to the board depends on connector placement and harness routing.
- Accurate cable/LISN models and measurement fixtures are required for meaningful correlation.

**Sources:** R-002


## Limitations and risks

- No certified EMI-receiver detector model (peak/avg/QP).
- Parasitic values are first-order estimates only.
- EMC compliance cannot be confirmed without physical measurement.

> **Disclaimer (pre-compliance):** This report is an *engineering aid* / *risk-reduction* artefact and does NOT constitute proof of EMC compliance. Simulation results do not replace measurements in an accredited laboratory. Every recommendation is an engineering hypothesis that requires verification.
