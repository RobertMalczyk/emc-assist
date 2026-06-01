import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
// Preview screen for "Live Lab Assistant" (Tier 3, coming soon).
// Read-only mockup that explains the capability.

const PreviewLabScreen = () => (
  <div className="screen" data-screen="preview-lab" data-state="coming-soon" data-feature-gate="live-lab-assistant" data-screen-label="Preview · Live Lab Assistant" id="screen-preview-lab">
    <div className="screen-head">
      <div className="screen-title-block">
        <div className="eyebrow" style={{ color: "var(--accent)"}}>Roadmap preview · not in this build</div>
        <h1 style={{ display: "flex", alignItems: "center", gap: 12 }}>
          Live Lab Assistant
          <span className="soon-pill">COMING SOON</span>
        </h1>
        <div className="lede">Today the tool is an offline pre-compliance pass. The planned <i>Live Lab Assistant</i> runs alongside the engineer at the conducted-emissions bench, correlating measured spectra against the simulated prediction in real time.</div>
      </div>
    </div>

    <div className="preview-hero">
      <span className="preview-watermark">MOCK · not live data</span>
      <div className="copy">
        <h2 style={{ margin: "0 0 12px", fontSize: 20 }}>Simulation and the lab, finally on one screen.</h2>
        <p style={{ color: "var(--text-dim)", fontSize: 14, lineHeight: 1.6, margin: "0 0 14px"}}>
          A connected EMI receiver streams its measured spectrum into the tool. The simulated prediction
          (this project's last <span className="mono">simulate run</span>) is overlaid; where the two traces diverge,
          the assistant points to the <span className="mono">parasitic / LISN / filter hypothesis</span> most
          likely to explain the gap — surfaced from the same specialist-agent panel that produced the offline findings.
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <FeatureRow label="Live receiver overlay (CISPR-16 conforming)" />
          <FeatureRow label="Real-time peak attribution to specific parasitic" />
          <FeatureRow label="What-if: apply candidate fix → predict new spectrum" />
          <FeatureRow label="Session capture for post-test report (linked to project)" />
        </div>
        <div style={{ marginTop: 18, display: "flex", gap: 8 }}>
          <button className="btn" disabled><Icon name="lock" size={14} /> Requires a connected measurement source</button>
        </div>
      </div>
      <div className="visual">
        <div className="mono faint" style={{ fontSize: "var(--t-xs)", marginBottom: 6, letterSpacing: "0.12em", textTransform: "uppercase" }}>How it would look</div>
        <SpectrumPlot showSim={true} showMeasured={true} showLimit={true} height={280} caption="MOCK · representative spectra" />
        <div style={{ marginTop: 10 }}>
          <SpectrumLegend showSim={true} showMeasured={true} showLimit={true} />
        </div>
        <div style={{ marginTop: 12, padding: 10, background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 4 }}>
          <div className="mono faint" style={{ fontSize: "var(--t-2xs)", letterSpacing: "0.14em", textTransform: "uppercase"}}>LIVE ATTRIBUTION (mock)</div>
          <div style={{ marginTop: 6, fontSize: 13, color: "var(--text-dim)"}}>
            Measured peak at <span className="mono" style={{ color: "var(--accent)"}}>1.62 MHz · 58 dBµV</span> is
            <b style={{ color: "var(--text)"}}> 9 dB above</b> simulation. Most likely cause:
            <b style={{ color: "var(--text)"}}> CM coupling through Cp_SW</b> (estimate underweighted).
            <span style={{ display: "block", marginTop: 4, color: "var(--text-muted)"}}>→ confirm by tapping a 2nd ferrite on VIN/RTN; expect 4–7 dB drop.</span>
          </div>
        </div>
      </div>
    </div>

    <div className="grid-2">
      <Card title="Status" sub="roadmap">
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <Roadmap k="Status" v={<Pill tone="warn" dot>planned · M5</Pill>} />
          <Roadmap k="Depends on" v={<span className="mono">spectrum-plot overlay (✓ already designed)</span>} />
          <Roadmap k="Hardware" v="EMI receiver via VISA / SCPI · pasted CSV as fallback" />
          <Roadmap k="Cost" v="no cloud LLM required — all correlation runs locally" />
          <Roadmap k="Privacy" v="receiver data stays on the machine; same posture as today" />
        </div>
      </Card>

      <Card title="What's already in place today" sub="so this can slot in without a redesign">
        <ul style={{ paddingLeft: 18, margin: 0, color: "var(--text-dim)", fontSize: 13, lineHeight: 1.7}}>
          <li>The <b>Results spectrum plot</b> already supports a second trace — toggle <span className="mono">MEAS</span> on the Results screen to see the slot.</li>
          <li>The <b>Findings</b> panel already speaks in hypothesis language with parameter bands — exactly what live attribution will surface.</li>
          <li>The pipeline stores per-variant <span className="mono">.raw</span> files; the lab assistant will read those as the prediction baseline.</li>
        </ul>
      </Card>
    </div>
  </div>
);

const FeatureRow = ({ label }) => (
  <div style={{ display: "flex", gap: 10, alignItems: "center"}}>
    <span style={{ color: "var(--accent)"}}><Icon name="check" size={14} /></span>
    <span className="mono" style={{ fontSize: "var(--t-sm)", color: "var(--text-dim)"}}>{label}</span>
  </div>
);

const Roadmap = ({ k, v }) => (
  <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: 12, alignItems: "center", padding: "4px 0", borderBottom: "1px solid var(--hairline)"}}>
    <span className="mono faint" style={{ fontSize: "var(--t-xs)", letterSpacing: "0.06em"}}>{k}</span>
    <div className="mono" style={{ fontSize: "var(--t-sm)", color: "var(--text-dim)"}}>{v}</div>
  </div>
);

window.PreviewLabScreen = PreviewLabScreen;
window.PreviewRoadmap = Roadmap;
window.PreviewFeatureRow = FeatureRow;
