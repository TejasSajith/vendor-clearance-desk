"""Vercel serverless entry for the Vendor Clearance Desk (Unmask) web UI.

Vercel's @vercel/python builder statically scans this file for a TOP-LEVEL `app` (or `application`/`handler`/
`server`). Keep the final `app = ...` at module indent 0, or the build fails with "couldn't find a top level app".

Demo mode only unless keys are supplied (see docs/vercel.md). Jobs run inline because a serverless function cannot
keep a background worker; Vercel sets VERCEL=1, so app/server.py uses /tmp automatically.

Access: open demo -> leave APP_PASSWORD unset; gated demo -> set APP_PASSWORD in the Vercel project.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # put the repo root on the import path


def _make_app():
    """The real ASGI app, or — if cold start fails — a tiny stdlib ASGI app that serves the traceback as plain text,
    so the real Python error is visible over HTTP instead of Vercel's opaque 500. (Diagnostic marker DIAG-v2.)"""
    try:
        from app.server import create_app
        # require_password=False lets the demo boot without a password; if APP_PASSWORD is set the gate still applies.
        return create_app(require_password=False)
    except BaseException:   # noqa: BLE001 -- catch everything, including import errors, so we can report it
        import traceback
        info = f"DIAG-v2 boot failed\npython {sys.version}\nsys.path[0:3]={sys.path[0:3]}\n\n{traceback.format_exc()}"

        async def fallback(scope, receive, send):
            if scope["type"] == "lifespan":
                while True:
                    message = await receive()
                    if message["type"] == "lifespan.startup":
                        await send({"type": "lifespan.startup.complete"})
                    elif message["type"] == "lifespan.shutdown":
                        await send({"type": "lifespan.shutdown.complete"})
                        return
                return
            if scope["type"] != "http":
                return
            body = info.encode("utf-8", "replace")
            await send({"type": "http.response.start", "status": 500,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
            await send({"type": "http.response.body", "body": body})
        return fallback


app = _make_app()   # TOP-LEVEL app — required by Vercel's builder. Do not indent this under try/except.
