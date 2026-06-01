# Test case 001 — buck conducted EMI

## Goal

The first test case for the MVP pipeline.

## Circuit

- DC source,
- buck converter or a simplified switching-noise source model,
- input capacitor,
- input cable,
- LISN,
- optional DM filter,
- PCB parasitics.

## Minimum input data

```json
{
  "input_voltage": "24 V",
  "switching_frequency": "400 kHz",
  "load_current": "2 A",
  "cable_length_m": 1.0,
  "pcb_layers": 4,
  "trace_length_mm": 20,
  "trace_width_mm": 1.0,
  "copper_oz": 1,
  "dielectric_height_mm": 0.2
}
```

## Expected artefacts

- `generated/testbench.cir`,
- `generated/parasitics.cir`,
- `results/run_001/report.md`,
- `results/run_001/recommendations.json`.

## Expected recommendations

- flag the missing layout data as a limitation,
- propose a sweep over trace / via parasitics,
- propose verifying input-filter damping,
- propose an ESR / ESL model for the input capacitor,
- a note that the result is not an EMC certification.
