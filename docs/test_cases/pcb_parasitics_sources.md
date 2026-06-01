# PCB parasitics source set (S032–S036)

## Purpose

A focused set of public reference PDFs about **PCB trace / via / polygon
parasitics** — rule-of-thumb values and first-order calculation guidance
for LTspice / EMC modelling. It exists to give the parasitics agent a
better-grounded basis for **min / typ / max** parasitic estimates and
**sweep** suggestions on conducted-EMI DC/DC analysis, without inventing
values and without copying copyrighted text.

This set complements the existing seed rules (`baza_pasozyty_pcb_rules.jsonl`)
— it does not replace them.

## Folder structure

PDFs are dropped locally under `knowledge/raw_sources/pcb_parasitics/`:

```text
knowledge/raw_sources/pcb_parasitics/
  traces/        # trace-inductance rule-of-thumb sources
  layout/        # layout / loop-area / via parasitic sources
  calculation/   # calculation-oriented, closed-form inductance sources
```

These directories are **gitignored** (like all `raw_sources/` content) —
the per-user source corpus is not committed. Create them locally and
drop the PDFs in.

## Expected filenames

Use the project naming convention `<SOURCE_ID>__<short_slug>.<ext>` so the
M2.8 chunker links each chunk back to its manifest entry (it splits the
stem on `__` to recover the `Source_ID`). A descriptive name without the
`S0xx__` prefix would index under the wrong source id.

| Source_ID | Expected local path |
|-----------|---------------------|
| S032 | `traces/S032__analog_devices_pcb_design_issues_chapter12.pdf` |
| S033 | `traces/S033__analog_devices_an353_pcb_track_inductance.pdf` |
| S034 | `traces/S034__wurth_pcb_board_layout_optimization.pdf` |
| S035 | `layout/S035__allegro_minimizing_pcb_parasitic_effects.pdf` |
| S036 | `calculation/S036__hubing_quantifying_pcb_inductance.pdf` |

| Source_ID | Title | Vendor / author |
|-----------|-------|-----------------|
| S032 | PCB Design Issues — Hardware Design Techniques, Ch. 12 | Analog Devices |
| S033 | AN-353: Ask the Applications Engineer 10 (PC track inductance) | Analog Devices |
| S034 | PCB Board Layout Optimization | Würth Elektronik |
| S035 | Minimizing PCB Parasitic Effects with Optimum Layout | Allegro MicroSystems |
| S036 | Identifying and Quantifying Printed Circuit Board Inductance | Clemson (T. Hubing et al.) |

> **Note on Source_IDs.** The task brief suggested `PCB-SRC-031…035`. The
> existing manifest `knowledge/seed/baza_pasozyty_pcb_sources.jsonl` uses a
> single `S0xx` sequence (last entry `S031`), so these sources were added
> as `S032`–`S036` to keep the manifest single-schema and consistent with
> the loader. The proposed-rule IDs keep the descriptive `PCB_*` prefix
> because the staging file is a separate, not-yet-merged artifact.

## Suggested tags

- **S032** — `pcb_parasitics, trace_inductance, rule_of_thumb, decoupling`
- **S033** — `pcb_parasitics, trace_inductance, pc_track, rule_of_thumb`
- **S034** — `pcb_parasitics, trace_inductance, dcdc, emi, didt, loop_inductance`
- **S035** — `pcb_parasitics, trace_inductance, via_inductance, loop_area, parasitic_capacitance, layout`
- **S036** — `pcb_parasitics, trace_inductance, calculation, closed_form, pcb_geometry, inductance`

## Extraction notes

- PDF extraction is **best-effort** and gated behind the optional `[pdf]`
  extra (`pip install 'emc-assistant[pdf]'`, pdfminer.six). Without it the
  indexer prints a friendly skip message — it does not crash.
- Scanned / image-only PDFs extract little or no text; the indexer emits a
  warning and produces zero chunks for that file rather than failing.
- The chunker recovers `Source_ID` from the `<SOURCE_ID>__…` filename — keep
  the prefix.
- Only **short summaries and ≤200-character snippets** are ever produced
  from these documents; full body text is never copied into rules or
  reports, and never leaves the machine when an LLM is involved
  (redaction layer).

## Copyright / use guardrails

- `access_class = public_reference`, `allowed_use =
  local_index_summary_and_short_snippets`, `license_warning =
  do_not_redistribute_full_text` (recorded in each manifest entry's
  `Notes` / `Use_caution`).
- Public availability ≠ redistribution rights. Files are read locally only.
- No paid CISPR / IEC / IPC standards in this set.
- No large copyrighted passages in generated rules or reports — summaries
  with a `Source_ID` and short snippets only.
- A single example value from a source is converted into a **bounded
  engineering rule** with explicit limitations, never a fixed "certain"
  PCB value.

## How these sources support min/typ/max estimates and sweeps

The parasitics agent (M2.10.4 per-net estimation) assigns every net a
rule-of-thumb R/L/C band. This source set backs those bands:

- **Trace inductance** (S032, S033) — anchors the high-single-digit
  nH/cm rule-of-thumb when no return-plane geometry is available.
- **di/dt sensitivity** (S034) — `V = L · di/dt` justifies why a
  parasitic-L sweep on switching nets matters for conducted EMI.
- **Via inductance** (S035) — anchors the ≈1 nH/via first-order rule and
  the parallel-via mitigation.
- **Loop area** (S034, S035, S036) — explains loop inductance / coupling
  and the layout-uncertainty warnings.
- **Closed-form inductance** (S036) — supports calculation-oriented rules
  and future calculator validation.

Every estimate stays a **min/typ/max band**, fed into LTspice `.step`
sweeps — never a single value presented as certain. See the proposed
rules in `knowledge/seed/staging_pcb_parasitic_trace_rules.jsonl`.

## Status

- Manifest entries S032–S036: **added** to
  `knowledge/seed/baza_pasozyty_pcb_sources.jsonl`.
- Proposed rules: **staged** in
  `knowledge/seed/staging_pcb_parasitic_trace_rules.jsonl` — review
  artifact, not auto-indexed, not merged into `baza_pasozyty_pcb_rules.jsonl`.
- PDFs: **not yet present** — drop them at the paths above to enable
  semantic retrieval over their bodies.
