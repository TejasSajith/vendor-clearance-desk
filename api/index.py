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

from app.server import create_app

# require_password=False lets the demo boot without a password; if APP_PASSWORD is set the gate still applies.
app = create_app(require_password=False)
