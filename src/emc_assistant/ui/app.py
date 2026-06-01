"""pywebview desktop shell — entry point for the M3 UI.

Loads the UI HTML, exposes the :class:`Api` bridge to the page, and
streams the logging seam into the page's live log. Run with::

    emc-assistant-ui

Needs the ``[ui]`` extra (``pip install 'emc-assistant[ui]'``) for
``pywebview``. The shell adds no analysis logic — it is a second
front-end over ``emc_assistant.service``. See ``docs/design/ui_integration.md``.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from emc_assistant.logging_setup import configure_logging, ensure_utf8_stdio
from emc_assistant.ui.bridge import Api
from emc_assistant.ui.log_handler import QueueLogHandler

# The real UI is the Vite + React build at ui/ — `npm run build` writes
# the static bundle (one HTML + the assets/ tree) into ui/web/ alongside
# this file. We prefer that build when present; the placeholder
# `index.html` next to this file is the fallback before the first build.
_WEB_DIR = Path(__file__).resolve().parent / "web"
INDEX_HTML = (
    _WEB_DIR / "index.html"
    if (_WEB_DIR / "index.html").is_file()
    else Path(__file__).resolve().parent / "index.html"
)

_POLL_SECONDS = 0.2
# Cap how many log lines we hand the page per tick. A full pipeline run can
# emit a burst of lines; sending them all (one evaluate_js per line) floods
# the WebView2 renderer and segfaults the window. We batch a tick into one
# call and keep only the most recent lines (the page retains a tail anyway).
_MAX_LINES_PER_TICK = 300


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1250 on a Polish install, which cannot
    # encode characters the pipeline logs (→, ≈, Ω, the non-breaking hyphen in
    # LLM-written text). The CLI does this; the UI must too, or every such log
    # line throws UnicodeEncodeError. See logging_setup.ensure_utf8_stdio.
    ensure_utf8_stdio()
    try:
        import webview  # noqa: F401 - optional [ui] dependency
    except ImportError:
        print(
            "pywebview is not installed. Install the UI extra:\n"
            "  pip install 'emc-assistant[ui]'",
            file=sys.stderr,
        )
        return 1

    # Bounded queue so a sustained log flood can't grow memory without limit
    # (the handler drops on Full; the page only keeps a tail anyway).
    log_handler = QueueLogHandler(maxsize=20000)
    configure_logging("info", ui_handler=log_handler)

    # Bridge the app-level LTspice path into the environment so any pipeline
    # run triggered from the UI can discover LTspice without the user having
    # to export LTSPICE_PATH manually. The backend's discovery order is
    # project.yaml -> LTSPICE_PATH -> common paths -> which; this seeds the
    # env step from the user's saved setting.
    import os as _os

    from emc_assistant.service import settings as _settings

    _ltspice = _settings.load_settings().ltspice_path
    if _ltspice and not _os.environ.get("LTSPICE_PATH"):
        _os.environ["LTSPICE_PATH"] = _ltspice

    window = webview.create_window(
        "EMC/LTspice Assistant",
        str(INDEX_HTML),
        js_api=Api(),
        width=1280,
        height=860,
        min_size=(960, 640),
    )

    def _pump_log() -> None:
        """Drain captured log records and stream them to the page in ONE
        evaluate_js call per tick (batched + rate-capped).

        Sending one evaluate_js per record floods the WebView2 renderer on a
        heavy run and crashes the window (exit 139). Here each tick collects
        all pending records, caps the burst to the most recent
        ``_MAX_LINES_PER_TICK`` (coalescing the rest into one notice), and
        hands the page a single array via ``window.appLogBatch`` (falling
        back to per-record ``window.appLog`` for older bundles)."""
        while True:
            entries = log_handler.drain()
            if entries:
                if len(entries) > _MAX_LINES_PER_TICK:
                    dropped = len(entries) - _MAX_LINES_PER_TICK
                    entries = entries[-_MAX_LINES_PER_TICK:]
                    entries.insert(0, {
                        "timestamp": entries[0]["timestamp"],
                        "level": "INFO",
                        "component": "ui",
                        "message": f"… {dropped} earlier log line(s) coalesced",
                    })
                payload = json.dumps(entries)
                js = (
                    "(function(a){"
                    "if(window.appLogBatch){window.appLogBatch(a);}"
                    "else if(window.appLog){for(var i=0;i<a.length;i++)"
                    "window.appLog(a[i]);}"
                    f"}})({payload})"
                )
                try:
                    window.evaluate_js(js)
                except Exception:  # noqa: BLE001 - window may be closing
                    return
            time.sleep(_POLL_SECONDS)

    webview.start(_pump_log)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
