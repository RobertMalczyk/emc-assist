# ANALYSIS 00 — System Overview (EMC/LTspice Assistant)

> Generated with the `codebase-analysis` skill methodology (Phase 1 — global
> exploration). Every claim carries an inline `VERIFY` tag (`path:line`) pointing at the
> exact code it is grounded in. No claim without code evidence.
>
> Scope: the Python package `src/emc_assistant/`. Verified against the repo at
> generation time; re-run after code changes (line numbers drift).

## Table of contents
- [1. System introduction](#1-system-introduction)
- [2. Core modules](#2-core-modules)
- [3. Architecture](#3-architecture)
- [4. Module relationships](#4-module-relationships)
- [5. Data-flow overview](#5-data-flow-overview)
- [6. Key technologies](#6-key-technologies)
- [7. Code-structure mapping](#7-code-structure-mapping)
- [8. Verification report](#8-verification-report)

---

## 1. System introduction

### 1.1 What is it?

EMC/LTspice Assistant is a **local, deterministic** tool for **conducted-EMI
pre-compliance** of DC/DC converters. It imports a SPICE schematic, estimates
PCB parasitics, composes a CISPR-style testbench (LISN + cable + parasitic
injection), runs corner sweeps in a **locally installed** LTspice, parses the
results, applies CISPR-like detector metrics against a configured EN 55022
Class B reference curve, and (optionally) runs an LLM agent panel to explain the
result.

It ships **two front-ends over one service core**:
- a CLI — `emc-assistant` → `emc_assistant.cli:main`  [VERIFY: pyproject.toml:38]
- a desktop UI — `emc-assistant-ui` → `emc_assistant.ui.app:main`  [VERIFY: pyproject.toml:39]

Both call the same service layer; `cli.py` is a thin argparse adapter over it
(parser assembled in `build_parser`)  [VERIFY: src/emc_assistant/cli.py:616].

### 1.2 Core principles (load-bearing, enforced in code)

- **Deterministic core first; LLM is opt-in.** The LLM only runs when enabled
  and a key resolves  [VERIFY: src/emc_assistant/service/resolve.py:148], and
  the assistant is constructed lazily  [VERIFY: src/emc_assistant/service/resolve.py:118].
- **LTspice is local, never bundled/hosted.** Runs are invoked against a local
  install  [VERIFY: src/emc_assistant/ltspice/runner.py:121].
- **The user schematic is never mutated.** Parasitic splices are produced into a
  generated fragment, not the user's `.cir`
  [VERIFY: src/emc_assistant/service/resolve.py:715].
- **Min/typ/max, not single values.** Parasitic corners are enumerated as a
  sweep  [VERIFY: src/emc_assistant/testbench/variants.py:36].
- **Cancellable pipeline.** A cooperative cancel is checked between stages
  [VERIFY: src/emc_assistant/service/pipeline.py:59].

### 1.3 Application scenarios

- Pre-compliance risk-reduction for a DC/DC converter before lab time.
- "What changes the conducted band?" parasitic corner exploration.
- LLM-assisted diagnostic narrative + per-area specialist findings.

---

## 2. Core modules

### 2.1 Module list

| Module (package) | Responsibility | Key file:line |
|---|---|---|
| `cli` | argparse front-end over the service layer | [VERIFY: src/emc_assistant/cli.py:616] |
| `service` | application core (one function per use-case) | [VERIFY: src/emc_assistant/service/pipeline.py:78] |
| `netlist` | parse `.cir`, classify topology, splice fragments | [VERIFY: src/emc_assistant/netlist/parser.py:71] |
| `parasitics` | per-net R/L/C estimation (min/typ/max) | [VERIFY: src/emc_assistant/parasitics/per_net.py:153] |
| `testbench` | compose LISN+cable+injection `.cir`, enumerate variants | [VERIFY: src/emc_assistant/testbench/composer.py:197] |
| `ltspice` | discover + run local LTspice, collect log/raw/exit | [VERIFY: src/emc_assistant/ltspice/runner.py:121] |
| `results` | parse `.raw`, metrics, CISPR-like detectors, limits, ranking | [VERIFY: src/emc_assistant/results/detectors.py:100] |
| `agents` | 11-specialist orchestrator + findings | [VERIFY: src/emc_assistant/agents/orchestrator.py:45] |
| `knowledge` | local RAG (chunk/embed/index/retrieve) | [VERIFY: src/emc_assistant/knowledge/retrieve.py:53] |
| `recommendations` | standardized recommendation JSON + decisions | [VERIFY: src/emc_assistant/service/recommendations.py:79] |
| `reports` | Markdown/HTML/PDF report assembly | [VERIFY: src/emc_assistant/service/report.py:258] |
| `ui` | pywebview desktop shell (disposable) | [VERIFY: pyproject.toml:39] |

### 2.2 The service layer (the real product core)

`service/` exposes one function per use case; `CommandOptions` is the typed
parameter object threaded through them  [VERIFY: src/emc_assistant/service/options.py:21].
Resolution of wiring / signals / parasitics / LISN-mode is centralized in
`service/resolve.py`:
- wiring  [VERIFY: src/emc_assistant/service/resolve.py:312]
- signals  [VERIFY: src/emc_assistant/service/resolve.py:391]
- LISN mode (pre-composition agent)  [VERIFY: src/emc_assistant/service/resolve.py:240]
- parasitic injection plan  [VERIFY: src/emc_assistant/service/resolve.py:493]
- shunt plan  [VERIFY: src/emc_assistant/service/resolve.py:558]
- series parasitics  [VERIFY: src/emc_assistant/service/resolve.py:644]
- LLM negligibility screen  [VERIFY: src/emc_assistant/service/resolve.py:160]

---

## 3. Architecture

### 3.1 Layered structure

```
┌──────────────────────────────────────────────────────────────┐
│  FRONT-ENDS                                                    │
│   ┌──────────────┐                  ┌──────────────────────┐  │
│   │ CLI (argparse)│                 │ pywebview desktop UI  │  │
│   │ cli.py        │                 │ ui/ (disposable)      │  │
│   └──────┬───────┘                  └───────────┬──────────┘  │
│          └───────────────┬──────────────────────┘             │
│                          ▼                                     │
│  APPLICATION CORE — service/                                   │
│   project · parasitics · testbench · simulate · report ·      │
│   recommendations · pipeline  + resolve.py (wiring/signals)   │
│                          │                                     │
│                          ▼                                     │
│  DETERMINISTIC DOMAIN                                          │
│   netlist → parasitics → testbench → ltspice → results        │
│                          │                                     │
│                          ▼  (opt-in, key-gated)               │
│  LLM LAYER                                                     │
│   agents/ (11 specialists + orchestrator) · knowledge/ (RAG)  │
└──────────────────────────────────────────────────────────────┘
```

**Evidence:** both front-ends resolve to the same package
([VERIFY: pyproject.toml:38], [VERIFY: pyproject.toml:39]); the CLI dispatches
into service functions (e.g. pipeline)  [VERIFY: src/emc_assistant/cli.py:330];
the LLM layer is gated  [VERIFY: src/emc_assistant/service/resolve.py:148].

### 3.2 The 11 specialist agents

The orchestrator fans out to a fixed, ordered roster of 11 active agents
[VERIFY: src/emc_assistant/agents/orchestrator.py:45]: `dcdc`, `filtering`,
`power_integrity`, `decoupling`, `parasitics`, `stackup`, `high_speed`,
`mixed_signal`, `ic_vendor`, `layout_risk`, `signal_map`. Each writes a JSON
finding; the fan-out is `run_agents`
[VERIFY: src/emc_assistant/agents/orchestrator.py:89], invoked during report
generation  [VERIFY: src/emc_assistant/service/report.py:391]. (Two further
`*_agent.py` files — `lisn_mode_agent` and `waveform_trace_agent` — are not in
this roster: the former runs pre-composition, the latter feeds the Results
waveform analyzer.)

---

## 4. Module relationships

### 4.1 Dependency direction

```
front-ends (cli, ui)
      │  call
      ▼
service/*  ── orchestrates ──▶ netlist, parasitics, testbench, ltspice, results
      │                                   │
      │  (opt-in)                         ▼
      └────────────▶ agents/ ──▶ knowledge/ (RAG)
```

- `service/report.py` pulls metrics, variants, ranking and detector plots
  together  [VERIFY: src/emc_assistant/service/report.py:156] and renders
  detector-vs-limit plots  [VERIFY: src/emc_assistant/service/report.py:216].
- `service/testbench.py` composes the testbench  [VERIFY: src/emc_assistant/service/testbench.py:170]
  and the variant set  [VERIFY: src/emc_assistant/service/testbench.py:334].
- `service/simulate.py` runs the single testbench  [VERIFY: src/emc_assistant/service/simulate.py:26]
  and every variant  [VERIFY: src/emc_assistant/service/simulate.py:78].

### 4.2 Communication pattern

Direct in-process function calls (no event bus, no server). The CLI handlers
(`cmd_*`) translate argparse namespaces into `CommandOptions` and call the
service function, e.g. report generation
[VERIFY: src/emc_assistant/cli.py:319] → [VERIFY: src/emc_assistant/service/report.py:258].

---

## 5. Data-flow overview

### 5.1 The pipeline

`run_pipeline` runs the chain **parasitics → testbench → variants → simulate →
report**  [VERIFY: src/emc_assistant/service/pipeline.py:78] (sequence stated in
its docstring  [VERIFY: src/emc_assistant/service/pipeline.py:79]).

```
.cir / .asc  (user schematic)
     │  parse / classify
     ▼
netlist.parse_cir ─▶ topology.build_topology_report
     │                         [VERIFY: src/emc_assistant/netlist/topology.py:156]
     ▼
parasitics.estimate_all_nets   (min/typ/max per net)
     │                         [VERIFY: src/emc_assistant/parasitics/per_net.py:153]
     ▼
testbench.compose_testbench_cir  (LISN + cable + splices)
     │                         [VERIFY: src/emc_assistant/testbench/composer.py:197]
     ▼
variants.enumerate_corner_variants  (baseline + min/typ/max corners)
     │                         [VERIFY: src/emc_assistant/testbench/variants.py:36]
     ▼
ltspice.run_simulation  (local LTspice, per variant)
     │                         [VERIFY: src/emc_assistant/ltspice/runner.py:121]
     ▼
results: raw_parser ─▶ detectors ─▶ limits ─▶ ranking
     │   [VERIFY: src/emc_assistant/results/detectors.py:100]
     │   [VERIFY: src/emc_assistant/results/limits.py:118]
     │   [VERIFY: src/emc_assistant/results/ranking.py:25]
     ▼
agents.run_agents (opt-in) ─▶ reports.generate_report
                                [VERIFY: src/emc_assistant/service/report.py:258]
```

### 5.2 Key transformations

| Stage | Input | Output | Evidence |
|---|---|---|---|
| Parse | `.cir` text | `ParsedNetlist` | [VERIFY: src/emc_assistant/netlist/parser.py:41] |
| Classify | parsed netlist | `TopologyReport` (net roles) | [VERIFY: src/emc_assistant/netlist/topology.py:156] |
| Estimate | topology + geometry | per-net `NetParasitics` | [VERIFY: src/emc_assistant/parasitics/per_net.py:79] |
| Compose | plan | `testbench.cir` | [VERIFY: src/emc_assistant/testbench/composer.py:197] |
| Sweep | parasitics | `Variant[]` | [VERIFY: src/emc_assistant/testbench/variants.py:23] |
| Simulate | `.cir` | `.raw`/`.log` + `SimulationResult` | [VERIFY: src/emc_assistant/ltspice/runner.py:81] |
| Detect | waveform | QP/avg meter readings | [VERIFY: src/emc_assistant/results/detectors.py:214] |
| Rank | variant metrics | `RankedVariant[]` | [VERIFY: src/emc_assistant/results/ranking.py:17] |

The quasi-peak detector is a meter-time-constant model
[VERIFY: src/emc_assistant/results/detectors.py:214]; the average detector
likewise  [VERIFY: src/emc_assistant/results/detectors.py:232]. The configured
compliance standard / worst-margin computation lives in `results/limits.py`
([VERIFY: src/emc_assistant/results/limits.py:187],
[VERIFY: src/emc_assistant/results/limits.py:118]).

---

## 6. Key technologies

| Technology | Purpose | Evidence |
|---|---|---|
| Python ≥ 3.11 | core + CLI | [VERIFY: pyproject.toml:15] |
| `numpy` | pure-numpy vector index + DSP | [VERIFY: pyproject.toml:19] |
| `openai` | LLM provider (opt-in) | [VERIFY: pyproject.toml:18] |
| `sentence-transformers` | local embeddings (RAG) | [VERIFY: pyproject.toml:27] |
| `xhtml2pdf` | PDF report export | [VERIFY: pyproject.toml:31] |
| `pywebview` | desktop UI shell (`[ui]` extra) | [VERIFY: pyproject.toml:34] |

---

## 7. Code-structure mapping

### 7.1 Directory layout (package)

```
src/emc_assistant/
├── cli.py              # argparse front-end          [VERIFY: src/emc_assistant/cli.py:616]
├── service/            # application core
│   ├── pipeline.py     # end-to-end orchestration    [VERIFY: src/emc_assistant/service/pipeline.py:78]
│   ├── options.py      # CommandOptions              [VERIFY: src/emc_assistant/service/options.py:21]
│   ├── resolve.py      # wiring/signals/parasitics   [VERIFY: src/emc_assistant/service/resolve.py:312]
│   ├── parasitics.py   # estimate / per-net / negligible
│   ├── testbench.py    # compose / variants / sim-settings
│   ├── simulate.py     # run testbench / variants
│   ├── report.py       # results view + report
│   └── recommendations.py
├── netlist/  parasitics/  testbench/  ltspice/  results/
├── agents/             # orchestrator + 13 *_agent.py files
├── knowledge/          # RAG
└── ui/                 # pywebview shell
```

### 7.2 File-to-use-case mapping (CLI command → service)

| CLI handler | Service entry | Evidence |
|---|---|---|
| `cmd_project_create` | `create_project` | [VERIFY: src/emc_assistant/cli.py:76] |
| `cmd_parasitics_estimate` | `estimate_parasitics` | [VERIFY: src/emc_assistant/cli.py:182] |
| `cmd_parasitics_per_net` | `estimate_per_net` | [VERIFY: src/emc_assistant/cli.py:195] |
| `cmd_testbench_compose` | `compose_testbench` | [VERIFY: src/emc_assistant/cli.py:221] |
| `cmd_variants_compose` | `compose_variants` | [VERIFY: src/emc_assistant/cli.py:258] |
| `cmd_simulate_run` | `run_testbench` | [VERIFY: src/emc_assistant/cli.py:232] |
| `cmd_report_generate` | `generate_report` | [VERIFY: src/emc_assistant/cli.py:319] |
| `cmd_pipeline_run` | `run_pipeline` | [VERIFY: src/emc_assistant/cli.py:330] |
| `cmd_recommendations_list` | `list_recommendations` | [VERIFY: src/emc_assistant/cli.py:278] |
| `cmd_raw_quasi_peak_sweep` | detector sweep | [VERIFY: src/emc_assistant/cli.py:431] |

---

## 8. Verification report

### 8.1 Claims verification (spot-check)

| Claim | Evidence | Status |
|---|---|---|
| Two front-ends, one core | [VERIFY: pyproject.toml:38] / [VERIFY: pyproject.toml:39] | ✓ |
| Pipeline = parasitics→testbench→variants→simulate→report | [VERIFY: src/emc_assistant/service/pipeline.py:78] | ✓ |
| 11 specialist agents, fixed roster | [VERIFY: src/emc_assistant/agents/orchestrator.py:45] | ✓ |
| LLM is opt-in / key-gated | [VERIFY: src/emc_assistant/service/resolve.py:148] | ✓ |
| User schematic never mutated (splice into fragment) | [VERIFY: src/emc_assistant/service/resolve.py:715] | ✓ |
| QP detector is a meter-time-constant model | [VERIFY: src/emc_assistant/results/detectors.py:214] | ✓ |
| Cooperative cancel between stages | [VERIFY: src/emc_assistant/service/pipeline.py:59] | ✓ |

### 8.2 Open questions / next phases
- [ ] Phase 2 — data structures: `CommandOptions`, `TestbenchPlan`, `Variant`,
  `NetParasitics`, `DetectorSpectrum`, `RawFile` field-by-field.
- [ ] Phase 3 — data flow: trace one variant end-to-end (`.cir` → `.raw` →
  detector reading → ranking → report row).
- [ ] Phase 4 — algorithms: the QP/avg meter models in `results/detectors.py`.

### 8.3 Caveats
- Line numbers are accurate at generation time and drift with edits; re-run the
  analysis after code changes.
- This is a code-structure overview, not a substitute for the canonical specs
  in `docs/` (see `docs/03_architecture.md`, `docs/11_roadmap.md`).
