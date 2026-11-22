"""Second pass (targeted site: queries, direct-URL fetch test, quoted news queries). Every call goes through core.cached_call (throttle, cache, ledger).
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


import base64
from urllib.parse import urlparse, parse_qs
run = core.start_run(db, f"probe-registry-news-pass2-{int(time.time())}")
found = {}
for key, name in COMPANIES:
    for site in ("zaubacorp.com", "tofler.in"):
        s = api(run, f"step6b_site_{site.split('.')[0]}_{key}", "/web/search/live", {"query": f"site:{site} {name}", "sources": ["web"], "location": "IN"})
        found[(key, site)] = [r["url"] for r in ((s["body"] or {}).get("results") or [])]
        print(key, site, "->", [u[:90] for u in found[(key, site)][:3]], flush=True)
# direct-URL fetch test on aggregator domains (home pages), then the first aggregator hit per company
api(run, "step6b_fetch_direct_aggregator_homes", "/web/enrich/live", {"urls": ["https://www.zaubacorp.com/", "https://www.tofler.in/"]})
hits = [u for k, v in found.items() for u in v if is_agg(u)][:4]
if hits: api(run, "step6b_fetch_aggregator_hits", "/web/enrich/live", {"urls": hits})
# quoted news queries
for key, name in COMPANIES:
    n = api(run, f"step6b_news_quoted_{key}", "/web/search/live", {"query": f'"{name}" fraud OR default OR FIR', "sources": ["news"], "location": "IN"})
    rs = (n["body"] or {}).get("results") or []
    print(key, "news results", len(rs), [r["url"][:60] for r in rs[:3]], flush=True)
# decode/resolve google.com/goto: try local decode, then ONE plain GET (no redirect follow) to see the Location header
g = next((r["url"] for f in RAW.glob("step6_news_search_*.json") for r in ((json.loads(f.read_text()) or {}).get("results") or []) if "google.com/goto" in r["url"]), None)
if g:
    tok = parse_qs(urlparse(g).query)["url"][0]
    blob = base64.urlsafe_b64decode(tok + "=" * (-len(tok) % 4))
    print("local decode contains http url:", bool(re.search(rb"https?://", blob)))
    try:
        r = requests.get(g, allow_redirects=False, timeout=20, headers={"user-agent": "Mozilla/5.0"})
        print("plain GET status", r.status_code, "location:", (r.headers.get("location") or "")[:120])
    except Exception as e: print("plain GET failed", repr(e))
print("done", round(spent, 2))
