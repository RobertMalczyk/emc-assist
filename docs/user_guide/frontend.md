# EMC/LTspice Assistant — Frontend (desktop UI) user guide

The desktop app is a thin viewer over the same `service/` core the CLI uses (see the **Backend guide**). It walks one project through the pipeline — Projects → Import & context → Parasitic selection → Testbench → Run → Results → Findings → Report — and reads/writes real backend artifacts at each step.

> **Heads-up — the M3 shell is deliberately disposable.** It will be rebuilt from the studs as **M11** (`tasks/m11_ui_rebuild.md`). A few affordances are intentionally placeholders (called out honestly below and in `docs/qa/QA_FLOWS.md`). Don't read this as the final UX; read it as "what the current shell does, screen by screen".

The running example is **`examples/case_003_DCDC_eval`** — an Analog Devices **LTC7800** synchronous buck (12 V → 3.3 V). All numbers in the mockups below are this project's **real** artifact values. (The mockups are text renderings, not screenshots.)

## Launching

```bash
pip install -e ".[ui]"
python -m emc_assistant.ui.app          # opens the pywebview window
```
The window loads a prebuilt static bundle (`src/emc_assistant/ui/web/`). If you change the React source under `ui/`, rebuild with `npm run build` in `ui/` and relaunch. Run heavy pipelines from the backend/CLI (a GUI crash can't then lose output); the screens read whatever artifacts exist.

Every wired screen shows a small `bridge: pywebview ✓ (live backend)` chip so you always know you're on the real backend (vs. `mock — browser dev`).

---

## The app shell

```
┌────────────────────────┬─────────────────────────────────────────────────────────┐
│ EMC Assistant          │  Project / case_003_DCDC_eval / Results      [local·LLM OFF] [Save] │
│ Pre-compliance · local │─────────────────────────────────────────────────────────│
│ WORKSPACE              │                                                           │
│  ▸ Projects            │                  (active screen renders here)             │
│ ANALYSIS  case_003     │                                                           │
│  01 Import & context ✓ │                                                           │
│  02 Parasitic sel.   ✓ │                                                           │
│  03 Testbench        ✓ │                                                           │
│  04 Run              ✓ │                                                           │
│  05 Results          ✓ │                                                           │
│  06 Findings & recs  ✓ │                                                           │
│  07 Report           ✓ │                                                           │
│ COMING SOON            │                                                           │
│  ◦ Live Lab Assistant  │                                                           │
│  ◦ Engineer Training   │                                                           │
│ ⚙ Settings  · local ●  │                                                           │
└────────────────────────┴─────────────────────────────────────────────────────────┘
```

- **Left rail = pipeline gating.** Tier 2 items light up in order. A stage shows `✓` (done), a `stale` pill (an upstream input changed — re-run needed), or a lock dot (`locked` — earlier stages must complete first; the item is unclickable with a "Locked — earlier stages must complete first." tip).
- **Breadcrumb** reads `Project / <name> / <stage>`.
- **Privacy indicator** (rail foot + topbar) shows `cloud LLM OFF` (lock icon) or `ON` (unlock icon). It reflects the **effective** state — opted in **and** an API key resolves — never a hardcoded value.
- **Save button** is a per-screen-autosave affordance (each screen persists its own inputs; ⌘S/Ctrl+S animates it). A single project-wide snapshot save is deferred to M11.
- A floating **Tweaks** panel adjusts theme/density/accent (presentation only).

---

## 01 · Projects (`screen-projects`)

```
┌─ Workspace · Projects ─────────────────────────────────[ Open project ] [ + New project ]─┐
│ Scanning: C:\path\to\EMC-Assist\examples            filter: [______]   3 projects        │
│ ┌────────────────────────┬──────────────────────┬──────────────┬──────────────┐           │
│ │ Project                │ Pipeline status      │ Findings     │ Last updated │           │
│ ├────────────────────────┼──────────────────────┼──────────────┼──────────────┤           │
│ │ case_003_DCDC_eval     │ ●●●●●●● report ready │ 37 total     │ 2026-05-23   │  →        │
│ │ case_002_DCDC          │ ●●●●●●● report ready │ …            │ 2026-05-22   │  →        │
│ │ case_001_buck_…        │ ●●●●●●● report ready │ …            │ 2026-05-20   │  →        │
│ └────────────────────────┴──────────────────────┴──────────────┴──────────────┘           │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Purpose:** pick a project to work on. **"Open project"** opens an OS folder picker — pick a folder that *is* a project (has `project.yaml`) to open it directly, or a parent folder to scan it for child projects (the folder is remembered for next launch). **"New project"** picks an empty folder and scaffolds an `.emcproj`. The filter is a name substring; counts and pipeline status are loaded live from `project_status` + `list_recommendations`. Clicking a row opens the project at its furthest-completed stage.

---

## 02 · Import & context (`screen-import-context`)

```
┌─ Stage 1/7 · Import schematic & context ───────────────[ Save context ] [ Estimate parasitics → ]┐
│ Schematic source: LTC7800.asc           Test conditions (dc operating point)                      │
│  [▣ LTC7800.asc]  [ Replace ]            Input V [ 12 ]  Output V [ 3.3 ]  Load A [   ]            │
│                                          fsw [   ]  Cable m [   ]  Ambient °C [   ]                │
│ Testbench wiring                         PCB stack-up (affects parasitics)                         │
│  Supply net [ VIN ]  Return [ 0 ]        Layers [4]  Cu [1 oz]  Dielectric [1.6 mm]               │
│  LISN [ Dual (CM/DM) ]                    Prepreg [0.1]  Trace w [0.5]  Trace len [25]             │
│  Signals [ Vout, Vin ]                   Detected from context                                     │
│                                            Return net 0   ·auto·   Supply VIN ·auto·              │
│  ▸ Advanced — edit user_context.json       Topology  "not yet parsed from schematic" ·verify·    │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Purpose:** point at the schematic and confirm the test conditions. The drop zone is **click-to-browse** (`pick_file` → copies into `input/`). Form fields map into `input/user_context.json` (deep-merge — untouched keys round-trip). The **"Detected from context"** card is honest: return/supply/LISN come from your context, while **topology and switch nodes read "not yet parsed from schematic"** (schematic auto-parse isn't implemented yet). The **Advanced** disclosure is a validated raw-JSON editor for anything without a form field (e.g. `simulation`). **"Estimate parasitics →"** saves, runs the per-net estimate, and advances.

> For case_003 the DC-operating-point fields are blank because the project didn't fill them; the PCB stackup (4-layer, 1 oz, 1.6 mm) and wiring (VIN / 0 / dual LISN) are real.

---

## 03 · Parasitic selection (`screen-parasitic-selection`) — the priority screen

```
┌─ Stage 2/7 · Parasitic selection ──[AI: suggest negligible][AI: re-evaluate (RAG)][Compose testbench →]┐
│ Nets analysed 31 · 14 included · 17 skipped   Overrides 0   Low-confidence 0   Report-only [ off ]      │
│ ┌─ Testbench block diagram (click a net) ──────────────────  selected: N003 ──────────────────────────┐ │
│ │   V_RAIL → LISN+ → cable → [TRACE_RLC] → ▣ DUT (case_003 · 31 nets) → LISN-                          │ │
│ └──────────────────────────────────────────────────────────────────────────────────────────────────┘ │
│  Net inspector: N003 [SWITCH]            │  31 of 31 nets        [All on][All off]  FILTER: ALL …       │
│   R 2.7 mΩ  L 4.62 nH  C 1.07 pF [override]│ ⏻ Net    Role    Type      R(mΩ)  L(nH)  C(pF) Conf        │
│  Override log: (empty — your estimated→    │ ■ N003   switch  series-RLC  2.7   4.62   1.07  ●●○        │
│   corrected edits show here, capturable as │ ■ N005   switch  shunt-C     2.7   4.62   1.07  ●●○        │
│   training signal)                         │ ■ OUT    power   shunt-C     7.6   23.4   4.02  ●●○        │
│                                            │ ■ N002   power   series-RLC  7.6   23.4   4.02  ●●○        │
│                                            │ ■ N007   signal  series-RLC 20.2   19.3   2.68  ●●○        │
│                                            │ ▢ MP_01  signal  shunt-C    20.2   19.3   2.68  (skipped)  │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Purpose:** for every net, decide which parasitics enter the simulated testbench. Estimates are **min·typ·max** bands; overrides are captured as explicit *"estimated → corrected"* edits (training signal for the future Engineer Training feature). Per-net actions:
- **Toggle include/skip** — for case_003 the 17 LTC7800 controller-pin nets (`MP_*`, `NC_*`) are skipped; the 14 power/switch/signal nets are kept.
- **Override** an R/L/C cell → a dialog pre-fills the estimate and records your value (R/L only on *injectable* series nets; C on any net). The override log lists each edit with a `×` to remove it.
- **AI: suggest negligible** / **AI: re-evaluate values (RAG)** — enabled only when cloud LLM is active; they pre-deselect negligible nets / refine values into cited bands (preview → review → apply).
- **Compose testbench →** writes `testbench.cir` from the current selection and advances.

---

## 04 · Testbench review (`screen-testbench-review`)

```
┌─ Stage 3/7 · Testbench review ─────────────────[ View testbench.cir ] [ Continue to run → ]──────┐
│ Composed testbench                                                       status: ● composed       │
│   V_RAIL → LISN+ → cable → [TRACE_RLC] → DUT (case_003 · 31 nets) → LISN-   (DM+CM probes)         │
│ ┌ Wiring audit ───────────┐ ┌ Parasitics audit ───────────┐ ┌ Signal audit ──────────┐           │
│ │ Supply VIN ↦ LISN   ok  │ │ Series RLC splices   6 nets  │ │ Vout probe   V(OUT)    │           │
│ │ Return 0 ↦ LISN     ok  │ │ Shunt-C injections   7 nets  │ │ Vin  probe   V(IN)     │           │
│ │ Cable model     default │ │ Dropped by user     17 nets  │ └────────────────────────┘           │
│ │ LISN mode  dual · DM+CM │ │ Dropped by AI        0 nets  │                                       │
│ │ Input-rail inj. 1 TRACE │ └─────────────────────────────┘                                       │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Purpose:** a read-only audit that the testbench was assembled correctly before you spend LTspice time. The three audit cards read the real `generated/parasitics_{series,shunt,wiring}.json` + `signals.json` + your skips. The counts are the *injected subset* (`series 6 + shunt 7 + dropped-user 17 = 30`; the 31st is the return net `0`/`DUT_GND`, which the composer owns). **"View testbench.cir"** shows the raw netlist; **"Continue to run →"** goes to Run and auto-starts it.

---

## 05 · Run (`screen-run`)

```
┌─ Stage 4/7 · Run simulation ───────────────[ DRY-RUN | LOCAL-RUN ] [ ▶ Run pipeline ] [Cancel]──┐
│ Mode LOCAL-RUN · calls LTspice    Stage 6/6 · complete    Progress 100% · complete                │
│ ▸ Simulation settings: 0–0.5 ms, max step 100 ns · trap · corner sweep ON · 3 runs                │
│ ┌ Run progress ────────────────────────────────────┐ ┌ Live log ─────────────────────────────┐  │
│ │ [██████████████████████████████████████] 100%    │ │ INFO pipeline [pipeline] 4/6 simulate… │  │
│ │ 1 Estimate ✓  2 Compose ✓  3 Variants ✓          │ │ INFO ltspice  variant max … done       │  │
│ │ 4 Simulate ✓  5 Single run ✓  6 Report ✓         │ │ OK   pipeline complete · results ready │  │
│ └──────────────────────────────────────────────────┘ └────────────────────────────────────────┘  │
│  Pre-run sim-setup check: reviews Δt vs the conducted band & switching edges (advisory)           │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Purpose:** run the pipeline locally and watch it. **DRY-RUN** composes only; **LOCAL-RUN** invokes LTspice for the testbench + every corner variant. The **Simulation settings** disclosure edits the `.tran` window/solver (saved into `user_context.simulation`) with a live, deterministic adequacy check; for case_003 the window is 0–0.5 ms / 100 ns max step. Progress is derived from the backend's real `[pipeline] N/6` log lines (it climbs incrementally, not 0→100). **Cancel** is cooperative — it stops after the current stage rather than killing LTspice mid-write. When done, **"View results →"** appears.

---

## 06 · Results (`screen-results`)

```
┌─ Stage 5/7 · Results ──────────────────────────────────────────[ Review findings → ]────────────┐
│ Diagnostic narrative                                              [conf 70%] [LLM synthesis]      │
│  "Switch-node (hot-loop) dv/dt likely dominates conducted EMI,    ✓ VERDICT · within limit by     │
│   with input-filter resonance a secondary contributor."             26.4 dB                       │
│  Dominant issue: switch-node dv/dt from an unverified hot loop.   [DM dominant] [simulated only]  │
│ ┌ Band peak ─┐ ┌ Worst QP margin ─┐ ┌ Corner span ─┐ ┌ DM peak ──┐                                │
│ │ 47.1 dBµV  │ │ −26.4 dB @156kHz │ │ ~1.0 dB      │ │ 20.85 V   │  (CM 10.40 V)                  │
│ └────────────┘ └──────────────────┘ └──────────────┘ └───────────┘                                │
│ Conducted-emissions spectrum (150 kHz–30 MHz)   [PEAK][✓QP][✓AVG][✓LIMIT]  worst +/− @156 kHz     │
│ Time-domain waveform analyzer · V(meas) over a comparison trace (default I(Rload))                 │
│ Corner-variant ranking (higher = worse):  par-trace-R…max 48.10 · … · baseline 47.08              │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Purpose:** the synthesised verdict in engineering-hypothesis language, plus the conducted-band numbers. Panels:
- **Diagnostic** — from `results/diagnostic.json` (here LLM-written, confidence 0.70), with a within-limit/breach verdict pill computed from the worst margin, and a DM/CM-dominant tag (case_003 is DM-dominant: 20.85 V vs 10.40 V).
- **Headline metrics** — baseline band peak 47.1 dBµV, worst QP margin −26.4 dB @ 156 kHz, corner span, DM/CM peaks.
- **Detector spectrum** — peak/QP/avg curves vs the EN 55022 Class B limit; toggle each detector.
- **Waveform analyzer** — `V(meas)` over a selectable, time-aligned comparison trace.
- **Corner-variant ranking** — click a row to highlight a variant.

> **Stale awareness (new).** If you change an upstream input after this run, Results shows an **out-of-date banner** with a **Re-run pipeline →** button, dims the numbers, and tags the verdict `stale · re-run` — so stale numbers are never presented as current. The same applies to Findings and Report:
> ```
> ┌ ⚠ These results are out of date. An input changed since this run was   [ Re-run pipeline → ]┐
> │   generated — re-run the pipeline to refresh.                                               │
> └─────────────────────────────────────────────────────────────────────────────────────────────┘
> ```

---

## 07 · Findings & recommendations (`screen-findings`)

```
┌─ Stage 6/7 · Findings & recommendations ───────────────────────[ Generate report → ]────────────┐
│ [ Open 37 ] [ Accepted 0 ] [ Rejected 0 ] [ All 37 ]                                              │
│ ┌────────────────────────────────────────────────────────────────────────────────────────────┐  │
│ │ ▸ ▍HIGH  DCDC      Differential-mode emissions are dominant (dm_peak > cm_peak).   70%  open │  │
│ │ ▸ ▍HIGH  FILTERING Input LC may be undamped; DM emissions dominate.                70%  open │  │
│ │ ▾ ▍HIGH  POWER_INT Likely LC resonance near 156 kHz amplifying conducted noise.   60%  open │  │
│ │      Evidence · Proposed change · Limitations · Cited sources         [ ✗ Reject ] [ ✓ Accept ]│ │
│ │ ▸ ▍HIGH  LAYOUT    Unknown hot-loop area and loop inductance around the switch.    30%  open │  │
│ └────────────────────────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Purpose:** review what the 11 specialist agents produced (case_003: ~37 recommendations across `dcdc`, `filtering`, `power_integrity`, `layout_risk`, `decoupling`, `parasitics`, `ic_vendor`, `high_speed`, `mixed_signal`, `signal_map`, `stackup`). Expand a card to see evidence / proposed change / limitations / cited knowledge sources. **Accept** records the decision; **Reject** prompts for a reason (recorded too). Decisions persist to `decisions/*.json` and flow into the report. Filter pills switch between open/accepted/rejected/all. **"Generate report →"** advances.

---

## 08 · Report & export (`screen-report`)

```
┌─ Stage 7/7 · Report & export ──────────────────────────[ .MD | HTML | PDF ] [ Locate MD ]────────┐
│ reports/report.md  (rendered in-app)                    Report artifacts                          │
│  # EMC pre-compliance report — LTC7800 DC/DC …           report.md   ● present (12.x KB)          │
│  Disclaimer (pre-compliance): engineering aid, not …     report.html ● present                    │
│  ## Diagnostic — switch-node dv/dt … (conf 0.70)         report.pdf  — run with PDF option        │
│  ## Project assumptions · Estimated parasitics …        Report contents                           │
│  ## Per-net parasitic estimate (31 nets) …               Project   case_003_DCDC_eval             │
│  …                                                        Generated 2026-05-23 07:54              │
│                                                          Findings  37 (37 open · 0 acc · 0 rej)    │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Purpose:** read and locate the final report. The preview renders the real `reports/report.md` (with the pre-compliance disclaimer at the top). The format toggle + **"Locate <FMT>"** confirms where the on-disk `report.md` / `.html` / `.pdf` is — it does **not** trigger a browser download, and PDF/HTML are produced by the *pipeline* (`--pdf` / `--html`), not by this button. The meta panel shows real section/findings counts and the generation timestamp.

---

## Settings (`screen-settings`)

**Purpose:** LTspice path, LLM provider & budget, and privacy posture. Honest about what's wired:
- **LTspice path** is read-only (resolved at run time from settings / `LTSPICE_PATH` / auto-discovery). **Browse / Detect** are disabled placeholders in this shell — set the path in `~/.emc-assistant/settings.json` or `LTSPICE_PATH`.
- **Cloud LLM** toggle persists `cloud_llm_enabled`; it shows **NO KEY** and stays off until an API key resolves. **Budget cap** (USD/run) is wired and saved.
- **Strip identifiers before send** is always on (redaction can't be disabled). **Telemetry** is none. Knowledge-source management and app-level default sim settings are placeholders (use the CLI / per-project Run screen).

---

## Coming-soon previews

Two Tier-3 screens are read-only mockups (watermarked "MOCK · not live data"): **Live Lab Assistant** (overlay a live EMI-receiver spectrum on the simulated prediction) and **Engineer Training** (your `estimated → corrected` overrides become opt-in, redacted training signal). They explain the roadmap and what's already in place to support them.

---

## Cross-cutting behaviour

- **Pre-compliance disclaimer** appears on every numeric screen (Results/Findings/Report) — identical text from one shared component.
- **Local-first / privacy** — with cloud LLM off, no network calls happen; the AI buttons on Parasitic selection are disabled with an explainer.
- **Stale propagation** — editing an upstream input marks the whole downstream chain `stale` on the rail, and Results/Findings/Report show the out-of-date banner (above). Note: freshness is mtime-based today, so even a no-op save re-stales — that's fail-safe (it over-warns rather than ever showing stale data as current); content-aware freshness is an M11 item.

---

## Honest status — wired vs. deferred

This shell wires the full analysis path Projects → Report against real artifacts. A handful of designed affordances are **not** built yet in M3 and are tracked for the **M11** rebuild — notably: project-wide snapshot save, in-UI report download/export options, Settings LTspice browse/detect, required-field validation on Import, per-variant metric refresh on Results, schematic topology auto-parse, and content-aware (non-mtime) freshness. The authoritative, per-flow status is in **`docs/qa/QA_FLOWS.md`** (each flow tagged ✅ wired / ⚠️ partial / ⏳ deferred-M11), and the exact DOM contract is in **`ui/HOOKS.md`**.
