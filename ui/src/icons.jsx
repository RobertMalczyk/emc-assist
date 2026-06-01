import React, { useState, useEffect, useMemo, useRef, useCallback, useLayoutEffect } from "react";
// Icons — small line icons in scope-firmware spirit. Single stroke, 16px.
const Icon = ({ name, size = 16, ...rest }) => {
  const s = size;
  const P = (d, extra) => (
    <svg width={s} height={s} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" {...rest}>
      {extra}
      {d && <path d={d} />}
    </svg>
  );
  switch (name) {
    case "folder":
      return P("M1.5 4.5v8a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1H8L6.5 3.5h-4a1 1 0 0 0-1 1Z");
    case "plus":
      return P("M8 3v10M3 8h10");
    case "schematic":
      return P("M1.5 8h3l1.5-3 3 6 1.5-3h3M1.5 8a1 1 0 1 1-2 0 1 1 0 0 1 2 0Zm15 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z");
    case "import":
      return P("M8 1.5v8M5 6.5l3 3 3-3M2 13.5h12");
    case "nets":
      return P("M3 3v10M13 3v10M3 5h10M3 11h10M6 8h4");
    case "testbench":
      return P("M2 3h12v6H2zM5 9v3M11 9v3M2 12h12");
    case "play":
      return P("M4 3l9 5-9 5z");
    case "spectrum":
      return P("M1.5 13V8m2.5 5V5m2.5 8V9m2.5 4V3m2.5 10V7m2.5 6V10");
    case "list":
      return P("M2 4h12M2 8h12M2 12h12");
    case "report":
      return P("M3 1.5h7l3 3v10a0.5.5 0 0 1-.5.5h-9.5a0.5.5 0 0 1-.5-.5v-12a0.5.5 0 0 1 .5-.5zM10 1.5v3h3M5.5 8h5M5.5 11h5");
    case "lab":
      return P("M6 1.5v4l-3.5 7a1 1 0 0 0 .9 1.5h9.2a1 1 0 0 0 .9-1.5L10 5.5v-4M5 1.5h6M5 9h6");
    case "brain":
      return P("M5.5 13.5a2 2 0 0 1-2-2v-1a2 2 0 0 1-1-3 2 2 0 0 1 1-3v-1a2 2 0 0 1 4 0v9a2 2 0 0 1-2 1zM10.5 13.5a2 2 0 0 1-2-2v-9a2 2 0 0 1 4 0v1a2 2 0 0 1 1 3 2 2 0 0 1-1 3v1a2 2 0 0 1-2 2z");
    case "gear":
      return P("M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM13.5 8a5.5 5.5 0 0 0-.1-1.1l1.4-1.1-1.4-2.4-1.7.5a5.5 5.5 0 0 0-1.9-1.1L9.5 1h-3l-.3 1.8a5.5 5.5 0 0 0-1.9 1.1L2.6 3.4 1.2 5.8l1.4 1.1A5.5 5.5 0 0 0 2.5 8c0 .4 0 .7.1 1.1L1.2 10.2l1.4 2.4 1.7-.5c.5.5 1.2.9 1.9 1.1l.3 1.8h3l.3-1.8a5.5 5.5 0 0 0 1.9-1.1l1.7.5 1.4-2.4-1.4-1.1c.1-.4.1-.7.1-1.1z");
    case "lock":
      return P("M4 7V5a4 4 0 0 1 8 0v2M3 7h10v7H3z");
    case "unlock":
      return P("M4 7V5a4 4 0 0 1 7.5-2M3 7h10v7H3z");
    case "check":
      return P("M3 8.5l3 3 7-7");
    case "x":
      return P("M3 3l10 10M13 3L3 13");
    case "info":
      return P("M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM8 7v4.5M8 5v.01");
    case "alert":
      return P("M7.1 1.8 1.5 12a1 1 0 0 0 .9 1.5h11.2a1 1 0 0 0 .9-1.5L8.9 1.8a1 1 0 0 0-1.8 0zM8 6v3M8 11v.01");
    case "clock":
      return P("M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM8 4.5V8l2.5 1.5");
    case "arrow-right":
      return P("M3 8h10M9 4l4 4-4 4");
    case "chevron-right":
      return P("M6 3l5 5-5 5");
    case "chevron-down":
      return P("M3 6l5 5 5-5");
    case "chevron-up":
      return P("M3 10l5-5 5 5");
    case "expand":
      return P("M2 6V2h4M14 6V2h-4M2 10v4h4M14 10v4h-4");
    case "download":
      return P("M8 2v8M5 7l3 3 3-3M2 13.5h12");
    case "save":
      return P("M2.5 2.5h9l2 2v9a.5.5 0 0 1-.5.5h-11a.5.5 0 0 1-.5-.5v-11a.5.5 0 0 1 .5-.5zM4.5 2.5v4h7v-4M4.5 14v-5h7v5");
    case "sun":
      return P("M8 4.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM8 .5v2M8 13.5v2M.5 8h2M13.5 8h2M2.5 2.5l1.4 1.4M12.1 12.1l1.4 1.4M2.5 13.5l1.4-1.4M12.1 3.9l1.4-1.4");
    case "moon":
      return P("M13.5 9.5A6 6 0 1 1 6.5 2.5a5 5 0 0 0 7 7z");
    case "eye":
      return P("M.8 8C2.2 5 4.9 3 8 3s5.8 2 7.2 5C13.8 11 11.1 13 8 13S2.2 11 .8 8zM8 5.5A2.5 2.5 0 1 0 8 10.5 2.5 2.5 0 0 0 8 5.5z");
    case "search":
      return P("M7 12.5a5.5 5.5 0 1 0 0-11 5.5 5.5 0 0 0 0 11zM11 11l3.5 3.5");
    case "drag":
      return P("M6 3v.01M6 8v.01M6 13v.01M10 3v.01M10 8v.01M10 13v.01");
    case "filter":
      return P("M1.5 2.5h13l-5 7v4l-3-1v-3z");
    case "ai":
      return P("M8 3v10M3 8h10M5 5l6 6M11 5l-6 6");
    default:
      return P("M2 2l12 12M14 2L2 14");
  }
};

window.Icon = Icon;
