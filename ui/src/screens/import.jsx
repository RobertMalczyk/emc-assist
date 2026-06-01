import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
import { FIELD_MAP, _get, mergeContextFromFields } from "./contextMap";
// Screen: Import & context
//
// Wired to the service layer through `window.pywebview.api.*`:
//   - On mount and on project change, `api.load_context(projectRoot)`
//     populates the form (uncontrolled inputs with `defaultValue`).
//   - "Browse…" -> `api.pick_file()` + `api.set_schematic()` copies the
//     chosen schematic into `<project>/input/` and rewrites
//     `project.yaml`; the displayed filename refreshes.
//   - "Save context" walks `[data-field]` inputs in the screen, applies
//     the flat→nested mapping below, merges with the loaded context
//     (so unrelated keys — `signals`, `simulation`, `pcb`, etc. — round-
//     trip), and calls `api.save_context(projectRoot, merged)`.
//   - "Estimate parasitics →" auto-saves, then calls
//     `api.estimate_per_net(projectRoot)`, then advances.
//
// FIELD_MAP (the flat data-field -> nested user_context mapping), _get,
// and the merge logic live in ./contextMap so they can be unit-tested
// under `node --test` without a DOM. The merge deep-copies the loaded
// context and only touches mapped keys, so unrelated keys round-trip.

const ImportScreen = ({ onAdvance, currentProject, onChanged }) => {
  const api = useApi();
  const projectRoot = currentProject?.path || "";
  const inPywebview = typeof window !== "undefined" && !!window.isPywebview?.();

  const [ctx, setCtx] = useState(null);       // loaded user_context (null = loading)
  const [schematicLabel, setSchematicLabel] = useState("");
  const [loadError, setLoadError] = useState("");
  const [saveStatus, setSaveStatus] = useState("");
  const formRef = useRef(null);
  // Advanced raw user_context.json editor.
  const [rawOpen, setRawOpen] = useState(false);
  const [rawText, setRawText] = useState("");
  const [rawErr, setRawErr] = useState("");
  const [rawMsg, setRawMsg] = useState("");
  const [formNonce, setFormNonce] = useState(0);   // bumped on raw save → remount the structured form

  // Load the project's user_context.json (and remember the netlist path
  // from project.yaml for the "schematic source" card).
  const reloadContext = useCallback(async () => {
    if (!projectRoot) { setCtx({}); return; }
    setLoadError("");
    const res = await api.load_context(projectRoot);
    if (!res.ok) {
      setLoadError(res.error?.message || "could not load context");
      setCtx({});
      return;
    }
    setCtx(res.data || {});
    // Fetch the configured netlist path for the schematic-source card.
    try {
      const inputs = await api.project_inputs(projectRoot);
      if (inputs.ok) {
        setSchematicLabel(inputs.data?.netlist_path || inputs.data?.schematic_path || "");
      }
    } catch { /* tolerated — the card just shows the file we saved last */ }
  }, [projectRoot, api]);

  useEffect(() => { reloadContext(); }, [reloadContext]);

  // "Browse…" — pick a schematic file, copy it into the project, refresh.
  const onBrowseSchematic = useCallback(async () => {
    if (!projectRoot) return;
    let picked;
    if (inPywebview) {
      const res = await api.pick_file("Select schematic (.asc / .cir)");
      picked = res.ok ? res.data?.path : null;
      if (!res.ok) { setLoadError(res.error?.message || "file picker failed"); return; }
    } else {
      picked = window.prompt("Path to schematic (.asc / .cir):", "");
    }
    if (!picked) return;       // user cancelled
    const res = await api.set_schematic(projectRoot, picked);
    if (!res.ok) {
      setLoadError(res.error?.message || "could not set schematic");
      return;
    }
    setSchematicLabel(res.data?.netlist_path || "");
    setSaveStatus(res.data?.copied ? "Schematic copied" : "Schematic updated");
  }, [projectRoot, api, inPywebview]);

  // Walk [data-field] inputs in the screen, apply FIELD_MAP, merge with
  // the loaded context, and persist.
  const onSaveContext = useCallback(async () => {
    if (!projectRoot) return;
    const root = formRef.current;
    if (!root) return;
    // Collect every [data-field] input's raw value, then let the pure
    // merge helper apply the flat->nested mapping over a deep copy of the
    // loaded context (blank numbers stay unset; signal metadata survives).
    const fieldValues = {};
    root.querySelectorAll("[data-field]").forEach(el => {
      fieldValues[el.getAttribute("data-field")] = el.value;
    });
    const merged = mergeContextFromFields(ctx, fieldValues);
    const res = await api.save_context(projectRoot, merged);
    if (!res.ok) {
      setLoadError(res.error?.message || "could not save context");
      return;
    }
    setCtx(merged);
    setSaveStatus("Context saved");
    onChanged && onChanged();   // rail: context changed → refresh stage status
  }, [projectRoot, api, ctx, onChanged]);

  // "Estimate parasitics →" — save first, then estimate, then advance.
  const onEstimate = useCallback(async () => {
    if (!projectRoot) { onAdvance && onAdvance(); return; }
    await onSaveContext();
    const res = await api.estimate_per_net(projectRoot);
    if (!res.ok) {
      setLoadError(res.error?.message || "estimate-per-net failed");
      return;
    }
    onChanged && onChanged();   // rail: parasitics stage now present
    onAdvance && onAdvance();
  }, [projectRoot, api, onSaveContext, onAdvance, onChanged]);

  // Keep the raw editor in sync with the loaded context (re-pretty-print on
  // any load / save). Resets the user's in-progress raw edits — acceptable
  // since a structured save is a deliberate, separate action.
  useEffect(() => {
    if (ctx && typeof ctx === "object") {
      setRawText(JSON.stringify(ctx, null, 2));
      setRawErr(""); setRawMsg("");
    }
  }, [ctx]);

  // Parse + validate the raw JSON; returns the object or null (sets rawErr).
  const rawValidate = useCallback(() => {
    let parsed;
    try {
      parsed = JSON.parse(rawText);
    } catch (e) {
      setRawErr(String(e.message || e)); setRawMsg(""); return null;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      setRawErr("Top-level value must be a JSON object."); setRawMsg(""); return null;
    }
    setRawErr(""); setRawMsg("valid JSON object"); return parsed;
  }, [rawText]);

  const rawFormat = useCallback(() => {
    const parsed = rawValidate();
    if (parsed) setRawText(JSON.stringify(parsed, null, 2));
  }, [rawValidate]);

  const rawSave = useCallback(async () => {
    if (!projectRoot) return;
    const parsed = rawValidate();
    if (!parsed) return;
    const res = await api.save_context(projectRoot, parsed);
    if (!res.ok) { setRawErr(res.error?.message || "could not save user_context"); return; }
    setCtx(parsed);                 // re-pretty-prints + drives the structured form
    setFormNonce(n => n + 1);       // remount the form so its defaults catch up
    setRawMsg("saved to project");
    onChanged && onChanged();
  }, [projectRoot, api, rawValidate, onChanged]);

  const S = window.SAMPLE;
  const dropped = !!schematicLabel || projectRoot.length > 0;
  const schematicShortName = schematicLabel.split(/[\\/]/).pop() || (S && S.file) || "";

  // DC operating point — values come from the loaded user_context (uncontrolled).
  const dcFields = [
    { k: "input_voltage_v", label: "Input voltage", units: "V", hint: "auto from .asc" },
    { k: "output_voltage_v", label: "Output voltage", units: "V", hint: "auto" },
    { k: "load_current_a", label: "Load current", units: "A", hint: "user" },
    { k: "switching_frequency_hz", label: "Switching frequency", units: "Hz", hint: "auto" },
    { k: "cable_length_m", label: "Supply cable length", units: "m", hint: "user" },
    { k: "ambient_t_c", label: "Ambient temperature", units: "°C", hint: "user" },
  ];

  // While loading, render a stub so the inputs aren't created with empty defaults.
  if (ctx === null) {
    return (
      <div className="screen" data-screen="import-context" id="screen-import-context">
        <div className="screen-head">
          <div className="screen-title-block">
            <div className="eyebrow">Stage 1 / 7</div>
            <h1>Import schematic & context</h1>
          </div>
        </div>
        <div className="faint" style={{ padding: 24 }}>Loading project context…</div>
      </div>
    );
  }

  // The whole form is keyed by projectRoot so switching projects produces
  // a clean remount and the uncontrolled inputs pick up the new defaults.
  return (
    <div className="screen" data-screen="import-context" data-screen-label="02 Import & context" id="screen-import-context">
      <div className="screen-head">
        <div className="screen-title-block">
          <div className="eyebrow">Stage 1 / 7</div>
          <h1>Import schematic & context</h1>
          <div className="lede">Drop the LTspice <span className="mono">.asc</span>/<span className="mono">.cir</span> file and confirm the test conditions. Fields auto-fill from the schematic where possible.</div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {saveStatus && <span className="mono faint" style={{ fontSize: "var(--t-xs)" }}>{saveStatus}</span>}
          <button className="btn" data-action="save-context" onClick={onSaveContext} disabled={!projectRoot}>Save context</button>
          <button className="btn primary" data-action="estimate-per-net" onClick={onEstimate} disabled={!projectRoot}>
            Estimate parasitics →
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
      </div>
      {loadError && (
        <div className="card" style={{ padding: 12, marginBottom: 12, color: "var(--sev-high)" }}>
          <span className="mono">error:</span> {loadError}
        </div>
      )}

      <div ref={formRef} key={`${projectRoot || "no-project"}:${formNonce}`} className="grid-2" style={{ gridTemplateColumns: "1.1fr 1fr" }}>
        <div className="col">
          {/* Drop zone */}
          <Card title="Schematic source" sub={dropped ? schematicShortName : "no file"}>
            {dropped ? (
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{
                  width: 48, height: 48, borderRadius: 6,
                  background: "var(--panel-2)", border: "1px solid var(--border)",
                  display: "grid", placeItems: "center", color: "var(--accent)",
                }}>
                  <Icon name="schematic" size={22} />
                </div>
                <div style={{ flex: 1 }}>
                  <div className="mono" data-bind="schematic-filename" style={{ fontWeight: 600 }}>{schematicShortName || "(no schematic set)"}</div>
                  <div className="mono faint" data-bind="schematic-meta" style={{ fontSize: "var(--t-xs)"}}>
                    {schematicLabel || "open project.yaml to see the configured netlist"}
                  </div>
                </div>
                <button className="btn btn-sm" data-action="replace-schematic" onClick={onBrowseSchematic} disabled={!projectRoot}>Replace</button>
              </div>
            ) : (
              <div className="stripe-empty" data-action="drop-schematic" onClick={onBrowseSchematic}>
                drop <span className="mono">.asc</span> / <span className="mono">.cir</span> here, or <button className="btn btn-sm" data-action="browse-schematic" style={{ display: "inline-flex" }} onClick={e => { e.stopPropagation(); onBrowseSchematic(); }}>browse…</button>
              </div>
            )}
          </Card>

          {/* Test conditions */}
          <Card title="Test conditions" sub="dc operating point">
            <div className="grid-2">
              {dcFields.map(f => (
                <Field key={f.k} label={f.label} hint={f.hint} units={f.units}>
                  <input className="input" data-field={f.k}
                         defaultValue={_get(ctx, FIELD_MAP[f.k].path)}
                         style={{ borderRadius: "var(--radius) 0 0 var(--radius)"}}/>
                </Field>
              ))}
            </div>
          </Card>

          {/* Testbench wiring */}
          <Card title="Testbench wiring">
            <div className="grid-2">
              <Field label="Supply net">
                <input className="input" data-field="supply_net" defaultValue={_get(ctx, FIELD_MAP.supply_net.path) || "VIN"} />
              </Field>
              <Field label="Return net">
                <input className="input" data-field="return_net" defaultValue={_get(ctx, FIELD_MAP.return_net.path) || "0"} />
              </Field>
              <Field label="LISN configuration">
                <select className="input" data-field="lisn_config" defaultValue={_get(ctx, FIELD_MAP.lisn_config.path) || "dual"}>
                  <option value="dual">Dual LISN (CM/DM separable)</option>
                  <option value="single">Single LISN</option>
                </select>
              </Field>
              <Field label="Signals to track">
                <input className="input" data-field="signals_to_track"
                       defaultValue={(Array.isArray(ctx.signals) ? ctx.signals.map(s => s.name).join(", ") : "")} />
              </Field>
            </div>
          </Card>
        </div>

        <div className="col">
          {/* PCB stack-up — wired: every pcb_* field persists via FIELD_MAP in onSaveContext. */}
          <Card title="PCB stack-up" sub="affects parasitic estimates">
            <div className="grid-2">
              <Field label="Layers" units="">
                <select className="input" data-field="pcb_layers" defaultValue={String(ctx.pcb?.layers ?? "4")}><option value="4">4-layer</option><option value="2">2-layer</option><option value="6">6-layer</option></select>
              </Field>
              <Field label="Copper weight" units="oz">
                <input className="input" data-field="pcb_copper_oz" defaultValue={String(ctx.pcb?.copper_oz ?? "1")} />
              </Field>
              <Field label="Dielectric" units="mm">
                <input className="input" data-field="pcb_dielectric_mm" defaultValue={String(ctx.pcb?.dielectric_height_to_plane_mm ?? "1.6")} />
              </Field>
              <Field label="Top→GND prepreg" units="mm">
                <input className="input" data-field="pcb_prepreg_mm" defaultValue={String(ctx.pcb?.prepreg_mm ?? "0.1")} />
              </Field>
              <Field label="Trace width (power)" units="mm">
                <input className="input" data-field="pcb_trace_width_mm" defaultValue={String(ctx.pcb?.trace_width_mm ?? "0.5")} />
              </Field>
              <Field label="Trace length (typ)" units="mm">
                <input className="input" data-field="pcb_trace_length_mm" defaultValue={String(ctx.pcb?.trace_length_mm ?? "25")} />
              </Field>
            </div>

            {/* Mini stack-up visual */}
            <div style={{ marginTop: 14, background: "var(--plot-bg)", border: "1px solid var(--border)", borderRadius: 4, padding: 14 }}>
              <svg viewBox="0 0 360 92" style={{ display: "block", width: "100%" }}>
                {[
                  { y: 8, label: "L1 — signal · 1 oz", color: "oklch(0.66 0.20 25)", h: 6 },
                  { y: 22, label: "core · 8 mil FR-4", color: "oklch(0.65 0.04 80)", h: 12 },
                  { y: 40, label: "L2 — GND · 1 oz", color: "oklch(0.55 0.08 230)", h: 6 },
                  { y: 54, label: "prepreg · 4 mil", color: "oklch(0.65 0.04 80)", h: 8 },
                  { y: 68, label: "L3 — PWR · 1 oz", color: "oklch(0.66 0.20 25)", h: 6 },
                  { y: 78, label: "L4 — signal · 1 oz", color: "oklch(0.66 0.20 25)", h: 6 },
                ].map((l, i) => (
                  <g key={i}>
                    <rect x="10" y={l.y} width="220" height={l.h} fill={l.color} opacity="0.55" />
                    <text x="240" y={l.y + l.h - 1} fill="var(--text-muted)" style={{ fontFamily: "var(--font-mono)", fontSize: 9 }}>{l.label}</text>
                  </g>
                ))}
              </svg>
            </div>
          </Card>

          {/* Detected from context. Full schematic auto-parse (topology /
              switch nodes / output net) is not yet wired — those rows say
              so honestly rather than showing invented values. */}
          <Card title="Detected from context" sub="confirmed values · schematic auto-parse pending">
            <div data-bind="auto-detected" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <Row k="Return net"   bind="auto_return_net"      v={_get(ctx, FIELD_MAP.return_net.path) || "0"} confirm />
              <Row k="Supply net"   bind="auto_supply_net"      v={_get(ctx, FIELD_MAP.supply_net.path) || "—"} confirm />
              <Row k="LISN model"   bind="auto_lisn_present"    v={`${_get(ctx, FIELD_MAP.lisn_config.path) || "dual"}-LISN configured`} confirm />
              <Row k="Topology"     bind="auto_topology"        v="not yet parsed from schematic" warn />
              <Row k="Switch nodes" bind="auto_switch_nodes"    v="not yet parsed from schematic" warn />
              <Row k="Cable model"  bind="auto_cable_present"   v="not in netlist — using user value" warn />
            </div>
          </Card>

          <PreComplianceDisclaimer />
        </div>
      </div>

      {/* Advanced — raw user_context.json editor. The escape hatch for any
          field without a structured form (simulation, notes, frequency_range,
          testbench_wiring.* …). Outside formRef so the structured Save never
          collects it. */}
      <div style={{ marginTop: 16 }}>
        <Disclosure title="Advanced — edit user_context.json directly" open={rawOpen} onToggle={setRawOpen}
          summary={<span className="mono dim">the full document · for fields without a form (simulation, notes, …)</span>}
          right={rawMsg && <span className="mono" style={{ fontSize: "var(--t-xs)", color: rawMsg.startsWith("saved") ? "var(--sev-low)" : "var(--text-faint)" }}>{rawMsg}</span>}>
          <div className="mono dim" style={{ fontSize: "var(--t-2xs)", marginBottom: 8 }}>
            Direct edit of this project's <code>user_context.json</code>. Validated on save; the structured fields above are regenerated from it. JSON numbers normalise on save (e.g. <code>1.0</code> → <code>1</code>).
          </div>
          <textarea data-field="raw_user_context" spellCheck={false}
            value={rawText}
            onChange={e => { setRawText(e.target.value); setRawErr(""); setRawMsg(""); }}
            style={{ width: "100%", minHeight: 340, boxSizing: "border-box", padding: 10,
                     background: "var(--plot-bg, var(--panel-2))", color: "var(--text)",
                     border: `1px solid ${rawErr ? "var(--sev-high)" : "var(--border)"}`, borderRadius: 4,
                     fontFamily: "var(--font-mono)", fontSize: "var(--t-xs)", lineHeight: 1.5,
                     whiteSpace: "pre", overflowWrap: "normal", resize: "vertical" }} />
          {rawErr && <div className="mono" style={{ color: "var(--sev-high)", fontSize: "var(--t-xs)", marginTop: 6 }}>✗ {rawErr}</div>}
          <div style={{ display: "flex", gap: 8, marginTop: 10, justifyContent: "flex-end" }}>
            <button className="btn btn-sm ghost" data-action="raw-context-revert"
                    onClick={() => { setRawText(JSON.stringify(ctx, null, 2)); setRawErr(""); setRawMsg(""); }}>Revert</button>
            <button className="btn btn-sm" data-action="raw-context-format" onClick={rawFormat}>Format</button>
            <button className="btn btn-sm" data-action="raw-context-validate" onClick={rawValidate}>Validate</button>
            <button className="btn btn-sm primary" data-action="raw-context-save" onClick={rawSave} disabled={!projectRoot}>Save JSON</button>
          </div>
        </Disclosure>
      </div>
    </div>
  );
};

const Row = ({ k, v, bind, confirm, warn }) => (
  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", borderBottom: "1px solid var(--hairline)"}}>
    <span className="mono faint" style={{ fontSize: "var(--t-xs)"}}>{k}</span>
    <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <span className="mono" data-bind={bind}>{v}</span>
      {confirm && <Pill tone="ok" dot>auto</Pill>}
      {warn && <Pill tone="warn" dot>verify</Pill>}
    </span>
  </div>
);

window.ImportScreen = ImportScreen;
