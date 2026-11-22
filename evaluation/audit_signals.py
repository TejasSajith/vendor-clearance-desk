"""Offline, free audit: raw probe values -> signals -> policy results, with mismatch flags. No API calls, no person names.
The check modules are not built yet, so the signals come from evaluation/build_real_cases.py (same code the fixtures use).
The raw values are recomputed here independently, then compared with the signals.
    python evaluation/audit_signals.py                 # prints and writes probe/audit_signals.txt (gitignored)"""
import json, sys
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "evaluation"))
import build_real_cases as b, policy, decision

def raw_trend(ts, as_of_days=b.TREND_DAYS):
    """Independent recompute: newest point vs the newest point that is at least `as_of_days` older."""
    pts = sorted((date.fromisoformat(p["date"]), p["employee_count"]) for p in ts if p.get("employee_count"))
    if len(pts) < 2: return None
    last_d, last_v = pts[-1]
    base = None
    for d, v in pts:                       # ascending: the last one that qualifies wins
        if (last_d - d).days >= as_of_days: base = v
    return None if not base else round((last_v - base) / base * 100, 1)

def mismatches(raw, sig):
    """raw: dict of independently read values; sig: the signals dict. Returns a list of human-readable flags."""
    out = []
    def chk(name, a, b_):
        if a != b_: out.append(f"MISMATCH {name}: raw-derived {a!r} vs signal {b_!r}")
    ts = raw["timeseries"]
    chk("headcount_total", raw["headcount_total"], sig["profile"]["headcount_total"])
    chk("headcount_trend_pct", raw_trend(ts), sig["profile"]["headcount_trend_pct"])
    age = (b.AS_OF - date.fromisoformat(ts[-1]["date"])).days if ts else None
    chk("series_age_days", age, sig["profile"]["series_age_days"])
    chk("jobs_90d", raw["jobs_90d"], sig["profile"]["jobs_90d"])
    chk("traffic_present", raw["traffic_present"], sig["profile"]["traffic_present"])
    chk("status", raw["status"], sig["identify"]["status"])
    chk("top_ties", raw["top_ties"], sig["identify"]["top_ties"])
    if sig["identify"]["domain_match"] is True and raw["domain_n"] == 0: out.append("MISMATCH domain_match True but no domain candidates")
    if raw["domain_n"] == 0 and raw["primary_domain"] and sig["identify"]["domain_match"] is not None:
        out.append("NOTE domain given but no identify-by-domain result")
    if ts and age is not None and age > 60: out.append(f"NOTE newest headcount point is {age} days old (policy max 60)")
    return out

def read_raw(case_id_num, raw_dir):
    load = lambda n: json.loads((raw_dir / n).read_text()) if (raw_dir / n).exists() else None
    cd = load(f"step2_enrich_{case_id_num}.json")[0]["matches"][0]["company_data"]
    ts = (cd.get("headcount") or {}).get("timeseries") or []
    ident = load(f"step2_identify_name_{case_id_num}.json")[0]["matches"]
    dom = load(f"step2_identify_domain_{case_id_num}.json")
    jobs = load(f"step3_jobs90_{case_id_num}.json") or {}
    wt = (cd.get("web_traffic") or {}).get("domain_traffic") or {}
    top = ident[0]["confidence_score"] if ident else None
    return {"headcount_total": (cd.get("headcount") or {}).get("total"), "timeseries": ts,
            "status": (cd.get("basic_info") or {}).get("status"), "primary_domain": (cd.get("basic_info") or {}).get("primary_domain"),
            "n_candidates": len(ident), "top_ties": sum(1 for m in ident if m["confidence_score"] == top),
            "domain_n": len(dom[0]["matches"]) if dom else 0, "jobs_90d": jobs.get("total_count"),
            "traffic_present": any(v.get("monthly_visitors") for v in wt.values())}

def block(case, raw):
    s, ts = case["signals"], raw["timeseries"]
    first, last = (ts[0], ts[-1]) if ts else (None, None)
    L = [f"=== {case['id']} (crustdata id {case['crustdata_company_id']})",
         "RAW   headcount.total=%s  timeseries n=%d first=%s last=%s" % (raw["headcount_total"], len(ts), first and (first["date"], first["employee_count"]), last and (last["date"], last["employee_count"])),
         "RAW   status=%s  primary_domain=%s  identify candidates=%d, tied at top score=%d  domain-identify matches=%d" % (raw["status"], "present" if raw["primary_domain"] else "EMPTY", raw["n_candidates"], raw["top_ties"], raw["domain_n"]),
         "RAW   jobs last 90d (total_count)=%s  web_traffic has visitors=%s" % (raw["jobs_90d"], raw["traffic_present"]),
         "SIG   identify=%s" % {k: v for k, v in s["identify"].items() if k != "sources"},
         "SIG   profile=%s" % {k: v for k, v in s["profile"].items() if k != "sources"},
         "SIG   director=%s" % {k: v for k, v in s["director"].items() if k != "sources"},
         "SIG   adverse=state %s, searches_run %s, hits %d (severity>=2: %d)" % (s["adverse"]["state"], s["adverse"]["searches_run"], len(s["adverse"]["hits"]), sum(1 for h in s["adverse"]["hits"] if h["severity"] >= 2))]
    for tier in ("low", "high"):
        ch = policy.evaluate(s, policy.PROPOSED_PARAMS, tier)
        v = decision.decide(ch).verdict
        L.append("POLICY tier=%-4s %s -> %s" % (tier, "  ".join(f"{k}={c['status']}" for k, c in ch.items()), v))
    flags = mismatches(raw, s)
    L += ["FLAG  " + f for f in flags] or ["FLAG  none"]
    return L, flags

def main():
    raw_dir = ROOT / "probe" / "raw"; lines = []; total = 0
    for case in b.build():
        L, f = block(case, read_raw(case["crustdata_company_id"], raw_dir)); lines += L + [""]; total += sum(1 for x in f if x.startswith("MISMATCH"))
    lines.append(f"TOTAL MISMATCHES: {total}")
    text = "\n".join(lines); print(text)
    (ROOT / "probe" / "audit_signals.txt").write_text(text + "\n")

if __name__ == "__main__": main()
