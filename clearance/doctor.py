"""Health check: python -m clearance doctor [--db clearance.db]

  database   file present, integrity_check, engine tables, runs by status, actions pending or stuck in 'executing'
  keys       CRUSTDATA_API_KEY, GEMINI_API_KEY, APP_PASSWORD: set or not set (values are never read into the report)
  headroom   calls in the last 60 s per endpoint against config.json rate_limits_per_min, and account-wide against account_rpm
  budget     credits spent today against the daily cap (ops_config.json, PROPOSED)
  ledger     the last reconciliation recorded by finance/cost_report.py --balance-before/--balance-after
  alerts     the most recent cap alerts
The database is opened read-only; doctor never creates or changes it and makes no network call.
"""
import os, sqlite3, time
from datetime import datetime
from pathlib import Path
import core
from clearance import guard, ops

KEYS = ("CRUSTDATA_API_KEY", "GEMINI_API_KEY", "APP_PASSWORD")
ENGINE_TABLES = ("runs", "steps", "calls", "cache", "actions", "request_keys")

def _env_names(path):
    try: return {line.split("=", 1)[0].strip() for line in Path(path).read_text().splitlines() if "=" in line and not line.strip().startswith("#")}
    except OSError: return set()

def check(db_path, env=None, dotenv=None):
    env = os.environ if env is None else env
    in_dotenv = _env_names(dotenv or (core.Path(core.__file__).parent / ".env"))
    rep = {"ok": True, "problems": [], "warnings": [], "db": db_path,
           "keys": {k: ("set (environment)" if env.get(k) else "set (.env)" if k in in_dotenv else "not set") for k in KEYS}}
    if rep["keys"]["CRUSTDATA_API_KEY"] == "not set": rep["warnings"].append("CRUSTDATA_API_KEY not set: live runs will fail; demo mode and tests still work")
    if not Path(db_path).exists():
        rep["ok"] = False; rep["problems"].append(f"database {db_path} not found (a run creates it)"); return rep
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        integ = db.execute("PRAGMA integrity_check").fetchone()[0]
        rep["integrity"] = integ
        if integ != "ok": rep["ok"] = False; rep["problems"].append(f"integrity_check: {integ}")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in ENGINE_TABLES if t not in tables]
        if missing: rep["ok"] = False; rep["problems"].append("missing tables: " + ", ".join(missing)); return rep
        rep["runs"] = dict(db.execute("SELECT status, COUNT(*) FROM runs GROUP BY status").fetchall())
        rep["actions"] = dict(db.execute("SELECT status, COUNT(*) FROM actions GROUP BY status").fetchall())
        if rep["actions"].get("executing"): rep["warnings"].append(f"{rep['actions']['executing']} action(s) left in 'executing': the next start-up finishes them")
        rep["audit_log"] = "installed (append-only triggers)" if "audit_log" in tables else "not installed (run any python -m clearance command once)"
        now = time.time()
        lim, acct = core.CONFIG["rate_limits_per_min"], core.CONFIG.get("account_rpm")
        used = dict(db.execute("SELECT endpoint, COUNT(*) FROM calls WHERE ts > ? GROUP BY endpoint", (now - 60,)).fetchall())
        rep["headroom"] = {ep: {"last_60s": n, "limit": core._limit(ep), "free": core._limit(ep) - n} for ep, n in sorted(used.items())}
        rep["headroom"]["account"] = {"last_60s": sum(used.values()), "limit": acct, "free": (acct - sum(used.values())) if acct else None}
        if any(v["free"] is not None and v["free"] <= 0 for v in rep["headroom"].values()): rep["warnings"].append("an endpoint is at its rate limit right now; calls will wait")
        cap = ops.OPS.get("max_cost_credits_per_day")
        today = db.execute("SELECT COALESCE(SUM(credits),0) FROM calls WHERE ts>=?", (guard.day_start(now),)).fetchone()[0]
        rep["budget"] = {"spent_today": round(today, 4), "daily_cap": cap, "left": None if cap is None else round(cap - today, 4)}
        if cap is not None and today >= cap: rep["warnings"].append("daily cap reached: new paid calls are refused until tomorrow")
        if "reconciliations" in tables:
            r = db.execute("SELECT ts, balance_before, balance_after, ledger_credits, difference FROM reconciliations ORDER BY ts DESC LIMIT 1").fetchone()
            rep["last_reconciliation"] = {"when": datetime.fromtimestamp(r[0]).isoformat(timespec="seconds"), "balance_before": r[1], "balance_after": r[2],
                                          "ledger_credits": r[3], "difference": r[4], "result": "MATCH" if abs(r[4]) < 0.01 else "DIFFERENCE"} if r else None
        else: rep["last_reconciliation"] = None
        if rep["last_reconciliation"] is None: rep["warnings"].append("no ledger reconciliation recorded: run finance/cost_report.py with --balance-before and --balance-after")
        elif rep["last_reconciliation"]["result"] != "MATCH": rep["warnings"].append("the last reconciliation found a difference between the ledger and the account")
        rep["recent_alerts"] = [{"when": datetime.fromtimestamp(t).isoformat(timespec="seconds"), "run_id": rid, "kind": k, "message": m}
                                for t, rid, k, m in db.execute("SELECT ts, run_id, kind, message FROM alerts ORDER BY ts DESC LIMIT 5")] if "alerts" in tables else []
    finally:
        db.close()
    return rep

def render(rep):
    L = [f"clearance doctor: {'OK' if rep['ok'] else 'PROBLEMS FOUND'}  ({rep['db']})"]
    L += [f"  problem: {p}" for p in rep["problems"]]
    L += [f"  key {k}: {v}" for k, v in rep["keys"].items()]
    if "integrity" in rep: L.append(f"  database integrity: {rep['integrity']}")
    if "runs" in rep:
        L.append(f"  runs: {rep['runs'] or 'none'}; actions: {rep['actions'] or 'none'}; audit log: {rep['audit_log']}")
        for ep, h in rep["headroom"].items(): L.append(f"  rate limit {ep}: {h['last_60s']} in the last 60 s of {h['limit']} (free {h['free']})")
        b = rep["budget"]; L.append(f"  budget: {b['spent_today']:g} credits today of a daily cap of {b['daily_cap']} (left {b['left']})")
        r = rep["last_reconciliation"]
        L.append("  last reconciliation: " + (f"{r['when']}: ledger {r['ledger_credits']:g}, account {r['balance_before'] - r['balance_after']:g}, {r['result']}" if r else "none recorded"))
        for al in rep["recent_alerts"]: L.append(f"  alert {al['when']} [{al['kind']}] {al['run_id']}: {al['message']}")
    L += [f"  warning: {w}" for w in rep["warnings"]]
    return "\n".join(L)
