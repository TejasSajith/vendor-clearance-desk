"""Live Crustdata sources for the pipeline. Every network call goes through ctx.call (core.cached_call): throttle, cache, limits, ledger.
Reads the key from CRUSTDATA_API_KEY only. Raw responses are saved to probe/raw/live/ (gitignored) for audit.
Raises core.RateLimited / core.TransientError for 429, timeouts and 5xx; returns only successful responses."""
import hashlib, json, os, time
from datetime import date, timedelta
from pathlib import Path
import requests
import core
from checks import normalize, adverse

BASE = "https://api.crustdata.com"
RAW = Path(__file__).resolve().parent.parent / "probe" / "raw" / "live"

def _post(path, body, timeout=90, save_raw=True):
    try:
        r = requests.post(BASE + path, json=body, timeout=timeout, headers={
            "authorization": f"Bearer {os.environ['CRUSTDATA_API_KEY']}", "x-api-version": "2025-11-01"})
    except requests.exceptions.RequestException as e:
        raise core.TransientError(repr(e))
    if r.status_code == 429:                           # back off using the reset time (X-RateLimit-Reset is seconds until the window resets)
        raise core.RateLimited(float(r.headers.get("x-ratelimit-reset") or r.headers.get("retry-after") or 0) or None)
    if r.status_code >= 500: raise core.TransientError(f"HTTP {r.status_code}")
    r.raise_for_status()
    out = {"credits": float(r.headers.get("x-credits-used") or 0), "body": r.json()}
    if not save_raw: return out                       # person data: never written to a file
    RAW.mkdir(parents=True, exist_ok=True)
    tag = hashlib.sha256(json.dumps([path, body], sort_keys=True).encode()).hexdigest()[:10]
    (RAW / f"{path.strip('/').replace('/', '_')}_{tag}.json").write_text(json.dumps(out["body"]))
    return out

def call(ctx, path, body, sensitive=False):
    return ctx.call(path, body, lambda: _post(path, body, save_raw=not sensitive), credits_from=lambda o: o["credits"], sensitive=sensitive)["body"]

class LiveSources:
    def identify(self, ctx, name, domain):
        res = call(ctx, "/company/identify", {"names": [name]})
        ms = (res[0]["matches"] if res else []) or []
        cands = [{"id": m["company_data"]["basic_info"]["crustdata_company_id"], "name": m["company_data"]["basic_info"].get("name") or "",
                  "score": m["confidence_score"], "domain": m["company_data"]["basic_info"].get("primary_domain")} for m in ms]
        dom_ids = None
        if domain:
            dres = call(ctx, "/company/identify", {"domains": [domain]})
            dom_ids = [m["company_data"]["basic_info"]["crustdata_company_id"] for m in ((dres[0]["matches"] if dres else []) or [])]
        self.records = {c["id"]: c for c in cands}
        return {"candidates": cands, "status": None, "domain_candidate_ids": dom_ids}

    def profile(self, ctx, cid):
        e = call(ctx, "/company/enrich", {"crustdata_company_ids": [cid], "fields": ["basic_info", "headcount", "web_traffic"]})
        cd = e[0]["matches"][0]["company_data"] if e and e[0].get("matches") else {}
        ts = (cd.get("headcount") or {}).get("timeseries") or []
        since = (date.today() - timedelta(days=90)).isoformat()
        j = call(ctx, "/job/search", {"filters": {"op": "and", "conditions": [
            {"field": "company.basic_info.company_id", "type": "=", "value": cid},
            {"field": "metadata.date_added", "type": "=>", "value": since}]}, "fields": ["metadata.date_added"], "limit": 1})
        wt = (cd.get("web_traffic") or {}).get("domain_traffic") or {}
        from datetime import date as _d
        pts = [_d.fromisoformat(p["date"]) for p in ts if p.get("date")]
        counts = sorted((_d.fromisoformat(p["date"]), p["employee_count"]) for p in ts if p.get("employee_count"))
        trend = None
        if len(counts) >= 2:
            last_d, last_v = counts[-1]; older = [c for c in counts if (last_d - c[0]).days >= 180]
            if older and older[-1][1]: trend = round((last_v - older[-1][1]) / older[-1][1] * 100, 1)
        return {"status": (cd.get("basic_info") or {}).get("status"), "headcount_total": (cd.get("headcount") or {}).get("total"),
                "headcount_trend_pct": trend, "series_age_days": (date.today() - max(pts)).days if pts else None,
                "jobs_90d": j.get("total_count"), "traffic_present": any(v.get("monthly_visitors") for v in wt.values()),
                "sources": ["crustdata:/company/enrich", "crustdata:/job/search"]}

    def director(self, ctx, cid, claimed):
        """Is the claimed person currently listed at this company? Person Search by name and employer (NOT yet validated live).
        The name only goes into the request; the call log keeps a salted hash, the raw response is not saved and is purged at the end of the run.
        Returns booleans only. This is profile data, not a director of record."""
        rec = getattr(self, "records", {}).get(cid, {})
        conds = [{"field": "basic_profile.name", "type": "=", "value": claimed}]
        if rec.get("name"): conds.append({"field": "experience.employment_details.current.name", "type": "(.)", "value": rec["name"]})
        res = call(ctx, "/person/search", {"filters": {"op": "and", "conditions": conds},
                                           "fields": ["crustdata_person_id", "basic_profile.headline", "experience.employment_details.current"], "limit": 5}, sensitive=True)
        people = res.get("profiles") or []
        self.stats = {"results": len(people), "total_count": res.get("total_count"),
                      "with_current_role_at_company": sum(1 for p in people if any(r.get("crustdata_company_id") == cid for r in ((p.get("experience") or {}).get("employment_details", {}).get("current") or []))),
                      "fields_present": sorted({k for p in people for k in p}),
                      "basic_profile_fields": sorted({k for p in people for k in (p.get("basic_profile") or {})}),
                      "current_role_fields": sorted({k for p in people for r in ((p.get("experience") or {}).get("employment_details", {}).get("current") or []) for k in r})}   # names of fields and counts only, never values
        cur = [r for p in people for r in ((p.get("experience") or {}).get("employment_details", {}).get("current") or []) if r.get("crustdata_company_id") == cid]
        tok = (normalize.normalize_name(rec.get("name", "")).split() or [""])[0]
        head = " ".join(((p.get("basic_profile") or {}).get("headline") or "") for p in people).lower()
        return {"found": bool(cur), "company_id_match": bool(cur), "start_date_plausible": any(r.get("start_date") for r in cur),
                "same_name_candidates": len(people), "discriminators_agree": bool(tok) and tok in head and len(people) == 1, "contradicted": False,
                "sources": ["crustdata:/person/search"]}

    def adverse(self, ctx, name, domain=""):
        """2 searches (web and news). Returns per-result FEATURES (checks/adverse.py); the pipeline derives the policy signals from them."""
        per = []
        for q, src in ((f"{name} fraud OR scam OR default OR FIR OR blacklisted", "web"), (f"{name} fraud OR default OR FIR", "news")):
            res = call(ctx, "/web/search/live", {"query": q, "sources": [src], "location": "IN"})
            rs = res.get("results") or []
            per.append({"source": src, "n_results": len(rs), "results": [adverse.result_features(r, name, domain) for r in rs]})
        return {"per_search": per, "sources": ["crustdata:/web/search/live"]}
