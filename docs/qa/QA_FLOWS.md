# QA flows — EMC Assistant UI (M3)

A flow inventory for the EMC Assistant desktop UI, sized for Claude Code to scaffold automated tests against (Playwright / Cucumber / similar) and for QA to run manually.

**Reconciled against the wired build on 2026-05-23.** Earlier revisions of this doc were written against the V2_2/V2_3 design prototype, when most screens still rendered hardcoded sample data. That is no longer true: per `docs/11_roadmap.md`, **all analysis screens (Projects → Import → Parasitic → Testbench → Run → Results → Findings → Report) are wired to real backend artifacts** through the pywebview bridge (`src/emc_assistant/ui/bridge.py`). Each flow below has been checked against the actual `ui/src/screens/*.jsx` and the `Api` it calls.

**Scope:** Core depth (~30 flows) covering the wired path plus the cross-cutting principles. Comprehensive edge-case coverage (60+) is still future work, but the gate is no longer "is it wired" — it's reviewer time.

**Focus:** State / data integrity and backend wiring. A pre-compliance tool can't ship wrong recommendations; the React app talks to Python through one narrow bridge and every `data-action` / `data-bind` has to land on the right side. UI correctness and a11y are out of scope for this pass.

## Status legend (per flow)

Because the M3 shell is a deliberately thin viewer (it will be rebuilt as **M11** — see `tasks/m11_ui_rebuild.md`), some flows describe behaviour the design intends but the current build does **not** implement. Each flow is tagged so a test author knows whether it is a *current acceptance gate* or a *recorded requirement*:

- ✅ **Wired** — the feature is built; the flow is testable against the live shell today.
- ⚠️ **Partial** — the core path works; specific assertions need the adjustments noted in the flow.
- ⏳ **Deferred (M11)** — the feature this flow targets is **not built** in the M3 shell. The flow is kept as a rebuild requirement, **not** a current build gate; do not fail CI on it. Where the *backend* already supports it (a bridge method exists but no screen wires it), that's called out.

> **Note on `HOOKS.md`.** The acceptance bullets reference DOM attributes. Where `ui/HOOKS.md` and the shipped DOM disagree, **this doc follows the shipped DOM** (the ground truth a test runs against) and flags the divergence. `HOOKS.md` itself still needs a reconciliation pass — see the "HOOKS.md drift" appendix at the end.

## How to read a flow

Each flow has the same shape:

- **ID** — `J*` journeys · `X*` cross-cutting · `<SCR>*` per-screen
- **Status** — one of the legend tags above
- **Persona / preconditions** — who's running this and what state the app is in
- **Gherkin** — Given / When / Then for BDD frameworks
- **Manual checklist** — numbered steps + expected results (selected flows)
- **Acceptance** — bullets tied to specific `id` / `data-action` / `data-bind` / `data-state` attributes **as they exist in the shipped DOM**. Every bullet must be **mechanically checkable** — an attribute is present, a value matches, an action fires.

Selectors are CSS — `[data-action="run-pipeline"]` — portable to Playwright (`page.locator(...)`), Cypress, `getByRole`, etc.

## Personas (starting states)

All five personas are in scope; each adds distinct coverage. These are test *fixtures*, not app concepts — note in particular that the shell has **no persistent project registry**: the Projects screen scans a folder the user picks (cached in `localStorage`), so "≥3 projects" means "a scanned folder containing ≥3 `*/project.yaml`".

| ID | Persona | Adds coverage for | Starting state |
|---|---|---|---|
| **P-new** | First-time user | Empty / no-config baseline | Fresh install · no projects folder picked · LTspice not configured · cloud-LLM disabled · dark theme · default density |
| **P-ret** | Returning user | Everyday flow | A scanned folder with ≥3 projects · one mid-pipeline (simulation not yet present) · cloud-LLM disabled |
| **P-pow** | Power user | Parasitic-screen depth | Open project with a completed local-run + accepted findings · several overrides in log · cloud-LLM enabled (key present) |
| **P-rev** | Reviewer (read-only) | Audit of a finished project | Project with report present — opens to read the report, no editing |
| **P-off** | Offline / privacy-strict | Local-first verification | Cloud-LLM disabled · telemetry off · strip-identifiers on · no network |

When a flow says "Given persona X", assume **all** of that persona's starting conditions before the first Gherkin `Given`. App-level settings (cloud-LLM, budget, LTspice path) persist in `~/.emc-assistant/settings.json`, not in `project.yaml`.

## Project principles (cross-cut every flow)

These show up as acceptance criteria across the doc — calling them out once up top so they're not missed:

- **PP1 — Pre-compliance disclaimer.** Every screen that displays numerical results (Results, Findings, Report) must show a visible pre-compliance disclaimer. This is non-negotiable; treat its absence as a critical test failure (`X1`). The disclaimer is one shared component (`.disclaimer`), so it is identical everywhere.
- **PP2 — Stale-state honesty.** When upstream inputs change, downstream stages must be marked stale on the rail; the user must not see a *passing* rail for results that no longer reflect the inputs (`X2`). (Per-screen stale banners are a separate, deferred requirement — see RES3.)
- **PP3 — Privacy transparency.** The privacy indicator must reflect the **effective** cloud-LLM state (opted-in **and** an API key resolves) — never a hardcoded value (`X4`).
- **PP4 — Local-first.** With cloud-LLM off, no network calls are made under any user action (`X5`).
- **PP5 — Persistence transparency.** The user must always be able to tell their work is saved. In the M3 shell this is delivered by **per-screen autosave** (each screen persists its own inputs through its own action) plus a topbar affordance; a single project-wide snapshot save is **deferred to M11** (`X6`).

---

# Part 1 · End-to-end journeys

The four journeys cover the typical user walkthrough. Each one walks multiple screens; if a journey fails at step N, the per-screen flow for that screen tells you where to look.

---

## J1 — First report, first user

**Status:** ⚠️ Partial · **Persona:** `P-new` · **Why it matters:** the cold-start path; if this breaks nothing else works.

```gherkin
Given persona P-new
When I open the app
Then the Projects screen is shown with the empty table message

When I click "New project"
 And I pick an empty folder
Then the Import & context screen is shown
 And only Projects + Import & context are reachable on the rail; analysis stages 03–08 show data-state="locked"

When I set "buck_sync_12v_3v3.asc" via the drop zone / "browse…"
Then [data-bind="schematic-filename"] reads the schematic file name
 And the [data-bind="auto-detected"] container is populated for the values that come from context (return net, supply net, LISN); topology + switch nodes read "not yet parsed from schematic"

When I fill DC operating point fields (input_voltage_v=12, output_voltage_v=3.3, load_current_a=2, switching_frequency_hz=500e3)
 And I click "Estimate parasitics →"
Then the Parasitic selection screen is shown
 And [data-bind="nets-total"] is > 0
 And the rail's "Parasitic selection" item shows data-state="active"; "Import & context" shows data-state="done"

When I click "Compose testbench →" then "Continue to run →" (which auto-starts the run) — or "Run pipeline"
Then [data-bind="run-status"] transitions idle → running → complete
 And [data-bind="run-progress-percent"] reaches 100

When I click "View results →" then "Review findings →"
 And I accept the open findings
 And I click "Generate report →"
Then the Report screen renders the live reports/report.md preview AND the pre-compliance disclaimer (PP1) is visible
 And [data-action="export-report"][data-format="pdf"] confirms whether report.pdf exists on disk (it is produced by the pipeline, not downloaded by this button — see REP1)
```

**Manual checklist:**
1. Open app → see Projects with the empty-table message ✓
2. Click "New project" → pick a folder → land on Import & context ✓
3. Verify rail: only Projects + Import & context reachable; 03–08 dimmed/locked ✓
4. Set schematic → filename shown; auto-detected populated for context-derived rows; topology/switch-nodes honestly say "not yet parsed" ✓
5. Fill required fields, click Estimate → land on Parasitic selection ✓
6. Compose testbench → Testbench review → Continue to run → Run screen (auto-starts) ✓
7. Run pipeline → progress bar fills incrementally, live log streams ✓
8. View results → detector spectrum renders QP/AVG vs limit ✓
9. **Pre-compliance disclaimer visible on Results (PP1)** ✓
10. Review findings → accept each → status flips to `accepted` ✓
11. **Pre-compliance disclaimer visible on Findings (PP1)** ✓
12. Generate report → preview renders → **disclaimer visible (PP1)** ✓
13. Export PDF → button reports where report.pdf is (or that it needs the pipeline PDF option) — **no browser download** ✓

**Acceptance:**
- Rail's `data-state` per item progresses `locked → active/null → done`; no stage flips `done` until its artifact is present.
- `data-active-screen` on `#screen-host` matches the visually-active screen at every step.
- **Known gap (⏳ M11):** the topbar `[data-bind="project-meta"]` row is **hardcoded** in the current shell (`app.jsx`), not read from `user_context.json`. Do **not** assert it reflects the project until M11 wires it.
- **Privacy indicator stays `data-cloud-llm="off"` throughout** (no LLM calls in P-new) — covered by X5.
- **Pre-compliance disclaimer present on Results, Findings, Report** — PP1.

---

## J2 — Resume a project mid-pipeline

**Status:** ✅ Wired (with the project-meta caveat) · **Persona:** `P-ret`

```gherkin
Given persona P-ret with project "boost_24_48" whose furthest-present stage is the testbench (no simulation yet)
When I open the app and the projects folder is scanned
Then the Projects row for "boost_24_48" shows a pipeline-status chip reflecting its furthest stage

When I click that row
Then the shell opens the project AT its furthest-present stage (not Import)
 And rail items Import, Parasitic, Testbench show data-state="done"
 And the next stage shows data-state="active"/null and later stages show data-state="locked"
```

**Manual checklist:**
1. Open app → Projects table populated from the scanned folder ✓
2. Find the in-flight project; verify its pipeline-status chip ✓
3. Click the row → land on its furthest-present stage, not Import ✓
4. Verify rail gating matches the stage ✓

**Acceptance:**
- `[data-action="open-project"]` carries `data-project-id` / `data-project-path` matching the row.
- Topbar breadcrumb reads `Project / <name> / <stage label>` (`#crumbs`, `data-bind="breadcrumb"`).
- Resume target = the furthest stage with a present artifact (driven by `Api.project_status`).
- **Known gap (⏳ M11):** `[data-bind="project-meta"]` is hardcoded — see J1.

---

## J3 — Reviewer audits a finished project

**Status:** ⚠️ Partial · **Persona:** `P-rev`

```gherkin
Given persona P-rev with project "flyback_100w" whose report is present
When I open the project
Then all analysis rail items show data-state="done"

When I navigate to Results, Findings, then Report in order
Then each screen displays the pre-compliance disclaimer (PP1)
 And each screen's [data-bind] slots populate from the project's persisted artefacts (results/diagnostic.json, results/variants/*.json, results/findings/*.json, reports/report.md) — not hardcoded sample data

When I select a format and click [data-action="export-report"]
Then the button confirms where the on-disk report.<fmt> is (or that the format needs a pipeline re-run) — it does NOT trigger a browser download (see REP1)
```

**Manual checklist:**
1. Open project → all stages done ✓
2. Visit Results → numbers match the stored artefact JSON, **disclaimer visible (PP1)** ✓
3. Visit Findings → counts match accepted/rejected status from artefact, **disclaimer visible (PP1)** ✓
4. Visit Report → preview renders reports/report.md, **disclaimer in the rendered report (PP1)** ✓
5. For each of .md / HTML / PDF: select the format, click export → the button reports the on-disk artifact's presence ✓

**Acceptance:**
- `[data-bind="report-meta"]` shows real counts (project, generated-at, sections, findings open/acc/rej, markdown size) derived from `project_status` + `list_recommendations`.
- Export format segmented carries `data-field="export_format"`; the primary button carries `data-format` matching the selection.
- **No editable controls fire destructive actions** — the reviewer can read without re-running. (Read-only screens expose no run/compose actions.)
- The on-disk `report.md` / `report.html` contain the disclaimer because the *pipeline* writes it; the UI cannot export, so verify by opening the artifact, not via a UI download.

---

## J4 — Power-user re-tunes parasitics; stale propagates

**Status:** ⚠️ Partial · **Persona:** `P-pow` · This is the single highest-value journey for state-integrity testing.

```gherkin
Given persona P-pow with a completed project (all stages done)
When I navigate to Parasitic selection
 And I open the inspector for an injectable net (e.g. a series-spliced rail) — R/L overrides apply only to injectable nets; C overrides apply to any net
 And I click [data-action="override-net-value"] for that net + component
 And I commit a new value via [data-action="commit-override"]
Then [data-bind="overrides-count"] increments by 1
 And the override log shows the new entry with [data-override-net] [data-override-key] and an "estimated → corrected" value
 And the change is persisted to user_context.parasitics.per_net (via save_context)
 And rail items Testbench, Run, Results, Findings, Report flip to data-state="stale"
 And each stale rail item shows the .stale-pill element ("stale")

When I navigate back, click Compose testbench → Continue to run → Run pipeline
Then stale markers clear stage-by-stage as each artifact is regenerated
 And final Results numbers reflect the new value
```

**Manual checklist:**
1. Open completed project ✓
2. Navigate to Parasitic selection ✓
3. Open override dialog on an injectable net's R/L cell (or any net's C cell) ✓
4. Commit override → log updates, count increments, value persists ✓
5. **Downstream rail items now `data-state="stale"` with the visible `.stale-pill`** ✓
6. Re-run pipeline → stale pills clear in order ✓
7. Confirm Results reflects updated numbers ✓
8. Remove the override via the log's × (`[data-action="remove-override"]`) → `overrides-count` decrements; downstream re-stales ✓

**Acceptance:**
- Override dialog `#override-dialog` carries `data-override-net` + `data-override-key` matching the cell that opened it.
- After commit, the table cell shows the new value with an override marker AND the override survives a screen round-trip (read from persisted `user_context`, not React-local state).
- Stale propagation hits **every** stage downstream of Parasitic, **transitively** (editing an upstream input stales the whole chain — `service/project.py build_project_status`). Verify rail item by rail item; the marker is **`.stale-pill`**, not `.stale-dot`.
- Removing the override decrements `[data-bind="overrides-count"]` and re-stales downstream.
- ✅ When Results is opened while stale, it shows the `results-stale-banner` and marks its numbers stale (`data-results-stale="true"`) — see RES3. The same holds for Findings and Report.
- **Known gap to NOT assert as pass:**
  - ⚠️ Skipping a net keeps its override persisted but does **not** render it as "inactive/struck-through" (PS4).

---

# Part 2 · Cross-cutting flows

Apply at any screen — test once, regression-run every release. These cover the project principles called out at the top.

---

## X1 — Pre-compliance disclaimer visible on every numeric screen (PP1)

**Status:** ✅ Wired (selector corrected)

```gherkin
Given any persona on a project with stored results
When I navigate to Results
Then a pre-compliance disclaimer is visible (queryable via the .disclaimer element)

When I navigate to Findings
Then a pre-compliance disclaimer is visible

When I navigate to Report
Then the rendered report.md preview contains the disclaimer
```

**Acceptance:**
- Disclaimer is one shared `PreComplianceDisclaimer` component, so its text is **identical** across screens (single source of truth). Query it with `.disclaimer` — there is **no** `data-bind="precompliance-disclaimer"` attribute in the shipped DOM.
- It is present not only on Results / Findings / Report but also on Projects / Import / Parasitic in the current shell — extra presence is fine; absence on a numeric screen is the failure.
- **Shipped-artifact check (separate from the UI):** the pipeline writes the disclaimer into `reports/report.md` and `reports/report.html`. Open those files and grep for the disclaimer string. The UI has no export/download, so this is an artifact check, not a UI flow.
- **Treat absence on a numeric screen as a critical test failure**, not a styling nit.

---

## X2 — Stale-state propagation across the pipeline (PP2)

**Status:** ⚠️ Partial · (See J4 for the override editing path. This flow covers context-edit propagation.)

```gherkin
Given a project whose report is present (all done)
When I navigate to Import & context
 And I edit [data-field="input_voltage_v"] from 12 to 24
 And I click [data-action="save-context"]
Then all downstream rail items (Parasitic … Report) flip to data-state="stale"
 And the .stale-pill element renders on each

When I open Results, Findings, or Report while stale
Then that screen shows its stale banner ([data-bind$="-stale-banner"]) with a [data-action="rerun-pipeline"] CTA
 And the screen root carries data-<screen>-stale="true" with its numbers dimmed

When I revert input_voltage_v back to 12 and save
Then stale markers remain (the content-hash-aware freshness model is an M11 requirement; the M3 shell uses mtime, so any save re-stales)
```

**Acceptance:**
- Stale ≠ locked. Stale items remain clickable; locked items don't.
- A stale stage shows a **`.stale-pill`** element, distinct from the locked stage's **`.lock-dot`**.
- Propagation is **transitive** — editing one upstream input stales the entire downstream chain, not just the next stage.
- ✅ Results / Findings / Report each render a per-screen stale banner consuming the same staleness signal as the rail (RES3).
- **Known gap to NOT assert as pass:**
  - ⏳ **(M11)** Freshness is mtime-based, so a no-op `save-context` re-stales everything (the per-screen banner then over-fires — fail-safe). Content-aware freshness is an M11 requirement (`tasks/m11_ui_rebuild.md` FR-3). Document the mtime behaviour as current.

---

## X3 — Pipeline gating (locked stages unclickable)

**Status:** ✅ Wired

```gherkin
Given persona P-new with a freshly created project (only Import reachable)
When I click rail item "Results"
Then nothing happens (the button is disabled)
 And the item shows data-state="locked" with a visible .lock-dot
 And hovering shows the tooltip "Locked — earlier stages must complete first."

When I complete Import → Parasitic → Testbench → Run
Then "Results" becomes reachable
```

**Acceptance:**
- Locked nav items carry `disabled`; CSS `cursor: not-allowed`.
- `[data-action="nav-locked"]` is set on a locked item (vs `goto-screen` when reachable) so analytics can record click-on-locked.
- Each nav item carries `data-screen-target`.

---

## X4 — Privacy indicator reflects actual settings, not hardcoded (PP3)

**Status:** ✅ Wired (semantics clarified)

```gherkin
Given persona P-off (cloud-LLM disabled in ~/.emc-assistant/settings.json)
When I open the app
Then #privacy-indicator carries data-cloud-llm="off"
 And the inner <b data-bind="cloud-llm-enabled"> reads "OFF"

When I open Settings and toggle [data-action="toggle-cloud-llm"]
Then the privacy indicators update without a page refresh
 And the persisted cloud_llm_enabled flag flips

When I close and reopen the app
Then the indicator reflects the persisted state — not a hardcoded default
```

**Acceptance:**
- The indicator reflects the **effective** state = opted-in (`cloud_llm_enabled`) **AND** an API key resolves (`Api.llm_status.effective`). With the flag on but **no key**, the Settings toggle shows "NO KEY" and the indicator stays `off`. This key-gating is intentional ("proper key → on, otherwise off"); assert the *effective* value, not the raw flag.
- The indicator value comes from `data-bind="cloud-llm-enabled"`, read from settings on render — never a literal in JSX.
- The rail-foot and topbar indicators share one source (`llmActive`), so they stay in sync.
- **Known nit (⏳ M11):** both indicators render with the same `id="privacy-indicator"` (duplicate id). A `#privacy-indicator` selector matches only the first; use `[data-bind="cloud-llm-enabled"]` (matches both) for a sync assertion.

---

## X5 — Local-first: no network with cloud-LLM off (PP4)

**Status:** ✅ Wired

```gherkin
Given persona P-off (cloud-LLM off / no key)
When I perform J1 end-to-end (new project → report)
Then no outbound network requests are made (the run stays llm="none"; the bridge's _run_options does not overlay OpenAI)
 And the [data-action="ai-suggest-negligible"] and [data-action="ai-reevaluate-values"] buttons on Parasitic selection are DISABLED with an explainer tooltip

When I enable cloud-LLM (with a key) and re-run
Then OpenAI is called only at the documented sites (compose/run with LLM on, suggest-negligible, re-evaluate values, waveform-trace suggestion)
```

**Acceptance:**
- With cloud-LLM inactive, `_run_options` keeps `llm="none"` for every run-style call — verifiable by asserting no OpenAI traffic and that `results/llm/*.jsonl` is not written.
- The AI buttons carry `disabled` + `data-state="coming-soon"` styling + a tooltip pointing to Settings when cloud-LLM is off.
- The renderer only ever talks to the Python bridge; there is no `fetch`/XHR in the React app.

---

## X6 — Save state is visible; per-screen autosave is truthful (PP5)

**Status:** ⏳ Deferred (M11) for a project-wide save · ✅ Wired for per-screen autosave + the topbar affordance.

The M3 shell has **no `save_project` backend method**. Persistence is delivered per screen: Import (`save-context` / raw-JSON save), Parasitic (override + skip persist on every change), Run (`save-sim-defaults`), Findings (accept/reject write the decision log). The topbar "Save" button is a **UX affordance only** — it animates a phase transition via a timer; it does not persist a project-wide snapshot.

```gherkin
Given any persona with a project loaded
When I navigate to each screen
Then the topbar [data-action="save-project"] is present on every workspace screen
 And [data-bind="project-save-status"] is present with [data-save-phase] ∈ {idle, saving, saved-just-now}
 And before any click it reads "autosaves per screen"

When I click [data-action="save-project"]
Then data-save-phase flips idle → saving → saved-just-now → idle
 And it does NOT call a backend save (no save_project method exists) — assert the phase animation only

When I press Cmd+S / Ctrl+S
Then save fires identically AND the browser default save-page behaviour is suppressed (preventDefault)

Given save is in flight (data-save-phase="saving")
When I click again
Then no second save is queued (the button is disabled while saving)
```

**Acceptance:**
- The button + status are children of `#topbar`, rendered identically across `data-active-screen` values.
- `data-project-name` on the button matches the currently-loaded project (it is empty when no project is open — the button is not separately disabled/hidden in that case; that's an ⏳ M11 polish item).
- **Real persistence is per-screen**, not via this button — write the actual persistence assertions against the owning screen's action (IC2, PS2/PS3, RUN save-sim, FIND1/FIND2), not against `save-project`.
- ⏳ **(M11)** A project-wide snapshot save + a backend-sourced "saved · Xm ago" timestamp are rebuild requirements. Until then, do not assert a backend call or a real elapsed-time value.

---

# Part 3 · Per-screen flows

Per the priority list: **Parasitic selection** gets the most depth. Projects, Import, Run, Results, Findings each get core flows. Testbench / Settings / Report are minimal.

---

## Projects (`screen-projects`)

### PR1 — Open a project from the table

**Status:** ✅ Wired (with the project-meta caveat)

```gherkin
Given persona P-ret with a scanned folder of ≥3 projects
When I click a row in #projects-table
Then [data-action="open-project"] fires with data-project-id and data-project-path
 And the shell opens the project at its furthest-present stage
```

**Acceptance:** `[data-bind="projects-count"]` reflects the filtered row count. Rows enrich asynchronously with real stage + findings counts (`project_status` + `list_recommendations`). **Known gap (⏳ M11):** `[data-bind="project-meta"]` in the topbar is hardcoded, not from `user_context.json`.

### PR2 — Empty state + new project

**Status:** ⚠️ Partial

```gherkin
Given persona P-new (no folder picked / empty folder)
Then #projects-table tbody shows a single message row
 And the header has a primary "New project" CTA (data-action="create-project")

When I click "New project"
Then I am prompted to pick a folder, a project skeleton is created, and I land on Import & context
```

**Acceptance:**
- The empty state is a **single message row inside the table**, not a separate empty-state card with an embedded CTA. The "New project" CTA lives in the screen header (always present), not inside the empty row.
- ⚠️ The empty-row copy still reads **"Open folder…"** (stale — the button was renamed "Open project"). Fix the copy or relax the assertion.
- `create-project` calls `Api.create_project(folder)`; the returned `project_id` is the folder name.

### PR2b — Open an existing project / folder of projects

**Status:** ⚠️ Partial (model differs from the original "adopt into a registry" design)

```gherkin
When I click [data-action="open-project-folder"] ("Open project")
Then an OS folder picker opens (in browser dev it falls back to a prompt)

When I pick a folder that IS a project (contains project.yaml)
Then the shell opens that project directly at its furthest-present stage

When I pick a folder that is NOT itself a project
Then the shell treats it as a parent folder, scans it for */project.yaml, and lists the children
 And the scanned folder is cached in localStorage so the next launch starts populated
```

**Acceptance:**
- There is **no persistent project registry**: the screen scans whichever folder is picked/cached. So there is **no** "increment projects-count by adopting one project", **no** dedupe-by-path, and **no** "Not a valid EMC project folder" error toast. Test the scan-or-open behaviour above instead.
- ⏳ **(M11)** A persistent multi-project workspace with validation + dedupe is a rebuild requirement.

### PR3 — Filter

**Status:** ⚠️ Partial

```gherkin
Given a scanned folder with projects "buck_sync_12v_3v3", "boost_24_48", "flyback_100w"
When I type "boost" into #projects-filter
Then only the boost row is visible
 And [data-bind="projects-count"] updates to "1 project"

When I clear the filter
Then all rows return AND the count is restored
```

**Acceptance:**
- Filter is a **case-sensitive substring** match on the project name (`name.includes(filter)`) — "Boost" will not match "boost_24_48". Either assert lowercase input or fix the match.
- ⚠️ The "no matches" result shows the **same** message row as the empty state — it is **not** a distinct "no matches" state. Don't assert distinct copy until it's added.

---

## Import & context (`screen-import-context`)

### IC1 — Set schematic, context-derived detection populates

**Status:** ⚠️ Partial

```gherkin
When I click the drop zone / "browse…" and pick "<file>.asc"
Then [data-bind="schematic-filename"] reads the file name
 And [data-bind="schematic-meta"] shows the configured netlist path
 And the [data-bind="auto-detected"] block lists: return net, supply net, LISN config (from context) AND honest "not yet parsed from schematic" rows for topology, switch nodes, cable
 And a "Replace" button (data-action="replace-schematic") appears
```

**Acceptance:**
- The drop zone is **click-to-browse** (`Api.pick_file` → `Api.set_schematic`); there is no real drag-and-drop file handling. Treat `[data-action="drop-schematic"]` as a click target.
- `schematic-meta` shows the **path**, not size / line-count / last-modified.
- ⏳ **(M11 / backend)** Topology, switch-node, and cable auto-parse from the `.asc` is **not implemented** — those rows read "not yet parsed from schematic"/"not in netlist". Don't assert parsed values.

### IC2 — Fill form + save context

**Status:** ✅ Wired

```gherkin
Given a schematic is set
When I fill the data-field inputs (DC OP, testbench wiring, PCB stackup)
 And I click [data-action="save-context"]
Then the persisted user_context.json contains each value at its mapped key path (FIELD_MAP)
 And navigating away and back preserves every value (read from disk, not React state)
 And unrelated keys (signals, simulation, …) round-trip untouched (deep-merge)
```

**Acceptance:**
- Each `data-field` maps through `contextMap.FIELD_MAP`. **HOOKS drift:** the dielectric/prepreg fields are `pcb_dielectric_mm` / `pcb_prepreg_mm` in the DOM (HOOKS.md says `…_mil`). Follow the DOM.
- The "Advanced — edit user_context.json" raw editor (`data-field="raw_user_context"`) validates JSON on save and regenerates the structured form.

### IC3 — Required-field validation

**Status:** ⏳ Deferred (M11)

```gherkin
Given a schematic is set but input_voltage_v is empty
When I look at [data-action="estimate-per-net"]
Then (DESIRED) it is disabled with a tooltip listing missing fields
```

**Acceptance:**
- ⏳ **Not implemented.** The Estimate button is disabled **only** when no project is open (`disabled={!projectRoot}`). There is no required-field gating, no missing-field tooltip, and no inline/negative-value validation. Keep this flow as an M11 requirement; do not run it as a current gate.

---

## Parasitic selection (`screen-parasitic-selection`) — deepest coverage

The highest-state-churn screen. Six flows.

### PS1 — Select a net

**Status:** ✅ Wired

```gherkin
When I click a net in the diagram or a row in #nets-table
Then [data-bind="selected-net"] updates to that net
 And the inspector's [data-bind="inspector-net-name"] matches
 And the row [data-net=...] is highlighted
```

**Acceptance:** Selecting from the table updates the diagram and vice-versa; selection survives filter changes (there is no table sort).

### PS2 — Override an R/L/C value (commit + persist)

**Status:** ✅ Wired

```gherkin
When I click an overridable cell's [data-action="override-net-value"] (data-net, data-component ∈ R_typ|L_typ|C_typ)
Then #override-dialog opens with matching data-override-net / data-override-key
 And the estimated value is pre-filled and shown next to the new input (diff visible)

When I enter a new value and click [data-action="commit-override"]
Then the dialog closes
 And the cell shows the new value with an override marker
 And [data-bind="overrides-count"] increments
 And [data-bind="override-log"] gains an "estimated → corrected" entry
 And the change persists to user_context.parasitics.per_net

When I navigate away and back
Then the override is still applied (read from persisted state)

When I click "×" on the log entry ([data-action="remove-override"], carries data-net + data-component)
Then the cell reverts and [data-bind="overrides-count"] decrements
```

**Acceptance:**
- R / L overrides are offered **only on injectable (series-spliced) nets**; C overrides are universal. On a shunt-only net the R/L cells are non-interactive (tooltip explains why). Choose your test net accordingly.
- Cancel via `[data-action="cancel-override"]` closes without changes. Commit writes through `save_context`; the round-trip survives reload.

### PS3 — Toggle net include / skip

**Status:** ✅ Wired

```gherkin
When I click [data-action="toggle-net-include"][data-net=...]
Then the row's data-net-included flips true↔false
 And the row dims
 And [data-bind="nets-included"] / [data-bind="nets-skipped"] update
 And the skip persists (user_context.parasitics.per_net[net].skip)
```

**Acceptance:** A skipped net shows up as "Dropped by user" in the Testbench audit on the next screen — verify end-to-end. Bulk `[data-action="include-all-in-view"]` / `[data-action="skip-all-in-view"]` apply to the current filter view only.

### PS4 — Override + skip interaction

**Status:** ⚠️ Partial

```gherkin
Given a net has a committed override
When I skip that net
Then data-net-included="false"
 And the override value is still shown in the cell and the log (it is NOT lost)
 And BOTH the skip flag and the override value are persisted

When I re-include the net
Then the override is active again with no re-prompt and no duplicate log entry
```

**Acceptance:**
- The override **data** survives skip → re-include → reload (the persistence writes `skip:true` alongside `c_pf`/`r_mohm`/`l_nh`).
- ⚠️ There is **no** "inactive / struck-through" visual treatment on a skipped net's override entry, and `[data-bind="overrides-count"]` counts **all** overrides (including those on skipped nets) — there is no active-vs-total distinction surfaced. Don't assert the strike-through or an "N inactive" sub-stat; those are M11 polish.

### PS5 — Override log empty → populated

**Status:** ✅ Wired

```gherkin
Given no overrides exist
Then [data-bind="override-log-empty"] is shown with explainer copy AND the log body is absent

When I commit my first override
Then the empty state is replaced by [data-bind="override-log"] with the new row
```

### PS6 — Compose testbench + advance

**Status:** ⚠️ Partial

```gherkin
Given at least one net is included
When I click [data-action="compose-testbench"]
Then compose runs (accept_wiring/signals/parasitics, report-only honoured) and I land on Testbench review
 And the rail flips Parasitic to data-state="done", Testbench to "active"
 And the composed testbench reflects committed overrides on included nets
```

**Acceptance:**
- The composed testbench round-trips override values — verify on the Testbench screen / in `generated/testbench.cir`.
- ⚠️ Compose is **not** disabled when all nets are skipped (no "include at least one net" tooltip). Don't assert that gate.
- ⚠️ The Testbench screen exposes a `data-bind="testbench-status"` pill ("composed"), **not** a `testbench-generated-at` timestamp. Use the status pill.

---

## Testbench review (`screen-testbench-review`) — smoke only

### TB1 — Smoke

**Status:** ✅ Wired

```gherkin
Then [data-bind="wiring-audit"], [data-bind="parasitics-audit"], [data-bind="signal-audit"] populate from the real generated/*.json (series / shunt / dropped / wiring / signals)
 And [data-bind="testbench-status"] reads "composed" (or "not composed" before compose)

When I click [data-action="view-testbench-asc"]
Then #testbench-cir-preview becomes visible AND contains the raw testbench.cir text

When I click [data-action="goto-run"]
Then I land on the Run screen and it auto-starts the run
```

**Acceptance:** `[data-action="goto-run"]` and `[data-action="view-testbench-asc"]` are disabled until the testbench is composed (the gate is "cir present", not audit-failure). Audit counts are the *injected subset* (series + shunt + dropped_user + dropped_ai ≤ total nets).

---

## Run (`screen-run`)

### RUN1 — Pick mode + start

**Status:** ⚠️ Partial (mode vocabulary corrected)

```gherkin
When I click a mode in the segmented control ([data-action="set-run-mode"], data-field="run_mode", value ∈ dry-run | local-run)
Then [data-bind="run-mode-label"] updates ("DRY-RUN" / "LOCAL-RUN")

When I click [data-action="run-pipeline"]
Then [data-bind="run-status"] flips idle → running
 And [data-bind="run-progress"] / data-progress begin updating
```

**Acceptance:**
- Modes are **`dry-run` / `local-run`**, not `smoke|corner|full`. The corner sweep is a **separate toggle** in the sim-settings panel (`[data-action="toggle-corner-sweep"]`, "ON · 3 runs" / "OFF · 1 run"). There is **no** `corner-variants-count` (1/3/7) bind. Test against the real controls.
- The mode segmented and run button are disabled while a run is in flight.

### RUN2 — Long-running pipeline: live log streams

**Status:** ✅ Wired

```gherkin
Given a local-run that takes ≥30s
When the run is in flight
Then #live-log appends lines via window.appLog / window.appLogBatch
 And the .lvl spans carry the correct class (INFO/WARN/ERR/OK)
 And the progress bar updates incrementally from the parsed "[pipeline] N/6" stage lines — it does NOT jump 0→100
 And the UI stays responsive (the pipeline runs off the GUI thread)
```

**Acceptance:** `data-progress` on `.progress` increments as stages advance (≈6 steps, ≥5). The six `data-stage` cards reflect queued/active/done.

### RUN3 — Pre-run sim-setup check

**Status:** ⚠️ Partial (advisory, not blocking)

```gherkin
Given the proposed sim settings are inadequate (e.g. max timestep too coarse for 30 MHz)
Then the "Pre-run sim-setup check" card ([data-bind="pre-run-warnings"]) lists the issues with severity
 And (when available) an [data-action="apply-recommended-sim"] button fills the recommended Δt / stop / record-start
```

**Acceptance:**
- The warnings are **advisory** — they do **not** disable `[data-action="run-pipeline"]`, and there is no per-warning acknowledge/dismiss. Don't assert that warnings block the run.
- The check is deterministic and live (re-assessed as the user edits, debounced) via `Api.assess_simulation`.

### RUN4 — Run failure: LTspice missing

**Status:** ⏳ Deferred (M11)

```gherkin
Given LTspice is not resolvable
When I click [data-action="run-pipeline"]
Then (CURRENT) the backend raises and the error text appears in the Run-screen error banner + the live log
Then (DESIRED) an inline "LTspice not found" with an "Open settings" link
```

**Acceptance:**
- ⏳ There is **no** dedicated pre-flight LTspice check, no "Open settings" deep-link, and no special-cased "LTspice not found" UX. A missing binary surfaces as the generic `ServiceError` banner. Keep the desired UX as an M11 requirement.

### RUN5 — Cancel returns the UI to a sane state

**Status:** ⚠️ Partial

```gherkin
Given a run is in flight
When I click [data-action="cancel-run"]
Then the bridge requests a COOPERATIVE cancel (the pipeline aborts after its current stage; an in-flight LTspice run is allowed to finish)
 And the live log writes a WARN line "cancel requested — stopping after the current stage…"
 And when the run returns cancelled, the run button is enabled again and downstream stages remain locked
```

**Acceptance:**
- Cancel is cooperative (`Api.cancel_run` → `request_cancel()`), **not** a subprocess kill — no orphaned `.raw`. The cancel button is only rendered while running.
- ⚠️ `[data-bind="run-status"]` does not flip to a literal "cancelled"; it returns to idle/error via the raised `RunCancelled`. The final log line is the WARN above, not an OK "Run cancelled by user". Assert the cooperative behaviour, not those exact strings.

---

## Results (`screen-results`)

### RES1 — Detector-spectrum trace toggles

**Status:** ⚠️ Drifted (trace model corrected to the M2.15 detector suite)

```gherkin
Given a project with a local-run
Then the conducted-emissions spectrum shows CISPR-16 detector curves vs the EN 55022 limit
 And the toggles are [data-action="toggle-trace-peak"], "-qp", "-avg", "-limit" (default: QP, AVG, LIMIT on; PEAK off)
 And the pre-compliance disclaimer (PP1) is visible

When I click [data-action="toggle-trace-avg"]
Then the AVG curve hides
```

**Acceptance:**
- Traces are **peak / quasi-peak / average / limit**, NOT `sim / measured / limit`. There is **no** `#spectrum-plot` element with `data-trace-sim`/`-measured`/`-limit` attributes — the spectrum is an inline SVG fed by `Api.load_spectrum`. Test the four detector toggles.
- The curves come from the run's `.raw` (real data); before a local-run the card shows an honest "run in local-run mode" note.

### RES2 — Variant ranking selection

**Status:** ⚠️ Partial

```gherkin
When I click a row in the corner-variant ranking ([data-action="select-variant"], data-variant)
Then the row highlights as the active variant
```

**Acceptance:**
- Selecting a variant currently **only highlights** the row. It does **not** refresh the headline metric cards or re-draw the spectrum for that variant — the headline stats are baseline-derived and the worst-margin is the max across the ranking. The relevant binds are `results-peak`, `results-worst-margin`, `results-corner-span`, `results-dm-peak` (note: `results-peak`, not `results-peak-typ`). Don't assert per-variant refresh.
- ⏳ **(M11)** Per-variant metric/spectrum refresh on selection is a rebuild requirement.

### RES3 — Stale results banner

**Status:** ✅ Wired

```gherkin
Given an upstream input changed since the last run (the rail shows the simulation stage stale)
When I open Results
Then a stale banner [data-bind="results-stale-banner"] is shown with a [data-action="rerun-pipeline"] CTA
 And #screen-results carries data-results-stale="true"
 And the headline metric cards are dimmed and the verdict shows a "stale · re-run" pill

When I click [data-action="rerun-pipeline"]
Then I am routed to the Run screen (re-run from there)

When the pipeline is re-run and the simulation is fresh again
Then the banner clears and data-results-stale flips to "false"
```

**Acceptance:**
- The stale signal is the backend's transitive staleness for the `simulation` stage (`build_project_status`), surfaced through `projStatus.results.stale` — the **same source the rail `.stale-pill` reads**, so the screen and the rail never disagree.
- The banner shows only when the stage is stale AND results exist (`diag || hasMetrics`); it is absent on a fresh run and before any run.
- ⚠️ Freshness is mtime-based and over-fires (any `user_context` save re-stales) — this is **fail-safe** (over-warn, never present stale-as-current). Content-aware precision stays ⏳ M11.
- The identical pattern is implemented on **Findings** (`findings-stale-banner`, `data-findings-stale`) and **Report** (`report-stale-banner`, `data-report-stale`) via the shared `StaleBanner` component.

---

## Findings & recommendations (`screen-findings`)

### FIND1 — Accept a recommendation

**Status:** ⚠️ Partial

```gherkin
When I expand a card and click [data-action="accept-recommendation"] (the card carries data-finding-id="<area>/<idx>")
Then data-finding-status flips to "accepted" and persists to decisions/*.json
 And [data-bind="findings-count-accepted"] increments
 And the Accept button is hidden (Reject remains)
 And the pre-compliance disclaimer (PP1) stays visible
```

**Acceptance:**
- Accept/Reject buttons live in the **expanded** card body — expand first.
- ⏳ **Not implemented:** there is **no** `[data-action="reopen-recommendation"]`. After accepting, the card cannot be reopened to "open" from the UI (re-deciding the other way is possible while the opposite button shows). Don't assert a reopen affordance.

### FIND2 — Reject with reason

**Status:** ⚠️ Partial

```gherkin
When I click [data-action="reject-recommendation"]
Then a window.prompt asks for a reason
 And on confirm, status flips to "rejected", [data-bind="finding-reject-reason"] is populated, and it persists across reload
```

**Acceptance:**
- The reason is collected via a **`window.prompt`**, not an inline input that holds the card open.
- An empty reason is **not blocked** — it falls back to "rejected by engineer". Don't assert empty-reason blocking; assert that a reason (entered or default) is persisted.

### FIND3 — Filter pills

**Status:** ✅ Wired

```gherkin
When I click [data-action="filter-findings"][data-filter="accepted"]
Then only accepted cards are visible
 And the active pill is styled active
 And [data-bind="findings-count-accepted"] reflects the count

When I click [data-filter="all"]
Then all cards return
```

**Acceptance:** Pills are open / accepted / rejected / all with live counts. (`[data-action="sort-findings"]` appears in HOOKS.md but is not implemented — don't test it.)

---

## Report & export (`screen-report`) — smoke only

### REP1 — Format select + locate-on-disk

**Status:** ⚠️ Drifted (no UI export; the button locates the pipeline-written artifact)

```gherkin
When I select a format ([data-action="set-export-format"], data-field="export_format", value ∈ md | html | pdf)
Then [data-bind="report-preview"] always renders reports/report.md (the toggle does not re-render the preview per format)
 And the primary button carries data-format matching the selection

When I click [data-action="export-report"]
Then the button checks whether reports/report.<fmt> exists on disk and reports its location — it does NOT trigger a browser download
 And for PDF/HTML that weren't generated, it tells the user to re-run the pipeline with that option (Run screen / --pdf / html:true)
```

**Acceptance:**
- The button label is "Locate <FMT>", not "Export". There is **no** download and **no** `[data-action="toggle-export-option"]` / `export-options` list in the shipped screen (those are HOOKS.md-only).
- The disclaimer check for shipped formats is an **artifact** check (open `reports/report.md` / `.html`), not a UI-download check — see X1.
- ⏳ **(M11)** True in-UI export (file-save dialog) and per-section export options are rebuild requirements.

---

## Settings (`screen-settings`) — LTspice path resolution

### SET1 — LTspice path

**Status:** ⏳ Deferred (M11 in the UI; backend methods exist)

```gherkin
Given LTspice is at a non-default location
When I open Settings
Then [data-field="ltspice_path"] is read-only and shows the configured/auto-discovered path
 And [data-action="browse-ltspice"] and [data-action="detect-ltspice"] are DISABLED (data-state="coming-soon") with tooltips
```

**Acceptance:**
- ⏳ The LTspice **browse/detect** buttons are intentionally disabled in the honest-ified Settings screen; the path is resolved at run time from `~/.emc-assistant/settings.json` / `LTSPICE_PATH` / auto-discovery. The bridge **does** expose `detect_ltspice` and `pick_file`, so wiring these is an M11 task, not a backend gap.
- The cloud-LLM toggle, budget cap, and the always-on "strip identifiers" / "no telemetry" rows **are** wired/honest — see X4. The project-default sim-settings and knowledge-source controls are disabled-honest placeholders.

---

# Part 4 · Test ordering recommendation

When wiring these into a Playwright suite, order by risk and runtime:

1. **Cross-cutting (X1–X5)** — fastest, catches the most regressions. **X1 (disclaimer), X3 (gating), X4/X5 (privacy / local-first) are project-principle gates** — fail the build on regression. X6 tests an affordance + per-screen autosave, not a backend save.
2. **Per-screen happy paths** in pipeline order: PR1 → IC1 → IC2 → PS1 → PS2 → PS6 → TB1 → RUN1 → RUN2 → RES1 → FIND1 → REP1.
3. **End-to-end journeys (J1–J4)** — slow, run on every PR but allow parallel sharding. **J4 is the highest-value state-integrity journey** — never skip on flake (test the rail `.stale-pill` propagation, not a per-screen banner).
4. **Edge / error states** that are wired: RUN5 (cooperative cancel), PS3/PS4 (skip + override), FIND2 (reject reason), PR3 (filter).
5. **Deferred (⏳ M11) flows** — IC3, RUN3-as-blocker, RUN4, RES2 per-variant, SET1, X6 project-wide save. Keep them in the suite as **skipped/`xfail`** with a link to `tasks/m11_ui_rebuild.md` so they become live gates when the rebuild lands.

## What's *not* covered here (intentional)

- **Visual regression** — colour, spacing, typography, theme × density. Add a snapshot suite once visuals are locked.
- **Backend integration** at the API level — these flows assert the DOM contract. Backend state assertions belong in the Python pytest suite hitting `service.*` / `Api.*` directly.
- **Performance** — spectrum render time, live-log throughput beyond the RUN2 baseline.
- **Accessibility** — keyboard nav, focus, ARIA, contrast.
- **Comprehensive edge cases** (~30 more) — corrupt schematic, audit-failure on Testbench, every Settings field, cloud-LLM-enabled flows beyond X4/X5. Add these incrementally now that the wiring is real.

---

# Appendix · `HOOKS.md` drift (to reconcile separately)

`ui/HOOKS.md` documents the *intended* contract; several entries no longer match the shipped DOM. The flows above already follow the DOM; this list is the to-do for a `HOOKS.md` reconciliation commit:

| HOOKS.md says | Shipped DOM | Affected flows |
|---|---|---|
| topbar `project-meta` populated from `user_context.json` | hardcoded sample values | J1, J2, PR1 |
| `save-project` calls a backend save | `setTimeout` affordance; no `save_project` bridge method | X6 |
| stale marker `.stale-dot` / `StaleChip` | rail uses `.stale-pill` | J4, X2 |
| disclaimer `data-bind="precompliance-disclaimer"` | `.disclaimer` (no data-bind) | X1 |
| run modes `smoke\|corner\|full` + `corner-variants-count` | `dry-run\|local-run` + separate corner-sweep toggle | RUN1 |
| spectrum `toggle-trace-sim\|measured\|limit` on `#spectrum-plot` | `toggle-trace-peak\|qp\|avg\|limit`, inline SVG | RES1 |
| `reopen-recommendation`, `sort-findings` | not implemented | FIND1, FIND3 |
| `toggle-export-option` / `export-options` | not implemented | REP1 |
| `pcb_dielectric_mil` / `pcb_prepreg_mil` | `pcb_dielectric_mm` / `pcb_prepreg_mm` | IC2 |
| single `#privacy-indicator` | rendered twice with the same id (rail + topbar) | X4 |
| `testbench-generated-at` | not rendered; `testbench-status` pill instead | PS6, TB1 |
