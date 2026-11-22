"""Vercel serverless entry for the Vendor Clearance Desk web UI.

Demo mode only (free, no Crustdata key, no credits). Each check runs inline inside the request, because a Vercel
function cannot keep a background worker. Live mode stays OFF on Vercel: `/tmp` SQLite is wiped between
invocations, which would break the ledger, once-only approvals, the duplicate check and history (DECISIONS.md D46).

Access:
  - Open demo  -> leave APP_PASSWORD unset.
  - Gated demo -> set APP_PASSWORD in the Vercel project; the page then asks for it.

Deploy: see docs/vercel.md. Vercel detects `VERCEL=1`, so app/server.py runs inline and uses /tmp automatically.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # put the repo root on the import path

# Build the app at import time. If anything fails during cold start, fall back to a tiny ASGI app that serves the
# traceback as plain text, so the real Python error is visible over HTTP instead of Vercel's opaque 500.
# (Diagnostic marker DIAG-v1; remove this wrapper once the boot error is fixed.)
try:
    from app.server import create_app
    # require_password=False lets the demo boot without a password; if APP_PASSWORD is set the gate still applies.
    app = create_app(require_password=False)
except BaseException:   # noqa: BLE001  -- catch everything, including import errors, so we can report it
    import traceback
    _tb = traceback.format_exc()
    _info = f"DIAG-v1 boot failed\npython {sys.version}\nsys.path[0:3]={sys.path[0:3]}\n\n{_tb}"

    async def app(scope, receive, send):   # minimal ASGI app, pure stdlib, no dependency on the failed import
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
        body = _info.encode("utf-8", "replace")
        await send({"type": "http.response.start", "status": 500,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body", "body": body})
