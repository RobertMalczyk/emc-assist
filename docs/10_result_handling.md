# Working with results

## Each analysis as a case

```text
case_001/
  input/
    original.asc                    # user schematic (optional)
    original.cir                    # user netlist fragment
    user_context.json               # incl. testbench_wiring{} + signals[]
    stackup.json                    # optional
  generated/
    parasitics.json                 # M0 calculator output
    user_circuit_fragment.cir       # M2.6.1 preprocessor copy (stripped + ground rename)
    testbench.cir                   # composer output (canonical, what LTspice runs)
    testbench.asc                   # M2.10.3 visualisation (open in LTspice; .include's .cir)
    LISN50UH.asy CABLE_PWR.asy ...  # M2.10.3 symbol bundle for testbench.asc
    parasitics_wiring.json          # M2.10 injection-plan audit
    signals.json                    # M2.10.1 resolved signal-map audit
    variants/<label>.cir            # M2 per-corner variants
    variants/variants.json          # variant manifest
    recommendations.json            # final recommendations (LLM or deterministic)
  results/
    variants/<label>.json           # per-variant .raw / .log metrics
    findings/<area>.json            # M2.9 per-agent findings (11 files)
    llm/<run-id>.jsonl              # M2.7 privacy log of every OpenAI call
    ltspice/                        # raw artefacts (.raw / .log) kept by the runner
  reports/
    report.md                       # Markdown report
    <project>_schematic.png         # M2.10.3 block-diagram visualisation (post-hoc)
  decisions/
    accepted_changes.json           # M2.12 (parked) — accepted variants
    rejected_changes.json           # M2.12 (parked) — rejected variants
  golden/                           # frozen snapshot (case_001 only) — refreshed deliberately
```

## Every result must contain

- project version,
- assumptions,
- input data,
- rules used,
- sources used,
- parasitic models,
- simulation configuration,
- metrics,
- recommendations,
- limitations,
- the path to the artefacts.

## Recommendations

Every recommendation is a JSON object conforming to `schemas/recommendation.schema.json`.

## Variant comparison

In a later version, every variant should have:

- an identifier,
- the list of changes,
- an estimated BOM cost,
- the impact on the result,
- side risks,
- a status: proposed / accepted / rejected / simulated.
