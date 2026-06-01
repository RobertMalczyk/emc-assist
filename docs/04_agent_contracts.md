# Agent contracts

Implemented in M2.9–M2.10.1. 11 active specialist agents fan out from `src/emc_assistant/agents/orchestrator.py`; each writes `results/findings/<area>.json` validated against `schemas/agent_finding.schema.json`. Prompts live in `prompts/agents/<area>_agent.md`.

## Shared format

Each agent receives (mirrors `AgentContext` in `agents/base.py`):

- `problem_context` — project metadata (topology, V_in, switching frequency, conducted-EMI band, `has_layout`, `has_stackup`, `missing_data`).
- `parasitics` — list of `ParasiticEstimate` (min/typ/max bands).
- `sim_metrics` — measured peak/rms/band metrics from the `.log` / `.raw`.
- `snippets` — redacted knowledge-base snippets (rule_id + source_id + our summary + ≤ 200-char excerpt only when `allowed_use` permits).
- `baseline_recs` — deterministic recommendations from the M0 engine.
- `topology` — net-structure report from `netlist/topology.py` (power-supply candidates, return candidates, switching nodes, capacitor terminals).
- `dut_supply_net`, `dut_return_net` — concrete net names from `user_context.testbench_wiring` (after dual-LISN `0 → DUT_GND` rename).
- `signals` (M2.10.1) — the resolved user signal map.

Each agent returns a JSON object validated against `schemas/agent_finding.schema.json`:

- `findings` — observations (title + detail + severity).
- `risks` — what may go wrong (title + detail + likelihood).
- `recommendations` — `$ref` to `schemas/recommendation.schema.json`.
- `missing_data` — inputs the agent would have liked.
- `simulation_requests` — follow-up sims (kind: `tran` / `ac` / `sweep`).
- `confidence` — 0.0 – 1.0 self-rating.
- `sources` — cited `Rule_ID` strings (or `engineering_estimate`).
- `limitations`.
- `llm_generated` — true when the LLM path ran; false for deterministic fallback.
- `injections` (M2.10, parasitics agent only) — `$ref` to `schemas/parasitic_injection.schema.json`. The composer reads this and splices `X_TRACE_RLC` / `X_VIA_L` / `X_CAP_ESR_ESL` instances into `testbench.cir`.

## Coordinator agent

Goal:

- gather context,
- split the task,
- assess contradictions,
- prioritize risks,
- assemble the final report.

Must not:

- guarantee EMC compliance,
- ignore data limitations,
- treat the user's hypothesis as a fact.

## Power-analysis agent

Goal:

- analyze power rails,
- identify current loops,
- detect ripple / ringing risks,
- assess input/output stability.

## DC/DC converter agent

Goal:

- identify the hot loop,
- the switch node,
- snubbers,
- input/output filters,
- sources of conducted EMI.

## High-speed signals agent

Goal:

- identify clock and communication lines,
- assess the need for termination,
- assess the return-current path,
- emission risk from fast edges.

## IC vendor recommendations agent

Goal:

- compare the design against datasheet / reference design,
- identify required values and layout rules,
- detect deviations.

Requirement:

- without a datasheet source, the agent must not pretend to know a specific IC.

## Filtering agent

Goal:

- selection of DM / CM topology,
- damping,
- peaking,
- ferrite beads,
- common-mode choke,
- value sweep.

## Stack-up agent

Goal:

- assess the effect of layer count,
- signal-to-plane distance,
- power-ground plane capacitance,
- return paths.

## Decoupling capacitors agent

Goal:

- ESR / ESL / SRF,
- DC bias,
- via inductance,
- antiresonances,
- selection of mounted-capacitor models.

## Mixed-signal agent

Goal:

- analog / digital separation,
- ADC / DAC references,
- analog supply,
- AGND / DGND as a return-path issue, not a magic ground split.

## Layout-risk agent (M2.9 active — partial)

Goal:

- enumerate layout-dependent failure modes the schematic cannot expose,
- recommend a layout review or extraction pass before the next iteration,
- always flag `missing_data: "layout file not supplied"`.

Status:

- M2.9 ships the "no-layout" partial role.
- Full layout-extraction agent (Gerber / ODB++ / KiCad PCB parsing, real R/L/C extraction, plane-gap detection, via-stitching density) is out of MVP scope; deferred to M7.

## Signal-map agent (M2.10.1 active — feature-keeper)

Goal:

- maintain stable, user-meaningful names (`Vout`, `Iout`, `V_5V_aux`, ...) for the signals the user cares about, across schematic preprocessing, parasitic injection, and variant generation,
- refine the auto-detected map (deterministic deduction from `.asc` FLAG labels + `.cir` net heuristics) via LLM judgment: renames, target-band proposals, current-probe suggestions,
- emit refinements as `recommendations` with `proposed_change.type ∈ {signal_rename, signal_retype, signal_add_target_band, signal_drop, signal_add}`.

The agent does **not** mutate the map this run. The user applies refinements by editing `user_context.signals[]` (or by accepting the next `--accept-signals` prompt).

## Parked stubs

- `acdc_agent` — AC/DC topologies (PFC, flyback, LLC), X/Y caps, line-frequency CM chokes. Parked stub in `prompts/agents/`; not loaded by the orchestrator.
- `analog_agent` — pure-analog circuits. Parked stub.
