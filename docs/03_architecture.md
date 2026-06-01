# Technical architecture

## MVP version (post M2.10.3)

CLI + local LTspice runner + deterministic core + LLM-augmented layer (11 specialist agents, embedded knowledge base, signal-map feature-keeper, parasitic injection, `.asc` visualisation export).

```text
User project (.emcproj + .asc/.cir + user_context.json)
  -> project loader
  -> context resolution (wiring + parasitics injection + signals)   [M2.6.1 / M2.10 / M2.10.1]
  -> parasitic estimator
  -> testbench generator    -> testbench.cir  + testbench.asc + .asy bundle   [M2.10.3]
  -> variants compose
  -> LTspice adapter (local batch)
  -> result parser (.raw + .log + FFT spectrum dBµV)               [M2.5 / M2.6 / M2.8.2]
  -> knowledge retrieval (vector or keyword + copyright redaction)  [M2.7 / M2.8]
  -> recommendation engine (deterministic OR LLM-written)           [M0 / M2.7]
  -> specialist agent orchestrator (11 active agents)               [M2.9 / M2.10 / M2.10.1]
  -> report generator (Markdown, with per-area subsections)
```

## Front-ends and the service layer

`src/emc_assistant/service/` is the application **service layer** — the core
both front-ends call. Each use case is a plain function (`service.project`,
`service.parasitics`, `service.testbench`, `service.simulate`,
`service.report`, `service.pipeline`, `service.knowledge`, `service.raw`,
`service.netlist`): it takes plain parameters or a `CommandOptions`, returns
a typed result dataclass, raises `ServiceError` for expected failures, and
logs progress through the logging seam (`logging_setup`). `cli.py` is a thin
`argparse` adapter over it; the M3 desktop UI calls the same functions
in-process. The domain packages below stay focused on domain logic; the
service layer owns the use-case orchestration. See
`docs/design/ui_backend_contract.md` and `docs/design/logging_design.md`.

## Modules

### Project Manager

- create a project,
- validate configuration,
- manage directories,
- track versions of generated files.

### Knowledge Loader

- load JSONL from `knowledge/seed`,
- validate the rule schema,
- search rules by domain / tags,
- return sources for the report.

### Parasitic Estimator

- trace calculators,
- via calculators,
- polygon calculators,
- cable calculators,
- resonance calculators,
- generate min / typ / max.

### Testbench Generator

- generate `.cir`,
- LISN models,
- cable models,
- filter models,
- `.step` parameterization,
- keep user files separate from generated files.

### LTspice Adapter

- discover the installation,
- manual path configuration,
- batch mode,
- log the command,
- never distribute LTspice.

### Result Parser

- `.log` as a minimum,
- `.raw` as an adapter / stub in M0,
- later, waveform reading and metric export.

### Recommendation Engine

- input: results + assumptions + rules,
- output: `recommendation.schema.json`,
- severity / confidence,
- evidence / limitations,
- proposed changes.

### Report Generator

- Markdown,
- HTML later,
- charts later,
- pre-compliance disclaimer.

### LLM Provider Seam (M2.7)

- `LlmAssistant` ABC with three implementations: `OpenAiAssistant` (live), `DeterministicAssistant` (no-LLM fallback), `StubAssistant` (tests).
- Low-level `complete(messages, purpose)` method shared by recommendations and per-agent calls; high-level `explain_recommendations(...)` builds the recommendations prompt.
- Run-level `BudgetTracker` enforces a cumulative cap across all calls in one pipeline run.
- Privacy log at `results/llm/<run-id>.jsonl` captures every payload that leaves the machine.
- Copyright-safe redaction (`redact_for_llm`) reduces retrieved snippets to `rule_id` + `source_id` + our summary + ≤ 200-char excerpt (only when allowed_use permits).

### Embedded Knowledge Base (M2.8)

- Chunker for `.md` / `.txt` / `.html` / `.jsonl` / `.pdf` (PDF via optional `[pdf]` extra).
- `Embedder` interface; default `SentenceTransformersEmbedder` (`all-MiniLM-L6-v2`, 384-dim).
- Pure-numpy `NumpyVectorIndex` with cosine similarity (no FAISS / Chroma dependency).
- `knowledge_pack.json` schema for the bounded pack consumed downstream.
- CLI: `knowledge index | search | build-pack`.
- Tier directories: `seed/` (committed), `raw_sources/` (downloads), `user_private_sources/`, `licensed_sources/`, `processed/` (chunks + index).

### Specialist Agent Layer (M2.9 + M2.10 + M2.10.1)

- 11 active per-area agents in `src/emc_assistant/agents/`, each with a prompt under `prompts/agents/<area>_agent.md`:
  `dcdc`, `filtering`, `power_integrity`, `decoupling`, `parasitics`, `stackup`, `high_speed`, `mixed_signal`, `ic_vendor`, `layout_risk`, `signal_map` (M2.10.1).
- 2 parked stubs (`acdc`, `analog`) kept in `prompts/agents/` but not loaded by the orchestrator.
- `Agent` ABC + `AgentFinding` dataclass mirror `schemas/agent_finding.schema.json`.
- `orchestrator.py` fans out, validates each finding against the schema, writes `results/findings/<area>.json`. Falls back to per-agent deterministic on `BudgetExceeded` or malformed JSON without taking down the run.
- Parasitics agent in M2.10 also emits an `injections[]` field (per `schemas/parasitic_injection.schema.json`). The composer reads the resolved plan, reroutes the cable to an intermediate net `n_dut_in_pre`, and renders the X-instances literally.
- Signal-map agent in M2.10.1 refines the auto-detected signal map (renames, target bands, current-probe proposals).

### Netlist topology + signals (M2.10 + M2.10.1)

- `netlist/topology.py` produces a `TopologyReport` from a parsed user fragment: power-supply candidates (V-source positives + high-fanout non-ground nets), return candidates, switching-node candidates (S/Q/M element neighbours), capacitor terminals.
- `netlist/signals.py` auto-detects user signals from `.asc` `FLAG` labels (encoding-tolerant) + `.cir` net-name heuristics (`Vout`/`Vin`/`V_5V`/...). Merges with `user_context.signals[]` (user > asc > cir).

### LTspice schematic export (M2.10.3)

- `testbench/asy_templates.py` emits hierarchical-block `.asy` symbols for every composer-side `.SUBCKT`.
- `testbench/asc_writer.py` builds a complete `testbench.asc` on a 16-px LTspice grid with placed symbols, wires, FLAG labels, and a `!.include` TEXT directive that pulls in the user `.cir`. Opens in LTspice as a real schematic; the `.cir` remains canonical for batch simulation.
- `scripts/plot_schematic.py` post-hoc PNG visualiser; supports `--expand-user-fragment`.

## Data storage

MVP:

- local files,
- JSON / YAML,
- no server.

Later:

- local SQLite,
- workspace sync,
- license server,
- corporate on-premise.

## Data security

- schematics stay local by default,
- explicit consent for sending to an LLM,
- a "no cloud" mode is available,
- diagnostic results can be anonymized,
- transparent logging of what was sent to the model.
