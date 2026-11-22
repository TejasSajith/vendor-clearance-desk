"""Pipeline: one vendor request in, one recommendation out. Resumable (core.run_step) and idempotent (request keys).
External data comes from injected `sources` (live Crustdata modules, or fakes in tests). Every external call a source makes
must go through ctx.call, which is core.cached_call (throttle, cache, limits, ledger, retry).
Verdicts are recommendations: CLEARED and REJECTED become pending actions that a person approves (core.finalize)."""
import json, time
import core, decision, policy
from checks import normalize

KIND = "clearance"

class ValidationError(ValueError):
    """A request that cannot be run. `field` names what is missing or wrong."""
    def __init__(self, field, message): super().__init__(f"{field}: {message}"); self.field, self.message = field, message

def validate_request(req):
    """Returns the cleaned request or raises ValidationError naming the field. The name is used as given (no transliteration)."""
    if not isinstance(req, dict): raise ValidationError("request", "must be an object with vendor_name")
    name = req.get("vendor_name")
    if not isinstance(name, str) or not name.strip(): raise ValidationError("vendor_name", "required: the vendor name is empty or missing")
    tier = req.get("risk_tier") or "low"
    if tier not in ("low", "medium", "high"): raise ValidationError("risk_tier", "must be low, medium or high")
    claimed = req.get("claimed_director")
    claimed = claimed.strip() if isinstance(claimed, str) and claimed.strip() else None
    site = req.get("website") or req.get("domain") or req.get("email")
    return {"vendor_name": name.strip(), "domain": normalize.normalize_domain(site) if isinstance(site, str) else "",
            "claimed_director": claimed, "risk_tier": tier}

class Ctx:
    def __init__(self, db, run_id): self.db, self.run_id = db, run_id
    def call(self, endpoint, params, fn, credits_from=None):
        return core.cached_call(self.db, self.run_id, endpoint, params, fn, credits_from=credits_from)

def identify_signals(name, domain, ident):
    cands = ident.get("candidates") or []
    if not cands: return {"found": False, "status": None, "name_similarity": 0.0, "top_ties": 0, "domain_match": None,
                          "sources": ["crustdata:/company/identify"]}
    top = max(c["score"] for c in cands); best = [c for c in cands if c["score"] == top]
    chosen = best[0]
    dm = None
    if domain and ident.get("domain_candidate_ids") is not None:
        ids = ident["domain_candidate_ids"]; dm = bool(ids) and ids[0] == chosen["id"]
    return {"found": True, "company_id": chosen["id"], "status": ident.get("status"),
            "name_similarity": normalize.name_similarity(name, chosen["name"]), "top_ties": len(best), "domain_match": dm,
            "sources": ["crustdata:/company/identify"]}

def _existing_result(db, run_id):
    row = db.execute("SELECT result FROM steps WHERE run_id=? AND name='final'", (run_id,)).fetchone()
    return json.loads(row[0]) if row else {"run_id": run_id, "status": "in_progress"}

def run_request(db, req, sources):
    try: v = validate_request(req)
    except ValidationError as e:                           # a clean result, not a crash
        return {"status": "invalid", "verdict": None, "field": e.field, "message": str(e)}
    name, domain, tier, claimed = v["vendor_name"], v["domain"], v["risk_tier"], v["claimed_director"]
    pk = normalize.request_key(KIND, name, domain)
    run = "r_" + pk[:12]
    existed = db.execute("SELECT 1 FROM runs WHERE id=?", (run,)).fetchone() is not None
    core.start_run(db, json.dumps({"vendor_name": name, "website": domain, "risk_tier": tier}), run_id=run)
    core.claim_request(db, pk, run)
    ctx = Ctx(db, run)
    state = {}                                             # stage -> "ok" | "unreachable" | "not_run"
    def stage(n, fn):
        if "not_run" in state.values(): state[n] = "not_run"; return None          # a cap already stopped this run
        try: out = core.run_step(db, run, n, fn); state[n] = "ok"; return out
        except (core.TransientError, core.SourceUnreachable): state[n] = "unreachable"; return None   # a timeout is never "nothing found"
        except core.LimitExceeded: state[n] = "not_run"; return None                # stop cleanly, never raise out of the run

    ident = stage("identify", lambda: sources.identify(ctx, name, domain))
    sig = {"identify": identify_signals(name, domain, ident) if ident is not None else {}}
    cid = sig["identify"].get("company_id")
    if cid is not None:
        owner = core.claim_request(db, normalize.request_key(KIND, company_id=cid), run)
        if owner != run:                                   # same company already requested under another spelling
            core.set_run_status(db, run, f"duplicate_of:{owner}")
            return {**_existing_result(db, owner), "existing": True, "duplicate_of": owner}
        sig["profile"] = stage("profile", lambda: sources.profile(ctx, cid))
        if sig["profile"] and sig["profile"].get("status"): sig["identify"]["status"] = sig["profile"]["status"]   # company status comes from enrich
        sig["director"] = (stage("director", lambda: sources.director(ctx, cid, claimed)) if claimed
                           else {"not_requested": True, "sources": []})
    sig["adverse"] = stage("adverse", lambda: sources.adverse(ctx, name))
    sig = {k: v for k, v in sig.items() if v is not None}

    CHECK_OF = {"identify": "exists", "profile": "active", "director": "director_match", "adverse": "adverse_media"}
    def final():
        checks = policy.evaluate(sig, policy.PROPOSED_PARAMS, tier)
        for st, c in CHECK_OF.items():
            if state.get(st) == "unreachable":
                checks[c] = {"status": "unreachable", "reason": "source unreachable after retries; retry or send to a person", "sources": []}
            elif state.get(st) == "not_run":
                checks[c] = {"status": "not_run", "reason": "cost or time cap reached before this check ran", "sources": []}
        started = db.execute("SELECT started FROM runs WHERE id=?", (run,)).fetchone()[0]
        d = decision.decide(checks, core.run_cost(db, run), time.time() - started); d.cost_credits = core.run_cost(db, run)
        key = core.finalize(db, run, d)
        status = "stopped_at_cap" if "not_run" in state.values() else "held" if d.verdict == decision.HOLD else "done"
        return {"run_id": run, "status": status, "verdict": d.verdict, "missing_inputs": [k for k, x in (("website", domain), ("claimed_director", claimed)) if not x],
                "decision": d.to_dict(), "checks": checks, "action_key": key}
    if "unreachable" in state.values():                    # do not cache: a later retry must be able to re-run the stage
        res = final()
    else:
        res = core.run_step(db, run, "final", final)
    core.set_run_status(db, run, res["status"])
    return {**res, "existing": existed}
