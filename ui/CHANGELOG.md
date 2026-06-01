# Changelog — EMC Assistant handoff package

Versions are tagged to match the project name (`EMC UI V2_N`). Higher = newer.

---

## V2_3 — 2026-05-20

### Added
- **Save project** — new button in the topbar, visible on every screen.
  - Hook: `data-action="save-project"`, carries `data-project-name`.
  - Status slot: `data-bind="project-save-status"` with `data-save-phase` reflecting `idle` | `saving` | `saved-just-now`.
  - Live "saved · Xm ago" timestamp updates every 30s.
  - Keyboard shortcut: ⌘S (mac) / Ctrl+S (win/linux).
  - New icon: `save` added to `icons.jsx`.
- `HOOKS.md` — App-shell table updated to document `save-project` + `project-save-status`.
- `QA_FLOWS.md` — new cross-cutting flow **X6** covers Save (visible everywhere, status truthful, ⌘S/Ctrl+S works, no-double-fire while saving, timestamp updates on tick). New per-screen flow **PR2b** covers "Open project" (adopt a `.emcproj` from disk).
- **Project principle PP5** added: persistence transparency — save state must be visible from every screen.

### Changed
- **Projects screen** — "Open folder…" button renamed to **"Open project"** for clarity. The `data-action="open-project-folder"` hook is unchanged so wiring continues to work.
- `HOOKS.md` — Projects screen entry updated to reflect the rename.

### Files changed
- `app.jsx` — added `SaveProjectButton` component to the topbar
- `icons.jsx` — added `save` glyph
- `screens/projects.jsx` — button rename
- `HOOKS.md` — documentation updates

### Unchanged
- _(no flows or styling untouched this release beyond the additions above)_

---

## V2_2 — initial handoff

### Included
- Full design prototype (React/Babel) with 11 screens: Projects, Import, Parasitic selection, Testbench, Run, Results, Findings, Report, Settings, plus two Tier-3 preview screens (Live Lab, Engineer Training)
- App shell: left rail with pipeline gating, topbar with breadcrumbs + project meta + privacy indicator + theme toggle
- `styles.css` — full design system: tokens, themes (dark/light), density modes (compact/default/comfortable), severity palettes (RAG + CB-safe)
- `HOOKS.md` — DOM-attribute contract for the wiring layer
- `README.md` — orientation, fidelity, screen-by-screen guidance, design tokens, suggested build order
- `QA_FLOWS.md` — ~30 QA flows in Gherkin + manual checklist + acceptance criteria, organised as 4 end-to-end journeys, 5 cross-cutting flows (incl. pre-compliance disclaimer, stale propagation, privacy transparency, local-first), and per-screen flows weighted toward Parasitic selection
