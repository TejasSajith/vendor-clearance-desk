"""Fairness report: verdict and check-state rates by firm-size band (headcount), from stored runs and the tuning cases.

    python scripts/fairness_report.py [DB ...] [--min-cases N] [--markdown]

Sources of cases:
  stored runs   vendor runs in the given ledger databases: the saved final result (verdict and checks) and the saved profile step
  tuning cases  evaluation/cases_real.json (probe cases with full signals) and evaluation/signals_real.json + cases_real.csv
                (collected signals, re-scored with the current policy; no director is requested there, so their verdict is never CLEARED)
Bands are PROPOSED in ops_config.json size_bands (D54). A band with fewer than --min-cases cases gets no rate statement
(default: ops_config fairness_min_cases_per_band, PROPOSED D54). Firm age is not in any stored signal, so new firms cannot
be separated from small ones; the 'small_real' and 'invented' strata in cases_real.csv are the nearest proxy.
No vendor names are printed.
"""
import argparse, collections, json, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "evaluation"))
import decision, policy
from clearance import ops

CHECKS = ("exists", "active", "director_match", "adverse_media")
VERDICTS = (decision.CLEARED, decision.REJECTED, decision.CANNOT_VERIFY, decision.HOLD)

def band(headcount, bands=None):
    for b in bands or ops.OPS["size_bands"]:
        if b["min"] is None and b["max"] is None:
            if headcount is None: return b["label"]
            continue
        if headcount is None: continue
        if (b["min"] is None or headcount >= b["min"]) and (b["max"] is None or headcount <= b["max"]): return b["label"]
    return "no headcount data" if headcount is None else "other"

def from_db(path):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True); out = []
    try:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"runs", "steps"} <= tables: return out
        for rid, req in db.execute("SELECT id, request FROM runs"):
            try: r = json.loads(req or "{}")
            except ValueError: continue
            if not isinstance(r, dict) or not r.get("vendor_name"): continue
            fin = db.execute("SELECT result FROM steps WHERE run_id=? AND name='final'", (rid,)).fetchone()
            if not fin: continue
            f = json.loads(fin[0]); prof = db.execute("SELECT result FROM steps WHERE run_id=? AND name='profile'", (rid,)).fetchone()
            hc = (json.loads(prof[0]) or {}).get("headcount_total") if prof else None
            out.append({"origin": f"run:{Path(path).name}", "stratum": None, "headcount": hc, "verdict": f.get("verdict"),
                        "states": {c: (f.get("checks") or {}).get(c, {}).get("status") for c in CHECKS}})
    finally: db.close()
    return out

def from_probe_cases(path=ROOT / "evaluation" / "cases_real.json"):
    out = []
    if not Path(path).exists(): return out
    for c in json.loads(Path(path).read_text()):
        checks = policy.evaluate(c["signals"], policy.PROPOSED_PARAMS, c.get("risk_tier", "low"))
        out.append({"origin": "case:cases_real.json", "stratum": None, "headcount": (c["signals"].get("profile") or {}).get("headcount_total"),
                    "verdict": decision.decide(checks).verdict, "states": {k: checks[k]["status"] for k in CHECKS}})
    return out

def from_tuning():
    try: import tuning
    except Exception: return []
    out = []
    for r in tuning.collected(tuning.load_cases()):
        e = tuning.engine(r, policy.PROPOSED_PARAMS)
        checks = {c: {"status": st, "reason": why, "sources": []} for c, (st, why) in e.items()}
        checks["director_match"] = {"status": "unknown", "reason": "not requested in tuning cases", "sources": []}
        prof = r["sig"].get("profile") or {}
        out.append({"origin": "case:signals_real.json", "stratum": r["stratum"], "headcount": prof.get("headcount_total"),
                    "verdict": decision.decide(checks).verdict, "states": {c: checks[c]["status"] for c in CHECKS}})
    return out

def tally(cases, key):
    groups = collections.OrderedDict()
    for c in cases: groups.setdefault(key(c), []).append(c)
    rows = {}
    for g, cs in groups.items():
        rows[g] = {"n": len(cs), "verdicts": collections.Counter(c["verdict"] for c in cs),
                   "states": {k: collections.Counter(c["states"].get(k) for c in cs) for k in CHECKS}}
    return rows

def _pct(n, d): return f"{n} ({100 * n / d:.0f}%)" if d else "0"

def statement(by_band, min_cases):
    """Plain statement. The first paragraph is what the rules do; everything after it is read off the counts above."""
    enough = {b: r for b, r in by_band.items() if r["n"] >= min_cases}
    rejected = sum(r["verdicts"][decision.REJECTED] for r in by_band.values())
    lines = ["What the rules do (policy.py): missing data is never a fail. A firm with no record, no headcount, no jobs or no web traffic "
             "gets 'unknown' (CANNOT_VERIFY), never REJECTED, and a rejection needs a dated, sourced, severe report. The activity check needs "
             f"{policy.PROPOSED_PARAMS['active_min_signals']} of headcount, jobs and traffic, which small firms are less likely to have, so by design "
             "a small genuine firm is more likely to end in CANNOT_VERIFY than to be cleared; it is not rejected for being small.",
             f"What the data shows: {rejected} REJECTED verdict(s) in {sum(r['n'] for r in by_band.values())} cases."]
    if len(enough) < 2:
        lines.append(f"The data is too small to compare bands: only {len(enough)} band(s) have at least {min_cases} cases "
                     f"({', '.join(f'{b}: {r['n']}' for b, r in by_band.items())}). No conclusion is drawn.")
        return lines
    tops = {b: r["verdicts"].most_common(1)[0] for b, r in enough.items()}
    if len({v for v, _ in tops.values()}) == 1 and all(n == enough[b]["n"] for b, (v, n) in tops.items()):
        v = next(iter(tops.values()))[0]
        lines.append(f"Verdicts do not differ between bands: every case in every band with at least {min_cases} cases ended {v}. "
                     "So this data cannot show whether small firms are cleared less often; nothing was cleared in any band.")
    else:
        lines.append("Verdict rates in bands with enough cases: " + "; ".join(
            f"{b}: " + ", ".join(f"{v} {_pct(r['verdicts'][v], r['n'])}" for v in VERDICTS if r["verdicts"][v]) for b, r in enough.items()) + ".")
    au = {b: r["states"]["active"]["unknown"] / r["n"] for b, r in enough.items()}
    hi, lo = max(au, key=au.get), min(au, key=au.get)
    if au[hi] > au[lo]:
        lines.append(f"Where the bands do differ is the activity check: 'unknown' in {au[hi]:.0%} of {hi} cases against {au[lo]:.0%} of {lo} cases. "
                     "That is the gap a small firm meets, and it is filled by a person collecting evidence, not by a rejection.")
    small = [b for b in by_band if b not in enough]
    if small: lines.append("Too few cases for a rate statement: " + ", ".join(f"{b} ({by_band[b]['n']})" for b in small) + ".")
    lines.append("Firm age is not in any stored signal, so new firms cannot be told apart from small ones here.")
    return lines

def render(cases, min_cases, md=False):
    order = [b["label"] for b in ops.OPS["size_bands"]]
    by_band = dict(sorted(tally(cases, lambda c: band(c["headcount"])).items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99))
    by_stratum = tally([c for c in cases if c["stratum"]], lambda c: c["stratum"])
    L = [f"# Fairness report" if md else "Fairness report", "",
         f"Cases: {len(cases)} ({', '.join(f'{k}: {v}' for k, v in collections.Counter(c['origin'] for c in cases).items())}). "
         f"Rates are shown with counts; bands with fewer than {min_cases} cases get no rate statement. "
         "The same vendor can appear in more than one source (a stored run and the tuning row collected from it), so the counts are not independent.", ""]
    def table(title, rows):
        out = [f"## {title}" if md else title, "",
               "| group | n | " + " | ".join(VERDICTS) + " | active unknown | exists unknown | adverse pass |", "|---" * (len(VERDICTS) + 5) + "|"]
        for g, r in rows.items():
            out.append(f"| {g} | {r['n']} | " + " | ".join(_pct(r["verdicts"][v], r["n"]) for v in VERDICTS)
                       + f" | {_pct(r['states']['active']['unknown'], r['n'])} | {_pct(r['states']['exists']['unknown'], r['n'])}"
                       f" | {_pct(r['states']['adverse_media']['pass'], r['n'])} |")
        return out + [""]
    L += table("By firm-size band (headcount)", by_band)
    if by_stratum: L += table("By stratum (tuning cases, cases_real.csv)", by_stratum)
    L += [("## Statement" if md else "Statement"), ""] + statement(by_band, min_cases)
    return "\n".join(L)

def main(argv=None):
    ap = argparse.ArgumentParser(prog="fairness_report.py")
    ap.add_argument("dbs", nargs="*"); ap.add_argument("--min-cases", type=int, default=ops.OPS.get("fairness_min_cases_per_band", 10))
    ap.add_argument("--markdown", action="store_true"); ap.add_argument("--no-tuning", action="store_true")
    a = ap.parse_args(argv)
    cases = [c for p in a.dbs if Path(p).exists() for c in from_db(p)]
    if not a.no_tuning: cases += from_probe_cases() + from_tuning()
    print(render(cases, a.min_cases, md=a.markdown))
    return 0

if __name__ == "__main__": raise SystemExit(main())
