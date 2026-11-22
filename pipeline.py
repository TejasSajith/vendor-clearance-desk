"""Pipeline: one vendor request in, one recommendation out. Resumable (core.run_step) and idempotent (request keys).
External data comes from injected `sources` (live Crustdata modules, or fakes in tests). Every external call a source makes
must go through ctx.call, which is core.cached_call (throttle, cache, limits, ledger, retry).
Verdicts are recommendations: CLEARED and REJECTED become pending actions that a person approves (core.finalize)."""
import json, time
import core, decision, policy
from checks import normalize, exists

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
    def call(self, endpoint, params, fn, credits_from=None, sensitive=False):
        return core.cached_call(self.db, self.run_id, endpoint, params, fn, credits_from=credits_from, sensitive=sensitive)

def identify_signals(name, domain, ident, params=None):
    """Our own matching (checks/exists.py); Crustdata's confidence score is not used for the choice."""
    p = params or policy.PROPOSED_PARAMS
    m = exists.match(name, domain, ident.get("candidates") or [], ident.get("domain_candidate_ids"), p["candidate_name_sim_floor"])
    base = {"sources": ["crustdata:/company/identify"], "status": ident.get("status"), "domain_mismatch_note": m["domain_note"]}
    if m["outcome"] == "none": return {**base, "found": False, "name_similarity": 0.0, "top_ties": 0, "domain_match": None}
    if m["outcome"] == "ambiguous":
        return {**base, "found": False, "name_similarity": m["above"][0]["sim"], "top_ties": len(m["above"]), "domain_match": None,
                "ambiguous": {"n": len(m["above"]), "candidates": [{"id": c["id"], "name": c["name"]} for c in m["above"]]}}
    c = m["chosen"]
    return {**base, "found": True, "company_id": c["id"], "name_similarity": c["sim"], "top_ties": 1, "domain_match": m["domain_match"]}

def _existing_result(db, run_id):
    row = db.execute("SELECT result FROM steps WHERE run_id=? AND name='final'", (run_id,)).fetchone()
    return json.loads(row[0]) if row else {"run_id": run_id, "status": "in_progress"}

def params_tag(params):
    """'' for the policy defaults; otherwise a short hash, so a run under other control settings is its own run (not a duplicate)."""
    if params is None or params == policy.PROPOSED_PARAMS: return ""
    import hashlib
    return "|p:" + hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:10]

def run_request(db, req, sources, params=None):
    """params: a full policy parameter set (controls.resolve); None = policy.PROPOSED_PARAMS."""
    p = params or policy.PROPOSED_PARAMS
    try: v = validate_request(req)
    except ValidationError as e:                           # a clean result, not a crash
        return {"status": "invalid", "verdict": None, "field": e.field, "message": str(e)}
    name, domain, tier, claimed = v["vendor_name"], v["domain"], v["risk_tier"], v["claimed_director"]
    fp = (core.salted_hash(db, claimed)[:16] if claimed else "") + params_tag(params)   # the claimed name itself is never stored, logged or keyed
    pk = normalize.request_key(KIND, name, domain, extra=fp)
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
    sig = {"identify": identify_signals(name, domain, ident, p) if ident is not None else {}}
    cid = sig["identify"].get("company_id")
    if cid is not None:
        owner = core.claim_request(db, normalize.request_key(KIND, company_id=cid, extra=fp), run)
        if owner != run:                                   # same company already requested under another spelling
            core.set_run_status(db, run, f"duplicate_of:{owner}")
            return {**_existing_result(db, owner), "existing": True, "duplicate_of": owner}
        sig["profile"] = stage("profile", lambda: sources.profile(ctx, cid))
        if sig["profile"] and sig["profile"].get("status"): sig["identify"]["status"] = sig["profile"]["status"]   # company status comes from enrich
        if claimed: sig["director"] = stage("director", lambda: sources.director(ctx, cid, claimed))
    if "director" not in sig:                              # nothing to check, or nothing to check it against
        sig["director"] = {"not_requested": True, "sources": []} if not claimed else {"no_company": True, "sources": []}
    sig["adverse"] = stage("adverse", lambda: sources.adverse(ctx, name, domain))
    sig = {k: v for k, v in sig.items() if v is not None}

    CHECK_OF = {"identify": "exists", "profile": "active", "director": "director_match", "adverse": "adverse_media"}
    def final():
        checks = policy.evaluate(sig, p, tier)
        for st, c in CHECK_OF.items():
            if state.get(st) == "unreachable":
                checks[c] = {"status": "unreachable", "reason": "source unreachable after retries; retry or send to a person", "sources": []}
            elif state.get(st) == "not_run":
                checks[c] = {"status": "not_run", "reason": "cost or time cap reached before this check ran", "sources": []}
        if claimed and state.get("director") == "ok": core.record_director_check(db, run, claimed, checks["director_match"]["status"])
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
    core.purge_sensitive(db, run)                          # raw person responses do not outlive the run
    return {**res, "existing": existed}


def main(argv=None, sources=None):
    """CLI: python pipeline.py run --vendor NAME [--website URL] [--tier low|medium|high] [--db PATH]
              [--claimed-director NAME | --claimed-director-env VAR | --claimed-director-prompt]
    The claimed director is taken at runtime only: it is never written to a file, log or the database (only a salted hash and the match result)."""
    import argparse, getpass, os, sys
    ap = argparse.ArgumentParser(prog="pipeline.py"); sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--vendor", required=True); r.add_argument("--website"); r.add_argument("--tier", default="low")
    r.add_argument("--db", default="clearance.db")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--claimed-director"); g.add_argument("--claimed-director-env"); g.add_argument("--claimed-director-prompt", action="store_true")
    a = ap.parse_args(argv)
    claimed = a.claimed_director or (os.environ.get(a.claimed_director_env) if a.claimed_director_env else None) \
        or (getpass.getpass("Claimed director (not echoed, not stored): ") if a.claimed_director_prompt else None)
    if sources is None:
        from checks import live
        sources = live.LiveSources()
    db = core.connect(a.db)
    res = run_request(db, {"vendor_name": a.vendor, "website": a.website, "risk_tier": a.tier, "claimed_director": claimed}, sources)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res.get("status") != "invalid" else 2

if __name__ == "__main__": raise SystemExit(main())
