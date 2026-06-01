# User groups and features

## Free

- local project,
- basic EMC rules,
- basic PCB parasitics,
- a single LISN testbench (single or dual mode),
- manual netlist export,
- a simplified report,
- no advanced sweeps,
- no cloud-hosted project history,
- no automatic layout analysis.

## Premium / Pro

- local LTspice runner,
- automatic sweeps + min/typ/max corner variants,
- filter-variant ranking,
- CISPR-style dual-LISN topology with DM/CM probes (M2.8.3),
- FFT spectrum in dBµV with per-band peaks (M2.8.2),
- a richer HTML / PDF report,
- stack-up profiles,
- cable profiles,
- a parasitic-model library,
- M2.10 parasitic injection — actual X-instances spliced into the testbench so the variant sweep moves V(MEAS) (CLI flag: `--accept-parasitics`),
- M2.10.1 feature-keeper — auto-detected user signals (Vout, Iout, ...) tracked across pipeline transformations and persisted to `user_context.json` (`--accept-signals`),
- M2.10.3 `.asc` visualisation — open the auto-assembled testbench in LTspice (`--no-asc-export` opts out),
- `.raw` / `.log` analysis,
- LLM-assisted recommendations (M2.7) + 11 specialist per-area agents (M2.9 / M2.10.1) (`--llm openai`),
- embedded knowledge base + copyright-redacted retrieval (M2.8),
- interactive recommendations,
- a larger AI budget (`--llm-budget-usd <amount>`, default 1.00),
- privacy log auditing every payload sent to the LLM (`results/llm/<run-id>.jsonl`),
- local project history.

## Corporate

- offline / on-premise mode,
- no schematic upload to the cloud,
- central user management,
- central budget management,
- the company's own API key,
- a private RAG knowledge base,
- change auditing,
- branded reports,
- integration with a project repository,
- roles and permissions.

## AI budget

- daily limit,
- monthly limit,
- per-project limit,
- per-analysis limit,
- a warning before an expensive analysis,
- cost history,
- an admin panel in a later version.

## OpenAI / API keys

- a regular user: ideally no need for their own key,
- Pro: product key or an optional user-supplied key,
- Corporate: BYOK as an option,
- keys stored locally with encryption,
- no logging of schematic content without user consent.
