# Handoff: EMC Assistant — UI v2

A desktop pre-compliance EMC analysis assistant. Local-first, with optional cloud LLM. The user's flow walks a switching-power-supply project through: import schematic → pick parasitics → review generated LTspice testbench → run sweeps → review spectrum vs. limit lines → triage findings & accept recommendations → export a report.

---

## About these files

The files in this bundle are **design references created in HTML** — a working React/Babel prototype showing the intended look, structure, and behaviour. **They are not production code to copy directly.**

Your task: **recreate these designs in the target codebase's existing environment** (Electron + React, Tauri, native, web — whatever the host app is). Use the host codebase's established patterns, components, state management, and routing. If no environment exists yet, pick whatever framework best fits the project (Electron + React + Vite is a reasonable default for a desktop-feeling app like this).

The included `app.jsx`, `components.jsx`, etc. compile in-browser through Babel standalone. **Do not ship Babel-standalone.** Treat the JSX as readable pseudocode that happens to render.

`HOOKS.md` is the most important file in this bundle — it is the **DOM contract** between the design and the wiring layer. Every backend-bound element has stable `id` / `data-action` / `data-field` / `data-bind` attributes documented there. The wiring layer (a thin `app.js` over `window.pywebview.api.*` round-trips) reads/writes these attributes; preserve the contract when you reimplement.

---

## Fidelity

**High-fidelity.** Final colours, type, spacing, severity palette, density modes, dark+light themes, and all eleven screens are spec'd. The prototype includes a Tweaks panel that lets a reviewer tune theme / density / accent hue / sidebar width / uncertainty viz / severity palette / pipeline progress / sample project at runtime — those are exploratory knobs, **not** required ship features (keep theme + density as user settings; the rest can be dropped or hidden).

Recreate the UI pixel-faithfully using the host codebase's library stack. Match colours, spacing scale, and density tokens exactly (see "Design tokens" below). Where the prototype draws SVG (diagram, spectrum plot), implementations are free to use a charting library (uPlot, Recharts, D3) as long as the visual result and the `data-bind` slot ids match `HOOKS.md`.

---

## Aesthetic direction

Spectrum-analyser / scope-firmware UI. Dense, monospace-forward, calm. Think Tektronix front panel, not consumer SaaS.

- **No gradients, no glassmorphism, no large rounded cards.** 4–6px radii.
- **Hairline borders** (1px, low-contrast) separate panels — not shadows.
- **Monospace numbers** everywhere (frequencies, voltages, margins, counts) using JetBrains Mono with `font-variant-numeric: tabular-nums`.
- **Inter** for UI prose; mono for any value, identifier, or measurement.
- **Accent purple** (`oklch(0.70 0.18 268)`) used sparingly — primary action, current selection, "sim" trace colour. The accent hue is themable via `--accent-h`.
- **RAG severity** by default; CB-safe palette available via `[data-severity="cb-safe"]`.

---

## Tech the prototype uses (and why)

| Prototype uses | What to ship |
|---|---|
| React 18 + Babel-standalone (in-browser JSX) | React in the host codebase's normal build chain, or whatever framework it uses |
| Inline `<script type="text/babel">` per file | Normal module/build setup |
| Hand-drawn SVG diagram + spectrum plot | Free to swap for a charting lib as long as `id`/`data-bind` slots match `HOOKS.md` |
| `data-tip` attribute for tooltips | Host codebase's tooltip primitive |
| `useTweaks` hook + `<TweaksPanel>` | **Don't ship** — review-only knob panel |

---

## Screens (in pipeline order)

`STAGE_ORDER` in `data.jsx` is the canonical sequence. Each screen lives in `screens/<name>.jsx`. **Detailed per-screen actions / fields / binds are in `HOOKS.md` — read that file alongside this README.**

### Workspace

1. **Projects** (`screens/projects.jsx`) — Project list table. Filter, open folder, new project, open existing.

### Analysis (pipeline, per project)

2. **Import & context** (`screens/import.jsx`) — Drop schematic file, fill DC operating point + testbench wiring + PCB stackup form. Auto-detected facts shown alongside user-editable fields. Primary action: "Estimate parasitics →".
3. **Parasitic selection** (`screens/parasitics.jsx`) — **The most important screen.** Per-net R/L/C table with confidence indicators, include/skip per net, inline override dialog, override log, AI suggest-negligible, block diagram with selectable nets, inspector panel. Primary action: "Compose testbench →".
4. **Testbench review** (`screens/testbench.jsx`) — Read-only audit of the generated testbench (wiring/parasitics/signals), with toggleable raw `testbench.cir` preview. Primary: "Continue to run →".
5. **Run** (`screens/run.jsx`) — Run-mode selector (smoke / corner sweep / full), live progress, three variant cards (min/typ/max), pre-run warnings, live log with INFO/WARN/ERR/OK levels, expandable sim-settings (transient + solver). Primary: "Run pipeline" → "View results →" when done.
6. **Results** (`screens/results.jsx`) — Verdict / narrative card, top stats (peak, worst margin, corner span, Vout ripple), spectrum plot (sim / measured / limit traces toggleable), variant ranking table, before/after overlay. Primary: "Review findings →".
7. **Findings & recommendations** (`screens/findings.jsx`) — Filter pills (open/accepted/rejected/all), per-finding card with severity + confidence + status, accept/reject/reopen, expandable evidence/proposal/assumptions/limitations/sources. Primary: "Generate report →".
8. **Report & export** (`screens/report.jsx`) — Format segmented (PDF / HTML / Markdown), live preview pane, per-section include toggles, meta (sections/findings/sources/figures/size).

### Foot

- **Settings** (`screens/settings.jsx`) — LTspice path detect/browse, cloud-LLM toggle (with budget + provider), strip-identifiers, telemetry, project-default sim settings, knowledge sources, About.

### Tier 3 (coming-soon previews)

- **Live Lab Assistant** (`screens/preview-lab.jsx`) — placeholder, `data-state="coming-soon"`, `data-feature-gate="live-lab-assistant"`.
- **Engineer Training** (`screens/preview-training.jsx`) — same shape, `data-feature-gate="engineer-training"`.

---

## App shell

`app.jsx` renders three things:

- **Left rail** (`<aside id="nav-rail">`) — three sections: **WORKSPACE** (Projects), **ANALYSIS** (the 7 pipeline stages, numbered 01–07, each with `done/active/locked/stale` state), **COMING SOON** (Tier 3 previews). Foot: Settings + privacy indicator. Width is themable (56–280px via `--rail-w`).
- **Top bar** (`<div id="topbar">`) — breadcrumbs · project meta row (topology / fsw / Vin/Vout / pipeline stage) · privacy indicator · theme toggle.
- **Screen host** (`<div id="screen-host" data-active-screen={id}>`) — the active screen mounts here.

Pipeline progress is gated: a stage's nav item is **locked** (visibly dimmed, lock dot, disabled) until earlier stages complete. The Tweaks panel includes a "Pipeline progress" select that fast-forwards to any stage for reviewers — drop this in production; let the real pipeline state drive it.

---

## Design tokens (exact values)

All in `styles.css` under `:root` and theme blocks. **Copy these into the host codebase's token file verbatim.**

### Type

```
--font-mono : "JetBrains Mono", "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace;
--font-sans : "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
```

Scale: `--t-2xs:10 · --t-xs:11 · --t-sm:12 · --t-md:13 · --t-base:14 · --t-lg:16 · --t-xl:20 · --t-2xl:26 · --t-3xl:34` (all px).

Mono usage: every number, identifier, file path, frequency, voltage, percent, count. Apply `font-variant-numeric: tabular-nums` so columns of numbers align.

### Accent (themable hue)

```
--accent-h    : 268;             /* purple by default */
--accent      : oklch(0.70 0.18 var(--accent-h));
--accent-soft : oklch(0.70 0.18 var(--accent-h) / 0.18);
--accent-dim  : oklch(0.70 0.18 var(--accent-h) / 0.08);
--accent-fg   : oklch(0.99 0.02 var(--accent-h));
```

### Severity (RAG, default)

```
--sev-high : oklch(0.66 0.20 25);   /* red    */
--sev-med  : oklch(0.78 0.16 75);   /* amber  */
--sev-low  : oklch(0.70 0.16 145);  /* green  */
--sev-info : oklch(0.72 0.10 230);  /* blue   */
```

CB-safe alternative is in `styles.css` under `[data-severity="cb-safe"]`.

### Traces (spectrum plot)

```
--trace-sim   : var(--accent);              /* purple    */
--trace-meas  : oklch(0.78 0.16 145);       /* green     */
--trace-limit : oklch(0.66 0.20 25);        /* red       */
```

### Density (three modes via `[data-density]`)

| Token | compact | default | comfortable |
|---|---|---|---|
| `--row-h` | 28px | 32px | 36px |
| `--pad-3` | 10px | 12px | 14px |
| `--pad-4` | 12px | 16px | 18px |
| `--pad-5` | 18px | 24px | 28px |
| `--t-base` | 13px | 14px | 14px |

Spacing scale: `--pad-1:4 · --pad-2:8 · --pad-3:12 · --pad-4:16 · --pad-5:24 · --pad-6:32`.

### Radii

```
--radius    : 4px;   /* default — buttons, inputs, pills */
--radius-lg : 6px;   /* cards, panels */
```

No larger radii. No shadows beyond hairlines.

### Theme: Dark (default)

```
--bg          : #0a0d12;
--bg-2        : #0d1117;
--panel       : #11151c;
--panel-2     : #161b24;
--panel-3     : #1c2230;
--border      : #232a39;
--border-strong : #2f3a4f;
--grid        : #1a2030;
--text        : #e6edf3;
--text-dim    : #b1bcce;
--text-muted  : #6f7c91;
--text-faint  : #4a5468;
--plot-bg     : #07090d;
--plot-grid   : rgba(255,255,255,0.05);
--plot-axis   : rgba(255,255,255,0.18);
```

### Theme: Light

See `styles.css` under `[data-theme="light"]` for the corresponding token set.

---

## Interactions & behaviour

Most behaviour is documented per-screen in `HOOKS.md`. High-level rules:

- **Routing is `data-action="goto-screen"` + `data-screen-target="<id>"`.** No URL hash in the prototype; the wiring may add one, but the IDs are the routing keys.
- **Forms autosave to the backend** via `data-field` → `save_context` / `save_settings`. No explicit "Save" except where shown (Import → "Save context").
- **Pipeline gating** — a stage is reachable only when earlier stages report complete. Locked items get `data-state="locked"`, `disabled`, `cursor: not-allowed`, and a tooltip explaining why.
- **Stale state** — when an upstream input changes, downstream stages get `data-state="stale"`; the wiring marks them and shows a re-run prompt.
- **Override dialog** is a modal anchored to a parasitic-table cell; carries `data-override-net` + `data-override-key`; commits via `commit-override` action.
- **Findings cards** expand on head click, accept/reject per card. Filter pills swap visible set without navigation.
- **Theme toggle** flips `data-theme` on `<html>`; respect on first load by reading the user's last setting (or system preference).
- **Privacy indicator** in rail-foot AND topbar always shows the cloud-LLM state. Click → jump to Settings → Privacy section.
- **Tooltips** — every actionable element with a non-obvious purpose carries `data-tip="..."`. Wire to the host codebase's tooltip primitive on hover/focus.

---

## State management

The prototype uses React `useState` as a placeholder. In the real app, replace each with backend-bound state:

- `currentProject` ← `pywebview.api.get_current_project()`
- `pipelineStage` ← `project.status.stage` (drives nav-rail gating)
- `llmEnabled` ← `settings.llm_enabled` (drives privacy indicator)
- `screen` — local router state, but persist last-visited per project so reopening a project lands on its last stage
- Per-screen artefacts (parasitic table, findings list, results, etc.) come from JSON artefacts in the project folder; the wiring stamps them into `data-bind` slots

The prototype's `useTweaks` hook is **review-only** — the EDITMODE-BEGIN/END block in `index.html` is for the design-tool's persistence, not your app. Drop both.

---

## Assets

- **Fonts** — `Inter` and `JetBrains Mono` from Google Fonts. Self-host in the desktop app (no CDN calls at runtime). Both are SIL Open Font License.
- **Icons** — inline SVGs in `icons.jsx` (`folder`, `lab`, `brain`, `gear`, `sun`, `moon`, `check`, plus the per-stage pipeline icons). Re-export as your codebase's icon component, or copy the SVG paths. No external icon font.
- **No logos / branded imagery** in the prototype — the rail head is a plain "EMC" text mark; replace if/when a logo exists.
- **Diagram & spectrum** are SVG drawn at runtime in `diagram.jsx` and `spectrum.jsx`. Both are placeholders for charting work; the slot ids (`#spectrum-plot` etc.) and trace classes (`.trace-sim`, `.trace-meas`, `.trace-limit`) are the wiring contract.

---

## Files in this bundle

| File | What it contains |
|---|---|
| `README.md` | This file |
| `HOOKS.md` | **DOM-attribute contract — read this** |
| `index.html` | Loader: imports React + Babel + JSX modules, mounts `<App />` into `#root` |
| `app.jsx` | App shell: rail, topbar, screen router, tweaks panel mount |
| `components.jsx` | Shared primitives (cards, pills, buttons, badges, etc.) |
| `data.jsx` | `STAGES`, `STAGE_ORDER`, sample project data |
| `diagram.jsx` | Switching-supply block diagram with selectable nets |
| `spectrum.jsx` | EMI spectrum plot SVG (sim / measured / limit traces) |
| `icons.jsx` | Inline SVG icon set |
| `styles.css` | Full design-system stylesheet (tokens + components + screens) |
| `tweaks-panel.jsx` | Review-only knobs — **do not ship** |
| `screens/*.jsx` | One file per screen (`projects`, `import`, `parasitics`, `testbench`, `run`, `results`, `findings`, `report`, `settings`, `preview-lab`, `preview-training`) |

---

## Running the prototype locally

`index.html` is self-contained — open it in any modern browser, no build step. The CDN scripts (React 18.3.1 + Babel 7.29.0 pinned with SRI hashes) take ~1s to compile the JSX on first load.

---

## Suggested implementation order

1. **Tokens + theme switching** — port the CSS variables, get dark↔light flipping correctly. Validate against both screenshots before touching screens.
2. **App shell** — rail, topbar, screen-host. Stub all screens as `<div data-screen="...">name</div>`. Verify nav gating and breadcrumb wiring.
3. **Projects** screen — easiest, drives the rest.
4. **Import & context** — biggest form; settles the form patterns for Settings later.
5. **Parasitic selection** — most complex screen; settles the table/inspector/override-dialog patterns.
6. **Testbench review → Run → Results → Findings → Report** — these reuse patterns from earlier screens.
7. **Settings** — reuses Import's form primitives.
8. **Preview screens** — trivial; just placeholder with the `data-feature-gate` attribute.

Refer to `HOOKS.md` continuously — it is the single source of truth for the wiring contract.
