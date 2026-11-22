"""Cost report from the ledger databases (the `calls` table every external call writes through core.cached_call).

    python finance/cost_report.py [DB ...] [--since ISO_OR_EPOCH] [--names] [--json]
                                  [--balance-before N --balance-after N] [--economics]

Prints, per vendor run: credits and seconds by endpoint; model calls (tokens; cost if a price is set in
finance/assumptions.json, otherwise "free tier"); mean, median and p90 credits per vendor; cache savings on reruns
(from the cache_hits table the clearance guard writes); credits spent by runs stopped at a cap.
With both balances it reconciles the ledger total against the account's balance change and records the result in the
first database (table reconciliations, read by `python -m clearance doctor`).
--economics adds the unit-economics tables (finance/UNIT_ECONOMICS.md); any input still "TODO" shows as ASSUMPTION - TODO.
Vendor names are hidden unless --names is given (a vendor name can be a proprietor's own name).
No figure is invented: everything comes from the ledger rows read or from finance/assumptions.json.
"""
import argparse, json, math, sqlite3, statistics, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSUMPTIONS = ROOT / "finance" / "assumptions.json"
LLM_ENDPOINT = "/llm/generate"
TODO = "ASSUMPTION - TODO"
FINISHED = ("done", "held", "stopped_at_cap")
RECON = "CREATE TABLE IF NOT EXISTS reconciliations(ts REAL, balance_before REAL, balance_after REAL, ledger_credits REAL, difference REAL, dbs TEXT)"

def load_assumptions(path=ASSUMPTIONS):
    a = json.loads(Path(path).read_text())
    return {k: v for k, v in a.items() if not k.startswith("_")}

def num(v): return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

def _since(v):
    if v is None: return 0.0
    try: return float(v)
    except ValueError: return datetime.fromisoformat(v).timestamp()

def read_ledger(paths, since=None):
    """Returns (runs, calls): runs {key: {...}}, calls [rows]. key = db path + run id, so the same run id in two files stays apart."""
    t0, runs, calls, hits = _since(since), {}, [], []
    for p in paths:
        db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "calls" not in tables: db.close(); continue
        for rid, req, st in (db.execute("SELECT id, request, status FROM runs") if "runs" in tables else []):
            try: r = json.loads(req) if req and req.startswith("{") else {}
            except ValueError: r = {}
            runs[(p, rid)] = {"db": p, "run_id": rid, "status": st or "", "vendor": r.get("vendor_name"), "is_vendor": bool(r.get("vendor_name")),
                              "recheck_of": r.get("recheck_of")}
        for rid, ep, params, st, cr, ms, ts in db.execute("SELECT run_id, endpoint, params, status, credits, ms, ts FROM calls WHERE ts>=?", (t0,)):
            calls.append({"key": (p, rid), "endpoint": ep, "params": params, "status": st, "credits": cr or 0.0, "ms": ms or 0, "ts": ts})
        if "cache_hits" in tables:
            hits += [{"key": (p, rid), "endpoint": ep, "saved": s} for rid, ep, s in
                     db.execute("SELECT run_id, endpoint, credits_saved FROM cache_hits WHERE ts>=?", (t0,))]
        db.close()
    return runs, calls, hits

def p90(xs):
    s = sorted(xs)
    return s[max(0, math.ceil(0.9 * len(s)) - 1)] if s else None

def summarize(paths, since=None, assumptions=None):
    a = assumptions if assumptions is not None else load_assumptions()
    runs, calls, hits = read_ledger(paths, since)
    per = {}
    for c in calls:
        r = runs.get(c["key"]) or {"db": c["key"][0], "run_id": c["key"][1], "status": "", "vendor": None, "is_vendor": False}
        e = per.setdefault(c["key"], {**r, "credits": 0.0, "seconds": 0.0, "calls": 0, "by_endpoint": {}})
        b = e["by_endpoint"].setdefault(c["endpoint"], {"calls": 0, "credits": 0.0, "seconds": 0.0, "errors": 0})
        b["calls"] += 1; b["credits"] += c["credits"]; b["seconds"] += c["ms"] / 1000; b["errors"] += c["status"] != "ok"
        e["calls"] += 1; e["credits"] += c["credits"]; e["seconds"] += c["ms"] / 1000
    vendor = [v for v in per.values() if v["is_vendor"]]
    finished = [v for v in vendor if v["status"] in FINISHED or v["status"].startswith("duplicate_of")]
    vc = [v["credits"] for v in finished]
    llm = [c for c in calls if c["endpoint"] == LLM_ENDPOINT]
    tin = tout = 0
    for c in llm:
        try: pr = json.loads(c["params"] or "{}")
        except ValueError: pr = {}
        tin += pr.get("tokens_in") or 0; tout += pr.get("tokens_out") or 0
    pin, pout = num(a.get("gemini_inr_per_1m_input_tokens")), num(a.get("gemini_inr_per_1m_output_tokens"))
    llm_cost = round(tin / 1e6 * pin + tout / 1e6 * pout, 4) if pin is not None and pout is not None else "free tier (no price in finance/assumptions.json)"
    capped = [v for v in per.values() if v["status"] == "stopped_at_cap"]
    saved_known = [h["saved"] for h in hits if h["saved"] is not None]
    max_call = max((c["credits"] for c in calls if (runs.get(c["key"]) or {}).get("is_vendor")), default=None)   # pipeline calls only
    return {
        "databases": list(paths), "since": since, "total_calls": len(calls), "total_credits": round(sum(c["credits"] for c in calls), 4),
        "vendor_runs": sorted(vendor, key=lambda v: (v["db"], v["run_id"])),
        "non_vendor_credits": round(sum(v["credits"] for v in per.values() if not v["is_vendor"]), 4),
        "non_vendor_runs": sum(1 for v in per.values() if not v["is_vendor"]),
        "unfinished_vendor_runs": len(vendor) - len(finished),
        "per_vendor": {"n": len(vc), "mean": round(statistics.mean(vc), 4) if vc else None, "median": round(statistics.median(vc), 4) if vc else None,
                       "p90": round(p90(vc), 4) if vc else None, "min": min(vc) if vc else None, "max": max(vc) if vc else None,
                       "mean_seconds": round(statistics.mean(v["seconds"] for v in finished), 2) if finished else None},
        "max_single_call_credits": max_call,
        "model_calls": {"n": len(llm), "tokens_in": tin, "tokens_out": tout, "cost_inr": llm_cost},
        "cache": {"hits_logged": len(hits), "credits_saved": round(sum(saved_known), 4), "hits_with_unknown_cost": len(hits) - len(saved_known),
                  "note": None if hits else "no cache_hits table rows: cache hits are only logged for runs made through the clearance guard"},
        "cap_stopped": {"runs": len(capped), "credits": round(sum(v["credits"] for v in capped), 4)},
        "error_calls": {"n": sum(1 for c in calls if c["status"] != "ok"), "credits": round(sum(c["credits"] for c in calls if c["status"] != "ok"), 4)},
    }

def reconcile(summary, before, after):
    spent = round(before - after, 4)
    diff = round(spent - summary["total_credits"], 4)
    return {"balance_before": before, "balance_after": after, "account_spent": spent, "ledger_credits": summary["total_credits"],
            "difference": diff, "result": "MATCH" if abs(diff) < 0.01 else f"DIFFERENCE of {diff:g} credits (account minus ledger)"}

def record_reconciliation(path, rec, dbs):
    db = sqlite3.connect(path, isolation_level=None); db.execute(RECON)
    db.execute("INSERT INTO reconciliations VALUES(?,?,?,?,?,?)", (time.time(), rec["balance_before"], rec["balance_after"],
                                                                    rec["ledger_credits"], rec["difference"], json.dumps(dbs)))
    db.close()

def _r(x, nd=2):
    if isinstance(x, str): return x
    return TODO if x is None else f"{x:,.{nd}f}"

def economics(s, a):
    """Unit economics from the ledger summary and assumptions. Returns rows of (label, value) and tables."""
    cap = None
    try:
        sys.path.insert(0, str(ROOT)); import core
        cap = core.CONFIG.get("max_cost_credits_per_run")
    except Exception: pass
    rate, analyst, price = num(a.get("inr_per_credit")), num(a.get("analyst_cost_inr_per_check")), num(a.get("price_inr_per_check"))
    review, fixed = num(a.get("analyst_review_cost_inr_per_check_with_service")), num(a.get("fixed_cost_inr_per_month"))
    mean = s["per_vendor"]["mean"]; maxc = s["max_single_call_credits"]
    inr = lambda cr: cr * rate if (rate is not None and cr is not None) else None
    var_inr = inr(mean)
    if var_inr is not None and review is not None: var_inr += review
    out = {"per_vendor": [
        ("credits per vendor: mean / median / p90 (ledger)", f"{_r(mean)} / {_r(s['per_vendor']['median'])} / {_r(s['per_vendor']['p90'])}"),
        ("rupees per vendor at the mean (credits x inr_per_credit)", _r(inr(mean))),
        ("model cost per vendor", s["model_calls"]["cost_inr"] if isinstance(s["model_calls"]["cost_inr"], str) else _r(s["model_calls"]["cost_inr"])),
        ("analyst cost per check today (assumption)", _r(analyst)),
        ("analyst review cost per check with the service (assumption)", _r(review)),
        ("proposed price per check (assumption)", _r(price)),
        ("gross margin per check: price - credits cost - review", _r(price - var_inr if price is not None and var_inr is not None else None)),
        ("worst case credits per vendor: per-run cap + largest single call in a vendor run (ledger)", _r(cap + maxc if cap is not None and maxc is not None else None)),
        ("worst case rupees per vendor", _r(inr(cap + maxc) if cap is not None and maxc is not None else None)),
    ], "volumes": [], "sensitivity": [], "break_even": None}
    for n in a.get("volumes_per_month") or []:
        out["volumes"].append((n, _r(mean * n if mean is not None else None), _r(inr(mean * n) if mean is not None else None),
                               _r(analyst * n if analyst is not None else None),
                               _r(price * n if price is not None else None)))
    for m in a.get("credit_price_multipliers") or []:
        c = mean * rate * m if (mean is not None and rate is not None) else None
        out["sensitivity"].append((m, _r(rate * m if rate is not None else None), _r(c),
                                   _r(price - c - (review or 0) if (price is not None and c is not None and review is not None) else None)))
    if fixed is not None and price is not None and var_inr is not None:
        unit = price - var_inr
        out["break_even"] = f"{math.ceil(fixed / unit):,} vendors per month" if unit > 0 else "never (price does not cover the variable cost)"
    else: out["break_even"] = TODO + " (needs price_inr_per_check, inr_per_credit, analyst_review_cost_inr_per_check_with_service, fixed_cost_inr_per_month)"
    return out

def render(s, rec=None, eco=None, names=False):
    L = [f"Ledger databases: {', '.join(s['databases'])}" + (f" (calls since {s['since']})" if s["since"] else ""),
         f"Calls: {s['total_calls']}, credits: {s['total_credits']:g} (vendor runs plus {s['non_vendor_runs']} non-vendor runs costing {s['non_vendor_credits']:g})", ""]
    L.append("Per vendor run (credits / seconds by endpoint):")
    for v in s["vendor_runs"]:
        who = v["vendor"] if names else "(name hidden)"
        L.append(f"  {Path(v['db']).name}:{v['run_id']} {who} [{v['status']}] total {v['credits']:g} credits, {v['seconds']:.1f} s, {v['calls']} calls")
        for ep, b in sorted(v["by_endpoint"].items()):
            L.append(f"      {ep:<22} {b['calls']:>3} calls {b['credits']:>7g} cr {b['seconds']:>7.1f} s" + (f"  ({b['errors']} errors)" if b["errors"] else ""))
    pv = s["per_vendor"]
    L += ["", f"Finished vendor runs: {pv['n']} (plus {s['unfinished_vendor_runs']} still running or killed, not in the statistics). Credits per vendor: mean {_r(pv['mean'])}, median {_r(pv['median'])}, p90 {_r(pv['p90'])}, "
              f"min {_r(pv['min'])}, max {_r(pv['max'])}. Mean seconds in calls: {_r(pv['mean_seconds'])}",
          f"Largest single call in a vendor run: {_r(s['max_single_call_credits'])} credits",
          f"Model calls ({LLM_ENDPOINT}): {s['model_calls']['n']}, tokens in {s['model_calls']['tokens_in']}, out {s['model_calls']['tokens_out']}, "
          f"cost: {s['model_calls']['cost_inr']}",
          f"Cache savings on reruns: {s['cache']['hits_logged']} hits logged, {s['cache']['credits_saved']:g} credits saved"
          + (f", {s['cache']['hits_with_unknown_cost']} hits with unknown cost" if s['cache']['hits_with_unknown_cost'] else "")
          + (f" ({s['cache']['note']})" if s['cache']['note'] else ""),
          f"Runs stopped at a cap: {s['cap_stopped']['runs']}, credits spent by them: {s['cap_stopped']['credits']:g}",
          f"Calls that ended in an error: {s['error_calls']['n']}, credits on them: {s['error_calls']['credits']:g}"]
    if rec:
        L += ["", "Reconciliation:", f"  balance before {rec['balance_before']:g}, after {rec['balance_after']:g}: account spent {rec['account_spent']:g}",
              f"  ledger says {rec['ledger_credits']:g}: {rec['result']}"]
    if eco:
        L += ["", "Unit economics (finance/assumptions.json; TODO inputs show as ASSUMPTION - TODO):"]
        L += [f"  {k}: {v}" for k, v in eco["per_vendor"]]
        L += ["", "  vendors/month | credits | rupees (credits) | analyst cost today | revenue at price"]
        L += [f"  {n:>13,} | {c} | {r} | {an} | {rev}" for n, c, r, an, rev in eco["volumes"]]
        L += ["", "  credit price x | rupees per credit | rupees per vendor (mean) | margin per check"]
        L += [f"  {m:>14g} | {r} | {c} | {mg}" for m, r, c, mg in eco["sensitivity"]]
        L += ["", f"  break-even volume: {eco['break_even']}"]
    return "\n".join(L)

def main(argv=None):
    ap = argparse.ArgumentParser(prog="cost_report.py", description=__doc__.split("\n")[0])
    ap.add_argument("dbs", nargs="*", default=["clearance.db"])
    ap.add_argument("--since"); ap.add_argument("--names", action="store_true"); ap.add_argument("--json", action="store_true")
    ap.add_argument("--balance-before", type=float); ap.add_argument("--balance-after", type=float)
    ap.add_argument("--economics", action="store_true"); ap.add_argument("--no-record", action="store_true")
    a = ap.parse_args(argv)
    dbs = [p for p in a.dbs if Path(p).exists()]
    if not dbs: print("no ledger database found: " + ", ".join(a.dbs), file=sys.stderr); return 2
    if (a.balance_before is None) != (a.balance_after is None): ap.error("give both --balance-before and --balance-after")
    assumptions = load_assumptions()
    s = summarize(dbs, a.since, assumptions)
    rec = reconcile(s, a.balance_before, a.balance_after) if a.balance_before is not None else None
    if rec and not a.no_record: record_reconciliation(dbs[0], rec, dbs)
    eco = economics(s, assumptions) if a.economics else None
    if a.json:
        if not a.names:
            for v in s["vendor_runs"]: v["vendor"] = None
        print(json.dumps({"summary": s, "reconciliation": rec, "economics": eco}, indent=1, default=str))
    else: print(render(s, rec, eco, names=a.names))
    return 0

if __name__ == "__main__": raise SystemExit(main())
