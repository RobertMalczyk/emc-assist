import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
// Screen: Testbench review.
//
// Wired to real artifacts written by service.testbench.compose_testbench:
//   generated/parasitics_series.json  — series-RLC splices (count)
//   generated/parasitics_shunt.json   — shunt-C injections (count)
//   generated/parasitics_dropped.json — nets the AI negligibility screen dropped
//   generated/parasitics_wiring.json  — input-rail TRACE_RLC injection plan
//   generated/signals.json            — tracked user signals
//   generated/testbench.cir           — the composed netlist (preview)
// "Dropped by user" comes from user_context.parasitics.per_net (skip flags),
// and the diagram's net set + count from generated/parasitics_per_net.json.
// Counts therefore reflect THIS project, and the relationship to the
// selection screen is: series + shunt + dropped_user + dropped_ai <= total
// nets (the audit is the injected subset, not every net).

const TestbenchScreen = ({ onAdvance, onRun, currentProject }) => {
  const api = useApi();
  const projectRoot = currentProject?.path || "";
  const inPywebview = typeof window !== "undefined" && !!window.isPywebview?.();

  const [showAsc, setShowAsc] = useState(false);
  const [data, setData] = useState(null);   // null = loading / no project
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!projectRoot) { setData(null); return; }
      setLoadError("");
      const rd = (rel) => api.read_artifact(projectRoot, rel);
      const [perNet, series, shunt, dropped, wiring, signals, ctx, cir] = await Promise.all([
        rd("generated/parasitics_per_net.json"),
        rd("generated/parasitics_series.json"),
        rd("generated/parasitics_shunt.json"),
        rd("generated/parasitics_dropped.json"),
        rd("generated/parasitics_wiring.json"),
        rd("generated/signals.json"),
        api.load_context(projectRoot),
        rd("generated/testbench.cir"),
      ]);
      if (cancelled) return;
      const list = (r) => (r.ok && Array.isArray(r.data) ? r.data : []);
      const uc = ctx.ok ? (ctx.data || {}) : {};
      const perNetOv = (uc.parasitics && uc.parasitics.per_net) || {};
      const skipSet = new Set(
        Object.entries(perNetOv).filter(([, v]) => v && v.skip).map(([k]) => k)
      );
      const estimates = list(perNet);
      const diagramNets = estimates.map((e) => ({ net: e.net, include: !skipSet.has(e.net) }));
      const tw = uc.testbench_wiring || {};
      setData({
        composed: cir.ok,
        cir: cir.ok ? cir.data : "",
        totalNets: estimates.length,
        series: list(series).length,
        shunt: list(shunt).length,
        droppedAi: list(dropped).length,
        droppedUser: skipSet.size,
        injections: list(wiring).length,
        signals: list(signals),
        wiring: {
          supply: tw.dut_supply_net || "—",
          ret: tw.dut_return_net || "—",
          lisn: (tw.lisn_mode || "dual"),
          cable: uc.cable_length_m,
          supplyV: uc.input_voltage_v,
          loadA: uc.load_current_a,
        },
        diagramNets,
      });
    })();
    return () => { cancelled = true; };
  }, [projectRoot, api]);

  const composed = !!data?.composed;
  const diagramNets = data?.diagramNets?.length ? data.diagramNets : (window.SAMPLE ? window.SAMPLE.nets : []);

  // Parasitics audit rows — real counts, or an honest "not composed" note.
  const parasiticsRows = composed ? [
    { k: "Series RLC splices", v: `${data.series} nets`, tone: "ok" },
    { k: "Shunt-C injections", v: `${data.shunt} nets`, tone: "ok" },
    { k: "Dropped by user", v: `${data.droppedUser} nets`, tone: "info" },
    { k: "Dropped by AI", v: `${data.droppedAi} nets`, tone: "info" },
  ] : [{ k: "Testbench not composed", v: "compose first", tone: "warn" }];

  const wiringRows = composed ? [
    { k: `Supply ${data.wiring.supply} ↦ LISN`, v: "ok", tone: "ok" },
    { k: `Return ${data.wiring.ret} ↦ LISN`, v: "ok", tone: "ok" },
    { k: "Cable model", v: data.wiring.cable != null ? `${data.wiring.cable} m` : "default", tone: "ok" },
    { k: "LISN mode", v: data.wiring.lisn === "dual" ? "dual · DM+CM" : "single", tone: "ok" },
    { k: "Input-rail injection", v: `${data.injections} TRACE_RLC`, tone: data.injections ? "ok" : "info" },
  ] : [{ k: "Wiring audit", v: "compose first", tone: "warn" }];

  const signalRows = composed ? (
    data.signals.length
      ? data.signals.map((s) => ({ k: `${s.name} probe`, v: s.expr || "—", tone: "ok" }))
      : [{ k: "Tracked signals", v: "none", tone: "info" }]
  ) : [{ k: "Signal audit", v: "compose first", tone: "warn" }];

  return (
    <div className="screen" data-screen="testbench-review" data-screen-label="04 Testbench review" id="screen-testbench-review">
      <div className="screen-head">
        <div className="screen-title-block">
          <div className="eyebrow">Stage 3 / 7</div>
          <h1>Testbench review</h1>
          <div className="lede">Visual verification of the assembled testbench. <span className="mono">testbench.cir</span> + <span className="mono">.asc</span> are generated by compose; open in LTspice to inspect, or proceed to run.</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" data-action="view-testbench-asc" onClick={() => setShowAsc(s => !s)} disabled={!composed}>
            <Icon name="schematic" /> {showAsc ? "Hide" : "View"} testbench.cir
          </button>
          <button className="btn primary" data-action="goto-run" onClick={onRun || onAdvance} disabled={!composed}
                  data-tip={composed ? "Go to Run and start the simulation" : "Compose the testbench first"}>
            Continue to run →
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
        {projectRoot && !composed && <span> · <span style={{ color: "var(--sev-med)" }}>not composed yet — run Compose on the Parasitics screen</span></span>}
      </div>
      {loadError && (
        <div className="card" style={{ padding: 12, marginBottom: 12, color: "var(--sev-med)" }}>
          <span className="mono">notice:</span> {loadError}
        </div>
      )}

      <Card title="Composed testbench" sub={composed ? "testbench.cir + .asc generated" : "compose to generate"} right={<Pill tone={composed ? "ok" : "warn"} dot data-bind="testbench-status">{composed ? "composed" : "not composed"}</Pill>} flush>
        <TestbenchDiagram selectedNet={null} nets={diagramNets} onSelectNet={() => {}} height={420}
          dutSub={`${currentProject?.name || "user circuit"} · ${data?.totalNets ?? diagramNets.length} nets`}
          meta={{
            supply: data?.wiring?.supplyV != null ? `${data.wiring.supplyV} V` : undefined,
            cable: data?.wiring?.cable != null ? `${data.wiring.cable} m` : undefined,
            lisn: data?.wiring?.lisn,
            load: data?.wiring?.loadA != null ? `${data.wiring.loadA} A load` : undefined,
          }} />
      </Card>

      <div className="grid-3" style={{ marginTop: 16 }}>
        <Card title="Wiring audit" sub="parasitics_wiring.json + testbench_wiring">
          <div data-bind="wiring-audit"><AuditRows rows={wiringRows} /></div>
        </Card>
        <Card title="Parasitics audit" sub="parasitics_series + shunt + dropped">
          <div data-bind="parasitics-audit"><AuditRows rows={parasiticsRows} /></div>
        </Card>
        <Card title="Signal audit" sub="signals.json">
          <div data-bind="signal-audit"><AuditRows rows={signalRows} /></div>
        </Card>
      </div>

      {showAsc && composed && (
        <Card title="testbench.cir" sub="netlist generated by service.testbench.compose_testbench" style={{ marginTop: 16 }}>
          <pre className="mono dim" id="testbench-cir-preview" data-bind="testbench-cir" style={{
            background: "var(--plot-bg)", padding: 14, borderRadius: 4,
            fontSize: 11, lineHeight: 1.55, margin: 0,
            maxHeight: 320, overflow: "auto"
          }}>{data.cir}</pre>
        </Card>
      )}
    </div>
  );
};

const AuditRows = ({ rows }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
    {rows.map((r, i) => (
      <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "4px 0" }}>
        <span className="mono faint" style={{ fontSize: "var(--t-xs)"}}>{r.k}</span>
        <Pill tone={r.tone}>{r.v}</Pill>
      </div>
    ))}
  </div>
);

window.TestbenchScreen = TestbenchScreen;
