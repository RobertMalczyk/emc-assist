import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
// Spectrum plot — FFT in conducted-EMI band 150 kHz – 30 MHz.
// Designed to take a second (measured) trace overlay.

// Generate plausible-looking sim trace
function genSimTrace(seed = 1, peaks = [{ f: 540e3, h: 78, w: 30e3 }, { f: 1.08e6, h: 70, w: 50e3 }, { f: 1.62e6, h: 60, w: 60e3 }, { f: 2.2e6, h: 53, w: 80e3 }, { f: 4.5e6, h: 44, w: 200e3 }, { f: 9e6, h: 36, w: 400e3 }]) {
  const N = 200;
  // log f
  const fMin = 150e3, fMax = 30e6;
  const logMin = Math.log10(fMin), logMax = Math.log10(fMax);
  const pts = [];
  // pseudo-random
  let s = seed;
  const rand = () => { s = (s * 9301 + 49297) % 233280; return s / 233280; };
  for (let i = 0; i < N; i++) {
    const lf = logMin + (logMax - logMin) * (i / (N - 1));
    const f = Math.pow(10, lf);
    let v = 28 - 4 * (lf - logMin); // gentle decay baseline ~28 dBuV → 4 dBuV decay
    for (const p of peaks) {
      const sigma = p.w / 2;
      v += p.h * Math.exp(-Math.pow((f - p.f) / sigma, 2));
    }
    v += (rand() - 0.5) * 3.5; // noise
    pts.push({ f, db: v });
  }
  return pts;
}

function genMeasuredTrace() {
  // Similar but shifted & noisier — emphasises why measured ≠ sim.
  return genSimTrace(7, [
    { f: 540e3, h: 82, w: 25e3 },
    { f: 1.08e6, h: 73, w: 45e3 },
    { f: 1.62e6, h: 58, w: 70e3 },
    { f: 2.2e6, h: 56, w: 110e3 },
    { f: 4.5e6, h: 49, w: 250e3 },
    { f: 8.4e6, h: 41, w: 600e3 },
    { f: 18e6, h: 32, w: 1.2e6 },
  ]).map(p => ({ ...p, db: p.db + 1.5 }));
}

const SpectrumPlot = ({
  showSim = true,
  showMeasured = false,
  showLimit = true,
  limitType = "Class B QP",
  height = 280,
  caption,
}) => {
  const W = 720, H = height;
  const padL = 56, padR = 16, padT = 18, padB = 36;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const sim = useMemo(() => genSimTrace(3), []);
  const meas = useMemo(() => genMeasuredTrace(), []);

  const fMin = 150e3, fMax = 30e6;
  const dbMin = 0, dbMax = 110;
  const lf = f => Math.log10(f);
  const xS = f => padL + ((lf(f) - lf(fMin)) / (lf(fMax) - lf(fMin))) * plotW;
  const yS = db => padT + plotH - ((db - dbMin) / (dbMax - dbMin)) * plotH;

  // Limit line: piecewise CISPR 22/32 Class B QP (rough)
  const limitPts = [
    [150e3, 66], [500e3, 56], [500e3, 56], [5e6, 56], [5e6, 60], [30e6, 60],
  ];

  const pathFor = arr => arr.map((p, i) => `${i ? "L" : "M"} ${xS(p.f).toFixed(1)} ${yS(p.db).toFixed(1)}`).join(" ");
  const limitPath = limitPts.map((p, i) => `${i ? "L" : "M"} ${xS(p[0]).toFixed(1)} ${yS(p[1]).toFixed(1)}`).join(" ");

  // Grid: log decade ticks
  const xTicks = [150e3, 300e3, 500e3, 1e6, 3e6, 10e6, 30e6];
  const yTicks = [0, 20, 40, 60, 80, 100];

  return (
    <div className="plot" style={{ height }}>
      <svg viewBox={`0 0 ${W} ${H}`}>
        {/* Conducted band shading */}
        <rect className="band-fill" x={xS(fMin)} y={padT} width={xS(fMax) - xS(fMin)} height={plotH} />

        {/* Grid */}
        {xTicks.map(f => (
          <line key={`gx-${f}`} className="grid-line" x1={xS(f)} y1={padT} x2={xS(f)} y2={padT + plotH} strokeWidth="1" />
        ))}
        {yTicks.map(db => (
          <line key={`gy-${db}`} className="grid-line" x1={padL} y1={yS(db)} x2={padL + plotW} y2={yS(db)} strokeWidth="1" />
        ))}

        {/* Axis */}
        <line className="axis-line" x1={padL} y1={padT} x2={padL} y2={padT + plotH} />
        <line className="axis-line" x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} />

        {/* X tick labels */}
        {xTicks.map(f => (
          <text key={`xt-${f}`} x={xS(f)} y={padT + plotH + 14} textAnchor="middle" className="axis-tick">{window.fmt.hz(f)}</text>
        ))}
        {/* Y tick labels */}
        {yTicks.map(db => (
          <text key={`yt-${db}`} x={padL - 8} y={yS(db) + 3} textAnchor="end" className="axis-tick">{db}</text>
        ))}

        {/* Axis labels */}
        <text x={padL + plotW / 2} y={H - 8} textAnchor="middle" className="axis-label">FREQUENCY</text>
        <text x={14} y={padT + plotH / 2} textAnchor="middle" className="axis-label" transform={`rotate(-90 14 ${padT + plotH / 2})`}>dBµV</text>

        {/* Limit line */}
        {showLimit && (
          <>
            <path d={limitPath} className="limit-line" />
            <text x={padL + plotW - 6} y={yS(60) - 4} textAnchor="end" className="axis-tick" fill="var(--trace-limit)">
              {limitType}
            </text>
          </>
        )}

        {/* Simulated trace */}
        {showSim && <path d={pathFor(sim)} className="trace-sim" />}
        {/* Measured trace */}
        {showMeasured && <path d={pathFor(meas)} className="trace-meas" />}

        {/* Caption corner */}
        <g>
          <rect x={padL + 8} y={padT + 6} width="170" height="20" fill="var(--panel)" stroke="var(--border)" rx="3" />
          <text x={padL + 16} y={padT + 20} className="axis-tick">CONDUCTED 150 kHz – 30 MHz</text>
        </g>
      </svg>
      {caption && (
        <div style={{
          position: "absolute", right: 12, top: 10,
          fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)",
        }}>{caption}</div>
      )}
    </div>
  );
};

const SpectrumLegend = ({ showSim, showMeasured, showLimit }) => (
  <div className="legend">
    {showSim && (
      <span className="item"><span className="swatch" style={{ background: "var(--trace-sim)"}}/> simulated</span>
    )}
    {showMeasured && (
      <span className="item"><span className="swatch" style={{ background: "var(--trace-meas)"}}/> measured (live)</span>
    )}
    {showLimit && (
      <span className="item" style={{ color: "var(--trace-limit)"}}>
        <span className="swatch dashed" style={{ color: "var(--trace-limit)"}}/> CISPR Class B QP
      </span>
    )}
    <span className="item" style={{ color: "var(--sev-med)"}}>
      <span className="swatch" style={{ background: "oklch(0.78 0.16 75 / 0.5)"}}/> conducted band
    </span>
  </div>
);

window.SpectrumPlot = SpectrumPlot;
window.SpectrumLegend = SpectrumLegend;
