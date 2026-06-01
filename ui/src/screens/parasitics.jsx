import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
// Screen: Parasitic selection — the priority screen.
//
// Layout: ~40% diagram (left) + ~60% table (right).
// Each row is a net; the engineer toggles include/exclude, can override
// an estimate (explicit "estimated → corrected" edit so it is capturable
// as a learning event later), and can run an "AI: suggest negligible"
// action which pre-deselects insignificant nets.

// Backend role name -> prototype role name (the UI uses the shorter names
// in its diagram / chips / filter pills).
const ROLE_MAP_BACKEND_TO_UI = {
  power_rail: "power",
  switching_node: "switch",
  signal: "signal",
  return: "return",
};

// Backend per-net estimate (SI units) -> screen-ready row:
//   r_typ_ohm / r_band  ->  R: [min, typ, max] in mΩ
//   l_typ_h   / l_band  ->  L: [min, typ, max] in nH
//   c_typ_f   / c_band  ->  C: [min, typ, max] in pF
// `override` is the matching entry from `user_context.parasitics.per_net`
// (the backend only persists `skip` + `c_pf` today; R / L overrides are
// not yet applied to the simulation and stay non-interactive below).
function _adaptNetForUI(est, override) {
  const role = ROLE_MAP_BACKEND_TO_UI[est.role] || "signal";
  const type = est.injectable ? "series-RLC" : "shunt-C";
  const Rband = est.r_band || [est.r_typ_ohm, est.r_typ_ohm];
  const Lband = est.l_band || [est.l_typ_h, est.l_typ_h];
  const Cband = est.c_band || [est.c_typ_f, est.c_typ_f];
  const R = [Rband[0] * 1e3, est.r_typ_ohm * 1e3, Rband[1] * 1e3];
  const L = [Lband[0] * 1e9, est.l_typ_h   * 1e9, Lband[1] * 1e9];
  const C = [Cband[0] * 1e12, est.c_typ_f  * 1e12, Cband[1] * 1e12];
  const include = !(override && override.skip);
  // Build the typed-view override from the backend keys (r_mohm / l_nh / c_pf
  // — all display units). Each "_estimated" sibling carries the rule-of-thumb
  // typ value so the audit log can show "est X → user Y".
  const o = {};
  if (override) {
    if (override.r_mohm != null) {
      o.R_typ = Number(override.r_mohm);
      o.R_typ_estimated = R[1];
    }
    if (override.l_nh != null) {
      o.L_typ = Number(override.l_nh);
      o.L_typ_estimated = L[1];
    }
    if (override.c_pf != null) {
      o.C_typ = Number(override.c_pf);
      o.C_typ_estimated = C[1];
    }
  }
  const hasOverride = Object.keys(o).length > 0;
  // Confidence is not emitted by the backend; derive it honestly from
  // the value provenance rather than faking a constant. A user override
  // is fully trusted; a rule-of-thumb estimate is "engineering estimate"
  // (the min/typ/max band already carries the uncertainty); a look-up /
  // extracted value is higher.
  const confidence =
    typeof est.confidence === "number" ? est.confidence :
    hasOverride ? 1.0 :
    (est.value_source === "look_up_table" || est.value_source === "extracted") ? 0.9 :
    est.value_source === "rule_of_thumb" ? 0.7 :
    0.5;
  // Reference designators wired to this net — lets the user identify an
  // opaque LTspice auto-name (N004) by what it connects to.
  const connected = Array.isArray(est.components) ? est.components : [];
  // The user's local reference `0` is renamed `DUT_GND` once the LISN is
  // composed (the real `0` then exists only on the LISN measurement side),
  // so flag it here for an honest note in the inspector.
  const isReturn = role === "return" || est.role === "return";
  return {
    net: est.net, role, type, R, L, C,
    confidence,
    include,
    override: hasOverride ? o : null,
    note: Array.isArray(est.notes) && est.notes.length ? est.notes[0] : null,
    connected,
    isReturn,
    _injectable: !!est.injectable,
  };
}

// Screen nets[] -> user_context.parasitics.per_net dict.
// Backend reads: `skip`, `r_mohm`, `l_nh`, `c_pf`. R / L overrides only
// apply to `injectable` (series-spliced) nets — for non-injectable nets
// we drop those keys to keep user_context clean.
function _buildPerNetOverrides(nets) {
  const per_net = {};
  for (const n of nets) {
    const entry = {};
    if (!n.include) entry.skip = true;
    if (n._injectable) {
      if (n.override?.R_typ != null) entry.r_mohm = Number(n.override.R_typ);
      if (n.override?.L_typ != null) entry.l_nh   = Number(n.override.L_typ);
    }
    if (n.override?.C_typ != null) entry.c_pf = Number(n.override.C_typ);
    if (Object.keys(entry).length > 0) per_net[n.net] = entry;
  }
  return per_net;
}

const ParasiticSelectionScreen = ({ tweaks, onAdvance, currentProject, llmActive, onChanged }) => {
  const api = useApi();
  const projectRoot = currentProject?.path || "";
  const inPywebview = typeof window !== "undefined" && !!window.isPywebview?.();

  const [nets, setNets] = useState(() => (window.SAMPLE ? window.SAMPLE.nets : []));
  const [selected, setSelected] = useState("");
  const [reportOnly, setReportOnly] = useState(false);
  const [filterRole, setFilterRole] = useState("all");
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideField, setOverrideField] = useState(null);   // {net, key, value, original}
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [composeStatus, setComposeStatus] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [reevalBusy, setReevalBusy] = useState(false);
  const [reeval, setReeval] = useState(null);   // {summary, proposals:[auditNet]} | null
  const ctxRef = useRef({});      // last-loaded user_context (kept for the save merge)

  const uncertaintyStyle = tweaks?.uncertaintyStyle || "bar";

  // Load per-net estimates + the project's overrides on mount / project change.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setLoadError("");
      if (!projectRoot) {
        // Browser dev / no project: keep the sample data so the screen renders.
        setNets(window.SAMPLE ? window.SAMPLE.nets : []);
        setLoading(false);
        return;
      }
      // Make sure parasitics_per_net.json exists (no-op when already up to date).
      const est = await api.estimate_per_net(projectRoot);
      if (cancelled) return;
      if (!est.ok) {
        setLoadError(est.error?.message || "could not estimate per-net parasitics");
        setLoading(false);
        return;
      }
      const [rawRes, ctxRes] = await Promise.all([
        api.read_artifact(projectRoot, "generated/parasitics_per_net.json"),
        api.load_context(projectRoot),
      ]);
      if (cancelled) return;
      const estimates = rawRes.ok && Array.isArray(rawRes.data) ? rawRes.data : [];
      const ctx = ctxRes.ok ? (ctxRes.data || {}) : {};
      ctxRef.current = ctx;
      const overrides = (ctx.parasitics && ctx.parasitics.per_net) || {};
      const adapted = estimates.map(e => _adaptNetForUI(e, overrides[e.net]));
      setNets(adapted);
      setSelected(adapted.find(n => n.role === "switch" || n.role === "power")?.net || adapted[0]?.net || "");
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [projectRoot, api]);

  // Persist the current nets[] back to user_context.parasitics.per_net.
  // Merges with the previously-loaded context so unrelated keys round-trip.
  const persistOverrides = useCallback(async (next) => {
    if (!projectRoot) return;
    const merged = JSON.parse(JSON.stringify(ctxRef.current || {}));
    // Preserve any prior per-net override whose net isn't surfaced in this
    // estimate run (e.g. the ground `0`, renamed to DUT_GND, or a hand-edited
    // net the estimator doesn't list). _buildPerNetOverrides only sees the
    // rows on screen, so without this a save would silently drop them.
    const prevPerNet = (merged.parasitics && merged.parasitics.per_net) || {};
    const known = new Set(next.map(n => n.net));
    const orphaned = Object.fromEntries(
      Object.entries(prevPerNet).filter(([net]) => !known.has(net))
    );
    merged.parasitics = {
      ...(merged.parasitics || {}),
      per_net: { ...orphaned, ..._buildPerNetOverrides(next) },
    };
    const res = await api.save_context(projectRoot, merged);
    if (res.ok) {
      ctxRef.current = merged;
      onChanged && onChanged();   // rail: selections changed → downstream goes stale
    } else {
      setLoadError(res.error?.message || "could not save overrides");
    }
  }, [projectRoot, api, onChanged]);

  const stats = useMemo(() => {
    const inc = nets.filter(n => n.include).length;
    const total = nets.length;
    const skipped = total - inc;
    const overrides = nets.filter(n => n.override).length;
    const lowConf = nets.filter(n => n.confidence < 0.7 && n.include).length;
    return { inc, total, skipped, overrides, lowConf };
  }, [nets]);

  const toggleNet = (name) => {
    setNets(ns => {
      const next = ns.map(n => n.net === name ? { ...n, include: !n.include } : n);
      persistOverrides(next);
      return next;
    });
  };

  // Override flow — `c_pf` is universal; `r_mohm` / `l_nh` only apply to
  // injectable (series-spliced) nets per the backend's
  // `default_series_plan`. Block R / L override on non-injectable nets.
  const beginOverride = (net, key, currentValue) => {
    if (key !== "C_typ" && key !== "R_typ" && key !== "L_typ") return;
    if ((key === "R_typ" || key === "L_typ") && !net._injectable) return;
    setOverrideField({ net: net.net, key, original: currentValue, value: currentValue });
    setOverrideOpen(true);
  };
  const commitOverride = () => {
    setNets(ns => {
      const next = ns.map(n => {
        if (n.net !== overrideField.net) return n;
        const value = parseFloat(overrideField.value);
        if (!Number.isFinite(value)) return n;
        return {
          ...n,
          override: {
            ...(n.override || {}),
            [overrideField.key]: value,
            [`${overrideField.key}_estimated`]: overrideField.original,
          },
        };
      });
      persistOverrides(next);
      return next;
    });
    setOverrideOpen(false);
    setOverrideField(null);
  };

  // Remove a single override key from a net (R_typ / L_typ / C_typ);
  // when the last override on a net is dropped, clear `override` entirely.
  const removeOverride = (name, key) => {
    setNets(ns => {
      const next = ns.map(n => {
        if (n.net !== name || !n.override) return n;
        const o = { ...n.override };
        delete o[key];
        delete o[`${key}_estimated`];
        const remaining = Object.keys(o).filter(k => !k.endsWith("_estimated"));
        return { ...n, override: remaining.length ? o : null };
      });
      persistOverrides(next);
      return next;
    });
  };

  // AI: suggest negligible — runs the M2.10.7 LLM negligibility screen via
  // the standalone `suggest_negligible` endpoint and pre-deselects the nets
  // it judges negligible. Enabled only when cloud LLM is active (opted in +
  // a key resolves); the backend re-checks and errors otherwise.
  const runAiSuggest = useCallback(async () => {
    if (!projectRoot || !llmActive || aiBusy) return;
    setAiBusy(true);
    setLoadError("");
    setComposeStatus("AI: screening nets…");
    const res = await api.suggest_negligible(projectRoot, { accept_parasitics: true });
    setAiBusy(false);
    if (!res.ok) {
      setComposeStatus("");
      setLoadError(res.error?.message || "AI suggest-negligible failed");
      return;
    }
    const dropped = Array.isArray(res.data?.dropped) ? res.data.dropped : [];
    const dropNets = new Set(dropped.map(d => d.net));
    if (dropNets.size === 0) {
      setComposeStatus(`AI: nothing negligible (${res.data?.considered ?? 0} considered)`);
      return;
    }
    setNets(ns => {
      const next = ns.map(n => dropNets.has(n.net) ? { ...n, include: false } : n);
      persistOverrides(next);
      return next;
    });
    setComposeStatus(`AI deselected ${dropNets.size} negligible net(s)`);
  }, [projectRoot, llmActive, aiBusy, api, persistOverrides]);

  // AI: re-evaluate values (M2.17) — preview pass. Refines per-net R/L/C into
  // citation-backed bands (RAG); writes the audit and shows proposals. Nothing
  // is applied until the user clicks "Apply refined typ values" below.
  const runReevaluate = useCallback(async () => {
    if (!projectRoot || !llmActive || reevalBusy) return;
    setReevalBusy(true); setLoadError(""); setComposeStatus("AI: re-evaluating values (RAG)…");
    const res = await api.reevaluate_parasitics(projectRoot);
    if (!res.ok) {
      setReevalBusy(false); setComposeStatus("");
      setLoadError(res.error?.message || "re-evaluate failed");
      return;
    }
    const audit = await api.read_artifact(projectRoot, "generated/parasitics_reevaluated.json");
    setReevalBusy(false);
    const proposals = (audit.ok && Array.isArray(audit.data?.nets))
      ? audit.data.nets.filter(n => n.refined) : [];
    setReeval({ summary: res.data, proposals });
    setComposeStatus(
      `AI re-evaluated ${res.data?.refined_count ?? 0}/${res.data?.considered ?? 0} net(s) · `
      + `${res.data?.cited_count ?? 0} cited · $${(res.data?.cost_usd ?? 0).toFixed(4)}`
    );
  }, [projectRoot, llmActive, reevalBusy, api]);

  // Accept step: persist the refined typ values from the audit as overrides
  // (no LLM call), then reload the table so it reflects them.
  const applyReevaluated = useCallback(async () => {
    if (!projectRoot) return;
    setComposeStatus("applying refined typ values…");
    const res = await api.apply_reevaluated_parasitics(projectRoot);
    if (!res.ok) { setLoadError(res.error?.message || "apply failed"); setComposeStatus(""); return; }
    setComposeStatus(`applied ${res.data?.applied ?? 0} refined typ override(s)`);
    setReeval(null);
    const [rawRes, ctxRes] = await Promise.all([
      api.read_artifact(projectRoot, "generated/parasitics_per_net.json"),
      api.load_context(projectRoot),
    ]);
    const estimates = rawRes.ok && Array.isArray(rawRes.data) ? rawRes.data : [];
    const ctx = ctxRes.ok ? (ctxRes.data || {}) : {};
    ctxRef.current = ctx;
    const overrides = (ctx.parasitics && ctx.parasitics.per_net) || {};
    setNets(estimates.map(e => _adaptNetForUI(e, overrides[e.net])));
    onChanged && onChanged();
  }, [projectRoot, api, onChanged]);

  // Compose testbench — primary action. Auto-applies the current overrides
  // (persisted by toggleNet / commitOverride above) and then advances.
  const onComposeTestbench = useCallback(async () => {
    if (!projectRoot) { onAdvance && onAdvance(); return; }
    setComposeStatus("composing…");
    const opts = {
      accept_wiring: true,
      accept_signals: true,
      accept_parasitics: true,
      parasitics_report_only: reportOnly,
    };
    const res = await api.compose_testbench(projectRoot, opts);
    if (!res.ok) {
      setLoadError(res.error?.message || "compose-testbench failed");
      setComposeStatus("");
      return;
    }
    setComposeStatus("composed");
    onChanged && onChanged();   // rail: testbench now present
    onAdvance && onAdvance();
  }, [projectRoot, api, reportOnly, onAdvance, onChanged]);

  const filteredNets = filterRole === "all" ? nets : nets.filter(n => n.role === filterRole);
  const selNet = nets.find(n => n.net === selected);

  // Bulk include/skip applied to the *current filtered view* only — so
  // "all off" under the SIGNAL filter skips just the signal nets.
  const setAllInView = (include) => {
    const inView = new Set(filteredNets.map(n => n.net));
    setNets(ns => {
      const next = ns.map(n => inView.has(n.net) ? { ...n, include } : n);
      persistOverrides(next);
      return next;
    });
  };

  return (
    <div className="screen" data-screen="parasitic-selection" data-screen-label="03 Parasitic selection" id="screen-parasitic-selection">
      <div className="screen-head">
        <div className="screen-title-block">
          <div className="eyebrow">Stage 2 / 7 · priority screen</div>
          <h1>Parasitic selection</h1>
          <div className="lede">For every net, decide which parasitics enter the simulated testbench. Estimates are <b>min · typ · max</b> bands with confidence — overrides are captured as explicit "estimated → corrected" edits.</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" data-action="ai-suggest-negligible"
                  onClick={runAiSuggest}
                  disabled={!llmActive || aiBusy || !projectRoot}
                  data-state={llmActive ? undefined : "coming-soon"}
                  style={llmActive ? undefined : { opacity: 0.45, cursor: "not-allowed" }}
                  data-tip={llmActive
                    ? "Run the LLM negligibility screen and pre-deselect nets it judges negligible."
                    : "Enable cloud LLM in Settings (and add an API key) to use this."}>
            <Icon name="ai" /> {aiBusy ? "Screening…" : "AI: suggest negligible"}
          </button>
          <button className="btn" data-action="ai-reevaluate-values"
                  onClick={runReevaluate}
                  disabled={!llmActive || reevalBusy || !projectRoot}
                  data-state={llmActive ? undefined : "coming-soon"}
                  style={llmActive ? undefined : { opacity: 0.45, cursor: "not-allowed" }}
                  data-tip={llmActive
                    ? "Re-evaluate per-net R/L/C into citation-backed min/typ/max bands (LLM + RAG). Review before applying."
                    : "Enable cloud LLM in Settings (and add an API key) to use this."}>
            <Icon name="ai" /> {reevalBusy ? "Re-evaluating…" : "AI: re-evaluate values (RAG)"}
          </button>
          <button className="btn" data-action="read-from-layout" disabled
                  style={{ opacity: 0.45, cursor: "not-allowed" }}
                  data-tip="Coming in M7 — read parasitic values from layout extraction.">
            Read from layout (M7)
          </button>
          <button className="btn primary" data-action="compose-testbench" onClick={onComposeTestbench}
                  disabled={composeStatus === "composing…"}>
            {composeStatus === "composing…" ? "Composing…" : "Compose testbench →"}
          </button>
        </div>
      </div>

      <div className="faint mono" style={{ fontSize: "var(--t-xs)", marginBottom: 8 }}>
        bridge:{" "}
        <span style={{ color: inPywebview ? "var(--sev-low)" : "var(--sev-med)" }}>
          {inPywebview ? "pywebview ✓ (live backend)" : "mock — browser dev (no real backend)"}
        </span>
        {projectRoot && <span> · project: <span style={{ color: "var(--text)" }}>{currentProject?.name || projectRoot}</span></span>}
        {!projectRoot && <span> · <span style={{ color: "var(--sev-med)" }}>no project — open one from Projects first</span></span>}
        {loading && <span> · <span style={{ color: "var(--sev-med)" }}>loading per-net estimates…</span></span>}
        {composeStatus && composeStatus !== "composing…" && <span> · <span style={{ color: "var(--sev-low)" }}>{composeStatus}</span></span>}
      </div>
      {loadError && (
        <div className="card" style={{ padding: 12, marginBottom: 12, color: "var(--sev-med)" }}>
          <span className="mono">notice:</span> {loadError}
        </div>
      )}

      {/* M2.17 re-evaluation proposals — review before applying */}
      {reeval && (
        <div className="card" style={{ padding: 14, marginBottom: 16, border: "1px solid var(--accent)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 10 }}>
            <div>
              <div className="mono" style={{ fontWeight: 600 }}>AI re-evaluation — proposals (review before applying)</div>
              <div className="mono dim" style={{ fontSize: "var(--t-xs)", marginTop: 2 }}>
                {(reeval.summary?.refined_count ?? 0)}/{(reeval.summary?.considered ?? 0)} net(s) refined · {(reeval.summary?.cited_count ?? 0)} citation-backed · ${(reeval.summary?.cost_usd ?? 0).toFixed(4)} · full min/typ/max + citations in <span className="mono">generated/parasitics_reevaluated.json</span>
              </div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn" data-action="dismiss-reeval" onClick={() => setReeval(null)}>Dismiss</button>
              <button className="btn primary" data-action="apply-reeval" onClick={applyReevaluated} disabled={!reeval.proposals?.length}>Apply refined typ values</button>
            </div>
          </div>
          {reeval.proposals?.length ? (
            <div style={{ maxHeight: 260, overflowY: "auto" }}>
              <table className="table">
                <thead><tr>
                  <th>net</th><th>source</th>
                  <th className="num">R typ (mΩ)</th><th className="num">L typ (nH)</th><th className="num">C typ (pF)</th>
                  <th className="num">conf</th><th>sources</th>
                </tr></thead>
                <tbody data-bind="reeval-proposals">
                  {reeval.proposals.map(p => {
                    const arrow = (prior, ref, scale) =>
                      `${(prior[1] * scale).toPrecision(3)} → ${(ref[1] * scale).toPrecision(3)}`;
                    const r = p.refined;
                    const cited = p.value_source === "llm_rag";
                    return (
                      <tr key={p.net} data-reeval-net={p.net}>
                        <td className="mono">{p.net}</td>
                        <td><span className="mono" style={{ fontSize: "var(--t-2xs)", color: cited ? "var(--sev-low)" : "var(--text-faint)" }}>{cited ? "LLM (RAG)" : "LLM (uncited)"}</span></td>
                        <td className="num tnum">{arrow(p.prior.r_band, r.r_band, 1e3)}</td>
                        <td className="num tnum">{arrow(p.prior.l_band, r.l_band, 1e9)}</td>
                        <td className="num tnum">{arrow(p.prior.c_band, r.c_band, 1e12)}</td>
                        <td className="num tnum">{(r.confidence ?? 0).toFixed(2)}</td>
                        <td className="mono dim" style={{ fontSize: "var(--t-2xs)" }}>{(r.cited_sources || []).join(", ") || "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="dim mono" style={{ fontSize: "var(--t-xs)" }}>No nets were refined — all kept their deterministic prior.</div>
          )}
        </div>
      )}

      {/* Top status row */}
      <div className="grid-4" style={{ marginBottom: 18 }}>
        <Stat label="Nets analysed" value={<span data-bind="nets-total">{nets.length}</span>} delta={<><span data-bind="nets-included">{stats.inc}</span> included · <span data-bind="nets-skipped">{stats.skipped}</span> skipped</>} />
        <Stat label="Overrides" value={<span data-bind="overrides-count">{stats.overrides}</span>} delta="captured as learning events" />
        <Stat label="Low confidence" value={<span data-bind="low-confidence-count">{stats.lowConf}</span>} delta="below 70 %" tone={stats.lowConf > 0 ? "med" : null} />
        <div className="stat" style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div className="label">Report-only mode</div>
            <div className="dim" style={{ fontSize: "var(--t-xs)", marginTop: 4 }}>keep estimates in report, exclude from sim</div>
          </div>
          <Toggle on={reportOnly} onChange={setReportOnly} data-action="toggle-report-only" />
        </div>
      </div>

      {/* Main: full-width diagram on top, table+inspector below */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {/* Diagram (full width hero) */}
        <Card title="Testbench block diagram" sub="click any block, rail, or parasitic to inspect" flush
              right={
                <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
                  <span className="mono faint" style={{ fontSize: "var(--t-xs)"}}>selected: <b data-bind="selected-net" style={{ color: "var(--accent)"}}>{selected || "—"}</b></span>
                  <div className="legend">
                    <span className="item" style={{ color: "oklch(0.78 0.18 25)"}}><span className="swatch" style={{ background: "oklch(0.66 0.20 25)"}}/> VIN+</span>
                    <span className="item" style={{ color: "oklch(0.82 0.10 230)"}}><span className="swatch" style={{ background: "oklch(0.72 0.10 230)"}}/> RTN/GND</span>
                    <span className="item" style={{ color: "oklch(0.85 0.14 75)"}}><span className="swatch" style={{ background: "oklch(0.78 0.16 75)"}}/> SW</span>
                    <span className="item" style={{ color: "var(--accent)"}}><span className="swatch" style={{ background: "var(--accent)"}}/> parasitic</span>
                  </div>
                </div>
              }>
          <TestbenchDiagram selectedNet={selected} nets={nets} onSelectNet={setSelected} height={460}
            dutSub={`${currentProject?.name || "user circuit"} · ${nets.length} nets`} />
        </Card>

        {/* Split: inspector + roles (left ~38%) — table (right ~62%) */}
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 38fr) minmax(0, 62fr)", gap: 16 }}>
          <div className="col">
            {/* Net inspector */}
            {selNet && <NetInspector net={selNet} onToggle={() => toggleNet(selNet.net)} onOverride={beginOverride} uncertaintyStyle={uncertaintyStyle} />}

            {/* Role legend */}
            <Card title="Net roles">
              <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                <RoleChip role="power" />
                <RoleChip role="return" />
                <RoleChip role="switch" />
                <RoleChip role="signal" />
                <RoleChip role="output" />
              </div>
              <div className="dim" style={{ marginTop: 10, fontSize: "var(--t-xs)", fontFamily: "var(--font-mono)"}}>
                Switching & power nets typically dominate conducted-EMI; signal nets are usually skippable.
              </div>
            </Card>

            {/* Override audit log */}
            <Card title="Override log" sub="explicit estimated → corrected edits (capturable as training signal)">
              {nets.filter(n => n.override).length === 0 ? (
                <div className="dim" data-bind="override-log-empty" style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-xs)"}}>
                  No overrides yet. Engineer corrections recorded here become training signal for the future Engineer Training model.
                </div>
              ) : (
                <div data-bind="override-log" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {nets.filter(n => n.override).flatMap(n =>
                    Object.keys(n.override)
                      .filter(x => !x.endsWith("_estimated"))
                      .map(k => {
                        const v = n.override[k];
                        const orig = n.override[`${k}_estimated`];
                        const unit = k === "R_typ" ? "mΩ" : k === "L_typ" ? "nH" : "pF";
                        return (
                          <div key={`${n.net}.${k}`} data-override-net={n.net} data-override-key={k} style={{ display: "grid", gridTemplateColumns: "auto 1fr auto auto auto", gap: 12, alignItems: "center", padding: "6px 10px", background: "var(--panel-2)", borderRadius: 4 }}>
                            <span className="net-tag" style={{ color: "var(--accent)"}}>{n.net}</span>
                            <span className="mono dim" style={{ fontSize: "var(--t-xs)"}}>{k.replace("_typ", " (typ)")} {unit}</span>
                            <span className="mono"><span className="faint">{orig?.toFixed?.(2) ?? orig}</span> → <b style={{ color: OVERRIDE_COLOR }}>{v}</b></span>
                            <Pill tone="accent">capturable</Pill>
                            <button className="icon-btn" data-action="remove-override" data-net={n.net} data-component={k} onClick={() => removeOverride(n.net, k)}><Icon name="x" size={12} /></button>
                          </div>
                        );
                      })
                  )}
                </div>
              )}
            </Card>

            <PreComplianceDisclaimer />
          </div>

          <div className="col">
            <Card title={<span data-bind="nets-shown-count">{`${filteredNets.length} of ${nets.length} nets`}</span>}
                  sub="estimate → review → include"
                  right={
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <button className="btn btn-sm" data-action="include-all-in-view" onClick={() => setAllInView(true)}
                        data-tip={`Include all ${filteredNets.length} ${filterRole === "all" ? "" : filterRole + " "}nets in view`}>All on</button>
                <button className="btn btn-sm" data-action="skip-all-in-view" onClick={() => setAllInView(false)}
                        data-tip={`Skip all ${filteredNets.length} ${filterRole === "all" ? "" : filterRole + " "}nets in view`}>All off</button>
                <span className="mono faint" style={{ fontSize: "var(--t-2xs)", letterSpacing: "0.12em"}}>FILTER</span>
                <Segmented value={filterRole} options={[
                  { value: "all", label: "ALL" },
                  { value: "power", label: "POWER" },
                  { value: "return", label: "RETURN" },
                  { value: "switch", label: "SWITCH" },
                  { value: "signal", label: "SIGNAL" },
                ]} onChange={setFilterRole} />
              </div>
            } flush>
              <div style={{ overflow: "auto", maxHeight: 640 }}>
                <table className="table" id="nets-table">
                  <thead>
                    <tr>
                      <th style={{ width: 28 }}></th>
                      <th>Net</th>
                      <th>Role</th>
                      <th>Type</th>
                      <th>R (mΩ)</th>
                      <th>L (nH)</th>
                      <th>C (pF)</th>
                      <th>Conf</th>
                      <th style={{ width: 40 }}></th>
                    </tr>
                  </thead>
                  <tbody data-bind="nets-list">
                    {filteredNets.map(n => (
                      <NetRow key={n.net}
                              net={n}
                              selected={selected === n.net}
                              uncertaintyStyle={uncertaintyStyle}
                              onSelect={() => setSelected(n.net)}
                              onToggle={() => toggleNet(n.net)}
                              onOverride={beginOverride} />
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        </div>
      </div>

      {/* Override modal */}
      {overrideOpen && overrideField && (
        <OverrideDialog
          field={overrideField}
          onChange={v => setOverrideField(o => ({ ...o, value: v }))}
          onCancel={() => setOverrideOpen(false)}
          onCommit={commitOverride} />
      )}
    </div>
  );
};

// Distinct colour for user-overridden values — deliberately NOT the
// accent purple (that means "selected") so an override reads as its own
// thing: a teal "you changed this".
const OVERRIDE_COLOR = "oklch(0.82 0.14 195)";
const OVERRIDE_CELL = {
  background: "oklch(0.82 0.14 195 / 0.10)",
  boxShadow: `inset 2px 0 0 ${OVERRIDE_COLOR}`,
};

// ----- Net row -----------------------------------------------------------
const NetRow = ({ net, selected, onSelect, onToggle, onOverride, uncertaintyStyle }) => {
  const includeOff = !net.include;

  // Per-column scale (rough, generous so wide bands look wide)
  const scaleR = [0, 35];
  const scaleL = [0, 14];
  const scaleC = [0, 90];

  // Render an R/L/C value cell; when overridden, draw the band with the
  // override as typ + a teal "est X → user Y" sub-label so the changed
  // value stands out in its own colour.
  const ovCell = (key, vals, scale) => {
    const ov = net.override?.[key];
    const view = (
      <UncertaintyView values={ov != null ? [vals[0], ov, vals[2]] : vals}
                       unit="" style={uncertaintyStyle} scaleMin={scale[0]} scaleMax={scale[1]} />
    );
    if (ov == null) return view;
    return (
      <span style={{ display: "inline-flex", flexDirection: "column" }}>
        {view}
        <span className="faint" style={{ fontSize: 10, marginTop: 1 }}>
          <span className="mono">est {vals[1]}</span> → <span className="mono" style={{ color: OVERRIDE_COLOR, fontWeight: 600 }}>user {ov}</span>
        </span>
      </span>
    );
  };

  return (
    <tr className={`${selected ? "selected" : ""} ${includeOff ? "dim" : ""}`}
        data-action="select-net"
        data-net={net.net}
        data-net-role={net.role}
        data-net-included={net.include ? "true" : "false"}
        onClick={onSelect}>
      <td onClick={e => { e.stopPropagation(); onToggle(); }}>
        <Toggle on={net.include} data-action="toggle-net-include" data-net={net.net} />
      </td>
      <td>
        <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
          <span className="net-tag"
            data-tip={Array.isArray(net.connected) && net.connected.length ? `connects ${net.connected.join(", ")}` : undefined}
            style={{ color: selected ? "var(--accent)" : "var(--text)", cursor: net.connected?.length ? "help" : undefined }}>{net.net}</span>
          {Array.isArray(net.connected) && net.connected.length > 0 && (
            <span className="faint mono" style={{ fontSize: 10 }}>{net.connected.slice(0, 4).join(" · ")}{net.connected.length > 4 ? " …" : ""}</span>
          )}
          {net.note && <span className="faint" style={{ fontSize: 10 }}>{net.note}</span>}
        </div>
      </td>
      <td><RoleChip role={net.role} /></td>
      <td><span className="mono faint" style={{ fontSize: "var(--t-xs)"}}>{net.type}</span></td>
      <td onClick={net._injectable ? e => { e.stopPropagation(); onOverride(net, "R_typ", net.R[1]); } : undefined}
          data-action={net._injectable ? "override-net-value" : undefined}
          data-net={net.net} data-component="R_typ"
          data-tip={net._injectable ? "click to override R" : "shunt-only net — only a Cp is injected; R/L are estimates, not simulated"}
          style={{ cursor: net._injectable ? "pointer" : "default", opacity: net._injectable ? 1 : 0.45,
                   ...(net.override?.R_typ != null ? OVERRIDE_CELL : {}) }}>
        {ovCell("R_typ", net.R, scaleR)}
      </td>
      <td onClick={net._injectable ? e => { e.stopPropagation(); onOverride(net, "L_typ", net.L[1]); } : undefined}
          data-action={net._injectable ? "override-net-value" : undefined}
          data-net={net.net} data-component="L_typ"
          data-tip={net._injectable ? "click to override L" : "shunt-only net — only a Cp is injected; R/L are estimates, not simulated"}
          style={{ cursor: net._injectable ? "pointer" : "default", opacity: net._injectable ? 1 : 0.45,
                   ...(net.override?.L_typ != null ? OVERRIDE_CELL : {}) }}>
        {ovCell("L_typ", net.L, scaleL)}
      </td>
      <td onClick={e => { e.stopPropagation(); net.C && onOverride(net, "C_typ", net.C[1]); }}
          data-action={net.C ? "override-net-value" : undefined} data-net={net.net} data-component="C_typ"
          data-tip="click to override C"
          style={{ cursor: net.C ? "pointer" : "default",
                   ...(net.override?.C_typ != null ? OVERRIDE_CELL : {}) }}>
        {ovCell("C_typ", net.C, scaleC)}
      </td>
      <td><ConfidenceDots value={net.confidence} /></td>
      <td>
        <button className="icon-btn" data-tip="select on diagram"><Icon name="chevron-right" size={12} /></button>
      </td>
    </tr>
  );
};

// ----- Net inspector ----------------------------------------------------
const NetInspector = ({ net, onToggle, onOverride, uncertaintyStyle }) => (
  <Card title={
    <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span style={{ color: "var(--accent)"}} data-bind="inspector-net-name">{net.net}</span>
      <RoleChip role={net.role} />
    </span>
  } sub={net.type} right={
    <Toggle on={net.include} onChange={onToggle} label={net.include ? "INCLUDE" : "SKIP"} data-action="toggle-net-include" data-net={net.net} />
  }>
    {net.note && <div className="dim" style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-xs)", marginBottom: 12 }}>{net.note}</div>}
    {Array.isArray(net.connected) && net.connected.length > 0 && (
      <div data-bind="inspector-connects" style={{ marginBottom: 12 }}>
        <div className="mono faint" style={{ fontSize: "var(--t-xs)", marginBottom: 6 }}>
          connects {net.connected.length} component{net.connected.length === 1 ? "" : "s"}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {net.connected.map(refdes => (
            <span key={refdes} className="mono" style={{
              fontSize: "var(--t-xs)", padding: "2px 7px", borderRadius: 4,
              border: "1px solid var(--border)", background: "var(--bg-subtle, transparent)",
              color: "var(--text)",
            }}>{refdes}</span>
          ))}
        </div>
      </div>
    )}
    {net.isReturn && (
      <div className="dim" data-bind="inspector-ground-note" style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-xs)", marginBottom: 12 }}>
        DUT-side virtual ground (your schematic's <code>0</code>, renamed for the dual-LISN testbench). Per-net shunt capacitances return here; the SPICE <code>0</code> node exists only on the LISN measurement side.
      </div>
    )}
    <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "8px 14px", alignItems: "center" }}>
      {net.R && (<>
        <span className="mono faint">R</span>
        <span style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <UncertaintyView values={net.R} unit="mΩ" style={uncertaintyStyle} />
          {net._injectable && (
            <button className="btn btn-sm ghost" data-action="override-net-value" data-net={net.net} data-component="R_typ" onClick={() => onOverride(net, "R_typ", net.R[1])}>override</button>
          )}
        </span>
      </>)}
      {net.L && (<>
        <span className="mono faint">L</span>
        <span style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <UncertaintyView values={net.L} unit="nH" style={uncertaintyStyle} />
          {net._injectable && (
            <button className="btn btn-sm ghost" data-action="override-net-value" data-net={net.net} data-component="L_typ" onClick={() => onOverride(net, "L_typ", net.L[1])}>override</button>
          )}
        </span>
      </>)}
      {net.C && (<>
        <span className="mono faint">C</span>
        <span style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <UncertaintyView values={net.C} unit="pF" style={uncertaintyStyle} />
          <button className="btn btn-sm ghost" data-action="override-net-value" data-net={net.net} data-component="C_typ" onClick={() => onOverride(net, "C_typ", net.C[1])}>override</button>
        </span>
      </>)}
      <span className="mono faint">conf</span>
      <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <ConfidenceDots value={net.confidence} />
        <span className="mono dim" style={{ fontSize: "var(--t-xs)"}}>{(net.confidence * 100).toFixed(0)}%</span>
      </span>
    </div>
  </Card>
);

// ----- Override dialog --------------------------------------------------
const OverrideDialog = ({ field, onChange, onCancel, onCommit }) => {
  const labelMap = { R_typ: "R (typ)", L_typ: "L (typ)", C_typ: "C (typ)" };
  const unitMap = { R_typ: "mΩ", L_typ: "nH", C_typ: "pF" };
  return (
    <div style={{
      position: "fixed", inset: 0, background: "var(--scrim)",
      display: "grid", placeItems: "center", zIndex: 100,
    }}
      id="override-dialog"
      data-override-net={field.net}
      data-override-key={field.key}
      onClick={onCancel}>
      <div style={{
        width: 440, background: "var(--panel)", border: "1px solid var(--border-strong)",
        borderRadius: 6, boxShadow: "0 30px 80px rgba(0,0,0,0.5)",
      }} onClick={e => e.stopPropagation()}>
        <div className="card-head">
          <h3>Override estimate — <span style={{ color: "var(--accent)"}}>{field.net}</span></h3>
          <button className="icon-btn" onClick={onCancel}><Icon name="x" /></button>
        </div>
        <div style={{ padding: 16 }}>
          <div className="dim" style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-xs)", marginBottom: 12 }}>
            This change is recorded as an explicit <b style={{ color: "var(--accent)"}}>estimated → corrected</b> edit. When you opt in to Engineer Training (future), these become training signal.
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="estimated" units={unitMap[field.key]}>
              <input className="input" value={field.original} disabled style={{ borderRadius: "var(--radius) 0 0 var(--radius)"}}/>
            </Field>
            <Field label={labelMap[field.key] + " — your value"} units={unitMap[field.key]}>
              <input className="input" value={field.value} onChange={e => onChange(e.target.value)} autoFocus style={{ borderRadius: "var(--radius) 0 0 var(--radius)"}}/>
            </Field>
          </div>
        </div>
        <div style={{ padding: "12px 16px", borderTop: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span className="mono faint" style={{ fontSize: 10 }}>Will mark testbench stale (re-run required).</span>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn" data-action="cancel-override" onClick={onCancel}>Cancel</button>
            <button className="btn primary" data-action="commit-override" onClick={onCommit}>Save correction</button>
          </div>
        </div>
      </div>
    </div>
  );
};

window.ParasiticSelectionScreen = ParasiticSelectionScreen;
