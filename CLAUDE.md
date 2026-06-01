# CLAUDE.md — instructions for Claude Code

You are Claude Code working on a local tool called **EMC/LTspice Assistant**. The goal is to build an MVP for conducted-EMI analysis of power converters (DC/DC in particular) using a locally installed LTspice.

## Top-level principles

- Implement the deterministic core first; the agent layer follows.
- Do not host LTspice on a server.
- Do not bundle LTspice with the application.
- Do not work around LTspice licensing or vendor-model licensing.
- Assume the user's schematic is confidential.
- Do not send the schematic or netlist to the cloud by default.
- Treat the LLM as an assistant, not as the source of truth.
- Do not fabricate EMC standard limits.
- Do not rely on pirated CISPR / IEC / IPC standards.
- Phrase every recommendation as an engineering hypothesis that requires verification.
- Use min / typ / max ranges for parasitics, never a single "certain" value.
- Prefer parameter sweeps over a single simulation.

## Current state (2026-05-20)

M0 through M2.13 are merged on `main` — the whole numbered M2.x series is complete. The deterministic core is closed (schematic → testbench → variants → real LTspice → metrics → ranking → report) and the LLM-augmented layer is live: 11 post-simulation specialist agents per area, an embedded knowledge base, a copyright-safe redaction layer, an interactive feature-keeper for user signal names, an orchestrator that synthesises a top-level diagnostic narrative, and an LTspice `.asc` visualisation export. **Per-net parasitic injection is complete** (M2.10.4–.8): every net carries a parasitic — series R+L+C on clean 2-element nets, shunt C elsewhere — with an opt-in LLM negligibility screen, project overrides, Q-damping, and a `--parasitics-report-only` flag. **M2.10.x** adds a 12th agent — the pre-composition LISN-mode agent. **M2.12** is the recommendation accept/reject feedback loop (`decisions/*.json` + a `recommendations` CLI group). **M2.13** is the structured simulation/solver-settings backend.

Post-M2.13, the backend was built out ahead of the UI: a full **service-layer refactor** (`cli.py` is a thin argparse adapter over the `emc_assistant.service` package — the application core both front-ends call) and the **CISPR detector suite** (`results/detectors.py` — peak / quasi-peak / average across three modes; CISPR 16-1-1 / EN 55016-1-1 constants; the average detector is a meter-time-constant model). **EN 55022 Class B compliance limit lines** ship in `results/limits.py` (norm-selectable), and the report's "EMI detector" section **embeds the detector-vs-limit plots** for the run. A structured logging seam (`logging_setup.py`) replaces ad-hoc `print()`. **653 pytest** pass without requiring a local LTspice install or a live OpenAI key. See `docs/11_roadmap.md` for milestone-by-milestone status.

Next: **M3 — UI** (in progress). The external Claude-design prototype arrived on 2026-05-19; the React/Vite build now lives at `ui/` (Node toolchain, `npm run build` writes the static bundle into `src/emc_assistant/ui/web/`, no CDN at runtime). The pywebview shell loads that bundle and exposes the `Api` bridge as `window.pywebview.api.*`. First wiring slice landed (Projects screen — `Api.pick_folder` + `api.list_projects`). A QA-flow critique on 2026-05-20 identified six backend gaps the design assumed; **all six are now closed**: `service/settings.py` (app-level user store at `~/.emc-assistant/settings.json`, raw-dict storage so the UI can grow keys without backend changes), `Api.{load_settings, save_settings, detect_ltspice, pick_file, set_schematic, cancel_run}`, the `--pdf` report flag (`xhtml2pdf`-backed), and a cooperative cancel between pipeline stages. The remaining ten screens still render the prototype's hardcoded sample data, with `ui/HOOKS.md` as the contract for the wiring still to come. The QA flow inventory (`docs/qa/QA_FLOWS.md`) backs the test work. Parked tracks: M4, M6–M8 (M5 — conversational parasitics-strategy chat — is planned). See `tasks/m3_backend_gap.md`, `tasks/implementation_plan.md`, `docs/design/ui_backend_contract.md`, `docs/design/ui_integration.md`.

**Update (2026-05-22):** all analysis screens are now wired to real backend artifacts (Projects → Import/context → Parasitics → Testbench → Run → Results → Findings → Report); cloud LLM is key-gated in the UI. The Results screen carries the **CISPR detector-vs-limit spectrum** (M2.15) and the **M2.18 comparative time-domain waveform analyzer** — a two-panel, time-aligned view (`V(meas)` over a selectable comparison trace; default `I(Rload)`, four further LLM/heuristic-deduced traces via `agents/waveform_trace_agent.py` + `service/waveform.py`). M2.17 (LLM/RAG parasitic-value re-eval) is **done** (2026-05-22 — post-estimate refinement; one batched LLM call over all non-ground nets; deterministic prior is the fallback; `--apply` persists typ-only overrides while the audit `generated/parasitics_reevaluated.json` keeps the full min/typ/max + citations; provenance disclosed in the report; CLI `parasitics reevaluate`); the numbered **M2.x series is now complete** — the remaining CM-coupling idea (CSTRAY → earth, was M2.16) was promoted to its **own standalone milestone, M10** (2026-05-23; `tasks/m10_cm_coupling.md`) so it isn't lost. `user_context.json` is now editable from the app: structured forms (Import/context, Parasitics) plus a wired **Run-screen simulation-settings panel** (loads/saves `user_context.simulation`, with a review-before-apply deterministic check on the *proposed* values via `assess_simulation(overrides)`) and an **"Advanced — edit user_context.json" raw editor** on the Import screen (full document, validate-on-save).

**Update (2026-05-23):** Roadmap housekeeping + fixes. The numbered **M2.x series is closed** — CM-coupling (CSTRAY → earth) was lifted out to its own standalone milestone **M10** (`tasks/m10_cm_coupling.md`). A **variant-review/proposal agent** is filed for M4 (`tasks/m4_variant_agent.md`). The **UI will be rebuilt as M11** (`tasks/m11_ui_rebuild.md`) — a from-the-studs remake that **supersedes M3.99** (absorbs the pipeline-decoupling hardening) and folds in the M3 follow-up backlog; requirements cover out-of-process execution, pull-based logging, a content-aware freshness model, large-`.raw` streaming, an honest-data invariant, and a pre-run cost/privacy gate (recommended architecture: a localhost service + thin client; the `service/` layer stays the product core). Backend fix: **stage staleness now propagates through the workflow** (`build_project_status` — editing an upstream input stales the whole downstream chain, not just the next stage). The **Settings screen was honest-ified** (no fabricated values; non-wired controls disabled). Stale orchestrator agent count corrected (10 → 11). The far-future **M8** (real-time lab support + collective learning) was **split into M12 — Live Lab Assistant and M13 — Engineer Training** (the two coming-soon UI previews), so M3 has no leftover placeholders of its own.

## MVP scope

The MVP includes:

- import of an `.asc` or `.cir` file,
- reading of basic topology / netlist,
- collecting user context,
- proposing PCB parasitic values,
- generating a conducted-EMI testbench,
- a basic LISN model,
- basic cable models,
- capacitor models with ESR / ESL / SRF,
- R/L/C models for traces and vias,
- running LTspice locally,
- a `.log` parser,
- a `.raw` parser or adapter,
- Markdown / HTML reports,
- recommendations in standardized JSON.

The MVP does not include:

- a full schematic editor,
- full mutation of `.asc` files,
- layout import,
- radiated EMI,
- a payment system,
- corporate / on-premise deployment,
- automated EMC certification,
- complete coverage of every standard.

## Order of work (for a fresh session)

1. Read `docs/11_roadmap.md` for milestone status.
2. Read `docs/03_architecture.md` for module layout.
3. Read `schemas/*.schema.json` for output contracts.
4. Read `tasks/implementation_plan.md` for the active milestone.
5. Read `docs/08_decision_log.md` for the reasoning behind committed choices.
6. Do not implement UI before the CLI / pipeline is stable. (UI = M3, frozen.)

## Preferred tech stack for the MVP

- Python 3.11+ for the core and CLI.
- A simple local project format `.emcproj/` as a directory.
- JSON / YAML for configuration.
- Markdown / HTML for reports.
- Local SQLite is optional, post-M1 only.
- Desktop UI only after the CLI pipeline is fully working.

For M2.7+ the stack additionally includes:

- `openai` SDK for the LLM provider (requires `OPENAI_API_KEY`).
- `sentence-transformers` for local embeddings (POC); embedder is pluggable so paid cloud providers can replace it later.
- A pure-numpy local vector index (M2.8 — no FAISS / Chroma dependency).
- `matplotlib` + `networkx` for the schematic plotter (M2.10.3).

## Implementation layout

```text
emc-ltspice-assistant/
  src/emc_assistant/
    cli.py              # thin argparse adapter over service/
    logging_setup.py    # stdlib-logging seam (console + per-run JSONL + UI handler)
    service/            # application service layer — the core both front-ends call
      options.py        # CommandOptions — the typed parameter object
      resolve.py        # wiring / parasitics / signals / LISN-mode resolution
      <use-case>.py     # project, parasitics, testbench, simulate, report, pipeline, …
    ui/                 # M3 desktop shell — pywebview over service/ ([ui] extra)
      bridge.py         # Python⇄JS Api; log_handler.py = logging-seam UI handler
      app.py            # pywebview entry (emc-assistant-ui); index.html = placeholder
    agents/             # M2.9 specialist agents + M2.10 injection + M2.10.1 signal_map
      base.py           # Agent ABC, AgentFinding, AgentContext
      orchestrator.py   # fan-out to 11 active agents, results/findings/<area>.json
      injection.py      # ParasiticInjection + ShuntParasitic + SeriesParasitic
      synthesiser.py    # M2.11 diagnostic-narrative synthesiser
      <area>_agent.py × 11
    knowledge/          # M2.8 chunker + embedder + vector_index + pack + retrieve
    llm/                # M2.7 assistant ABC + OpenAI / Deterministic / Stub + budget
    ltspice/
    netlist/
      asc_converter.py  # M2.8 .asc → .cir via LTspice CLI
      fragment.py       # strip + ground rename + M2.10.6 series-splice cuts
      parser.py
      signals.py        # M2.10.1 feature-keeper auto-detect
      topology.py       # M2.10 net-structure analysis + M2.10.4 net roles
    parasitics/
      per_net.py        # M2.10.4 per-net R/L/C estimation
    project/
    recommendations/
    reports/
    results/
    testbench/
      asc_writer.py     # M2.10.3 LTspice .asc visualisation export
      asy_templates.py
      composer.py
      generators.py
      variants.py
  prompts/agents/       # one .md per specialist agent (11 active + 2 parked stubs)
  scripts/              # one-shot helpers (fetch_seed_pdfs, plot_schematic, plot_*_before_after)
  tests/                # 299 tests
  docs/
  schemas/              # *.schema.json — local Registry resolves cross-$refs offline
  knowledge/            # seed/, raw_sources/, user_private_sources/, licensed_sources/, processed/
  examples/             # case_001_buck_conducted_emi, case_002_DCDC
```

## Minimal modules

### `project`

- create an `.emcproj` project,
- validate `project.yaml`,
- maintain `input/`, `generated/`, `results/`, `reports/` directories.

### `ltspice`

- discover LTspice locally,
- allow manual path configuration,
- run batch mode,
- collect `.log`, `.raw`, and the exit code.

### `netlist`

- import `.cir`,
- minimal parser for R/L/C/V/I/X/M/D elements,
- extract `.include`, `.model`, `.param`, `.tran`, `.ac`, `.step`,
- for `.asc`: treat it as an input file in the MVP and emit a sibling testbench `.cir`; a full `.asc` parser is out of scope for now.

### `parasitics`

- trace parasitic models,
- via models,
- polygon-plane models,
- cable models,
- capacitor models with ESR / ESL,
- min / typ / max values,
- sources and assumptions.

### `testbench`

- LISN,
- input cable model,
- noise injection / observation,
- CM / DM helpers,
- filter variants,
- sweeps.

### `results`

- `.log` parser,
- result parser from `.raw` or via export to `.txt` / CSV,
- peak / average / quasi-peak calculations (later milestone),
- comparative metrics.

### `recommendations`

- generate recommendations conforming to `schemas/recommendation.schema.json`,
- severity,
- confidence,
- evidence,
- limitations,
- simulation_required,
- proposed_change,
- starting in M2.9, `related_sources` linking to knowledge-pack snippet IDs.

### `reports`

- Markdown report,
- HTML report,
- assumptions table,
- parasitics table,
- before / after results,
- risk list,
- pre-compliance disclaimer,
- starting in M2.9, a "Knowledge sources" section.

## Knowledge sources

- Use `knowledge/seed/*.jsonl` as the curated metadata and rules layer.
- Use `knowledge/raw_sources/` (to be created in M2.7) as the directory for downloaded reference documents.
- Do not auto-fetch content from the internet inside the MVP.
- Do not copy long excerpts from vendor documents.
- Produce summaries with references to the source.
- Every rule must have a `Source_ID` or be marked `engineering_estimate`.

## Recommendation standard

Every recommendation must include:

- problem,
- evidence,
- proposed change,
- value range,
- assumptions,
- limitations,
- simulation or measurement requirement,
- confidence,
- severity,
- sources.

## EMC guardrails

- Do not write "the circuit will pass EMC".
- Write "reduces risk", "may improve", "requires verification".
- When layout is missing — flag the limitation.
- When stack-up is missing — use the default profile and flag low/medium confidence.
- When a component model is missing — use a substitute and flag the limitation.
- When the user provides a cause for a problem — treat it as a hypothesis, not a fact.

## Tests

Every module needs unit tests. The minimum coverage is:

- project config validation,
- a simple `.cir` parser,
- parasitic calculators,
- LISN generator,
- testbench netlist generator,
- recommendation JSON validation,
- Markdown report generation.

## What is no longer in scope here

The earlier bootstrap-era "first session" guidance (no UI, no billing, no agent framework — set up the Python skeleton, CLI, data models, knowledge loader, calculators, and the first report) has already been executed and is reflected in commits up to M2.6.1. New work should follow the milestones in `docs/11_roadmap.md`.
