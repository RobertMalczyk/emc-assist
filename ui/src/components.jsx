import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
// Shared UI primitives.

// ----- Pill --------------------------------------------------------------
const Pill = ({ tone, dot, children, className = "", ...rest }) => (
  <span className={`pill ${tone || ""} ${className}`} {...rest}>
    {dot && <span className="dot" />}
    {children}
  </span>
);

// ----- Severity badge ----------------------------------------------------
const SeverityBadge = ({ level }) => {
  const cls = `sev-${level}`;
  const label = level.toUpperCase();
  return (
    <span className={`badge-sev ${cls}`}>
      <span className="bar" />
      {label}
    </span>
  );
};

// ----- Confidence dots ---------------------------------------------------
const ConfidenceDots = ({ value }) => {
  // 0..1 → 0..3 dots filled
  const filled = Math.min(3, Math.max(0, Math.round(value * 3)));
  return (
    <span className="conf-dots" data-tip={`confidence ${(value*100).toFixed(0)}%`}>
      {[0,1,2].map(i => (
        <span key={i} className={`d ${i < filled ? "on" : ""}`} />
      ))}
    </span>
  );
};

// ----- Toggle ------------------------------------------------------------
const Toggle = ({ on, onChange, label, dim, ...rest }) => (
  <button className={`toggle ${on ? "on" : ""} ${dim ? "dim" : ""}`} onClick={() => onChange && onChange(!on)} {...rest}>
    <span className="track"><span className="thumb" /></span>
    {label && <span className="lbl mono" style={{ fontSize: "var(--t-xs)", color: "var(--text-dim)"}}>{label}</span>}
  </button>
);

// ----- Segmented control -------------------------------------------------
const Segmented = ({ value, options, onChange }) => (
  <div className="seg" role="tablist">
    {options.map(o => (
      <button key={o.value} className={value === o.value ? "active" : ""} onClick={() => onChange(o.value)} role="tab">
        {o.label}
      </button>
    ))}
  </div>
);

// ----- Role chip --------------------------------------------------------
const ROLE_LABELS = {
  power: "POWER",
  return: "RETURN",
  switch: "SWITCH",
  signal: "SIGNAL",
  output: "OUTPUT",
};
const RoleChip = ({ role }) => (
  <span className={`role-chip role-${role}`}>
    <span className="sq" />{ROLE_LABELS[role] || role}
  </span>
);

// ----- Uncertainty visualisation (3 styles via tweak) -------------------
// values: [min, typ, max] in some unit; unit: string; style: "bar"|"ticks"|"num"
// scaleMin / scaleMax: normalize across the column for visual comparison.
const UncertaintyView = ({ values, unit, style = "bar", scaleMin, scaleMax }) => {
  if (!values) return <span className="dim">—</span>;
  const [min, typ, max] = values;
  const sMin = scaleMin ?? Math.min(min * 0.5, 0);
  const sMax = scaleMax ?? max * 1.4;
  const span = sMax - sMin || 1;
  const pct = v => `${((v - sMin) / span) * 100}%`;
  const fmt = v => (v < 10 ? v.toFixed(2) : v < 100 ? v.toFixed(1) : v.toFixed(0));
  if (style === "num") {
    const dev = Math.max(typ - min, max - typ);
    return (
      <span className="uncert uncert-num">
        <span className="typ tnum">{fmt(typ)}</span>
        <span className="pm">± {fmt(dev)}</span>
        {unit && <span className="units">{unit}</span>}
      </span>
    );
  }
  if (style === "ticks") {
    return (
      <span className="uncert uncert-ticks">
        <span className="axis">
          <span className="tick" style={{ left: pct(min) }} />
          <span className="tick typ" style={{ left: pct(typ) }} />
          <span className="tick" style={{ left: pct(max) }} />
        </span>
        <span className="label tnum">
          {fmt(min)}<span className="dim"> · </span><b>{fmt(typ)}</b><span className="dim"> · </span>{fmt(max)}
          {unit && <span className="units"> {unit}</span>}
        </span>
      </span>
    );
  }
  // bar (default)
  return (
    <span className="uncert uncert-bar">
      <span className="bar-wrap">
        <span className="envelope" style={{ left: pct(min), width: `calc(${pct(max)} - ${pct(min)})` }} />
        <span className="tick-typ" style={{ left: pct(typ) }} />
      </span>
      <span className="label tnum">
        <b>{fmt(typ)}</b>{" "}
        <span className="dim">[{fmt(min)}–{fmt(max)}]</span>
        {unit && <span className="units"> {unit}</span>}
      </span>
    </span>
  );
};

// ----- Disclaimer banner -------------------------------------------------
const PreComplianceDisclaimer = ({ inline = false }) => (
  <div className="disclaimer" style={inline ? { padding: "6px 10px"} : null}>
    <span className="icon"><Icon name="alert" /></span>
    <span>
      <b>Pre-compliance only.</b> Outputs are <i>engineering hypotheses requiring lab verification</i> — never a guarantee that a design will pass formal EMC.
    </span>
  </div>
);

// ----- Privacy indicator -------------------------------------------------
const PrivacyIndicator = ({ llmEnabled }) => (
  <div className={`privacy ${llmEnabled ? "warn" : ""}`}
       id="privacy-indicator"
       data-action="goto-settings-privacy"
       data-bind="privacy-state"
       data-cloud-llm={llmEnabled ? "on" : "off"}
       data-tip={llmEnabled ? "Cloud LLM enabled — redacted payloads only" : "Fully local — nothing about this circuit leaves the machine"}>
    <span className="lock"><Icon name={llmEnabled ? "unlock" : "lock"} size={14} /></span>
    <span><span className="k">local</span> · <span className="k">cloud LLM</span> <b data-bind="cloud-llm-enabled" style={{ color: llmEnabled ? "var(--sev-med)" : "var(--sev-low)"}}>{llmEnabled ? "ON" : "OFF"}</b></span>
  </div>
);

// ----- Theme & accent toggle (top bar) -----------------------------------
const ThemeToggle = ({ theme, onToggle }) => (
  <button className="icon-btn" onClick={onToggle} data-tip={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} aria-label="Toggle theme">
    <Icon name={theme === "dark" ? "sun" : "moon"} />
  </button>
);

// ----- Card --------------------------------------------------------------
const Card = ({ title, sub, right, children, flush = false, className = "", style }) => (
  <div className={`card ${className}`} style={style}>
    {(title || right) && (
      <div className="card-head">
        <div>
          {title && <h3>{title}</h3>}
          {sub && <div className="sub" style={{ marginTop: 2 }}>{sub}</div>}
        </div>
        {right && <div>{right}</div>}
      </div>
    )}
    <div className={`card-body ${flush ? "flush" : ""}`}>{children}</div>
  </div>
);

// ----- Stat block -------------------------------------------------------
const Stat = ({ label, value, delta, tone }) => (
  <div className="stat">
    <div className="label">{label}</div>
    <div className="value" style={tone ? { color: `var(--sev-${tone})`} : null}>{value}</div>
    {delta && <div className="delta">{delta}</div>}
  </div>
);

// ----- Stale chip -------------------------------------------------------
const StaleChip = ({ children = "STALE · NEEDS RE-RUN" }) => (
  <span className="stale-chip"><span className="pulse" />{children}</span>
);

// ----- Stale banner -----------------------------------------------------
// Honest-data invariant (QA flow RES3 / PP2): when an upstream input changed
// since the run that produced a screen's artifacts, the screen must say so
// rather than present stale numbers as current. Shared by Results / Findings
// / Report — each passes its own `bind` and the rerun callback.
const StaleBanner = ({ bind = "stale-banner", onRerun, children }) => (
  <div
    className="card"
    data-bind={bind}
    style={{
      padding: 12, marginBottom: 12,
      borderLeft: "3px solid var(--sev-med)",
      display: "flex", alignItems: "center", gap: 12,
    }}>
    <span style={{ color: "var(--sev-med)", flexShrink: 0 }}><Icon name="alert" /></span>
    <div style={{ flex: 1, fontSize: "var(--t-sm)", color: "var(--text-dim)" }}>
      {children || (
        <><b style={{ color: "var(--text)" }}>Out of date.</b> An input changed since this was generated — re-run the pipeline to refresh.</>
      )}
    </div>
    {onRerun && (
      <button className="btn btn-sm" data-action="rerun-pipeline" onClick={onRerun} style={{ flexShrink: 0 }}>
        Re-run pipeline →
      </button>
    )}
  </div>
);

// ----- Disclosure / Collapsible card ------------------------------------
const Disclosure = ({ title, summary, open: openProp, onToggle, children, right }) => {
  const [open, setOpen] = useState(openProp ?? false);
  useEffect(() => { if (openProp !== undefined) setOpen(openProp); }, [openProp]);
  const toggle = () => { setOpen(o => { onToggle && onToggle(!o); return !o; }); };
  return (
    <div className="card">
      <button className="card-head" onClick={toggle} style={{ width: "100%", cursor: "pointer" }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <Icon name={open ? "chevron-down" : "chevron-right"} />
          <div style={{ textAlign: "left" }}>
            <h3 style={{ margin: 0 }}>{title}</h3>
            {summary && <div className="sub" style={{ marginTop: 2 }}>{summary}</div>}
          </div>
        </div>
        {right}
      </button>
      {open && <div className="card-body fade-in">{children}</div>}
    </div>
  );
};

// ----- Field (form) ------------------------------------------------------
const Field = ({ label, hint, units, children }) => (
  <div className="field">
    <label>
      <span>{label}</span>
      {hint && <span className="hint">{hint}</span>}
    </label>
    <div style={{ display: "flex", alignItems: "stretch", gap: 0 }}>
      {children}
      {units && (
        <span style={{
          display: "inline-flex", alignItems: "center", padding: "0 10px",
          background: "var(--panel-2)", border: "1px solid var(--input-border)",
          borderLeft: "none", borderRadius: "0 var(--radius) var(--radius) 0",
          fontFamily: "var(--font-mono)", fontSize: "var(--t-xs)", color: "var(--text-muted)",
        }}>{units}</span>
      )}
    </div>
  </div>
);

// Expose
Object.assign(window, {
  Pill, SeverityBadge, ConfidenceDots, Toggle, Segmented,
  RoleChip, UncertaintyView,
  PreComplianceDisclaimer, PrivacyIndicator, ThemeToggle,
  Card, Stat, StaleChip, StaleBanner, Disclosure, Field,
});
