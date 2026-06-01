# Documentation index

Map of the `docs/` folder. **`11_roadmap.md` is authoritative** for milestone
status; when any doc disagrees with the roadmap + git, trust those.

## Canonical concept & spec series (root)

The numbered series is the canonical project specification — kept at the docs
root and referenced by number across the codebase. Do not relocate or renumber.

| Doc | What |
|---|---|
| [`00_product_brief.md`](00_product_brief.md) | Product brief / positioning |
| [`01_mvp_scope.md`](01_mvp_scope.md) | MVP scope — in and out |
| [`02_user_groups_and_features.md`](02_user_groups_and_features.md) | User groups & feature set |
| [`03_architecture.md`](03_architecture.md) | Module map & architecture |
| [`04_agent_contracts.md`](04_agent_contracts.md) | Specialist-agent contracts |
| [`05_knowledge_ingestion.md`](05_knowledge_ingestion.md) | Knowledge base / RAG ingestion |
| [`06_local_ltspice_runner.md`](06_local_ltspice_runner.md) | Local LTspice runner |
| [`07_ui_and_interactive_recommendations.md`](07_ui_and_interactive_recommendations.md) | UI & interactive recommendations |
| [`08_decision_log.md`](08_decision_log.md) | Decision log (dated, with rationale) |
| [`09_security_privacy_licensing.md`](09_security_privacy_licensing.md) | Security, privacy & licensing |
| [`10_result_handling.md`](10_result_handling.md) | Result handling (`.log`/`.raw`, metrics) |
| [`11_roadmap.md`](11_roadmap.md) | **Milestone-by-milestone status (authoritative)** |

## Subfolders

| Folder | What |
|---|---|
| [`analysis/`](analysis/) | Generated codebase analysis (`codebase-analysis` skill), Phases 1–7 — system overview, data structures, data flow, algorithms, key functions, Q&A/pitfalls, and a verification report — every claim carries a `VERIFY: file:line` tag (230 tags, all validated) |
| [`concepts/`](concepts/) | Deep-dive concept explainers (e.g. the quasi-peak detector) |
| [`design/`](design/) | UI & internal-engineering design docs — the M3 UI design brief, the UI↔backend contract, the design→app integration handoff, design-session prompts, and the logging-seam design |
| [`user_guide/`](user_guide/) | End-user guides — [`backend.md`](user_guide/backend.md) (CLI/pipeline) and [`frontend.md`](user_guide/frontend.md) (desktop app), grounded in `case_003` |
| [`qa/`](qa/) | QA flow inventory ([`QA_FLOWS.md`](qa/QA_FLOWS.md)) — each flow tagged wired / partial / deferred-M11 |
| [`test_cases/`](test_cases/) | Worked-example references (first buck case, PCB-parasitics sources) |
