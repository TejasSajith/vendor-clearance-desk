"""Live Crustdata sources for the pipeline. Every network call goes through ctx.call (core.cached_call): throttle, cache, limits, ledger.
Reads the key from CRUSTDATA_API_KEY only. Raw responses are saved to probe/raw/live/ (gitignored) for audit.
Raises core.RateLimited / core.TransientError for 429, timeouts and 5xx; returns only successful responses."""
import hashlib, json, os, time
from datetime import date, timedelta
from pathlib import Path
import requests
import core
from checks import normalize

BASE = "https://api.crustdata.com"
RAW = Path(__file__).resolve().parent.parent / "probe" / "raw" / "live"

def _post(path, body, timeout=90):
    try:
        r = requests.post(BASE + path, json=body, timeout=timeout, headers={
            "authorization": f"Bearer {os.environ['CRUSTDATA_API_KEY']}", "x-api-version": "2025-11-01"})
    except requests.exceptions.RequestException as e:
        raise core.TransientError(repr(e))
    if r.status_code == 429: raise core.RateLimited(float(r.headers.get("retry-after") or 0) or None)
    if r.status_code >= 500: raise core.TransientError(f"HTTP {r.status_code}")
    r.raise_for_status()
    out = {"credits": float(r.headers.get("x-credits-used") or 0), "body": r.json()}
    RAW.mkdir(parents=True, exist_ok=True)
    tag = hashlib.sha256(json.dumps([path, body], sort_keys=True).encode()).hexdigest()[:10]
    (RAW / f"{path.strip('/').replace('/', '_')}_{tag}.json").write_text(json.dumps(out["body"]))
    return out

def call(ctx, path, body):
    return ctx.call(path, body, lambda: _post(path, body), credits_from=lambda o: o["credits"])["body"]

class LiveSources:
    def identify(self, ctx, name, domain):
        res = call(ctx, "/company/identify", {"names": [name]})
        ms = (res[0]["matches"] if res else []) or []
        cands = [{"id": m["company_data"]["basic_info"]["crustdata_company_id"], "name": m["company_data"]["basic_info"].get("name") or "",
                  "score": m["confidence_score"]} for m in ms]
        dom_ids = None
        if domain:
            dres = call(ctx, "/company/identify", {"domains": [domain]})
            dom_ids = [m["company_data"]["basic_info"]["crustdata_company_id"] for m in ((dres[0]["matches"] if dres else []) or [])]
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
        raise NotImplementedError("director check is not part of this validation (no claimed director is supplied)")

    def adverse(self, ctx, name):
        import re
        from urllib.parse import urlparse
        hits, ran = [], 0
        for q, src in ((f"{name} fraud OR scam OR default OR FIR OR blacklisted", "web"), (f"{name} fraud OR default OR FIR", "news")):
            res = call(ctx, "/web/search/live", {"query": q, "sources": [src], "location": "IN"}); ran += 1
            tok = normalize.normalize_name(name).split()[0] if normalize.normalize_name(name) else ""
            for r in res.get("results") or []:
                text = f"{r.get('title','')} {r.get('snippet','')}"
                sev = 3 if re.search(r"\b(fir|blacklist\w*|default\w*|arrest\w*|insolven\w*)\b", text, re.I) else 2 if re.search(r"\b(fraud|scam)\b", text, re.I) else 1
                if tok and tok in normalize.normalize_name(text):
                    hits.append({"dated": bool(re.match(r"^\s*\d{1,2}\s+\S+\s+\d{4}\s+[—-]", r.get("snippet", ""))), "names_target": True,
                                 "discriminator": False, "source_ok": False, "severity": sev, "url_host": urlparse(r.get("url", "")).hostname})
        return {"state": "searched", "searches_run": ran, "hits": hits, "sources": ["crustdata:/web/search/live"]}
