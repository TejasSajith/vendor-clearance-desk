"""Web UI for the clearance desk: one HTML page (plain JS) on FastAPI. The server holds the only copies of the API keys.

    APP_PASSWORD=... uvicorn app.server:create_app --factory --port 8000

Env:  APP_PASSWORD (required)  ·  APP_MODE demo (default, no cost, replayed fixtures) | live (needs CRUSTDATA_API_KEY)
      GEMINI_API_KEY (optional; without it parsing and memos use templates)  ·  APP_DB (default clearance.db, demo.db in demo mode)
Rules kept here: code decides (pipeline, policy, decision); the model only parses and writes the memo; CLEARED and REJECTED wait
for a person's Approve or Reject; every run has a credit and time cap, and each session has a hard credit cap.
"""
import hmac, json, os, secrets, sys, threading, time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import controls, core, display, llm, nl, pipeline   # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
COOKIE = "vcd_session"
EFFECTS = "CREATE TABLE IF NOT EXISTS app_effects(key TEXT PRIMARY KEY, kind TEXT, note TEXT, ts REAL)"
MEMOS = "CREATE TABLE IF NOT EXISTS app_memos(run_id TEXT PRIMARY KEY, memo TEXT, writer TEXT, seconds REAL, view TEXT)"

class RunIn(BaseModel):
    text: str = Field(max_length=2000)
    controls: dict = Field(default_factory=dict)

class LoginIn(BaseModel):
    password: str = Field(max_length=200)

def executor(db):
    """Approved actions are only RECORDED locally (nothing is sent anywhere). Idempotent per key."""
    def run(kind, payload, key):
        db.execute("INSERT OR IGNORE INTO app_effects VALUES(?,?,?,?)",
                   (key, kind, "recorded locally; nothing sent outside this app", time.time()))
    return run

def create_app(db_path=None, mode=None, sources=None, password=None, llm_provider="config", candidate_path=None):
    llm.load_dotenv()
    mode = mode or os.environ.get("APP_MODE", "demo")
    if mode not in ("demo", "live"): raise RuntimeError("APP_MODE must be demo or live")
    password = password if password is not None else os.environ.get("APP_PASSWORD")
    if not password: raise RuntimeError("Set APP_PASSWORD before starting the server")
    db_path = db_path or os.environ.get("APP_DB") or ("demo.db" if mode == "demo" else "clearance.db")
    if sources is None:
        if mode == "demo":
            from .demo import DemoSources
            sources = DemoSources()
        else:
            if not os.environ.get("CRUSTDATA_API_KEY"): raise RuntimeError("APP_MODE=live needs CRUSTDATA_API_KEY")
            from checks import live
            sources = live.LiveSources()
    provider = llm.get_provider() if llm_provider == "config" else llm_provider
    per_run_cap, seconds_cap = core.CONFIG["max_cost_credits_per_run"], core.CONFIG["max_seconds_per_run"]
    session_cap = core.CONFIG.get("session_credit_cap", per_run_cap)
    sessions, lock, fails = {}, threading.Lock(), []
    run_lock = threading.Lock()           # one run at a time: keeps the throttle and the session cap exact

    def db():
        d = core.connect(db_path); d.execute(EFFECTS); d.execute(MEMOS); return d

    d0 = db(); core.recover_actions(d0, executor(d0)); d0.close()

    app = FastAPI(title="Vendor Clearance Desk", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.update({"Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                             "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})
        return resp

    def session(request: Request):
        tok = request.cookies.get(COOKIE)
        with lock: s = sessions.get(tok) if tok else None
        if not s: raise HTTPException(401, "Please log in")
        return s

    def total(d): return d.execute("SELECT COALESCE(SUM(credits),0) FROM calls").fetchone()[0]
    def spent(d, s): return round(s["spent"], 4)

    @app.get("/")
    def index(): return FileResponse(STATIC / "index.html")

    @app.get("/app.js")
    def js(): return FileResponse(STATIC / "app.js", media_type="text/javascript")

    @app.get("/app.css")
    def css(): return FileResponse(STATIC / "app.css", media_type="text/css")

    @app.post("/api/login")
    def login(body: LoginIn, response: Response):
        now = time.time()
        with lock:
            fails[:] = [t for t in fails if now - t < 60]
            if len(fails) >= 10: raise HTTPException(429, "Too many attempts; wait a minute")
        if not hmac.compare_digest(body.password.encode(), password.encode()):
            with lock: fails.append(now)
            raise HTTPException(401, "Wrong password")
        tok = secrets.token_urlsafe(32)
        with lock: sessions[tok] = {"spent": 0.0, "created": now}
        response.set_cookie(COOKIE, tok, httponly=True, samesite="strict", secure=os.environ.get("APP_SECURE_COOKIE") == "1")
        return {"ok": True}

    @app.get("/api/status")
    def status(request: Request):
        s = session(request); d = db()
        try:
            opts, notes = controls.options(candidate_path)
            return {"mode": mode, "demo_label": _demo_label(mode), "model": "on" if provider else "off (template parsing and memos)",
                    "caps": {"credits_per_run": per_run_cap, "seconds_per_run": seconds_cap, "credits_per_session": session_cap,
                             "session_spent": spent(d, s)},
                    "controls": opts, "control_notes": notes}
        finally: d.close()

    @app.post("/api/run")
    def run(body: RunIn, request: Request):
        s = session(request)
        with run_lock:
            d = db()
            try: return _run(d, s, body)
            finally: d.close()

    def _run(d, s, body):
        used = spent(d, s)
        if used + per_run_cap > session_cap:
            raise HTTPException(402, f"Session credit cap reached: {used:g} of {session_cap:g} credits used; "
                                     f"a run may cost up to {per_run_cap:g}. Log in again for a new session.")
        ledger = llm.ledger_run(d, "ui")
        parsed = nl.parse_request(body.text, db=d, run_id=ledger, provider=provider)
        req = parsed["request"]
        echo = {"vendor_name": req["vendor_name"], "domain": req["domain"], "risk_tier": req["risk_tier"] or "low",
                "claimed_director": "provided (not stored)" if req["claimed_director"] else None,
                "registry_ids": req["registry_ids"]}
        if not parsed["complete"]:
            return {"status": "needs_input", "questions": parsed["questions"], "request": echo, "parser": parsed["parser"]}
        ctl = controls.resolve(body.controls, candidate_path)
        t0, before = time.time(), total(d)
        try: res = pipeline.run_request(d, nl.to_pipeline_request(req), sources, params=ctl["params"])
        finally: s["spent"] += total(d) - before          # exact: runs are serialised by run_lock
        seconds = time.time() - t0
        if res.get("status") == "invalid":
            return {"status": "needs_input", "questions": [res["message"]], "request": echo, "parser": parsed["parser"]}
        run_id = res.get("duplicate_of") or res.get("run_id")
        card = _card(d, run_id, res, seconds, ledger)
        card.update({"request": echo, "parser": parsed["parser"], "questions": parsed["questions"], "controls": ctl["controls"],
                     "control_notes": ctl["notes"], "existing": bool(res.get("existing") or res.get("duplicate_of")),
                     "session_spent": spent(d, s)})
        return card

    def _card(d, run_id, res, seconds=None, ledger=None):
        row = d.execute("SELECT started FROM runs WHERE id=?", (run_id,)).fetchone()
        retrieved = datetime.fromtimestamp(row[0], timezone.utc).date().isoformat() if row else None
        if not res.get("verdict"):
            return {"status": res.get("status", "in_progress"), "run_id": run_id, "verdict": None, "overall": "In progress", "checks": []}
        m = d.execute("SELECT memo, writer, seconds FROM app_memos WHERE run_id=?", (run_id,)).fetchone()
        if m is None or res.get("status") == "held":        # a held run may be retried: write a fresh memo
            mm = nl.write_memo(res, db=d, run_id=ledger or llm.ledger_run(d, "ui"), provider=provider, retrieved=retrieved, seconds=seconds)
            d.execute("INSERT OR REPLACE INTO app_memos VALUES(?,?,?,?,?)", (run_id, mm["memo"], mm["writer"], seconds, None))
            m = (mm["memo"], mm["writer"], seconds)
        view = display.display_result(res)
        for c in view["checks"]: c["record_date"], c["retrieved"] = "not stated by the source", retrieved
        act = None
        if res.get("action_key"):
            a = d.execute("SELECT kind, status FROM actions WHERE key=?", (res["action_key"],)).fetchone()
            if a: act = {"key": res["action_key"], "kind": a[0], "status": a[1]}
        return {"status": res.get("status"), "run_id": run_id, "verdict": res["verdict"], "overall": view["overall"], "checks": view["checks"],
                "missing": view["missing"], "memo": m[0], "memo_writer": m[1], "credits": round(core.run_cost(d, run_id), 4),
                "seconds": None if m[2] is None else round(m[2], 2), "action": act, "mode": mode, "demo_label": _demo_label(mode)}

    @app.get("/api/runs")
    def runs(request: Request):
        session(request); d = db()
        try:
            out = []
            for rid, req, st, started in d.execute("SELECT id, request, status, started FROM runs WHERE id LIKE 'r\\_%' ESCAPE '\\' "
                                                    "ORDER BY started DESC LIMIT 50"):
                fin = d.execute("SELECT result FROM steps WHERE run_id=? AND name='final'", (rid,)).fetchone()
                verdict = json.loads(fin[0]).get("verdict") if fin else None
                a = d.execute("SELECT status FROM actions WHERE run_id=?", (rid,)).fetchone()
                out.append({"run_id": rid, "vendor_name": json.loads(req).get("vendor_name"), "status": st,
                            "overall": display.overall_label(verdict) if verdict else st, "action": a[0] if a else None,
                            "credits": round(core.run_cost(d, rid), 4),
                            "started": datetime.fromtimestamp(started, timezone.utc).isoformat(timespec="seconds")})
            return {"runs": out}
        finally: d.close()

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str, request: Request):
        session(request); d = db()
        try:
            fin = d.execute("SELECT result FROM steps WHERE run_id=? AND name='final'", (run_id,)).fetchone()
            if not fin: raise HTTPException(404, "No finished result for this run")
            return _card(d, run_id, json.loads(fin[0]))
        finally: d.close()

    @app.post("/api/actions/{key}/{choice}")
    def act(key: str, choice: str, request: Request):
        session(request)
        if choice not in ("approve", "reject"): raise HTTPException(404, "Unknown choice")
        d = db()
        try:
            row = d.execute("SELECT status FROM actions WHERE key=?", (key,)).fetchone()
            if not row: raise HTTPException(404, "No such action")
            if row[0] != "pending": return {"key": key, "status": row[0], "note": "already decided; nothing changed"}
            core.set_approval(d, key, approve=(choice == "approve"))
            if choice == "approve": core.execute_action(d, key, executor(d))
            st = d.execute("SELECT status FROM actions WHERE key=?", (key,)).fetchone()[0]
            return {"key": key, "status": st, "note": "recorded locally; nothing was sent outside this app" if choice == "approve"
                    else "rejected by a person; no action taken"}
        finally: d.close()

    @app.exception_handler(HTTPException)
    def http_error(request, exc): return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    return app

def _demo_label(mode):
    if mode != "demo": return None
    from .demo import LABEL
    return LABEL
