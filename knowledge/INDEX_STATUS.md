# Knowledge index — content status

**Last regenerated:** 2026-05-16
**Embedder:** `sentence-transformers/all-MiniLM-L6-v2` (384-dim)
**Total chunks:** 4623 (176 seed + 4447 raw_sources)

This file is the human-readable manifest of what is **in** vs **not in** the local vector index. The numbers are produced by walking `knowledge/processed/chunks.jsonl` and cross-referencing the two source manifest files. Regenerate this file after any `emc-assistant knowledge index` rerun that changes the corpus — see [How to refresh](#how-to-refresh) below.

---

## Summary

| Tier | Files indexed | Chunks |
|---|---:|---:|
| `knowledge/seed/` | 4 (2 jsonl rules + 2 md index docs) | 176 |
| `knowledge/raw_sources/` | 88 (44 PDF + 44 HTML) | 4447 |
| `knowledge/user_private_sources/` | 0 | 0 |
| `knowledge/licensed_sources/` | 0 | 0 |
| **Total** | **92** | **4623** |

### Parasitics-agent feed (2026-05-16)

Added `S031` — Malczyk et al., *Estimation of SMPS' Conducted Emission According to CISPR Standards* (Appl. Sci. 2022, 12, 1458, open-access). PDF in `raw_sources/parasitics/`. Distilled into **6 curated parasitics rules R091–R096** in `baza_pasozyty_pcb_rules.jsonl` (transformer leakage / magnetizing inductance, cable-harness S-parameter model, di/dt-loop extraction scope, extraction frequency range, quasi-static vs full-wave solver choice). Rules + PDF chunks both retrievable; R091 is the top hit for "transformer leakage inductance conducted emission".

## Source-manifest coverage

| Status | Count |
|---|---:|
| Catalogued in seed manifests | 105 |
| Downloaded + indexed (URL-fetched) | 82 |
| Manually-dropped + indexed (user-supplied) | 5 |
| Direct `.pdf` URL but download still failed | 14 (ADI anti-bot + Infineon SSL + STMicro) |
| Dead URL (source moved) | 1 (SRC-058 Murata LTspice library) |

## 2026-05-16 batch — browser-fetcher + HTML ingestion

`scripts/fetch_seed_pdfs.py` was rewritten as a content-adaptive browser-like fetcher (full Chrome headers, gzip/deflate decode, retry, `--insecure`, `--html` mode). Running `--html` pulled the 63 catalogued non-PDF sources: **44 saved as `.html`** + **16 TI `lit/pdf/<id>` URLs auto-detected as PDFs and saved as `.pdf`** + 1 dead link. Index grew **2472 → 4489 chunks**.

Still outstanding (browser-fetch manually into `knowledge/raw_sources/`): the 14 ADI / Infineon / STMicro PDFs below.

---

## In the DB (downloaded + indexed)

27 PDFs covering the high-value Würth / Texas Instruments / IEEE catalog. All Würth ANP application notes, the TI "Low EMI in DC/DC" e-book, the LVDS / Ethernet / motor-driver TI guides, **plus 5 user-supplied DC/DC conducted-EMI PDFs (SRC-071..SRC-075)** dropped directly into `knowledge/raw_sources/conducted_emissions/dcdc/` for the M2.9 filter agent.

### Würth Elektronik (11 PDFs)
| Source_ID | Title |
|---|---|
| S003 / SRC-026 | EMC Design Tips 2025 |
| S012 | EMI/EMC — Inductors and Filters |
| S029 | Design for EMC 2026 |
| SRC-020 | Practical EMC Design Considerations |
| SRC-021 | Efficient EMI Filtering of CM/DM Noise |
| SRC-022 | Calculation, Design and LTspice Simulation of AC Line Filters |
| SRC-023 | DC/DC Boost Converter EMI Seminar |
| SRC-024 | ANP044: Impact of Layout, Components and Filters on EMC of DC/DC |
| SRC-025 | ANP098: Effect of Layout, Vias and Design on Blocking Capacitor Performance |
| SRC-027 | ANP074: Introduction to RF Inductors |
| SRC-028 | ANP146: WE-CMDC Common Mode Chokes |
| SRC-029 | How do I solve EMI on PCB level? |

### Texas Instruments (9 PDFs)
| Source_ID | Title |
|---|---|
| S007 | Section 5 — High Speed PCB Layout Techniques |
| S008 | Decoupling Capacitors |
| S022 | PCB Layout Guidelines to Optimize Power Supply Performance |
| SRC-031 | An Engineer's Guide to Low EMI in DC/DC Regulators (e-book) |
| SRC-032 | Fundamentals of EMI Requirements for an Isolated DC/DC Converter |
| SRC-037 | AM335x/AM43xx USB Layout Guidelines |
| SRC-041 | Optimizing EMC Performance in Industrial Ethernet |
| SRC-043 | Best Practices for Board Layout of Motor Drivers |
| SRC-046 / SRC-047 | LVDS Application Handbook + Owner's Manual |

### IEEE.li (1 PDF)
| Source_ID | Title |
|---|---|
| S012 | EMI/EMC — EMC Inductors and Filters (mirror) |

### DC/DC conducted-EMI bundle — user-supplied (5 PDFs, 215 chunks)

Dropped directly into `knowledge/raw_sources/conducted_emissions/dcdc/` (browser-fetched, no automated URL). Catalogued in `knowledge/seed/baza_wiedzy_emc_ltspice_sources.jsonl` via `scripts/append_dcdc_sources.py`. Indexed 2026-05-14.

| Source_ID | Org | Title | Chunks |
|---|---|---|---:|
| SRC-071 | Texas Instruments | AN-2162: Simple Success With Conducted EMI From DC-DC Converters | 52 |
| SRC-072 | Texas Instruments | SNVA886: Reduce Conducted EMI in Automotive Buck Converter Applications | 53 |
| SRC-073 | Würth Elektronik | ANS018: EMI Filter Design for Non-Isolated DC/DC Converter | 30 |
| SRC-074 | Texas Instruments | SLUA929: Simple Solution for Input Filter Stability Issue in DC/DC Converters | 41 |
| SRC-075 | Texas Instruments | SNVA801: Analysis and Design of Input Filter for DC-DC Circuit | 39 |

Semantic-search sanity check (2026-05-14): query *"input filter damping stability DC/DC converter"* → top-4 hits all SRC-074 SLUA929 chunks, cosine 0.66–0.74. RAG retrieval over the new bundle is healthy.

---

## NOT in the DB — but referenced in seed manifests

### Direct PDF URL, download failed (15 files)

These have a `.pdf` URL in the manifest but the automated fetch failed. Each is worth fetching manually if relevant to your case.

| Source_ID | Org | Title | Failure reason |
|---|---|---|---|
| S013 / SRC-010 | Analog Devices | MT-101: Decoupling Techniques | `RemoteDisconnected` (anti-bot?) |
| S030 | Analog Devices | AN-202: An IC Amplifier User's Guide to Decoupling | timeout |
| SRC-011 | Analog Devices | Basic Linear Design, Ch. 12: PCB Design Issues | timeout |
| SRC-012 | Analog Devices | Practical Power Solutions, §4: Hardware Design Techniques | timeout |
| SRC-016 | Analog Devices | Public GMSL2 Hardware Design and Validation Guide | `RemoteDisconnected` |
| SRC-017 | Analog Devices | Public GMSL3 Hardware Design and Validation Guide | `RemoteDisconnected` |
| SRC-048 | Infineon | EMC and System-ESD Design Guidelines for Board Layout | SSL: self-signed cert in chain |
| SRC-049 | Infineon | Basic Design Consideration and Layout Recommendations for EMC Robustness | SSL |
| SRC-050 | Infineon | AC-DC Universal Input 45 W Power Supply Using CoolSET | SSL |
| SRC-051 | Infineon | Optimizing CoolMOS CE Based Power Supplies to Meet EMI | SSL |
| SRC-052 | Infineon | EZ-USB FX2G3 Hardware Design Guidelines | SSL |
| SRC-053 | Infineon | EZ-PD PMG1 MCU Hardware Design Guidelines | SSL |
| SRC-056 | STMicroelectronics | AN5240 Layout Recommendations for ST25R Devices | timeout |

**Likely causes:**
- **Analog Devices / STMicro:** anti-bot / rate-limit on programmatic requests. Browser-fetch and drop the PDF into `knowledge/raw_sources/<SOURCE_ID>__<slug>.pdf`.
- **Infineon:** SSL chain interception. Almost certainly a corporate proxy (Zscaler-style) on this machine intercepting TLS. Either install the proxy's root cert into Python's trust store, or download in a browser and drop the PDFs manually.

### Non-PDF URL (63 entries)

These point at HTML articles, online calculators, vendor library pages, or component-tool websites. They are catalogued for citation purposes but not indexed because the chunker doesn't follow links and `.html` pages need fetching first.

Examples (full list at the end of this doc):

- **TI / ADI articles in HTML** — most of the SRC-001 through SRC-045 series points at article pages, not PDFs.
- **Vendor SPICE libraries** — `SRC-018` (Würth LTspice), `SRC-057` (Murata ferrites), `SRC-058`, `SRC-059`, `SRC-060`: download pages, not docs.
- **Calculators / tools** — `S004` Saturn PCB toolkit, `S005`–`S006`–`S024`–`S025`–`S026`–`S027` Chemandy/Sierra/DigiKey/Clemson calculators.
- **Manufacturing pages** — `SRC-061`–`SRC-070` Eurocircuits, JLCPCB, Sierra Circuits DFM guidelines.

To bring any of these in: download the HTML page (browser → save as HTML), drop it in `knowledge/raw_sources/<SOURCE_ID>__<slug>.html`. The chunker handles `.html` (strips tags) and indexes it.

---

## How to refresh

After dropping new files in `knowledge/raw_sources/`:

```powershell
emc-assistant knowledge index
```

This walks the whole tree, embeds new content, writes `knowledge/processed/{chunks.jsonl,embeddings.npy,index_meta.json}`. Idempotent — re-running with the same corpus produces the same index (modulo timestamp).

To bulk-fetch the catalogued PDFs:

```powershell
python scripts/fetch_seed_pdfs.py
```

Idempotent (skips files already on disk). Outputs go to `knowledge/raw_sources/` and are gitignored. Adjust failure handling per the table above.

To regenerate this status doc:

```powershell
# (One-shot helper, not yet wired into the CLI — re-run the inventory
# script from the commit that produced this file. M2.8.x could add
# `emc-assistant knowledge status` if useful.)
```

---

## Privacy / license reminder

Even with these 22 PDFs indexed locally, **outbound LLM payloads carry only `rule_id` + `source_id` + our own short summary** (per the `feedback_copyright_redaction_for_llm` rule). A ≤200-char verbatim excerpt is included only when the source's `allowed_use` is `internal_reference` (no seed sources are currently flagged that way). The full PDF body text is used for local retrieval scoring only — it never leaves the machine.

The privacy log at `results/llm/<run-id>.jsonl` after every `--llm openai` run is the auditable evidence of what was actually sent.

---

## Full non-PDF source list (for reference)

S001 (TI), S002 (ADI), S004 (Saturn), S005-S006 (Chemandy/Sierra), S009 (ADI AN-136), S010 (Belden), S011 (TI), S014 (TI), S015-S016 (Murata), S017 (R&S), S018-S019 (TI), S020 (Coilcraft), S021 (ADI), S023 (TI LMG5200), S024 (Clemson), S025-S026 (Chemandy), S027 (DigiKey), S028 (Altium), SRC-001 through SRC-009 (ADI articles), SRC-013 (ADI cable), SRC-014-SRC-015 (ADI mixed-sig/RF), SRC-018-SRC-019 (Würth libraries / tools), SRC-030 (TI EMI intro), SRC-033-SRC-036 (TI PCB / high-speed guides), SRC-038-SRC-040 (TI RS-485 / CAN / SPE), SRC-042 (TI radiated Ethernet), SRC-044-SRC-045 (TI SIMPLE SWITCHER / TPSM33620), SRC-054-SRC-055 (Infineon stack-up), SRC-057-SRC-060 (vendor SPICE libs), SRC-061-SRC-070 (Eurocircuits / JLCPCB / Sierra DFM).
