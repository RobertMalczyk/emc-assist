import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
// Preview screen for "Engineer Training" (Tier 3, coming soon).

const PreviewTrainingScreen = () => (
  <div className="screen" data-screen="preview-training" data-state="coming-soon" data-feature-gate="engineer-training" data-screen-label="Preview · Engineer Training" id="screen-preview-training">
    <div className="screen-head">
      <div className="screen-title-block">
        <div className="eyebrow" style={{ color: "var(--accent)"}}>Roadmap preview · not in this build</div>
        <h1 style={{ display: "flex", alignItems: "center", gap: 12 }}>
          Engineer Training
          <span className="soon-pill">COMING SOON</span>
        </h1>
        <div className="lede">Per-net parasitic values are rule-of-thumb estimates. In the lab, engineers correct them. <i>Those corrections are training signal.</i> Over time, the tool's estimates improve from the accumulated lab outcomes of many engineers.</div>
      </div>
    </div>

    <div className="preview-hero">
      <span className="preview-watermark">MOCK · not live data</span>
      <div className="copy">
        <h2 style={{ margin: "0 0 12px", fontSize: 20 }}>The tool compounds in value the more it is used.</h2>
        <p style={{ color: "var(--text-dim)", fontSize: 14, lineHeight: 1.6, margin: "0 0 14px"}}>
          Every override you make on the <b>Parasitic selection</b> screen — and every LISN / filter
          correction at the bench — is recorded as an explicit <span className="mono" style={{ color: "var(--accent)"}}>estimate → corrected</span> edit.
          A model learns the mapping from <span className="mono">circuit / layout features</span> to
          <span className="mono"> realistic parasitic values</span> from that accumulated training data.
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <window.PreviewFeatureRow label="Your overrides become training signal — automatically, no extra step" />
          <window.PreviewFeatureRow label="Shared model improves with use; everyone benefits from everyone's lab" />
          <window.PreviewFeatureRow label="Strictly opt-in — per engineer or per organisation" />
          <window.PreviewFeatureRow label="Federated / on-device — raw netlists never leave your machine" />
        </div>
        <div style={{ marginTop: 18, display: "flex", gap: 8 }}>
          <button className="btn" disabled><Icon name="lock" size={14} /> Opt-in not yet available</button>
          <button className="btn ghost">Read privacy posture →</button>
        </div>
      </div>
      <div className="visual">
        <div className="mono faint" style={{ fontSize: "var(--t-xs)", marginBottom: 6, letterSpacing: "0.12em", textTransform: "uppercase" }}>How it would look</div>

        {/* Mock model-quality chart */}
        <div className="plot" style={{ height: 200, padding: 10 }}>
          <svg viewBox="0 0 360 180" style={{ width: "100%", height: "100%" }}>
            {/* grid */}
            {[0, 1, 2, 3, 4].map(i => (
              <line key={i} className="grid-line" x1={36} x2={350} y1={20 + i * 32} y2={20 + i * 32} stroke="var(--plot-grid)" />
            ))}
            {/* axes */}
            <line className="axis-line" x1={36} y1={20} x2={36} y2={148} stroke="var(--plot-axis)" />
            <line className="axis-line" x1={36} y1={148} x2={350} y2={148} stroke="var(--plot-axis)" />
            {/* labels */}
            <text x={193} y={172} textAnchor="middle" className="axis-label" fill="var(--text-muted)" style={{ fontFamily: "var(--font-mono)", fontSize: 10 }}>cumulative engineer corrections</text>
            <text x={6} y={84} textAnchor="middle" transform="rotate(-90 6 84)" className="axis-label" fill="var(--text-muted)" style={{ fontFamily: "var(--font-mono)", fontSize: 10 }}>est. error vs lab</text>
            {/* y ticks */}
            {["high","","mid","","low"].map((l, i) => (
              <text key={i} x={32} y={24 + i * 32} textAnchor="end" fill="var(--text-faint)" style={{ fontFamily: "var(--font-mono)", fontSize: 9 }}>{l}</text>
            ))}
            {/* learning curve — concave decreasing */}
            <path d="M 40 36 C 80 60, 130 100, 200 124 S 320 142, 350 144" stroke="var(--accent)" strokeWidth="1.6" fill="none" />
            {/* envelope */}
            <path d="M 40 26 C 80 50, 130 90, 200 116 S 320 134, 350 138 L 350 150 C 320 148, 200 132, 200 132 S 80 70, 40 46 Z" fill="var(--accent-soft)" opacity="0.4" />
            {/* points */}
            {[
              { x: 60, y: 60 }, { x: 110, y: 90 }, { x: 160, y: 112 }, { x: 220, y: 126 }, { x: 290, y: 138 },
            ].map((p, i) => (
              <circle key={i} cx={p.x} cy={p.y} r="3" fill="var(--accent)" />
            ))}
            {/* now marker */}
            <line x1={290} y1={20} x2={290} y2={148} stroke="var(--sev-med)" strokeDasharray="3 3" />
            <text x={290} y={16} textAnchor="middle" fill="var(--sev-med)" style={{ fontFamily: "var(--font-mono)", fontSize: 9 }}>future · with you</text>
          </svg>
        </div>

        {/* Mock contribution sample */}
        <div style={{ marginTop: 12, padding: 10, background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 4 }}>
          <div className="mono faint" style={{ fontSize: "var(--t-2xs)", letterSpacing: "0.14em", textTransform: "uppercase"}}>WHAT YOU WOULD CONTRIBUTE (mock · redacted)</div>
          <pre className="mono dim" style={{ margin: "8px 0 0", fontSize: 10, lineHeight: 1.5 }}>
{`{
  "net_role": "switch",
  "net_topology_hash": "0xa3f1…",
  "geometry_class": "4-layer · 1oz · trace 0.5mm",
  "estimated_C_pF":   [42, 56, 78],
  "corrected_C_pF":   62,
  "context_hash":     "0x1c47…"
}`}
          </pre>
          <div className="dim" style={{ marginTop: 6, fontFamily: "var(--font-mono)", fontSize: 10 }}>
            no schematic, no nets, no identifiers — only feature-class + estimated/corrected R/L/C.
          </div>
        </div>
      </div>
    </div>

    <div className="grid-2">
      <Card title="Privacy posture — load-bearing for this feature" sub="opt-in · federated · redacted-only">
        <ul style={{ paddingLeft: 18, margin: 0, color: "var(--text-dim)", fontSize: 13, lineHeight: 1.7}}>
          <li><b>Schematics never leave the machine.</b> Only feature-class to value pairs (geometry class, net role, estimated vs corrected R/L/C) — never net names, never identifying netlist fragments.</li>
          <li><b>Federated by default.</b> Model deltas are shared, not raw data.</li>
          <li><b>Strictly opt-in.</b> Per engineer or per organisation — never enabled silently.</li>
          <li><b>Reusable redaction discipline.</b> Same redaction pipeline the (optional) cloud LLM already uses.</li>
        </ul>
      </Card>

      <Card title="What's already in place today" sub="so this can slot in without a redesign">
        <ul style={{ paddingLeft: 18, margin: 0, color: "var(--text-dim)", fontSize: 13, lineHeight: 1.7}}>
          <li>Every parasitic override is captured as an explicit <span className="mono" style={{ color: "var(--accent)"}}>estimated → corrected</span> edit on the Parasitic selection screen — see the override log there.</li>
          <li>LISN-mode and filter-value edits will be captured the same way as the testbench compose pipeline gains those controls.</li>
          <li>The Settings → Privacy posture panel is where the opt-in will live.</li>
        </ul>
      </Card>
    </div>

    <div style={{ marginTop: 16 }}>
      <window.PreviewRoadmap k="Status" v={<Pill tone="warn" dot>planned · M6+ (after Live Lab Assistant)</Pill>} />
    </div>
  </div>
);

window.PreviewTrainingScreen = PreviewTrainingScreen;
