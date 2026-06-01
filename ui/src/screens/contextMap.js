// Pure user_context field-mapping + merge logic for the Import & context
// screen. Extracted from import.jsx so it can be unit-tested under
// `node --test` without a DOM or React (see contextMap.test.js).
//
// The flat HOOKS.md field names don't map 1:1 to the backend's nested
// user_context shape; FIELD_MAP pins each `data-field` to its path +
// value coercion. mergeContextFromFields() applies that mapping onto a
// deep copy of the loaded context so unrelated keys round-trip untouched.

// Mapping: data-field name -> { path: list of keys into user_context,
// type: how to coerce the string form value, [unitFn]: optional
// (raw, existing) -> value transform applied on save (UI->backend) }.
export const FIELD_MAP = {
  // DC operating point — top-level
  input_voltage_v:        { path: ["input_voltage_v"],        type: "number" },
  output_voltage_v:       { path: ["output_voltage_v"],       type: "number" },
  load_current_a:         { path: ["load_current_a"],         type: "number" },
  switching_frequency_hz: { path: ["switching_frequency_hz"], type: "number" },
  cable_length_m:         { path: ["cable_length_m"],         type: "number" },
  ambient_t_c:            { path: ["ambient_t_c"],            type: "number" },
  // Testbench wiring — nested under `testbench_wiring`
  supply_net:    { path: ["testbench_wiring", "dut_supply_net"], type: "string" },
  return_net:    { path: ["testbench_wiring", "dut_return_net"], type: "string" },
  lisn_config:   { path: ["testbench_wiring", "lisn_mode"],      type: "string" },
  signals_to_track: { path: ["signals"], type: "list", unitFn: _mergeSignals },
  // PCB stack-up — nested under `pcb`.
  pcb_layers:          { path: ["pcb", "layers"], type: "number" },
  pcb_copper_oz:       { path: ["pcb", "copper_oz"], type: "number" },
  pcb_dielectric_mm:   { path: ["pcb", "dielectric_height_to_plane_mm"], type: "number" },
  pcb_prepreg_mm:      { path: ["pcb", "prepreg_mm"], type: "number" },
  pcb_trace_width_mm:  { path: ["pcb", "trace_width_mm"], type: "number" },
  pcb_trace_length_mm: { path: ["pcb", "trace_length_mm"], type: "number" },
};

// Look up a nested value via a path list, returning "" if missing.
export const _get = (obj, path) => {
  let v = obj;
  for (const k of path) {
    if (v == null || typeof v !== "object") return "";
    v = v[k];
  }
  return v == null ? "" : v;
};

export const _set = (obj, path, value) => {
  let cur = obj;
  for (let i = 0; i < path.length - 1; i++) {
    if (cur[path[i]] == null || typeof cur[path[i]] !== "object") cur[path[i]] = {};
    cur = cur[path[i]];
  }
  cur[path[path.length - 1]] = value;
};

export const _coerce = (value, type) => {
  if (type === "number") {
    // A blank numeric field means "unset", not 0 — return null so the
    // caller skips it and the previously-saved value round-trips. (JS
    // `Number("")` is 0, which would silently overwrite e.g. a null
    // switching frequency with a misleading "DC".)
    if (value === "" || value == null) return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  if (type === "list") return value;       // unitFn handles it
  return String(value ?? "");
};

// Signals round-trip: the screen's input only carries the comma-joined
// names, so a naive rebuild would discard each signal's provenance
// (unit / rationale / from_label) and reset confidence. Instead: when the
// set of names is unchanged, return the existing entries untouched; when
// it changes, reuse the existing entry for any kept name and synthesize a
// fresh one (confidence 0.8) only for genuinely new names.
function _mergeSignals(text, existing) {
  const names = String(text || "")
    .split(",").map((s) => s.trim()).filter(Boolean);
  const prev = Array.isArray(existing) ? existing : [];
  const sameNames =
    names.length === prev.length && names.every((n, i) => prev[i] && prev[i].name === n);
  if (sameNames) return prev;
  const byName = new Map(prev.map((s) => [s.name, s]));
  return names.map(
    (name) =>
      byName.get(name) || {
        name, kind: "voltage", expr: `V(${name})`, source: "user", confidence: 0.8,
      },
  );
}

// Merge raw [data-field] -> string-value pairs into a deep copy of the
// loaded context. Keys not present in fieldValues (or not in FIELD_MAP)
// are left exactly as they were, so the screen never disturbs context it
// doesn't own (`simulation`, `parasitics`, `notes`, …).
export function mergeContextFromFields(ctx, fieldValues) {
  const merged = JSON.parse(JSON.stringify(ctx || {}));
  for (const key of Object.keys(fieldValues || {})) {
    const spec = FIELD_MAP[key];
    if (!spec) continue;                    // not wired in this slice
    const raw = fieldValues[key];
    if (spec.unitFn) {
      _set(merged, spec.path, spec.unitFn(raw, _get(merged, spec.path)));
    } else {
      const value = _coerce(raw, spec.type);
      if (value !== null && value !== "") _set(merged, spec.path, value);
    }
  }
  return merged;
}
