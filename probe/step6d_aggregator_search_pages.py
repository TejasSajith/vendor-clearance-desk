"""Fourth pass: do aggregator site-search pages fetch directly (no CIN needed)? Every call goes through core.cached_call (throttle, cache, ledger).
Run from the repo root with CRUSTDATA_API_KEY set. Budget guard: 40 credits."""
import json, os, re, sys, time, requests
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import core

RAW = ROOT / "probe" / "raw"; LOG = ROOT / "probe" / "calls.jsonl"
BASE = "https://api.crustdata.com"; BUDGET = 40.0
db = core.connect(str(ROOT / "probe" / "probe.db"))
spent = 0.0
COMPANIES = [("delhivery", "Delhivery"), ("everest", "Everest Fleet"), ("xtrans", "Xtrans Logistics")]
AGG = ("zaubacorp.com", "tofler.in", "thecompanycheck.com", "instafinancials.com", "falconebiz.com", "mca.gov.in", "indiafilings.com", "companydetails.in")

def api(run, tag, path, body, timeout=120):
    """One billed call via core.cached_call. Cost = x-credits-used header."""
    global spent
    if spent >= BUDGET: raise SystemExit("budget reached")
    def fn():
        t0 = time.time()
        try:
            r = requests.post(BASE + path, json=body, timeout=timeout, headers={
                "authorization": f"Bearer {os.environ['CRUSTDATA_API_KEY']}", "x-api-version": "2025-11-01"})
            out = {"status": r.status_code, "credits": float(r.headers.get("x-credits-used") or 0), "body": r.json() if r.text else None}
        except requests.exceptions.RequestException as e:
            out = {"status": "error", "credits": 0.0, "body": None, "error": repr(e)}
        out["ms"] = int((time.time() - t0) * 1000)
        return out
    out = core.cached_call(db, run, path, body, fn, credits_from=lambda o: o["credits"])
    spent += out["credits"]
    with LOG.open("a") as f:
        f.write(json.dumps({"ts": time.strftime("%H:%M:%S"), "tag": tag, "endpoint": path, "params": body, "status": out["status"],
                            "credits": out["credits"], "ms": out["ms"], "via": "core.cached_call"}) + "\n")
    (RAW / f"{tag}.json").write_text(json.dumps(out["body"]))
    return out

def is_agg(u): return any(h in u for h in AGG)


run = core.start_run(db, f"probe-registry-news-pass4-{int(time.time())}")
o = api(run, "step6d_fetch_aggregator_search_pages", "/web/enrich/live", {"urls": [
    "https://www.tofler.in/search?q=Delhivery", "https://www.zaubacorp.com/companysearchresults/Delhivery"]})
for p in (o["body"] or []): print(p.get("success"), p.get("url"), p.get("title"), len(p.get("content") or ""))
print("done", round(spent, 2))
