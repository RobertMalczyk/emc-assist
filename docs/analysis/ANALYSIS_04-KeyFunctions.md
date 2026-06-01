# ANALYSIS 04 — Key Function Analysis (EMC/LTspice Assistant)

> `codebase-analysis` skill, Phase 5. Each critical function is analysed against
> its real body with an inline `VERIFY` tag (`path:line`). Re-run after code
> changes (line numbers drift).

## Table of contents
- [1. `run_pipeline`](#1-run_pipeline)
- [2. `generate_report`](#2-generate_report)
- [3. `run_simulation`](#3-run_simulation)
- [4. `compose_testbench_cir`](#4-compose_testbench_cir)
- [5. `run_agents`](#5-run_agents)
- [6. `rank_variants`](#6-rank_variants)
- [7. Verification report](#7-verification-report)

---

## 1. `run_pipeline`

The single orchestration entry  [VERIFY: src/emc_assistant/service/pipeline.py:78].

**Flow:**
1. Reset the cancel flag and load project + `user_context`
   [VERIFY: src/emc_assistant/service/pipeline.py:84].
2. **Resolve wiring once** for the whole run; sub-steps inherit it
   [VERIFY: src/emc_assistant/service/pipeline.py:90].
3. If the user netlist exists, prepare the spliced fragment (series parasitics)
   [VERIFY: src/emc_assistant/service/pipeline.py:112]; resolve the injection +
   shunt plans  [VERIFY: src/emc_assistant/service/pipeline.py:126].
4. Thread all pre-resolved decisions into a `child` options object
   [VERIFY: src/emc_assistant/service/pipeline.py:149].
5. Run the **six stages**, each preceded by a cancel check and a `N/6` log line
   [VERIFY: src/emc_assistant/service/pipeline.py:159]: estimate → compose
   testbench → compose variants → run variants → run single testbench → report
   ([VERIFY: src/emc_assistant/service/pipeline.py:164],
   [VERIFY: src/emc_assistant/service/pipeline.py:179]).

**Failure behaviour:** a partial variants run (e.g. no LTspice) only logs a
warning and the pipeline still proceeds to the report
[VERIFY: src/emc_assistant/service/pipeline.py:171] — the report is never
skipped just because simulation degraded.

---

## 2. `generate_report`

Runs the LLM/agents layer and renders the report + recommendations JSON
[VERIFY: src/emc_assistant/service/report.py:258].

**Flow:**
1. Build parasitics, LISN/cable fragments, baseline recommendations and the
   problem context  [VERIFY: src/emc_assistant/service/report.py:281]; retrieve
   redacted KB snippets  [VERIFY: src/emc_assistant/service/report.py:283].
2. Construct the assistant (deterministic unless LLM is enabled + keyed)
   [VERIFY: src/emc_assistant/service/report.py:286] and ask it to explain
   recommendations  [VERIFY: src/emc_assistant/service/report.py:292]; a budget
   overrun is surfaced as a `ServiceError`
   [VERIFY: src/emc_assistant/service/report.py:300].
3. Re-analyse the fragment topology and compute per-net estimates to feed the
   agents concrete net names
   ([VERIFY: src/emc_assistant/service/report.py:325],
   [VERIFY: src/emc_assistant/service/report.py:332]).
4. Fan out to the 11 specialist agents
   [VERIFY: src/emc_assistant/service/report.py:391].

---

## 3. `run_simulation`

The local-LTspice boundary  [VERIFY: src/emc_assistant/ltspice/runner.py:121].

**Flow / modes:**
- Builds the batch command + expected `.log`/`.raw` paths and a `planned`
  result  [VERIFY: src/emc_assistant/ltspice/runner.py:146].
- **dry-run:** marks `dry_run` and (if no LTspice) warns — never invokes LTspice
  [VERIFY: src/emc_assistant/ltspice/runner.py:155].
- **local-run:** if LTspice is absent it fails cleanly
  [VERIFY: src/emc_assistant/ltspice/runner.py:163]; otherwise it runs the
  subprocess with a timeout  [VERIFY: src/emc_assistant/ltspice/runner.py:171].
  A non-zero exit → `failed`; a `TimeoutExpired` → **`timeout`** status
  [VERIFY: src/emc_assistant/ltspice/runner.py:187] (this is exactly why the
  demo single-run record shows `timeout`).
- **Fail-safe metrics:** on success, parse `.raw` for metrics
  [VERIFY: src/emc_assistant/ltspice/runner.py:201] and pull `.meas` results
  from `.log`  [VERIFY: src/emc_assistant/ltspice/runner.py:213].

---

## 4. `compose_testbench_cir`

Renders `testbench.cir` from a `TestbenchPlan`
[VERIFY: src/emc_assistant/testbench/composer.py:197].

**Key property — the user circuit is read-only:** the user netlist is brought in
via `.include`, never edited
[VERIFY: src/emc_assistant/testbench/composer.py:207].

**Flow:**
- Emit the LISN subckt + cable fragment
  [VERIFY: src/emc_assistant/testbench/composer.py:213].
- Auto-wire dual-LISN (supply+ and return each through their own LISN, CISPR
  style)  [VERIFY: src/emc_assistant/testbench/composer.py:227] or single-LISN
  legacy  [VERIFY: src/emc_assistant/testbench/composer.py:237].
- When an injection plan exists, the cable lands on an intermediate net so the
  first parasitic X-instance sits in series between cable and the user supply
  [VERIFY: src/emc_assistant/testbench/composer.py:226].
- Append trace R+L+C and via-L fragments when present
  [VERIFY: src/emc_assistant/testbench/composer.py:247].

---

## 5. `run_agents`

The orchestrator fan-out  [VERIFY: src/emc_assistant/agents/orchestrator.py:89].

**Flow:**
- Iterate the fixed roster, running each agent and writing its finding JSON
  ([VERIFY: src/emc_assistant/agents/orchestrator.py:119],
  [VERIFY: src/emc_assistant/agents/orchestrator.py:129]).
- **Budget-cap handling:** if the shared budget trips mid-run, the remaining
  agents are filled with their *deterministic* findings so the run still
  produces all 11  [VERIFY: src/emc_assistant/agents/orchestrator.py:132].
- A single `BudgetTracker` is threaded across all agents (one cap per
  `pipeline run`), per the module docstring
  [VERIFY: src/emc_assistant/agents/orchestrator.py:10].

---

## 6. `rank_variants`

Pure ranking over `simulation_run.json` dicts (no LTspice)
[VERIFY: src/emc_assistant/results/ranking.py:25]: keep comparable entries
[VERIFY: src/emc_assistant/results/ranking.py:39], sort by the metric
[VERIFY: src/emc_assistant/results/ranking.py:53], and compute baseline deltas
[VERIFY: src/emc_assistant/results/ranking.py:60].

---

## 7. Verification report

| Function | Key property | Evidence | Status |
|---|---|---|---|
| `run_pipeline` | six cancel-checked stages | [VERIFY: src/emc_assistant/service/pipeline.py:159] | ✓ |
| `run_pipeline` | report runs even on partial sim failure | [VERIFY: src/emc_assistant/service/pipeline.py:171] | ✓ |
| `generate_report` | budget overrun → ServiceError | [VERIFY: src/emc_assistant/service/report.py:300] | ✓ |
| `run_simulation` | TimeoutExpired → `timeout` status | [VERIFY: src/emc_assistant/ltspice/runner.py:187] | ✓ |
| `compose_testbench_cir` | user netlist `.include`d, never edited | [VERIFY: src/emc_assistant/testbench/composer.py:207] | ✓ |
| `run_agents` | budget trip → deterministic fill | [VERIFY: src/emc_assistant/agents/orchestrator.py:132] | ✓ |
| `rank_variants` | metric sort + baseline delta | [VERIFY: src/emc_assistant/results/ranking.py:53] | ✓ |

Next: **Phase 6** answers the "why/how" design questions these functions raise.
