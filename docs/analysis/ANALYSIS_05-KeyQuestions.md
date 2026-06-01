# ANALYSIS 05 — Key Questions (EMC/LTspice Assistant)

> `codebase-analysis` skill, Phase 6. "Why / how" design questions and common
> pitfalls, each answered from code with an inline `VERIFY` tag (`path:line`).

## Table of contents
- [Design "why" questions](#design-why-questions)
- [Operational "how" questions](#operational-how-questions)
- [Common pitfalls](#common-pitfalls)
- [Configuration guidance](#configuration-guidance)
- [Verification report](#verification-report)

---

## Design "why" questions

**Q: Why is the deterministic core run before (and independently of) the LLM?**
The LLM is opt-in and only constructed when enabled *and* a key resolves
[VERIFY: src/emc_assistant/service/resolve.py:148]; when it is off, every agent
falls back to a rule-based finding
[VERIFY: src/emc_assistant/agents/base.py:510]. So the pipeline always produces
output without a key — the LLM is an assistant layered on top, never a
dependency.

**Q: Why min/typ/max bands and a corner sweep instead of one "best" value?**
Parasitics are uncertain without layout, so each net carries a banded estimate
[VERIFY: src/emc_assistant/parasitics/per_net.py:79] and the sweep moves one
parasitic to each corner while holding the rest at typ
[VERIFY: src/emc_assistant/testbench/variants.py:36] — an honest spread and a
per-parasitic sensitivity, not false precision.

**Q: Why is the user's schematic never modified?**
The composer brings the user netlist in via `.include` (read-only)
[VERIFY: src/emc_assistant/testbench/composer.py:207]; parasitic splices are
written into a *generated* fragment
[VERIFY: src/emc_assistant/service/resolve.py:715]. The original file is never
touched — a top-level product principle.

**Q: Why is the detector called "diagnostic-grade" rather than a real receiver?**
`CisprBand` carries the CISPR 16-1-1 detector parameters, but the QP stage is a
meter-time-constant model (charge/discharge + max-hold), explicitly not a
calibrated receiver  [VERIFY: src/emc_assistant/results/detectors.py:108]; by
default no receiver-bandwidth filter is applied. It is a relative
pre-compliance diagnostic.

**Q: Why are only some nets "injectable"?**
A series splice is unambiguous only on a clean 2-element point-to-point net; the
rule is `is_two_element and not is_ground`
([VERIFY: src/emc_assistant/netlist/topology.py:68],
[VERIFY: src/emc_assistant/parasitics/per_net.py:169]). Star/bus and ground nets
are estimated but not spliced (the splice point would be layout-dependent).

---

## Operational "how" questions

**Q: How do I enable the LLM layer?**
Set the `llm` option (CLI `--llm openai`); it maps onto `CommandOptions.llm`
[VERIFY: src/emc_assistant/service/options.py:37], is gated by `llm_enabled`
[VERIFY: src/emc_assistant/service/resolve.py:148], and the assistant is built
by `make_assistant`  [VERIFY: src/emc_assistant/service/resolve.py:118]. Without
a resolved key it stays deterministic.

**Q: How does the pipeline survive with no LTspice installed?**
`run_simulation` returns a clean `failed`/`dry_run` result instead of throwing
([VERIFY: src/emc_assistant/ltspice/runner.py:155],
[VERIFY: src/emc_assistant/ltspice/runner.py:163]) and `run_pipeline` continues
to the report on a partial variants run
[VERIFY: src/emc_assistant/service/pipeline.py:171].

**Q: How is the LLM budget enforced across 11 agents?**
A single budget is threaded across the whole agent fan-out; if it trips
mid-run, the remaining agents fall back to deterministic findings so all 11 are
still produced  [VERIFY: src/emc_assistant/agents/orchestrator.py:132].

---

## Common pitfalls

**Pitfall — detector-margin disagreement (FIXED 2026-05-24).** The verdict
margin and the spectrum chart were once two independent paths (Mode 1/skip 0.1
vs Mode 3/skip 0.0) that contradicted each other by ~40 dB. They now share one
canonical detector  [VERIFY: src/emc_assistant/results/detectors.py:751], so the
verdict, corner table, chart and report plot agree by construction (still scored
against the same `worst_margin`
[VERIFY: src/emc_assistant/results/limits.py:118]). *Residual caveat:* the
canonical Mode-3 sweep under-reads narrow harmonics that fall between its swept
points — see `tasks/detector_selectable.md`.

**Pitfall — the demo single testbench run times out.** The full single run can
exceed LTspice's timeout, yielding a `timeout` status
[VERIFY: src/emc_assistant/ltspice/runner.py:187]; the smaller corner variants
complete and back the Results view. That is expected, not a crash.

**Pitfall — a variant missing the chosen metric vanishes from the ranking.**
`rank_variants` silently skips entries without `metric_key`
[VERIFY: src/emc_assistant/results/ranking.py:39] — an empty ranking usually
means the metric name is wrong, not that all variants failed.

---

## Configuration guidance

- **Rank metric / direction:** `rank_metric` + `lower_is_better` on the options
  object choose what "worst" means
  ([VERIFY: src/emc_assistant/service/options.py:32],
  [VERIFY: src/emc_assistant/service/options.py:33]); `rank_variants` honours
  `lower_is_better` in its sort
  [VERIFY: src/emc_assistant/results/ranking.py:53].
- **LISN mode:** dual vs single changes the wiring the composer emits
  [VERIFY: src/emc_assistant/testbench/composer.py:227]; dual is the CISPR-style
  default and renames the return to `DUT_GND`.
- **Report formats:** `html` / `pdf` options gate the extra renders
  [VERIFY: src/emc_assistant/service/options.py:34].

---

## Verification report

| Q/Pitfall | Evidence | Status |
|---|---|---|
| LLM gating + deterministic fallback | [VERIFY: src/emc_assistant/service/resolve.py:148] | ✓ |
| user `.cir` is `.include`d read-only | [VERIFY: src/emc_assistant/testbench/composer.py:207] | ✓ |
| injectability rule | [VERIFY: src/emc_assistant/parasitics/per_net.py:169] | ✓ |
| no-LTspice continues to report | [VERIFY: src/emc_assistant/service/pipeline.py:171] | ✓ |
| budget trip → deterministic fill | [VERIFY: src/emc_assistant/agents/orchestrator.py:132] | ✓ |
| timeout status path | [VERIFY: src/emc_assistant/ltspice/runner.py:187] | ✓ |
| ranking skips missing-metric variants | [VERIFY: src/emc_assistant/results/ranking.py:39] | ✓ |

Next: **Phase 7** records the cross-document verification result.
