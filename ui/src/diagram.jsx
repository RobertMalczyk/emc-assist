import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
// Testbench block diagram — schematic-style with explicit power & return rails.
//
// Layout principles:
//   • Two horizontal rails: VIN+ (top) and PGND/RTN (bottom).
//   • Every block sits between the rails and taps them on its left & right edges.
//   • Routing is strictly orthogonal (no diagonals). Wires only kink at right angles.
//   • Parasitic shunts hang *below* the bottom rail (or sit between rails in an open
//     space) — never overlap a block label.
//   • Selecting a net highlights the matching wire segment + parasitic glyph.

const _CABLE_GROUND_Y = 470; // where ground symbols below the PGND rail sit
const TestbenchDiagram = ({ selectedNet, nets, onSelectNet, withParasitics = true, height = 480, dutSub, meta = {} }) => {
  const W = 1360, H = 500;
  const isNet = n => selectedNet === n;
  const wireOn = (n) => isNet(n) ? "highlight" : "";
  const includeOf = name => nets?.find(n => n.net === name)?.include ?? true;
  // Real, data-driven labels for the DUT block + parasitic summary. The
  // diagram frame (supply → LISN → cable → DUT → load) is the universal
  // conducted-EMI testbench; the DUT *interior* is intentionally NOT a
  // fabricated schematic — a faithful render is the queued follow-up.
  const dutSubLabel = dutSub || `${(nets || []).length} nets`;
  const paraCount = (nets || []).filter(n => (n.include ?? true)).length;

  // Project-driven labels (hardening: the frame adapts to the imported
  // project instead of hardcoding a buck). All optional with safe defaults.
  const supplyV   = meta.supply || "DC";
  const lisnMode  = String(meta.lisn || "dual").toLowerCase();
  const lisnLabel = lisnMode === "single" ? "SINGLE LISN" : "DUAL LISN";
  const lisnRx    = lisnMode === "single" ? "50 Ω" : "50 Ω · DM/CM";
  const cableLbl  = meta.cable ? `${meta.cable} · L/C distributed` : "L/C distributed";
  const loadLbl   = meta.load || "resistive";

  // Rails (y coords)
  const VIN_Y = 180;
  const RTN_Y = 360;
  const GND_Y = 430; // ground-symbol height below the rail

  // === Block extents (left/right edges where rails enter/exit) =============
  // Block widths are sized so the gap between adjacent blocks (~80–100 px)
  // is large enough to fit a parasitic splice + label clearly.
  const blocks = [
    { id: "supply",  x: 40,   w: 140, label: `${supplyV} SUPPLY`, sub: "external source",             inner: "supply" },
    { id: "lisn",    x: 260,  w: 200, label: lisnLabel,           sub: "50 µH / 50 Ω · CISPR 16-1-2", inner: "lisn",  net: "VIN" },
    { id: "cable",   x: 560,  w: 120, label: "CABLE",             sub: cableLbl,                       inner: "cable" },
    { id: "dut",     x: 780,  w: 380, label: "DUT",               sub: dutSubLabel,                    inner: "dut" },
    { id: "load",    x: 1260, w: 100, label: "LOAD",              sub: loadLbl,                        inner: "load" },
  ];

  // Helper getters
  const blk = id => blocks.find(b => b.id === id);

  // === Render helpers ======================================================
  const Block = ({ b }) => {
    const yTop = 130;
    const yBot = 410;
    const active = (b.net && isNet(b.net)) || (b.id === "dut" && (isNet("SW") || isNet("LX") || isNet("VOUT") || isNet("PGND") || isNet("VCC")));
    return (
      <g>
        <rect
          className={`node ${active ? "active" : ""}`}
          x={b.x} y={yTop}
          width={b.w} height={yBot - yTop}
          rx="4"
          onClick={b.net ? () => onSelectNet && onSelectNet(b.net) : undefined}
          style={{ cursor: b.net ? "pointer" : "default" }}
        />
        <text x={b.x + b.w / 2} y={yTop + 22} textAnchor="middle" className="node-label" style={{ fontSize: 12, fontWeight: 600 }}>{b.label}</text>
        <text x={b.x + b.w / 2} y={yTop + 38} textAnchor="middle" className="node-sub">{b.sub}</text>
      </g>
    );
  };

  // === Capacitor symbol (vertical) =========================================
  // Two horizontal plates, with a small gap between. Caller supplies x,
  // y-top (where wire enters), and y-bottom (where wire exits).
  const Cap = ({ x, yTop, yBot, className = "" }) => {
    const midTop = (yTop + yBot) / 2 - 3;
    const midBot = (yTop + yBot) / 2 + 3;
    return (
      <g className={className}>
        <line x1={x} y1={yTop} x2={x} y2={midTop} />
        <line x1={x - 9} y1={midTop} x2={x + 9} y2={midTop} strokeWidth="1.5" />
        <line x1={x - 7} y1={midBot} x2={x + 7} y2={midBot} strokeWidth="1.5" />
        <line x1={x} y1={midBot} x2={x} y2={yBot} />
      </g>
    );
  };

  // Inductor / coil — a row of semicircular humps (IEC/ANSI coil). Each
  // hump bows *upward* (sweep 0) so it reads clearly as a coil and not a
  // short. The path starts and ends on the rail level so the broken rail
  // segments meet it cleanly at both terminals.
  const InductorH = ({ x, y, w = 40, bumps = 4, className = "" }) => {
    const bw = w / bumps;
    let d = `M ${x} ${y}`;
    for (let i = 0; i < bumps; i++) {
      d += ` a ${bw / 2} ${bw / 2} 0 0 0 ${bw} 0`;
    }
    return <path d={d} className={className} fill="none" />;
  };

  // Ground symbol (chassis triangle)
  const Ground = ({ x, y }) => (
    <g className="gnd">
      <line x1={x - 9} y1={y} x2={x + 9} y2={y} strokeWidth="1.5" />
      <line x1={x - 6} y1={y + 3} x2={x + 6} y2={y + 3} strokeWidth="1.2" />
      <line x1={x - 3} y1={y + 6} x2={x + 3} y2={y + 6} strokeWidth="1" />
    </g>
  );

  // Junction dot
  const Junction = ({ x, y }) => (
    <circle cx={x} cy={y} r="3" fill="var(--text-dim)" />
  );

  // Parasitic shunt: taps the bottom rail (or any horizontal wire at yBus),
  // drops to a capacitor and a ground symbol below.
  const ParShunt = ({ x, yBus, label, netName }) => {
    const off = !includeOf(netName);
    const sel = isNet(netName);
    const cls = `parasitic ${off ? "off" : ""} ${sel ? "highlight" : ""}`;
    return (
      <g style={{ cursor: "pointer" }} onClick={() => onSelectNet && onSelectNet(netName)}>
        <Junction x={x} y={yBus} />
        <Cap x={x} yTop={yBus + 4} yBot={yBus + 32} className={cls} />
        <line x1={x} y1={yBus + 32} x2={x} y2={yBus + 44} className={cls} />
        <Ground x={x} y={yBus + 44} />
        <text x={x + 14} y={yBus + 22} className="ghost-label" style={{ fontSize: 10 }}>
          {label}
        </text>
        <text x={x + 14} y={yBus + 34} className="ghost-label" style={{ fontSize: 9, opacity: 0.7 }}>
          {netName}
        </text>
      </g>
    );
  };

  // Parasitic series RLC splice on a horizontal wire (R + L + C-to-ground in chain)
  // labelBelow: when true, label sits below the wire (gives room above for block subtitle).
  const ParSeries = ({ xStart, xEnd, y, label, netName, labelBelow = false }) => {
    const off = !includeOf(netName);
    const sel = isNet(netName);
    const cls = `parasitic ${off ? "off" : ""} ${sel ? "highlight" : ""}`;
    const w = xEnd - xStart;
    const xR1 = xStart + 6, xR2 = xR1 + 18; // resistor
    const xL1 = xR2 + 4, xL2 = xL1 + 22;    // inductor
    return (
      <g style={{ cursor: "pointer" }} onClick={() => onSelectNet && onSelectNet(netName)}>
        {/* connecting line */}
        <line x1={xStart} y1={y} x2={xR1} y2={y} className={cls} />
        {/* R as a clean symmetric zig-zag (fixed resistor, no through-line) */}
        <path d={`M ${xR1} ${y} l 3 -5 l 4 10 l 4 -10 l 4 10 l 3 -5`} className={cls} fill="none" />
        <line x1={xR2} y1={y} x2={xL1} y2={y} className={cls} />
        {/* L as coil */}
        <InductorH x={xL1} y={y} w={xL2 - xL1} className={cls} />
        <line x1={xL2} y1={y} x2={xEnd} y2={y} className={cls} />
        <text x={(xStart + xEnd) / 2} y={labelBelow ? y + 18 : y - 10} textAnchor="middle" className="ghost-label" style={{ fontSize: 10 }}>
          {label}
        </text>
      </g>
    );
  };

  // === Build wires =========================================================
  // Top rail (VIN+): runs left-to-right through blocks, with gaps between them.
  // Bottom rail (RTN/PGND): same but at y=RTN_Y.
  // We draw it as a series of segments between blocks.

  // Convert block list into edges
  const segs = [];
  for (let i = 0; i < blocks.length - 1; i++) {
    const a = blocks[i];
    const b = blocks[i + 1];
    segs.push({ id: `${a.id}->${b.id}`, x1: a.x + a.w, x2: b.x, after: a.id });
  }

  // Source: VIN+ output node — also need internal source detail
  const supply = blk("supply");
  const lisn = blk("lisn");
  const cable = blk("cable");
  const dut = blk("dut");
  const load = blk("load");

  return (
    <svg className="diagram" viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height, display: "block" }} preserveAspectRatio="xMidYMid meet">
      <defs>
        <style>{`
          .diagram .gnd line { stroke: var(--text-faint); }
          .diagram text { font-family: var(--font-mono); }
        `}</style>
      </defs>

      {/* Top strip caption lives at the bottom of this file (one line, no
          overlap) — a second title here used to collide with it. */}

      {/* Rail labels (left side) */}
      <text x={14} y={VIN_Y - 6} className="ghost-label" style={{ fontSize: 9, fill: "oklch(0.78 0.18 25)" }}>VIN+</text>
      <text x={14} y={RTN_Y - 6} className="ghost-label" style={{ fontSize: 9, fill: "oklch(0.82 0.10 230)" }}>RTN</text>

      {/* === Blocks ========================================================== */}
      {blocks.map(b => <Block key={b.id} b={b} />)}

      {/* === Block internals ================================================= */}
      {/* SUPPLY interior */}
      <g>
        <circle cx={supply.x + supply.w / 2} cy={270} r="14" fill="none" stroke="var(--text-muted)" strokeWidth="1.2" />
        <text x={supply.x + supply.w / 2} y={275} textAnchor="middle" className="node-sub" style={{ fontSize: 14 }}>~</text>
        <line x1={supply.x + supply.w / 2} y1={256} x2={supply.x + supply.w / 2} y2={VIN_Y} className="wire power" />
        <line x1={supply.x + supply.w / 2} y1={284} x2={supply.x + supply.w / 2} y2={RTN_Y} className="wire return" />
        <text x={supply.x + supply.w / 2 + 18} y={VIN_Y + 12} className="node-sub" style={{ fontSize: 9 }}>{supplyV}</text>
        <text x={supply.x + supply.w / 2 + 18} y={RTN_Y - 4} className="node-sub" style={{ fontSize: 9 }}>0 V</text>
      </g>

      {/* LISN interior — DM/CM probes + 50Ω receiver */}
      <g>
        {/* inductor on top rail (going through LISN) */}
        <InductorH x={lisn.x + 30} y={VIN_Y} w={50} className="wire power" />
        <InductorH x={lisn.x + 30} y={RTN_Y} w={50} className="wire return" />
        <text x={lisn.x + lisn.w / 2} y={240} textAnchor="middle" className="node-sub" style={{ fontSize: 9 }}>50 µH</text>

        {/* 50 Ω termination + receiver block */}
        <rect x={lisn.x + 100} y={250} width={90} height={70} rx={2} fill="var(--plot-bg)" stroke="var(--border-strong)" strokeWidth="1"/>
        <text x={lisn.x + 145} y={272} textAnchor="middle" className="node-sub" style={{ fontWeight: 600 }}>EMI RX</text>
        <text x={lisn.x + 145} y={288} textAnchor="middle" className="node-sub" style={{ fontSize: 9 }}>{lisnRx}</text>
        <text x={lisn.x + 145} y={302} textAnchor="middle" className="node-sub" style={{ fontSize: 9 }}>quasi-peak</text>
        {/* Probe taps from rails to receiver */}
        <line x1={lisn.x + 100} y1={260} x2={lisn.x + 85} y2={260} stroke="var(--text-faint)" strokeDasharray="2 2"/>
        <line x1={lisn.x + 85} y1={260} x2={lisn.x + 85} y2={VIN_Y + 2} stroke="var(--text-faint)" strokeDasharray="2 2"/>
        <Junction x={lisn.x + 85} y={VIN_Y} />
        <line x1={lisn.x + 100} y1={310} x2={lisn.x + 85} y2={310} stroke="var(--text-faint)" strokeDasharray="2 2"/>
        <line x1={lisn.x + 85} y1={310} x2={lisn.x + 85} y2={RTN_Y - 2} stroke="var(--text-faint)" strokeDasharray="2 2"/>
        <Junction x={lisn.x + 85} y={RTN_Y} />
      </g>

      {/* CABLE interior — just labels */}
      <g>
        <text x={cable.x + cable.w / 2} y={260} textAnchor="middle" className="node-sub" style={{ fontSize: 9 }}>distributed L/C model</text>
        <text x={cable.x + cable.w / 2} y={275} textAnchor="middle" className="node-sub" style={{ fontSize: 9, opacity: 0.7 }}>1 nH/mm · 1 pF/mm</text>
      </g>

      {/* DUT interior — neutral. We do NOT draw a fabricated buck here; the
          real per-net circuit is the table below, and a faithful schematic
          render is the queued follow-up. The DUT box sits on both rails
          (drawn behind) and feeds the load via a generic output trace. */}
      <g>
        <text x={dut.x + dut.w / 2} y={250} textAnchor="middle" className="node-sub" style={{ fontWeight: 600, fontSize: 13 }}>user circuit</text>
        <text x={dut.x + dut.w / 2} y={270} textAnchor="middle" className="node-sub" style={{ fontSize: 10, opacity: 0.85 }}>{dutSubLabel}</text>
        <text x={dut.x + dut.w / 2} y={290} textAnchor="middle" className="ghost-label" style={{ fontSize: 8.5, opacity: 0.55 }}>schematic render queued — real circuit is in the net table</text>
        {/* generic output trace to the load */}
        <line x1={dut.x + dut.w} y1={270} x2={load.x} y2={270} className="wire" stroke="oklch(0.70 0.18 var(--accent-h))" />
      </g>

      {/* LOAD interior */}
      <g>
        {/* Resistor zig-zag */}
        <path d={`M ${load.x + load.w/2} 230 l -8 6 l 16 12 l -16 12 l 16 12 l -16 12 l 8 6`}
              fill="none" stroke="var(--text-dim)" strokeWidth="1.2" />
        <line x1={load.x + load.w/2} y1={270} x2={load.x} y2={270} className={`wire ${wireOn("VOUT")}`} stroke="oklch(0.70 0.18 var(--accent-h))" />
        <line x1={load.x + load.w/2} y1={290} x2={load.x + load.w/2} y2={RTN_Y} className={`wire return ${wireOn("PGND")}`} />
        <Junction x={load.x + load.w/2} y={RTN_Y} />
      </g>

      {/* === Rails — SEGMENTED so a rail connects TO each series component
          and never draws straight through it. A continuous line over a coil
          reads as a short; over a zig-zag it reads as a *variable* resistor.
          Gaps: the LISN series inductors (both rails) and the input-rail
          series splice (VIN only, when parasitics are shown). =============== */}
      {(() => {
        const sCx = supply.x + supply.w / 2;
        const indX1 = lisn.x + 30, indX2 = lisn.x + 80;     // LISN coil span
        const serX1 = lisn.x + lisn.w, serX2 = cable.x;     // series-splice span
        const vinSegs = withParasitics
          ? [[sCx, indX1], [indX2, serX1], [serX2, dut.x + dut.w]]
          : [[sCx, indX1], [indX2, dut.x + dut.w]];
        const rtnSegs = [[sCx, indX1], [indX2, load.x + load.w / 2]];
        return (
          <g>
            {vinSegs.map(([a, z], i) => (
              <line key={`v${i}`} x1={a} y1={VIN_Y} x2={z} y2={VIN_Y}
                    className={`wire power ${wireOn("VIN")}`} strokeWidth="1.6" />
            ))}
            {rtnSegs.map(([a, z], i) => (
              <line key={`r${i}`} x1={a} y1={RTN_Y} x2={z} y2={RTN_Y}
                    className={`wire return ${wireOn("PGND")}`} strokeWidth="1.6" />
            ))}
            {/* terminal dots where the LISN coils meet the rails */}
            <Junction x={indX1} y={VIN_Y} /><Junction x={indX2} y={VIN_Y} />
            <Junction x={indX1} y={RTN_Y} /><Junction x={indX2} y={RTN_Y} />
          </g>
        );
      })()}

      {/* === Parasitics — honest summary ===================================
          The fabricated per-net chips (Cp_VIN/SW/VOUT/VCC at fixed values)
          were removed — they invented nets that aren't in the real design.
          A representative series splice + shunt show *where* parasitics
          attach on the testbench; the real per-net values (count below)
          are in the table. Faithful per-net placement is the queued
          schematic render. */}
      {withParasitics && (
        <g>
          <ParSeries xStart={lisn.x + lisn.w} xEnd={cable.x} y={VIN_Y} label="R+L  ·  supply trace" netName="__supply" labelBelow />
          <ParShunt x={cable.x + cable.w + 30} yBus={RTN_Y} label="shunt C  ·  per net" netName="__shunt" />
          {paraCount > 0 && (
            <text x={dut.x + dut.w / 2} y={RTN_Y + 56} textAnchor="middle" className="ghost-label" style={{ fontSize: 10, opacity: 0.7 }}>
              {paraCount} per-net parasitic{paraCount === 1 ? "" : "s"} on the testbench — values in the table
            </text>
          )}
        </g>
      )}

      {/* === Stage labels strip below ======================================== */}
      <g transform={`translate(0, ${H - 12})`}>
        {[
          { x: supply.x + supply.w / 2, label: "01 · SOURCE" },
          { x: lisn.x + lisn.w / 2,     label: "02 · LISN" },
          { x: cable.x + cable.w / 2,   label: "03 · CABLE" },
          { x: dut.x + dut.w / 2,       label: "04 · DUT" },
          { x: load.x + load.w / 2,     label: "05 · LOAD" },
        ].map(s => (
          <text key={s.label} x={s.x} y={0} textAnchor="middle" className="ghost-label" style={{ fontSize: 9, letterSpacing: "0.14em", opacity: 0.55 }}>
            {s.label}
          </text>
        ))}
      </g>

      {/* === Captions ======================================================= */}
      <text x={16} y={28} className="ghost-label" style={{ fontSize: 9, opacity: 0.6 }}>
        illustrative testbench frame — the imported circuit is the net table, not this drawing
      </text>
      <text x={W - 16} y={28} textAnchor="end" className="ghost-label" style={{ fontSize: 9, opacity: 0.55 }}>
        click a block or rail to inspect
      </text>
    </svg>
  );
};

window.TestbenchDiagram = TestbenchDiagram;
