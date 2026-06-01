import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
// Screen: Findings & recommendations — wired to api.list_recommendations
// (the specialist agents' recommendations from results/findings/*.json) with
// Accept/Reject persisting to the decision log (accept/reject_recommendation).

const _SEV = { critical: "high", high: "high", medium: "med", med: "med", low: "low", info: "low" };

function _adaptRec(r) {
  const status = r.status === "accepted" ? "accepted" : r.status === "rejected" ? "rejected" : "open";
  return {
    key: `${r.area}/${r.rec_id}`,
    area: r.area || "—",
    severity: _SEV[String(r.severity || "").toLowerCase()] || "med",
    status,
    problem: r.problem || "(no problem statement)",
    confidence: typeof r.confidence === "number" ? r.confidence : 0,
    evidence: Array.isArray(r.evidence) ? r.evidence.join("  ·  ") : "",
    proposal: r.proposal || r.user_action || "",
    limitations: Array.isArray(r.limitations) ? r.limitations.join("  ·  ") : "",
    sources: [...(r.sources || []), ...(r.citations || [])],
    reason: r.reason || "",
  };
}

const FindingsScreen = ({ onAdvance, currentProject, onChanged, stale, onRerun }) => {
  const api = useApi();
  const projectRoot = currentProject?.path || "";
  const inPywebview = typeof window !== "undefined" && !!window.isPywebview?.();

  const [recs, setRecs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [filter, setFilter] = useState("open");
  const [expanded, setExpanded] = useState("");

  const reload = useCallback(async () => {
    if (!projectRoot) { setRecs([]); setLoading(false); return; }
    setLoading(true); setLoadError("");
    const res = await api.list_recommendations(projectRoot);
    if (!res.ok) { setLoadError(res.error?.message || "could not load recommendations"); setRecs([]); setLoading(false); return; }
    const rows = (res.data?.rows || []).map(_adaptRec);
    setRecs(rows);
    setLoading(false);
  }, [projectRoot, api]);

  useEffect(() => { reload(); }, [reload]);

  const decide = useCallback(async (key, status) => {
    let reason = "";
    if (status === "rejected") {
      reason = (window.prompt?.("Reason for rejecting this recommendation:", "") || "").trim()
        || "rejected by engineer";
    }
    const res = status === "accepted"
      ? await api.accept_recommendation(projectRoot, key)
      : await api.reject_recommendation(projectRoot, key, reason);
    if (!res.ok) { setLoadError(res.error?.message || "could not record decision"); return; }
    await reload();
    onChanged && onChanged();   // rail: decision recorded
  }, [projectRoot, api, reload, onChanged]);

  const counts = {
    open: recs.filter(f => f.status === "open").length,
    accepted: recs.filter(f => f.status === "accepted").length,
    rejected: recs.filter(f => f.status === "rejected").length,
    all: recs.length,
  };
  const visible = recs.filter(f => filter === "all" ? true : f.status === filter);

  return (
    <div className="screen" data-screen="findings" data-screen-label="07 Findings &amp; recommendations" id="screen-findings" data-findings-stale={stale ? "true" : "false"}>
      <div className="screen-head">
        <div className="screen-title-block">
          <div className="eyebrow">Stage 6 / 7</div>
          <h1>Findings & recommendations</h1>
          <div className="lede">Specialist analysis agents produced these. Each recommendation is reviewable, <b>accept</b>/<b>reject</b>, and persists into the report's decision log.</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn primary" data-action="generate-report" onClick={onAdvance}>Generate report →</button>
        </div>
      </div>

      <div className="faint mono" style={{ fontSize: "var(--t-xs)", marginBottom: 8 }}>
        bridge:{" "}
        <span style={{ color: inPywebview ? "var(--sev-low)" : "var(--sev-med)" }}>
          {inPywebview ? "pywebview ✓ (live backend)" : "mock — browser dev (no real backend)"}
        </span>
        {projectRoot && <span> · project: <span style={{ color: "var(--text)" }}>{currentProject?.name || projectRoot}</span></span>}
        {!projectRoot && <span> · <span style={{ color: "var(--sev-med)" }}>no project — open one from Projects first</span></span>}
        {projectRoot && !loading && recs.length === 0 && <span> · <span style={{ color: "var(--sev-med)" }}>no recommendations yet — run the pipeline</span></span>}
      </div>
      {loadError && (
        <div className="card" style={{ padding: 12, marginBottom: 12, color: "var(--sev-high)" }}>
          <span className="mono">notice:</span> {loadError}
        </div>
      )}

      {stale && recs.length > 0 && (
        <StaleBanner bind="findings-stale-banner" onRerun={onRerun}>
          <b style={{ color: "var(--text)" }}>These findings are out of date.</b> The simulation they were generated from is stale — re-run the pipeline so the recommendations reflect the current inputs.
        </StaleBanner>
      )}

      {/* Filter pills */}
      <div style={{ display: "flex", gap: 6, marginBottom: 12 }} data-bind="findings-filter-bar">
        {[
          { v: "open", label: "Open" },
          { v: "accepted", label: "Accepted" },
          { v: "rejected", label: "Rejected" },
          { v: "all", label: "All" },
        ].map(f => (
          <button key={f.v} className="btn btn-sm" data-action="filter-findings" data-filter={f.v}
                  onClick={() => setFilter(f.v)}
                  style={filter === f.v ? { background: "var(--accent-dim)", borderColor: "oklch(0.70 0.18 var(--accent-h) / 0.4)", color: "var(--text)" } : null}>
            {f.label} <span className="mono faint" data-bind={`findings-count-${f.v}`} style={{ marginLeft: 6, fontSize: "var(--t-xs)"}}>{counts[f.v]}</span>
          </button>
        ))}
      </div>

      <div data-bind="findings-list" style={{ display: "flex", flexDirection: "column", gap: 10, opacity: stale ? 0.6 : 1 }}>
        {visible.length === 0 && !loading && (
          <div className="card" style={{ padding: 16 }}>
            <span className="dim mono" style={{ fontSize: "var(--t-xs)" }}>
              {recs.length === 0 ? "No recommendations — run the pipeline (Run screen) to generate them." : `No ${filter} recommendations.`}
            </span>
          </div>
        )}
        {visible.map((f) => (
          <FindingCard key={f.key} finding={f}
            expanded={expanded === f.key}
            onExpand={() => setExpanded(e => e === f.key ? "" : f.key)}
            onAccept={() => decide(f.key, "accepted")}
            onReject={() => decide(f.key, "rejected")} />
        ))}
      </div>

      <div style={{ marginTop: 16 }}>
        <PreComplianceDisclaimer />
      </div>
    </div>
  );
};

const FindingCard = ({ finding, expanded, onExpand, onAccept, onReject }) => {
  const f = finding;
  const barColor = `var(--sev-${f.severity})`;
  const barWidth = f.severity === "high" ? 4 : f.severity === "med" ? 3 : 2;
  return (
    <div className="card"
         data-finding-id={f.key} data-finding-area={f.area}
         data-finding-severity={f.severity} data-finding-status={f.status}
         data-finding-confidence={f.confidence}
         style={{ borderLeft: `${barWidth}px solid ${barColor}`, opacity: f.status === "rejected" ? 0.7 : 1 }}>
      <div className="card-head" data-action="toggle-finding-expand" style={{ cursor: "pointer" }} onClick={onExpand}>
        <div style={{ display: "flex", gap: 14, alignItems: "center", flex: 1 }}>
          <Icon name={expanded ? "chevron-down" : "chevron-right"} />
          <SeverityBadge level={f.severity} />
          <span className="mono faint" data-bind="finding-area" style={{ fontSize: "var(--t-xs)", letterSpacing: "0.08em", textTransform: "uppercase"}}>{f.area}</span>
          <span className="divider-v" style={{ height: 14 }} />
          <span data-bind="finding-problem" style={{ flex: 1, color: "var(--text)", fontFamily: "var(--font-sans)", fontSize: "var(--t-base)"}}>{f.problem}</span>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <ConfidenceDots value={f.confidence} />
          <span className="mono faint" data-bind="finding-confidence" style={{ fontSize: "var(--t-xs)"}}>{(f.confidence * 100).toFixed(0)}%</span>
          {f.status === "open"     && <Pill data-bind="finding-status">open</Pill>}
          {f.status === "accepted" && <Pill tone="ok" dot data-bind="finding-status">accepted</Pill>}
          {f.status === "rejected" && <Pill tone="bad" dot data-bind="finding-status">rejected</Pill>}
        </div>
      </div>

      {expanded && (
        <div className="card-body fade-in" style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 18 }}>
          <div>
            {f.evidence && <Field2 k="Evidence" bind="finding-evidence">{f.evidence}</Field2>}
            {f.proposal && <Field2 k="Proposed change" bind="finding-proposal">{f.proposal}</Field2>}
            {f.limitations && <Field2 k="Limitations" bind="finding-limitations">{f.limitations}</Field2>}
            {f.reason && <Field2 k="Rejection reason" bind="finding-reject-reason"><span style={{ color: "var(--sev-high)"}}>{f.reason}</span></Field2>}
            {!f.evidence && !f.proposal && !f.limitations && (
              <div className="dim mono" style={{ fontSize: "var(--t-xs)" }}>No further detail provided by the agent.</div>
            )}
          </div>

          <div className="col">
            <Card title="Cited knowledge sources">
              <div data-bind="finding-sources" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {f.sources.length === 0 && <span className="dim mono" style={{ fontSize: "var(--t-xs)" }}>none cited</span>}
                {f.sources.map((s, i) => (
                  <div key={i} className="mono" style={{ fontSize: "var(--t-xs)", color: "var(--text-dim)", display: "flex", gap: 8 }}>
                    <span className="faint">{(i + 1).toString().padStart(2, "0")}.</span><span>{s}</span>
                  </div>
                ))}
              </div>
            </Card>

            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              {f.status !== "rejected" && (
                <button className="btn danger" data-action="reject-recommendation" data-finding-id={f.key} onClick={onReject}><Icon name="x" /> Reject</button>
              )}
              {f.status !== "accepted" && (
                <button className="btn success" data-action="accept-recommendation" data-finding-id={f.key} onClick={onAccept}><Icon name="check" /> Accept</button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const Field2 = ({ k, bind, children }) => (
  <div style={{ paddingBottom: 12, marginBottom: 12, borderBottom: "1px solid var(--hairline)"}}>
    <div className="mono faint" style={{ fontSize: "var(--t-2xs)", letterSpacing: "0.14em", textTransform: "uppercase", marginBottom: 4 }}>{k}</div>
    <div data-bind={bind} style={{ color: "var(--text-dim)", fontSize: "var(--t-md)", fontFamily: "var(--font-sans)", lineHeight: 1.5 }}>{children}</div>
  </div>
);

window.FindingsScreen = FindingsScreen;
