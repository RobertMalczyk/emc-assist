// Round-trip regression tests for the Import & context save path.
// Run with `npm test` (Node's built-in `node --test`, no extra deps).
//
// These guard the two bugs that silently corrupted user_context.json:
//   1. a blank numeric field used to be written as 0 (null -> 0);
//   2. saving rebuilt the signals list from names alone, dropping each
//      signal's unit/rationale/from_label and resetting confidence.

import test from "node:test";
import assert from "node:assert/strict";

import { mergeContextFromFields, _coerce } from "./contextMap.js";

test("blank numeric field stays unset, not 0", () => {
  const ctx = { switching_frequency_hz: null, input_voltage_v: 12 };
  const merged = mergeContextFromFields(ctx, {
    switching_frequency_hz: "",   // user left it blank
    input_voltage_v: "12",
  });
  // null ("unknown") must survive — never become 0 ("DC").
  assert.equal(merged.switching_frequency_hz, null);
  assert.equal(merged.input_voltage_v, 12);
});

test("blank numeric field does not create a 0 key", () => {
  const merged = mergeContextFromFields({}, {
    output_voltage_v: "",
    ambient_t_c: "",
  });
  assert.ok(!("output_voltage_v" in merged), "output_voltage_v must not be added");
  assert.ok(!("ambient_t_c" in merged), "ambient_t_c must not be added");
});

test("_coerce maps empty string to null for numbers", () => {
  assert.equal(_coerce("", "number"), null);
  assert.equal(_coerce("0", "number"), 0);     // an explicit 0 is honoured
  assert.equal(_coerce("3.3", "number"), 3.3);
  assert.equal(_coerce("nope", "number"), null);
});

test("signal metadata survives a save when names are unchanged", () => {
  const ctx = {
    signals: [
      { name: "Vin", kind: "voltage", expr: "V(VIN)", source: "user",
        unit: "V", confidence: 1.0, rationale: "FLAG label VIN", from_label: "VIN" },
      { name: "Vout", kind: "voltage", expr: "V(VOUT)", source: "user",
        unit: "V", confidence: 1.0, rationale: "FLAG label VOUT", from_label: "VOUT" },
    ],
  };
  const merged = mergeContextFromFields(ctx, { signals_to_track: "Vin, Vout" });
  // Same names in, full provenance back out — including upper-case expr.
  assert.deepEqual(merged.signals, ctx.signals);
  assert.equal(merged.signals[0].confidence, 1.0);
  assert.equal(merged.signals[0].expr, "V(VIN)");
  assert.equal(merged.signals[0].from_label, "VIN");
});

test("a newly added signal name is synthesised, kept ones preserved", () => {
  const ctx = {
    signals: [
      { name: "Vin", kind: "voltage", expr: "V(VIN)", source: "user",
        unit: "V", confidence: 1.0, from_label: "VIN" },
    ],
  };
  const merged = mergeContextFromFields(ctx, { signals_to_track: "Vin, Vsw" });
  assert.equal(merged.signals.length, 2);
  // Kept name keeps its metadata...
  assert.deepEqual(merged.signals[0], ctx.signals[0]);
  // ...new name is a fresh user entry at the default confidence.
  assert.deepEqual(merged.signals[1], {
    name: "Vsw", kind: "voltage", expr: "V(Vsw)", source: "user", confidence: 0.8,
  });
});

test("keys the screen does not own round-trip untouched", () => {
  const ctx = {
    simulation: { tran_directive: ".tran 0 1m 0 5n" },
    parasitics: { per_net: { N013: { skip: true, l_nh: 30 } } },
    notes: "long provenance note",
    pcb: { layers: 2, trace_width_mm: 1.0 },
  };
  const merged = mergeContextFromFields(ctx, {
    pcb_prepreg_mm: "0.1",   // the only field we touch
  });
  assert.deepEqual(merged.simulation, ctx.simulation);
  assert.deepEqual(merged.parasitics, ctx.parasitics);
  assert.equal(merged.notes, ctx.notes);
  // The touched nested key is set without disturbing its siblings.
  assert.equal(merged.pcb.prepreg_mm, 0.1);
  assert.equal(merged.pcb.layers, 2);
  assert.equal(merged.pcb.trace_width_mm, 1.0);
});
