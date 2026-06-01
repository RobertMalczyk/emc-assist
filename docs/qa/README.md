# QA flows

Authoritative source for the M3 UI's user flows — used both as **automated-test source** (Gherkin maps to Playwright / Cucumber later) and as a **manual QA / user-walkthrough script**.

## What lives here

- **[`QA_FLOWS.md`](QA_FLOWS.md)** — the flow inventory, **reconciled against the wired build on 2026-05-23**. Core depth (~30 flows): end-to-end journeys (`J*`), cross-cutting concerns (`X*`), and per-screen flows (`PR*` / `IC*` / `PS*` / `RUN*` / `RES*` / `FIND*` / `REP*`). Each flow carries a Gherkin (Given/When/Then) body, a **status tag** (✅ wired · ⚠️ partial · ⏳ deferred to M11), acceptance criteria tied to the **shipped DOM** (not the aspirational `ui/HOOKS.md`), and notes. The file is the single source of truth — read it top-to-bottom for context, then jump by flow ID. A closing appendix lists the `HOOKS.md` ↔ DOM drift still to reconcile.

## Companion docs (read alongside)

| File | What it gives a flow author |
|---|---|
| [`../design/ui_design_brief.md`](../design/ui_design_brief.md) | The functional brief — screens, workflow, principles. |
| [`../design/ui_backend_contract.md`](../design/ui_backend_contract.md) | Per-screen: what's read, what's actioned, what's written. |
| [`../design/ui_integration.md`](../design/ui_integration.md) | The handoff contract from design HTML to the pywebview shell + service layer. |
| [`../../ui/HOOKS.md`](../../ui/HOOKS.md) | The DOM contract — every `data-action` / `data-bind` / `data-field` / `data-state` name the Gherkin references. |
| [`../11_roadmap.md`](../11_roadmap.md) | M3 status — which screens are wired vs. still on hardcoded sample data. |

## Scope (intentional, see `QA_FLOWS.md` intro)

- **Depth:** core (~30) — not comprehensive (60+). All analysis screens are now wired to real backend artifacts (per `docs/11_roadmap.md`), so the gate on deeper coverage is reviewer time, not "is it wired". Flows whose target feature isn't built in the M3 shell are tagged ⏳ **deferred (M11)** and kept as rebuild requirements, not current build gates.
- **Focus:** state / data integrity (pipeline gating, stale propagation, override persistence) and backend wiring (every `data-action` lands on the right `Api` method, every `data-bind` receives the matching payload). UI correctness and a11y are **not** covered here — they're visual-regression / manual-audit territory.
- **Skipped on purpose:** theme / density visual switching, and deep coverage of Testbench review (read-only), Settings (beyond LTspice path + privacy), and Report (beyond format/locate). The cloud-LLM toggle's observable surface — the privacy-indicator state — is exercised by `X4`.

## Personas (used as starting state)

Five personas appear in the flows: first-time user (no projects, no LTspice), returning user with projects, power user editing parasitics, reviewer auditing a finished project read-only, and offline / cloud-LLM disabled.

## How this turns into tests

Each flow's acceptance criteria are mechanically checkable: a hook exists, a value matches, an action fires the matching bridge method. The current shell is pywebview + a React app; the bridge is `window.pywebview.api.*` (`src/emc_assistant/ui/bridge.py`). The analysis screens are **already wired** to that bridge (`ui/src/screens/*.jsx`), so the flows assert against real behaviour, not a spec-in-waiting. The natural runner is **Playwright** driving the built bundle (`src/emc_assistant/ui/web/`) — or, with a bridge stub, the React app's Vite dev mode. No automated suite exists yet; this doc is what it gets written from.
