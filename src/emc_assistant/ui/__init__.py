"""Desktop UI (M3) — a pywebview shell over the service layer.

- ``bridge`` — the Python⇄JS ``Api`` object the page calls.
- ``log_handler`` — captures the logging seam for the UI's live log.
- ``app`` — the pywebview entry point (``emc-assistant-ui``).

The shell adds no analysis logic; it is a second front-end over
``emc_assistant.service``, exactly like ``cli.py``. See
``docs/design/ui_integration.md``.
"""
