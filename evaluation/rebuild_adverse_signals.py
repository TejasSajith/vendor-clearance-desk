"""Re-derive the adverse signals in evaluation/signals_real.json from SAVED raw responses (the cache table of the collection database),
at 0 credits and with no network. Each result becomes a small feature record (host, source class, name phrase, domain, legal suffix,
industry term, obituary, person page, severity, date text, url id); no text and no URL is kept. The rules (source classes, name
collision) are evaluated at scoring time from these features, so the sweep can switch them on and off.
    python evaluation/rebuild_adverse_signals.py [--db probe/live/tuning.db] [--signals evaluation/signals_real.json]"""
import argparse, csv, hashlib, json, sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "evaluation"))
from checks import adverse, normalize

QUERIES = ((" fraud OR scam OR default OR FIR OR blacklisted", "web"), (" fraud OR default OR FIR", "news"),
           (" insolvency OR struck off OR closed down OR shut down", "web"), (" complaint OR lawsuit OR court case OR NCLT", "web"))   # same as collect_signals.CollectSources.QUERIES

def cache_key(body, repeat=0):
    params = {**body, "_repeat": repeat} if repeat else body
    return hashlib.sha256(json.dumps(["/web/search/live", params], sort_keys=True).encode()).hexdigest()

def per_search_from_cache(db, name, domain, repeat=0, rules=None):
    per = []
    for suffix, src in QUERIES:
        body = {"query": f"{name}{suffix}", "sources": [src], "location": "IN"}
        row = db.execute("SELECT response FROM cache WHERE key=?", (cache_key(body, repeat),)).fetchone()
        if not row: continue
        rs = (json.loads(row[0]).get("body") or {}).get("results") or []
        feats = [adverse.result_features(r, name, domain, rules) for r in rs]
        for f in feats: f.pop("url", None)                      # stored signals keep no URL
        per.append({"source": src, "n_results": len(rs), "results": feats})
    return per

def adverse_block(per, rules):
    return {"state": "searched", "searches_run": len(per), "results_scanned": sum(p["n_results"] for p in per), "per_search": per,
            "sources": ["crustdata:/web/search/live"], "rules_version": rules["version"]}

def rebuild(doc, rows, db, rules=None):
    rules = rules or adverse.load_rules(); changed = 0
    by_id = {r["case_id"]: r for r in rows}
    for cid, sig in doc["rows"].items():
        r = by_id.get(cid)
        if not r: continue
        dom = normalize.normalize_domain(r["website"]); per = per_search_from_cache(db, r["vendor_name"], dom, 0, rules)
        if per: sig["adverse"] = adverse_block(per, rules); sig["adverse_rules_version"] = rules["version"]; changed += 1
    for cid, reps in doc.get("repeats", {}).items():
        r = by_id.get(cid)
        if not r: continue
        for k in ("1", "2"):
            per = per_search_from_cache(db, r["vendor_name"], normalize.normalize_domain(r["website"]), int(k), rules)
            if per: reps[k] = adverse_block(per, rules)
    doc["rebuilt_with"] = "evaluation/rebuild_adverse_signals.py"; doc["rules_version"] = rules["version"]
    return changed

def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--db", default=str(ROOT / "probe" / "live" / "tuning.db"))
    ap.add_argument("--signals", default=str(ROOT / "evaluation" / "signals_real.json")); ap.add_argument("--csv", default=str(ROOT / "evaluation" / "cases_real.csv"))
    a = ap.parse_args(argv)
    doc = json.loads(Path(a.signals).read_text()); rows = list(csv.DictReader(open(a.csv)))
    db = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)       # read only: no calls, no credits
    n = rebuild(doc, rows, db)
    tmp = Path(a.signals).with_suffix(".tmp"); tmp.write_text(json.dumps(doc, indent=1)); tmp.replace(a.signals)
    print(f"rebuilt adverse signals for {n} rows with rules {doc['rules_version']} (0 credits)")

if __name__ == "__main__": main()
