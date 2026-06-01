import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
// Screen: Projects — list / create / open local .emcproj projects.
//
// Wired to the Python service layer via `window.pywebview.api.*`:
//   - `pick_folder()` opens pywebview's native folder dialog,
//   - `list_projects(root)` scans `<root>/*/project.yaml` and returns
//     `[{name, path}, …]`. The last-picked folder is cached in
//     localStorage so the next launch starts populated.
//
// In Vite dev / a plain browser tab `window.pywebview` is absent, so the
// `useApi()` hook returns the mock stub from `src/api.jsx` instead — the
// list shows two "(mock)" entries.

const STAGE_LABEL = {
  import: "imported",
  parasitics: "parasitics set",
  testbench: "testbench composed",
  run: "simulated",
  results: "results ready",
  findings: "findings reviewed",
  report: "report ready",
};

const _LS_FOLDER_KEY = "emc:projectsFolder";

const ProjectsScreen = ({ onOpenProject, onCreate }) => {
  const [filter, setFilter] = useState("");
  const [folder, setFolder] = useState(
    () => (typeof localStorage !== "undefined" && localStorage.getItem(_LS_FOLDER_KEY)) || ""
  );
  const [projects, setProjects] = useState([]);
  const [loadError, setLoadError] = useState("");
  const api = useApi();

  const loadFrom = useCallback(async (root) => {
    if (!root) {
      setProjects([]);
      return;
    }
    setLoadError("");
    const res = await api.list_projects(root);
    if (!res.ok) {
      setLoadError(res.error?.message || "could not list projects");
      setProjects([]);
      return;
    }
    const base = res.data || [];
    // First paint: names + paths immediately (status loads asynchronously).
    setProjects(base.map(p => ({
      id: p.path, name: p.name, path: p.path,
      stage: null, updated: "", findings: 0, accepted: 0, severity: null,
    })));
    // Enrich each row with real pipeline stage (from project_status) and,
    // when the findings stage is present, the recommendation counts.
    const order = window.STAGE_ORDER || [];
    const enriched = await Promise.all(base.map(async (p) => {
      const row = {
        id: p.path, name: p.name, path: p.path,
        stage: null, updated: "", findings: 0, accepted: 0, severity: null,
      };
      const st = await api.project_status(p.path);
      if (st.ok && Array.isArray(st.data?.stages)) {
        const ui = window._uiStageStatus ? window._uiStageStatus(st.data) : null;
        let latestTs = "";
        for (const s of order) {
          if (ui && ui[s]?.present) row.stage = s;
        }
        for (const s of st.data.stages) {
          if (s.present && s.generated_at && s.generated_at > latestTs) latestTs = s.generated_at;
        }
        if (latestTs) row.updated = latestTs.slice(0, 10);   // YYYY-MM-DD
        if (ui && ui.findings?.present) {
          const rec = await api.list_recommendations(p.path);
          if (rec.ok && Array.isArray(rec.data?.rows)) {
            row.findings = rec.data.rows.length;
            row.accepted = rec.data.rows.filter(r => r.status === "accepted").length;
          }
        }
      }
      return row;
    }));
    setProjects(enriched);
  }, [api]);

  // Repopulate whenever the folder changes (incl. the initial-localStorage load).
  useEffect(() => { loadFrom(folder); }, [folder, loadFrom]);

  const onOpenFolder = useCallback(async () => {
    const res = await api.pick_folder("Open a project (or a folder of projects)");
    if (!res.ok) {
      setLoadError(res.error?.message || "folder picker failed");
      return;
    }
    let picked = res.data?.path;
    // Browser dev mode (no pywebview): mock returns null silently — fall
    // back to window.prompt so the screen is testable without launching
    // the pywebview shell. In pywebview, a null result means the user
    // cancelled the dialog; we respect that.
    if (!picked && !window.isPywebview?.()) {
      picked = window.prompt("Folder (a project, or a folder of projects):", folder || "");
    }
    if (!picked) return;
    // If the picked folder is *itself* a project (has project.yaml), open it
    // directly — that's what "Open project" implies. Otherwise treat it as a
    // parent folder and scan it for child *.emcproj projects.
    const st = await api.project_status(picked);
    if (st.ok) {
      onOpenProject && onOpenProject({
        name: picked.replace(/[\\/]+$/, "").split(/[\\/]/).pop(), path: picked,
      });
      return;
    }
    try { localStorage.setItem(_LS_FOLDER_KEY, picked); } catch {}
    setFolder(picked);
  }, [api, folder, onOpenProject]);

  const inPywebview = typeof window !== "undefined" && !!window.isPywebview?.();

  const filtered = useMemo(
    () => projects.filter(p => !filter || p.name.includes(filter)),
    [projects, filter]
  );

  return (
    <div className="screen" data-screen="projects" data-screen-label="01 Projects" id="screen-projects">
      <div className="screen-head">
        <div className="screen-title-block">
          <div className="eyebrow">Workspace</div>
          <h1>Projects</h1>
          <div className="lede">Local <span className="mono">.emcproj</span> folders. Each is a self-contained pre-compliance project; nothing leaves this machine.</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" data-action="open-project-folder" onClick={onOpenFolder}>
            <Icon name="folder" /> Open project
          </button>
          <button className="btn primary" data-action="create-project" onClick={onCreate}>
            <Icon name="plus" /> New project
          </button>
        </div>
      </div>

      <div className="faint mono" style={{ fontSize: "var(--t-xs)", marginBottom: 8 }}>
        bridge:{" "}
        <span style={{ color: inPywebview ? "var(--sev-low)" : "var(--sev-med)" }}>
          {inPywebview ? "pywebview ✓ (live backend)" : "mock — browser dev (no real backend)"}
        </span>
      </div>

      {folder && (
        <div className="faint mono" style={{ fontSize: "var(--t-xs)", marginBottom: 8 }}>
          Scanning: <span data-bind="projects-root">{folder}</span>
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <div style={{ position: "relative", flex: 1, maxWidth: 320 }}>
          <span style={{ position: "absolute", left: 10, top: 7, color: "var(--text-faint)"}}><Icon name="search" /></span>
          <input className="input" id="projects-filter" data-action="filter-projects" placeholder="filter projects…" style={{ paddingLeft: 32 }}
                 value={filter} onChange={e => setFilter(e.target.value)} />
        </div>
        <div className="mono dim" data-bind="projects-count" style={{ fontSize: "var(--t-xs)"}}>{filtered.length} project{filtered.length === 1 ? "" : "s"}</div>
      </div>

      {loadError && (
        <div className="card" style={{ padding: 12, marginBottom: 12, color: "var(--sev-high)" }}>
          <span className="mono">error:</span> {loadError}
        </div>
      )}

      <div className="card" style={{ overflow: "hidden" }}>
        <table className="table" id="projects-table">
          <thead>
            <tr>
              <th style={{ width: "26%" }}>Project</th>
              <th style={{ width: "22%" }}>Pipeline status</th>
              <th>Findings</th>
              <th>Last updated</th>
              <th style={{ width: 60 }}></th>
            </tr>
          </thead>
          <tbody data-bind="projects-list">
            {filtered.length === 0 ? (
              <tr><td colSpan={5} className="faint" style={{ padding: 24, textAlign: "center" }}>
                {folder ? "No .emcproj folders here." : "Click \"Open folder…\" to pick a directory of .emcproj projects."}
              </td></tr>
            ) : filtered.map(p => (
              <tr key={p.id}
                  data-action="open-project"
                  data-project-id={p.id}
                  data-project-path={p.path}
                  onClick={() => onOpenProject && onOpenProject(p)}
                  style={{ cursor: "pointer" }}>
                <td>
                  <div style={{ display: "flex", flexDirection: "column" }}>
                    <span className="net-tag" data-bind="project-name" style={{ color: "var(--text)"}}>{p.name}</span>
                    <span className="faint" data-bind="project-path" style={{ fontSize: "var(--t-xs)"}}>{p.path}</span>
                  </div>
                </td>
                <td>
                  <PipelineMini stage={p.stage} />
                  <div className="faint" data-bind="project-stage" style={{ fontSize: "var(--t-xs)", marginTop: 4 }}>{STAGE_LABEL[p.stage] || "—"}</div>
                </td>
                <td data-bind="project-findings">
                  {p.findings === 0 ? <span className="faint">—</span> : (
                    <div style={{ display: "flex", gap: 8, alignItems: "center"}}>
                      <span className="tnum"><b data-bind="findings-total" style={{ color: "var(--text)"}}>{p.findings}</b> total</span>
                      <span className="dim">· <span data-bind="findings-accepted">{p.accepted}</span> accepted</span>
                      {p.severity && <SeverityBadge level={p.severity} />}
                    </div>
                  )}
                </td>
                <td className="dim" data-bind="project-updated">{p.updated || "—"}</td>
                <td><Icon name="chevron-right" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 16 }}>
        <PreComplianceDisclaimer />
      </div>
    </div>
  );
};

// Tiny pipeline progress chip (7 dots, current = filled)
const PipelineMini = ({ stage }) => {
  const idx = window.STAGE_ORDER.indexOf(stage);
  return (
    <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
      {window.STAGE_ORDER.map((s, i) => (
        <span key={s} data-tip={s} style={{
          width: 14, height: 6, borderRadius: 1,
          background: i < idx ? "var(--accent)" : i === idx ? "var(--accent)" : "var(--panel-3)",
          opacity: i === idx ? 1 : (i < idx ? 0.55 : 1),
          border: i === idx ? "none" : "none",
          boxShadow: i === idx ? "0 0 6px var(--accent)" : "none",
        }} />
      ))}
    </div>
  );
};

window.ProjectsScreen = ProjectsScreen;
window.PipelineMini = PipelineMini;
