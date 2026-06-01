# Roadmap

Milestones are sliced so each one is independently shippable and reviewable on its own commit.

## M0 — skeleton and deterministic core (done 2026-05-13)

- project structure,
- CLI,
- data schemas,
- seed knowledge loader,
- parasitic calculators,
- report generator.

## M1 — conducted-EMI testbench (done 2026-05-13)

- LISN generator,
- cable model,
- trace / via / cap ESR/ESL fragments,
- testbench netlist,
- local LTspice runner (`dry-run` and `local-run`),
- log parser.

## M2 — recommendations and sweeps (done 2026-05-13)

- filter variants,
- parameter sweeps,
- variant ranking,
- JSON recommendations,
- before/after report sections.

## M2.5 — pipeline hardening, demo-ready (done 2026-05-13)

- golden buck example,
- user-netlist → fragment preprocessor,
- `.raw` parser (ASCII + binary real / complex),
- metrics module + Measurements section in the report,
- one-shot `pipeline run`,
- `raw inspect` / `raw export-csv` CLI.

## M2.6 — LTspice integration (done 2026-05-13)

- `.meas` directives auto-emitted by the composer,
- band metrics wired into `summarize_default_metrics`,
- mock LTspice in CI,
- robust `.log` parsing for `.meas` blocks after `.step`,
- LTspice error surfacing (convergence, license, missing model, syntax),
- "First local-run" section in the README.

## M2.6.1 — real-LTspice loop closure (done 2026-05-14)

- composer auto-wires `V_RAIL → X_LISN → X_CABLE` when `user_context.testbench_wiring` is present and the user accepts via interactive prompt or `--accept-wiring`,
- `netlist.fragment` strips a named user source so the LISN chain owns the DUT supply,
- `.raw` parser handles modern LTspice "compressed real" layout (time = 8 B double, data vars = 4 B float),
- `.raw` parser tolerates over-reported `No. Points`,
- failure classifier picks up `File not found.` as `[missing_model]`,
- buck demo on real LTspice 26.0.2: V(MEAS) peak 3.41 V, vp2p 7.10 V, vrms 0.643 V.

## M2.7 — LLM provider seam and first LLM-assisted recommendation (done 2026-05-14)

- abstract `LlmAssistant` interface (`OpenAiAssistant` / `DeterministicAssistant` / `StubAssistant`),
- `--llm openai|none` CLI flag; `none` is the deterministic fallback,
- one LLM call per `pipeline run` that takes `(problem_context + parasitic estimates + sim metrics + top-K retrieved snippets)` and writes the report's Recommendations section,
- keyword/substring retrieval over seed `.jsonl` rules (vector retrieval added in M2.8),
- prompt template `prompts/recommendations_v1.md` with strict guardrails (no fake values, citations required, every claim mapped to a `Rule_ID` or `engineering_estimate`),
- copyright-safe redaction before the LLM call: retrieved snippets reduced to `rule_id` + `source_id` + our summary + ≤ 200-char excerpt only when `allowed_use` permits,
- AI cost budget: `--llm-budget-usd <amount>` flag (default 1.00) aborts before any network I/O when the estimate exceeds the cap; M2.9 added a run-level `BudgetTracker` for cumulative spend,
- privacy log: every OpenAI call recorded in `results/llm/<run-id>.jsonl` (prompt, response, model, token counts, timestamp),
- live buck-demo smoke test: 5 LLM recs, zero hallucinations, $0.0036 cost.
- Tests grew by ~14 (CI uses a stubbed `LlmAssistant`; live OpenAI runs are opt-in).

## M2.8 — embedded knowledge base (done 2026-05-14)

- chunker for `.md`, `.txt`, `.html`, `.jsonl`, `.pdf` (PDF behind optional `[pdf]` extra → `pdfminer.six`),
- local embedding via `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim) behind an `Embedder` interface so cloud providers can swap in later,
- pure-numpy `NumpyVectorIndex` with cosine similarity (no FAISS / Chroma dependency — chosen during the milestone, see decision log),
- new schemas `knowledge_pack.schema.json` and `chunk_index.schema.json`,
- CLI: `knowledge index` / `knowledge search <query>` / `knowledge build-pack <project>`,
- `knowledge/{raw_sources, user_private_sources, licensed_sources, processed}/` tier directories with READMEs,
- `.asc → .cir` auto-converter (`netlist.asc_converter`) wired into the composer's fragment-prep path,
- M2.8.1: seed-PDF batch fetcher + `knowledge/INDEX_STATUS.md` (22 PDFs auto-downloaded; manifest tracks the 15 that anti-bot / SSL chains blocked),
- M2.8.2: CISPR-style FFT post-processing (`compute_spectrum`, `compute_band_peaks`) + DM probe + `dm_*` `.meas` directives,
- M2.8.3: dual-LISN as the default topology with the `0 → DUT_GND` fragment ground rename + DM/CM probes,
- User-supplied 5 DC/DC conducted-EMI PDFs ingested (SRC-071..SRC-075); index grew **170 → 2257 → 2472 chunks**.

## M2.9 — specialist agents per area (done 2026-05-14)

- 10 active specialist agents in `src/emc_assistant/agents/`: dcdc, filtering, power_integrity, decoupling, parasitics, stackup, high_speed, mixed_signal, ic_vendor, layout_risk,
- 2 parked stubs (acdc, analog) kept in `prompts/agents/` for future converter types — not loaded by the orchestrator,
- schema audit logged in `docs/08_decision_log.md`: existing `agent_task` is the *input* contract, `analysis_result` is project-wide; new `schemas/agent_finding.schema.json` covers the per-agent output (findings / risks / recommendations / missing_data / simulation_requests / sources / limitations / confidence / llm_generated),
- orchestrator (`agents/orchestrator.py`) fans out to the 10 agents, writes `results/findings/<area>.json`, handles BudgetExceeded + LLM failures by falling back to deterministic per-agent paths so the run always produces 10 sections,
- run-level `BudgetTracker` (`llm/budget.py`) is threaded into `OpenAiAssistant.complete()`; cumulative spend across all 11 LLM calls (1 recommendations + 10 agents) shares the user's `--llm-budget-usd` cap,
- per-area prompt templates rewritten in English with concrete I/O contracts in `prompts/agents/`,
- Markdown report grows a "Specialist findings (per area)" section with 10 subsections, each citing the agent and its sources,
- 30 new tests (244 total), no live LTspice or OpenAI required in CI.

## M2.9.1 — per-agent RAG retrieval (done 2026-05-16)

Closes the M2.9 retrieval weakness surfaced by the case_002 smoke test: all 11 agents shared one problem-context vector query, so the substring keyword-filter leaked broadly-relevant docs (e.g. `SRC-046` LVDS handbook into DC/DC agents).

- `knowledge/retrieve.py`: `_retrieve_via_vector_index` refactored to take an explicit query string; `_retrieve_by_tokens` core extracted (shared by `retrieve_top_k` + the keyword fallback); new `retrieve_for_keywords(keywords, problem_context, ...)` builds a focused query from an agent's keyword list + topology and runs the vector index (or keyword-token fallback).
- `AgentContext` gains a `retrieve_fn` hook; `Agent._select_snippets()` calls it with the agent's own `keywords` when set, else falls back to keyword-filtering the shared pool (and on empty result or any exception).
- All 11 agents switched from `select_snippets_by_keywords(ctx.snippets, ...)` to `self._select_snippets(ctx)`.
- CLI builds a real `sentence-transformers` embedder once per LLM run and threads a per-agent `retrieve_fn` closure into `AgentContext`; tests inject a stub embedder so CI never loads the model.
- 8 new tests (322 total): `retrieve_for_keywords` vector + keyword fallback + distinct-keyword distinctness; `_select_snippets` retrieve_fn preference + 3 fallback paths (no fn / empty result / exception).

## M2.10 — parasitics agent augments the testbench (done 2026-05-15)

- `netlist/topology.py` does deterministic net-structure analysis on the user fragment (power-supply candidates, return candidates, switching nodes, capacitor terminals),
- `schemas/parasitic_injection.schema.json` defines the agent → composer contract: instance_name, subckt_name (TRACE_RLC | VIA_L | CAP_ESR_ESL), nets, rationale, rule_id, parasitic_id, corner,
- `AgentFinding` gains an `injections: list[ParasiticInjection]` field; the parasitics agent's deterministic fallback emits a default plan (series TRACE_RLC between cable output and DUT supply); the LLM-path agent can extend it,
- composer reroutes the cable to an intermediate net `n_dut_in_pre` when an injection plan is present, then emits the agent-proposed X-instances; with an empty plan the M2.6.1 wiring is byte-equivalent,
- new CLI flags `--accept-parasitics` / `--no-parasitics` independent from `--accept-wiring`,
- audit file `generated/parasitics_wiring.json` records the plan that drove the simulation,
- report grows a "Parasitic injection plan (M2.10)" section,
- 19 new tests (263 total).
- Closes M2.6.1 limitation "all 11 corner-variants rank identically" — variants now vary by ~0.2 % on V(MEAS) for the buck demo (small because the buck's existing input filter dominates over the 10 nH trace parasitic; honest engineering finding).

## M2.10.1 — feature-keeper / signal-map agent (done 2026-05-15)

- `schemas/signal_map.schema.json` defines the user-signal contract (name, kind, expr, unit, target_band, source, confidence, rationale),
- `src/emc_assistant/netlist/signals.py` auto-detects signals from `.asc` FLAG labels (latin-1 / cp1252 / utf-8 / utf-16-le tolerant) + `.cir` net-name heuristics. Merges with user-declared `signals[]` in `user_context.json` (user > asc > cir),
- new CLI flags `--accept-signals` / `--no-signals`; resolver prints the proposal, accepts via flag or TTY, **persists back to `user_context.json`** so subsequent runs don't re-prompt, and writes `generated/signals.json` audit,
- composer emits per-signal `.meas TRAN <name>_peak / _rms / _avg` directives so the LTspice `.log` carries the user's vocabulary alongside the canonical `v_meas_*` / `dm_*` / `cm_*`,
- new 11th specialist agent `signal_map_agent` (orchestrator `AGENT_CLASSES` 10 → 11) refines the map (renames, target bands, current-probe proposals) via LLM; deterministic fallback emits low-priority hints,
- report grows a "Tracked user signals (M2.10.1)" section with per-signal table,
- 24 new tests (287 total).

## M2.10.2 — prompt hardening + agent net-name plumbing + schematic plotter (done 2026-05-15)

Closes three issues observed in the M2.10.1 buck smoke test:

- **Placeholder leakage in injection plans** — the parasitics agent's LLM response emitted literal `<user_supply_net>` strings in the `nets` array because the prompt's example used that placeholder. Replaced the example with concrete net names and added an explicit "net names are literal" warning to the parasitics prompt.
- **LLM agents producing malformed JSON** — two of eleven agents (stackup, high_speed) returned text outside the JSON braces in the first buck run and fell back to deterministic. Replaced the soft "Return ONLY the JSON object" closing line in every agent prompt (11 files) with a stronger "FINAL INSTRUCTION — strict output" block listing exactly what is and isn't allowed.
- **Topology not reaching the agent layer** — `cmd_report_generate` constructed `AgentContext` without populating `topology`, `dut_supply_net`, or `dut_return_net`, so the agents only saw `(not supplied)` in the topology block. Fixed by analysing the user fragment and forwarding `testbench_wiring`'s supply/return nets to the context (with the dual-LISN `0 → DUT_GND` rename applied).

Buck smoke test after fixes: **0 fallbacks**, parasitics LLM injection matches the deterministic plan literally (`n_dut_in_pre → in → DUT_GND`), $0.0429 / 12 calls.

Also adds `scripts/plot_schematic.py` — block-diagram visualiser for `generated/testbench.cir`. Shows V_RAIL → LISN+ → cable → M2.10 injection → user DUT → LISN- chain plus B-source DM/CM probes, with the parasitic injection highlighted in green. The user can verify visually that the LISN + cable + injection were wired correctly without reading SPICE source.

## M2.10.3 — LTspice .asc visualisation export + polished PNG plot (done 2026-05-15)

- `src/emc_assistant/testbench/asy_templates.py` emits hierarchical-block `.asy` files for every composer-side `.SUBCKT` (LISN50UH, CABLE_PWR, TRACE_RLC, VIA_L, CAP_ESR_ESL) plus a variable-pin DUT_FRAGMENT placeholder.
- `src/emc_assistant/testbench/asc_writer.py` builds a complete LTspice `testbench.asc` with all composer symbols, wires, and FLAG labels on a 16-px grid; the user `.cir` is referenced via a `!.include` TEXT directive. Bundle (`.asc` + 6 `.asy`) goes to `generated/`.
- CLI: `cmd_testbench_compose` writes the bundle every run; new `--no-asc-export` flag opts out.
- `scripts/plot_schematic.py` polished: deduplicated MEAS_P label, probe wires routed through a single right-side "probe bus" instead of crossing dashed lines, new `--expand-user-fragment` flag shows the user fragment's elements as a colour-coded grid inside the DUT region instead of as a black box.
- 12 new tests covering .asy header / pin names / prefix, .asc section presence, FLAG labels, bundle completeness, and write_asc_bundle output (299 tests total).

## M2.10.4 — per-net parasitic estimation (done 2026-05-16)

- `netlist/topology.py` gains `NetUsage.role` (return / switching_node / power_rail / signal, derived generically from element kinds + fanout) and `is_two_element`. The `.cir` parser learns `S/Q/J` element prefixes so converter switching nodes parse, and the X-instance parser was fixed so `key=value` params and `;` inline comments no longer leak in as fake nets.
- New `parasitics/per_net.py`: `estimate_all_nets()` walks every net and assigns a rule-of-thumb R/L/C band via a pluggable `ParasiticValueSource` ABC (`RuleOfThumbValueSource` today; look-up-table / extracted sources later). The report gains a per-net parasitic table.
- PCB-parasitics knowledge set: sources `S032`–`S036` (Analog Devices, Würth, Allegro, Clemson/Hubing) added to `baza_pasozyty_pcb_sources.jsonl`; 10 proposed rules staged in `knowledge/seed/staging_pcb_parasitic_trace_rules.jsonl` (a `staging_*` file is skipped by the index walk until promoted).

## M2.10.5 — per-net shunt-parasitic injection (done 2026-05-16)

- `ShuntParasitic` — a bare `C_par_<net>` capacitor to the return node, valid on any net (no rerouting). `ParasiticsAgent.default_shunt_plan()` proposes one per non-ground net; the composer emits a shunt section.
- Project override via `user_context.parasitics`: `skip_all`, or `per_net{net:{skip|c_pf}}`. Audit → `parasitics_shunt.json`.

## M2.10.6 — internal-net series splices (done 2026-05-16)

- `SeriesParasitic` — series R+L between `<net>__pre` and `<net>` plus a shunt C. `fragment.split_series_nets()` cuts a clean 2-element net by renaming it to `<net>__pre` on its first element (in the processed fragment copy, never the user's original).
- `ParasiticsAgent.default_series_plan()` + CLI two-pass `_prepare_user_fragment_with_splices`. Every net now carries a parasitic — series R+L+C on clean 2-element nets, shunt C elsewhere. Audit → `parasitics_series.json`.

## M2.10.7 — LLM parasitic-negligibility screen (done 2026-05-16)

- `ParasiticsAgent.filter_negligible()` — one `complete()` call scores the per-net plans and drops the parasitics the LLM is confident are negligible (switching nodes / power rails / fast di/dt never dropped). Fail-safe: any LLM error / malformed JSON / missing net keeps the entry.
- Opt-in via `--llm openai` (default stays deterministic = no screen). Audit → `parasitics_dropped.json`. Real-OpenAI smoke test: dropped exactly the 3 no-connect nets on case_002.

## M2.10.8 — LC-tank damping + report-only flag (done 2026-05-16)

- Real-LTspice run exposed a blocker: tiny pF/nH parasitics form undamped GHz LC tanks that collapse the transient timestep (a 6 s buck sim became a >120 s / 3.4 GB runaway). Fix: every parasitic inductance gets a parallel Q-damping resistor `Rd = 2*pi*200 MHz*L` — the branch is the inductor in-band (9 kHz–30 MHz) and resistive above, so the GHz tanks cannot ring.
- `--parasitics-report-only`: estimate the per-net parasitics for the report/audit but keep them out of the simulated `testbench.cir`.
- Verified on real LTspice: case_001 per-net testbench 14.2 s / 192 MB, case_002 3.1 s / 10.5 MB, both completing with all `.meas` metrics.

## M2.10.x — LISN-mode agent (done 2026-05-16)

- The 12th specialist agent. Unlike the eleven post-simulation report agents it runs **before** the testbench is composed — the dual vs single LISN choice shapes the testbench itself (the dual-LISN topology lifts the DUT ground to `DUT_GND` and enables the DM/CM split), so the decision is made up front.
- `agents/lisn_mode_agent.py`: `LisnModeAgent` + `LisnModeDecision`. `decide()` is the entry point — LLM path under `--llm openai`, deterministic heuristic otherwise (dual-LISN unless the project context signals a chassis/earth-bonded return). Fail-safe: any LLM error or malformed response falls back to the heuristic.
- `prompts/agents/lisn_mode_agent.md`: focused decision prompt (outputs `{lisn_mode, confidence, rationale}`).
- CLI `_resolve_lisn_mode` runs before `_resolve_wiring`. An explicit `dual`/`single` in `user_context.testbench_wiring.lisn_mode` always wins; unset or `"auto"` hands the call to the agent. Decision audited to `results/lisn_mode.json`.
- Verified: deterministic compose → dual (source=deterministic, 0.60); real-OpenAI compose → dual (source=llm, 0.90) with a sound rationale. 10 new tests; suite 395 pass.

## M2.11 — orchestrator / diagnostic-narrative synthesiser (done 2026-05-15)

- `schemas/diagnostic_narrative.schema.json` defines the synthesis output (title, narrative, dominant_issue, cited_findings / variants / rule_ids, confidence, llm_generated, limitations).
- `prompts/workflows/conducted_emi_dcdc_workflow.md` rewritten as the synthesis system prompt: role, inputs (7 labelled sections incl. aggregated findings, ranking, sim metrics, snippets, signals), output contract, guardrails ("hypothesis only, never compliance claim", "convergence beats novelty"), confidence rubric, strict-JSON closing.
- `src/emc_assistant/agents/synthesiser.py` ships `DiagnosticNarrative`, deterministic `aggregate_findings()` (clusters across the 11 agents by topic keywords with severity ranking), and `Synthesiser` with two paths:
  - LLM path: builds the prompt + calls `LlmAssistant.complete(purpose="synthesis.diagnostic")` + parses the JSON; falls back to deterministic on malformed response with a `limitations` note.
  - Deterministic stub: emits a templated narrative naming the dominant cluster + top-3 cited agents + top-2 ranked variants when no LLM is configured.
- CLI: `cmd_report_generate` runs the synthesiser after `run_agents()`; writes `results/diagnostic.json` (schema-validated) and threads `DiagnosticNarrative` into `ReportContext`.
- Markdown report opens with a `## Diagnostic (M2.11)` section right after the disclaimer, before "Project assumptions".
- Tests: 11 new (310 total) covering aggregation clustering, deterministic synthesis, stub-LLM parsing, malformed-response fallback, missing-required-field fallback, and an end-to-end pipeline test asserting the Diagnostic section renders ahead of Project assumptions under `--llm none`.

## M2.12 — recommendation feedback loop (done 2026-05-16)

Clarified with the user: the decidable unit is the agent **recommendation**, not the corner-sweep `Variant` (a `Variant` is a parasitic min/typ/max point — not a mitigation).

- `recommendations/decisions.py`: `Decision` + `DecisionLog`. Persists to `decisions/accepted_changes.json` + `decisions/rejected_changes.json` per project, keyed `<area>/<rec_id>`; re-deciding a key moves it between buckets; tolerates malformed files.
- CLI `recommendations` group: `list`, `accept <key>`, `reject <key> --reason`. Recommendation content is snapshotted into the decision record from `results/findings/`.
- Report: each recommendation carries an `[ACCEPTED]`/`[REJECTED]` badge + the decision note (via `ReportContext.decision_log`). A re-run report reflects prior decisions — rejected mitigations are flagged, not silently re-proposed.
- `bom_cost_estimate` / `side_risks` are optional `Decision` fields (user-supplied; the agents do not emit them today).
- `ProjectLayout` gains `decisions_dir`; `examples/**/decisions/` gitignored. 11 new tests.

## M2.13 — structured simulation / solver settings (done 2026-05-16)

- `testbench/sim_settings.py`: `SimulationSettings` — structured `stop_time`, `max_timestep`, `record_start`, `startup`, `integration_method`, plus a generic `options` dict (reltol/abstol/gmin pass through). `tran_line()` builds the `.tran` directive, `options_line()` the `.options`; `spice_to_float()` + validation (rejects `max_timestep > stop_time`, zero stop, bad method, record-start past stop). The raw `tran_directive` string still works and overrides the structured transient fields.
- `composer.py`: `TestbenchPlan.options_directive`, emitted before `.tran`.
- `cli.py`: `_resolve_simulation_settings` replaces `_resolve_tran_directive`; compose + variants pass `tran_directive` + `options_directive`; invalid settings abort with a friendly message.
- Backward compatible: case_001 keeps the `.tran 0 5m 0 100n` default, case_002's raw override still wins. The backend for the solver-settings UI panel (`docs/design/ui_design_brief.md`). 20 new tests; suite 426.

## M2.14 — service layer + logging seam (done 2026-05-17)

Backend restructuring after M2.13, ahead of the frozen M3 UI, so the CLI and the future UI share one application core.

- `emc_assistant.service` package — the application service layer: one plain function per use case (project / context / parasitics / testbench / simulate / report / pipeline / recommendations / …), each taking plain parameters or a `CommandOptions`, returning a typed result dataclass, raising `ServiceError` for expected failures. `cli.py` becomes a thin `argparse` adapter over it; `service/resolve.py` holds the wiring / parasitics / signals / LISN-mode decision resolvers.
- `logging_setup.py` — a structured stdlib-`logging` seam replacing ad-hoc `print()`: components log under `emc_assistant.<component>`; a stdout console handler (`%(message)s`), an optional per-run JSONL log file, and a UI-handler hook for the M3 shell.
- `docs/design/ui_backend_contract.md` records the screen-by-screen UI ↔ backend contract both front-ends honour.
- Test-coverage backfill — dedicated suites for the logging seam, the service-layer resolvers, the `.raw` service, the LTspice adapter, and `units`.

## M2.15 — conducted-EMI detector suite (done 2026-05-18)

The MVP's "peak / average / quasi-peak calculations" item — a CISPR-style EMI-receiver detector with norm-selectable compliance limit lines. Designed conceptually first in `docs/concepts/quasi_peak_detector_concept.md`.

- `results/detectors.py`: peak / quasi-peak / average detectors in three modes — Mode 1 `time_domain_diagnostic` (STFT over a selected waveform, no receiver-bandwidth filter), Mode 2 `receiver_like_single_frequency` (receiver-bandwidth band-pass at one centre frequency), Mode 3 `receiver_like_sweep` (Mode 2 across the conducted band). CISPR 16-1-1 / EN 55016-1-1 ed. 3 band constants, verified against the standard.
- Quasi-peak — the CISPR charge/discharge weighted detector with a max-hold indication.
- Average — the meter-time-constant counterpart: the envelope through a linear low-pass with the band's meter constant, then max-held. The low-pass is seeded with the envelope mean, so a transient sim far shorter than the 160 ms meter constant degrades gracefully to that mean instead of under-reading from a cold start. `average ≤ quasi-peak ≤ peak` enforced.
- `results/limits.py`: norm-selectable compliance limit lines — ships EN 55022 Class B (conducted, quasi-peak + average) with a `STANDARDS` registry for further norms; `margin_db()` / `worst_margin()` give the per-frequency margin (reading − limit).
- CLI `raw quasi-peak` (Mode 2) / `raw quasi-peak-sweep` (Mode 3) report peak / quasi-peak / average + the compliance margins; the report's "EMI detector" section carries the detector metadata, the worst margins, and **embeds the detector-vs-limit plots** for the run (Mode 1 + Mode 3) — `reports/detector_plot.py` renders them lazily, matplotlib-optional, and falls back gracefully if the run can't resolve band B.
- All results are CISPR-like pre-compliance diagnostics, never a compliance verdict — no normative limit text reproduced, only widely-published numeric values.
- Tests: `test_detectors`, `test_quasi_peak_detector`, `test_limits`, `test_average_detector`, `test_detector_plot`; suite at 611.

## M2.18 — comparative time-domain waveform analyzer (done 2026-05-22)

Built ahead of M2.16/M2.17 at the user's request. Turns the Results
screen's single `V(meas)` plot into a required **two-panel, time-aligned
analyzer**: the measured LISN voltage on top, a selectable comparison trace
below, both sharing the X (time) axis (each panel auto-scales its own Y,
volts or amps).

- Default comparison trace = `I(Rload)` (load current), resolved
  deterministically. The selector also offers **four further traces deduced
  by the LLM** (cloud LLM on) or a topology heuristic (off) — input
  current, switch/inductor current, CM/DM probe, etc. — each with a reason.
- `service/raw.py` `load_waveform(trace=…)` gains per-trace caching + a
  `kind`/`unit` field; all traces share the axis + bucket edges so the two
  envelopes line up sample-for-sample.
- New `agents/waveform_trace_agent.py` (+ prompt) and
  `service/waveform.py` `suggest_waveform_traces` (cached to
  `results/waveform_traces.json`, shares `--llm-budget-usd`); bridge
  `Api.suggest_waveform_traces` + `Api.load_waveform(trace)`.
- A visualization aid only — it selects *which* traces to plot; fabricates
  no values, makes no compliance claim, sends no netlist (structured
  summaries only). Fail-safe to the heuristic on any LLM error.
- Conversational control of the selection is deferred to **M5** (below).
  See `tasks/m2_18_waveform_subplot.md`.

## M2.17 — LLM/RAG re-evaluation of parasitic values (done 2026-05-22)

A user-triggered, opt-in pass that refines the deterministic per-net
parasitic *values* into citation-backed min/typ/max bands, grounded in the
RAG PCB-parasitics knowledge. Built as a **post-estimate refinement** (not a
`ParasiticValueSource`): one batched LLM call over all non-ground nets, with
the deterministic rule-of-thumb estimate kept as the prior/fallback.

- `agents/parasitics_agent.py` `reevaluate_values` — sibling to
  `filter_negligible`: one `complete(purpose="parasitics.reevaluate")`, parses
  `{refined:[{net,r_band,l_band,c_band,confidence,rationale,cited_sources}]}`,
  coerces/validates each band, and **fails safe to the prior** (omits the net)
  on any LLM error, malformed JSON, or unusable band.
- `service/parasitics.py` `reevaluate_parasitics(project_root, options,
  apply=False)` — `llm_enabled` gate (raises `ServiceError` when off), per-net
  RAG retrieval (`retrieve_for_keywords`; redacted snippets + structured
  summaries only — the netlist never leaves), one batched refinement, then the
  full audit `generated/parasitics_reevaluated.json` (prior + refined
  min/typ/max, typ-delta %, confidence, rationale, citations, provenance).
  Weak retrieval → keep the prior, widen the band, lower confidence.
- **`--apply` persists only the refined typ values** as explicit user
  overrides (`user_context.parasitics.per_net` r_mohm/l_nh/c_pf, merged so a
  `skip` is preserved); the bands + citations stay in the audit only.
- Provenance disclosed in the report's per-net table (`source` column):
  **calculator (rule-of-thumb)** / **LLM-refined (RAG)** / **LLM (uncited
  est.)**, read from the audit.
- `schemas/parasitics_reevaluated.schema.json` validates the audit on write.
- CLI `parasitics reevaluate <project> [--apply] --llm openai`; bridge
  `Api.reevaluate_parasitics` / `apply_reevaluated_parasitics`.
- UI (wired 2026-05-23, user-directed): an **"AI: re-evaluate values (RAG)"**
  button on the Parasitic-selection screen (next to "AI: suggest negligible")
  runs the preview, then a **review-before-apply proposals panel** shows each
  net's prior→refined typ (R/L/C), confidence and citations with an "Apply
  refined typ values" button (accept = persist typ-only from the audit, no
  second LLM call). A disabled **"Read from layout (M7)"** placeholder sits
  beside it.
- Tests: 11 (agent stub + service: audit full bands + provenance, typ-only
  apply, fail-safe, LLM-required) + a `live_llm` real-OpenAI test. See
  `tasks/m2_17_parasitics_llm_rag_reeval.md`.

## M2.x series — complete; CM-coupling promoted to M10 (2026-05-23)

The numbered M2.x series is **closed**. The one remaining deterministic-core
idea — common-mode coupling — was lifted out of M2 at the user's request and
promoted to its **own standalone milestone, M10** (below), so it isn't lost:

- **Common-mode coupling model (CSTRAY → earth)** *(now M10, was M2.16)* —
  opt-in per-net stray capacitance to the ground reference plane (SPICE `0`),
  dual-LISN only, so the CM metric/plot carry real signal. See
  `tasks/m10_cm_coupling.md` and the M10 section below.

The conversational parasitics-strategy chat (formerly proposed as M2.18)
moved out of the M2 series — it is now **M5**, after the M4 multi-agent /
tool-use foundations it depends on.

## M3 — light UI (in progress)

- local desktop UI (a pywebview shell over the service layer),
- project list,
- recommendations panel,
- result visualization.

**Design prototype received 2026-05-19** — a React/Babel reference (one HTML loading 18 `.jsx` files). The designer's `README.md` is explicit: do not ship Babel-standalone; rebuild on the host stack. Adopted as Vite + React under `ui/`.

**Landed:**

- Vite + React build at `ui/` — `package.json` pins react 18 + vite 5 + `@vitejs/plugin-react`; `vite.config.js` writes the static bundle into `src/emc_assistant/ui/web/` with relative asset paths (file:// safe), so the pywebview shell loads a self-contained build (no CDN at runtime). 18 `.jsx` files moved into `ui/src/` + `ui/src/screens/` with React-hooks imports prepended; the prototype's `window.X = X` cross-file exports are preserved.
- `ui/HOOKS.md` + `ui/README.md` from the handoff stay next to the source as the wiring contract.
- Pywebview shell (`src/emc_assistant/ui/app.py`) prefers the Vite build at `web/index.html`, falls back to the placeholder. `Api.pick_folder()` opens the native folder dialog.
- **First wiring slice — Projects screen.** `ui/src/api.jsx` (`useApi` hook + mock stub for browser dev) + `ui/src/screens/projects.jsx` (rewritten to call `api.list_projects(root)` on mount + on folder change; `localStorage` caches the last-picked folder; a bridge-mode indicator reads `pywebview ✓ (live backend)` or `mock — browser dev`).
- QA flow inventory at `docs/qa/QA_FLOWS.md` — 4 end-to-end journeys + 5 cross-cutting + ~24 per-screen flows, Gherkin + criteria tied to `ui/HOOKS.md`.
- **Backend gap closed (2026-05-20).** A QA-flow critique surfaced six features the design assumed but the backend didn't provide. All six now landed (see `tasks/m3_backend_gap.md`): `service/settings.py` for app-level user prefs (raw-dict storage at `~/.emc-assistant/settings.json` so the UI can grow keys without backend changes); `Api.load_settings` / `save_settings` / `detect_ltspice` / `pick_file` / `set_schematic` / `cancel_run` on the bridge; `--pdf` flag on `report generate` and `pipeline run` (xhtml2pdf-backed, in the `[pdf]` extra); a cooperative `RunCancelled`-raising checkpoint between every pipeline stage. Suite at 653.

- **All analysis screens wired (2026-05-22).** Projects → Import/context → Parasitics → Testbench → Run → Results → Findings → Report all read/write real backend artifacts; cloud LLM is key-gated. Results carries the M2.15 detector spectrum + the M2.18 comparative waveform analyzer.
- **`user_context` editable from the app (2026-05-22).** Beyond the structured Import/context + Parasitics forms, the **Run-screen simulation-settings panel** is now wired — it loads/saves `user_context.simulation` and runs a *review-before-apply* deterministic check on the proposed values (`service.testbench.assess_simulation(overrides)` / `load_simulation_settings` / `save_simulation_settings`; raw `.tran` overrides are surfaced as effective values and promoted to structured fields on save). An **"Advanced — edit user_context.json" raw editor** on the Import screen exposes the full document (validate-on-save) for fields without a form.

**Next:** the two coming-soon previews remain mock; otherwise the analysis flow is wired end-to-end.

## M3.99 — UI production hardening (decouple the pipeline from the GUI) (superseded by M11)

**Superseded by M11 (2026-05-23):** the pipeline-decoupling hardening below is
now a core requirement of the M11 UI rebuild (out-of-process execution +
log-stream hardening + crash-resilient screens); this section is kept for its
detailed root-cause analysis. See `tasks/m11_ui_rebuild.md`.

**Deferred (2026-05-22):** the user prioritises backend features and treats
the current pywebview UI as a thin, disposable viewer to be rebuilt later,
so this hardening is filed as the spec for that rebuild rather than worked
now. Until then, run heavy pipelines from the backend (the GUI just views
the artifacts).

A hardening pass that gates M3 being production-ready. Surfaced by the
2026-05-22 hands-on session: running a full pipeline from the app
repeatedly crashed the WebView2 renderer (exit 5 / historically 139) on
heavy runs (11-variant sweep + ~13 cloud-LLM calls + the live-log stream),
and because `run_pipeline` runs on a background thread **inside** the
pywebview process, the crash killed the run mid-report-stage — losing the
findings, `diagnostic.json`, `report.md` and `recommendations.json`
despite the run having logged "6/6 markdown report". The crash destroys
pipeline output, not just the window.

Root causes are **architectural, not WebView2 limitations**: (1) the
pipeline is in-process with the GUI; (2) the live-log pump calls
`evaluate_js` ~5×/s for the whole run, flooding the renderer.

The fix keeps pywebview/WebView2 and **decouples the pipeline from the
GUI**: run it out-of-process (spawn the CLI / a worker), make the GUI a
thin client that tails the per-run log file + polls artifacts, and replace
the push log-pump with JS-side pull (or hard rate-capping). Then a
renderer crash closes a window but never kills a run or loses output —
reopening shows complete results. Engine swaps (Tauri also uses WebView2
on Windows; Electron is heavier) are explicitly out of scope — the
decoupling applies regardless of engine. See
`tasks/m3_99_ui_production_hardening.md`.

## M4 — multi-agent orchestration with shared state (parked)

The original M4 plan (a separate "RAG and agents" milestone) is absorbed into M2.7–M2.11. M4 may later cover more sophisticated agent coordination — multi-step tool use, agent-to-agent dialog, etc. — once M2.11 is stable. Out of scope for now.

Queued M4 agent / optimization work (detailed task files under `tasks/`):

- **`sim_setup` agent** — infer the device switching-edge rate (from the FET part number / topology + KB) to feed the deterministic sim-setup check, so fast-edge devices get a device-aware timestep verdict without the user supplying `t_rise`. See `tasks/m4_sim_setup_agent.md`.
- **Power-line EMI-filter design / optimization agent** — diagnose DM/CM noise from the detector result, size a π-filter / CM choke (banded, with Y-cap leakage + damping guards), and close the loop (inject → re-simulate → adjust) to meet the limit. Distinct from the analysis-only `filtering_agent`. See `tasks/m4_power_filter_agent.md`.
- **Variant-review / variant-proposal agent** — review whether the deterministic min/typ/max corner sweep adequately covers the parasitic uncertainty, and propose *additional* simulation variants (single-net sensitivity sweeps, RAG-grounded what-if scenarios) as a reviewable accept/skip list. The deterministic core still owns generation/running; the agent only suggests which extra corners are worth the compute, and must **add to** — never replace — the baseline corner sweep that Results/Findings/Report derive from. Note: a `Variant` stays a deterministic corner point, not an agent decision. See `tasks/m4_variant_agent.md`.
- **Schematic-understanding agent** — the tool currently *netlists* but does not *understand* the schematic: `.asc` is only CLI-converted to `.cir` (graphics unread), net roles are heuristic (`netlist/topology.py`), and the Import screen honestly shows topology/switch-nodes as "not yet parsed from schematic". This agent interprets the netlist + context + RAG to label the power stage, high-/low-side switches, the SW node, the hot loop and the rails as **user-confirmable, sourced hypotheses** — replacing that placeholder and sharpening the per-net roles the `dcdc`/`layout_risk`/`high_speed` agents lean on. Deterministic roles stay the fallback; the heavier deterministic graphical-`.asc` parser is a separate, scope-frozen piece (overlaps M7 layout). Extends the `signal_map_agent` feature-keeper from signal names to full topology. See `tasks/m4_schematic_understanding_agent.md`.

## M5 — conversational parasitics strategy chat (planned)

The conversational layer (was proposed as M2.18; the number was reused for the waveform analyzer above). An in-window chat on the parasitic-selection screen where the engineer directs strategy in natural language (e.g. "add a series inductance to every net with a 10 pF shunt cap"); the LLM proposes structured, RAG-grounded per-net edits shown as a reviewable diff that the user accepts before anything applies — never a silent mutation. Builds on the M4 tool-use / agent foundations and the M3 parasitic-selection screen. See `tasks/m5_parasitics_strategy_chat.md`.

Sibling conversational controls to land with the same layer:

- **Waveform comparison-trace selection (from M2.18)** — change the Results-screen comparison subplot by chat ("show me the inductor current instead") instead of the dropdown. The M2.18 selector + `waveform_trace_agent` already produce the structured choices; the conversational layer just drives the selection. See `tasks/m2_18_waveform_subplot.md`.

## M6 — Pro (parked)

- project history beyond a single project,
- PDF / HTML report,
- richer stack-up / cable profiles,
- advanced sweeps,
- expanded AI-budget controls (daily / monthly / per-project limits; M2.7 already ships the per-run `--llm-budget-usd` cap).

## M7 — layout / radiated / corporate (parked)

- layout import,
- parasitics extraction,
- radiated-risk estimation,
- on-premise deployment,
- team workspace.

## M8 — real-time lab support + collective learning (split into M12 + M13, 2026-05-23)

**Superseded:** this far-future track was split into two dedicated milestones so
each can be scoped on its own — **M12 — Live Lab Assistant** (real-time lab
support) and **M13 — Engineer Training** (engineer-supported collective
learning). The two UI "coming-soon" preview screens (`preview-lab` /
`preview-training`) are the teasers for M12 / M13 respectively. See those
sections below.

## M9 — Security & privacy hardening review (standalone)

A cross-cutting security & privacy assurance pass — **not gated on M4–M8**.
Should run before the tool is distributed beyond the author's machine. The
threat model is unusual: it holds a confidential schematic (the #1
principle), an API key on disk, an outbound LLM egress path, untrusted-file
parsers (`.asc` / `.cir` / `.raw`), an LTspice subprocess, and a pywebview
JS↔Python bridge whose every `Api.*` method is page-callable.

Verifies the existing guardrails hold and closes gaps: schematic never
leaves the machine (redaction-path audit + an outbound-payload guard), API
key never logged / returned / persisted, path-traversal review across all
bridge methods, malformed-file parser robustness, argv-list LTspice
invocation, bundle-loads-local-only / CSP, report output escaping, secrets
gitignored, and a `pip-audit` dependency scan. Deliverable:
`docs/security_review.md` + a regression test suite. No new product
features — assurance + hardening. See `tasks/m9_security_review.md`.

## M10 — Common-mode coupling model (CSTRAY → earth) (planned, standalone)

Promoted out of the (now-closed) M2.x series at the user's request so it
isn't lost (2026-05-23, was M2.16). A **deterministic-core** enhancement,
**independently schedulable** — not gated on M4–M9.

Today every per-net parasitic returns to `DUT_GND`, so there is no path to
the earth reference plane (SPICE `0`): the CM metrics (`cm_peak/rms/p2p`) and
the CM detector-vs-limit plot exist but carry no meaningful signal — CM
analysis effectively produces nothing. M10 adds an **opt-in, dual-LISN-only,
banded (min/typ/max)** per-net stray capacitance to earth from high-dv/dt
nets, so CM results actually appear and are disclosed in the report — same
opt-in discipline as the M2.10.5 shunt model. Acceptance requires a
real-LTspice before/after on case_001 plus a runtime check (LC-tank stiffness
risk, the class of problem M2.10.8 damping solved). Open design questions
(default nets, typ value range to the plane, additive vs re-pointed shunt,
before/after report) are in the task file. See `tasks/m10_cm_coupling.md`.

## M11 — UI rebuild (next-generation desktop UI) (planned — requirements)

A from-the-studs rebuild of the desktop UI, **superseding M3.99** (it absorbs
the pipeline-decoupling hardening) and closing the open M3 follow-up queue.
Driven by hands-on experience with the M3 shell: in-process runs that crash
WebView2 and lose output, an `evaluate_js` log flood, fragile mtime-based
staleness that over-flags the workflow (the case_003 "all stale" surprise),
no dev hot-reload, accidental paid cloud-LLM runs, and mock data leaking into
shipped screens. Requirements cover crash-isolated **out-of-process**
execution, pull-based log streaming, a **content-aware freshness model** with
clear re-run affordances, large-`.raw` streaming/virtualization, an
honest-data invariant, a faithful testbench render, and a pre-run cost/privacy
gate. The `service/` layer stays the product core; the UI is a disposable
client over it. Architecture decision pending (recommended: a localhost
service + thin client). Full requirements + acceptance + open decisions in
`tasks/m11_ui_rebuild.md`.

## M12 — Live Lab Assistant (real-time EMC-lab support) (parked, far future)

Split out of the former M8 (2026-05-23). The UI "coming-soon" preview
`preview-lab` (feature-gate `live-lab-assistant`) teases this. The tool runs
alongside the engineer at the test bench: live receiver / spectrum-analyser
data is ingested and correlated against the simulated prediction, and the UI
surfaces **which parasitic / LISN / filter hypothesis explains a measured
peak**. Parked: depends on the new UI (M11) and a **measurement-ingest path**
that does not exist yet. Recorded so the MVP is designed to leave room for it.
See `docs/design/ui_design_brief.md`, "Future vision".

## M13 — Engineer Training (engineer-supported collective learning) (parked, far future)

Split out of the former M8 (2026-05-23). The UI "coming-soon" preview
`preview-training` (feature-gate `engineer-training`) teases this. Engineers'
corrections to parasitics, LISN mode and filter values become training signal;
a model learns realistic parasitic values from the accumulated corrections of
many engineers, so the tool's estimates improve from real lab outcomes.
**Privacy is load-bearing** — the schematic is confidential, so the learning
loop ships only model deltas (federated / on-device) or redacted structured
feature→value pairs, **never raw netlists**; contributing is strictly opt-in,
reusing the existing copyright-redaction discipline. Parked: depends on M11 and
M12's measurement-ingest path.

## Always out of scope

- LTspice hosting as a SaaS,
- bundling LTspice with the application,
- payments / billing infrastructure (until M6 at the earliest),
- corporate / on-premise deployment (until M7),
- automated EMC certification,
- full coverage of every standard (CISPR / IEC / IPC verbatim).
