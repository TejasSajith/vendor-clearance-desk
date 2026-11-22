"""One entry point that puts the service layer around the engine:

  schema.clean_request -> lease (one worker per request) -> GuardedSources (daily cap, breaker, malformed, alerts)
  -> pipeline.run_request (resumable, deduped, policy + decision, pending action) -> explain.record -> audit

The engine decides; nothing here changes a verdict. open_db installs the service tables and triggers and finishes any action a
crash left in 'executing' (core.recover_actions with the local-only executor).
"""
import json, time, uuid
import core, pipeline
from checks import normalize
from clearance import audit, executors, explain, guard, schema

LEASES = "CREATE TABLE IF NOT EXISTS leases(key TEXT PRIMARY KEY, owner TEXT NOT NULL, ts REAL NOT NULL)"

def open_db(path="clearance.db"):
    db = core.connect(path)
    for m in (guard, audit, explain, executors): m.install(db)
    db.execute(LEASES)
    for key in core.recover_actions(db, executors.local_record(db)):
        audit.append(db, "engine", "action_recovered", None, key, {"note": "finished after a crash, executor is idempotent"})
    return db

def lease_seconds(): return core.CONFIG["max_seconds_per_run"] + 60

def _lease(db, key, owner):
    """True if this owner now holds the lease. A lease older than the run time cap (+60 s) belonged to a dead worker and is taken over."""
    if db.execute("INSERT OR IGNORE INTO leases VALUES(?,?,?)", (key, owner, time.time())).rowcount == 1: return True
    return db.execute("UPDATE leases SET owner=?, ts=? WHERE key=? AND ts<?", (owner, time.time(), key, time.time() - lease_seconds())).rowcount == 1

def run_vendor(db, req, sources, params=None, guard_obj=None, owner=None):
    """Returns the pipeline result (plus 'conflict' when a duplicate request disagrees with the run it maps to), or
    {"status": "invalid", ...} for a request outside the schema, or {"status": "in_progress", ...} while another worker runs it."""
    db.execute(LEASES)
    try: v = schema.clean_request(req)
    except schema.SchemaError as e: return {"status": "invalid", "verdict": None, "field": e.field, "message": str(e)}
    fp = (core.salted_hash(db, v["claimed_director"])[:16] if v["claimed_director"] else "") + pipeline.params_tag(params)
    key = normalize.request_key("lease", v["vendor_name"], v["website"], extra=fp)
    owner = owner or uuid.uuid4().hex
    if not _lease(db, key, owner):
        return {"status": "in_progress", "verdict": None, "message": "the same request is being run by another worker; ask again later"}
    try:
        g = guard_obj or guard.Guard(db)
        res = pipeline.run_request(db, v, guard.GuardedSources(sources, g), params=params)
        if res.get("status") == "invalid": return res
        run_id = res.get("duplicate_of") or res.get("run_id")
        if res.get("existing") or res.get("duplicate_of"):
            row = db.execute("SELECT request FROM runs WHERE id=?", (run_id,)).fetchone()
            stored = json.loads(row[0]) if row else {}
            if stored.get("risk_tier", "low") != v["risk_tier"]:
                res["conflict"] = {"field": "risk_tier", "existing": stored.get("risk_tier", "low"), "requested": v["risk_tier"],
                                   "note": "this request matches an existing run evaluated at another risk tier; the existing result is shown "
                                           "unchanged. A person decides whether to re-check at the requested tier (D55)."}
        if res.get("verdict"):
            first = explain.get(db, run_id) is None
            explain.record(db, run_id, res)
            if first: audit.append(db, "engine", "verdict", run_id, res.get("action_key"),
                                   {"verdict": res["verdict"], "status": res.get("status"), "cost_credits": (res.get("decision") or {}).get("cost_credits")})
        return res
    finally:
        db.execute("DELETE FROM leases WHERE key=? AND owner=?", (key, owner))

def queue(db):
    """Pending actions with the explanation a person will be shown."""
    out = []
    for key, run_id, kind, created in db.execute("SELECT key, run_id, kind, created FROM actions WHERE status='pending' ORDER BY created"):
        out.append({"key": key, "run_id": run_id, "kind": kind, "explanation": explain.get(db, run_id)})
    return out

def decide(db, key, approve, actor):
    row = db.execute("SELECT run_id, payload FROM actions WHERE key=?", (key,)).fetchone()
    if not row: raise audit.AuditError(f"no such action: {key}")
    shown = explain.get(db, row[0]) or {"payload": json.loads(row[1])}
    return audit.decide_action(db, key, approve, actor, shown, executor=executors.local_record(db))
