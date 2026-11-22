"""Demo-mode API for the static Vercel page. It only replays recorded fixtures: no keys, no database, no network calls, no writes.

  GET /api/config              {"platform": "vercel", "backend_url": BACKEND_URL or null, "demo_label": ...}
  GET /api/demo/cases          the six demo cases (index)
  GET /api/demo/cases/{id}     one result card, exactly as the web UI shows it

Fixtures are built by scripts/build_demo_fixtures.py from the live validation runs (recorded) and app/demo.py (synthetic, labelled).
BACKEND_URL (optional): the live backend the page may call. Only https URLs are passed on (http only for localhost).
"""
import json, os
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

FIX = Path(__file__).resolve().parent / "fixtures"
LABEL = ("Demo mode: recorded results. Nothing here is a live check and no credits are spent. Four cases replay recorded live runs; "
         "two (Cleared, Held for approval) are synthetic and labelled so.")
INDEX = json.loads((FIX / "index.json").read_text())
CASES = {c["id"]: json.loads((FIX / f"{c['id']}.json").read_text()) for c in INDEX}

def backend_url(raw=None):
    raw = (os.environ.get("BACKEND_URL", "") if raw is None else raw).strip().rstrip("/")
    if not raw: return None
    u = urlparse(raw)
    local = u.hostname in ("localhost", "127.0.0.1")
    if u.scheme == "https" or (u.scheme == "http" and local):
        return f"{u.scheme}://{u.netloc}"
    return None                                   # anything else (http to a public host, a path, junk) is ignored

app = FastAPI(title="Vendor Clearance Desk demo", docs_url=None, redoc_url=None, openapi_url=None)

@app.middleware("http")
async def headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.update({"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})
    return resp

@app.get("/api/config")
def config(): return {"platform": "vercel", "backend_url": backend_url(), "demo_label": LABEL}

@app.get("/api/demo/cases")
def cases(): return {"cases": INDEX, "demo_label": LABEL}

@app.get("/api/demo/cases/{case_id}")
def case(case_id: str):
    if case_id not in CASES: raise HTTPException(404, "No such demo case")
    return {**CASES[case_id], "demo": True, "demo_label": LABEL}

@app.exception_handler(HTTPException)
def http_error(request, exc): return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
