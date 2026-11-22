"""Live validation of the real pipeline on 10 vendors (live Crustdata, every call through core.cached_call).
    python probe/live_validation.py main | rerun | variants | cap | crash | crash-child | report
Run from the repo root with CRUSTDATA_API_KEY in the environment. Hard stop at 60 credits across all databases.
No person names are used or written: no claimed director is supplied, and the leadership section is not requested."""
import json, os, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import core, pipeline
from checks import live

LIVE = ROOT / "probe" / "live"; LIVE.mkdir(exist_ok=True)
DB = {"main": LIVE / "live.db", "cap": LIVE / "cap.db", "crash": LIVE / "crash.db"}
BUDGET = 60.0
VENDORS = [
    ("large", "Delhivery", "delhivery.com"), ("large", "DTDC Express Limited", "https://www.dtdc.com"),
    ("mid", "Everest Fleet Pvt. Ltd.", "everestfleet.com"), ("mid", "ProConnect Supply Chain Solutions Ltd", "proconnect.co.in"),
    ("small", "Xtrans Logistics Pvt Ltd", "xtrans.in"), ("small", "LorryCare", "lorrycare.com"),
    ("lookalike A", "Ecom Express Ltd", "ecomexpress.in"), ("lookalike B", "Ecom Express Delivery Center", None),
    ("invented", "Zentrovia Cargo Solutions Pvt Ltd", None),
    ("wrong domain", "Future Supply Chain Solutions Limited", "xtrans.in"),       # real company, another company's domain
]

def spent_all():
    import sqlite3
    t = 0.0
    for p in DB.values():
        if p.exists():
            t += sqlite3.connect(str(p)).execute("SELECT COALESCE(SUM(credits),0) FROM calls").fetchone()[0]
    return t

_orig_post = live._post
def _guarded_post(path, body, timeout=90):
    if spent_all() >= BUDGET - 3: raise SystemExit(f"budget guard: {spent_all():.2f} credits spent, stopping before {BUDGET}")
    return _orig_post(path, body, timeout)
live._post = _guarded_post

def req(v): return {"vendor_name": v[1], "website": v[2], "risk_tier": "low"}

def snapshot(db):
    q = lambda s: db.execute(s).fetchone()[0]
    return {"runs": q("SELECT COUNT(*) FROM runs"), "actions": q("SELECT COUNT(*) FROM actions"), "calls": q("SELECT COUNT(*) FROM calls"),
            "credits": round(q("SELECT COALESCE(SUM(credits),0) FROM calls"), 4), "cache": q("SELECT COUNT(*) FROM cache")}

def run_all(db, label):
    rows = []
    for v in VENDORS:
        before = snapshot(db); t0 = time.time()
        r = pipeline.run_request(db, req(v), live.LiveSources())
        after = snapshot(db)
        rows.append({"bucket": v[0], "vendor": v[1], "run_id": r.get("run_id"), "status": r.get("status"), "verdict": r.get("verdict"),
                     "checks": {k: c["status"] for k, c in (r.get("checks") or {}).items()},
                     "reasons": {k: c["reason"] for k, c in (r.get("checks") or {}).items()},
                     "missing": (r.get("decision") or {}).get("missing"), "missing_inputs": r.get("missing_inputs"),
                     "credits_new": round(after["credits"] - before["credits"], 4), "seconds": round(time.time() - t0, 1),
                     "action_key": r.get("action_key"), "existing": r.get("existing")})
        print(f"[{label}] {v[1]}: {r.get('verdict')} {rows[-1]['checks']} +{rows[-1]['credits_new']} credits {rows[-1]['seconds']}s", flush=True)
    return rows

def main():
    mode = sys.argv[1]
    if mode == "main":
        db = core.connect(str(DB["main"])); rows = run_all(db, "main")
        (LIVE / "main_results.json").write_text(json.dumps({"rows": rows, "snapshot": snapshot(db)}, indent=1))
    elif mode == "rerun":
        db = core.connect(str(DB["main"])); before = snapshot(db); rows = run_all(db, "rerun"); after = snapshot(db)
        (LIVE / "rerun_results.json").write_text(json.dumps({"before": before, "after": after, "rows": rows}, indent=1))
        print("before", before, "\nafter ", after)
    elif mode == "variants":
        db = core.connect(str(DB["main"])); before = snapshot(db); out = []
        for base, site, names in (("Delhivery", "delhivery.com", ["Delhivery Ltd", "M/s Delhivery Limited", "Delhivery"]),
                                  ("Xtrans Logistics", "xtrans.in", ["Xtrans Logistics Ltd", "M/s Xtrans Logistics Limited", "Xtrans Logistics"])):
            for n in names:
                r = pipeline.run_request(db, {"vendor_name": n, "website": site}, live.LiveSources())
                out.append({"submitted": n, "run_id": r["run_id"], "verdict": r["verdict"], "existing": r["existing"]})
                print(out[-1], flush=True)
        after = snapshot(db)
        (LIVE / "variants_results.json").write_text(json.dumps({"rows": out, "before": before, "after": after}, indent=1)); print(before, after)
    elif mode == "cap":
        if DB["cap"].exists(): DB["cap"].unlink()
        db = core.connect(str(DB["cap"])); core.CONFIG["max_cost_credits_per_run"] = 2     # in-process only; config.json is unchanged
        v = VENDORS[2]; t0 = time.time()
        r = pipeline.run_request(db, req(v), live.LiveSources())
        rows = db.execute("SELECT endpoint, credits FROM calls").fetchall()
        res = {"vendor": v[1], "status": r["status"], "verdict": r["verdict"], "checks": {k: c["status"] for k, c in r["checks"].items()},
               "missing": r["decision"]["missing"], "reasons": [x["text"] for x in r["decision"]["reasons"]], "calls": rows,
               "credits": sum(c for _, c in rows), "seconds": round(time.time() - t0, 1), "actions": snapshot(db)["actions"]}
        (LIVE / "cap_results.json").write_text(json.dumps(res, indent=1)); print(json.dumps(res, indent=1))
    elif mode == "crash":
        if DB["crash"].exists(): DB["crash"].unlink()
        env = {**os.environ, "CRASH_AFTER": "2"}
        p = subprocess.run([sys.executable, __file__, "crash-child"], env=env, cwd=ROOT)
        db = core.connect(str(DB["crash"])); before = snapshot(db)
        rows_before = db.execute("SELECT id, endpoint, credits FROM calls ORDER BY id").fetchall()
        print("child exit code", p.returncode, "ledger before restart:", before, rows_before, flush=True)
        r = pipeline.run_request(db, req(VENDORS[4]), live.LiveSources())          # restart: same request, same db
        after = snapshot(db); rows_after = db.execute("SELECT id, endpoint, params, credits FROM calls ORDER BY id").fetchall()
        dup = len(rows_after) - len({(e, pr) for _, e, pr, _ in rows_after})
        res = {"child_exit_code": p.returncode, "before": before, "rows_before": rows_before, "after": after, "rows_after": [(i, e, c) for i, e, _, c in rows_after],
               "repeated_calls": dup, "verdict": r["verdict"], "status": r["status"], "actions": after["actions"], "runs": after["runs"]}
        (LIVE / "crash_results.json").write_text(json.dumps(res, indent=1)); print(json.dumps(res, indent=1))
    elif mode == "crash-child":
        n = {"i": 0}; orig = live.call
        def counting(ctx, path, body):
            out = orig(ctx, path, body); n["i"] += 1
            if n["i"] == int(os.environ["CRASH_AFTER"]): os._exit(137)      # killed right after the 2nd call returns
            return out
        live.call = counting
        db = core.connect(str(DB["crash"])); pipeline.run_request(db, req(VENDORS[4]), live.LiveSources())

if __name__ == "__main__": main()
