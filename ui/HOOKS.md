# Wiring hooks — DOM contract

Stable attributes on the rendered DOM that the wiring binds against. These names are the contract a test runner (or a future rebuild) targets.

**Reconciled against the shipped DOM on 2026-05-23.** This file began as the design-prototype contract; it had drifted from what `ui/src/screens/*.jsx` actually render. Every entry below has been checked against the wired build. Where the design intended a hook the M3 shell does **not** ship, the entry is kept (it's a real M11 target) but tagged. The wiring itself is React in `ui/src/` talking to `window.pywebview.api.*` (`src/emc_assistant/ui/bridge.py`), not a separate `app.js`.

## Status legend

- ✅ **Shipped** — present in the rendered DOM today; bind/assert against it.
- ⏳ **Designed (M11)** — the design intends this; the M3 shell does **not** render it (or renders an inert placeholder). Don't bind to it yet. See `tasks/m11_ui_rebuild.md` and `docs/qa/QA_FLOWS.md` (matching status tags).

## Conventions

| Attribute | Purpose | Naming |
|---|---|---|
| `id` | Singleton elements (panels, dialogs, rails, tables) | `kebab-case`, prefix `screen-` for screen roots |
| `data-screen` | Marks a screen panel root | `kebab-case` (note: the three multi-word screens use the long form — `import-context`, `parasitic-selection`, `testbench-review`) |
| `data-screen-target` | The screen a nav item routes to | the **short** stage id — `import`, `parasitics`, `testbench`, `run`, `results`, `findings`, `report` (NOT the long `data-screen` form) |
| `data-action` | Triggers a backend / navigation action | `verb-noun` kebab, e.g. `run-pipeline` |
| `data-field` | A form input the page reads → sends to `save_context` / `save_settings` / `save_simulation_settings` | `snake_case`, matches backend artifact keys |
| `data-bind` | A slot the page writes backend JSON into | `kebab-case` |
| `data-state` | Disabled-/lifecycle-state marker | `coming-soon` \| `locked` \| `done` \| `active` \| `stale` |

Action-element rows that act per-record carry an extra identifying attribute alongside `data-action`:

| Extra attr | Example | Used on |
|---|---|---|
| `data-project-id`, `data-project-path` | `data-action="open-project"` | Projects table row |
| `data-net`, `data-component` | `data-action="override-net-value" data-net="VOUT" data-component="C_typ"` | Parasitic table cells (also on `remove-override`) |
| `data-net`, `data-net-role`, `data-net-included` | `data-action="select-net"` | Parasitic table row |
| `data-finding-id` | `data-action="accept-recommendation"` | Findings cards (id form: `<area>/<rec_id>`) |
| `data-filter`, `data-format`, `data-variant` | filter pills, export-format segmented, variant-ranking row | Findings / Report / Results |
| `data-screen-target` | `data-action="goto-screen"` (or `nav-locked` when disabled) | Every nav-rail item |
| `data-feature-gate` | `live-lab-assistant`, `engineer-training` | Preview screen roots |

---

## App shell (not a screen)

| `id` / element | Hook | Status / notes |
|---|---|---|
| `app` | root grid (rail + main) | ✅ |
| `nav-rail` | left rail; sections `rail-head`/`rail-brand`, `rail-tier-workspace`, `rail-tier-analysis`, `rail-tier-coming-soon`, `rail-foot` | ✅ |
| `main` | right side | ✅ |
| `topbar` | contains `#crumbs`, project-meta, privacy indicator, save affordance, theme toggle | ✅ |
| `theme-toggle` | `data-action="toggle-theme"` | ✅ |
| `screen-host` | `data-active-screen="<screen>"` | ✅ |
| `#crumbs` | `data-bind="breadcrumb"`; reads `Project / <name> / <stage label>` | ✅ |
| project-meta | `data-bind="project-meta"` with nested `project-topology` / `project-fsw` / `project-vin-vout` / `pipeline-stage` | ⏳ **values are hardcoded** in the M3 shell — not read from `user_context.json` |
| `rail-tier-analysis` | `data-bind="current-project-name"` | ✅ |
| save-project | `data-action="save-project"`, `data-project-name`, ⌘S / Ctrl+S | ⏳ **UX affordance only** — animates a phase; there is **no `save_project` bridge method**. Real persistence is per-screen autosave |
| `project-save-status` | `data-bind="project-save-status"`, `data-save-phase="idle\|saving\|saved-just-now"` | ✅ as affordance — default text is "autosaves per screen"; the timestamp is session-local, not backend-sourced (⏳ M11) |
| `privacy-indicator` | `data-action="goto-settings-privacy"`, `data-bind="privacy-state"`, `data-cloud-llm="on\|off"`; inner `<b data-bind="cloud-llm-enabled">` | ✅ reflects the **effective** state (opted-in AND key resolves). ⚠️ rendered **twice** (rail-foot + topbar) with the same `id` — select via `[data-bind="cloud-llm-enabled"]` to match both |

### Nav rail items

| Tier | Item | `data-screen-target` | `data-state` |
|---|---|---|---|
| 1 | Projects | `projects` | (none) |
| 2 | Import & context | `import` | `done` / `active` / `locked` / `stale` |
| 2 | Parasitic selection | `parasitics` | same |
| 2 | Testbench | `testbench` | same |
| 2 | Run | `run` | same |
| 2 | Results | `results` | same |
| 2 | Findings & recs | `findings` | same |
| 2 | Report | `report` | same |
| Foot | Settings | `settings` | (none) |
| 3 | Live Lab Assistant | `preview-lab` | `coming-soon` |
| 3 | Engineer Training | `preview-training` | `coming-soon` |

Each item: `data-action="goto-screen"`, or `data-action="nav-locked"` + `disabled` when its stage is `locked`. A locked item renders a `.lock-dot`; a stale item renders a `.stale-pill` ("stale"); a coming-soon item renders a `.soon-pill` ("SOON"); a done item shows a check icon.

---

## 1. Projects

`data-screen` `projects` · `id` `screen-projects`

| Actions | Where | Status |
|---|---|---|
| `open-project-folder` | "Open project" button | ✅ opens/scans a folder — see note |
| `create-project` | "New project" button (screen header) | ✅ |
| `filter-projects` | `#projects-filter` | ✅ case-sensitive substring on name |
| `open-project` | each row; `data-project-id`, `data-project-path` | ✅ opens at the furthest-present stage |

| Binds | Slot | Status |
|---|---|---|
| `projects-count` | "N projects" caption (filtered count) | ✅ |
| `projects-root` | the scanned folder path | ✅ |
| `projects-list` | `<tbody data-bind="projects-list">` inside `<table id="projects-table">` | ✅ |
| `project-name`, `project-path`, `project-stage`, `project-findings` (nested `findings-total`, `findings-accepted`), `project-updated` | per-row cells | ✅ enriched async from `project_status` + `list_recommendations` |

**Notes:** there is **no persistent project registry** — the screen scans whichever folder is picked (cached in `localStorage`). So `open-project-folder` either opens a folder that is itself a project, or scans a parent for child `*/project.yaml`. The empty/no-match state is a single message row (its copy still reads the stale "Open folder…"); a distinct "no matches" state and a validated multi-project workspace are ⏳ M11.

---

## 2. Import & context

`data-screen` `import-context` · `id` `screen-import-context`

| Actions | Where | Status |
|---|---|---|
| `drop-schematic` | the stripe-empty zone | ✅ **click-to-browse** (no real drag-and-drop) |
| `browse-schematic` | "browse…" button | ✅ |
| `replace-schematic` | "Replace" button (after a file is set) | ✅ |
| `save-context` | "Save context" | ✅ |
| `estimate-per-net` | "Estimate parasitics →" (primary) | ✅ disabled only when no project (no required-field validation — ⏳ M11) |
| `raw-context-revert`, `raw-context-format`, `raw-context-validate`, `raw-context-save` | the "Advanced — edit user_context.json" raw editor | ✅ |

| Fields (`data-field`) | → `user_context.json` |
|---|---|
| `input_voltage_v`, `output_voltage_v`, `load_current_a`, `switching_frequency_hz`, `cable_length_m`, `ambient_t_c` | `dc_operating_point` |
| `supply_net`, `return_net`, `lisn_config`, `signals_to_track` | `testbench_wiring` |
| `pcb_layers`, `pcb_copper_oz`, `pcb_dielectric_mm`, `pcb_prepreg_mm`, `pcb_trace_width_mm`, `pcb_trace_length_mm` | `pcb` (note: `…_mm`, not `…_mil`) |
| `raw_user_context` | the whole document (textarea) |

| Binds | Slot | Status |
|---|---|---|
| `schematic-filename` | file name after set | ✅ |
| `schematic-meta` | the configured netlist **path** (not size/lines/mtime) | ✅ |
| `auto-detected` | container | ✅ |
| `auto_return_net`, `auto_supply_net`, `auto_lisn_present` | from context | ✅ |
| `auto_topology`, `auto_switch_nodes`, `auto_cable_present` | rows | ⏳ schematic auto-parse not implemented — these read "not yet parsed from schematic" |

---

## 3. Parasitic selection *(priority screen)*

`data-screen` `parasitic-selection` · `id` `screen-parasitic-selection`

| Actions | Where | Status |
|---|---|---|
| `ai-suggest-negligible` | "AI: suggest negligible" | ✅ disabled unless cloud-LLM effective |
| `ai-reevaluate-values` | "AI: re-evaluate values (RAG)" (M2.17) | ✅ same gate; preview→review→`apply-reeval` |
| `apply-reeval`, `dismiss-reeval` | re-evaluation proposal card | ✅ |
| `read-from-layout` | "Read from layout (M7)" | ⏳ disabled placeholder |
| `compose-testbench` | "Compose testbench →" (primary) | ✅ not gated on "all skipped" (⏳) |
| `toggle-report-only` | report-only stat toggle | ✅ |
| `select-net` | every row (`data-net`, `data-net-role`, `data-net-included`) | ✅ |
| `toggle-net-include` | per-row + inspector toggle (`data-net`) | ✅ |
| `override-net-value` | R/L/C cells + inspector buttons (`data-net`, `data-component` ∈ `R_typ\|L_typ\|C_typ`) | ✅ R/L only on injectable nets; C universal |
| `commit-override`, `cancel-override` | override dialog | ✅ |
| `remove-override` | × in override log (`data-net`, `data-component`) | ✅ |
| `include-all-in-view`, `skip-all-in-view` | "All on" / "All off" (current filter view) | ✅ |

| Binds | Slot | Status |
|---|---|---|
| `nets-total`, `nets-included`, `nets-skipped` | "Nets analysed" stat | ✅ |
| `overrides-count` | counts **all** overrides (incl. on skipped nets) | ✅ |
| `low-confidence-count` | stat | ✅ |
| `selected-net` | diagram header pill | ✅ |
| `nets-shown-count` | table card title | ✅ |
| `nets-list` | `<tbody>` inside `<table id="nets-table">` | ✅ |
| `override-log`, `override-log-empty` | override log card | ✅ |
| `inspector-net-name`, `inspector-connects`, `inspector-ground-note` | net inspector | ✅ |
| `reeval-proposals` | re-evaluation table body | ✅ |

Override dialog: `id="override-dialog"`, `data-override-net`, `data-override-key`.

---

## 4. Testbench review

`data-screen` `testbench-review` · `id` `screen-testbench-review`

| Actions | Where | Status |
|---|---|---|
| `view-testbench-asc` | "View testbench.cir" (toggles preview) | ✅ disabled until composed |
| `goto-run` | "Continue to run →" (primary) | ✅ disabled until composed; auto-starts the run on arrival |

| Binds | Slot | Status |
|---|---|---|
| `testbench-status` | status pill ("composed" / "not composed") | ✅ |
| `wiring-audit`, `parasitics-audit`, `signal-audit` | the three audit cards (real `generated/*.json`) | ✅ |
| `testbench-cir` | `<pre id="testbench-cir-preview">` | ✅ |

(The block diagram reuses the parasitic-selection diagram. `testbench-generated-at` is **not** rendered — ⏳; use `testbench-status`.)

---

## 5. Run

`data-screen` `run` · `id` `screen-run`

| Actions | Where | Status |
|---|---|---|
| `set-run-mode` | mode segmented (`data-field="run_mode"`, values `dry-run` \| `local-run`) | ✅ (NOT `smoke/corner/full`) |
| `run-pipeline` | primary "Run pipeline" | ✅ |
| `cancel-run` | "Cancel" (shown while running) | ✅ cooperative cancel (no kill) |
| `toggle-ramp-startup`, `toggle-corner-sweep` | sim-settings toggles | ✅ corner sweep = "ON · 3 runs" / "OFF · 1 run" |
| `save-sim-defaults`, `reset-sim-defaults`, `reset-tolerances` | sim-settings buttons | ✅ |
| `apply-recommended-sim` | "apply recommended" on the pre-run check | ✅ |
| `export-log` | log card header | ⏳ inert placeholder (no handler) |
| `goto-results` | "View results →" (shown when done) | ✅ |

| Fields (`data-field`) | → `user_context.simulation` |
|---|---|
| `sim_stop_time_ms`, `sim_max_timestep_ns`, `sim_data_start_ms`, `sim_ramp_startup` | transient block |
| `sim_method`, `sim_reltol`, `sim_abstol`, `sim_vntol`, `sim_gmin`, `sim_cshunt`, `sim_corner_sweep` | solver block |

| Binds | Slot | Status |
|---|---|---|
| `run-mode-label`, `run-stage`, `run-stage-label`, `run-progress-percent`, `run-status` | top stats | ✅ |
| `run-progress` | `<div class="progress">` (also `data-progress=NN`) | ✅ increments per stage |
| `stage-status` | the 6 stage cards (each `data-stage`, `data-status`) | ✅ (replaces the old `variants-status`) |
| `sim-nyquist-hz`, `sim-cost-estimate` | live-feedback numbers | ✅ |
| `live-log` | `<div id="live-log">` — `appLog(record)` / `appLogBatch(records)` append `.line` (with `.lvl` class INFO/WARN/ERR/OK) | ✅ |
| `pre-run-warnings` | the pre-run sim-setup check (advisory; does **not** block the run) | ✅ |

Dropped from the design: `corner-variants-count`, `variant-in-flight` (no 1/3/7 count; corner sweep is a toggle).

---

## 6. Results

`data-screen` `results` · `id` `screen-results`

| Actions | Where | Status |
|---|---|---|
| `goto-findings` | "Review findings →" | ✅ |
| `toggle-trace-peak`, `toggle-trace-qp`, `toggle-trace-avg`, `toggle-trace-limit` | spectrum detector toggles | ✅ (replaces `toggle-trace-sim/measured/limit`) |
| `select-variant` | variant-ranking rows (`data-variant`) | ✅ highlight only — no per-variant metric/spectrum refresh (⏳) |
| `select-compare-trace` | waveform comparison-trace selector | ✅ |
| `rerun-pipeline` | stale-banner CTA → Run screen | ✅ |

| Binds | Slot | Status |
|---|---|---|
| `diagnostic-narrative`, `diagnostic-tags`, `diagnostic-confidence` | verdict card | ✅ |
| `results-peak`, `results-worst-margin`, `results-corner-span`, `results-dm-peak` | headline stats | ✅ (note `results-peak`, not `results-peak-typ`) |
| `variant-ranking` | ranking table `<tbody>` | ✅ |
| `results-stale-banner` | out-of-date banner (shown when the simulation stage is stale) | ✅ |

The conducted-emissions spectrum is an inline SVG (`SpectrumChart`) fed by `Api.load_spectrum`; the time-domain analyzer is `WaveformChart` fed by `Api.load_waveform`. There is **no** `#spectrum-plot` element with `data-trace-*` attributes, no `spectrum-traces` bind, and no `before-after-overlay` (⏳). The screen root carries `data-results-stale="true|false"`; when stale it renders `results-stale-banner` and dims the headline numbers (RES3) — the stale signal is the same `project_status` value the rail `.stale-pill` reads.

---

## 7. Findings & recommendations

`data-screen` `findings` · `id` `screen-findings`

| Actions | Where | Status |
|---|---|---|
| `filter-findings` | filter pills (`data-filter="open\|accepted\|rejected\|all"`) | ✅ |
| `toggle-finding-expand` | card head | ✅ |
| `accept-recommendation` | per-card (expanded body); `data-finding-id` | ✅ |
| `reject-recommendation` | per-card; reason via `window.prompt`, empty → default (not blocked) | ✅ |
| `generate-report` | primary "Generate report →" | ✅ |
| `rerun-pipeline` | stale-banner CTA → Run screen | ✅ |

Dropped: `reopen-recommendation`, `sort-findings` (⏳ not implemented).

| Binds | Slot | Status |
|---|---|---|
| `findings-filter-bar` | pill row | ✅ |
| `findings-count-open\|accepted\|rejected\|all` | counts inside pills | ✅ |
| `findings-list` | card list container | ✅ |
| `finding-area`, `finding-problem`, `finding-confidence`, `finding-status` | card head | ✅ |
| `finding-evidence`, `finding-proposal`, `finding-limitations`, `finding-reject-reason`, `finding-sources` | card body (expanded) | ✅ |
| `findings-stale-banner` | out-of-date banner (shown when the findings stage is stale) | ✅ |

Each card root carries `data-finding-id`, `data-finding-area`, `data-finding-severity`, `data-finding-status`, `data-finding-confidence`. (`finding-assumptions` / `finding-bands` are not rendered.) The screen root carries `data-findings-stale="true|false"`; when stale it renders `findings-stale-banner` and dims the findings list.

---

## 8. Report & export

`data-screen` `report` · `id` `screen-report`

| Actions | Where | Status |
|---|---|---|
| `set-export-format` | format segmented (`data-field="export_format"`, `md\|html\|pdf`) | ✅ |
| `export-report` | primary "Locate <FMT>" button (`data-format`) | ✅ **locates the on-disk artifact** — does not download; PDF/HTML are produced by the pipeline |
| `rerun-pipeline` | stale-banner CTA → Run screen | ✅ |

Dropped: `toggle-export-option` / `export-options` (⏳ not implemented).

| Binds | Slot | Status |
|---|---|---|
| `report-preview` | `<div id="report-preview">` — in-app markdown render of `reports/report.md` | ✅ (always renders `.md`, regardless of the format toggle) |
| `report-artifacts` | report.md / .html / .pdf presence list | ✅ |
| `report-meta` | sections / findings / sources / size table | ✅ |
| `report-stale-banner` | out-of-date banner (shown when the report stage is stale) | ✅ |

The screen root carries `data-report-stale="true|false"`; when stale it renders `report-stale-banner` and dims the preview.

---

## Settings

`data-screen` `settings` · `id` `screen-settings`

| Actions | Where | Status |
|---|---|---|
| `browse-ltspice`, `detect-ltspice` | LTspice path buttons | ⏳ disabled (`data-state="coming-soon"`) — backend `detect_ltspice` / `pick_file` exist but aren't wired here |
| `toggle-cloud-llm` | cloud-LLM toggle | ✅ gated on a resolvable key ("NO KEY" otherwise) |
| `toggle-strip-identifiers` | strip-identifiers | ✅ disabled — always-on (redaction can't be turned off) |
| `toggle-telemetry` | telemetry | ✅ disabled — none collected |
| `toggle-default-corner-sweep` | project-default corner sweep | ⏳ disabled placeholder |
| `add-knowledge-source`, `rebuild-knowledge-index` | KB buttons | ⏳ disabled placeholders |

| Fields (`data-field`) | Notes |
|---|---|
| `ltspice_path` | read-only (resolved at run time) |
| `llm_enabled`, `llm_provider`, `llm_budget_usd` | `llm_budget_usd` persists on blur (`save_settings`); the others gate on a key |
| `strip_identifiers`, `telemetry_enabled` | honest, disabled |
| `default_stop_time_ms`, `default_max_timestep_ns`, `default_method`, `default_corner_sweep` | ⏳ illustrative, disabled — per-project sim settings live on the Run screen |

| Binds | Slot | Status |
|---|---|---|
| `ltspice-version` | caption | ✅ |
| `llm-usage-month-usd` | "per run · monthly total not tracked" | ✅ (honest — no cross-run aggregation) |
| `knowledge-sources-list` | KB blurb | ✅ |
| `about` | stage / build / backend / shell | ✅ |

---

## Preview screens

### Live Lab Assistant
`data-screen` `preview-lab` · `data-state` `coming-soon` · `data-feature-gate` `live-lab-assistant` · `id` `screen-preview-lab`

### Engineer Training
`data-screen` `preview-training` · `data-state` `coming-soon` · `data-feature-gate` `engineer-training` · `id` `screen-preview-training`

Read-only mockups (watermarked "MOCK · not live data"). No actions/fields/binds. When a feature ships, flip the Tier-3 nav item's `data-state` off and swap the screen body (router keyed on `data-feature-gate`).

---

## State markers (no-action display)

| Attribute / element | Values | Where |
|---|---|---|
| `data-state` (nav items) | `done`, `active`, `locked`, `stale`, `coming-soon` | rail items (set from `project_status`) |
| `.stale-pill` / `.lock-dot` / `.soon-pill` | rendered element | rail item per state (stale / locked / coming-soon) |
| `data-net-included` | `true` / `false` | parasitic table row (CSS dims when false) |
| `data-finding-status` | `open`, `accepted`, `rejected` | findings card |
| `data-results-stale` / `data-findings-stale` / `data-report-stale` | `true` / `false` | screen roots — `true` renders the screen's `*-stale-banner` (CTA `rerun-pipeline`) and dims its numbers |
| `data-cloud-llm` | `on` / `off` | `#privacy-indicator` |
| `data-active-screen` | screen id | `#screen-host` |
| `data-progress` | `0..100` | `.progress` (live run) |
| `data-stage`, `data-status` | stage 1..6 / `idle\|queued\|active\|done` | Run stage cards |
| `data-override-net`, `data-override-key` | net / `R_typ\|L_typ\|C_typ` | override log rows + `#override-dialog` |
| `data-reeval-net` | net | re-evaluation proposal rows |
| `data-check-id`, `data-check-severity` | check id / `ok\|medium\|high` | pre-run sim-setup check rows |

---

## What's *not* here (intentionally)

- **No `fetch` / XHR / business logic in the React app.** Every backend call goes through `window.pywebview.api.*`.
- **No fabricated data presented as real.** Unwired rows are disabled with honest tooltips ("not yet parsed", "not wired in the UI yet"), not filled with plausible fakes.
- **The pre-compliance disclaimer** is a shared `.disclaimer` element (no `data-bind`); it appears on every screen showing numerics (and several others).

> A larger set of design-intended hooks (`save_project` snapshot, per-variant Results refresh, in-UI export, Settings LTspice browse/detect, required-field validation) is deferred to the **M11** UI rebuild. They're tagged ⏳ above and mirrored in `docs/qa/QA_FLOWS.md`. (Per-screen stale banners — `results/findings/report-stale-banner` — are now shipped; see RES3.)
