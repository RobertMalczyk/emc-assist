import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
// Sample-project data — a synchronous buck 12V → 3.3V @ 500 kHz.
// Used as the realistic data the screens render from.

const SAMPLE_BUCK = {
  id: "buck-12-3v3",
  name: "buck_sync_12v_3v3",
  file: "buck_sync_12v_3v3.asc",
  topology: "Synchronous buck",
  vin: 12.0,
  vout: 3.3,
  iload: 2.5,
  fsw: 500e3,
  cable_m: 1.5,
  lisn: "Dual (CM/DM separable)",
  pcb: {
    layers: 4,
    cu_oz: 1,
    stackup: "1oz / 8mil dielectric",
    trace_w_mm: 0.5,
    trace_l_mm: 25,
  },
  signals: ["Vout", "Vsw", "Iin"],
  // Per-net parasitic estimates (R/L/C bands, min/typ/max + confidence).
  nets: [
    { net: "VIN",   role: "power",  type: "series-RLC",
      R: [12, 18, 28],   // mΩ
      L: [6, 8.5, 12],   // nH
      C: [2.2, 3.1, 4.5],// pF (shunt-to-GND)
      confidence: 0.78, include: true, override: null,
      note: "Input rail trace into LISN — dominates DM coupling." },
    { net: "SW",    role: "switch", type: "shunt-C",
      R: null, L: null,
      C: [42, 56, 78],
      confidence: 0.62, include: true, override: null,
      note: "Switching node — CM injector. High dv/dt." },
    { net: "VOUT",  role: "output", type: "series-RLC",
      R: [8, 12, 18], L: [4, 6, 9], C: [3.0, 4.0, 6.5],
      confidence: 0.71, include: true, override: { C_typ: 5.5 },
      note: "Engineer override on shunt-C (typ)." },
    { net: "FB",    role: "signal", type: "shunt-C",
      R: null, L: null, C: [0.8, 1.2, 1.9],
      confidence: 0.84, include: false, override: null,
      note: "AI suggested drop: insignificant for conducted band." },
    { net: "BOOT",  role: "signal", type: "shunt-C",
      R: null, L: null, C: [1.2, 1.8, 2.6],
      confidence: 0.66, include: true, override: null,
      note: "" },
    { net: "EN",    role: "signal", type: "shunt-C",
      R: null, L: null, C: [0.5, 0.9, 1.4],
      confidence: 0.81, include: false, override: null,
      note: "AI suggested drop: DC-static, no switching content." },
    { net: "PGND",  role: "return", type: "series-RLC",
      R: [3, 5, 9], L: [2, 3, 5], C: [4, 6, 9],
      confidence: 0.69, include: true, override: null,
      note: "Return path under SW node — critical for CM." },
    { net: "AGND",  role: "return", type: "series-RLC",
      R: [4, 7, 12], L: [3, 4, 6], C: [2, 3, 5],
      confidence: 0.73, include: true, override: null,
      note: "" },
    { net: "VCC",   role: "power",  type: "shunt-C",
      R: null, L: null, C: [8, 12, 18],
      confidence: 0.74, include: true, override: null,
      note: "Driver supply decoupling." },
    { net: "LX",    role: "switch", type: "shunt-C",
      R: null, L: null, C: [22, 30, 44],
      confidence: 0.65, include: true, override: null,
      note: "Second switching node (synchronous low-side gate drive)." },
    { net: "ISNS",  role: "signal", type: "shunt-C",
      R: null, L: null, C: [1.0, 1.5, 2.4],
      confidence: 0.79, include: true, override: null,
      note: "" },
    { net: "VREF",  role: "signal", type: "shunt-C",
      R: null, L: null, C: [0.6, 1.0, 1.6],
      confidence: 0.86, include: false, override: null,
      note: "AI suggested drop: bandgap reference." },
  ],

  // Findings & recommendations (from the 12 specialist agents)
  findings: [
    {
      area: "Input filter",
      problem: "DM peak at 540 kHz exceeds CISPR Class B limit by 8 dB (typ).",
      evidence: "Sim spectrum 150 kHz – 1 MHz; corner sweep all three cases breach 2nd & 3rd harmonics.",
      proposal: "Add π-filter: 4.7 µH + 2× 4.7 µF X7R on VIN, before LISN tap.",
      bands: { L_uH: [3.3, 4.7, 6.8], C_uF: [3.3, 4.7, 6.8] },
      assumptions: "Input cable 1.5 m; LISN per CISPR 16-1-2.",
      limitations: "Does not consider radiated coupling at >30 MHz.",
      severity: "high", confidence: 0.82, status: "open",
      sources: ["TI SLUA803", "CISPR 16-1-2:2014", "Internal: buck_input_filter_design.md"],
    },
    {
      area: "CM choke / common-mode",
      problem: "CM peak at 540 kHz typ 6 dB over limit.",
      evidence: "CM trace separated via dual-LISN model; SW node dv/dt = 4.2 V/ns typ.",
      proposal: "Add common-mode choke ~1 mH on VIN+/RTN pair before LISN.",
      bands: { L_mH: [0.47, 1.0, 2.2] },
      assumptions: "Choke leakage inductance < 5 % of CM inductance.",
      limitations: "Choke saturation not modelled; verify Isat > Iin·1.5.",
      severity: "high", confidence: 0.74, status: "open",
      sources: ["Würth ANP-117", "CISPR 32:2015"],
    },
    {
      area: "Switching node",
      problem: "SW node dv/dt drives broadband CM injection through Cp_sw → chassis.",
      evidence: "Cp_sw typ 56 pF; conducted band slope consistent with capacitive coupling.",
      proposal: "Shield SW area with hatched ground pour; consider snubber 1 nF + 2.2 Ω.",
      bands: { R_ohm: [1.0, 2.2, 4.7], C_nF: [0.47, 1.0, 2.2] },
      assumptions: "PCB layer 2 = ground; SW under hatched pour.",
      limitations: "Snubber dissipation P ≈ ½·C·V²·fsw; verify thermal.",
      severity: "med", confidence: 0.68, status: "open",
      sources: ["TI SLVA255", "AN-1671"],
    },
    {
      area: "Output filter",
      problem: "Output ripple within spec; no action required.",
      evidence: "Vout ripple 18 mVpp typ; HF content < limit by 14 dB.",
      proposal: "No change.",
      bands: null,
      assumptions: "Load 2.5 A resistive; no downstream LDO.",
      limitations: "Result holds only for the simulated load step.",
      severity: "low", confidence: 0.88, status: "accepted",
      sources: ["Project: results/simulation_run.json"],
    },
    {
      area: "PCB layout",
      problem: "Return current under SW node loops 12 mm laterally (typ).",
      evidence: "Topology report: PGND segment length 22 mm; no continuous return under switch.",
      proposal: "Re-route PGND under SW with via-stitching; reduce loop area to < 4 mm².",
      bands: null,
      assumptions: "4-layer stack-up with adjacent ground.",
      limitations: "Estimated from net geometry; final loop area depends on actual placement.",
      severity: "med", confidence: 0.59, status: "open",
      sources: ["Henry Ott §11"],
    },
    {
      area: "Bulk capacitance",
      problem: "Bulk input cap ESR contributes ~3 dB at 540 kHz.",
      evidence: "Cap model: 22 µF Al-electrolytic, ESR ~70 mΩ typ.",
      proposal: "Add 1 × 10 µF X7R in parallel with bulk; or upgrade to polymer (ESR < 20 mΩ).",
      bands: { ESR_mohm: [5, 18, 40] },
      assumptions: "Polymer cap available in 1210/D-case.",
      limitations: "Polymer cost +0.30 USD/board.",
      severity: "low", confidence: 0.71, status: "rejected",
      reason: "Procurement: polymer not qualified for this product line.",
      sources: ["Panasonic SP-Cap appnote"],
    },
  ],
};

window.SAMPLE = SAMPLE_BUCK;

// Pipeline stages (Tier 2)
window.STAGES = [
  { id: "import",   label: "Import & context",    icon: "import" },
  { id: "parasitics", label: "Parasitic selection", icon: "nets" },
  { id: "testbench", label: "Testbench",          icon: "testbench" },
  { id: "run",       label: "Run",                icon: "play" },
  { id: "results",   label: "Results",            icon: "spectrum" },
  { id: "findings",  label: "Findings & recs",     icon: "list" },
  { id: "report",    label: "Report",             icon: "report" },
];

window.STAGE_ORDER = ["import","parasitics","testbench","run","results","findings","report"];

// Map stage to state given current "pipelineStage"
window.stageStateFor = (current, target) => {
  const ci = window.STAGE_ORDER.indexOf(current);
  const ti = window.STAGE_ORDER.indexOf(target);
  if (ti < ci) return "done";
  if (ti === ci) return "active";
  return "locked";
};

// Format helpers
window.fmt = {
  hz(v) {
    if (v >= 1e6) return (v/1e6).toFixed(v/1e6 < 10 ? 2 : 1) + " MHz";
    if (v >= 1e3) return (v/1e3).toFixed(v/1e3 < 10 ? 1 : 0) + " kHz";
    return v + " Hz";
  },
  pf(v) { return v == null ? "—" : v.toFixed(v < 10 ? 2 : 1); },
  nh(v) { return v == null ? "—" : v.toFixed(v < 10 ? 2 : 1); },
  mohm(v) { return v == null ? "—" : v.toFixed(v < 10 ? 2 : 1); },
  sec(v) {
    if (v == null || typeof v !== "number") return "—";
    const a = Math.abs(v);
    if (a === 0) return "0 s";
    if (a >= 1) return v.toFixed(a < 10 ? 2 : 1) + " s";
    if (a >= 1e-3) return (v * 1e3).toFixed(a < 1e-2 ? 2 : 1) + " ms";
    if (a >= 1e-6) return (v * 1e6).toFixed(a < 1e-5 ? 2 : 1) + " µs";
    return (v * 1e9).toFixed(a < 1e-8 ? 2 : 1) + " ns";
  },
};
