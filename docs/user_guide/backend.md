# EMC/LTspice Assistant — Backend user guide

The backend is a local, deterministic command-line pipeline for **conducted-EMI pre-compliance** analysis of DC/DC converters in LTspice. Everything in this guide runs on your machine; the only thing that ever leaves it is an *optional*, redacted LLM payload (off by default).

> **Pre-compliance only.** Every output is an *engineering hypothesis requiring lab verification* — never a guarantee that a design will pass formal EMC. The tool says "reduces risk" / "may improve" / "requires verification", never "will pass".

The running example throughout is **`examples/case_003_DCDC_eval`** — an Analog Devices **LTC7800** synchronous step-down controller (12 V → 3.3 V).

---

## 1. What it does

Import a `.cir`/`.asc` → read topology → collect context → estimate per-net PCB parasitics → compose a conducted-EMI testbench (LISN + cable + injection) → run LTspice locally → parse `.raw`/`.log` → compute CISPR-16 detectors (peak / quasi-peak / average) against EN 55022 Class B limits → rank corner variants → (optionally) run 11 specialist LLM agents + a diagnostic synthesiser → emit a Markdown/HTML report and standardized recommendation JSON.

**Not** in scope: a schematic editor, layout import, radiated EMI, automated certification, or full coverage of every standard.

---

## 2. Prerequisites & install

- **Python 3.11+**
- **LTspice** installed locally (e.g. `C:\Users\<you>\AppData\Local\Programs\ADI\LTspice\LTspice.exe`). The tool **discovers** it; it never bundles or hosts LTspice.
- Optional extras:
  - `[ui]` — the desktop shell (pywebview). See the **Frontend guide**.
  - `[pdf]` — PDF report export (`xhtml2pdf`).
- Optional **OpenAI API key** — only needed for the LLM agents / RAG features. Without it the pipeline runs fully deterministic.

```bash
# from the repo root, editable install
pip install -e .
# with extras:
pip install -e ".[ui,pdf]"
```

All commands below are shown as `emc-assistant …`; the equivalent is `python -m emc_assistant.cli …`. Run `emc-assistant --help` (or `<group> --help`) for the authoritative, current flag list.

---

## 3. Configuration

### LTspice discovery (in priority order)
1. `ltspice.executable_path` in the project's `project.yaml`
2. `ltspice_path` in `~/.emc-assistant/settings.json`
3. the `LTSPICE_PATH` environment variable
4. common install paths / `which`

On Windows PowerShell, set it for a single run (env vars don't persist between calls):
```powershell
$env:LTSPICE_PATH = "C:\Users\<you>\AppData\Local\Programs\ADI\LTspice\LTspice.exe"
```

### App-level settings — `~/.emc-assistant/settings.json`
Raw-dict store shared with the desktop UI. Relevant keys:
- `ltspice_path` — configured LTspice binary
- `cloud_llm_enabled` — opt-in for cloud LLM (a *request*; gated by a resolvable key)
- `llm_model`, `llm_budget_usd` — model + per-run spend cap

### OpenAI key resolution (in priority order)
1. `OPENAI_API_KEY` environment variable
2. `~/.emc-assistant/openai_key`
3. repo-root `.openai_key` (gitignored)

Never paste a key into a shell that gets logged. Cloud LLM is **off** unless you opt in **and** a key resolves.

### Privacy & redaction (load-bearing)
- With cloud LLM **off**, no netlist content leaves the machine.
- With it **on**, only redacted, structured payloads are sent: `rule_id` + `source_id` + our own summary + a ≤200-char excerpt (only from permissively-licensed sources). The full schematic/netlist is **never** sent. Every outbound payload is logged to `results/llm/*.jsonl` for audit.

---

## 4. Project layout — the `.emcproj` directory

A project is a plain directory with a `project.yaml` manifest:

```
case_003_DCDC_eval/
  project.yaml                 # manifest: id, scope, inputs, privacy, ltspice
  input/
    LTC7800.cir / .asc         # your schematic / netlist (confidential)
    user_context.json          # test conditions, wiring, PCB stackup, per-net choices, sim settings
    models/                    # optional vendor models
  generated/                   # testbench.cir, parasitics_*.json, signals.json, variants/ …
  results/                     # run-*.json, variants/*.json, diagnostic.json, findings/, spectrum.json, llm/
  reports/                     # report.md, report.html, (report.pdf), detector_plot_*.png
```

`generated/`, `results/`, `reports/` are **regenerated** by the pipeline and are gitignored — delete them to reset a project to "not composed".

`case_003`'s `project.yaml`:
```yaml
project_id: "case_003_DCDC_eval"
name: "LTC7800 DC/DC controller — conducted EMI evaluation"
analysis_scope: "conducted_emi_dc_dc"
inputs:
  netlist_path: "input/LTC7800.asc"
privacy:
  allow_cloud_llm: false
  redact_net_names: true
ltspice:
  executable_path: ""
  mode: "dry-run"
  timeout_seconds: 120
```

`input/user_context.json` is where you (or the UI) record test conditions, the supply/return nets, the LISN mode, the PCB stackup, **per-net parasitic choices** (skip / override), and **simulation settings**. For case_003, the 17 IC-controller pin nets (`MP_*`, `NC_*`) are marked `{"skip": true}`, and the transient window is `stop_time: 500u`, `max_timestep: 100n`.

---

## 5. The pipeline

`pipeline run` chains six stages (the same ones the desktop Run screen drives):

| # | Stage | Output |
|---|---|---|
| 1 | Estimate parasitics (per-net) | `generated/parasitics_per_net.json` |
| 2 | Compose testbench | `generated/testbench.cir` (+ `.asc`) |
| 3 | Generate corner variants | `generated/variants/*.cir` |
| 4 | Simulate variants (LTspice) | `results/variants/*.json` (+ `.raw`) |
| 5 | Single testbench run | `results/run-*.json` |
| 6 | Report + agents | `results/findings/`, `results/diagnostic.json`, `reports/report.md` |

**Modes:**
- `--mode dry-run` — compose only; does **not** call LTspice. Use to validate wiring/parasitics fast.
- `--mode local-run` — the real run; invokes LTspice for the testbench and every corner variant.

**Corner sweep** (on by default) runs min/typ/max parasitic variants so results carry an honest spread, not a single "certain" number.

**LLM:** `--llm none` (default, deterministic) or `--llm openai`. With OpenAI on, stage 6 runs the 11 specialist agents + the diagnostic synthesiser and enriches recommendations; spend is capped by `--llm-budget-usd` (or the settings value).

---

## 6. CLI reference (by group)

Run `emc-assistant <group> --help` for exact flags.

| Group · command | What it does |
|---|---|
| `project create <dir>` | Scaffold a new `.emcproj` |
| `project validate <proj>` | Validate `project.yaml` |
| `project status <proj>` | Per-stage state (present / generated_at / **stale**) + LLM cost, as JSON |
| `netlist inspect <proj>` | Parse the input `.cir` (R/L/C/V/I/X/M/D, `.model`, `.param`, `.tran`, …) |
| `parasitics estimate <proj>` | Legacy flat parasitic estimate |
| `parasitics per-net <proj>` | Per-net R/L/C estimate (the UI's parasitics stage) |
| `parasitics reevaluate <proj> [--apply]` | LLM/RAG refine per-net values into cited min/typ/max (preview; `--apply` persists typ overrides) |
| `testbench compose <proj>` | Build `testbench.cir` (LISN + cable + injection) |
| `variants compose <proj>` | Generate per-variant `.cir` (corner sweep) |
| `variants run <proj>` | Run LTspice for each variant |
| `simulate run <proj> [--mode …]` | Run the single `testbench.cir` |
| `report generate <proj> [--html] [--pdf]` | Render the Markdown/HTML/PDF report |
| `recommendations list\|accept\|reject <proj> …` | List + decide on agent recommendations (decision log) |
| `raw inspect\|export-csv <raw>` | Inspect a `.raw` / export traces to CSV |
| `knowledge list\|index\|search\|build-pack` | Embedded EMC knowledge base ops |
| `pipeline run <proj> [--mode …] [--llm …] [--html] [--pdf]` | The whole chain, one shot |

---

## 7. Worked example — case_003 (LTC7800)

```bash
# 1. validate + inspect
emc-assistant project validate examples/case_003_DCDC_eval
emc-assistant netlist  inspect  examples/case_003_DCDC_eval

# 2. (optional) dry-run to check the testbench composes without LTspice
emc-assistant pipeline run examples/case_003_DCDC_eval --mode dry-run --llm none

# 3. the real run (deterministic), with HTML report
$env:LTSPICE_PATH = "C:\Users\<you>\AppData\Local\Programs\ADI\LTspice\LTspice.exe"
emc-assistant pipeline run examples/case_003_DCDC_eval --mode local-run --llm none --html

# 4. inspect state + recommendations
emc-assistant project status        examples/case_003_DCDC_eval
emc-assistant recommendations list  examples/case_003_DCDC_eval
```

What you get (real values from the shipped case_003 artifacts):

- **31 nets** estimated; **17 skipped** by the user (the LTC7800 `MP_*`/`NC_*` pin nets), **6** series-injectable, **7** shunt-C, **1** input-rail TRACE_RLC injection; signals `Vout=V(OUT)`, `Vin=V(IN)`; dual LISN.
- **Baseline metrics:** band peak **47.08 dBµV** (150 kHz–30 MHz), worst quasi-peak margin **−26.36 dB @ 156 kHz** (within EN 55022 Class B), DM peak **20.85 V** vs CM peak **10.40 V** (DM-dominant).
- **Corner span ≈ 1.0 dB** — the worst variant (`par-trace-R-…-max`) reaches 48.10 dBµV; all variants stay within the limit.
- **Diagnostic (confidence 0.70, LLM):** *"Switch-node (hot-loop) dv/dt likely dominates conducted EMI, with input-filter resonance a secondary contributor."*
- **11 agent areas, ~37 recommendations** (e.g. `dcdc` high/0.70 "DM emissions dominant", `power_integrity` high/0.60 "likely LC resonance near 156 kHz", `layout_risk` high/0.30 "unknown hot-loop area").

> Honest note from this exact run: the **single** `testbench.cir` run hit the 120 s LTspice timeout, while the **corner variants completed** — so the Results view is built from the variant artifacts. That's by design (the corner sweep is the primary data source); see the Frontend guide.

---

## 8. Reading the outputs

| Artifact | What it holds |
|---|---|
| `generated/parasitics_per_net.json` | Per-net role + R/L/C bands + `injectable` flag |
| `generated/testbench.cir` | The composed netlist actually simulated |
| `results/variants/*.json` | Per-variant metrics (band peak, QP/avg margins, DM/CM) |
| `results/run-*.json` | The single-run record (status can be `completed` / `timeout`) |
| `results/spectrum.json` | Detector-vs-limit sweep (peak/QP/avg dBµV per frequency) |
| `results/diagnostic.json` | The synthesised top-level verdict + cited agents/rules + limitations |
| `results/findings/<area>.json` | Per-agent recommendations (problem, evidence, proposal, limitations, sources) |
| `results/llm/*.jsonl` | Every outbound LLM payload (redacted) — the privacy audit trail |
| `reports/report.md` / `.html` | The full pre-compliance report (with the disclaimer) |
| `decisions/*.json` | Your accept/reject decisions on recommendations |

`project status` is the machine-readable view of which stages are present, when they were generated, and whether each is **stale** (an upstream input changed since it was built — staleness propagates transitively down the chain).

---

## 9. Troubleshooting

- **Stray interactive LTspice wedges later runs.** Opening a schematic (or the `.asc → .cir` conversion) can leave an idle `LTspice.exe` GUI open. ADI LTspice is single-instance, so a later batch run hands off to that window and waits forever. Kill it before/after runs: `Get-Process LTspice | Stop-Process -Force`.
- **`results/run-*.json` shows `status: timeout`.** The single testbench run exceeded `ltspice.timeout_seconds`. The corner variants (smaller/faster) usually still complete and back the Results view. Raise the timeout or simplify the window if you need the single run too.
- **Garbled Ω / µ in the console (Polish/Windows cp1250).** The CLI forces UTF-8 on stdout; if you script your own prints, reconfigure stdio to UTF-8 first.
- **`.raw` "fastaccess" format unsupported.** The parser reads the normal binary format.
- **Heavy runs from the desktop UI can crash the WebView2 window.** Run heavy pipelines from the backend (this CLI / `service.pipeline`) so a GUI crash can't lose output; the UI screens then read the artifacts. See the Frontend guide.

---

## 10. Pointers

- Architecture & module map: `docs/03_architecture.md`
- Milestone status: `docs/11_roadmap.md`
- Output contracts: `schemas/*.schema.json`
- Decisions/reasoning: `docs/08_decision_log.md`
- UI flows + DOM contract: `docs/qa/QA_FLOWS.md`, `ui/HOOKS.md`
- The desktop UI: **`docs/user_guide/frontend.md`**
