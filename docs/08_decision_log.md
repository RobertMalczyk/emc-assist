# Decision log

## 2026-05-13 — LTspice runs locally only

Decision:

- LTspice will not be run as a SaaS backend.
- The tool uses the user's locally installed LTspice.

Reason:

- licensing risk,
- schematic privacy,
- simpler MVP,
- easier acceptance from hardware customers.

Consequences:

- a local runner is required,
- the LTspice executable path must be configurable,
- the user must bring their own LTspice install.

## 2026-05-13 — MVP scope: conducted EMI only

Decision:

- The first use case is conducted EMI for DC/DC converters.

Reason:

- easiest to validate in LTspice,
- high practical value,
- lower risk of false promises than radiated EMI.

Consequences:

- layout and radiated EMI are out of MVP scope,
- a strong PCB-parasitics module is required.

## 2026-05-13 — Deterministic pipeline first

Decision:

- The agent framework only comes after the core works.

Reason:

- fewer hallucinations,
- easier to test,
- more engineering value.

Consequences:

- the first release can be a CLI only,
- agents are encoded as contracts and prompts, not as the main mechanism.

## 2026-05-13 — Pre-compliance disclaimer is mandatory in every report

Decision:

- The Markdown report generator inserts a pre-compliance disclaimer both at the top and at the bottom of the report.
- Tests verify the presence of the disclaimer and the absence of phrasings such as "the circuit will pass EMC".

Reason:

- guardrails from CLAUDE.md,
- protection against the tool being misused as fake proof of compliance.

Consequences:

- every report carries a fixed, testable warning section,
- changing this requires `tests/test_report.py` to pass.

## 2026-05-13 — M0 implemented as the `emc_assistant` package

Decision:

- MVP core in Python 3.11+ under `src/emc_assistant/`.
- The `emc-assistant` CLI is the only interface in M0 (no UI).
- Only the standard library + `PyYAML` + `jsonschema`; no network, LLM or agent-framework dependencies.

Reason:

- minimal attack/bug surface,
- easy to install for engineers,
- consistent with the bans on hosting LTspice and sending schematics.

Consequences:

- agents will be added in later milestones as a layer on top of the deterministic CLI,
- `pytest` is the only regression contract.

## 2026-05-13 — Parasitics always return a min/typ/max band

Decision:

- Each calculator (`trace_resistance`, `trace_inductance_no_plane`, `trace_capacitance_from_z0_delay`, `polygon_plane_capacitance`, `via_inductance`, `lc_resonance`) returns a `ParasiticEstimate` with `ValueBand` (min/typ/max), `confidence`, an `assumptions` list and `source_ids`.

Reason:

- consistent with CLAUDE.md (no "certain" values),
- aligned with `schemas/parasitic_model.schema.json`,
- required for sweep-friendly testbench in M1/M2.

Consequences:

- the report always shows a band,
- every recommendation must cite a rule source or mark `engineering_estimate`.

## 2026-05-13 — LISN and cable as educational SPICE models, not normative

Decision:

- The generated `.SUBCKT LISN50UH` uses a 50 µH / 0.1 µF / 50 Ω topology as a first approximation.
- The cable generator uses an LC ladder with a configurable number of segments.

Reason:

- we have no rights to reproduce CISPR/IEC standards,
- the MVP must show a working workflow without violating licenses.

Consequences:

- the report labels the models as *engineering aid* and excludes interpretation as an EMI-receiver measurement (peak/avg/QP),
- an EMI-receiver detector is out of MVP scope.

## 2026-05-13 — M1: testbench composer + LTspice runner

Decision:

- `testbench.cir` is composed by `compose_testbench_cir` as a separate file in `generated/testbench.cir`; user files are included via `.include` and are never modified.
- The min/typ/max sweep is realized via `.step param sweep_corner list 0 1 2`, with parasitic values exposed as `.param <prefix>_{min,typ,max}` parameters.
- `simulate run` has two modes: `dry-run` (records the planned command, no process spawned) and `local-run` (calls `subprocess.run` with timeout).
- Every run writes `results/<run-id>.json` conforming to `schemas/simulation_run.schema.json`; status ∈ {dry_run, completed, failed, timeout}.

Reason:

- protect the original user netlist (no `.asc/.cir` mutation),
- prepare for variant ranking in M2 (sweep over parasitic values),
- explicit logging of what would be executed even without LTspice.

Consequences:

- `simulate run` requires a prior `testbench compose`,
- when LTspice is not available, `dry-run` is a fully valid artefact and `local-run` ends with `status=failed` instead of an exception.

## 2026-05-13 — M2: corner-sweep variants + ranking + hard JSON validation

Decision:

- Variant sweep: `enumerate_corner_variants` produces `1 + 2N` variants (baseline + per-parasitic min/max); `frequency`-type parasitics (from `lc_resonance`) are intentionally excluded from the sweep.
- Each variant is its own `.cir` in `generated/variants/<label>.cir`, one sweep point per file (instead of `.step` in a single file) — easier to compare results and produce a before/after ranking.
- Ranking: `rank_variants(pairs, metric_key, lower_is_better)` is independent of LTspice; it works on metric dicts from `simulation_run.json`. Missing metric in a variant = skipped.
- Hard JSON validation: `emc_assistant.schemas` raises `SchemaValidationError` when `recommendation.schema.json` or `parasitic_model.schema.json` mismatches. CLI `parasitics estimate` and `report generate` use this validation as a gate.

Reason:

- an agent needs a reproducible cross-section of variants (previously only an abstract `.step` in one file, with no comparable artefacts),
- ranking must be testable without LTspice (gold path for CI / M3),
- hard JSON validation closes the contract between the core and the future agent layer — no artefact escapes its schema.

Consequences:

- the report gained two new sections: "Variants (min/typ/max sweep)" and "Variant ranking by `<metric>`",
- CLI gained `variants compose` + `variants run` + the `report generate --rank-metric <key>` flag,
- the new output directory `results/variants/<label>.json` contains `variant_label` and `overrides` in addition to the regular `simulation_run.schema.json` fields.

## 2026-05-13 — M2.5: golden buck demo + `.raw` parser + one-shot pipeline

Decision:

- The golden example is `examples/case_001_buck_conducted_emi/input/buck_demo.cir`, a behavioral 24 V → ~5 V 400 kHz buck as a *fragment* (no `.tran`/`.end`).
- The testbench composer invokes the preprocessor `write_user_fragment(src, dst)`, which copies the user netlist to `generated/user_circuit_fragment.cir` with control directives stripped (`.tran`, `.end`, `.step`, `.ac`, `.dc`, `.options`, `.meas`, …). The source file is never modified.
- `.raw` parser: ASCII + binary (`real` and `complex`) with fail-safe `UnsupportedRawFormat` for `fastaccess` and truncated files. No numpy.
- `.raw` header decoded first as UTF-16-LE (LTspice on Windows), with an ASCII fallback.
- `parasitic_model.schema.json` extended with `parasitic_type: "frequency"` (needed for `lc_resonance` as a diagnostic output).
- Base metrics (`max`, `min`, `peak`, `peak_to_peak`, `rms`, `axis_min`, `axis_max`) computed after a successful `local-run`; missing `.raw` or unsupported format = warning in `simulation_run.json`, not a crash.
- CLI: `pipeline run` (one-shot), `raw inspect`, `raw export-csv`.
- The report now has a **Measurements** section in the required order: assumptions → parasitics → LISN/cable → variants → measurements → ranking → recommendations → limitations + disclaimer.

Reason:

- a demo-ready buck-conducted-EMI scenario runs as one command (`pipeline run`) without needing to know the step order,
- a real path to pre-compliance metrics when the local LTspice produces `.raw` — previously `metrics{}` was always empty,
- protection of the user file against being overwritten.

Consequences:

- every pipeline run creates `generated/user_circuit_fragment.cir` — that is a tool artefact, not a user file,
- the report always has a "Measurements" section (empty placeholder in dry-run mode),
- tests cover synthetic `.raw` fixtures (ASCII + binary real + binary complex) — no LTspice required in CI.

## 2026-05-13 — Next milestone is M2.6 (LTspice integration); M3 UI stays frozen

Decision:

- After M2.5 we do not jump to M3 (UI). The next milestone is **M2.6 — LTspice integration**: real batch run, parsing `.meas` from `.log`, band metrics (conducted EMI), mock LTspice for CI.
- M3 (UI) stays in the roadmap but is frozen until further notice.
- `tasks/implementation_plan.md` and `docs/11_roadmap.md` reflect the change.

Reason:

- the dry-run pipeline is demo-ready but Measurements and Ranking in the report stay empty without real LTspice — the current value-limiting gap,
- the user wants engineering value from measurements, not UI,
- M2.6 closes the "schematic → numbers" loop — only then does UI have real material to visualize.

Consequences:

- a new M2.6 section in `tasks/implementation_plan.md` with 6 tasks and acceptance criteria,
- `docs/11_roadmap.md` has M2.5 (done) and M2.6 (next) before M3,
- mock LTspice in CI becomes mandatory — tests cannot require a local LTspice install.

## 2026-05-13 — M2.6 implemented (LTspice integration)

Decision:

- The testbench composer now emits 4 default `.meas TRAN` directives covering `V(MEAS)` (`vpeak`/`vmin`/`vp2p`/`vrms`). They can be overridden or disabled via `TestbenchPlan.meas_directives`.
- The `.log` parser handles the full LTspice format: `Measurement: <name>` blocks, `.step`-aware tables (per-step as `<name>_stepN`, canonical = last), nested parens in `MAX(v(meas))=...`.
- `summarize_default_metrics` adds `max_in_band` for frequency axes; default conducted-EMI band `(150 kHz, 30 MHz)`, parameterized via the `bands_hz` argument. Time-domain `.tran` skipped — meaningful only for `.ac`/FFT.
- The runner, after a successful `local-run`, parses *both* `.raw` *and* `.log` and merges metrics (`.raw` first, `.log` fills gaps via `setdefault`).
- LTspice error classifier: stderr + log scanned against 4 patterns (convergence, license, missing_model, syntax); each match adds a line to `errors` formatted as `[tag] hint (matched: snippet)`.
- Mock LTspice for CI: `tests/test_runner_local_run_mocked.py` monkey-patches `subprocess.run`, emits a synthetic `.raw` + `.log`, and exercises the full `pipeline run --mode local-run` path. CI does not require a local LTspice install.

Reason:

- Measurements and Ranking in the report were empty in dry-run; local-run (or mock) now fills them with real numbers.
- `.log` as a cheaper path to `.meas` — when the user disables `.raw` writing, metrics still flow.
- Error classification turns LTspice stack traces into something readable in the report.

Consequences:

- the new default `testbench.cir` artefact has 4 `.meas` directives — the report will always receive at least `vpeak/vmin/vp2p/vrms` from `.log` during local-run,
- test count rose from 85 → 101 (+16: composer `.meas`, log block parsing, band metrics, mocked local-run, failure classification),
- unsupported `.raw` formats (fastaccess) still raise `UnsupportedRawFormat` — no change there.

## 2026-05-14 — M2.6.1: closing the "schematic → numbers" loop on real LTspice

Decision:

- The testbench composer auto-wires `V_RAIL → X_LISN → X_CABLE` when `user_context.testbench_wiring` is configured **and** the user accepts the proposal (CLI `[y/N]` prompt on a TTY, or `--accept-wiring` for scripted/CI contexts). `--no-wiring` explicitly skips emission.
- `user_context.json` schema extended with a `testbench_wiring` block (`external_supply_v`, `dut_supply_net`, `dut_return_net`, `user_source_to_strip`). Missing block = old behavior (only `.SUBCKT` definitions, no instances).
- `netlist.fragment.write_user_fragment` now accepts an optional `strip_sources` — it removes the named user voltage source (e.g. `Vin`) so the LISN chain owns the DUT supply alone.
- The composer `.include`s the user fragment **by absolute path** (`Path.resolve().as_posix()`). LTspice resolves `.include` relative to the `.cir`, so relative paths from CWD are useless.
- The `.raw` parser recognizes the "compressed real" layout of modern LTspice (XVII / 26.x): time as 8 B double, other variables as 4 B float. The choice between legacy and compressed is made by minimizing `body_len % record_bytes`, without depending on header flags.
- The `.raw` parser tolerates over-reported `No. Points` in the header (LTspice with `.step` + adaptive timestep reports an upper bound, not the actual point count). We return `min(declared, body_len // record_bytes)`.
- The runner's failure classifier picks up LTspice's `File not found.` as `[missing_model]`.

Reason:

- M2.6's mock-only validation hid three real bugs: relative include, no LISN instance, mismatched `.raw` layout. The real smoke test on LTspice 26.0.2 revealed that `pipeline run --mode local-run` on the buck demo returned only `tnom`/`temp` from `.log` and nonsense `v_meas_*` values (around 1e9) from `.raw`. The M2.6 acceptance criterion ("Measurements + Ranking populated with real numbers") was never actually met without the mock.
- Wiring is a sensitive piece — a netname mistake would break the simulation without a clear message. Requiring explicit user acceptance protects against silently applying a bad configuration.

Consequences:

- `examples/case_001_buck_conducted_emi/input/user_context.json` now has a `testbench_wiring` block. The CI mock test still works without wiring (pre-resolved as None when there is no TTY and no `--accept-wiring`).
- After `--accept-wiring`, the report shows **V(MEAS) peak 3.41 V, RMS 0.64 V** for the buck demo on real LTspice; `.raw` and `.log` metrics agree.
- All 11 variants rank identically by `v_meas_peak` because the parasitic perturbations (8–25 nH) are dwarfed by the 1 µH `Ldm` + 4.7 µF `Cin` input filter. That is a physical fact, not a bug — documented as an M2.6.1 limitation. A future enhancement is a second golden example without an input EMI filter, where parasitics actually move V(MEAS).
- `.step`-segmented `.raw` is merged into a single axis by `abs()` on the time axis (unchanged). Per-segment access is a future enhancement; for aggregated peak/min/rms metrics merging is sufficient.
- 110 pytest tests (+1 vs M2.6: compressed-real format), still no local LTspice required in CI.

## 2026-05-14 — All `.md` files become English; documentation language switch

Decision:

- Every tracked `.md` file in the repo is translated to English: `CLAUDE.md`, all of `docs/`, `tasks/`, `prompts/`, `knowledge/README.md`, the knowledge index files, `WSAD_SUMMARY.md`, `claude_code_bootstrap_prompt.md`, `claude_design_emc_promo/claude_design_promo_wsad.md`. Translation is sliced into three commits: strategic docs first, reference docs second, prompts third.
- This reverses the prior rule in `feedback_english_first_code.md` that kept `docs/`, `CLAUDE.md` and `docs/08_decision_log.md` in Polish.
- Conversation between the user and the assistant can be in either language; the user picks per session.

Reason:

- the user requested it before M2.7 starts; English documentation makes the open-source surface uniform and removes the language boundary inside the repo,
- M2.9+ will turn `prompts/agents/*.md` into actual LLM prompts — English prompts are easier to reason about and align with the OpenAI provider chosen for M2.7,
- the rest of the codebase (src/, tests/, CLI output, reports) has been English since the 2026-05-13 refactor; now the docs match.

Consequences:

- two stale bootstrap directories were deleted as part of the same cleanup: `Input/` (a duplicate of `knowledge/seed/` plus the original bootstrap zip) and `src_placeholder/` (a marker file from before `src/emc_assistant/` existed),
- the auto-memory rule `feedback_english_first_code.md` is updated to reflect "all .md files English",
- some reference docs in `docs/` are translated verbatim even though they describe bootstrap-era plans — they will be rewritten when the milestones they describe are revisited.

## 2026-05-14 — OpenAI as the LLM provider for M2.7+

Decision:

- M2.7 implements an `LlmAssistant` interface and an OpenAI provider on top of it. Access via `OPENAI_API_KEY` environment variable. The CLI flag `--llm openai|none` selects the runtime; `none` is the deterministic fallback that lets the pipeline run end-to-end without any LLM call.
- Other providers (Anthropic, Azure OpenAI, local Ollama, …) are not implemented now but can slot in behind the same interface.
- Live `--llm openai` runs are opt-in. CI uses a stubbed assistant by default — no API key needed for the test suite.

Reason:

- the user already has an OpenAI key available; that is the fastest path to a working LLM-assisted recommendation,
- a stubbed assistant in tests keeps regression coverage cheap and deterministic,
- the interface boundary makes it easy to swap providers later if cost, privacy or quality requirements change.

Consequences:

- `openai` becomes a runtime dependency (declared in `pyproject.toml`),
- the report's Recommendations section starting in M2.7 may contain LLM-generated text — every claim must cite either a `Rule_ID` from the knowledge base or be tagged `engineering_estimate`, never invent precise values,
- when `--llm openai` is active, prompts (problem context + retrieved snippets + simulation metrics) leave the local machine via the OpenAI API. The user schematic does not — only structured summaries.

## 2026-05-14 — Embedding strategy for M2.8: local sentence-transformers, pluggable

Decision:

- M2.8 implements an `Embedder` interface and a default implementation that uses `sentence-transformers` locally (one-time ~500 MB model download on first use). The interface allows paid cloud providers (OpenAI, Voyage, Anthropic) to be swapped in via the same configuration mechanism as the LLM provider choice.
- The chosen vector index is decided during the milestone (FAISS or Chroma); either way it is a local file inside the project directory.

Reason:

- the user wants a free POC path but wants the option to upgrade later — a pluggable interface lets that happen without touching downstream consumers,
- local embedding aligns with the local-first principle; knowledge sources never leave the machine in the default configuration,
- the model is small enough to run on a CPU.

Consequences:

- `sentence-transformers` becomes an optional dependency (declared as an extra in `pyproject.toml`, not required for the base install),
- the first run of `knowledge index` downloads the embedding model and may take time,
- if a user opts into a cloud embedding provider, the indexing step sends knowledge-source text (typically vendor docs and standards excerpts, not user schematics) to that provider once.

## 2026-05-14 — LLM scope freeze partially lifted: narrow priority-5 role only

Decision:

- The earlier scope-freeze rule (`feedback_mvp_scope_freeze.md`) that banned LLM-augmented features (RAG, agents) is lifted, but only for the specific roles defined in M2.7–M2.11: LLM-assisted recommendation enrichment, RAG with a knowledge pack, per-area specialist agents, parasitics agent that augments the testbench, and orchestrator synthesis.
- The LLM is priority 5 in the parasitic-suggestion chain (after explicit user/layout data, deterministic calculators, curated rules, knowledge-pack snippets). The LLM must not invent precise values.
- All other scope freezes remain: no UI (M3 still frozen), no billing, no cloud backend, no `.asc` graphical parsing, no autonomous multi-agent orchestration beyond what M2.11 ships.

Reason:

- "RAG without an LLM consumer is busywork" — keyword search over jsonl rules without a downstream synthesizer adds little value over the existing `knowledge list` CLI,
- moving the original M4 plan ("RAG and agents") forward to M2.7–M2.11 lets every commit deliver visible LLM output instead of infrastructure with no consumer,
- a narrow role keeps cost and complexity bounded and preserves the deterministic core's testability.

Consequences:

- `feedback_mvp_scope_freeze.md` is updated to reflect the partial lift,
- M2.7 ships the LLM seam; if the OpenAI provider is configured, the recommendations text is LLM-generated and cited,
- `pyproject.toml` gains the `openai` runtime dependency in M2.7 and a `[pdf]` / `[embeddings]` optional extras in M2.8.

## 2026-05-14 — M2.7 retrieval redacts copyrighted content before sending to the LLM

Decision:

- The M2.7 retrieval layer must never hand raw vendor-document text to the LLM. Every retrieved snippet is reduced to a `RedactedSnippet` carrying `rule_id`, `source_id`, our own concise summary, and at most a ≤ 200-character verbatim excerpt.
- The verbatim excerpt is included **only** when the source's `allowed_use` value (per `schemas/source_manifest.schema.json`) is permissive (`internal_reference` or comparable). Sources marked `link_and_summary`, `check_license`, `user_provided_only`, or `do_not_ingest` contribute **only** `source_id` + our summary — no body text.
- A helper `redact_for_llm(snippet) -> RedactedSnippet` enforces this contract regardless of caller. The prompt template (`prompts/recommendations_v1.md`) only references redacted snippets.
- Tests assert that for a synthetic 5000-character source body marked `link_and_summary`, the prompt logged to `results/llm/<run-id>.jsonl` contains the `source_id` but no substring of the body.

Reason:

- `docs/05_knowledge_ingestion.md` already forbids "copying full PDFs into the product as our own content" and "trening modelu na płatnych normach bez licencji". `docs/09_security_privacy_licensing.md` says "do not redistribute full vendor content as our own database". Sending a retrieved chunk to OpenAI is functionally the same as redistribution if the chunk is verbatim and long.
- `CLAUDE.md` ("Nie kopiuj długich fragmentów dokumentów producentów" → translated to "Do not copy long excerpts from vendor documents") is the load-bearing rule.
- The curated `.jsonl` files (`baza_pasozyty_pcb_rules.jsonl`, `baza_wiedzy_emc_ltspice_rules.jsonl`) already contain our own summaries in fields like `Default_value_for_agent`, `Range_or_sensitivity`, `Use_when`, and `agent_action`. Those fields are safe to send. The source URLs and full document bodies are not.

Consequences:

- M2.7 adds `RedactedSnippet` dataclass + `redact_for_llm()` helper + retrieval test pair (adds ~2 tests beyond the M2.7 baseline of ~12 new tests).
- The rule generalises: every future LLM-using milestone (M2.8 embeddings, M2.9 specialist agents, M2.10 parasitics agent, M2.11 orchestrator) must apply the same redaction before any outbound API call. The auto-memory captures this as a general rule (`feedback_copyright_redaction_for_llm.md`) so future sessions do not relax it.
- Knowledge index quality is preserved — long-form documents stay locally indexed for retrieval scoring; only the LLM-facing surface is redacted. Local-only consumers (CLI, report generator) can still see full bodies when needed.

## 2026-05-14 — Plan adjustments after full-corpus review

Decision:

After reading the complete documentation set (`docs/00`–`docs/10`, `prompts/agents/`, `tasks/`), six adjustments were applied to the M2.7+ plan:

1. **M2.9 expanded from 5 to 10 active specialist agents** to match `docs/04_agent_contracts.md` and the 11 prompt stubs in `prompts/agents/`. The 10 active agents are: power_integrity, dcdc, filtering, decoupling, parasitics, stackup, high_speed, mixed_signal, ic_vendor, layout_risk. Two remaining stubs (acdc, analog) are parked because the MVP focuses on DC/DC conducted EMI, not AC/DC or pure-analog work.
2. **M2.7 gains an AI cost budget flag** (`--llm-budget-usd <amount>`, default 1.00) per `docs/02_user_groups_and_features.md`, plus a per-run privacy log `results/llm/<run-id>.jsonl` per `docs/09_security_privacy_licensing.md`. The pipeline aborts before any OpenAI call if estimated cost exceeds budget.
3. **M2.8 adds `knowledge/processed/`** to the directory list per `docs/05_knowledge_ingestion.md`. It holds chunks, summaries, and the local vector index.
4. **M2.11 explicitly uses `prompts/workflows/conducted_emi_dcdc_workflow.md`** as the orchestration recipe; the file is rewritten as part of M2.11. Orchestration logic lives in a prompt file, not buried in Python, so it can be audited and tuned without code changes.
5. **A new parked milestone M2.12 (variant feedback loop)** is added to acknowledge the `decisions/accepted_changes.json` / `rejected_changes.json` flow and the variant BOM cost / side risks / status fields mentioned in `docs/10_result_handling.md`. Parked until M2.11 ships.
6. **Before M2.9 invents `agent_finding.schema.json`**, existing `schemas/agent_task.schema.json` and `schemas/analysis_result.schema.json` are audited for fit and reused if they cover the contract.

Reason:

- `docs/04`, `docs/05`, `docs/09`, `docs/10` define infrastructure that the initial M2.7–M2.11 sketch didn't fully address. The adjustments close those gaps without changing the milestone shape.
- The agent-count expansion matches what the bootstrap-era contracts envisioned; shipping only 5 of 10 would have left half the prompt stubs orphaned in `prompts/agents/` indefinitely.
- AI cost and privacy guardrails are baseline requirements before any OpenAI integration goes live.

Consequences:

- M2.9 active-agent count roughly doubles (5 → 10), but each marginal agent is small (~50 LOC + a prompt template); the marginal cost is manageable.
- M2.7 task count grows by 2 (budget flag, privacy log) and acceptance criteria grow by 2; no new dependencies.
- M2.12 placeholder ensures the variant-feedback-loop UX isn't silently forgotten when M2.11 ships.
- `prompts/workflows/conducted_emi_dcdc_workflow.md` becomes a load-bearing artefact at M2.11; today it is a bootstrap stub.

## 2026-05-14 — M2.9 schema audit: new `agent_finding.schema.json`

Decision:

- Per the M2.9 plan's first task, `schemas/agent_task.schema.json` and `schemas/analysis_result.schema.json` were audited as candidates for the per-agent output contract. Neither fits.
- `agent_task.schema.json` is the *input* contract (`task_id`, `agent`, `goal`, `inputs`, `constraints`) — it describes the call to an agent, not the agent's output.
- `analysis_result.schema.json` is too broad — it covers a whole project's analysis (`analysis_id`, `project_id`, `scope`, `assumptions`, `parasitic_models`, `simulation_runs`, `recommendations`, `limitations`, `used_sources`). Treating it as one agent's output would force every agent to fill 9 unrelated fields and would conflate per-agent findings with the project-wide bundle the orchestrator produces in M2.11.
- A new `schemas/agent_finding.schema.json` is introduced for the per-agent contract, mirroring the shape in `docs/04_agent_contracts.md`: `agent`, `area`, `confidence`, `findings`, `risks`, `recommendations` (each `$ref` to `recommendation.schema.json`), `missing_data`, `simulation_requests`, `sources`, `limitations`, `llm_generated`.

Reason:

- The plan explicitly mandates "Avoid inventing a parallel `agent_finding.schema.json` if the existing schemas already cover the case" — they don't, so the new schema is justified.
- Reusing `analysis_result.schema.json` would have made every agent emit a synthetic `analysis_id`/`project_id`/`scope` plus partial parasitic-model and simulation-run arrays, which is contortion. `analysis_result` stays meaningful as the **orchestrator's** aggregated output once M2.11 ships.
- Keeping the per-agent contract narrow (findings + risks + recommendations + simulation_requests) leaves the orchestrator free to deduplicate, aggregate, and synthesise without each agent having to anticipate the final report shape.

Consequences:

- Per-agent output lands at `results/findings/<area>.json` and validates against `agent_finding.schema.json`.
- `analysis_result.schema.json` is left untouched; M2.11 may reuse it as the orchestrator's top-level output.
- The new schema cross-references `recommendation.schema.json` for each agent's recommendation entries, so the per-recommendation contract stays identical to the M2.7 baseline (`llm_generated`, `citations`).

## 2026-05-14 — M2.7–M2.11 plan absorbs the old M4

Decision:

- The original M4 milestone ("RAG and agents") is replaced by the M2.7–M2.11 phased plan in `docs/11_roadmap.md`. M4 may later cover more sophisticated multi-step agent coordination once M2.11 is stable.
- Each milestone is independently shippable on its own commit:
  - **M2.7**: LLM provider seam + first LLM-assisted recommendation, keyword retrieval over seed `.jsonl`.
  - **M2.8**: embedded knowledge base, chunker, vector index, `knowledge_pack.json` schema.
  - **M2.9**: specialist agents per area, per-area prompts in `prompts/agents/`.
  - **M2.10**: parasitics agent augments the composer's testbench (never the user `.cir`).
  - **M2.11**: orchestrator synthesizes findings into a top-level diagnostic narrative.

Reason:

- the user pushed back on "RAG without LLM" — every milestone now ships a user-visible LLM artefact,
- slicing into 5 milestones keeps each commit reviewable and lets the project pause between any two,
- the order respects dependencies (provider seam before agents, agents before orchestrator).

Consequences:

- `docs/11_roadmap.md` is updated; old "M4 — RAG and agents" is replaced by an "absorbed" note,
- `tasks/implementation_plan.md` will gain M2.7–M2.11 sections with task lists and acceptance criteria,
- the prompts in `prompts/agents/*.md` (currently bootstrap-era stubs) will be rewritten with concrete I/O contracts during M2.9.

## 2026-05-15 — M2.10: parasitics agent splices X-instances into the testbench

Decision:

- The composer reserves a fixed intermediate net `n_dut_in_pre`. When an injection plan is provided, the cable's downstream port lands on `n_dut_in_pre` instead of the user's supply net; the first injection (typically `TRACE_RLC`) bridges `n_dut_in_pre → <user supply net>` so the parasitic L/R/C is *in series* with the signal path. With an empty plan, the composer falls back to M2.6.1 wiring byte-equivalent — `--no-parasitics` regression-tested.
- Agent → composer contract: new `schemas/parasitic_injection.schema.json`. Each entry has `instance_name` (must start with `X_`), `subckt_name` ∈ {TRACE_RLC, VIA_L, CAP_ESR_ESL}, `nets` (port count validated against `subckt_name`), `rationale`, `rule_id`, `parasitic_id`, `corner`. The composer rejects unknown subckt names.
- AgentFinding gains an optional `injections[]` field; only the parasitics agent populates it. The deterministic fallback emits a default plan (series TRACE_RLC between cable output and DUT supply); the LLM path may extend it.
- CLI: new `--accept-parasitics` / `--no-parasitics` flags, **independent** from `--accept-wiring`. The user chose this split for flexibility (single LISN/cable gate vs separate injection gate).
- Audit file `generated/parasitics_wiring.json` records the plan that drove the simulation.
- Topology deduction (single vs dual LISN by agent) deferred to a parked M2.10.x.

Reason:

- M2.6.1 left a documented gap: the composer emitted `.SUBCKT TRACE_RLC` / `VIA_L` / `CAP_ESR_ESL` definitions but never instantiated them, so the variant sweep didn't move V(MEAS). The injection closes the loop.
- Per-agent Python files (see `feedback_per_agent_python_files`) — the parasitics agent gets a small extension instead of a separate "injection agent".
- New schema beats overloading `simulation_requests` because the composer needs a strict contract to render SPICE; placeholder strings or malformed payloads would crash LTspice.

Consequences:

- For the buck demo the LLM agent now proposes the same plan as the deterministic fallback after the M2.10.2 fix (placeholder leakage + topology piped to agents).
- The variant sweep finally moves V(MEAS) — spread on case_001 is small (≈ 0.2 %) because the buck's existing 1 µH `Ldm` + 4.7 µF `Cin` filter dominates the ~10 nH trace L; an honest engineering finding, not a tool bug.
- 19 new tests (263 total).

## 2026-05-15 — M2.10.1: feature-keeper signal-map + 11th specialist agent

Decision:

- User-meaningful signals (`Vout`, `Iout`, `V_5V_aux`, ...) are maintained across pipeline transformations via a new "feature-keeper" layer. Hybrid declaration: deterministic auto-detect from `.asc` `FLAG` labels + `.cir` net-name heuristics; user-declared `user_context.signals[]` takes precedence (user > asc > cir).
- New schema `schemas/signal_map.schema.json`.
- CLI: `--accept-signals` / `--no-signals` flags. On acceptance, the resolved map is **persisted back into `user_context.json`** so subsequent runs don't re-prompt. The user explicitly chose this over a generated-only audit file because the signal map is part of the user's project intent.
- Composer emits `.meas TRAN <name>_peak / _rms / _avg` for each signal so the user's vocabulary lands in the `.log` alongside the canonical `v_meas_*` / `dm_*` / `cm_*`.
- New 11th specialist agent `signal_map_agent` (orchestrator `AGENT_CLASSES` 10 → 11). LLM-driven refinement (renames, target bands, current-probe proposals); deterministic fallback echoes the map.
- Report grows a "Tracked user signals (M2.10.1)" section.

Reason:

- The user (`save memory` request 2026-05-15) flagged this as a recurring need: signals like Vout / Iout should survive `.asc → .cir` conversion, fragment preprocessing (`0 → DUT_GND` rename), and parasitic injection (introducing `n_dut_in_pre`). The composer must speak the user's vocabulary in the `.meas` directives.
- The hybrid declaration option matches the user's "first deduce, then ask, allow change" workflow.

Consequences:

- 24 new tests (287 total).
- `user_context.json` is now mutated by the pipeline (when the user accepts via `--accept-signals` or TTY prompt) — a deliberate departure from the M2.6.1 rule that user files are read-only. The mutation is gated and the new fields are additive (top-level `signals` key) so existing tooling is unaffected.

## 2026-05-15 — M2.10.2: prompt hardening + topology forwarded to agents

Decision:

- Replace the placeholder `<user_supply_net>` in the parasitics prompt's example with a concrete net name + an explicit "net names are literal" rule. The LLM was copying the placeholder verbatim into its injection plan, producing netlists LTspice would reject.
- Replace the soft `Return ONLY the JSON object.` closing line in every agent prompt (11 files) with a `## FINAL INSTRUCTION — strict output` block that explicitly forbids markdown fences, code comments, prose, and trailing remarks.
- `cmd_report_generate` now populates `AgentContext.topology` (via `analyse_fragment(user_fragment)`) + `dut_supply_net` + `dut_return_net` (from `user_context.testbench_wiring`, with the dual-LISN `0 → DUT_GND` rename applied). Without these the agents only saw `(not supplied)` and correctly refused to invent net names.

Reason:

- Buck smoke test #1 (M2.10.1) showed two issues: (a) parasitics LLM emitted `nets: ['n_dut_in_pre', '<user_supply_net>', 'DUT_GND']` verbatim — placeholder leak; (b) stackup + high_speed agents returned text outside JSON braces and fell back to deterministic.
- Both fixes converged in smoke test #3: 0 fallbacks, LLM injection matches the deterministic plan literally, $0.0429 / 12 calls.

Consequences:

- No new tests (the existing prompt-construction tests cover the message format).
- Documented as M2.10.2 in the roadmap.

## 2026-05-15 — M2.10.3: LTspice `.asc` visualisation export

Decision:

- The composer-generated `testbench.cir` remains canonical (what LTspice runs in batch). A **visualisation companion** `testbench.asc` is emitted alongside, opening as a real schematic in LTspice with hierarchical block symbols for the LISN, cable, M2.10 parasitic injection, B-source probes, and a DUT placeholder. The user's `.cir` is referenced via a `!.include` TEXT directive — the `.asc` is fully runnable.
- 6 `.asy` symbol files (`LISN50UH.asy`, `CABLE_PWR.asy`, `TRACE_RLC.asy`, `VIA_L.asy`, `CAP_ESR_ESL.asy`, `DUT_FRAGMENT.asy`) ship alongside the `.asc` in `generated/`.
- New CLI flag `--no-asc-export` for users who don't want the bundle.
- `scripts/plot_schematic.py` (post-hoc PNG visualiser, added in M2.10.2) is polished: deduplicated MEAS_P label, probe wires routed through a single "probe bus", new `--expand-user-fragment` flag.

Reason:

- The user (this session) wanted to verify visually that the LISN + cable + injection were wired correctly without reading SPICE source. The `.asc` is also useful for hand-modification + re-simulation outside the pipeline.
- Two parallel renderings — `.asc` for LTspice, PNG for the markdown report — was the user's explicit choice over a single output.

Consequences:

- 12 new tests (299 total) covering `.asy` header / pin names / prefix, `.asc` section presence, FLAG labels, bundle completeness, write_asc_bundle output.
- `generated/` grows the `.asc` + 6 `.asy` files per run; all gitignored. Reports/ grows `<project>_schematic.png` + optional `*_expanded.png`.

## 2026-05-16 — M2.10.4–.8: per-net parasitic injection

Decision:

- The parasitics agent estimates and injects a parasitic on **every net** of the user fragment, not just the input rail. A *shunt C* to the return node is the universal per-net parasitic (works on any net); a *series R+L+C* splice is added only on clean 2-element point-to-point nets, where the fragment preprocessor can cut a clean injection point (`<net>__pre`). 3+-element star/bus nets get the shunt C only — guessing a series cut point on them would need layout.
- The series cut edits the processed fragment copy (`generated/user_circuit_fragment.cir`), never the user's original `.asc`/`.cir`.
- An opt-in LLM negligibility screen (`--llm openai`) drops parasitics the LLM is confident are insignificant for conducted EMI; it fails safe (keeps everything) on any error. Default stays deterministic.
- Every parasitic inductance carries a parallel Q-damping resistor (`Rd = 2*pi*200 MHz*L`). `--parasitics-report-only` keeps the per-net estimates out of the simulated netlist entirely.
- PCB-parasitics knowledge set `S032`–`S036` added; 10 proposed rules staged (not auto-indexed) for review before promotion.

Reason:

- The user asked for whole-schematic parasitic coverage so the conducted-EMI analysis is honest, with three opt-outs: LLM-negligible, user-accept, or project-setup values.
- The real-LTspice run (M2.10.8) showed the tiny pF/nH parasitics form undamped GHz LC tanks that collapse LTspice's transient timestep — a 6 s buck sim became a >120 s / 3.4 GB runaway. The Q-damping corner sits above the 9 kHz–30 MHz conducted-EMI band, so in-band results are preserved while the GHz tanks cannot ring. The report-only flag is the escape hatch the user explicitly asked to keep.

Consequences:

- 86 new tests (385 total). Real-LTspice verified: case_001 per-net testbench 14.2 s, case_002 3.1 s, both completing.
- New audit files per project: `parasitics_series.json`, `parasitics_shunt.json`, `parasitics_dropped.json`.
- Future: per-net parasitic *selection* will become an interactive UI gesture once M3 ships; the report-only flag + project overrides are the substrate.
## 2026-05-16 — M2.10.x: LISN-mode agent (pre-composition)

Decision:

- A 12th specialist agent, `LisnModeAgent`, decides single vs dual LISN
  for the conducted-EMI testbench. Unlike the eleven post-simulation
  report agents, it runs **before** the testbench is composed — the
  dual/single choice changes the testbench structure itself (dual-LISN
  lifts the DUT ground to `DUT_GND` and enables the DM/CM split), so the
  decision cannot wait for the post-sim orchestrator fan-out.
- `decide()` is the entry point: LLM path under `--llm openai`,
  deterministic heuristic otherwise (dual unless the project context
  signals a chassis/earth-bonded return). Any LLM error or malformed
  response falls back to the heuristic.
- An explicit `lisn_mode` in `user_context.testbench_wiring` always
  overrides the agent; `"auto"` or absent hands the call to the agent.

Reason:

- The user asked that the LISN mode be deduced rather than set by hand,
  and chose a full LLM agent (over a deterministic-only helper) so the
  reasoning can weigh ambiguous topologies. The early-vs-late lifecycle
  was flagged during design — an agent in the post-sim fan-out could
  only advise; to actually pick the mode it must run pre-composition.

Consequences:

- New CLI resolver `_resolve_lisn_mode`; decision audited to
  `results/lisn_mode.json`.
- 10 new tests (395 total). Verified on real OpenAI: buck demo →
  dual-LISN, confidence 0.90, with a topology-grounded rationale.
- The orchestrator's post-sim fan-out stays at 11 agents; the LISN-mode
  agent is the 12th but runs in the pre-composition phase.
## 2026-05-16 — M2.12: recommendation feedback loop (not "variant")

Decision:

- M2.12's accept/reject feedback loop operates on agent
  **recommendations**, not on the codebase's `Variant`. A `Variant` is
  a parasitic corner-sweep point (min/typ/max) — every corner is
  simulated to bound uncertainty; there is nothing to "accept". The
  decidable artifact is the `Recommendation` (it carries a
  `proposed_change`).
- Decisions persist to `decisions/accepted_changes.json` +
  `decisions/rejected_changes.json`, keyed `<area>/<rec_id>`. The report
  shows a status badge per recommendation and reruns reflect prior
  decisions.
- `bom_cost_estimate` / `side_risks` (from the original plan text) are
  optional, user-supplied fields on the decision record — the agents do
  not produce cost/side-risk data today.

Reason:

- The plan and `docs/10` used "variant" loosely. Building it literally
  would have meant a new mitigation-variant object plus extending all
  12 agents to emit cost data. The user confirmed the lean
  interpretation (operate on recommendations), which matches the
  codebase and the UI brief (recommendation cards are accept/reject).

Consequences:

- New `recommendations` CLI group; `ProjectLayout.decisions_dir`.
- 11 new tests. The recommendation key `<area>/<rec_id>` is stable for
  deterministic recommendations; for LLM-written ones whose ids can
  drift between runs the match is best-effort, with the stored
  `problem` snapshot keeping the record auditable.

## 2026-05-16 — M2.13: structured simulation settings

Decision:

- `user_context.simulation` gains structured fields (`stop_time`,
  `max_timestep`, `record_start`, `startup`, `integration_method`, a
  generic `options` dict) that the composer turns into `.tran` and
  `.options`. The single raw `tran_directive` string is kept as an
  advanced override and, when present, wins over the structured fields.
- Advanced solver options (reltol, abstol, gmin, cshunt) go through the
  generic `options` dict — no field per option.

Reason:

- The solver-settings UI panel (`docs/design/ui_design_brief.md`) needs
  structured fields to bind to; a single opaque `.tran` string cannot
  back a form. Validation (e.g. `max_timestep <= stop_time`) belongs in
  the backend, not only the UI.

Consequences:

- `testbench/sim_settings.py` (`SimulationSettings`); `composer.py`
  gains `options_directive`. Backward compatible — the default and
  case_002's raw override are unchanged. 20 new tests.

## 2026-05-21 — parasitics-strategy chat moved out of M2; M5+ renumbered

Decision:

- The conversational parasitics-strategy chat, briefly proposed as
  M2.18, is moved out of the M2 series. It becomes **M5**, sequenced
  after M4 (multi-agent / tool-use), which it builds on.
- The later milestones shift down by one: Pro M5→M6, layout / radiated /
  corporate M6→M7, real-time lab + collective learning M7→M8.

Reason:

- The chat is open-ended tool-use / agent-dialog work that belongs with
  the M4 family, not with the deterministic-core M2.x enhancements
  (M2.16 CM coupling, M2.17 LLM/RAG value re-evaluation), which ship
  independently and sooner.
- The user chose a full renumber (over folding into M4 or a low-churn
  M4.1 sub-milestone) so the sequence stays cleanly sequential.

Consequences:

- `tasks/m2_18_parasitics_strategy_chat.md` renamed to
  `tasks/m5_parasitics_strategy_chat.md`; every "M6 = layout extraction"
  reference across docs, prompts, task files and source comments bumped
  to M7 (layout is now M7). `M3` (UI) and `M4` (multi-agent) unchanged.
- Two UI preview labels (`preview-lab.jsx`, `preview-training.jsx`) use a
  separate, pre-existing numbering and are left for a dedicated pass.

## 2026-05-22 — M2.18 comparative waveform analyzer (number reused)

Decision:

- Added **M2.18 — a two-panel, time-aligned waveform analyzer** on the
  Results screen: `V(meas)` (top) over one selectable comparison trace
  (bottom). The two panels share the **X (time) axis only**; each
  auto-scales its own **Y** (volts or amps). The default comparison trace
  is the **load current `I(Rload)`**, resolved deterministically; the
  selector offers four further traces deduced by the LLM (cloud LLM on)
  or a topology heuristic (off).
- The M2.18 number is reused: the old M2.18 (parasitics chat) had already
  moved to M5 on 2026-05-21, so the slot was free.

Reason (the two design forks, confirmed with the user):

- **Shared X, independent Y** — the goal is *correlating events in time*
  ("this switching edge → this EMI spike"); a forced-identical Y would
  flatten the small `V(meas)` ripple under a large rail and bars currents
  entirely. Time-alignment is the load-bearing requirement.
- **Default = load current** (not load voltage) — the user wants the
  converter's output draw as the at-a-glance comparison.

Consequences:

- New `agents/waveform_trace_agent.py` (one-class-per-file; **not** in the
  orchestrator fan-out — invoked by `service/waveform.py`, like
  `lisn_mode_agent`) + prompt; `service/raw.py` `load_waveform(trace=…)`
  gains per-trace caching + `kind`/`unit`; `Api.suggest_waveform_traces`
  / `Api.load_waveform(trace)`.
- Visualization aid only — selects *which* traces to plot; no fabricated
  values, no compliance claim, no netlist sent (structured summaries
  only), fail-safe to the heuristic. Shares `--llm-budget-usd`.
- Conversational control of the selection deferred to **M5**.

## 2026-05-22 — M2.17 parasitic value re-evaluation: post-pass, batched, typ-only apply

Decision:

- M2.17 is a **post-estimate refinement pass**, not a new
  `ParasiticValueSource`. The ABC is `estimate(net, role)` (one call per net);
  a value refinement wants **one batched LLM call over all non-ground nets**
  for cost, so it refines on top of the deterministic `estimate_all_nets()`
  output.
- The **deterministic rule-of-thumb estimate stays the prior/fallback.** Any
  net the LLM errors on, omits, or returns an unusable band for keeps its
  prior verbatim. Weak retrieval → keep the prior, widen the band, lower
  confidence (never replace a value with an uncited guess).
- **`--apply` persists only typ values** as explicit user overrides
  (`user_context.parasitics.per_net` r_mohm/l_nh/c_pf). The full min/typ/max
  bands, prior-vs-refined delta, confidence, rationale and citations live in
  the audit `generated/parasitics_reevaluated.json` only — never silently
  applied.
- Provenance is disclosed per net in the report (`source` column):
  calculator (rule-of-thumb) / LLM-refined (RAG) / LLM (uncited est.).

Reason:

- Cost + the "bias to the deterministic prior" guardrail (user, 2026-05-22).
- Privacy: only redacted snippets + structured per-net summaries are sent,
  never the netlist (reuses the M2.7 redaction path).

Consequences:

- `agents/parasitics_agent.reevaluate_values` (sibling to `filter_negligible`)
  + `service/parasitics.reevaluate_parasitics` + CLI `parasitics reevaluate` +
  `Api.reevaluate_parasitics` + `schemas/parasitics_reevaluated.schema.json`.
- The UI was wired 2026-05-23 (user-directed, overriding the initial defer):
  an "AI: re-evaluate values (RAG)" button on the Parasitic-selection screen +
  a review-before-apply proposals panel; accept persists typ-only from the
  audit (no second LLM call) via `apply_reevaluated_parasitics`. A disabled
  "Read from layout (M7)" placeholder sits beside it.
