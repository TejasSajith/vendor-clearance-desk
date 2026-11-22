"""Web UI for the clearance desk: one HTML page (plain JS) on FastAPI. The server holds the only copies of the API keys.

    python -m app                    local: http://127.0.0.1:8000, password optional (APP_PASSWORD)
    api/index.py                     Vercel entry point (password required; see docs/vercel.md)

Modes are chosen per request on the page:
  demo  replayed fixtures (app/demo.py), template parsing and memos: zero live calls, zero credits. Database demo.db.
  live  Crustdata (CRUSTDATA_API_KEY) and the configured model; needs a confirmed spend and set caps. Database clearance.db.

Runs: POST /api/ask queues a job; one worker thread runs one job at a time (keeps the throttle and the session cap exact);
the page polls GET /api/run/{job_id} for per-check progress. On Vercel (or inline=True) the job runs inside the request
instead, because a serverless function cannot keep a background thread.
Rules kept here: code decides (pipeline, policy, decision); the model only parses and writes the memo; the UI never decides:
CLEARED and REJECTED wait for a person's Approve or Reject (core.set_approval + core.execute_action).
Logging: job ids, modes, states and error types only. Never the request text, a director name or a key.
"""
import hashlib, hmac, json, logging, os, queue, secrets, sys, threading, time, uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import controls, core, display, llm, nl, pipeline   # noqa: E402

log = logging.getLogger("clearance.app")
STATIC = Path(__file__).resolve().parent / "static"
COOKIE = "vcd_session"
EFFECTS = "CREATE TABLE IF NOT EXISTS app_effects(key TEXT PRIMARY KEY, kind TEXT, note TEXT, ts REAL)"
MEMOS = "CREATE TABLE IF NOT EXISTS app_memos(run_id TEXT PRIMARY KEY, memo TEXT, writer TEXT, seconds REAL, view TEXT)"
MODES = ("demo", "live")
# pipeline stage (the source method it calls) -> progress key shown on the page
STAGES = {"identify": "exists", "profile": "active", "director": "director", "adverse": "adverse"}
CHECK_KEY = {"exists": "exists", "active": "active", "director_match": "director", "adverse_media": "adverse"}

class AskIn(BaseModel):
    text: str = Field(max_length=2000)
    controls: dict = Field(default_factory=dict)
    mode: str = "demo"
    confirm_spend: bool = False

class LoginIn(BaseModel):
    password: str = Field(max_length=200)

def on_vercel(): return bool(os.environ.get("VERCEL"))

def executor(db):
    """Approved actions are only RECORDED locally (nothing is sent anywhere). Idempotent per key."""
    def run(kind, payload, key):
        db.execute("INSERT OR IGNORE INTO app_effects VALUES(?,?,?,?)",
                   (key, kind, "recorded locally; nothing sent outside this app", time.time()))
    return run

class ProgressSources:
    """Wraps the real sources to report per-check progress. It only observes: arguments and results pass through unchanged."""
    def __init__(self, inner, progress): self.inner, self.progress = inner, progress
    def __getattr__(self, name):
        fn = getattr(self.inner, name)
        if name not in STAGES: return fn
        key = STAGES[name]
        def wrapped(*a, **kw):
            self.progress[key] = "running"
            try: out = fn(*a, **kw)
            except (core.TransientError, core.SourceUnreachable): self.progress[key] = "unreachable"; raise
            except core.LimitExceeded: self.progress[key] = "stopped at cap"; raise
            except Exception: self.progress[key] = "error"; raise
            self.progress[key] = "fetched"
            return out
        return wrapped

def live_caps():
    """Per-run caps from config.json. Live mode refuses to run unless both are set to positive numbers."""
    c, s = core.CONFIG.get("max_cost_credits_per_run"), core.CONFIG.get("max_seconds_per_run")
    ok = all(isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 for x in (c, s))
    return ok, c, s

def create_app(data_dir=None, demo_sources=None, live_sources=None, password=None, llm_provider="config", candidate_path=None,
               inline=None, require_password=True, run_pipeline=None, allow_live=None):
    """data_dir: where demo.db and clearance.db live (APP_DATA_DIR; /tmp on Vercel). run_pipeline: injectable for tests
    (default pipeline.run_request). allow_live: None = live if a Crustdata key (or live_sources) is present and the store is durable."""
    llm.load_dotenv()
    # The gate applies only when APP_PASSWORD (or the password argument) is set and non-blank. There is no default password.
    password = (password if password is not None else os.environ.get("APP_PASSWORD") or "").strip() or None
    if require_password and not password:
        raise RuntimeError("Set APP_PASSWORD before starting the server (required unless bound to 127.0.0.1 by python -m app)")
    data_dir = Path(data_dir or os.environ.get("APP_DATA_DIR") or ("/tmp" if on_vercel() else ROOT))
    data_dir.mkdir(parents=True, exist_ok=True)
    db_paths = {"demo": str(data_dir / "demo.db"), "live": str(data_dir / "clearance.db")}
    inline = on_vercel() if inline is None else inline
    run_pipeline = run_pipeline or pipeline.run_request
    if demo_sources is None:
        from .demo import DemoSources
        demo_sources = DemoSources()

    # Live mode: available only with a key (or injected sources), set caps, and a durable store (not Vercel's /tmp, D41)
    live_reason = None
    if allow_live is False: live_reason = "Live mode is switched off on this server."
    elif live_sources is None and not os.environ.get("CRUSTDATA_API_KEY"): live_reason = "Live mode needs CRUSTDATA_API_KEY on the server."
    elif allow_live is None and on_vercel() and os.environ.get("APP_ALLOW_LIVE_EPHEMERAL") != "1":
        live_reason = ("Live mode is off on Vercel until a durable database is chosen (D41): /tmp storage would lose the "
                       "ledger, the approvals and the duplicate check between requests.")
    elif not live_caps()[0]: live_reason = "Live mode refuses to run: the credit cap and time cap are not set in config.json."
    _live = {"sources": live_sources}
    def get_live_sources():
        if _live["sources"] is None:
            from checks import live
            _live["sources"] = live.LiveSources()
        return _live["sources"]

    # demo never calls a model (zero live calls); live uses the configured one
    live_provider = llm.get_provider() if llm_provider == "config" else llm_provider
    provider = {"demo": None, "live": live_provider}
    _, per_run_cap, seconds_cap = live_caps()
    session_cap = core.CONFIG.get("session_credit_cap", per_run_cap)
    sessions, lock, fails = {}, threading.RLock(), []
    local_session = {"spent": 0.0, "reserved": 0.0, "created": time.time()}
    run_lock = threading.Lock()                 # one run at a time, also in inline mode
    jobs, order = {}, []                        # job_id -> job; order = queued job ids (for the queue position)
    work = queue.Queue()

    def db(mode):
        d = core.connect(db_paths[mode]); d.execute(EFFECTS); d.execute(MEMOS); return d

    for m in MODES:                              # finish approved-but-unexecuted actions after a crash
        d0 = db(m); core.recover_actions(d0, executor(d0)); d0.close()

    app = FastAPI(title="Vendor Clearance Desk", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.update({"Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                             "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})
        return resp

    def session(request: Request):
        if not password: return local_session
        tok = request.cookies.get(COOKIE)
        with lock: s = sessions.get(tok) if tok else None
        if not s: raise HTTPException(401, "Please sign in")
        return s

    def total(d): return d.execute("SELECT COALESCE(SUM(credits),0) FROM calls").fetchone()[0]

    @app.get("/")
    def index(): return FileResponse(STATIC / "index.html")

    @app.get("/app.js")
    def js(): return FileResponse(STATIC / "app.js", media_type="text/javascript")

    @app.get("/app.css")
    def css(): return FileResponse(STATIC / "app.css", media_type="text/css")

    @app.get("/api/health")
    def health():
        return {"ok": True, "modes": {"demo": True, "live": live_reason is None}, "inline": inline,
                "queue": len(order), "login_required": bool(password)}

    @app.post("/api/login")
    def login(body: LoginIn, response: Response):
        if not password: return {"ok": True}
        now = time.time()
        with lock:
            fails[:] = [t for t in fails if now - t < 60]
            if len(fails) >= 10: raise HTTPException(429, "Too many attempts; wait a minute")
        if not hmac.compare_digest(body.password.encode(), password.encode()):
            with lock: fails.append(now)
            raise HTTPException(401, "Wrong password")
        tok = secrets.token_urlsafe(32)
        with lock: sessions[tok] = {"spent": 0.0, "reserved": 0.0, "created": now}
        response.set_cookie(COOKIE, tok, httponly=True, samesite="strict",
                            secure=on_vercel() or os.environ.get("APP_SECURE_COOKIE") == "1")
        return {"ok": True}

    @app.get("/api/status")
    def status(request: Request):
        s = session(request)
        opts, notes = controls.options(candidate_path)
        model = (f"{live_provider.model}; templates if it fails or is slow" if hasattr(live_provider, "model") else "on") if live_provider \
            else "off (template parsing and memos)"
        return {"modes": {"demo": {"available": True, "label": _demo_label()},
                          "live": {"available": live_reason is None, "reason": live_reason}},
                "default_mode": os.environ.get("APP_MODE", "demo") if live_reason is None else "demo",
                "model": {"demo": "off in demo (templates)", "live": model}, "inline": inline, "login_required": bool(password),
                "caps": {"credits_per_run": per_run_cap, "seconds_per_run": seconds_cap, "credits_per_session": session_cap,
                         "session_spent": round(s["spent"], 4)},
                "controls": opts, "control_notes": notes}

    # ---------- jobs ----------
    def public(job):
        out = {k: job[k] for k in ("job_id", "mode", "status", "progress", "created")}
        with lock: out["position"] = order.index(job["job_id"]) + 1 if job["job_id"] in order else 0
        for k in ("card", "questions", "request", "error", "note", "duplicate_job"):
            if job.get(k) is not None: out[k] = job[k]
        return out

    @app.post("/api/ask")
    def ask(body: AskIn, request: Request):
        s = session(request)
        if body.mode not in MODES: raise HTTPException(400, "Mode must be demo or live")
        if not body.text.strip(): raise HTTPException(400, "Please describe the vendor first, for example: Check Acme Logistics Pvt Ltd, acmelogistics.in, low risk.")
        if body.mode == "live":
            if live_reason: raise HTTPException(409, live_reason)
            if not body.confirm_spend:
                raise HTTPException(428, f"Live mode spends Crustdata credits (up to {per_run_cap:g} credits and {seconds_cap:g} s for this run). Confirm to continue.")
            with lock:
                used = s["spent"] + s["reserved"]
                if used + per_run_cap > session_cap:
                    raise HTTPException(402, f"Credit cap reached for this session: {used:g} of {session_cap:g} credits used or reserved, "
                                             f"and a run may cost up to {per_run_cap:g}. Sign in again for a new session.")
                s["reserved"] += per_run_cap
        fp = hashlib.sha256(json.dumps([body.mode, " ".join(body.text.lower().split()), body.controls], sort_keys=True).encode()).hexdigest()
        with lock:                               # the same request already waiting or running: show that job, do not queue twice
            for j in jobs.values():
                if j["fp"] == fp and j["status"] in ("queued", "running"):
                    if body.mode == "live": s["reserved"] -= per_run_cap
                    return {**public(j), "note": "This request is already queued or running; showing it."}
            jid = "j_" + uuid.uuid4().hex[:12]
            job = {"job_id": jid, "mode": body.mode, "status": "queued", "fp": fp, "created": time.time(),
                   "progress": {"parse": "waiting", **{k: "waiting" for k in STAGES.values()}, "memo": "waiting"},
                   "_body": body, "_session": s}
            jobs[jid] = job
            if len(jobs) > 200:                  # keep memory bounded: drop the oldest finished jobs (runs stay in SQLite)
                for old in sorted((j for j in jobs.values() if j["status"] not in ("queued", "running")), key=lambda j: j["created"])[:50]:
                    jobs.pop(old["job_id"], None)
            if not inline: order.append(jid)
        log.info("job %s queued (mode=%s)", jid, body.mode)
        if inline: execute(job)
        else:
            ensure_worker(); work.put(jid)
        return public(job)

    def execute(job):
        body, s, mode = job.pop("_body"), job.pop("_session"), job["mode"]
        with run_lock:
            with lock:
                if job["job_id"] in order: order.remove(job["job_id"])
            job["status"] = "running"; log.info("job %s running", job["job_id"])
            d = db(mode)
            try: _run(d, job, body, s)
            except Exception as e:               # log the type only: a message could quote the request
                log.error("job %s failed: %s", job["job_id"], type(e).__name__)
                job["status"], job["error"] = "error", f"Something went wrong on the server ({type(e).__name__}). Nothing was decided; please try again."
            finally:
                if mode == "live":
                    with lock: s["reserved"] = max(0.0, s["reserved"] - per_run_cap)
                d.close()
        log.info("job %s %s", job["job_id"], job["status"])

    _worker = {"t": None}
    def ensure_worker():
        with lock:
            if _worker["t"] and _worker["t"].is_alive(): return
            t = threading.Thread(target=worker_loop, name="clearance-worker", daemon=True); _worker["t"] = t; t.start()
    def worker_loop():
        while True:
            jid = work.get()
            job = jobs.get(jid)
            if job and job["status"] == "queued": execute(job)

    def _run(d, job, body, s):
        mode, prog = job["mode"], job["progress"]
        t_request = time.time()
        ledger = llm.ledger_run(d, "ui")
        prog["parse"] = "running"
        parsed = nl.parse_request(body.text, db=d, run_id=ledger, provider=provider[mode])
        prog["parse"] = "done"
        req = parsed["request"]
        job["request"] = {"vendor_name": req["vendor_name"], "domain": req["domain"], "risk_tier": req["risk_tier"] or "low",
                          "claimed_director": "provided (not stored)" if req["claimed_director"] else None,
                          "registry_ids": req["registry_ids"], "parser": parsed["parser"]}
        if not parsed["complete"]:
            job["status"], job["questions"] = "needs_input", parsed["questions"]
            for k in STAGES.values(): prog[k] = "not started"
            prog["memo"] = "not started"; return
        ctl = controls.resolve(body.controls, candidate_path)
        srcs = ProgressSources(demo_sources if mode == "demo" else get_live_sources(), prog)
        t0, before = time.time(), total(d)
        try: res = run_pipeline(d, nl.to_pipeline_request(req), srcs, params=ctl["params"])
        finally:
            with lock: s["spent"] += total(d) - before        # exact: runs are serialised by run_lock
        seconds = time.time() - t0
        if res.get("status") == "invalid":
            job["status"], job["questions"] = "needs_input", [res["message"]]; return
        for k in STAGES.values():
            if prog[k] == "waiting": prog[k] = "skipped" if not (res.get("existing") or res.get("duplicate_of")) else "from the earlier run"
        run_id = res.get("duplicate_of") or res.get("run_id")
        prog["memo"] = "running"
        card = _card(d, mode, run_id, res, seconds, ledger)
        prog["memo"] = "done"
        card.update({"controls": ctl["controls"], "control_notes": ctl["notes"], "questions": parsed["questions"],
                     "existing": bool(res.get("existing") or res.get("duplicate_of")),
                     "session_spent": round(s["spent"], 4), "total_seconds": round(time.time() - t_request, 2)})
        card["notices"] = notices(card, res)
        job["card"], job["status"] = card, "done"

    def notices(card, res):
        """Plain-English messages for the cases the page must explain (duplicate, cap hit, unreachable source)."""
        out = []
        if card.get("existing"):
            out.append(f"Already checked: this vendor was run before with these settings (run {card['run_id']}, started "
                       f"{card.get('started') or 'earlier'}). Showing the existing result; no new credits were spent on it.")
        if res.get("status") == "stopped_at_cap":
            out.append(f"Stopped at the cap: the run reached its limit ({per_run_cap:g} credits or {seconds_cap:g} s) before every check "
                       "ran. The unfinished checks show as Can't verify.")
        down = [c["title"] for c in card.get("checks", []) if c["status"] == "unreachable"]
        if down:
            out.append(f"Couldn't reach the source for: {', '.join(down)}, even after retries. The case is held for a person; "
                       "try again later. A timeout is never read as \"nothing found\".")
        return out

    def _card(d, mode, run_id, res, seconds=None, ledger=None):
        row = d.execute("SELECT started FROM runs WHERE id=?", (run_id,)).fetchone()
        started = datetime.fromtimestamp(row[0], timezone.utc) if row else None
        retrieved = started.date().isoformat() if started else None
        if not res.get("verdict"):
            return {"status": res.get("status", "in_progress"), "run_id": run_id, "mode": mode, "verdict": None, "overall": "In progress", "checks": []}
        m = d.execute("SELECT memo, writer, seconds FROM app_memos WHERE run_id=?", (run_id,)).fetchone()
        if m is None or res.get("status") == "held":        # a held run may be retried: write a fresh memo
            mm = nl.write_memo(res, db=d, run_id=ledger or llm.ledger_run(d, "ui"), provider=provider[mode], retrieved=retrieved, seconds=seconds)
            # view: the last result, so a held run (no cached final step, so it can be retried) can still be reopened from history
            d.execute("INSERT OR REPLACE INTO app_memos VALUES(?,?,?,?,?)", (run_id, mm["memo"], mm["writer"], seconds, json.dumps(res)))
            m = (mm["memo"], mm["writer"], seconds)
        view = display.display_result(res)
        for c in view["checks"]:
            c["record_date"], c["retrieved"], c["key"] = "not stated by the source", retrieved, CHECK_KEY.get(c["check"], c["check"])
        act = None
        if res.get("action_key"):
            a = d.execute("SELECT kind, status FROM actions WHERE key=?", (res["action_key"],)).fetchone()
            if a: act = {"key": res["action_key"], "kind": a[0], "status": a[1]}
        return {"status": res.get("status"), "run_id": run_id, "mode": mode, "verdict": res["verdict"], "overall": view["overall"],
                "checks": view["checks"], "missing": view["missing"], "memo": m[0], "memo_writer": m[1],
                "credits": round(core.run_cost(d, run_id), 4), "seconds": None if m[2] is None else round(m[2], 2), "action": act,
                "started": started.isoformat(timespec="seconds") if started else None,
                "demo_label": _demo_label() if mode == "demo" else None}

    # ---------- reading results ----------
    @app.get("/api/run/{rid}")
    def run_detail(rid: str, request: Request, mode: str = None):
        session(request)
        with lock: job = jobs.get(rid)
        if job: return public(job)
        for m in ([mode] if mode in MODES else ["live", "demo"]):
            d = db(m)
            try:
                fin = d.execute("SELECT result FROM steps WHERE run_id=? AND name='final'", (rid,)).fetchone() \
                    or d.execute("SELECT view FROM app_memos WHERE run_id=? AND view IS NOT NULL", (rid,)).fetchone()
                if fin:
                    card = _card(d, m, rid, json.loads(fin[0])); card["notices"] = notices(card, json.loads(fin[0]))
                    return {"job_id": None, "mode": m, "status": "done", "card": card}
            finally: d.close()
        raise HTTPException(404, "No finished result for this run. It may still be running, or it was stored on another server instance.")

    @app.get("/api/runs")
    def runs(request: Request):
        session(request); out = []
        for m in MODES:
            d = db(m)
            try:
                for rid, req, st, started in d.execute("SELECT id, request, status, started FROM runs WHERE id LIKE 'r\\_%' ESCAPE '\\' "
                                                        "ORDER BY started DESC LIMIT 50"):
                    if (st or "").startswith("duplicate_of:"): continue
                    fin = d.execute("SELECT result FROM steps WHERE run_id=? AND name='final'", (rid,)).fetchone() \
                        or d.execute("SELECT view FROM app_memos WHERE run_id=? AND view IS NOT NULL", (rid,)).fetchone()
                    verdict = json.loads(fin[0]).get("verdict") if fin else None
                    a = d.execute("SELECT status FROM actions WHERE run_id=?", (rid,)).fetchone()
                    out.append({"run_id": rid, "mode": m, "vendor_name": json.loads(req).get("vendor_name"), "status": st,
                                "overall": display.overall_label(verdict) if verdict else st, "action": a[0] if a else None,
                                "credits": round(core.run_cost(d, rid), 4), "_t": started,
                                "started": datetime.fromtimestamp(started, timezone.utc).isoformat(timespec="seconds")})
            finally: d.close()
        out.sort(key=lambda r: -r.pop("_t"))
        return {"runs": out[:50]}

    # ---------- the human approval step ----------
    @app.post("/api/action/{key}/{choice}")
    def act(key: str, choice: str, request: Request, mode: str = None):
        session(request)
        if choice not in ("approve", "reject"): raise HTTPException(404, "Unknown choice: use approve or reject")
        for m in ([mode] if mode in MODES else ["live", "demo"]):
            d = db(m)
            try:
                row = d.execute("SELECT status FROM actions WHERE key=?", (key,)).fetchone()
                if not row: continue
                if row[0] != "pending": return {"key": key, "mode": m, "status": row[0], "note": "Already decided; nothing changed."}
                core.set_approval(d, key, approve=(choice == "approve"))
                if choice == "approve": core.execute_action(d, key, executor(d))
                st = d.execute("SELECT status FROM actions WHERE key=?", (key,)).fetchone()[0]
                log.info("action decided (mode=%s): %s", m, st)
                return {"key": key, "mode": m, "status": st, "note": "Approved and recorded locally; nothing was sent outside this app."
                        if choice == "approve" else "Rejected by a person; no action taken."}
            finally: d.close()
        raise HTTPException(404, "No such pending action")

    @app.exception_handler(HTTPException)
    def http_error(request, exc): return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    return app

def _demo_label():
    from .demo import LABEL
    return LABEL
