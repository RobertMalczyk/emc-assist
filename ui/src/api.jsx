import React, { useMemo } from "react";

/* Bridge access — `window.pywebview.api.*` when the page is loaded by the
   pywebview shell, a small mock stub otherwise so Vite dev / a plain
   browser tab still renders something for design review.

   `Api` (`src/emc_assistant/ui/bridge.py`) returns every value as either
   `{ok: true, data: <jsonable>}` or `{ok: false, error: {message, ...}}`
   — see `docs/ui_integration.md`. The mock here mimics that envelope so
   consumer code is identical across both modes. */

const _MOCK_PROJECTS = [
  { name: "(mock) buck_sync_12v_3v3", path: "(mock) ~/emc/buck_sync_12v_3v3.emcproj" },
  { name: "(mock) hotswap_inrush_48v", path: "(mock) ~/emc/hotswap_inrush_48v.emcproj" },
];

const _ok  = (data) => ({ ok: true,  data });
const _err = (message) => ({ ok: false, error: { message, details: [] } });

const _mockApi = {
  ping:           () => _ok({ pong: true, version: "(mock — browser dev mode)" }),
  pick_folder:    () => _ok({ path: null }),
  list_projects:  () => _ok(_MOCK_PROJECTS),
  create_project: () => _err("create_project: only available inside pywebview"),
  validate_project: () => _err("validate_project: only available inside pywebview"),
  project_status: () => _err("project_status: only available inside pywebview"),
  load_context:   () => _err("load_context: only available inside pywebview"),
  save_context:   () => _err("save_context: only available inside pywebview"),
  estimate_per_net: () => _err("estimate_per_net: only available inside pywebview"),
  compose_testbench: () => _err("compose_testbench: only available inside pywebview"),
  run_pipeline:   () => _err("run_pipeline: only available inside pywebview"),
  list_recommendations: () => _err("list_recommendations: only available inside pywebview"),
  accept_recommendation: () => _err("accept_recommendation: only available inside pywebview"),
  reject_recommendation: () => _err("reject_recommendation: only available inside pywebview"),
  read_artifact:  () => _err("read_artifact: only available inside pywebview"),
  inspect_raw:    () => _err("inspect_raw: only available inside pywebview"),
  quasi_peak:     () => _err("quasi_peak: only available inside pywebview"),
  quasi_peak_sweep: () => _err("quasi_peak_sweep: only available inside pywebview"),
};

const isPywebview = () =>
  typeof window !== "undefined" && !!window.pywebview && !!window.pywebview.api;

const getApi = () => (isPywebview() ? window.pywebview.api : _mockApi);

// Stable proxy that resolves the real bridge (or mock) at **call time**,
// not at hook-mount time. pywebview injects `window.pywebview.api`
// asynchronously after the page loads (the `pywebviewready` event), so a
// screen that mounts first must not capture the mock forever — every
// `api.method(...)` re-checks and routes to the live bridge once present.
const _apiProxy = new Proxy({}, {
  get(_t, prop) {
    if (typeof prop !== "string" || prop === "then") return undefined;
    return (...args) => {
      const target = getApi();
      const fn = target[prop];
      if (typeof fn !== "function") {
        return { ok: false, error: { message: `bridge method '${prop}' unavailable`, details: [] } };
      }
      return fn.apply(target, args);
    };
  },
});

// React hook — returns the stable call-time proxy. Bare `useApi()` in
// screen files resolves to this via globalThis (the window-global pattern).
const useApi = () => _apiProxy;

window.useApi = useApi;
window.isPywebview = isPywebview;
window.emcApi = { isPywebview, getApi };
