import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
// Screen: Results — wired to api.load_results (diagnostic narrative +
// corner-variant ranking + headline metrics from results/diagnostic.json
// and results/variants/*.json), api.load_spectrum (detector-vs-limit
// curves) and the M2.18 two-panel waveform analyzer (api.load_waveform for
// the V(meas) + comparison envelopes; api.suggest_waveform_traces for the
// default I(Rload) + four LLM/heuristic comparison choices). Metrics
// populate after a local-run; before that the cards show honest states.

const ResultsScreen = ({ onAdvance, currentProject, stale, onRerun }) => {
  const api = useApi();
  const projectRoot = currentProject?.path || "";
  const inPywebview = typeof window !== "undefined" && !!window.isPywebview?.();

  const [view, setView] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [activeVariant, setActiveVariant] = useState(null);
  const [spec, setSpec] = useState(null);
  const [specLoading, setSpecLoading] = useState(false);
  const [specNote, setSpecNote] = useState("");
  const [traces, setTraces] = useState({ peak: false, qp: true, avg: true, limit: true });
  const [wave, setWave] = useState(null);
  const [waveLoading, setWaveLoading] = useState(false);
  const [waveNote, setWaveNote] = useState("");
  const [cmpOpts, setCmpOpts] = useState(null);   // {default, suggestions, options, llm_generated}
  const [cmpTrace, setCmpTrace] = useState(null);  // selected comparison trace name
  const [cmpWave, setCmpWave] = useState(null);
  const [cmpLoading, setCmpLoading] = useState(false);
  const [cmpNote, setCmpNote] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!projectRoot) { setView(null); setLoading(false); return; }
      setLoading(true); setLoadError("");
      const res = await api.load_results(projectRoot);
      if (cancelled) return;
      if (!res.ok) {
        setLoadError(res.error?.message || "could not load results");
        setView(null); setLoading(false); return;
      }
      setView(res.data);
      setActiveVariant(res.data?.ranking?.[0]?.label || null);
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [projectRoot, api]);

  const diag = view?.diagnostic || null;
  const base = view?.baseline || {};
  const ranking = view?.ranking || [];
  const hasMetrics = !!view?.has_metrics;

  // Detector-vs-limit spectrum — loaded lazily (the sweep is a few seconds
  // on the first call, then cached to results/spectrum.json server-side).
  useEffect(() => {
    let cancelled = false;
    if (!projectRoot || !hasMetrics) { setSpec(null); return; }
    setSpecLoading(true); setSpecNote("");
    (async () => {
      const res = await api.load_spectrum(projectRoot);
      if (cancelled) return;
      setSpecLoading(false);
      if (!res.ok) { setSpecNote(res.error?.message || "spectrum failed"); return; }
      if (res.data?.available) setSpec(res.data);
      else { setSpec(null); setSpecNote(res.data?.note || "spectrum unavailable"); }
    })();
    return () => { cancelled = true; };
  }, [projectRoot, api, hasMetrics]);

  // Time-domain waveform — the trace the detectors/FFT actually run on. Fast
  // (a min/max-envelope decimation of the .raw, no sweep), then cached to
  // results/waveform.json server-side.
  useEffect(() => {
    let cancelled = false;
    if (!projectRoot || !hasMetrics) { setWave(null); return; }
    setWaveLoading(true); setWaveNote("");
    (async () => {
      const res = await api.load_waveform(projectRoot);
      if (cancelled) return;
      setWaveLoading(false);
      if (!res.ok) { setWaveNote(res.error?.message || "waveform failed"); return; }
      if (res.data?.available) setWave(res.data);
      else { setWave(null); setWaveNote(res.data?.note || "waveform unavailable"); }
    })();
    return () => { cancelled = true; };
  }, [projectRoot, api, hasMetrics]);

  // Comparison-subplot trace choices — default I(Rload) + four traces the
  // LLM (or heuristic) deems most relevant. Cached server-side per run.
  useEffect(() => {
    let cancelled = false;
    if (!projectRoot || !hasMetrics) { setCmpOpts(null); setCmpTrace(null); return; }
    (async () => {
      const res = await api.suggest_waveform_traces(projectRoot);
      if (cancelled) return;
      if (res.ok && res.data?.available) {
        setCmpOpts(res.data);
        setCmpTrace(res.data.default?.trace || res.data.options?.[0]?.trace || null);
      } else { setCmpOpts(null); setCmpTrace(null); }
    })();
    return () => { cancelled = true; };
  }, [projectRoot, api, hasMetrics]);

  // The comparison subplot's selected trace envelope (shares the .raw axis
  // with V(meas), so it aligns sample-for-sample on the time axis).
  useEffect(() => {
    let cancelled = false;
    if (!projectRoot || !hasMetrics || !cmpTrace) { setCmpWave(null); return; }
    setCmpLoading(true); setCmpNote("");
    (async () => {
      const res = await api.load_waveform(projectRoot, cmpTrace);
      if (cancelled) return;
      setCmpLoading(false);
      if (!res.ok) { setCmpNote(res.error?.message || "waveform failed"); return; }
      if (res.data?.available) setCmpWave(res.data);
      else { setCmpWave(null); setCmpNote(res.data?.note || "trace unavailable"); }
    })();
    return () => { cancelled = true; };
  }, [projectRoot, api, hasMetrics, cmpTrace]);

  // margin_db = reading − limit: POSITIVE means the reading is OVER the
  // limit (a breach); negative means under it (pass). The worst case is the
  // largest margin across variants.
  const margins = ranking.map(r => r.margin_db).filter(v => typeof v === "number");
  const worstMargin = margins.length ? Math.max(...margins) : base.margin_db;
  const verdictPass = typeof worstMargin === "number" ? worstMargin < 0 : null;
  const dmDominant = typeof base.dm_peak === "number" && typeof base.cm_peak === "number"
    ? base.dm_peak >= base.cm_peak : null;

  const dbuv = v => (typeof v === "number" ? `${v.toFixed(1)} dBµV` : "—");
  const db = v => (typeof v === "number" ? `${v >= 0 ? "+" : ""}${v.toFixed(1)} dB` : "—");

  return (
    <div className="screen" data-screen="results" data-screen-label="06 Results" id="screen-results" data-results-stale={stale ? "true" : "false"}>
      <div className="screen-head">
        <div className="screen-title-block">
          <div className="eyebrow">Stage 5 / 7</div>
          <h1>Results</h1>
          <div className="lede">Synthesised diagnostic verdict in <i>engineering-hypothesis</i> language, plus the corner-variant ranking and headline conducted-band metrics.</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn primary" data-action="goto-findings" onClick={onAdvance}>Review findings →</button>
        </div>
      </div>

      <div className="faint mono" style={{ fontSize: "var(--t-xs)", marginBottom: 8 }}>
        bridge:{" "}
        <span style={{ color: inPywebview ? "var(--sev-low)" : "var(--sev-med)" }}>
          {inPywebview ? "pywebview ✓ (live backend)" : "mock — browser dev (no real backend)"}
        </span>
        {projectRoot && <span> · project: <span style={{ color: "var(--text)" }}>{currentProject?.name || projectRoot}</span></span>}
        {!projectRoot && <span> · <span style={{ color: "var(--sev-med)" }}>no project — open one from Projects first</span></span>}
        {projectRoot && !loading && !diag && <span> · <span style={{ color: "var(--sev-med)" }}>no diagnostic yet — run the pipeline</span></span>}
        {projectRoot && !loading && diag && !hasMetrics && <span> · <span style={{ color: "var(--sev-med)" }}>no metrics — run in local-run mode</span></span>}
      </div>
      {loadError && (
        <div className="card" style={{ padding: 12, marginBottom: 12, color: "var(--sev-high)" }}>
          <span className="mono">notice:</span> {loadError}
        </div>
      )}

      {stale && (diag || hasMetrics) && (
        <StaleBanner bind="results-stale-banner" onRerun={onRerun}>
          <b style={{ color: "var(--text)" }}>These results are out of date.</b> An input changed since this run was generated — the verdict and numbers below reflect the previous inputs. Re-run the pipeline to refresh.
        </StaleBanner>
      )}

      {/* Diagnostic narrative — results/diagnostic.json */}
      <Card title="Diagnostic narrative" sub={`results/diagnostic.json${diag ? (diag.llm_generated ? " · LLM synthesis" : " · deterministic synthesis") : ""}`}
            right={diag && <div style={{ display: "flex", gap: 10, alignItems: "center"}}>
              <ConfidenceDots value={diag.confidence ?? 0.5} />
              <span className="mono dim" data-bind="diagnostic-confidence" style={{ fontSize: "var(--t-xs)"}}>confidence {Math.round((diag.confidence ?? 0) * 100)} %</span>
            </div>}>
        {!diag ? (
          <div className="dim" style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-xs)" }}>
            No diagnostic yet — run the pipeline (Run screen) to synthesise one from the specialist agents.
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 16, alignItems: "start"}}>
            <div data-bind="diagnostic-narrative">
              <div style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-xs)", color: "var(--text-faint)", marginBottom: 6 }}>{diag.title}</div>
              <div style={{ fontFamily: "var(--font-sans)", fontSize: 15, lineHeight: 1.6, color: "var(--text)" }}>
                <p style={{ margin: "0 0 10px"}}>{diag.narrative}</p>
                {diag.dominant_issue && <p style={{ margin: "0 0 10px"}}><b>Dominant issue:</b> {diag.dominant_issue}</p>}
                <p style={{ margin: 0, color: "var(--text-dim)", fontStyle: "italic", fontSize: 13 }}>
                  Pre-compliance hypothesis — confirm with a laboratory CISPR-16 measurement.
                </p>
                {Array.isArray(diag.limitations) && diag.limitations.length > 0 && (
                  <ul className="dim" style={{ margin: "10px 0 0", paddingLeft: 18, fontSize: "var(--t-xs)", fontFamily: "var(--font-mono)" }}>
                    {diag.limitations.map((l, i) => <li key={i}>{l}</li>)}
                  </ul>
                )}
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 180 }} data-bind="diagnostic-tags">
              {stale && <Pill tone="warn" dot>stale · re-run</Pill>}
              {verdictPass === true && <Pill tone="ok">VERDICT · within limit by {Math.abs(worstMargin).toFixed(1)} dB</Pill>}
              {verdictPass === false && <Pill tone="bad">VERDICT · exceeds limit by {worstMargin.toFixed(1)} dB</Pill>}
              {dmDominant === true && <Pill tone="info">DM dominant</Pill>}
              {dmDominant === false && <Pill tone="info">CM dominant</Pill>}
              {Array.isArray(diag.cited_findings) && diag.cited_findings.slice(0, 3).map(a => (
                <Pill key={a}>{a}</Pill>
              ))}
              <Pill>simulated only</Pill>
            </div>
          </div>
        )}
      </Card>

      {/* Headline metrics — baseline variant */}
      <div className="grid-4" style={{ marginTop: 16, opacity: stale ? 0.5 : 1 }}>
        <Stat label="Band peak (baseline)" value={<span data-bind="results-peak">{dbuv(base.peak_dbuv)}</span>}
              delta={typeof base.margin_hz === "number" ? `@ ${window.fmt.hz(base.margin_hz)} · 150 k–30 MHz` : "150 k–30 MHz"} tone={hasMetrics ? null : null} />
        <Stat label="Worst QP margin" value={<span data-bind="results-worst-margin">{db(worstMargin)}</span>}
              delta="vs CISPR-B QP · + = over limit" tone={verdictPass === false ? "high" : verdictPass === true ? "low" : null} />
        <Stat label="Corner-variant span" value={<span data-bind="results-corner-span">{typeof base.span_db === "number" ? `${base.span_db.toFixed(2)} dB` : "—"}</span>} delta="min … max peak" />
        <Stat label="DM peak (baseline)" value={<span data-bind="results-dm-peak">{typeof base.dm_peak === "number" ? `${base.dm_peak.toFixed(2)} V` : "—"}</span>} delta={typeof base.cm_peak === "number" ? `CM ${base.cm_peak.toExponential(1)} V` : ""} />
      </div>

      {/* Time-domain waveform analyzer — V(meas) over a time-aligned
          comparison trace (M2.18). Both panels share the X (time) axis. */}
      <Card title="Time-domain waveform analyzer" style={{ marginTop: 16 }}
            sub={wave
              ? `${wave.points?.length || 0} envelope buckets of ${wave.n_raw?.toLocaleString?.() || wave.n_raw} samples · ${window.fmt.sec(wave.t_min)}…${window.fmt.sec(wave.t_max)}${wave.n_steps > 1 ? ` · ${wave.corner || "typ"} corner (1 of ${wave.n_steps})` : ""}`
              : "the LISN-measured voltage over time, against a selectable comparison trace"}>
        {!hasMetrics ? (
          <div className="dim mono" style={{ fontSize: "var(--t-xs)" }}>Run in <b>local-run</b> mode (real LTspice) to capture the transient waveform.</div>
        ) : waveLoading ? (
          <div className="dim mono" style={{ fontSize: "var(--t-xs)" }}>Reading the transient .raw…</div>
        ) : wave ? (
          <div>
            {/* Top panel — measured LISN voltage */}
            <div className="mono dim" style={{ fontSize: "var(--t-2xs)", marginBottom: 1 }}>
              {wave.trace} <span style={{ color: "var(--text-faint)" }}>[{wave.unit || "V"}]</span> · measured
            </div>
            <WaveformChart points={wave.points} tMin={wave.t_min} tMax={wave.t_max}
                           unit={wave.unit || "V"} showXAxis={false} height={158} />

            {/* Comparison-trace selector (M2.18) */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", margin: "8px 0 1px" }}>
              <span className="mono dim" style={{ fontSize: "var(--t-2xs)" }}>compare against:</span>
              <select value={cmpTrace || ""} onChange={e => setCmpTrace(e.target.value)}
                      data-action="select-compare-trace"
                      style={{ background: "var(--surface-2, var(--surface))", color: "var(--text)",
                               border: "1px solid var(--border)", borderRadius: 6,
                               fontFamily: "var(--font-mono)", fontSize: "var(--t-xs)", padding: "3px 6px" }}>
                {(cmpOpts?.options || []).map(o => (
                  <option key={o.trace} value={o.trace}>
                    {o.label} · {o.trace}{o.source === "default" ? "  (default)" : ""}
                  </option>
                ))}
              </select>
              {cmpOpts && (cmpOpts.llm_generated
                ? <Pill tone="info">AI-picked traces</Pill>
                : <Pill>heuristic traces</Pill>)}
            </div>

            {/* Bottom panel — the selected comparison trace (shares X) */}
            {cmpLoading ? (
              <div className="dim mono" style={{ fontSize: "var(--t-xs)", padding: "8px 0" }}>loading {cmpTrace}…</div>
            ) : cmpWave ? (
              <>
                <div className="mono dim" style={{ fontSize: "var(--t-2xs)", marginBottom: 1 }}>
                  {cmpWave.trace} <span style={{ color: "var(--text-faint)" }}>[{cmpWave.unit || "?"}]</span>
                </div>
                <WaveformChart points={cmpWave.points} tMin={wave.t_min} tMax={wave.t_max}
                               unit={cmpWave.unit || ""} showXAxis={true} height={184} />
              </>
            ) : (
              <div className="dim mono" style={{ fontSize: "var(--t-xs)", padding: "8px 0" }}>{cmpNote || "select a comparison trace"}</div>
            )}
            {(() => {
              const sel = (cmpOpts?.options || []).find(o => o.trace === cmpTrace);
              return sel?.reason ? (
                <div className="dim" style={{ fontSize: "var(--t-2xs)", marginTop: 2, fontStyle: "italic" }}>
                  {sel.source === "llm" ? "AI: " : ""}{sel.reason}
                </div>
              ) : null;
            })()}
          </div>
        ) : (
          <div className="dim mono" style={{ fontSize: "var(--t-xs)" }}>{waveNote || "waveform unavailable"}</div>
        )}
        <div className="dim mono" style={{ marginTop: 10, fontSize: "var(--t-2xs)", borderTop: "1px solid var(--border)", paddingTop: 8 }}>
          Both panels share the time axis. Shaded band = the min/max envelope within each time bucket (switching spikes are not aliased away). The default comparison is the load current; the four other choices are picked for EMI relevance. The spectrum below is computed from the top (V(meas)) trace.
        </div>
      </Card>

      {/* Detector-vs-limit spectrum — the curves the margins are read off */}
      <Card title="Conducted-emissions spectrum" style={{ marginTop: 16 }}
            sub={spec ? `${spec.standard_name} · trace ${spec.trace} · ${spec.n_points} pts (peak/QP/avg vs limit)${spec.n_steps > 1 ? ` · ${spec.corner || "typ"} corner` : ""}` : "150 kHz – 30 MHz · CISPR-16 detectors vs EN 55022 Class B"}
            right={spec && (
              <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
                <Toggle on={traces.peak}  onChange={v => setTraces(t => ({ ...t, peak: v }))}  label="PEAK"  data-action="toggle-trace-peak" />
                <Toggle on={traces.qp}    onChange={v => setTraces(t => ({ ...t, qp: v }))}    label="QP"    data-action="toggle-trace-qp" />
                <Toggle on={traces.avg}   onChange={v => setTraces(t => ({ ...t, avg: v }))}   label="AVG"   data-action="toggle-trace-avg" />
                <Toggle on={traces.limit} onChange={v => setTraces(t => ({ ...t, limit: v }))} label="LIMIT" data-action="toggle-trace-limit" />
              </div>
            )}>
        {!hasMetrics ? (
          <div className="dim mono" style={{ fontSize: "var(--t-xs)" }}>Run in <b>local-run</b> mode (real LTspice) to compute the detector spectrum.</div>
        ) : specLoading ? (
          <div className="dim mono" style={{ fontSize: "var(--t-xs)" }}>Computing detector sweep across CISPR band B… (a few seconds on first load; cached afterward)</div>
        ) : spec ? (
          <SpectrumChart points={spec.points} traces={traces} worst={spec.worst_qp} />
        ) : (
          <div className="dim mono" style={{ fontSize: "var(--t-xs)" }}>{specNote || "spectrum unavailable"}</div>
        )}
        <div className="dim mono" style={{ marginTop: 10, fontSize: "var(--t-2xs)", borderTop: "1px solid var(--border)", paddingTop: 8 }}>
          QP/AVG are the receiver-like detector readings; the dashed lines are the EN 55022 Class B limits. The worst-margin numbers above are read off these curves (reading − limit; <b>+ = over</b>). Pre-compliance estimate, not a CISPR-16 measurement.
        </div>
      </Card>

      {/* Corner-variant ranking */}
      <div style={{ marginTop: 16 }}>
        <Card title="Corner-variant ranking" sub={`ranked by ${view?.rank_metric || "band peak"} · higher = worse`}>
          {!hasMetrics ? (
            <div className="dim" style={{ fontFamily: "var(--font-mono)", fontSize: "var(--t-xs)" }}>
              No variant metrics yet — run the pipeline in local-run mode and the ranking populates here.
            </div>
          ) : (
            <table className="table" style={{ marginTop: -4 }}>
              <thead>
                <tr>
                  <th>#</th><th>Variant</th>
                  <th className="num">Peak (dBµV)</th>
                  <th className="num">Δ vs baseline</th>
                  <th className="num">QP margin</th>
                  <th className="num">@ Frequency</th>
                </tr>
              </thead>
              <tbody data-bind="variant-ranking">
                {ranking.map(r => (
                  <tr key={r.label}
                      data-action="select-variant" data-variant={r.label}
                      className={activeVariant === r.label ? "selected" : ""}
                      onClick={() => setActiveVariant(r.label)} style={{ cursor: "pointer" }}>
                    <td className="mono dim">{r.rank}</td>
                    <td><b style={{ color: activeVariant === r.label ? "var(--accent)" : "var(--text)"}}>{r.label}</b></td>
                    <td className="num tnum">{typeof r.peak_dbuv === "number" ? r.peak_dbuv.toFixed(2) : "—"}</td>
                    <td className="num tnum dim">{typeof r.delta === "number" ? `${r.delta >= 0 ? "+" : ""}${r.delta.toFixed(3)}` : "—"}</td>
                    <td className="num tnum" style={{ color: typeof r.margin_db === "number" && r.margin_db < 0 ? "var(--sev-high)" : "var(--sev-low)"}}>{db(r.margin_db)}</td>
                    <td className="num mono">{typeof r.margin_hz === "number" ? window.fmt.hz(r.margin_hz) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <div style={{ marginTop: 16 }}>
        <PreComplianceDisclaimer />
      </div>
    </div>
  );
};

// Detector-vs-limit spectrum chart (log frequency × dBµV), drawn from the
// real Mode-3 sweep points returned by api.load_spectrum.
const SpectrumChart = ({ points, traces, worst, height = 300 }) => {
  const W = 760, H = height, ML = 46, MR = 14, MT = 16, MB = 30;
  const pw = W - ML - MR, ph = H - MT - MB;
  const pts = (points || []).filter(p => typeof p.hz === "number" && p.hz > 0);
  if (pts.length < 2) return <div className="dim mono" style={{ fontSize: "var(--t-xs)" }}>not enough spectrum points</div>;
  const fmin = pts[0].hz, fmax = pts[pts.length - 1].hz;
  const lspan = Math.log10(fmax) - Math.log10(fmin) || 1;
  const lx = (hz) => ML + (Math.log10(hz) - Math.log10(fmin)) / lspan * pw;

  const vals = [];
  for (const p of pts) {
    if (traces.peak && typeof p.peak === "number") vals.push(p.peak);
    if (traces.qp && typeof p.qp === "number") vals.push(p.qp);
    if (traces.avg && typeof p.avg === "number") vals.push(p.avg);
    if (traces.limit) { if (typeof p.qp_limit === "number") vals.push(p.qp_limit); if (typeof p.avg_limit === "number") vals.push(p.avg_limit); }
  }
  let ymin = vals.length ? Math.min(...vals) : 0, ymax = vals.length ? Math.max(...vals) : 100;
  ymin = Math.floor((ymin - 5) / 10) * 10; ymax = Math.ceil((ymax + 5) / 10) * 10;
  const yspan = (ymax - ymin) || 1;
  const ly = (v) => MT + (1 - (v - ymin) / yspan) * ph;
  const path = (key) => pts.map((p, i) => (typeof p[key] === "number" ? `${i ? "L" : "M"}${lx(p.hz).toFixed(1)} ${ly(p[key]).toFixed(1)}` : "")).join(" ");

  const decades = [];
  for (let d = Math.ceil(Math.log10(fmin)); d <= Math.floor(Math.log10(fmax)); d++) decades.push(Math.pow(10, d));
  const yticks = []; for (let v = ymin; v <= ymax; v += 20) yticks.push(v);
  const C = { peak: "var(--text-faint)", qp: "var(--accent)", avg: "oklch(0.78 0.12 230)", lim: "var(--sev-high)" };
  const wp = worst && typeof worst.hz === "number"
    ? pts.reduce((a, b) => Math.abs(b.hz - worst.hz) < Math.abs(a.hz - worst.hz) ? b : a, pts[0]) : null;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height, display: "block" }}>
      {yticks.map(v => (
        <g key={`y${v}`}>
          <line x1={ML} y1={ly(v)} x2={W - MR} y2={ly(v)} stroke="var(--border)" strokeWidth="0.5" />
          <text x={ML - 6} y={ly(v) + 3} textAnchor="end" className="mono" style={{ fontSize: 9, fill: "var(--text-faint)" }}>{v}</text>
        </g>
      ))}
      {decades.map(f => (
        <g key={`x${f}`}>
          <line x1={lx(f)} y1={MT} x2={lx(f)} y2={MT + ph} stroke="var(--border)" strokeWidth="0.5" />
          <text x={lx(f)} y={H - 10} textAnchor="middle" className="mono" style={{ fontSize: 9, fill: "var(--text-faint)" }}>{window.fmt.hz(f)}</text>
        </g>
      ))}
      <text x={12} y={MT + ph / 2} transform={`rotate(-90 12 ${MT + ph / 2})`} textAnchor="middle" className="mono" style={{ fontSize: 9, fill: "var(--text-faint)" }}>dBµV</text>

      {traces.limit && <path d={path("qp_limit")} fill="none" stroke={C.lim} strokeWidth="1.2" strokeDasharray="5 3" />}
      {traces.limit && <path d={path("avg_limit")} fill="none" stroke="var(--sev-med)" strokeWidth="1" strokeDasharray="3 3" />}
      {traces.peak && <path d={path("peak")} fill="none" stroke={C.peak} strokeWidth="1" />}
      {traces.avg && <path d={path("avg")} fill="none" stroke={C.avg} strokeWidth="1.3" />}
      {traces.qp && <path d={path("qp")} fill="none" stroke={C.qp} strokeWidth="1.6" />}

      {wp && traces.qp && (
        <g>
          <circle cx={lx(wp.hz)} cy={ly(wp.qp)} r="3.5" fill="none" stroke={C.lim} strokeWidth="1.5" />
          <text x={lx(wp.hz)} y={ly(wp.qp) - 8} textAnchor="middle" className="mono" style={{ fontSize: 9, fill: C.lim }}>
            {worst.margin_db >= 0 ? `+${worst.margin_db.toFixed(1)}` : worst.margin_db.toFixed(1)} dB
          </text>
        </g>
      )}

      <g transform={`translate(${ML + 6}, ${MT})`}>
        {[["QP", C.qp], ["AVG", C.avg], ["limit", C.lim]].map((l, i) => (
          <g key={l[0]} transform={`translate(${i * 64}, 0)`}>
            <line x1={0} y1={5} x2={14} y2={5} stroke={l[1]} strokeWidth="2" />
            <text x={18} y={8} className="mono" style={{ fontSize: 9, fill: "var(--text-muted)" }}>{l[0]}</text>
          </g>
        ))}
      </g>
    </svg>
  );
};

// Time-domain waveform chart (linear time × volts). Draws the min/max
// envelope returned by api.load_waveform as a filled band — the actual
// signal the detectors / FFT are computed from.
const WaveformChart = ({ points, tMin, tMax, unit = "V", showXAxis = true, height = 200 }) => {
  const W = 760, H = height, ML = 52, MR = 14, MT = 14, MB = showXAxis ? 30 : 12;
  const pw = W - ML - MR, ph = H - MT - MB;
  const pts = (points || []).filter(p => typeof p.t === "number" && typeof p.lo === "number" && typeof p.hi === "number");
  if (pts.length < 2) return <div className="dim mono" style={{ fontSize: "var(--t-xs)" }}>not enough waveform points</div>;
  const t0 = typeof tMin === "number" ? tMin : pts[0].t;
  const t1 = typeof tMax === "number" ? tMax : pts[pts.length - 1].t;
  const tspan = (t1 - t0) || 1;
  const tx = (t) => ML + (t - t0) / tspan * pw;

  let ymin = Math.min(...pts.map(p => p.lo));
  let ymax = Math.max(...pts.map(p => p.hi));
  if (ymin === ymax) { ymin -= 1; ymax += 1; }
  const pad = (ymax - ymin) * 0.08;
  ymin -= pad; ymax += pad;
  const yspan = (ymax - ymin) || 1;
  const ty = (v) => MT + (1 - (v - ymin) / yspan) * ph;

  // Envelope as a closed area: top = hi L→R, bottom = lo R→L.
  const top = pts.map((p, i) => `${i ? "L" : "M"}${tx(p.t).toFixed(1)} ${ty(p.hi).toFixed(1)}`).join(" ");
  const bot = pts.slice().reverse().map(p => `L${tx(p.t).toFixed(1)} ${ty(p.lo).toFixed(1)}`).join(" ");
  const area = `${top} ${bot} Z`;
  const midLine = pts.map((p, i) => `${i ? "L" : "M"}${tx(p.t).toFixed(1)} ${ty((p.lo + p.hi) / 2).toFixed(1)}`).join(" ");

  const fmtV = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 1 ? v.toFixed(1) : v.toPrecision(2));
  const yticks = []; for (let k = 0; k <= 4; k++) yticks.push(ymin + (yspan * k) / 4);
  const xticks = []; for (let k = 0; k <= 5; k++) xticks.push(t0 + (tspan * k) / 5);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height, display: "block" }}>
      {yticks.map((v, i) => (
        <g key={`y${i}`}>
          <line x1={ML} y1={ty(v)} x2={W - MR} y2={ty(v)} stroke="var(--border)" strokeWidth="0.5" />
          <text x={ML - 6} y={ty(v) + 3} textAnchor="end" className="mono" style={{ fontSize: 9, fill: "var(--text-faint)" }}>{fmtV(v)}</text>
        </g>
      ))}
      {xticks.map((t, i) => (
        <g key={`x${i}`}>
          <line x1={tx(t)} y1={MT} x2={tx(t)} y2={MT + ph} stroke="var(--border)" strokeWidth="0.5" />
          {showXAxis && <text x={tx(t)} y={H - 10} textAnchor="middle" className="mono" style={{ fontSize: 9, fill: "var(--text-faint)" }}>{window.fmt.sec(t)}</text>}
        </g>
      ))}
      <text x={12} y={MT + ph / 2} transform={`rotate(-90 12 ${MT + ph / 2})`} textAnchor="middle" className="mono" style={{ fontSize: 9, fill: "var(--text-faint)" }}>{unit || "V"}</text>

      <path d={area} fill="var(--accent)" fillOpacity="0.18" stroke="none" />
      <path d={midLine} fill="none" stroke="var(--accent)" strokeWidth="1.2" />
    </svg>
  );
};

window.ResultsScreen = ResultsScreen;
