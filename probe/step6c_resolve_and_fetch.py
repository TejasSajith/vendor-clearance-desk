"""Third pass: resolve google.com/goto links (plain GET, no redirect follow, free) and Web Fetch the real targets. Every call goes through core.cached_call (throttle, cache, ledger).
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


import glob
from urllib.parse import urlparse
def resolve(u):
    try:
        r = requests.get(u, allow_redirects=False, timeout=20, headers={"user-agent": "Mozilla/5.0"})
        return r.headers.get("location") if r.status_code in (301, 302, 303, 307, 308) else None
    except Exception: return None
run = core.start_run(db, f"probe-registry-news-pass3-{int(time.time())}")
res = {}
def results(f):
    try: return (json.loads(open(f).read()) or {}).get("results") or []
    except Exception: return []
cands = {}
for key, _ in COMPANIES:
    for f in sorted(glob.glob(str(RAW / f"step6*_{key}.json"))) + sorted(glob.glob(str(RAW / f"step6b_site_*_{key}.json"))):
        for r in results(f):
            if "google.com/goto" in r.get("url", ""): cands.setdefault(key, {})[r["url"]] = (f.split("/")[-1], r["title"][:60])
out = {}
for key, d in cands.items():
    for u, (f, t) in list(d.items())[:9]:
        loc = resolve(u); time.sleep(0.4)
        out.setdefault(key, []).append({"from": f, "title": t, "resolved_host": urlparse(loc).hostname if loc else None, "resolved": loc})
        print(key, f, "->", (urlparse(loc).hostname if loc else None), flush=True)
json.dump(out, open(RAW / "step6c_resolved.json", "w"))
# fetch: up to 2 aggregator targets per company, then 2 news targets overall
n = 0
for key, rows in out.items():
    agg = [r["resolved"] for r in rows if r["resolved"] and is_agg(r["resolved"])][:2]
    if agg: api(run, f"step6c_fetch_aggregator_{key}", "/web/enrich/live", {"urls": agg}); n += 1
news = [r["resolved"] for key, rows in out.items() for r in rows if r["resolved"] and "news_search" in r["from"]][:2]
if news: api(run, "step6c_fetch_news_resolved", "/web/enrich/live", {"urls": news})
print("done", round(spent, 2))
