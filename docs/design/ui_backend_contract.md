# UI ↔ backend contract (M3)

> Single source of truth bridging the **UI design** (`docs/design/ui_design_brief.md`,
> design sessions) and the **UI implementation**. Every UI screen renders a
> backend artifact and every UI action invokes a CLI command — the UI invents
> no data and no logic of its own. This doc maps that contract screen by
> screen, and flags the gaps to close *before* UI code starts.

## 1. The model

The backend is the existing Python CLI/pipeline. A project is an `.emcproj`
directory of schema-validated JSON. The UI is a thin shell:

- **Read** — a screen displays one or more JSON / Markdown / PNG artifacts.
- **Act** — a button invokes one CLI command (or, in-process, the equivalent
  `cmd_*` function).
- **Write** — the only thing the UI itself writes is `input/user_context.json`
  (the context form). Everything else is written by backend commands.

Nothing in the UI bypasses the CLI contract. If a screen needs data, that
data must be a backend artifact; if a screen needs an action, that action
must be a CLI command.

## 2. Project folder layout (the data substrate)

```text
<project>.emcproj/
  project.yaml                  # config — schemas/project_config.schema.json
  input/
    <netlist>.asc | .cir        # user schematic (read-only)
    user_context.json           # circuit context — the UI writes this
    models/
  generated/                    # rebuilt by the CLI; gitignored
    user_circuit_fragment.cir   # processed copy of the user netlist
    testbench.cir / testbench.asc + *.asy
    topology.json               # net-structure report (parasitics per-net)
    parasitics.json             # bulk parasitic estimates
    parasitics_per_net.json     # per-net R/L/C estimates (parasitics per-net)
    parasitics_wiring.json      # M2.10 input-rail injection audit
    parasitics_series.json      # M2.10.6 per-net series splices audit
    parasitics_shunt.json       # M2.10.5 per-net shunt-C audit
    parasitics_dropped.json     # M2.10.7 LLM-screened-out parasitics
    signals.json                # M2.10.1 resolved signal map
    recommendations.json        # schemas/recommendation.schema.json
    knowledge_pack.json         # schemas/knowledge_pack.schema.json
    variants/<id>.cir + variants.json
  results/                      # rebuilt by the CLI; gitignored
    findings/<area>.json        # ×11 — schemas/agent_finding.schema.json
    simulation_run.json         # schemas/simulation_run.schema.json
    diagnostic.json             # schemas/diagnostic_narrative.schema.json
    lisn_mode.json              # M2.10.x LISN-mode decision
    llm/<run-id>.jsonl          # privacy log of every LLM payload
    variants/<id>.json
  reports/                      # gitignored
    report.md / report.html
    <project>_schematic.png [+ _expanded.png]
  decisions/                    # gitignored
    accepted_changes.json / rejected_changes.json   # M2.12
```

## 3. CLI command reference (the actions)

| Command | Purpose |
|---|---|
| `project create <dir>` | Create a new `.emcproj` (validated skeleton + `input/`). |
| `project validate <p>` | Validate `project.yaml`. |
| `project status <p>` | Per-stage state + LLM cost, as JSON (stale-detection). |
| `parasitics estimate <p>` | Write `generated/parasitics.json`. |
| `parasitics per-net <p>` | Write `generated/topology.json` + `parasitics_per_net.json` (no compose). |
| `testbench compose <p> [flags]` | Build `testbench.cir` (+ `.asc`). Flags: `--accept-wiring/--no-wiring`, `--accept-parasitics/--no-parasitics`, `--parasitics-report-only`, `--accept-signals/--no-signals`, `--no-asc-export`, `--llm openai`. |
| `variants compose <p>` / `variants run <p> --mode` | Per-corner `.cir` files / run them. |
| `simulate run <p> --mode {dry-run,local-run}` | Run LTspice on `testbench.cir`. |
| `report generate <p> [--html] [--rank-metric] [--llm ...]` | Write `report.md` (+ `report.html`). |
| `pipeline run <p> --mode {dry-run,local-run} [--html] [--accept-wiring] [--llm ...]` | Compose → variants → simulate → report, one shot. |
| `recommendations list <p>` / `accept <p> <area>/<id>` / `reject <p> <area>/<id> --reason` | M2.12 decisions. |
| `knowledge index / search / build-pack` | Knowledge-base ops. |
| `raw inspect / export-csv` | Inspect / export `.raw` waveforms. |
| `raw quasi-peak <raw> --frequency <Hz> [--standard]` | Receiver-like quasi-peak (Mode 2) at one frequency + compliance margin. |
| `raw quasi-peak-sweep <raw> [--points N] [--standard]` | Receiver-like quasi-peak sweep (Mode 3) across CISPR Band B + worst margin. |

## 4. Per-screen contract

Each row: what the screen **reads**, the **action** it triggers, what gets
**written**.

### 1 — Projects
- Reads: a filesystem scan for `*/project.yaml` (UI-side; no command).
- Action: open a project, or `project create <dir>`.
- Writes: (create) a validated `.emcproj` skeleton + `input/`.

### 2 — Import & context
- Reads: the dropped `.asc`/`.cir`; `input/user_context.json` if present.
- Action: save the context form.
- Writes: `input/user_context.json` (the UI writes this directly — the one
  exception to "only commands write").

### 3 — Parasitic selection *(priority screen)*
- Reads: `generated/parasitics_per_net.json` + `topology.json` (per-net role
  + R/L/C bands + net structure), produced by `parasitics per-net <p>` —
  available before any compose.
- Action: `parasitics per-net <p>` (populate the screen), then
  `testbench compose <p> --accept-parasitics [--parasitics-report-only]`.
- Writes: `user_context.parasitics` overrides (UI-written: `skip_all`,
  `per_net{net:{skip|c_pf}}`); `generated/testbench.cir`; the parasitics audit
  JSONs.

### 4 — Testbench review
- Reads: `generated/testbench.cir`, `testbench.asc`, the schematic PNG,
  `parasitics_wiring.json`.
- Action: re-open / regenerate (`testbench compose`).
- Writes: none.

### 5 — Run (+ Simulation settings panel)
- Reads: `user_context.simulation` (structured solver settings, M2.13);
  `testbench.cir`.
- Action: `pipeline run <p> --mode local-run` (or `simulate run`).
- Writes: `results/` (findings, `simulation_run.json`, `diagnostic.json`,
  `lisn_mode.json`, variant runs), `generated/variants/`. The solver-settings
  panel writes `user_context.simulation`.

### 6 — Results
- Reads: `results/simulation_run.json`, `results/diagnostic.json`, the variant
  ranking, the FFT spectrum (from `.raw`), and the **EMI-detector** output —
  peak / quasi-peak / average band levels + the worst compliance margin vs the
  selected standard (in the run metrics and the report's "EMI detector"
  section).
- Action: display; optionally `raw quasi-peak` (receiver-like reading at a
  chosen frequency) or `raw quasi-peak-sweep` (band sweep); re-run loops back
  to screen 5.
- Writes: none.

### 7 — Findings & recommendations
- Reads: `results/findings/<area>.json` (×11), `generated/recommendations.json`,
  `decisions/*.json` for current status.
- Action: `recommendations accept|reject <p> <area>/<id> [--reason]`.
- Writes: `decisions/accepted_changes.json` / `rejected_changes.json`.

### 8 — Report & export
- Reads: `reports/report.html` (render in-app), `report.md` (export).
- Action: `report generate <p> --html`.
- Writes: `reports/report.{md,html}`.

### Settings
- Reads/writes: LTspice path + LLM provider/budget → `project.yaml`
  (`ltspice`, and an LLM block); privacy toggles.

## 5. Invocation model

The backend is the **`emc_assistant.service` package** — the application
service layer. Every use case is a plain function there
(`service.project.create_project`, `service.testbench.compose_testbench`,
`service.pipeline.run_pipeline`, …) that takes plain parameters / a
`CommandOptions`, returns a typed result dataclass, raises `ServiceError`
for expected failures, and emits progress through the logging seam.
`cli.py` is one thin front-end over it (an `argparse` adapter); the M3 UI
is the second.

The UI design prompts produce HTML/CSS, so the recommended shell is
**pywebview** (or Tauri): the design HTML *becomes* the UI, and the service
package is called **in-process** — each UI action calls the matching
`service.*` function directly, no subprocess, no local HTTP server, and no
`argparse.Namespace` to fabricate. The CLI's `cmd_*` functions are only the
argparse adapter; the UI does not route through them.

Long actions (`run_pipeline`, `run_testbench`, `build_index`, any LLM call)
must run off the UI thread. Progress / warnings / errors are consumed via
the logging seam: the UI installs a `logging.Handler` through
`configure_logging(ui_handler=…)` and renders the records — see
`docs/design/logging_design.md`.

## 6. Known gaps

All five gaps are **closed** — the backend contract is complete for the
M3 UI.

1. ~~No project-create command.~~ **DONE** — `project create <dir>` writes a
   validated `project.yaml` skeleton + the `input/models/` tree and refuses
   to overwrite an existing project.
2. ~~Per-net estimates are not a first-class artifact.~~ **DONE** —
   `parasitics per-net <p>` writes `generated/parasitics_per_net.json` from
   `estimate_all_nets()` without composing, so the parasitic-selection screen
   has data on first open.
3. ~~Topology is not persisted.~~ **DONE** — the same `parasitics per-net`
   command also writes `generated/topology.json` (`TopologyReport`).
4. ~~No machine-readable run status.~~ **DONE** — `project status <p>` emits
   per-stage JSON: each stage's artifact, whether it is present, its
   generated-at timestamp, and whether it is **stale** (older than an
   upstream artifact). The UI uses this for "what needs re-run".
5. ~~LLM cost surfacing.~~ **DONE** — `project status` folds in an `llm`
   block aggregating `results/llm/*.jsonl`: total calls, prompt/completion
   tokens, and estimated USD cost.
