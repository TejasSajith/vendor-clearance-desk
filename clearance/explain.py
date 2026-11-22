"""Explanation and contest.

record(db, run_id, result)  stores, once per run, what the verdict rests on: the reasons, every source with its record date and
                            retrieval date, and the missing evidence. Rows cannot be updated or deleted (triggers), so a stored
                            explanation always matches the verdict it was written for.
contest(db, run_id, ...)    records a vendor's challenge and creates a re-check run linked to the original. It never changes the
                            original verdict, its action, or its explanation.
run_recheck(db, rc, src)    runs the four checks again into the re-check run (stages resumable through core.run_step) and stores
                            the result next to the original. It creates NO action: a person compares the two and decides.

Record dates: Crustdata returns no record date for the company fields the checks use (probe/REPORT.md), and web search results carry
no date field, so a source without a stored fact date says "not stated by the source". Retrieval dates come from the ledger.
"""
import hashlib, json, time
from datetime import datetime, timezone
import core, decision, pipeline, policy
from clearance import audit, guard

NOT_STATED = "not stated by the source"
SCHEMA = """
CREATE TABLE IF NOT EXISTS explanations(run_id TEXT PRIMARY KEY, ts REAL NOT NULL, verdict TEXT, body TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS explanations_no_update BEFORE UPDATE ON explanations BEGIN SELECT RAISE(ABORT, 'explanations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS explanations_no_delete BEFORE DELETE ON explanations BEGIN SELECT RAISE(ABORT, 'explanations are immutable'); END;
CREATE TABLE IF NOT EXISTS contests(id TEXT PRIMARY KEY, ts REAL NOT NULL, run_id TEXT NOT NULL, recheck_run_id TEXT NOT NULL,
  challenge TEXT NOT NULL, supplied TEXT NOT NULL, status TEXT NOT NULL);
"""
MAX_CHALLENGE = 2000

class ContestError(ValueError): pass

def install(db): db.executescript(SCHEMA)

def _day(ts): return datetime.fromtimestamp(ts, timezone.utc).date().isoformat() if ts else None

def _source_entry(db, run_id, s):
    fact = db.execute("SELECT source_date, retrieved_at FROM facts WHERE run_id=? AND source_url=? ORDER BY id LIMIT 1", (run_id, s)).fetchone()
    ep = s.split(":", 1)[1] if s.startswith("crustdata:") else None
    row = db.execute("SELECT MIN(ts) FROM calls WHERE run_id=? AND endpoint=? AND status='ok'", (run_id, ep)).fetchone() if ep else None
    if row is None or row[0] is None:
        row = db.execute("SELECT MIN(ts) FROM calls WHERE run_id=? AND status='ok'", (run_id,)).fetchone()
    return {"source": s, "record_date": (fact[0] if fact and fact[0] else NOT_STATED),
            "retrieved": (fact[1] if fact and fact[1] else _day(row[0] if row else None)) or "not recorded"}

def build(db, run_id, result):
    d = result.get("decision") or {}
    checks = {}
    for name, c in (result.get("checks") or {}).items():
        checks[name] = {"status": c.get("status"), "reason": c.get("reason", ""),
                        "sources": [_source_entry(db, run_id, s) for s in c.get("sources") or []],
                        "missing": list(c.get("missing") or [])}
    return {"run_id": run_id, "verdict": result.get("verdict"), "status": result.get("status"),
            "reasons": [r.get("text") for r in d.get("reasons") or []], "checks": checks,
            "missing_evidence": list(d.get("missing") or []), "cost_credits": d.get("cost_credits"),
            "note": "A recommendation. CLEARED and REJECTED wait for a person's approval; CANNOT_VERIFY and HOLD go to a person as they are."}

def record(db, run_id, result):
    """Store the explanation once (a later call for the same run is a no-op). Returns the stored explanation."""
    install(db)
    if result.get("verdict"):
        body = build(db, run_id, result)
        db.execute("INSERT OR IGNORE INTO explanations VALUES(?,?,?,?)", (run_id, time.time(), body["verdict"], json.dumps(body, ensure_ascii=False)))
    return get(db, run_id)

def get(db, run_id):
    install(db)
    row = db.execute("SELECT body FROM explanations WHERE run_id=?", (run_id,)).fetchone()
    return json.loads(row[0]) if row else None

def _final(db, run_id):
    row = db.execute("SELECT result FROM steps WHERE run_id=? AND name='final'", (run_id,)).fetchone()
    return json.loads(row[0]) if row else None

def contest(db, run_id, challenge, actor="vendor", website=None):
    """Record a challenge to a verdict and create a linked re-check run (status recheck_pending). Returns ids and the unchanged verdict.
    `challenge` is stored as submitted (data, never instructions); `website` is the only input a vendor may correct here."""
    install(db)
    fin = _final(db, run_id)
    if not fin or not fin.get("verdict"): raise ContestError(f"run {run_id} has no finished verdict to contest")
    if not isinstance(challenge, str) or not challenge.strip(): raise ContestError("challenge: say what is wrong with the verdict")
    if len(challenge) > MAX_CHALLENGE: raise ContestError(f"challenge: at most {MAX_CHALLENGE} characters")
    req = json.loads(db.execute("SELECT request FROM runs WHERE id=?", (run_id,)).fetchone()[0])
    n = db.execute("SELECT COUNT(*) FROM contests WHERE run_id=?", (run_id,)).fetchone()[0]
    cid = "ct_" + hashlib.sha256(f"{run_id}|{n}|{time.time()}".encode()).hexdigest()[:10]
    rc = "rc_" + cid[3:]
    supplied = {"website": website} if website else {}
    core.start_run(db, json.dumps({"vendor_name": req.get("vendor_name"), "website": website or req.get("website") or "",
                                   "risk_tier": req.get("risk_tier", "low"), "recheck_of": run_id, "contest_id": cid}), run_id=rc)
    core.set_run_status(db, rc, "recheck_pending")
    db.execute("INSERT INTO contests VALUES(?,?,?,?,?,?,?)", (cid, time.time(), run_id, rc, challenge.strip(), json.dumps(supplied), "open"))
    record(db, run_id, fin)                       # make sure the verdict being contested is on record as it was
    audit.append(db, actor, "contest", run_id, None, {"contest_id": cid, "recheck_run_id": rc, "verdict_contested": fin["verdict"],
                                                       "challenge_sha256": hashlib.sha256(challenge.strip().encode()).hexdigest(), "supplied": supplied})
    return {"contest_id": cid, "recheck_run_id": rc, "original_run_id": run_id, "original_verdict": fin["verdict"], "status": "open"}

def run_recheck(db, rc, sources, claimed_director=None, params=None, actor="engine"):
    """Run the checks again for a re-check run. Same stages and rules as pipeline.run_request, but no dedupe and no action:
    the result is stored on the re-check run only, and the contest is marked 'rechecked' for a person to compare.
    Note: with the response cache on and no TTL (D24), unchanged requests reuse cached responses."""
    install(db)
    row = db.execute("SELECT request, status FROM runs WHERE id=?", (rc,)).fetchone()
    if not row: raise ContestError(f"no such re-check run: {rc}")
    req = json.loads(row[0]); orig = req.get("recheck_of")
    if not orig: raise ContestError(f"{rc} is not a re-check run")
    done = _final(db, rc)
    if done: return done
    p = params or policy.PROPOSED_PARAMS
    name, domain, tier = req["vendor_name"], req.get("website") or "", req.get("risk_tier", "low")
    ctx = pipeline.Ctx(db, rc)
    src = sources if isinstance(sources, guard.GuardedSources) else guard.GuardedSources(sources, guard.Guard(db))
    state = {}
    def stage(n, fn):
        if "not_run" in state.values(): state[n] = "not_run"; return None
        try: out = core.run_step(db, rc, n, fn); state[n] = "ok"; return out
        except (core.TransientError, core.SourceUnreachable): state[n] = "unreachable"; return None
        except core.LimitExceeded: state[n] = "not_run"; return None
    ident = stage("identify", lambda: src.identify(ctx, name, domain))
    sig = {"identify": pipeline.identify_signals(name, domain, ident, p) if ident is not None else {}}
    cid = sig["identify"].get("company_id")
    if cid is not None:
        sig["profile"] = stage("profile", lambda: src.profile(ctx, cid))
        if sig["profile"] and sig["profile"].get("status"): sig["identify"]["status"] = sig["profile"]["status"]
        if claimed_director: sig["director"] = stage("director", lambda: src.director(ctx, cid, claimed_director))
    if "director" not in sig:
        sig["director"] = {"not_requested": True, "sources": []} if not claimed_director else {"no_company": True, "sources": []}
    sig["adverse"] = stage("adverse", lambda: src.adverse(ctx, name, domain))
    sig = {k: v for k, v in sig.items() if v is not None}
    checks = policy.evaluate(sig, p, tier)
    for st, c in {"identify": "exists", "profile": "active", "director": "director_match", "adverse": "adverse_media"}.items():
        if state.get(st) == "unreachable": checks[c] = {"status": "unreachable", "reason": "source unreachable after retries; retry or send to a person", "sources": []}
        elif state.get(st) == "not_run": checks[c] = {"status": "not_run", "reason": "cost or time cap reached before this check ran", "sources": []}
    started = db.execute("SELECT started FROM runs WHERE id=?", (rc,)).fetchone()[0]
    d = decision.decide(checks, core.run_cost(db, rc), time.time() - started); d.cost_credits = core.run_cost(db, rc)
    res = {"run_id": rc, "recheck_of": orig, "status": "rechecked", "verdict": d.verdict, "decision": d.to_dict(), "checks": checks,
           "action_key": None, "note": "re-check result only: the original verdict is unchanged and no action was created; a person compares and decides"}
    held = "unreachable" in state.values()
    if not held: db.execute("INSERT OR REPLACE INTO steps VALUES(?,?,?)", (rc, "final", json.dumps(res)))
    core.set_run_status(db, rc, "held" if held else "rechecked")
    core.purge_sensitive(db, rc)
    if not held:
        record(db, rc, res)
        db.execute("UPDATE contests SET status='rechecked' WHERE recheck_run_id=?", (rc,))
        orig_verdict = (_final(db, orig) or {}).get("verdict")
        audit.append(db, actor, "recheck_done", rc, None, {"recheck_of": orig, "original_verdict": orig_verdict, "recheck_verdict": d.verdict})
    return res
