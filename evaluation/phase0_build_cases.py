"""Phase 0: build evaluation/cases_real.csv (labels left BLANK for the owner). Company Search (through core.cached_call), fixed seed.
Run once from the repo root with CRUSTDATA_API_KEY set. The pools are sampled from Crustdata, nothing is chosen from memory."""
import csv, json, random, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import core, pipeline
from checks import live, normalize

SEED = 20261122
IND = ["Transportation, Logistics, Supply Chain and Storage", "Logistics & Supply Chain", "Truck Transportation",
       "Freight and Package Transportation", "Transportation/Trucking/Railroad", "Warehousing and Storage"]
BAD_WORDS = ("air", "airport", "airports", "airways", "aviation", "spicejet", "railway", "railways", "rail", "metro", "government", "govt", "ministry", "authority",
             "drdo", "corporation", "hospital", "school", "university", "bank", "register", "working", "tourism", "tours", "travels")
FIRST_NAMES = {"rajesh", "suresh", "ramesh", "amit", "sunil", "anil", "vijay", "sanjay", "ravi", "mohan", "krishna", "prabhas", "rahul", "deepak",
               "manoj", "ashok", "ajay", "vikas", "sachin", "pradeep", "mahesh", "dinesh", "naresh", "rakesh", "sandeep", "arun", "satish", "kiran", "jeena"}
FIELDS = ["basic_info.name", "basic_info.primary_domain", "basic_info.year_founded", "basic_info.status", "headcount.total"]

def ok_name(n):
    t = normalize.normalize_name(n).split()
    return bool(t) and not any(w in t for w in BAD_WORDS) and not (set(t) & FIRST_NAMES)

def search(ctx, extra, limit, sort=None, name=None):
    conds = [{"field": "locations.country", "type": "=", "value": "India"}] + extra
    if name is None: conds.append({"field": "basic_info.industries", "type": "in", "value": IND})
    else: conds.append({"field": "basic_info.name", "type": "(.)", "value": name})
    body = {"filters": {"op": "and", "conditions": conds}, "fields": FIELDS, "limit": limit}
    if sort: body["sorts"] = [sort]
    sub = pipeline.Ctx(ctx.db, core.start_run(ctx.db, "phase0-search-" + str(abs(hash(json.dumps(body, sort_keys=True))))))   # one run (and one cap) per search
    res = live.call(sub, "/company/search", body)
    out = []
    for c in res.get("companies", []):
        b = c.get("basic_info") or {}
        out.append({"id": c["crustdata_company_id"], "name": (b.get("name") or "").strip(), "domain": normalize.normalize_domain(b.get("primary_domain")),
                    "year": b.get("year_founded"), "status": b.get("status"), "headcount": (c.get("headcount") or {}).get("total")})
    return out

def main():
    db = core.connect(str(ROOT / "probe" / "live" / "phase0.db")); ctx = pipeline.Ctx(db, core.start_run(db, "phase0"))
    hc = lambda lo, hi: [{"field": "headcount.total", "type": "=>", "value": lo}, {"field": "headcount.total", "type": "=<", "value": hi}]
    act = [{"field": "basic_info.status", "type": "=", "value": "active"}]
    large = [c for c in search(ctx, hc(4000, 200000) + act, 70, {"field": "headcount.total", "order": "desc"}) if ok_name(c["name"])]
    mid = [c for c in search(ctx, hc(300, 3000) + act, 80) if ok_name(c["name"]) and c["domain"]]
    small = [c for c in search(ctx, hc(11, 50) + act + [{"field": "basic_info.year_founded", "type": "=<", "value": 2022}], 120) if ok_name(c["name"]) and c["domain"]]
    dead = [c for c in search(ctx, hc(20, 5000) + [{"field": "basic_info.status", "type": "=", "value": "deleted"}], 80) if ok_name(c["name"]) and c["domain"]]
    rnd = random.Random(SEED)
    pick = lambda pool, n, seen: [c for c in rnd.sample(pool, len(pool)) if c["id"] not in seen][:n]
    rows, seen = [], set()
    def add(stratum, cs, site_of=lambda c: c["domain"], note=""):
        for c in cs:
            seen.add(c["id"]); rows.append({"vendor_name": c["name"], "website": site_of(c), "stratum": stratum, "source_note": note or "Crustdata company search", "cid": c["id"]})
    add("large_legit", large[:14], note="Crustdata search, largest by headcount; VERIFY it is a logistics firm and trading")
    add("mid", pick(mid, 12, seen), note="Crustdata search, 300 to 3000 staff")
    add("small_real", pick(small, 16, seen), note="Crustdata search, 11 to 50 staff; VERIFY it is real and trading")
    add("shut_down", pick(dead, 8, seen), note="Crustdata status=deleted (a profile flag, not proof of closure); VERIFY")
    wrong_pool = pick(mid, 3, seen)
    domains = [c["domain"] for c in pick(mid, 3, seen | {w["id"] for w in wrong_pool})]
    for c, d in zip(wrong_pool, domains):
        seen.add(c["id"]); rows.append({"vendor_name": c["name"], "website": d, "stratum": "lookalike_or_wrong_domain", "source_note": "real company, a DIFFERENT company's domain (wrong domain by construction)", "cid": c["id"]})
    for big in [c["name"].split()[0] for c in large[:12]][:8]:
        if sum(1 for r in rows if r["stratum"] == "lookalike_or_wrong_domain") >= 6: break
        for c in search(ctx, hc(2, 60), 10, name=big):
            if c["id"] not in seen and ok_name(c["name"]) and normalize.normalize_name(c["name"]).split()[:1] == [big.lower()]:
                seen.add(c["id"]); rows.append({"vendor_name": c["name"], "website": c["domain"], "stratum": "lookalike_or_wrong_domain",
                                                "source_note": f"small entity whose name starts like a large firm; VERIFY it is a different company", "cid": c["id"]}); break
    invented = ["Quillvane Freight Pvt Ltd", "Nordexa Carriers Pvt Ltd", "Brivaldo Logistics Pvt Ltd", "Taliswen Cargo Movers Pvt Ltd", "Vexoria Transport Solutions Pvt Ltd",
                "Ombrelin Supply Chain Pvt Ltd", "Kestravon Haulage Pvt Ltd", "Dunmarek Freight Forwarders Pvt Ltd", "Pelorix Trucking Co Pvt Ltd", "Yarvenzia Express Carriers Pvt Ltd"]
    for n in invented: rows.append({"vendor_name": n, "website": "", "stratum": "invented", "source_note": "invented by construction (nonexistent)", "cid": ""})
    # stratified fixed-seed split: 2/3 tune, 1/3 holdout
    by = {}
    for r in rows: by.setdefault(r["stratum"], []).append(r)
    r2 = random.Random(SEED + 1)
    for s, rs in by.items():
        r2.shuffle(rs); k = round(len(rs) / 3)
        for i, r in enumerate(rs): r["split"] = "holdout" if i < k else "tune"
    rows.sort(key=lambda r: (["large_legit", "mid", "small_real", "shut_down", "invented", "lookalike_or_wrong_domain"].index(r["stratum"]), r["vendor_name"]))
    for i, r in enumerate(rows, 1): r["case_id"] = f"c{i:03d}"
    cols = ["case_id", "vendor_name", "website", "stratum", "split", "expected_exists", "expected_active", "expected_adverse", "source_note", "cid"]
    with open(ROOT / "evaluation" / "cases_real.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({**r, "expected_exists": "", "expected_active": "", "expected_adverse": ""})
    from collections import Counter
    print(Counter(r["stratum"] for r in rows), len(rows), "credits", round(db.execute("SELECT COALESCE(SUM(credits),0) FROM calls").fetchone()[0], 2))

if __name__ == "__main__": main()
