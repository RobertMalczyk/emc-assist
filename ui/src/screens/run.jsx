import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
// Screen: Run + Simulation settings panel.

const RunScreen = ({ onAdvance, currentProject, autostart, onAutostartConsumed, onChanged }) => {
  const api = useApi();
  const projectRoot = currentProject?.path || "";
  const inPywebview = typeof window !== "undefined" && !!window.isPywebview?.();
  const [mode, setMode] = useState("local-run");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [stage, setStage] = useState(0);              // current pipeline stage (1..6), parsed from the live log
  const [logLines, setLogLines] = useState([]);
  const [done, setDone] = useState(false);
  const [runError, setRunError] = useState("");
  const [simChecks, setSimChecks] = useState(null);   // backend sim-setup assessment
  const [simLoaded, setSimLoaded] = useState(false);  // settings loaded from project
  const [hasRaw, setHasRaw] = useState(false);        // project uses a raw .tran override
  const [saveMsg, setSaveMsg] = useState("");

  // Sim settings state (defaults; replaced by the project's saved settings
  // on load via api.load_simulation_settings).
  const [sim, setSim] = useState({
    stopTime: 5e-3,
    maxTimestep: 100e-9,
    dataStart: 1e-3,
    rampStart: true,
    method: "trap",
    reltol: 1e-3,
    abstol: 1e-9,
    vntol: 1e-6,
    gmin: 1e-12,
    cshunt: 0,
    cornerSweep: true,
  });

  // Live feedback derived from sim
  const nyquist = 1 / (2 * sim.maxTimestep);
  const covers30M = nyquist >= 30e6;
  const points = Math.ceil(sim.stopTime / sim.maxTimestep);
  const sizeMB = (points * 8 * 6) / (1024 * 1024); // rough: 6 doubles per point
  const ts = () => new Date().toTimeString().slice(0, 8);

  // Real pipeline stages — 1:1 with the backend's "[pipeline] N/6 …" log lines.
  const STAGE_DEFS = [
    { n: 1, label: "Estimate parasitics" },
    { n: 2, label: "Compose testbench" },
    { n: 3, label: "Generate variants" },
    { n: 4, label: "Simulate variants" },
    { n: 5, label: "Single testbench run" },
    { n: 6, label: "Report + agents" },
  ];
  const stageStatus = (s) => {
    if (done) return "done";
    if (!running) return "idle";
    if (stage > s.n) return "done";
    if (stage === s.n) return "active";
    return "queued";
  };
  // Progress derived from the real stage — stays < 100 while the (slow,
  // LLM-heavy) report stage runs, and only hits 100 when run_pipeline returns
  // (the backend logs "6/6" the instant the report stage *starts*).
  const progress = done ? 100 : running ? Math.min(Math.round((stage / 6) * 100), 90) : 0;
  const currentStageLabel = done
    ? "complete"
    : running
      ? (STAGE_DEFS.find(s => stageStatus(s) === "active")?.label || "starting…")
      : "idle";

  // Stream the backend logging seam into the live log. The pywebview
  // shell's _pump_log drains records to window.appLog(record) every
  // 0.2 s; we render them and derive progress from the pipeline's own
  // "[pipeline] N/6 …" stage lines. Only mounted while on the Run screen.
  useEffect(() => {
    const LVL = { WARNING: "WARN", ERROR: "ERR", CRITICAL: "ERR" };
    const toLine = (rec) => ({
      ts: (rec.timestamp || "").slice(11, 19) || ts(),
      lvl: LVL[rec.level] || rec.level || "INFO",
      comp: rec.component || "",
      msg: (rec && rec.message) || "",
    });
    // The pywebview shell streams a *batch* of records per tick (one
    // evaluate_js, rate-capped) — append them in ONE setState and derive
    // progress from the last "[pipeline] N/6" line in the batch.
    window.appLogBatch = (recs) => {
      if (!Array.isArray(recs) || recs.length === 0) return;
      const lines = recs.map(toLine);
      for (const l of lines) {
        const m = l.msg.match(/\[pipeline\]\s*(\d)\/6/);
        if (m) setStage(prev => Math.max(prev, parseInt(m[1], 10)));
      }
      setLogLines(l => [...l, ...lines].slice(-400));
    };
    window.appLog = (rec) => window.appLogBatch([rec]);   // back-compat
    return () => { window.appLog = undefined; window.appLogBatch = undefined; };
  }, []);

  // Proposed settings → backend payload (user_context.simulation shape).
  // Times are sent as plain seconds-strings (SPICE-parseable); the panel
  // edits them as ms/ns for display.
  const overridesFromSim = useCallback((s) => ({
    stop_time: String(s.stopTime),
    max_timestep: String(s.maxTimestep),
    record_start: String(s.dataStart),
    startup: !!s.rampStart,
    integration_method: s.method === "gear" ? "gear" : "trap",
    options: {
      reltol: String(s.reltol), abstol: String(s.abstol),
      vntol: String(s.vntol), gmin: String(s.gmin),
      ...(Number(s.cshunt) > 0 ? { cshunt: String(s.cshunt) } : {}),
    },
  }), []);

  // Load the project's saved simulation settings into the panel on mount.
  useEffect(() => {
    let cancelled = false;
    if (!projectRoot) { setSimLoaded(false); return; }
    (async () => {
      const res = await api.load_simulation_settings(projectRoot);
      if (cancelled || !res.ok || !res.data) { setSimLoaded(true); return; }
      const d = res.data, e = d.effective || {};
      const num = (v, dflt) => (Number.isFinite(Number(v)) ? Number(v) : dflt);
      setSim(s => ({
        ...s,
        stopTime: num(e.stop_s, s.stopTime),
        maxTimestep: num(e.max_timestep_s, s.maxTimestep),
        dataStart: num(e.record_start_s, s.dataStart),
        rampStart: !!d.startup,
        method: d.integration_method === "gear" ? "gear" : "trap",
        reltol: num(d.options?.reltol, s.reltol),
        abstol: num(d.options?.abstol, s.abstol),
        vntol: num(d.options?.vntol, s.vntol),
        gmin: num(d.options?.gmin, s.gmin),
      }));
      setHasRaw(!!d.has_raw_directive);
      setSimLoaded(true);
    })();
    return () => { cancelled = true; };
  }, [projectRoot, api]);

  // Review-before-apply: re-assess the *proposed* settings as the user
  // edits (debounced). The deterministic check is instant + free.
  useEffect(() => {
    if (!projectRoot || !simLoaded) return;
    let cancelled = false;
    const t = setTimeout(async () => {
      const res = await api.assess_simulation(projectRoot, overridesFromSim(sim));
      if (!cancelled && res.ok) setSimChecks(res.data);
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [projectRoot, api, simLoaded, sim, overridesFromSim]);

  // Persist the panel's settings to user_context.simulation (validated
  // backend-side). Marks downstream stale.
  const saveSim = useCallback(async () => {
    if (!projectRoot) return;
    setSaveMsg("saving…"); setRunError("");
    const res = await api.save_simulation_settings(projectRoot, overridesFromSim(sim));
    if (!res.ok) { setSaveMsg(""); setRunError(res.error?.message || "could not save simulation settings"); return; }
    setHasRaw(!!res.data?.has_raw_directive);
    setSaveMsg("saved to project");
    onChanged && onChanged();
  }, [projectRoot, api, sim, overridesFromSim, onChanged]);

  const resetSim = useCallback(() => {
    setSim(s => ({ ...s, stopTime: 5e-3, maxTimestep: 100e-9, dataStart: 1e-3, rampStart: true,
                   method: "trap", reltol: 1e-3, abstol: 1e-9, vntol: 1e-6, gmin: 1e-12, cshunt: 0 }));
    setSaveMsg("");
  }, []);

  // Fill in the validator's recommended Δt / stop / record-start.
  const applyRecommended = useCallback(() => {
    setSim(s => ({
      ...s,
      maxTimestep: Number.isFinite(simChecks?.recommended_max_timestep_s) ? simChecks.recommended_max_timestep_s : s.maxTimestep,
      stopTime: Number.isFinite(simChecks?.recommended_stop_time_s) ? simChecks.recommended_stop_time_s : s.stopTime,
      dataStart: Number.isFinite(simChecks?.recommended_record_start_s) ? simChecks.recommended_record_start_s : s.dataStart,
    }));
  }, [simChecks]);

  // Real run — one run_pipeline call (pywebview runs it off the UI thread,
  // so the window stays responsive and the live log streams meanwhile).
  const startRun = useCallback(async () => {
    if (!projectRoot) { setRunError("No project — open one from Projects first."); return; }
    setRunning(true); setDone(false); setStage(0); setRunError("");
    setLogLines([{ ts: ts(), lvl: "INFO", comp: "pipeline", msg: `run_pipeline(mode=${mode}) starting…` }]);
    const res = await api.run_pipeline(projectRoot, {
      mode, accept_wiring: true, accept_signals: true, accept_parasitics: true, html: true,
    });
    setRunning(false);
    if (!res.ok) {
      setRunError(res.error?.message || "run failed");
      setLogLines(l => [...l, { ts: ts(), lvl: "ERR", comp: "pipeline", msg: res.error?.message || "run failed" }]);
      return;
    }
    setStage(6); setDone(true);
    setLogLines(l => [...l, { ts: ts(), lvl: "OK", comp: "pipeline", msg: "pipeline complete · results ready" }]);
    onChanged && onChanged();   // rail: simulation/findings/report now present → unlock Results
  }, [projectRoot, api, mode, onChanged]);

  // Cooperative cancel — the pipeline aborts after its current stage.
  const cancelRun = useCallback(async () => {
    await api.cancel_run();
    setLogLines(l => [...l, { ts: ts(), lvl: "WARN", comp: "pipeline", msg: "cancel requested — stopping after the current stage…" }]);
  }, [api]);

  // Auto-start when arriving via the Testbench "Continue to run →" button.
  // Fires once; clears the app-level flag immediately so it never re-triggers.
  const autostartedRef = useRef(false);
  useEffect(() => {
    if (autostart && projectRoot && !autostartedRef.current) {
      autostartedRef.current = true;
      onAutostartConsumed && onAutostartConsumed();
      startRun();
    }
  }, [autostart, projectRoot, startRun, onAutostartConsumed]);

  return (
    <div className="screen" data-screen="run" data-screen-label="05 Run" id="screen-run">
      <div className="screen-head">
        <div className="screen-title-block">
          <div className="eyebrow">Stage 4 / 7</div>
          <h1>Run simulation</h1>
          <div className="lede">Local LTspice invocation over the composed testbench, with a corner-variant sweep across min/typ/max parasitics. The full pipeline writes <span className="mono">results/</span> on success.</div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <Segmented value={mode} options={[
            { value: "dry-run", label: "DRY-RUN" },
            { value: "local-run", label: "LOCAL-RUN" },
          ]} onChange={setMode} data-action="set-run-mode" data-field="run_mode" />
          <button className="btn primary btn-lg" data-action="run-pipeline" onClick={startRun} disabled={running || !projectRoot}>
            <Icon name="play" /> {running ? "Running…" : "Run pipeline"}
          </button>
          {running && (
            <button className="btn btn-lg" data-action="cancel-run" onClick={cancelRun}>Cancel</button>
          )}
        </div>
      </div>

      <div className="faint mono" style={{ fontSize: "var(--t-xs)", marginBottom: 8 }}>
        bridge:{" "}
        <span style={{ color: inPywebview ? "var(--sev-low)" : "var(--sev-med)" }}>
          {inPywebview ? "pywebview ✓ (live backend)" : "mock — browser dev (no real backend)"}
        </span>
        {projectRoot && <span> · project: <span style={{ color: "var(--text)" }}>{currentProject?.name || projectRoot}</span></span>}
        {!projectRoot && <span> · <span style={{ color: "var(--sev-med)" }}>no project — open one from Projects first</span></span>}
      </div>
      {runError && (
        <div className="card" style={{ padding: 12, marginBottom: 12, color: "var(--sev-high)" }}>
          <span className="mono">error:</span> {runError}
        </div>
      )}

      {/* Run state row */}
      <div className="grid-3" style={{ marginBottom: 16 }}>
        <Stat label="Mode" value={<span data-bind="run-mode-label">{mode === "local-run" ? "LOCAL-RUN" : "DRY-RUN"}</span>} delta={mode === "local-run" ? "calls LTspice" : "compose only"} />
        <Stat label="Stage" value={<span data-bind="run-stage">{running ? `${Math.min(stage || 1, 6)} / 6` : done ? "6 / 6" : "—"}</span>} delta={<span data-bind="run-stage-label">{currentStageLabel}</span>} tone={running ? "med" : done ? "low" : null} />
        <Stat label="Progress" value={<><span data-bind="run-progress-percent">{Math.round(progress)}</span> %</>} delta={<span data-bind="run-status">{done ? "complete" : running ? "running" : "idle"}</span>} tone={done ? "low" : running ? "med" : null} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 16 }}>
        <div className="col">
          {/* Sim settings panel */}
          <Disclosure
            open={settingsOpen}
            onToggle={setSettingsOpen}
            title="Simulation settings"
            summary={
              <span className="mono">
                Transient: 0–{(sim.stopTime * 1e3).toFixed(1)} ms, max step {(sim.maxTimestep * 1e9).toFixed(0)} ns · method {sim.method}
                {!covers30M && <span style={{ color: "var(--sev-med)", marginLeft: 10 }}>· timestep too coarse for 30 MHz</span>}
              </span>
            }
            right={<span className="mono faint" style={{ fontSize: "var(--t-xs)", color: saveMsg === "saved to project" ? "var(--sev-low)" : undefined }}>
              {saveMsg || (hasRaw ? "raw .tran override active" : "edits live-checked below")}
            </span>}
          >
            {hasRaw && (
              <div className="mono" style={{ fontSize: "var(--t-xs)", color: "var(--sev-med)", marginBottom: 10, padding: 8, background: "var(--panel-2)", border: "1px solid var(--border)", borderRadius: 4 }}>
                This project uses a raw <code>.tran</code> override (shown below as its effective values). Saving here replaces it with the structured fields — the run is unchanged unless you edit them.
              </div>
            )}
            <div className="grid-2">
              <div className="col">
                <h4 className="mono" style={{ margin: 0, fontSize: "var(--t-xs)", letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--text-faint)"}}>Transient</h4>
                <div className="grid-2">
                  <Field label="Stop time" units="ms" hint="default 5">
                    <input className="input" data-field="sim_stop_time_ms" value={(sim.stopTime * 1e3).toFixed(2)} onChange={e => setSim(s => ({...s, stopTime: parseFloat(e.target.value) * 1e-3 || s.stopTime}))} style={{ borderRadius: "var(--radius) 0 0 var(--radius)"}}/>
                  </Field>
                  <Field label="Max timestep" units="ns" hint="default 100">
                    <input className="input" data-field="sim_max_timestep_ns" value={(sim.maxTimestep * 1e9).toFixed(0)} onChange={e => setSim(s => ({...s, maxTimestep: parseFloat(e.target.value) * 1e-9 || s.maxTimestep}))} style={{ borderRadius: "var(--radius) 0 0 var(--radius)"}}/>
                  </Field>
                  <Field label="Data start" units="ms" hint="skip startup">
                    <input className="input" data-field="sim_data_start_ms" value={(sim.dataStart * 1e3).toFixed(2)} onChange={e => setSim(s => ({...s, dataStart: parseFloat(e.target.value) * 1e-3 || s.dataStart}))} style={{ borderRadius: "var(--radius) 0 0 var(--radius)"}}/>
                  </Field>
                  <div className="field">
                    <label><span>Ramp startup</span></label>
                    <div style={{ paddingTop: 6 }}><Toggle on={sim.rampStart} onChange={v => setSim(s => ({ ...s, rampStart: v }))} label={sim.rampStart ? "ENABLED" : "DISABLED"} data-action="toggle-ramp-startup" data-field="sim_ramp_startup" /></div>
                  </div>
                </div>

                {/* Live feedback */}
                <div style={{
                  marginTop: 10, padding: 10, background: "var(--panel-2)",
                  border: "1px solid var(--border)", borderRadius: 4,
                  display: "flex", flexDirection: "column", gap: 6,
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span className="mono faint">FFT Nyquist (1/2·Δt)</span>
                    <span className="mono" data-bind="sim-nyquist-hz" style={{ color: covers30M ? "var(--sev-low)" : "var(--sev-med)"}}>
                      {window.fmt.hz(nyquist)} {covers30M ? "✓ covers 30 MHz" : "⚠ below 30 MHz"}
                    </span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span className="mono faint">Estimated points</span>
                    <span className="mono tnum" data-bind="sim-cost-estimate">{points.toLocaleString()} · ~{sizeMB.toFixed(1)} MB raw</span>
                  </div>
                  {!covers30M && (
                    <div className="mono" style={{ color: "var(--sev-med)", fontSize: "var(--t-xs)", paddingTop: 6, borderTop: "1px solid var(--border)"}}>
                      ⚠ Max timestep is too coarse to reach 30 MHz. Reduce to ≤ 16.7 ns to cover the full conducted band.
                    </div>
                  )}
                </div>
              </div>

              <div className="col">
                <h4 className="mono" style={{ margin: 0, fontSize: "var(--t-xs)", letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--text-faint)"}}>Solver options</h4>
                <Field label="Integration method">
                  <select className="input" data-field="sim_method" value={sim.method} onChange={e => setSim(s => ({ ...s, method: e.target.value }))}>
                    <option value="trap">trapezoidal (default)</option>
                    <option value="gear">Gear</option>
                  </select>
                </Field>

                <Disclosure title="Tolerances" summary={<span className="mono dim">advanced — reltol/abstol/vntol</span>}>
                  <div className="grid-2">
                    <Field label="reltol" hint="default 1e-3">
                      <input className="input" data-field="sim_reltol" value={String(sim.reltol)} onChange={e => setSim(s => ({ ...s, reltol: parseFloat(e.target.value) || s.reltol }))} />
                    </Field>
                    <Field label="abstol" hint="default 1e-9">
                      <input className="input" data-field="sim_abstol" value={String(sim.abstol)} onChange={e => setSim(s => ({ ...s, abstol: parseFloat(e.target.value) || s.abstol }))} />
                    </Field>
                    <Field label="vntol" hint="default 1e-6">
                      <input className="input" data-field="sim_vntol" value={String(sim.vntol)} onChange={e => setSim(s => ({ ...s, vntol: parseFloat(e.target.value) || s.vntol }))} />
                    </Field>
                    <div style={{ display: "flex", alignItems: "end" }}>
                      <button className="btn btn-sm ghost" data-action="reset-tolerances"
                              onClick={() => setSim(s => ({ ...s, reltol: 1e-3, abstol: 1e-9, vntol: 1e-6 }))}>restore defaults</button>
                    </div>
                  </div>
                </Disclosure>

                <Disclosure title="Convergence aids" summary={<span className="mono dim">advanced — gmin, cshunt</span>}>
                  <div className="grid-2">
                    <Field label="gmin" hint="default 1e-12">
                      <input className="input" data-field="sim_gmin" value={String(sim.gmin)} onChange={e => setSim(s => ({ ...s, gmin: parseFloat(e.target.value) || s.gmin }))} />
                    </Field>
                    <Field label="cshunt" hint="optional">
                      <input className="input" data-field="sim_cshunt" value={String(sim.cshunt)} onChange={e => setSim(s => ({ ...s, cshunt: parseFloat(e.target.value) || 0 }))} />
                    </Field>
                  </div>
                </Disclosure>

                <div className="field">
                  <label><span>Corner sweep</span><span className="hint">min/typ/max parasitics</span></label>
                  <div style={{ paddingTop: 6 }}><Toggle on={sim.cornerSweep} onChange={v => setSim(s => ({ ...s, cornerSweep: v }))} label={sim.cornerSweep ? "ON · 3 runs" : "OFF · 1 run"} data-action="toggle-corner-sweep" data-field="sim_corner_sweep" /></div>
                </div>
              </div>
            </div>

            <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--border)", display: "flex", gap: 8, justifyContent: "space-between", alignItems: "center"}}>
              <span className="mono faint" style={{ fontSize: "var(--t-xs)"}}>These are engineering choices — guidance is provided, but the right answer is topology-dependent.</span>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                {saveMsg && <span className="mono" style={{ fontSize: "var(--t-xs)", color: saveMsg === "saved to project" ? "var(--sev-low)" : "var(--text-faint)" }}>{saveMsg}</span>}
                <button className="btn btn-sm primary" data-action="save-sim-defaults" onClick={saveSim} disabled={!projectRoot}>Save to project</button>
                <button className="btn btn-sm ghost" data-action="reset-sim-defaults" onClick={resetSim}>Reset all to defaults</button>
              </div>
            </div>
          </Disclosure>

          {/* Progress block */}
          <Card title="Run progress" sub={running ? "live" : done ? "complete" : "idle"} right={done ? <Pill tone="ok" dot>complete</Pill> : running ? <Pill tone="info" dot>running</Pill> : <Pill>idle</Pill>}>
            <div className="progress" data-bind="run-progress" data-progress={Math.round(progress)} style={{ height: 8, marginBottom: 14 }}>
              <div className={`fill ${running && progress < 99 ? "" : ""}`} style={{ width: `${progress}%` }} />
            </div>
            <div className="grid-3" data-bind="stage-status" style={{ gap: 8 }}>
              {STAGE_DEFS.map(s => {
                const st = stageStatus(s);
                return (
                  <div key={s.n} data-stage={s.n} data-status={st} style={{
                    padding: 10,
                    borderRadius: 4,
                    border: "1px solid var(--border)",
                    background: st === "active" ? "var(--accent-dim)" : "var(--panel-2)",
                    opacity: (st === "queued" || st === "idle") ? 0.5 : 1,
                  }}>
                    <div className="mono faint" style={{ fontSize: "var(--t-2xs)", letterSpacing: "0.12em" }}>STAGE {s.n}/6</div>
                    <div className="mono" style={{ fontSize: "var(--t-sm)", fontWeight: 600, marginTop: 3 }}>{s.label}</div>
                    <div className="mono dim" style={{ fontSize: "var(--t-xs)", marginTop: 2 }}>
                      {st === "done" ? "✓ done" : st === "active" ? "● in progress" : "queued"}
                    </div>
                  </div>
                );
              })}
            </div>
            {running && stage >= 6 && (
              <div className="mono faint" style={{ fontSize: "var(--t-xs)", marginTop: 10 }}>
                Report stage runs the LLM recommendations, agents and synthesis — with cloud LLM on this can take 1–2 min.
              </div>
            )}
          </Card>

          {done && (
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <button className="btn primary" data-action="goto-results" onClick={onAdvance}>View results →</button>
            </div>
          )}
        </div>

        <div className="col">
          {/* Live log */}
          <Card title="Live log" sub="logging seam — appLog(record)" right={<button className="btn btn-sm ghost" data-action="export-log"><Icon name="download" size={12} /> Export</button>}>
            <div className="log" id="live-log" data-bind="live-log" style={{ maxHeight: 380 }}>
              {logLines.map((l, i) => (
                <div className="line" key={i}>
                  <span className="ts">{l.ts}</span>
                  <span className={`lvl ${l.lvl}`}>{l.lvl}</span>
                  <span className="comp">{l.comp}</span>
                  <span className="msg">{l.msg}</span>
                </div>
              ))}
              {running && (
                <div className="line">
                  <span className="ts">{ts()}</span>
                  <span className="lvl INFO">INFO</span>
                  <span className="comp">pipeline</span>
                  <span className="msg">{currentStageLabel === "idle" ? "starting…" : `${currentStageLabel.toLowerCase()}…`}</span>
                </div>
              )}
            </div>
          </Card>

          {/* Pre-run sim-setup check — deterministic backend assessment of the
              project's actual .tran window/timestep (band, switching edges,
              frequency resolution). */}
          {simChecks && (() => {
            const issues = (simChecks.checks || []).filter(c => c.severity !== "ok");
            return (
              <Card title="Pre-run sim-setup check" sub="reviews your proposed settings live · Δt vs band & edges · window vs resolution"
                    right={<div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      {!simChecks.ok && (Number.isFinite(simChecks.recommended_max_timestep_s) || Number.isFinite(simChecks.recommended_stop_time_s)) && (
                        <button className="btn btn-sm" data-action="apply-recommended-sim" onClick={applyRecommended}
                                data-tip="Fill the fields with the validator's recommended Δt / stop / record-start">apply recommended</button>
                      )}
                      <Pill tone={simChecks.ok ? "ok" : "warn"} dot>{simChecks.ok ? "adequate" : `${issues.length} issue${issues.length === 1 ? "" : "s"}`}</Pill>
                    </div>}>
                <div data-bind="pre-run-warnings" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {issues.length === 0 && <div className="dim mono" style={{ fontSize: "var(--t-xs)" }}>Window & timestep look adequate for the conducted band.</div>}
                  {issues.map((c, i) => (
                    <div key={i} data-check-id={c.id} data-check-severity={c.severity} style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                      <span style={{ color: c.severity === "high" ? "var(--sev-high)" : c.severity === "medium" ? "var(--sev-med)" : "var(--text-faint)" }}><Icon name="alert" /></span>
                      <div>
                        <div className="mono" style={{ color: "var(--text)", fontSize: "var(--t-sm)" }}>{c.message}</div>
                        {c.recommendation && <div className="dim" style={{ fontSize: "var(--t-xs)", marginTop: 3, fontFamily: "var(--font-mono)" }}>→ {c.recommendation}</div>}
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            );
          })()}
        </div>
      </div>
    </div>
  );
};

window.RunScreen = RunScreen;
