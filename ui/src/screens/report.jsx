import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
// Screen: Report & export — renders the real reports/report.md (via
// read_artifact) with a light markdown renderer; meta + findings counts
// come from project_status + list_recommendations. Export confirms which
// report artifacts exist on disk (the pipeline writes .md, and .html when
// run with html:true); regenerating to PDF is a Run-screen pipeline option.

// --- minimal markdown -> React (headings, bold/code, lists, tables, rules) ---
function _inline(text, keyBase) {
  // split on **bold** and `code`
  const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((p, i) => {
    if (/^\*\*[^*]+\*\*$/.test(p)) return <strong key={`${keyBase}-${i}`}>{p.slice(2, -2)}</strong>;
    if (/^`[^`]+`$/.test(p)) return <code key={`${keyBase}-${i}`} className="mono">{p.slice(1, -1)}</code>;
    return <React.Fragment key={`${keyBase}-${i}`}>{p}</React.Fragment>;
  });
}

function renderMarkdown(md) {
  const lines = String(md || "").split(/\r?\n/);
  const out = [];
  let i = 0, list = null, key = 0;
  const flushList = () => { if (list) { out.push(<ul key={`ul-${key++}`} style={{ margin: "0 0 12px", paddingLeft: 22 }}>{list}</ul>); list = null; } };
  while (i < lines.length) {
    let ln = lines[i];
    if (ln.trim().startsWith("```")) {           // code fence
      flushList(); const buf = []; i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) { buf.push(lines[i]); i++; }
      i++;
      out.push(<pre key={`pre-${key++}`} className="mono" style={{ background: "var(--plot-bg)", padding: 12, borderRadius: 4, fontSize: 11, overflow: "auto", margin: "0 0 12px" }}>{buf.join("\n")}</pre>);
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(ln)) {              // table block
      flushList(); const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        const cells = lines[i].trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
        if (!cells.every(c => /^:?-+:?$/.test(c) || c === "")) rows.push(cells);
        i++;
      }
      out.push(
        <table key={`tbl-${key++}`} className="table" style={{ margin: "0 0 14px" }}>
          <tbody>{rows.map((r, ri) => (
            <tr key={ri}>{r.map((c, ci) => ri === 0
              ? <th key={ci}>{_inline(c, `h${ri}${ci}`)}</th>
              : <td key={ci}>{_inline(c, `c${ri}${ci}`)}</td>)}</tr>
          ))}</tbody>
        </table>
      );
      continue;
    }
    const img = ln.match(/^!\[([^\]]*)\]\(([^)]+)\)/);
    if (img) { flushList(); out.push(<div key={`img-${key++}`} className="dim mono" style={{ fontSize: "var(--t-xs)", padding: "6px 0" }}>[figure: {img[1] || img[2]}]</div>); i++; continue; }
    const h = ln.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      flushList();
      const lvl = h[1].length;
      const Tag = lvl <= 1 ? "h2" : lvl === 2 ? "h3" : "h4";
      out.push(<Tag key={`h-${key++}`} style={{ margin: "16px 0 8px", fontFamily: lvl <= 2 ? "var(--font-mono)" : undefined, fontSize: lvl <= 1 ? 18 : lvl === 2 ? 15 : 13, color: "var(--text)" }}>{_inline(h[2], `h${key}`)}</Tag>);
      i++; continue;
    }
    const li = ln.match(/^\s*[-*]\s+(.*)$/);
    if (li) { if (!list) list = []; list.push(<li key={`li-${key}-${list.length}`} style={{ marginBottom: 4 }}>{_inline(li[1], `li${key}${list.length}`)}</li>); i++; continue; }
    if (/^\s*(---|===)\s*$/.test(ln)) { flushList(); out.push(<hr key={`hr-${key++}`} style={{ border: 0, borderTop: "1px solid var(--border)", margin: "14px 0" }} />); i++; continue; }
    if (ln.trim() === "") { flushList(); i++; continue; }
    flushList();
    out.push(<p key={`p-${key++}`} style={{ margin: "0 0 10px", color: "var(--text-dim)" }}>{_inline(ln, `p${key}`)}</p>);
    i++;
  }
  flushList();
  return out;
}

const ReportScreen = ({ currentProject, stale, onRerun }) => {
  const api = useApi();
  const projectRoot = currentProject?.path || "";
  const inPywebview = typeof window !== "undefined" && !!window.isPywebview?.();

  const [md, setMd] = useState("");
  const [present, setPresent] = useState({});       // {md, html}
  const [counts, setCounts] = useState(null);
  const [generatedAt, setGeneratedAt] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [exportNote, setExportNote] = useState("");
  const [format, setFormat] = useState("md");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!projectRoot) { setMd(""); setLoading(false); return; }
      setLoading(true); setLoadError(""); setExportNote("");
      const [mdRes, htmlRes, recRes, st] = await Promise.all([
        api.read_artifact(projectRoot, "reports/report.md"),
        api.read_artifact(projectRoot, "reports/report.html"),
        api.list_recommendations(projectRoot),
        api.project_status(projectRoot),
      ]);
      if (cancelled) return;
      setMd(mdRes.ok ? mdRes.data : "");
      if (!mdRes.ok) setLoadError("no report yet — run the pipeline to generate reports/report.md");
      setPresent({ md: mdRes.ok, html: htmlRes.ok });
      if (recRes.ok) {
        const rows = recRes.data?.rows || [];
        setCounts({
          all: rows.length,
          accepted: rows.filter(r => r.status === "accepted").length,
          rejected: rows.filter(r => r.status === "rejected").length,
          open: rows.filter(r => r.status !== "accepted" && r.status !== "rejected").length,
        });
      }
      if (st.ok && Array.isArray(st.data?.stages)) {
        const rep = st.data.stages.find(s => s.stage === "report");
        if (rep?.generated_at) setGeneratedAt(rep.generated_at.slice(0, 19).replace("T", " "));
      }
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [projectRoot, api]);

  const sections = useMemo(() => (md.match(/^#{1,2}\s+/gm) || []).length, [md]);
  const sizeKb = useMemo(() => (md ? (new Blob([md]).size / 1024).toFixed(1) : "0"), [md]);
  const body = useMemo(() => renderMarkdown(md), [md]);

  const onExport = useCallback(async () => {
    const ext = format === "html" ? "html" : format === "pdf" ? "pdf" : "md";
    const res = await api.read_artifact(projectRoot, `reports/report.${ext}`);
    if (res.ok) setExportNote(`✓ report.${ext} is at reports/report.${ext}`);
    else if (ext === "pdf") setExportNote("PDF not generated yet — re-run the pipeline with the PDF option (Run screen).");
    else setExportNote(`report.${ext} not found — re-run the pipeline to generate it.`);
  }, [api, projectRoot, format]);

  return (
    <div className="screen" data-screen="report" data-screen-label="08 Report" id="screen-report" data-report-stale={stale ? "true" : "false"}>
      <div className="screen-head">
        <div className="screen-title-block">
          <div className="eyebrow">Stage 7 / 7</div>
          <h1>Report & export</h1>
          <div className="lede">Markdown / HTML pre-compliance report — your context, parasitics, simulation settings, results, findings, and decisions, in one auditable bundle.</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Segmented value={format} options={[
            { value: "md", label: ".MD" },
            { value: "html", label: "HTML" },
            { value: "pdf", label: "PDF" },
          ]} onChange={setFormat} data-action="set-export-format" data-field="export_format" />
          <button className="btn primary" data-action="export-report" data-format={format} onClick={onExport} disabled={!projectRoot}><Icon name="download" /> Locate {format.toUpperCase()}</button>
        </div>
      </div>

      <div className="faint mono" style={{ fontSize: "var(--t-xs)", marginBottom: 8 }}>
        bridge:{" "}
        <span style={{ color: inPywebview ? "var(--sev-low)" : "var(--sev-med)" }}>
          {inPywebview ? "pywebview ✓ (live backend)" : "mock — browser dev (no real backend)"}
        </span>
        {projectRoot && <span> · project: <span style={{ color: "var(--text)" }}>{currentProject?.name || projectRoot}</span></span>}
        {!projectRoot && <span> · <span style={{ color: "var(--sev-med)" }}>no project — open one from Projects first</span></span>}
        {exportNote && <span> · <span style={{ color: "var(--sev-low)" }}>{exportNote}</span></span>}
      </div>
      {loadError && (
        <div className="card" style={{ padding: 12, marginBottom: 12, color: "var(--sev-med)" }}>
          <span className="mono">notice:</span> {loadError}
        </div>
      )}

      {stale && md && (
        <StaleBanner bind="report-stale-banner" onRerun={onRerun}>
          <b style={{ color: "var(--text)" }}>This report is out of date.</b> An input changed since it was generated — re-run the pipeline to regenerate the report from the current inputs.
        </StaleBanner>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 16 }}>
        <Card title="reports/report.md" sub="rendered in-app" flush>
          <div id="report-preview" data-bind="report-preview" style={{
            background: "var(--panel-2)", padding: 28, minHeight: 560,
            fontFamily: "var(--font-sans)", lineHeight: 1.55, maxHeight: 700, overflow: "auto",
            opacity: stale ? 0.6 : 1,
          }}>
            {md ? body : (
              <div className="dim mono" style={{ fontSize: "var(--t-xs)" }}>
                {loading ? "loading…" : "No report yet — run the pipeline (Run screen). The report writes to reports/report.md."}
              </div>
            )}
          </div>
        </Card>

        <div className="col">
          <Card title="Report artifacts" sub="written by report generation">
            <div data-bind="report-artifacts" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <ArtRow label="report.md" present={present.md} note={`${sizeKb} KB`} />
              <ArtRow label="report.html" present={present.html} note={present.html ? "present" : "run with HTML on"} />
              <ArtRow label="report.pdf" present={false} note="run with PDF option" />
            </div>
          </Card>

          <Card title="Report contents" sub="from this run" flush>
            <table className="table">
              <tbody data-bind="report-meta">
                <tr><td className="faint" style={{ fontSize: "var(--t-xs)"}}>Project</td><td className="num">{currentProject?.name || "—"}</td></tr>
                <tr><td className="faint" style={{ fontSize: "var(--t-xs)"}}>Generated</td><td className="num mono" style={{ fontSize: "var(--t-xs)"}}>{generatedAt || "—"}</td></tr>
                <tr><td className="faint" style={{ fontSize: "var(--t-xs)"}}>Sections</td><td className="num">{sections || "—"}</td></tr>
                <tr><td className="faint" style={{ fontSize: "var(--t-xs)"}}>Findings</td><td className="num">{counts ? `${counts.all} (${counts.open} open · ${counts.accepted} acc · ${counts.rejected} rej)` : "—"}</td></tr>
                <tr><td className="faint" style={{ fontSize: "var(--t-xs)"}}>Markdown size</td><td className="num">{sizeKb} KB</td></tr>
              </tbody>
            </table>
          </Card>

          <PreComplianceDisclaimer />
        </div>
      </div>
    </div>
  );
};

const ArtRow = ({ label, present, note }) => (
  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
    <span className="mono" style={{ fontSize: "var(--t-xs)", color: "var(--text-dim)" }}>{label}</span>
    <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <span className="mono faint" style={{ fontSize: 10 }}>{note}</span>
      <Pill tone={present ? "ok" : null} dot={present}>{present ? "present" : "—"}</Pill>
    </span>
  </div>
);

window.ReportScreen = ReportScreen;
