# ANALYSIS 06 — Verification & Review (EMC/LTspice Assistant)

> `codebase-analysis` skill, Phase 7. Records the cross-document verification of
> the whole `docs/analysis/` set against the live code.

## 1. Method

Every claim in Phases 1–6 carries an inline `VERIFY` tag (`path:line`). Each tag is
checked two ways:
1. **The skill's verifier** — `verify_analysis.sh` confirms the file exists and
   the line is in range  (`verify_file_exists`
   [VERIFY: .claude/skills/codebase-analysis/verification/verify_analysis.sh:40],
   `verify_line_number`
   [VERIFY: .claude/skills/codebase-analysis/verification/verify_analysis.sh:56]).
2. **An independent loop** — re-extracts every unique tag and re-checks
   file-exists + line-in-range, catching anything the vendored script's
   `set -e` early-exit would mask.

> Note: the vendored `verify_analysis.sh` has a `set -e` quirk that halts on the
> first non-resolving tag; it is run with that neutralised to obtain the full
> per-document summary, and the independent loop is the authoritative check.

## 2. Result (all green)

| Document | Unique tags | Checks | Failed |
|---|---|---|---|
| ANALYSIS_00 — System Overview | 62 | 124 | 0 |
| ANALYSIS_01 — Data Structures | 41 | 82 | 0 |
| ANALYSIS_02 — Data Flow | 29 | 58 | 0 |
| ANALYSIS_03 — Algorithms | 28 | 56 | 0 |
| ANALYSIS_04 — Key Functions | 43 | 86 | 0 |
| ANALYSIS_05 — Key Questions | 23 | 46 | 0 |
| **Total (Phases 1–6)** | **226** | **452** | **0** |

`checks = 2 × tags` (file-exists + line-in-range per tag). One placeholder tag
was found and fixed during Phase 1 (an explanatory placeholder of the form
`VERIFY` `path:line` written in prose); no other discrepancies remained.

## 3. Coverage

- **Phase 1** overview, **Phase 2** data structures, **Phase 3** data flow,
  **Phase 4** algorithms, **Phase 5** key functions, **Phase 6** Q&A/pitfalls.
- The deterministic pipeline is the source of truth that every claim resolves to
  (e.g. the six-stage `run_pipeline`
  [VERIFY: src/emc_assistant/service/pipeline.py:159] and the 11-agent roster
  [VERIFY: src/emc_assistant/agents/orchestrator.py:45]).

## 4. Known limitations of this analysis

- **Line numbers drift.** Tags are valid at generation time; re-run the verifier
  after any source edit. Re-validate with, from the repo root:
  `bash .claude/skills/codebase-analysis/verification/verify_analysis.sh docs/analysis/ANALYSIS_00-SystemOverview.md`.
- **In-range ≠ semantic match.** The automated check proves a tag points at a
  real, in-range line, not that the cited line still expresses the claim; the
  prose was written from the actual bodies, but a future refactor can move logic
  without breaking the file:line check.
- **Scope.** This set documents the Python package `src/emc_assistant/`; it is a
  code-structure companion, not a replacement for the canonical specs in `docs/`
  (notably `docs/03_architecture.md` and `docs/11_roadmap.md`).

## 5. Open questions / next steps

- [x] Reconcile the two detector-margin code paths (the disagreement noted in
  ANALYSIS_05) — **done 2026-05-24**: unified on `conducted_emi_spectrum`
  [VERIFY: src/emc_assistant/results/detectors.py:751]. Residual: Mode-3
  narrow-tone under-read (`tasks/detector_selectable.md`).
- [ ] Optional deeper Phase 4/5 per-module deep-dives (e.g. a dedicated
  `ALGORITHM_*` file for the STFT envelope + QP/avg meter) if needed.

---

Phases 1–7 complete. All 226 verification tags resolve (452/452 checks).
