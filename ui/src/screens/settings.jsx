import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
// Screen: Settings.

const SettingsScreen = ({ llmEnabled, keyPresent, onToggleLLM }) => {
  const api = useApi();
  const [ltspicePath, setLtspicePath] = useState("");
  const [budgetUsd, setBudgetUsd] = useState(1.00);
  const [stripPrivate, setStripPrivate] = useState(true);

  // Prefill from the persisted app settings (~/.emc-assistant/settings.json).
  useEffect(() => {
    (async () => {
      const res = await api.load_settings();
      if (res.ok && res.data) {
        if (res.data.ltspice_path) setLtspicePath(res.data.ltspice_path);
        if (typeof res.data.llm_budget_usd === "number") setBudgetUsd(res.data.llm_budget_usd);
      }
    })();
  }, [api]);

  // Persist the budget cap on blur. The cloud-LLM opt-in is persisted by the
  // toggle's onToggleLLM (app.jsx → save_settings → re-reads key-gated status).
  const saveBudget = useCallback(async () => {
    await api.save_settings({ llm_budget_usd: Number(budgetUsd) || 0 });
  }, [api, budgetUsd]);

  return (
    <div className="screen" data-screen="settings" data-screen-label="Settings" id="screen-settings">
      <div className="screen-head">
        <div className="screen-title-block">
          <div className="eyebrow">Application</div>
          <h1>Settings</h1>
          <div className="lede">LTspice path, LLM provider & budget, privacy posture, and project-default simulation settings.</div>
        </div>
      </div>

      <div className="grid-2">
        <div className="col">
          <Card title="LTspice executable" sub="local install — never bundled">
            <Field label="Executable path">
              <input className="input" data-field="ltspice_path" value={ltspicePath} readOnly
                     placeholder="resolved from LTSPICE_PATH / auto-discovery at run time" />
            </Field>
            <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center" }}>
              <button className="btn btn-sm" data-action="browse-ltspice" data-state="coming-soon" disabled
                      data-tip="Not wired in the UI yet — set the path in ~/.emc-assistant/settings.json or the LTSPICE_PATH env var."><Icon name="folder" /> Browse…</button>
              <button className="btn btn-sm" data-action="detect-ltspice" data-state="coming-soon" disabled
                      data-tip="Not wired in the UI yet — the backend auto-discovers LTspice at run time.">Detect</button>
              <span className="mono dim" data-bind="ltspice-version" style={{ alignSelf: "center", fontSize: "var(--t-xs)"}}>
                {ltspicePath ? "from app settings" : "auto-discovered at run time"}
              </span>
            </div>
          </Card>

          <Card title="Privacy posture" sub="schematics are confidential" right={<PrivacyIndicator llmEnabled={llmEnabled} />}>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <PrivRow
                k="Cloud LLM provider"
                v={
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <Toggle on={keyPresent && llmEnabled} onChange={onToggleLLM} disabled={!keyPresent}
                            label={!keyPresent ? "NO KEY" : llmEnabled ? "ON" : "OFF"}
                            data-action="toggle-cloud-llm" data-field="llm_enabled"
                            data-tip={keyPresent ? undefined : "No API key found — add one to ~/.emc-assistant/openai_key (or set OPENAI_API_KEY) to enable cloud LLM."} />
                    <select className="input" data-field="llm_provider" defaultValue="openai" disabled={!keyPresent || !llmEnabled} style={{ width: 160 }}>
                      <option value="openai">OpenAI (gpt-5-mini)</option>
                    </select>
                  </div>
                }
              />
              <PrivRow k="Strip identifiers before send"
                       v={<Toggle on={stripPrivate} onChange={setStripPrivate} disabled label="ALWAYS STRIPPED" data-action="toggle-strip-identifiers" data-field="strip_identifiers"
                                  data-tip="Always on — outbound LLM payloads are redacted before any send (rule_id + source_id + our summary + short excerpt only); it cannot be turned off." />} />
              <PrivRow k="LLM budget cap (per run)"
                       v={<div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                         <input className="input" data-field="llm_budget_usd" style={{ width: 100 }} value={budgetUsd.toFixed(2)} onChange={e => setBudgetUsd(parseFloat(e.target.value) || 0)} onBlur={saveBudget} />
                         <span className="mono faint">USD</span>
                         <span className="mono dim" data-bind="llm-usage-month-usd" data-tip="The per-run cap is enforced by the budget tracker; cross-run monthly aggregation isn't tracked yet." style={{ fontSize: "var(--t-xs)"}}>per run · monthly total not tracked</span>
                       </div>} />
              <PrivRow k="Telemetry"
                       v={<Toggle on={false} disabled label="NONE" data-action="toggle-telemetry" data-field="telemetry_enabled"
                                  data-tip="This local tool collects no telemetry." />} />
            </div>
            <div className="disclaimer" style={{ marginTop: 16 }}>
              <span className="icon"><Icon name="lock" /></span>
              <span>
                <b>Privacy posture:</b> with cloud LLM <b>off</b>, this machine never sends netlist content over the network. With it <b>on</b>, only redacted, structured payloads are sent — every payload is logged to <span className="mono">results/llm/*.jsonl</span>.
              </span>
            </div>
          </Card>
        </div>

        <div className="col">
          <Card title="Project-default simulation settings" sub="per-project settings live on the Run screen">
            <div className="mono dim" style={{ fontSize: "var(--t-xs)", lineHeight: 1.6, marginBottom: 12 }}>
              App-level simulation defaults aren't stored yet. Each project's
              <code> .tran</code> / solver settings are edited (with a
              review-before-apply check) on the <b>Run</b> screen and saved into
              that project's <code>user_context.simulation</code>. The fields
              below are illustrative — not yet wired.
            </div>
            <div className="grid-2">
              <Field label="Stop time" units="ms"><input className="input" data-field="default_stop_time_ms" defaultValue="5.00" disabled /></Field>
              <Field label="Max timestep" units="ns"><input className="input" data-field="default_max_timestep_ns" defaultValue="100" disabled /></Field>
              <Field label="Integration method"><select className="input" data-field="default_method" disabled><option value="trap">trapezoidal</option><option value="gear">Gear</option></select></Field>
              <Field label="Corner sweep"><div style={{ paddingTop: 6 }}><Toggle on={true} disabled label="ENABLED" data-action="toggle-default-corner-sweep" data-field="default_corner_sweep" data-tip="Corner sweep is on by default; per-project control isn't surfaced here yet." /></div></Field>
            </div>
          </Card>

          <Card title="Knowledge sources" sub="embedded EMC knowledge base">
            <div data-bind="knowledge-sources-list" className="mono dim" style={{ fontSize: "var(--t-xs)", lineHeight: 1.6 }}>
              The app ships a pre-built, embedded knowledge index (curated EMC
              seed rules + application-note summaries). Per-source management
              isn't surfaced in the UI yet — the index is maintained from the
              <code> knowledge/</code> directory and the CLI.
            </div>
            <div style={{ marginTop: 12 }}>
              <button className="btn btn-sm" data-action="add-knowledge-source" data-state="coming-soon" disabled
                      data-tip="Knowledge-source management isn't in the UI yet — add sources under the knowledge/ directory."><Icon name="plus" /> Add source</button>
              <button className="btn btn-sm ghost" data-action="rebuild-knowledge-index" data-state="coming-soon" disabled
                      data-tip="Index rebuild isn't wired in the UI yet — use the CLI." style={{ marginLeft: 6 }}>Rebuild index</button>
            </div>
          </Card>

          <Card title="About">
            <div data-bind="about" style={{ display: "flex", flexDirection: "column", gap: 4, fontFamily: "var(--font-mono)", fontSize: "var(--t-xs)" }}>
              <Kv2 k="Stage" v="M3 — light UI (in development)" />
              <Kv2 k="Build" v="local source build" />
              <Kv2 k="Backend" v="emc_assistant.service" />
              <Kv2 k="Shell" v="pywebview + WebView2" />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};

const PrivRow = ({ k, v }) => (
  <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 12, alignItems: "center", padding: "4px 0", borderBottom: "1px solid var(--hairline)"}}>
    <span className="mono faint" style={{ fontSize: "var(--t-xs)"}}>{k}</span>
    <div>{v}</div>
  </div>
);

const Kv2 = ({ k, v }) => (
  <div style={{ display: "grid", gridTemplateColumns: "100px 1fr", gap: 12 }}>
    <span className="faint">{k}</span>
    <span style={{ color: "var(--text-dim)"}}>{v}</span>
  </div>
);

window.SettingsScreen = SettingsScreen;
