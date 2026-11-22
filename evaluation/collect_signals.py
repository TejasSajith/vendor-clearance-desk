"""Phase 1: run the live pipeline on every row of evaluation/cases_real.csv and save SIGNALS (no labels needed) to
evaluation/signals_real.json. Resumable and exactly-once (core.run_step + core.cached_call). Per-vendor outcomes go to FILES ONLY;
the console and log get counts and credits only. Third-party company names are not stored in the signals (candidates keep a similarity,
a domain and an id).
    python evaluation/collect_signals.py [--minutes 45]
Adverse media: 4 distinct searches per vendor. For 12 rows the 4 searches are repeated (run 1 and 2, at least a minute apart) to measure stability."""
import argparse, csv, hashlib, json, os, random, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import core, pipeline
from checks import adverse, exists, live, normalize

EV = ROOT / "evaluation"; CSV = EV / "cases_real.csv"; OUT = EV / "signals_real.json"; PROG = EV / "tuning_progress.md"; STATE = ROOT / "probe" / "live" / "tuning_state.json"
DB = ROOT / "probe" / "live" / "tuning.db"
CREDIT_CAP = 1500.0; PHASE0_CREDITS = 153.08

class CollectSources(live.LiveSources):
    def identify(self, ctx, name, domain):
        res = live.call(ctx, "/company/identify", {"names": [name]})
        ms = (res[0]["matches"] if res else []) or []
        cands = [{"id": m["company_data"]["basic_info"]["crustdata_company_id"], "name": "",
                  "sim": exists.token_sort_ratio(name, m["company_data"]["basic_info"].get("name") or ""),
                  "domain": normalize.normalize_domain(m["company_data"]["basic_info"].get("primary_domain")) or None} for m in ms]   # names are not kept
        dom_ids = None
        if domain:
            dres = live.call(ctx, "/company/identify", {"domains": [domain]})
            dom_ids = [m["company_data"]["basic_info"]["crustdata_company_id"] for m in ((dres[0]["matches"] if dres else []) or [])]
        return {"candidates": cands, "status": None, "domain_candidate_ids": dom_ids}

    QUERIES = ((" fraud OR scam OR default OR FIR OR blacklisted", "web"), (" fraud OR default OR FIR", "news"),
               (" insolvency OR struck off OR closed down OR shut down", "web"), (" complaint OR lawsuit OR court case OR NCLT", "web"))

    def adverse(self, ctx, name, domain="", repeat=0):
        per, hits, scanned = [], [], 0
        for suffix, src in self.QUERIES:
            body = {"query": f"{name}{suffix}", "sources": [src], "location": "IN"}
            key = {**body, "_repeat": repeat} if repeat else body            # repeats get their own cache entry; the API never sees the marker
            res = ctx.call("/web/search/live", key, lambda b=body: live._post("/web/search/live", b), credits_from=lambda o: o["credits"])["body"]
            rs = res.get("results") or []; scanned += len(rs); sh = []
            for r in rs:
                hs = adverse.build_hits([r], name, domain)
                if hs:
                    h = hs[0]; m = adverse.DATE_PREFIX.match(r.get("snippet", ""))
                    h.update({"date_text": m.group(1) if m else None, "rank": r.get("position"), "url_id": hashlib.sha256(r.get("url", "").encode()).hexdigest()[:10]})
                    sh.append(h)
            per.append({"source": src, "n_results": len(rs), "hits": sh}); hits += sh
        return {"state": "searched", "searches_run": len(per), "results_scanned": scanned, "hits": hits, "per_search": per, "sources": ["crustdata:/web/search/live"]}

def spent(db=None):
    c = core.connect(str(DB))              # a short-lived connection: safe to call from any thread
    try: return c.execute("SELECT COALESCE(SUM(credits),0) FROM calls").fetchone()[0]
    finally: c.close()

def load_out(): return json.loads(OUT.read_text()) if OUT.exists() else {"rows": {}, "repeats": {}}
def save_out(d):
    tmp = OUT.with_suffix(".tmp"); tmp.write_text(json.dumps(d, indent=1)); tmp.replace(OUT)

def state_of(res, sig_identify):
    if res.get("status") == "stopped_at_cap": return "stopped_at_cap"
    if any(c["status"] == "unreachable" for c in res["checks"].values()): return "unreachable"
    if sig_identify.get("ambiguous"): return "ambiguous"
    if not sig_identify.get("found"): return "no_record"
    return "done"

def collect_row(db, row, sources):
    domain = normalize.normalize_domain(row["website"])
    t0 = time.time(); before = spent(db)
    res = pipeline.run_request(db, {"vendor_name": row["vendor_name"], "website": row["website"] or None, "risk_tier": "low"}, sources)
    steps = {n: json.loads(r) for n, r in db.execute("SELECT name, result FROM steps WHERE run_id=?", (res["run_id"],))}
    ident = steps.get("identify") or {}
    sig_id = pipeline.identify_signals(row["vendor_name"], domain, ident) if ident else {}
    return {"case_id": row["case_id"], "stratum": row["stratum"], "split": row["split"], "state": state_of(res, sig_id), "run_status": res["status"],
            "input_domain": domain or None, "identify": {"candidates": ident.get("candidates", []), "domain_candidate_ids": ident.get("domain_candidate_ids")},
            "profile": steps.get("profile"), "adverse": steps.get("adverse"), "credits": round(spent(db) - before, 4), "seconds": round(time.time() - t0, 1)}

def write_progress(out, db, started, note=""):
    from collections import Counter
    rows = out["rows"]; c = Counter(r["state"] for r in rows.values())
    total = len(list(csv.DictReader(open(CSV))))
    reps = sum(len(v) for v in out["repeats"].values())
    PROG.write_text(f"""# tuning_progress.md (checkpoint {time.strftime('%H:%M:%S')} IST)

Phase 1 collection {note}. Counts only; per-vendor outcomes are in `evaluation/signals_real.json` (not printed anywhere).

- Rows collected: {len(rows)} of {total}
- States: {dict(c)}
- Adverse repeat runs recorded: {reps} (target 24: 12 rows x 2 repeats)
- Credits this tuning run (collection): {round(spent(db), 2)}; phase 0 case building: {PHASE0_CREDITS}; total {round(spent(db) + PHASE0_CREDITS, 2)} of the {CREDIT_CAP:g} cap
- Elapsed since collection start: {round((time.time() - started) / 60, 1)} min of 45
- Left: {total - len(rows)} rows, {24 - reps} repeat runs, then phases 2 to 6 (labels needed for 3 and 4)
""")

def checkpoint(out, db, started, note=""):
    save_out(out); write_progress(out, db, started, note)
    try:
        subprocess.run(["git", "add", str(PROG), str(OUT)], cwd=ROOT, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "eval: tuning collection checkpoint", "-m", "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"], cwd=ROOT, capture_output=True)
        subprocess.run(["git", "push", "-q", "origin", "main"], cwd=ROOT, capture_output=True, timeout=60)
    except Exception: pass

def main():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    ap = argparse.ArgumentParser(); ap.add_argument("--minutes", type=float, default=45); ap.add_argument("--workers", type=int, default=5); a = ap.parse_args()
    st = json.loads(STATE.read_text()) if STATE.exists() else {"started": time.time()}
    STATE.write_text(json.dumps(st)); started = st["started"]; deadline = started + a.minutes * 60
    db = core.connect(str(DB)); out = load_out(); rows = list(csv.DictReader(open(CSV)))
    lock = threading.Lock(); last_cp = [time.time()]
    def tick():                                   # call with the lock held
        if time.time() - last_cp[0] >= 600: checkpoint(out, db, started, "in progress"); last_cp[0] = time.time()
    def over_credit(): return spent(db) + PHASE0_CREDITS >= CREDIT_CAP - 20
    def work(r):
        if time.time() >= deadline or over_credit(): return
        wdb = core.connect(str(DB))
        try: res = collect_row(wdb, r, CollectSources())
        finally: wdb.close()
        with lock: out["rows"][r["case_id"]] = res; save_out(out); tick()
    # main pass in parallel (the per-endpoint throttle is shared and thread-safe), then retry rows that ended unreachable or stopped
    for n_pass in range(3):
        todo = [r for r in rows if r["case_id"] not in out["rows"] or out["rows"][r["case_id"]]["state"] in ("unreachable", "stopped_at_cap")]
        if not todo or time.time() >= deadline: break
        if n_pass: time.sleep(60)
        with ThreadPoolExecutor(a.workers) as ex: list(ex.map(work, todo))
    # adverse stability: 12 rows, 2 repeats each (run 0 is the collection itself), at least a minute apart per row
    rnd = random.Random(7)
    pools = {"large_legit": 3, "mid": 2, "small_real": 3, "shut_down": 1, "lookalike_or_wrong_domain": 1, "invented": 2}
    chosen = [r for s_, k in pools.items() for r in rnd.sample([x for x in rows if x["stratum"] == s_], k)]
    out["repeat_rows"] = [r["case_id"] for r in chosen]
    def repeat(job):
        r, k = job; cid = r["case_id"]
        if time.time() >= deadline or str(k) in out["repeats"].get(cid, {}): return
        wdb = core.connect(str(DB)); run = core.start_run(wdb, f"repeat-{cid}-{k}", run_id=f"rep_{cid}_{k}")
        try:
            if k == 2:                            # at least a minute after repeat 1 of the same row
                gap = 60 - (time.time() - out["repeats"].get(cid, {}).get("t", 0))
                if gap > 0: time.sleep(gap)
            sig = CollectSources().adverse(pipeline.Ctx(wdb, run), r["vendor_name"], normalize.normalize_domain(r["website"]), repeat=k)
        except (core.TransientError, core.SourceUnreachable, core.LimitExceeded): return
        finally: wdb.close()
        with lock: out["repeats"].setdefault(cid, {})[str(k)] = sig; out["repeats"][cid]["t"] = time.time(); save_out(out); tick()
    for k in (1, 2):
        with ThreadPoolExecutor(a.workers) as ex: list(ex.map(repeat, [(r, k) for r in chosen]))
    complete = len(out["rows"]) == len(rows)
    checkpoint(out, db, started, "finished" if complete else "stopped at the 45 minute wall clock")
    print(f"done: {len(out['rows'])}/{len(rows)} rows, credits {round(spent(db), 2)}", flush=True)

if __name__ == "__main__": main()
