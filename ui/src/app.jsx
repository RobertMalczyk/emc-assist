import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
import * as ReactDOM from "react-dom/client";
// Main app: rail + topbar + screen router + tweaks.

const SCREENS = window.STAGE_ORDER; // pipeline screen ids

// Backend project_status stage names -> UI screen ids.
const BACKEND_STAGE_TO_UI = {
  context: "import", parasitics: "parasitics", testbench: "testbench",
  simulation: "run", findings: "findings", report: "report",
};

// project_status payload -> { <uiStage>: {present, stale} } (or null).
function _uiStageStatus(status) {
  if (!status || !Array.isArray(status.stages)) return null;
  const map = {};
  for (const s of status.stages) {
    const ui = BACKEND_STAGE_TO_UI[s.stage];
    if (ui) map[ui] = { present: !!s.present, stale: !!s.stale };
  }
  if (map.run) map.results = map.run;   // the Results view reads the simulation output
  return map;
}
// Shared with the Projects screen (runtime ref via globalThis).
window._uiStageStatus = _uiStageStatus;

const App = () => {
  const api = useApi();
  // Tweaks
  const [t, setTweak] = useTweaks(window.__TWEAK_DEFAULTS__);

  // Active screen
  const [screen, setScreen] = useState("projects");
  // Real per-stage backend state (Api.project_status); null in browser dev /
  // before a project is open, where the tweak-driven fallback gating runs.
  const [projStatus, setProjStatus] = useState(null);
  // Tweak-driven fallback pipeline stage (browser-dev only).
  const [pipelineStage, setPipelineStage] = useState(t.pipelineStage || "results");
  const [llmEnabled, setLLMEnabled] = useState(false);
  const [llmKeyPresent, setLlmKeyPresent] = useState(false);
  const [currentProject, setCurrentProject] = useState(null);
  // Set when "Continue to run →" (Testbench) wants the Run screen to start
  // the run on arrival; the Run screen consumes + clears it.
  const [autoRun, setAutoRun] = useState(false);
  // pywebview injects window.pywebview.api asynchronously after load. Track
  // readiness so render-time `isPywebview()` checks (bridge chip, rail
  // gating) and the settings load below correct themselves once the bridge
  // appears — without the user having to navigate away and back.
  const [bridgeReady, setBridgeReady] = useState(
    () => typeof window !== "undefined" && !!(window.pywebview && window.pywebview.api)
  );
  useEffect(() => {
    if (bridgeReady) return;
    const check = () => {
      if (window.pywebview && window.pywebview.api) setBridgeReady(true);
    };
    window.addEventListener("pywebviewready", check);
    const t = setInterval(check, 200);   // in case the event fired pre-mount
    return () => { window.removeEventListener("pywebviewready", check); clearInterval(t); };
  }, [bridgeReady]);

  // Apply tweaks to document attributes
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", t.theme);
    document.documentElement.setAttribute("data-density", t.density);
    document.documentElement.setAttribute("data-severity", t.severity);
    document.documentElement.style.setProperty("--accent-h", t.accentHue);
    document.documentElement.style.setProperty("--rail-w", `${t.railWidth}px`);
  }, [t.theme, t.density, t.severity, t.accentHue, t.railWidth]);

  // Keep pipelineStage in sync with tweaks
  useEffect(() => { if (t.pipelineStage) setPipelineStage(t.pipelineStage); }, [t.pipelineStage]);

  // Cloud-LLM state for the indicators: the user's opt-in (`enabled`) AND
  // whether an API key resolves (`key_present`). `llmActive` (= both) is what
  // the privacy indicator and the parasitics AI button gate on — "key → on,
  // otherwise off". See Api.llm_status.
  const refreshLlmStatus = useCallback(async () => {
    const res = await api.llm_status();
    if (res.ok && res.data) {
      setLLMEnabled(!!res.data.enabled);
      setLlmKeyPresent(!!res.data.key_present);
    }
  }, [api]);
  useEffect(() => { refreshLlmStatus(); }, [refreshLlmStatus, bridgeReady]);

  // Toggle cloud LLM: persist the opt-in, then re-read status so the
  // indicator reflects the key-gated effective state.
  const onToggleLLM = useCallback(async (next) => {
    const res = await api.save_settings({ cloud_llm_enabled: !!next });
    if (res.ok) await refreshLlmStatus();
  }, [api, refreshLlmStatus]);

  const llmActive = llmEnabled && llmKeyPresent;

  // Helpers: navigate / advance
  const goto = (s) => setScreen(s);
  const advance = () => {
    const idx = SCREENS.indexOf(screen);
    if (idx >= 0 && idx < SCREENS.length - 1) {
      const next = SCREENS[idx + 1];
      // unlock that stage if reached
      const curIdx = SCREENS.indexOf(pipelineStage);
      if (idx + 1 > curIdx) {
        setPipelineStage(next);
        setTweak("pipelineStage", next);
      }
      setScreen(next);
    }
  };
  // Testbench "Continue to run →": advance to the Run stage AND ask it to
  // start the run on arrival (so the button actually runs, not just navigates).
  const goRun = () => { setAutoRun(true); advance(); };

  // Backend project state — drives the rail gating + resume-at-stage.
  // Refreshes whenever the project or active screen changes, so the rail
  // reflects the latest after each screen's action (estimate / compose / run).
  const refreshStatus = useCallback(async () => {
    if (!currentProject?.path) { setProjStatus(null); return; }
    const res = await api.project_status(currentProject.path);
    setProjStatus(res.ok ? _uiStageStatus(res.data) : null);
  }, [api, currentProject]);
  useEffect(() => { refreshStatus(); }, [refreshStatus, screen]);

  // Open a project → load its status, resume at the furthest completed stage.
  const openProject = useCallback(async (p) => {
    setCurrentProject(p);
    const res = await api.project_status(p.path);
    const ui = res.ok ? _uiStageStatus(res.data) : null;
    setProjStatus(ui);
    let target = "import";
    if (ui) { for (const s of SCREENS) { if (ui[s]?.present) target = s; } }
    setScreen(target);
  }, [api]);

  // New project → pick a folder, create the .emcproj skeleton, open it.
  const onCreateProject = useCallback(async () => {
    let dir;
    if (window.isPywebview?.()) {
      const res = await api.pick_folder("Choose an empty folder for the new project");
      dir = res.ok ? res.data?.path : null;
    } else {
      dir = window.prompt("New project folder path:", "");
    }
    if (!dir) return;
    const res = await api.create_project(dir);
    if (!res.ok) { window.alert?.(res.error?.message || "Could not create project"); return; }
    setCurrentProject({ name: res.data.project_id, path: res.data.root });
    setProjStatus(null);
    setScreen("import");
  }, [api]);

  // Tier-2 rail gating. Backend-driven when project_status is loaded:
  //   present + !stale -> done · present + stale -> stale ·
  //   reachable (all earlier present) -> active/null · else locked.
  // Falls back to the tweak-driven index gating for browser dev / no project.
  const stageState = (stageId) => {
    if (projStatus) {
      const idx = SCREENS.indexOf(stageId);
      const st = projStatus[stageId];
      if (st?.present) return st.stale ? "stale" : "done";
      const earlierPresent = SCREENS.slice(0, idx).every(s => projStatus[s]?.present);
      return (idx === 0 || earlierPresent) ? null : "locked";
    }
    // No backend status. In the real shell that means no project is open
    // (or its status couldn't load) → the analysis tier is inert.
    if (window.isPywebview?.()) return "locked";
    // Browser dev: tweak-driven gating so the design stays reviewable.
    const i = SCREENS.indexOf(stageId);
    const ci = SCREENS.indexOf(pipelineStage);
    if (i <= ci) return i < ci ? "done" : null;
    return "locked";
  };

  // Render the right screen
  const renderScreen = () => {
    switch (screen) {
      case "projects":   return <ProjectsScreen onOpenProject={openProject} onCreate={onCreateProject} />;
      case "import":     return <ImportScreen onAdvance={advance} currentProject={currentProject} onChanged={refreshStatus} />;
      case "parasitics": return <ParasiticSelectionScreen tweaks={t} onAdvance={advance} currentProject={currentProject} llmActive={llmActive} onChanged={refreshStatus} />;
      case "testbench":  return <TestbenchScreen onAdvance={advance} onRun={goRun} currentProject={currentProject} />;
      case "run":        return <RunScreen onAdvance={advance} currentProject={currentProject} autostart={autoRun} onAutostartConsumed={() => setAutoRun(false)} onChanged={refreshStatus} />;
      case "results":    return <ResultsScreen onAdvance={advance} currentProject={currentProject} stale={!!projStatus?.results?.stale} onRerun={() => goto("run")} />;
      case "findings":   return <FindingsScreen onAdvance={advance} currentProject={currentProject} onChanged={refreshStatus} stale={!!projStatus?.findings?.stale} onRerun={() => goto("run")} />;
      case "report":     return <ReportScreen currentProject={currentProject} stale={!!projStatus?.report?.stale} onRerun={() => goto("run")} />;
      case "settings":   return <SettingsScreen llmEnabled={llmEnabled} keyPresent={llmKeyPresent} onToggleLLM={onToggleLLM} />;
      case "preview-lab":      return <PreviewLabScreen />;
      case "preview-training": return <PreviewTrainingScreen />;
      default:           return <ProjectsScreen onOpenProject={openProject} onCreate={onCreateProject} />;
    }
  };

  const inWorkspace = screen !== "projects" && screen !== "settings" && !screen.startsWith("preview");
  const onPreview = screen.startsWith("preview");

  return (
    <div className="app" id="app">
      <Rail
        screen={screen}
        gotoScreen={goto}
        currentProject={currentProject}
        stageStateFor={stageState}
        railWidth={t.railWidth}
        llmEnabled={llmActive}
        inWorkspace={inWorkspace}
      />

      <div className="main" id="main">
        <TopBar
          screen={screen}
          currentProject={currentProject}
          pipelineStage={pipelineStage}
          theme={t.theme}
          onThemeToggle={() => setTweak("theme", t.theme === "dark" ? "light" : "dark")}
          llmEnabled={llmActive}
          inWorkspace={inWorkspace}
        />
        <div id="screen-host" data-active-screen={screen}>
          {renderScreen()}
        </div>
      </div>

      {/* Tweaks panel — toggled by the toolbar */}
      <TweaksUI t={t} setTweak={setTweak} />
    </div>
  );
};

// =========================================================================
// Left rail
// =========================================================================
const Rail = ({ screen, gotoScreen, currentProject, stageStateFor, railWidth, llmEnabled, inWorkspace }) => {
  return (
    <aside className="rail" id="nav-rail" style={{ width: railWidth, minWidth: railWidth }}>
      <div className="rail-head" id="rail-brand">
        <div className="rail-logo">EMC</div>
        <div className="rail-title">
          <span className="t1">EMC Assistant</span>
          <span className="t2">Pre-compliance · local</span>
        </div>
      </div>

      <div className="rail-body">
        {/* Tier 1 — Workspace */}
        <div className="rail-section" id="rail-tier-workspace">
          <div className="rail-section-label">
            <span>WORKSPACE</span>
          </div>
          <NavItem icon="folder" label="Projects" screenId="projects" active={screen === "projects"} onClick={() => gotoScreen("projects")} />
        </div>

        {/* Tier 2 — Analysis workflow (per open project) */}
        <div className="rail-section" id="rail-tier-analysis" data-bind="current-project-name">
          <div className="rail-section-label">
            <span>ANALYSIS</span>
            <span className="hint mono" data-bind="current-project-name" style={{ fontSize: 9, textTransform: "none", letterSpacing: "0.04em" }}>
              {currentProject?.name || "no project"}
            </span>
          </div>
          {window.STAGES.map((s, i) => {
            const state = stageStateFor(s.id);
            return (
              <NavItem
                key={s.id}
                icon={s.icon}
                label={s.label}
                screenId={s.id}
                num={(i + 1).toString().padStart(2, "0")}
                active={screen === s.id}
                state={state}
                onClick={state === "locked" ? null : () => gotoScreen(s.id)}
                tip={state === "locked" ? "Locked — earlier stages must complete first." : null}
              />
            );
          })}
        </div>

        {/* Tier 3 — Coming soon */}
        <div className="rail-coming-divider" />
        <div className="rail-section" id="rail-tier-coming-soon">
          <div className="rail-section-label">
            <span>COMING SOON</span>
            <span className="hint">ROADMAP</span>
          </div>
          <NavItem
            icon="lab"
            label="Live Lab Assistant"
            screenId="preview-lab"
            state="coming-soon"
            active={screen === "preview-lab"}
            onClick={() => gotoScreen("preview-lab")}
            tip="Planned — not available in this version. Click to preview."
            soon
          />
          <NavItem
            icon="brain"
            label="Engineer Training"
            screenId="preview-training"
            state="coming-soon"
            active={screen === "preview-training"}
            onClick={() => gotoScreen("preview-training")}
            tip="Planned — not available in this version. Click to preview."
            soon
          />
        </div>
      </div>

      <div className="rail-foot" id="rail-foot">
        <NavItem icon="gear" label="Settings" screenId="settings" active={screen === "settings"} onClick={() => gotoScreen("settings")} />
        <div style={{ padding: "6px 6px 2px" }}>
          <PrivacyIndicator llmEnabled={llmEnabled} />
        </div>
      </div>
    </aside>
  );
};

// =========================================================================
// Nav item
// =========================================================================
const NavItem = ({ icon, label, num, active, state, onClick, tip, soon, screenId }) => {
  const dataState = state || (active ? "active" : "");
  return (
    <button
      className="nav-item"
      data-state={dataState}
      data-screen-target={screenId}
      data-action={state === "locked" ? "nav-locked" : "goto-screen"}
      aria-current={active ? "page" : undefined}
      onClick={onClick || undefined}
      data-tip={tip}
      disabled={state === "locked"}
      style={state === "locked" ? { cursor: "not-allowed" } : null}>
      <span className="nav-icon">
        {state === "done" ? <Icon name="check" /> : <Icon name={icon} />}
      </span>
      <span className="nav-label">{label}</span>
      <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
        {state === "done" && <span className="mono faint" style={{ fontSize: 9 }}>✓</span>}
        {state === "stale" && <span className="stale-pill">stale</span>}
        {state === "locked" && <span className="lock-dot" />}
        {soon && <span className="soon-pill">SOON</span>}
        {num && state !== "coming-soon" && state !== "stale" && !soon && <span className="nav-num">{num}</span>}
      </span>
    </button>
  );
};

// =========================================================================
// Topbar — crumbs + project meta + theme toggle
// =========================================================================
const TopBar = ({ screen, currentProject, pipelineStage, theme, onThemeToggle, llmEnabled, inWorkspace }) => {
  const breadcrumb = (() => {
    if (screen === "projects") return ["Workspace", "Projects"];
    if (screen === "settings") return ["Settings"];
    if (screen === "preview-lab") return ["Roadmap", "Live Lab Assistant"];
    if (screen === "preview-training") return ["Roadmap", "Engineer Training"];
    const stage = window.STAGES.find(s => s.id === screen);
    return ["Project", currentProject?.name || "(no project)", stage ? stage.label : screen];
  })();

  return (
    <div className="topbar" id="topbar">
      <div className="crumbs" id="crumbs" data-bind="breadcrumb">
        {breadcrumb.map((c, i) => (
          <React.Fragment key={i}>
            {i > 0 && <span className="sep">/</span>}
            <span className={i === breadcrumb.length - 1 ? "cur" : ""}>{c}</span>
          </React.Fragment>
        ))}
      </div>
      <div className="spacer" />
      {inWorkspace && (
        <div className="meta" data-bind="project-meta">
          <span><span className="k">topology</span> <span className="v" data-bind="project-topology">sync buck</span></span>
          <span><span className="k">fsw</span> <span className="v" data-bind="project-fsw">500 kHz</span></span>
          <span><span className="k">Vin/Vout</span> <span className="v" data-bind="project-vin-vout">12 / 3.3 V</span></span>
          <span><span className="k">pipeline</span> <span className="v" data-bind="pipeline-stage">{pipelineStage}</span></span>
        </div>
      )}
      <PrivacyIndicator llmEnabled={llmEnabled} />
      <SaveProjectButton projectName={currentProject?.name} />
      <button className="icon-btn" id="theme-toggle" data-action="toggle-theme" onClick={onThemeToggle} data-tip={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} aria-label="Toggle theme">
        <Icon name={theme === "dark" ? "sun" : "moon"} />
      </button>
    </div>
  );
};

// =========================================================================
// Save project — topbar button + "saved Xm ago" status (V2_3, mock).
// The mock simulates a save via setTimeout; the actual backend wiring
// (a `save_project` bridge method) is deferred — every real backend
// store (user_context, settings, schematic file) already has its own
// save action via the screen that owns it, so this button is a UX
// affordance today and a hook for an eventual project-wide snapshot.
// =========================================================================
const SaveProjectButton = ({ projectName }) => {
  // Phases: "idle" → "saving" → "saved-just-now" → "idle"
  const [phase, setPhase] = useState("idle");
  // Real per-session timestamp — null until the user actually clicks Save,
  // so we never fabricate a "saved Xm ago" before anything happened.
  const [lastSavedAt, setLastSavedAt] = useState(null);
  const [, force] = useState(0);

  // Tick once a minute so "Xm ago" stays current
  useEffect(() => {
    const t = setInterval(() => force(x => x + 1), 30 * 1000);
    return () => clearInterval(t);
  }, []);

  // Cmd/Ctrl+S keyboard shortcut
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        doSave();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const doSave = () => {
    if (phase === "saving") return;
    setPhase("saving");
    // TODO(wiring): replace the timer with `await window.pywebview.api.save_project(projectName)`
    // once a project-wide snapshot operation exists.
    setTimeout(() => {
      setLastSavedAt(Date.now());
      setPhase("saved-just-now");
      setTimeout(() => setPhase("idle"), 1600);
    }, 350);
  };

  const ago = (ts) => {
    const s = Math.floor((Date.now() - ts) / 1000);
    if (s < 10) return "just now";
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  };

  const statusText =
    phase === "saving" ? "saving…" :
    phase === "saved-just-now" ? "saved · just now" :
    lastSavedAt ? `saved · ${ago(lastSavedAt)}` :
    "autosaves per screen";

  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <span
        className="mono faint"
        data-bind="project-save-status"
        data-save-phase={phase}
        style={{ fontSize: "var(--t-2xs)", letterSpacing: "0.02em" }}>
        {statusText}
      </span>
      <button
        className="btn btn-sm"
        data-action="save-project"
        data-project-name={projectName}
        onClick={doSave}
        disabled={phase === "saving"}
        data-tip="Each screen autosaves its own changes; this confirms the project is persisted (⌘S / Ctrl+S)"
        aria-label="Save project">
        <Icon name={phase === "saved-just-now" ? "check" : "save"} />
        <span>{phase === "saved-just-now" ? "Saved" : "Save"}</span>
      </button>
    </div>
  );
};

// =========================================================================
// Tweaks UI
// =========================================================================
const TweaksUI = ({ t, setTweak }) => (
  <TweaksPanel title="Tweaks">
    <TweakSection label="Appearance">
      <TweakRadio label="Theme" value={t.theme} onChange={v => setTweak("theme", v)}
                  options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }]} />
      <TweakRadio label="Density" value={t.density} onChange={v => setTweak("density", v)}
                  options={[
                    { value: "compact", label: "Compact" },
                    { value: "default", label: "Default" },
                    { value: "comfortable", label: "Roomy" },
                  ]} />
      <TweakSlider label="Accent hue" value={t.accentHue} min={0} max={360} step={5}
                   onChange={v => setTweak("accentHue", v)} />
      <TweakSlider label="Sidebar width" value={t.railWidth} min={56} max={280} step={4}
                   onChange={v => setTweak("railWidth", v)} />
    </TweakSection>

    <TweakSection label="Data visualisation">
      <TweakRadio label="Uncertainty style" value={t.uncertaintyStyle} onChange={v => setTweak("uncertaintyStyle", v)}
                  options={[
                    { value: "bar", label: "Bar" },
                    { value: "ticks", label: "Ticks" },
                    { value: "num", label: "Numeric" },
                  ]} />
      <TweakRadio label="Severity palette" value={t.severity} onChange={v => setTweak("severity", v)}
                  options={[
                    { value: "default", label: "RAG" },
                    { value: "cb-safe", label: "CB-safe" },
                  ]} />
    </TweakSection>

    <TweakSection label="Prototype state">
      <TweakSelect label="Pipeline progress" value={t.pipelineStage} onChange={v => setTweak("pipelineStage", v)}
                   options={window.STAGE_ORDER.map(s => ({ value: s, label: s }))} />
      <TweakSelect label="Sample project" value={t.sampleProject} onChange={v => setTweak("sampleProject", v)}
                   options={[
                     { value: "buck", label: "sync buck 12→3.3 V" },
                     { value: "boost", label: "boost 24→48 V" },
                     { value: "flyback", label: "flyback 100 W iso" },
                   ]} />
    </TweakSection>
  </TweaksPanel>
);

// Mount
ReactDOM.createRoot(document.getElementById("root")).render(<App />);
