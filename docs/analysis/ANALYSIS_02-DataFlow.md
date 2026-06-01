# ANALYSIS 02 — Data Flow (EMC/LTspice Assistant)

> `codebase-analysis` skill, Phase 3. Traces data through one full pipeline run,
> every hop carrying an inline `VERIFY` tag (`path:line`). Re-run after code
> changes (line numbers drift).

## Table of contents
- [1. End-to-end flow](#1-end-to-end-flow)
- [2. Stage-by-stage trace](#2-stage-by-stage-trace)
- [3. Transformation table](#3-transformation-table)
- [4. Failure / fallback paths](#4-failure--fallback-paths)
- [5. Verification report](#5-verification-report)

---

## 1. End-to-end flow

```
user .cir/.asc + user_context.json
        │
        ▼  run_pipeline()  [parasitics → testbench → variants → simulate → report]
┌───────────────────────────────────────────────────────────────────────┐
│ resolve wiring/signals/parasitics  ─▶  compose testbench.cir            │
│        │                                                                │
│        ▼  enumerate corner variants (baseline + per-parasitic min/max)  │
│   variant_<id>.cir  ──▶  local LTspice  ──▶  variant_<id>.raw + .log    │
│        │                                                                │
│        ▼  raw parse → metrics → CISPR detectors → limit margins         │
│   simulation_run.json (per-variant metrics)                            │
│        │                                                                │
│        ▼  rank_variants  +  run_agents (opt-in)  ──▶  report.md/html/pdf │
└───────────────────────────────────────────────────────────────────────┘
```

`run_pipeline` is the single orchestration entry; its docstring states the stage
order  [VERIFY: src/emc_assistant/service/pipeline.py:78]. A cooperative cancel is
checked between stages  [VERIFY: src/emc_assistant/service/pipeline.py:59].

---

## 2. Stage-by-stage trace

**Stage A — resolve + estimate.** The pipeline resolves wiring
[VERIFY: src/emc_assistant/service/resolve.py:312], signals
[VERIFY: src/emc_assistant/service/resolve.py:391], and the parasitic injection
plan  [VERIFY: src/emc_assistant/service/resolve.py:493], then estimates per-net
R/L/C from the topology  [VERIFY: src/emc_assistant/parasitics/per_net.py:153].
The user fragment is spliced into a *generated* fragment, never the original
[VERIFY: src/emc_assistant/service/resolve.py:715].

**Stage B — compose testbench.** `compose_testbench` assembles the plan
[VERIFY: src/emc_assistant/service/testbench.py:170] and
`compose_testbench_cir` renders `testbench.cir` (LISN + cable + splices)
[VERIFY: src/emc_assistant/testbench/composer.py:197].

**Stage C — enumerate variants.** `compose_variants`
[VERIFY: src/emc_assistant/service/testbench.py:334] calls
`enumerate_corner_variants` → `baseline` (all-typ) + one `min` and one `max`
per R/L/C parasitic  [VERIFY: src/emc_assistant/testbench/variants.py:36].

**Stage D — simulate.** `run_variants` runs each variant `.cir`
[VERIFY: src/emc_assistant/service/simulate.py:78]; each call invokes local
LTspice via `run_simulation`  [VERIFY: src/emc_assistant/ltspice/runner.py:121],
producing a `SimulationResult` (exit code, log path, raw path)
[VERIFY: src/emc_assistant/ltspice/runner.py:81]. A single (non-corner) run uses
`run_testbench`  [VERIFY: src/emc_assistant/service/simulate.py:26].

**Stage E — parse + detect + margin.** The `.raw` parses into a `RawFile`
[VERIFY: src/emc_assistant/results/raw_parser.py:63]; the chosen waveform is
resampled to a uniform grid  [VERIFY: src/emc_assistant/results/detectors.py:182],
then the QP meter  [VERIFY: src/emc_assistant/results/detectors.py:214] and
average meter  [VERIFY: src/emc_assistant/results/detectors.py:232] produce
readings, compared to the configured limit via `worst_margin`
[VERIFY: src/emc_assistant/results/limits.py:118].

**Stage F — rank + agents + report.** `rank_variants` orders the corner set by
the metric  [VERIFY: src/emc_assistant/results/ranking.py:25];
`generate_report` assembles the document
[VERIFY: src/emc_assistant/service/report.py:258], pulling the results view
[VERIFY: src/emc_assistant/service/report.py:156], rendering detector-vs-limit
plots  [VERIFY: src/emc_assistant/service/report.py:216], and (opt-in) fanning
out to the 11 agents  [VERIFY: src/emc_assistant/service/report.py:391].

---

## 3. Transformation table

| # | Input | Output | Where | Evidence |
|---|---|---|---|---|
| A | `.cir` + context | injection plan + per-net `NetParasitics` | resolve + estimate | [VERIFY: src/emc_assistant/parasitics/per_net.py:153] |
| B | plan | `testbench.cir` | composer | [VERIFY: src/emc_assistant/testbench/composer.py:197] |
| C | parasitics | `Variant[]` (baseline + corners) | variants | [VERIFY: src/emc_assistant/testbench/variants.py:36] |
| D | `variant.cir` | `.raw` + `.log` + `SimulationResult` | ltspice | [VERIFY: src/emc_assistant/ltspice/runner.py:121] |
| E | `.raw` waveform | QP/avg readings + worst margin | detectors + limits | [VERIFY: src/emc_assistant/results/limits.py:118] |
| F | per-variant metrics | `RankedVariant[]` + report | ranking + report | [VERIFY: src/emc_assistant/service/report.py:258] |

---

## 4. Failure / fallback paths

- **No LLM / key:** agents take the deterministic fallback so every area still
  produces a finding  [VERIFY: src/emc_assistant/agents/base.py:510]; gating is
  decided up front  [VERIFY: src/emc_assistant/service/resolve.py:148].
- **Malformed LLM JSON:** the agent falls back to deterministic and appends a
  limitation note  [VERIFY: src/emc_assistant/agents/base.py:525].
- **Cancellation:** `_check_cancel` raises `RunCancelled` between stages
  [VERIFY: src/emc_assistant/service/pipeline.py:59].
- **Variant missing a metric:** `rank_variants` skips non-comparable entries
  [VERIFY: src/emc_assistant/results/ranking.py:37].

---

## 5. Verification report

| Claim | Evidence | Status |
|---|---|---|
| Pipeline order parasitics→…→report | [VERIFY: src/emc_assistant/service/pipeline.py:78] | ✓ |
| Variants = baseline + per-R/L/C min/max | [VERIFY: src/emc_assistant/testbench/variants.py:36] | ✓ |
| Each variant invokes local LTspice | [VERIFY: src/emc_assistant/ltspice/runner.py:121] | ✓ |
| Worst margin computed vs configured limit | [VERIFY: src/emc_assistant/results/limits.py:118] | ✓ |
| Agents fan out during report generation | [VERIFY: src/emc_assistant/service/report.py:391] | ✓ |
| Deterministic fallback when no LLM | [VERIFY: src/emc_assistant/agents/base.py:510] | ✓ |

Next: **Phase 4** opens the detector meter algorithms and the per-net estimator.
