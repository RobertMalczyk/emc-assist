# ANALYSIS 01 — Data Structures (EMC/LTspice Assistant)

> `codebase-analysis` skill, Phase 2. Every structure is grounded in code with an
> inline `VERIFY` tag (`path:line`). Field lists reflect the dataclass at the
> cited line. Re-run after code changes (line numbers drift).

## Table of contents
- [1. Control: `CommandOptions`](#1-control-commandoptions)
- [2. Netlist: `ParsedNetlist` / `NetlistElement`](#2-netlist-parsednetlist--netlistelement)
- [3. Topology: `NetUsage` / `TopologyReport`](#3-topology-netusage--topologyreport)
- [4. Parasitics: `NetRLC` / `NetParasitics`](#4-parasitics-netrlc--netparasitics)
- [5. Testbench: `TestbenchPlan` / `Variant`](#5-testbench-testbenchplan--variant)
- [6. Raw results: `RawFile` / `RawHeader`](#6-raw-results-rawfile--rawheader)
- [7. Detectors: `CisprBand` / `DetectorSpectrum` / `DetectorReading`](#7-detectors-cisprband--detectorspectrum--detectorreading)
- [8. Limits: `ComplianceLimit` / `ComplianceStandard`](#8-limits-compliancelimit--compliancestandard)
- [9. Ranking: `RankedVariant`](#9-ranking-rankedvariant)
- [10. Agents: `AgentFinding` / `AgentContext`](#10-agents-agentfinding--agentcontext)
- [11. Verification report](#11-verification-report)

---

## 1. Control: `CommandOptions`

The typed parameter object threaded through every service function; the CLI
builds one from its argparse namespace, the UI builds one directly
[VERIFY: src/emc_assistant/service/options.py:21].

```
CommandOptions
├── user flags:   accept_wiring, no_wiring, accept_parasitics, no_parasitics,
│                 accept_signals, no_signals, parasitics_report_only,
│                 no_asc_export, mode, rank_metric, lower_is_better, html, pdf
├── LLM:          llm, llm_mode, llm_budget_usd, llm_model, llm_top_k
├── pre-resolved: resolved_wiring/strip/injection_plan/shunt_plan/series_plan/signals
└── test hooks:   stub_assistant, stub_embedder
```

- `_UNSET` sentinel marks a resolved-decision field a parent step has *not*
  pre-resolved, so the step resolves it itself
  [VERIFY: src/emc_assistant/service/options.py:17].
- `from_namespace` tolerantly maps a CLI namespace (each subcommand defines only
  a subset of flags)  [VERIFY: src/emc_assistant/service/options.py:53].
- `child(**overrides)` clones with overrides — how the pipeline threads
  pre-resolved decisions into each sub-step
  [VERIFY: src/emc_assistant/service/options.py:95].

---

## 2. Netlist: `ParsedNetlist` / `NetlistElement`

The parse result of a `.cir`  [VERIFY: src/emc_assistant/netlist/parser.py:41].

| Type | Fields | Evidence |
|---|---|---|
| `NetlistElement` | `refdes, kind, nodes, value, extra, raw` | [VERIFY: src/emc_assistant/netlist/parser.py:24] |
| `NetlistDirective` | `name, args, raw` | [VERIFY: src/emc_assistant/netlist/parser.py:34] |
| `ParsedNetlist` | `title, elements, directives, comments` | [VERIFY: src/emc_assistant/netlist/parser.py:41] |

`parse_cir` reads the `.cir` (encoding-tolerant) and splits each line into
element / directive / comment  [VERIFY: src/emc_assistant/netlist/parser.py:71];
`elements_by_kind` filters by first-letter kind
[VERIFY: src/emc_assistant/netlist/parser.py:47].

---

## 3. Topology: `NetUsage` / `TopologyReport`

`NetUsage` records how each net is used  [VERIFY: src/emc_assistant/netlist/topology.py:31]
(`name, element_count, element_kinds, components, is_v_source_positive,
is_ground, on_switch_element`). Two derived properties drive everything
downstream:
- `role` — `return` (ground) / `switching_node` (on S/Q/M) / `power_rail`
  (V+ terminal or ≥3 elements) / `signal`
  [VERIFY: src/emc_assistant/netlist/topology.py:50].
- `is_two_element` — only a clean 2-element net can take an unambiguous series
  splice  [VERIFY: src/emc_assistant/netlist/topology.py:68].

`TopologyReport` aggregates candidates (supply / return / switching), capacitor
terminal pairs, and an element-kind histogram, all derived from the parsed `.cir`
with no simulation  [VERIFY: src/emc_assistant/netlist/topology.py:78].

---

## 4. Parasitics: `NetRLC` / `NetParasitics`

- `TraceGeometry` — coarse per-role default geometry (length/width/oz/Z0/delay)
  [VERIFY: src/emc_assistant/parasitics/per_net.py:38]; the role table
  `DEFAULT_ROLE_GEOMETRY` keys power_rail / switching_node / return / signal
  [VERIFY: src/emc_assistant/parasitics/per_net.py:53].
- `NetRLC` — the R/L/C `ParasiticEstimate` triple for one net; `cited_sources()`
  dedups source IDs  [VERIFY: src/emc_assistant/parasitics/per_net.py:62].
- `NetParasitics` — `net, role, rlc, injectable, value_source, components, notes`;
  `to_dict()` emits typ + min/max bands + cited sources
  [VERIFY: src/emc_assistant/parasitics/per_net.py:79].
- `ParasiticValueSource` (ABC) is the pluggable estimator interface
  [VERIFY: src/emc_assistant/parasitics/per_net.py:111]; the shipped one is
  `RuleOfThumbValueSource` — role geometry → deterministic trace calculators,
  every value an `engineering_estimate`
  [VERIFY: src/emc_assistant/parasitics/per_net.py:127].

---

## 5. Testbench: `TestbenchPlan` / `Variant`

- `TestbenchWiring` — supply/return/probe wiring of the composed testbench
  [VERIFY: src/emc_assistant/testbench/composer.py:51].
- `TestbenchPlan` — the full plan rendered to `testbench.cir` by
  `compose_testbench_cir`  [VERIFY: src/emc_assistant/testbench/composer.py:87].
- `Variant` — one corner point: `label, description, overrides (id→min|typ|max),
  parasitics`; `short_id()` makes a path/SPICE-safe label
  [VERIFY: src/emc_assistant/testbench/variants.py:23].

---

## 6. Raw results: `RawFile` / `RawHeader`

- `RawVariable` — `index, name, kind`  [VERIFY: src/emc_assistant/results/raw_parser.py:40].
- `RawHeader` — title/date/plotname/flags/n_variables/n_points/offset/command +
  `is_binary/is_complex/is_fastaccess`
  [VERIFY: src/emc_assistant/results/raw_parser.py:46].
- `RawFile` — `header, axis, traces, traces_complex, path`; `variable_names`
  and `is_complex` are convenience properties
  [VERIFY: src/emc_assistant/results/raw_parser.py:63].

---

## 7. Detectors: `CisprBand` / `DetectorSpectrum` / `DetectorReading`

- `CisprBand` — band edges + CISPR 16-1-1 detector parameters (rbw, qp charge /
  discharge, meter constant)  [VERIFY: src/emc_assistant/results/detectors.py:100];
  the three band constants A / B / C-D
  [VERIFY: src/emc_assistant/results/detectors.py:122]; the conducted band of
  interest is Band B  [VERIFY: src/emc_assistant/results/detectors.py:127].
- `DetectorSpectrum` — per-frequency peak/QP/avg curves (dBµV) for one band,
  with `mode` and `receiver_filtered`
  [VERIFY: src/emc_assistant/results/detectors.py:131].
- `DetectorReading` — the band-max peak/QP/avg scalar reading; `to_dict()`
  serializes it  [VERIFY: src/emc_assistant/results/detectors.py:146].

---

## 8. Limits: `ComplianceLimit` / `ComplianceStandard`

- `LimitSegment` — one log-linear piece of a limit line `(f_low,dbuv_low)→
  (f_high,dbuv_high)`  [VERIFY: src/emc_assistant/results/limits.py:27].
- `ComplianceLimit` — a per-detector limit line (frozen) with `f_low`/`f_high`
  properties  [VERIFY: src/emc_assistant/results/limits.py:38].
- `ComplianceStandard` — a selectable standard = QP + average limit pair
  [VERIFY: src/emc_assistant/results/limits.py:56].

---

## 9. Ranking: `RankedVariant`

`RankedVariant` — `label, metric, delta, delta_pct, rank`
[VERIFY: src/emc_assistant/results/ranking.py:17]. `rank_variants` is pure
(works on dicts from `simulation_run.json`, no LTspice), sorts by `metric_key`,
and computes deltas vs the baseline entry
[VERIFY: src/emc_assistant/results/ranking.py:25].

---

## 10. Agents: `AgentFinding` / `AgentContext`

- `Finding` / `Risk` / `SimulationRequest` are the leaf records
  ([VERIFY: src/emc_assistant/agents/base.py:44],
  [VERIFY: src/emc_assistant/agents/base.py:56],
  [VERIFY: src/emc_assistant/agents/base.py:68]).
- `AgentFinding` — one agent's full output: `agent, area, confidence, findings,
  risks, recommendations, missing_data, simulation_requests, sources,
  limitations, llm_generated, injections`; mirrors
  `schemas/agent_finding.schema.json` and serializes via `to_schema_dict()`
  [VERIFY: src/emc_assistant/agents/base.py:85].
- `AgentContext` — the shared project context every agent receives (problem
  context, parasitics, sim metrics, snippets, topology, supply/return nets,
  signals, `retrieve_fn`)  [VERIFY: src/emc_assistant/agents/base.py:130].
- `AgentInputs` — the per-agent slice produced by `select_relevant`
  [VERIFY: src/emc_assistant/agents/base.py:166].

---

## 11. Verification report

| Structure | Evidence | Status |
|---|---|---|
| `CommandOptions` carries pre-resolved decisions | [VERIFY: src/emc_assistant/service/options.py:21] | ✓ |
| `NetUsage.role` classifies switch/rail/return/signal | [VERIFY: src/emc_assistant/netlist/topology.py:50] | ✓ |
| only 2-element nets are injectable | [VERIFY: src/emc_assistant/netlist/topology.py:68] | ✓ |
| `NetParasitics` keeps min/typ/max + sources | [VERIFY: src/emc_assistant/parasitics/per_net.py:79] | ✓ |
| `Variant.overrides` maps id→min/typ/max | [VERIFY: src/emc_assistant/testbench/variants.py:23] | ✓ |
| `DetectorReading` is band-max peak/QP/avg | [VERIFY: src/emc_assistant/results/detectors.py:146] | ✓ |
| `ComplianceStandard` = QP + avg limit pair | [VERIFY: src/emc_assistant/results/limits.py:56] | ✓ |
| `AgentFinding` mirrors the JSON schema | [VERIFY: src/emc_assistant/agents/base.py:85] | ✓ |

Next: **Phase 3** traces these structures through one variant run; **Phase 4**
analyses the detector + estimation algorithms that produce/consume them.
