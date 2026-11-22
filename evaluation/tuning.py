"""Phases 3 to 6, offline (0 credits): score the engine against the owner's labels, sweep parameters with repeated stratified splits and
5-fold cross-validation, measure the suspicious band and search noise, and write candidate presets. It never writes policy.py or
config.json and never writes labels. No person names: cases are referred to by case_id and stratum.
    python evaluation/tuning.py all          # needs >= 25 fully labelled rows in cases_real.csv
Labels per check: pass | fail | unknown (blank = not labelled). Loss weights: wrong 3, abstain 1, hold-vs-cannot-verify 0.5 (run_eval.WEIGHTS)."""
import csv, json, random, statistics, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "evaluation"))
import policy, pipeline, run_eval
from checks import adverse, crosschecks

CHECKS = ("exists", "active", "adverse_media")
LABEL_COL = {"exists": "expected_exists", "active": "expected_active", "adverse_media": "expected_adverse"}
VERDICT = {"pass": "CLEARED", "fail": "REJECTED", "unknown": "CANNOT_VERIFY", "unreachable": "HOLD_FOR_APPROVAL", "not_run": "CANNOT_VERIFY"}
LOSSES = {"false_pass": 5.0, "false_fail": 3.0, "abstain": 1.0, "hold_vs_cnv": 0.5}      # PROPOSED; parameters of this harness (--losses overrides)
W = run_eval.WEIGHTS                                                                       # kept for run_eval users; scoring below uses LOSSES
D = {**policy.PROPOSED_PARAMS, **adverse.RULE_PARAMS, **crosschecks.CROSS_PARAMS}                                     # policy defaults plus the PROPOSED source-class rules
ESTABLISHED_STRATA = ("large_legit", "big_brand_noise")
BAD_STRATA = ("shut_down", "invented")
GRID = {"candidate_name_sim_floor": [0.70, 0.75, 0.80, 0.85, 0.90, 0.95], "min_headcount": [1, 3, 5, 10, 20], "max_decline_pct": [10, 20, 30, 40, 60],
        "max_series_age_days": [30, 45, 60, 90, 120, 180], "min_jobs_90d": [1, 2, 3, 5], "active_min_signals": [1, 2, 3], "min_searches": [1, 2, 3, 4, 5],
        "adverse_min_severity": [1, 2, 3], "reject_min_severity": [1, 2, 3], "reject_min_sources": [1, 2, 3],
        "established_headcount_min": [100, 250, 500, 1000, 5000, 10 ** 9], "rule_source_classes": [False, True], "rule_name_collision": [False, True],
        "adverse_pass_needs_exists": [False, True], "adverse_pass_needs_active": [False, True], "adverse_min_results_scanned": [0, 5, 10, 20]}

# ---------- loading ----------
def valid(x): return (x or "").strip().lower() in ("pass", "fail", "unknown")

def load_cases(csv_path=ROOT / "evaluation" / "cases_real.csv", signals_path=ROOT / "evaluation" / "signals_real.json", labels_path=None):
    """labels_path: an optional PROVISIONAL label file (evaluation/labels_agent.csv). The owner's labels in cases_real.csv always win; the file only fills blanks."""
    sig = json.loads(Path(signals_path).read_text())["rows"] if Path(signals_path).exists() else {}
    extra = {r["case_id"]: r for r in csv.DictReader(open(labels_path))} if labels_path else {}
    rows = []
    for r in csv.DictReader(open(csv_path)):
        s = sig.get(r["case_id"])
        e = extra.get(r["case_id"], {})
        pick = lambda c: r[LABEL_COL[c]] if valid(r[LABEL_COL[c]]) else e.get(LABEL_COL[c], "")
        labels = {c: pick(c).strip().lower() if valid(pick(c)) else None for c in CHECKS}
        rows.append({"case_id": r["case_id"], "name": r["vendor_name"], "stratum": r["stratum"], "split": r["split"], "labels": labels, "sig": s})
    return rows

def labelled(rows): return [r for r in rows if r["sig"] and all(r["labels"].values())]
def collected(rows): return [r for r in rows if r["sig"]]

# ---------- engine on stored signals ----------
def engine(row, params):
    """Per-check engine status and reason for a collected row under `params`. Mirrors pipeline.run_request on the stored signals."""
    s = row["sig"]
    if s["state"] == "unreachable": return {c: ("unreachable", "source unreachable") for c in CHECKS}
    if s["state"] == "stopped_at_cap": return {c: ("not_run", "cap") for c in CHECKS}
    ident = {"candidates": s["identify"]["candidates"], "domain_candidate_ids": s["identify"]["domain_candidate_ids"], "status": (s.get("profile") or {}).get("status")}
    sig = {"identify": pipeline.identify_signals("", s["input_domain"] or "", ident, params), "director": {"not_requested": True, "sources": []}}
    if sig["identify"].get("company_id") is not None and s.get("profile"): sig["profile"] = s["profile"]
    if sig["identify"].get("company_id") is not None and (s.get("profile") or {}).get("status"): sig["identify"]["status"] = s["profile"]["status"]
    a = s["adverse"] or {"state": "searched", "searches_run": 0, "hits": [], "sources": []}
    if a.get("per_search") and "results" in a["per_search"][0]:                      # features in, policy signals out: the rules run here, under `params`
        a = adverse.derive_signals(a["per_search"], row.get("name", ""), params, (s.get("profile") or {}).get("headcount_total"))
    sig["adverse"] = a
    checks = crosschecks.apply(policy.evaluate(sig, params, "low"), a, params)
    return {c: (checks[c]["status"], checks[c]["reason"]) for c in CHECKS}

def check_loss(label, status, losses=None):
    """false_pass 5: the engine says pass but the label is not pass. false_fail 3: it says fail but the label is not fail. abstain 1: unknown (or not run)
    where the label is a definite answer. hold_vs_cnv 0.5: a hold where the label is unknown (an unreachable source is never a definite answer)."""
    L = losses or LOSSES
    if status == label: return 0.0
    if status == "pass": return L["false_pass"]
    if status == "fail": return L["false_fail"]
    if status in ("unknown", "not_run"): return L["abstain"] if label in ("pass", "fail") else 0.0
    return L["abstain"] if label in ("pass", "fail") else L["hold_vs_cnv"]          # unreachable

def row_loss(row, params, losses=None):
    e = engine(row, params); return sum(check_loss(row["labels"][c], e[c][0], losses) for c in CHECKS)

# ---------- splits ----------
def stratified_split(rows, seed, frac=2 / 3):
    rnd = random.Random(seed); train, test = [], []
    by = {}
    for r in rows: by.setdefault(r["stratum"], []).append(r)
    for s in sorted(by):
        rs = sorted(by[s], key=lambda r: r["case_id"]); rnd.shuffle(rs)
        k = max(1, round(len(rs) * frac)) if len(rs) > 1 else len(rs)
        train += rs[:k]; test += rs[k:]
    return train, test

def stratified_folds(rows, k=5, seed=99):
    rnd = random.Random(seed); folds = [[] for _ in range(k)]; by = {}
    for r in rows: by.setdefault(r["stratum"], []).append(r)
    i = 0
    for s in sorted(by):
        rs = sorted(by[s], key=lambda r: r["case_id"]); rnd.shuffle(rs)
        for r in rs: folds[i % k].append(r); i += 1
    return [([r for j, f in enumerate(folds) if j != i for r in f], folds[i]) for i in range(k)]

def all_splits(rows, repeats=20, k=5): return [stratified_split(rows, seed) for seed in range(repeats)] + stratified_folds(rows, k)

# ---------- sweep ----------
def mean(xs): return sum(xs) / len(xs) if xs else 0.0
def sd(xs): return statistics.pstdev(xs) if len(xs) > 1 else 0.0

def classify(vals, means, tol_rel=0.05, tol_abs=0.02):
    """plateau: >= 3 adjacent values within tolerance of the best (2 for grids of 3); inert: all values within tolerance;
    edge: best at the end of the grid, still improving; narrow: 2 adjacent values on a long grid; spike: an isolated interior best (OVERFIT)."""
    best = min(means); tol = max(tol_rel * best, tol_abs); i = means.index(best)
    within = [m <= best + tol for m in means]
    if all(within): return "inert"
    lo = hi = i
    while lo > 0 and within[lo - 1]: lo -= 1
    while hi < len(means) - 1 and within[hi + 1]: hi += 1
    run = hi - lo + 1
    if run >= 3 or (len(vals) <= 3 and run >= 2): return "plateau"
    if i in (0, len(vals) - 1): return "edge"
    return "narrow" if run == 2 else "spike"

def sweep(rows, grid=GRID, defaults=D, splits=None):
    """One-at-a-time sweep on the labelled rows. Test loss per split is the mean row loss on the held-out part."""
    rows = labelled(rows); splits = splits or all_splits(rows); out = {}
    for p, vals in grid.items():
        loss = {v: {r["case_id"]: row_loss(r, {**defaults, p: v}) for r in rows} for v in vals}
        test = {v: [mean([loss[v][r["case_id"]] for r in te]) for _, te in splits if te] for v in vals}
        chosen, chosen_test, default_test = [], [], []
        for tr, te in splits:
            if not te: continue
            tm = {v: mean([loss[v][r["case_id"]] for r in tr]) for v in vals}
            b = min(vals, key=lambda v: (tm[v], abs(v - defaults[p])))
            chosen.append(b); chosen_test.append(mean([loss[b][r["case_id"]] for r in te])); default_test.append(mean([loss[defaults[p]][r["case_id"]] for r in te])) if defaults[p] in loss else None
        means = [mean(test[v]) for v in vals]; best = vals[means.index(min(means))]
        if defaults[p] in vals and means[vals.index(defaults[p])] <= min(means) + max(0.05 * min(means), 0.02): best = defaults[p]   # a tie keeps the default
        kind = classify(vals, means)
        out[p] = {"values": vals, "mean_loss": means, "sd_loss": [sd(test[v]) for v in vals], "best": best, "kind": kind, "overfit": kind == "spike",
                  "selected_best_share": round(chosen.count(best) / len(chosen), 2) if chosen else None,
                  "chosen_test_loss": mean(chosen_test), "default_test_loss": mean(default_test) if default_test else None, "n_rows": len(rows), "n_splits": len(splits)}
    return out

def holdout_check(rows, best, defaults=D):
    """Best values chosen on the tune rows, evaluated on the holdout rows (the split column of cases_real.csv)."""
    tune = [r for r in labelled(rows) if r["split"] == "tune"]; hold = [r for r in labelled(rows) if r["split"] == "holdout"]
    chosen = dict(defaults)
    for p, vals in GRID.items():
        chosen[p] = min(vals, key=lambda v: (mean([row_loss(r, {**defaults, p: v}) for r in tune]), abs(v - defaults[p]))) if tune else defaults[p]
    f = lambda rs, par: mean([row_loss(r, par) for r in rs])
    return {"n_tune": len(tune), "n_holdout": len(hold), "chosen_on_tune": {p: v for p, v in chosen.items() if p in GRID},
            "tune_loss_default": f(tune, defaults), "tune_loss_chosen": f(tune, chosen), "holdout_loss_default": f(hold, defaults), "holdout_loss_chosen": f(hold, chosen)}

# ---------- small firms vs large, sensitivity (all collected rows, labels not needed) ----------
def nonpass_rate(rows, params):
    xs = [engine(r, params) for r in rows]; n = len(xs) * len(CHECKS)
    return sum(1 for e in xs for c in CHECKS if e[c][0] != "pass") / n if n else 0.0

def small_vs_large(rows, grid=GRID, defaults=D, margin=0.10):
    small = [r for r in collected(rows) if r["stratum"] == "small_real"]; large = [r for r in collected(rows) if r["stratum"] == "large_legit"]
    gap = lambda par: nonpass_rate(small, par) - nonpass_rate(large, par); g0 = gap(defaults); out = {}
    for p, vals in grid.items():
        out[p] = [{"value": v, "small_nonpass": round(nonpass_rate(small, {**defaults, p: v}), 3), "large_nonpass": round(nonpass_rate(large, {**defaults, p: v}), 3),
                   "gap": round(gap({**defaults, p: v}), 3), "flag": gap({**defaults, p: v}) - g0 > margin} for v in vals]
    return out, round(g0, 3)

def sensitivity(rows, grid=GRID, defaults=D, unstable_share=0.10):
    rs = [r for r in collected(rows) if r["sig"]["state"] not in ("unreachable", "stopped_at_cap")]; out = {}
    for p, vals in grid.items():
        steps = []
        ev = {v: {r["case_id"]: engine(r, {**defaults, p: v}) for r in rs} for v in vals}
        for a, b in zip(vals, vals[1:]):
            ch = {c: sum(1 for r in rs if ev[a][r["case_id"]][c][0] != ev[b][r["case_id"]][c][0]) for c in CHECKS}
            any_ch = sum(1 for r in rs if any(ev[a][r["case_id"]][c][0] != ev[b][r["case_id"]][c][0] for c in CHECKS))
            steps.append({"from": a, "to": b, "rows_changed": any_ch, "by_check": ch, "share": round(any_ch / len(rs), 3) if rs else 0})
        out[p] = {"steps": steps, "unstable": any(s["share"] >= unstable_share for s in steps), "n_rows": len(rs)}
    return out

# ---------- phase 3: scoring and wrong cases ----------
def score(rows, params=D):
    per_check = {c: {"n": 0, "loss": 0.0, "wrong": 0, "abstain": 0, "hold": 0} for c in CHECKS}; strata = {}; splits = {}; wrong = []
    for r in labelled(rows):
        e = engine(r, params)
        for c in CHECKS:
            st, why = e[c]; l = check_loss(r["labels"][c], st); pc = per_check[c]
            pc["n"] += 1; pc["loss"] += l
            is_wrong = st in ("pass", "fail") and st != r["labels"][c]
            pc["wrong"] += is_wrong; pc["abstain"] += (not is_wrong and l == LOSSES["abstain"]); pc["hold"] += (not is_wrong and l == LOSSES["hold_vs_cnv"] and st == "unreachable")
            for key, d in ((r["stratum"], strata), (r["split"], splits)): d.setdefault(key, {"n": 0, "loss": 0.0})["n"] += 1; d[key]["loss"] += l
            if is_wrong: wrong.append({"case_id": r["case_id"], "stratum": r["stratum"], "check": c, "label": r["labels"][c], "engine": st, "reason": why, "raw": raw_values(r, c, params)})
    return {"per_check": per_check, "per_stratum": strata, "per_split": splits, "wrong": wrong}

def raw_values(row, check, params):
    s = row["sig"]
    if check == "exists":
        i = pipeline.identify_signals("", s["input_domain"] or "", {"candidates": s["identify"]["candidates"], "domain_candidate_ids": s["identify"]["domain_candidate_ids"]}, params)
        sims = sorted((c["sim"] for c in s["identify"]["candidates"]), reverse=True)[:3]
        return {"input_domain_given": bool(s["input_domain"]), "candidates": len(s["identify"]["candidates"]), "top_sims": sims, "found": i["found"],
                "ambiguous": (i.get("ambiguous") or {}).get("n"), "domain_match": i["domain_match"]}
    if check == "active":
        p = s.get("profile") or {}
        return {k: p.get(k) for k in ("status", "headcount_total", "headcount_trend_pct", "series_age_days", "jobs_90d", "traffic_present")}
    a = s.get("adverse") or {}
    return {"searches_run": a.get("searches_run"), "results_scanned": a.get("results_scanned"), "hits": len(a.get("hits", [])),
            "hits_sev>=2": sum(1 for h in a.get("hits", []) if h["severity"] >= 2), "dated_hits": sum(1 for h in a.get("hits", []) if h["dated"])}

# ---------- phase 5 ----------
def concern_fires(row, params=D):
    st, why = engine(row, params)["adverse_media"]
    return st == "unknown" and "possible adverse report" in why

def suspicious_band(rows, params=D):
    done = [r for r in collected(rows) if r["sig"]["state"] == "done" and (r["sig"].get("adverse") or {}).get("searches_run", 0) > 0]
    def rate(rs): return {"n": len(rs), "fires": sum(concern_fires(r, params) for r in rs), "rate": round(sum(concern_fires(r, params) for r in rs) / len(rs), 3) if rs else None}
    lab = [r for r in done if r["labels"]["adverse_media"]]
    return {"by_label": {"legit (adverse=pass)": rate([r for r in lab if r["labels"]["adverse_media"] == "pass"]), "bad (adverse=fail)": rate([r for r in lab if r["labels"]["adverse_media"] == "fail"]),
                         "unknown": rate([r for r in lab if r["labels"]["adverse_media"] == "unknown"])},
            "by_stratum": {s: rate([r for r in done if r["stratum"] == s]) for s in sorted({r["stratum"] for r in done})}}

def jaccard(a, b): return 1.0 if not a and not b else len(a & b) / len(a | b)

def repeat_noise(signals_doc, params=D):
    """Adverse stability across run 0 (the collection) and repeats 1 and 2 of 12 rows."""
    rows = signals_doc["rows"]; rep = signals_doc.get("repeats", {}); out = []
    for cid, reps in rep.items():
        runs = [rows[cid]["adverse"]] + [reps[k] for k in ("1", "2") if k in reps]
        if len(runs) < 2 or not runs[0]: continue
        fake = [{"sig": {"state": "done", "identify": rows[cid]["identify"], "profile": rows[cid].get("profile"), "adverse": a, "input_domain": rows[cid]["input_domain"]}} for a in runs]
        st = [engine(f, params)["adverse_media"][0] for f in fake]
        ids = [{h["url_id"] for h in a["hits"]} for a in runs]
        dates = [{h["url_id"]: h.get("date_text") for h in a["hits"]} for a in runs]
        common = set.intersection(*ids) if ids else set()
        out.append({"case_id": cid, "runs": len(runs), "statuses": st, "status_flips": len(set(st)) > 1, "hit_jaccard_min": round(min(jaccard(ids[0], x) for x in ids[1:]), 3),
                    "common_hits": len(common), "date_changes": sum(1 for u in common if len({d.get(u) for d in dates}) > 1),
                    "results_scanned": [a["results_scanned"] for a in runs]})
    return out

# ---------- established pass rate, bad-vendor gate ----------
def reason_bucket(check, status, reason):
    r = (reason or "").lower()
    if status == "unreachable": return "source unreachable (held)"
    if status == "not_run": return "stopped at a cap"
    if check == "exists":
        if r.startswith("ambiguous"): return "exists: ambiguous match"
        if r.startswith("no record found"): return "exists: no record found"
        if "domain" in r: return "exists: domain belongs to another company"
        if "deleted" in r: return "exists: profile marked deleted"
        return "exists: other"
    if check == "active":
        if "only" in r and "activity signals" in r: return "active: too few activity signals"
        if "no activity data" in r: return "active: no activity data"
        if "conflict" in r: return "active: sources conflict"
        return "active: other"
    if "possible adverse report" in r: return "adverse: unconfirmed reports name the company"
    if "too few searches" in r: return "adverse: too few searches"
    return "adverse: other"

def established_pass_rate(rows, params=D):
    """Share of large_legit + big_brand_noise vendors where exists, active and adverse are all Passed, and why the others fell back."""
    rs = [r for r in collected(rows) if r["stratum"] in ESTABLISHED_STRATA]; passed, why = 0, {}
    for r in rs:
        e = engine(r, params)
        if all(e[c][0] == "pass" for c in CHECKS): passed += 1; continue
        for c in CHECKS:
            if e[c][0] != "pass": b = reason_bucket(c, e[c][0], e[c][1]); why[b] = why.get(b, 0) + 1
    return {"n": len(rs), "passed": passed, "rate": round(passed / len(rs), 3) if rs else None, "fell_back": len(rs) - passed, "why": dict(sorted(why.items(), key=lambda kv: -kv[1]))}

def is_bad(row): return row["stratum"] in BAD_STRATA or any(v == "fail" for v in row["labels"].values())

def bad_passes(rows, params=D):
    """(case, check) pairs where a shut_down or invented vendor reaches Passed on a check that must not pass for it. A label wins when present
    (label other than pass); without a label the stratum decides: invented must not pass exists or active, shut_down must not pass active."""
    out = []
    for r in collected(rows):
        if r["stratum"] not in BAD_STRATA: continue
        e = engine(r, params)
        for c in CHECKS:
            lab = r["labels"][c]
            must_not = (lab != "pass") if lab else ((r["stratum"] == "invented" and c in ("exists", "active")) or (r["stratum"] == "shut_down" and c == "active"))
            if must_not and e[c][0] == "pass": out.append((r["case_id"], c))
    return out

def gate(rows, params, base=None, losses=None):
    """Hard gate: no shut_down or invented vendor reaches Passed (exists, active or adverse), and no bad vendor's loss gets worse than at the defaults."""
    base = base or D; viol = [{"case_id": c, "check": k, "why": "bad vendor reaches Passed"} for c, k in bad_passes(rows, params)]
    for r in labelled(rows):
        if is_bad(r) and row_loss(r, params, losses) > row_loss(r, base, losses) + 1e-9: viol.append({"case_id": r["case_id"], "check": "all", "why": "bad vendor's loss gets worse"})
    return viol

# ---------- sweep with the gate ----------
def sweep_gate(rows, grid=GRID, defaults=D, splits=None, losses=None):
    """One at a time. Per value: gate result, established pass rate, cross-validated loss (mean, sd over 20 repeated splits + 5 folds) and the small_real effect."""
    lab = labelled(rows); splits = splits or all_splits(lab) if lab else []; out = {}
    small = [r for r in collected(rows) if r["stratum"] == "small_real"]
    for p, vals in grid.items():
        per = []
        for v in vals:
            par = {**defaults, p: v}
            loss = {r["case_id"]: row_loss(r, par, losses) for r in lab}
            parts = [mean([loss[r["case_id"]] for r in te]) for _, te in splits if te]
            viol = gate(rows, par, defaults, losses); er = established_pass_rate(rows, par)
            per.append({"value": v, "gate_ok": not viol, "violations": len(viol), "established_rate": er["rate"], "cv_loss": mean(parts) if parts else None, "cv_sd": sd(parts),
                        "small_real_nonpass": round(nonpass_rate(small, par), 3), "small_real_loss": mean([loss[r["case_id"]] for r in lab if r["stratum"] == "small_real"]) if any(r["stratum"] == "small_real" for r in lab) else None})
        means = [x["cv_loss"] for x in per]
        kind = classify(vals, means) if all(m is not None for m in means) else "n/a"
        out[p] = {"values": per, "kind": kind, "overfit": kind == "spike"}
    return out

def greedy(rows, grid=GRID, defaults=D, losses=None, order=None, objective="established", freeze=()):
    """Coordinate ascent under the gate: change one parameter at a time, keep a change only if the gate still holds and the established pass rate does not fall;
    prefer a higher established pass rate, then a lower loss, then the value closest to the default. If the defaults violate the gate, first look for the smallest
    set of cross-check rules (D45) that satisfies it; if none does, nothing passes and the gate is not relaxed. Returns (params, trace, started_ok)."""
    cur = dict(defaults); trace = []
    if gate(rows, cur, defaults, losses):
        import itertools
        found = None
        for combo in sorted(itertools.product([False, True], repeat=2), key=sum):
            cand = {**cur, "adverse_pass_needs_exists": combo[0], "adverse_pass_needs_active": combo[1]}
            if not gate(rows, cand, defaults, losses): found = cand; break
        if not found: return cur, [{"note": "the default setting itself violates the gate, and no cross-check rule fixes it"}], False
        cur = found; trace += [{"parameter": k, "from": defaults[k], "to": cur[k]} for k in ("adverse_pass_needs_exists", "adverse_pass_needs_active") if cur[k] != defaults[k]]
    er0 = established_pass_rate(rows, defaults)["rate"] or 0
    lossf = lambda par: mean([row_loss(r, par, losses) for r in labelled(rows)]) if labelled(rows) else 0
    est = lambda par: -(established_pass_rate(rows, par)["rate"] or 0)
    key = (lambda par: (est(par), lossf(par))) if objective == "established" else (lambda par: (round(lossf(par), 3), est(par)))   # "loss": minimise loss, never lowering the established pass rate
    for p in (order or list(grid)):
        if p in freeze: continue
        best, bk = cur[p], key(cur)
        for v in grid[p]:
            cand = {**cur, p: v}
            if gate(rows, cand, defaults, losses): continue
            if objective == "loss" and -est(cand) < er0 - 1e-9: continue
            k = key(cand); closer = isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v - defaults[p]) < abs(best - defaults[p])
            if k < bk or (k == bk and closer): best, bk = v, k
        if best != cur[p]: trace.append({"parameter": p, "from": cur[p], "to": best}); cur[p] = best
    return cur, trace, True

def count_bad_passes(rows, params): return len(bad_passes(rows, params))

# ---------- presets (gate-aware) ----------
LENIENT_MOVES = [("candidate_name_sim_floor", 0.80), ("min_headcount", 3), ("max_decline_pct", 40.0), ("max_series_age_days", 90), ("active_min_signals", 1), ("min_searches", 2),
                 ("adverse_min_severity", 3), ("established_headcount_min", 250)]
STRICT_MOVES = [("adverse_pass_needs_exists", True), ("adverse_pass_needs_active", True), ("adverse_min_results_scanned", 5), ("candidate_name_sim_floor", 0.90), ("min_headcount", 10), ("max_decline_pct", 20.0), ("max_series_age_days", 45), ("active_min_signals", 3), ("min_searches", 4),
                ("adverse_min_severity", 1), ("reject_min_sources", 2), ("established_headcount_min", 1000)]
DESCRIPTIONS = {
    "lenient": "Gives the benefit of the doubt where it is safe to. Large, well-known companies are accepted on a looser name match and with fewer signs of activity, and a single report from one outlet no longer holds them up. It still never accepts a business that looks shut down or does not exist, and anything it cannot settle goes to a person.",
    "balanced": "Our recommended middle setting. It asks for a clear name match and at least two independent signs that the business is operating, treats forum posts and review sites as unverified chatter, and for very large companies wants two reputable sources before raising a concern. Genuine large vendors usually get a clear answer; thin or unclear cases go to a person with a list of what is missing.",
    "strict": "Asks for more before saying yes. The name must match closely, the business must show three signs of activity with recent data, and even minor reports from reputable sources are raised. A rejection needs two separate sources. Expect more cases handed to a person and a heavier load on small or new firms, which often have little public data.",
}

def apply_moves(rows, moves, base, losses=None):
    cur = dict(base); kept = []
    for p, v in moves:
        if cur.get(p) == v: continue
        cand = {**cur, p: v}
        if not gate(rows, cand, D, losses): cur = cand; kept.append(p)
    return cur, kept

def evaluate_preset(rows, params, losses=None):
    lab = labelled(rows); folds = stratified_folds(lab) if lab else []
    cv = mean([mean([row_loss(r, params, losses) for r in te]) for _, te in folds if te]) if lab else None
    hold = [r for r in lab if r["split"] == "holdout"]; sm = [r for r in collected(rows) if r["stratum"] == "small_real"]; lg = [r for r in collected(rows) if r["stratum"] == "large_legit"]
    er = established_pass_rate(rows, params)
    return {"mean_cv_loss": cv, "holdout_loss": mean([row_loss(r, params, losses) for r in hold]) if hold else None, "n_holdout": len(hold),
            "established_pass_rate": er["rate"], "established_fell_back": er["fell_back"], "bad_vendor_passes": count_bad_passes(rows, params),
            "small_real": {"nonpass_rate": round(nonpass_rate(sm, params), 3), "large_nonpass_rate": round(nonpass_rate(lg, params), 3),
                           "loss": mean([row_loss(r, params, losses) for r in lab if r["stratum"] == "small_real"]) if any(r["stratum"] == "small_real" for r in lab) else None}}

BALANCED_FREEZE = ("active_min_signals", "min_headcount", "reject_min_sources", "reject_min_severity")      # safety-relevant: the balanced preset does not loosen these

def build_presets(rows, losses=None):
    """balanced = the lowest-loss setting under the gate that never lowers the established pass rate, with the activity and rejection standards frozen."""
    best, trace, ok0 = greedy(rows, losses=losses, objective="loss", freeze=BALANCED_FREEZE)
    if not ok0:
        return {"blocked": True, "reason": "No setting passes the gate: the default setting already lets a shut_down or invented vendor reach Passed (see tuning_report.md)",
                "violations_at_defaults": gate(rows, D, D, losses)[:20], "presets": {}}
    out = {}
    bal = best
    len_, _ = apply_moves(rows, LENIENT_MOVES, bal, losses); strict, _ = apply_moves(rows, STRICT_MOVES, D, losses)
    for name, par in (("lenient", len_), ("balanced", bal), ("strict", strict)):
        changed = {p: v for p, v in par.items() if D.get(p) != v}
        out[name] = {"params_changed": changed, **evaluate_preset(rows, par, losses), "customer_description": DESCRIPTIONS[name]}
    return {"blocked": False, "greedy_trace": trace, "presets": out}

PRESET_SHAPES = {"lenient": dict(LENIENT_MOVES), "balanced": {}, "strict": dict(STRICT_MOVES)}
def preset_params(name, balanced_changes=None):
    ch = dict(PRESET_SHAPES[name]) if name != "balanced" else dict(balanced_changes or {})
    return {**D, **ch}

def write_presets(rows, losses=None, path=ROOT / "evaluation" / "presets_candidate.json"):
    bp = build_presets(rows, losses)
    doc = {"approved": False, "note": "Candidate presets for the owner. Nothing here is applied. Every preset keeps: no unsourced fail, unreachable leads to HOLD, no CANNOT_VERIFY to CLEARED when a required check is unknown, no rejection on one undated source, and no shut_down or invented vendor reaching Passed (tests/test_preset_invariants.py).",
           "losses": losses or LOSSES, "defaults": {"params": {p: D[p] for p in GRID}, **evaluate_preset(rows, D, losses)}, "strictness": {}, **{k: v for k, v in bp.items() if k != "presets"}, "presets": bp["presets"]}
    for name, p in bp["presets"].items(): doc["strictness"][name] = p["params_changed"]
    path.write_text(json.dumps(doc, indent=1) + "\n"); return doc

# ---------- report ----------
def fmt(x, n=2): return "-" if x is None else f"{x:.{n}f}"

def write_report(rows, doc, losses=None, path=ROOT / "evaluation" / "tuning_report.md"):
    lab = labelled(rows); sc = score(rows); sg = sweep_gate(rows, losses=losses); gr, trace, ok0 = greedy(rows, losses=losses)
    ho = holdout_gate(rows, gr, losses); sens = sensitivity(rows); band = suspicious_band(rows); noise = repeat_noise(doc)
    er = established_pass_rate(rows); er_old = established_pass_rate(rows, {**D, "rule_source_classes": False, "rule_name_collision": False, "established_headcount_min": 10 ** 9})
    L = ["", f"## Scoring with false_pass {LOSSES['false_pass']:g}, false_fail {LOSSES['false_fail']:g}, abstain {LOSSES['abstain']:g}, hold_vs_cnv {LOSSES['hold_vs_cnv']:g} (PROPOSED)", "",
         f"{len(lab)} rows have all three labels (of {len(collected(rows))} collected).", "", "| Check | Rows | Mean loss | Wrong (false pass / false fail) | Abstained | Hold mismatch |", "|---|---|---|---|---|---|"]
    for c, v in sc["per_check"].items(): L.append(f"| {c} | {v['n']} | {fmt(v['loss'] / v['n'] if v['n'] else None)} | {v['wrong']} | {v['abstain']} | {v['hold']} |")
    L += ["", "| Stratum | Rows | Mean loss per row |", "|---|---|---|"] + [f"| {s} | {v['n'] // 3} | {fmt(v['loss'] / (v['n'] / 3))} |" for s, v in sorted(sc["per_stratum"].items())]
    L += ["", "| Split | Rows | Mean loss per row |", "|---|---|---|"] + [f"| {s} | {v['n'] // 3} | {fmt(v['loss'] / (v['n'] / 3))} |" for s, v in sorted(sc["per_split"].items())]
    L += ["", f"### Wrong cases ({len(sc['wrong'])})", ""] + (["None."] if not sc["wrong"] else
          [f"- **{w['case_id']}** ({w['stratum']}), {w['check']}: label `{w['label']}`, engine `{w['engine']}`. Reason: {w['reason']}. Raw: `{json.dumps(w['raw'])}`" for w in sc["wrong"]])
    L += ["", f"### Established pass rate (large_legit + big_brand_noise: exists, active and adverse all Passed)", "",
          f"Current rules: **{er['passed']} of {er['n']} ({fmt((er['rate'] or 0) * 100, 0)}%)**; {er['fell_back']} fell back to Can't verify. Old rules (source classes, name collision and established rule off): {er_old['passed']} of {er_old['n']} ({fmt((er_old['rate'] or 0) * 100, 0)}%).", "",
          "| Why a check fell back (current rules) | Checks |", "|---|---|"] + [f"| {k} | {v} |" for k, v in er["why"].items()]
    L += ["", "## Sweep with the hard gate", "", "Gate: no shut_down or invented vendor reaches Passed on exists, active or adverse, and no bad vendor's loss is worse than at the defaults. 20 repeated stratified splits plus 5-fold cross-validation. Spike = isolated interior best (OVERFIT).", "",
          "| Parameter | Shape | Value | Gate | Established pass rate | CV loss (sd) | small_real non-pass | small_real loss |", "|---|---|---|---|---|---|---|---|"]
    for p, r in sg.items():
        for i, x in enumerate(r["values"]):
            L.append(f"| {p if i == 0 else ''} | {(r['kind'].upper() + (' (OVERFIT)' if r['overfit'] else '')) if i == 0 else ''} | {x['value']} | {'ok' if x['gate_ok'] else 'REJECTED (' + str(x['violations']) + ')'} | {fmt(x['established_rate'])} | {fmt(x['cv_loss'])} ({fmt(x['cv_sd'])}) | {x['small_real_nonpass']} | {fmt(x['small_real_loss'])} |")
    L += ["", "**Joint setting chosen under the gate** " + (f"(greedy, starting from the defaults): `{json.dumps({t['parameter']: t['to'] for t in trace})}`" if ok0 else "NONE: the default setting itself violates the gate, so no setting passes and the gate was not relaxed. Violations at defaults: `" + json.dumps(gate(rows, D, D, losses)[:12]) + "`"),
          "", f"Holdout ({ho['n_holdout']} rows): loss {fmt(ho['holdout_loss_default'])} at defaults, {fmt(ho['holdout_loss_chosen'])} at the chosen setting; bad-vendor passes at the chosen setting: {ho['bad_passes_chosen']}.", ""]
    L += ["### Sensitivity on ALL collected rows (checks that change per parameter step)", "", "| Parameter | Step | Rows changed | exists / active / adverse |", "|---|---|---|---|"]
    for p, r in sens.items():
        for st in r["steps"]: L.append(f"| {p}{' **UNSTABLE**' if st['share'] >= 0.10 else ''} | {st['from']} to {st['to']} | {st['rows_changed']} of {r['n_rows']} ({st['share']:.0%}) | {st['by_check']['exists']} / {st['by_check']['active']} / {st['by_check']['adverse_media']} |")
    L += ["", "### Suspicious band and search noise", "", "| Group | Rows | Concern fires | Rate |", "|---|---|---|---|"]
    for k, v in {**band["by_label"], **{f"stratum {s}": x for s, x in band["by_stratum"].items()}}.items(): L.append(f"| {k} | {v['n']} | {v['fires']} | {fmt(v['rate'])} |")
    L += ["", f"Repeat test ({len(noise)} rows): status flips in {sum(1 for n in noise if n['status_flips'])} rows; minimum hit overlap per row: " + (", ".join(str(n['hit_jaccard_min']) for n in noise) or "n/a") + f"; dates changed on {sum(n['date_changes'] for n in noise)} of {sum(n['common_hits'] for n in noise)} common hits."]
    path.write_text((path.read_text() if path.exists() else "") + "\n".join(L) + "\n")
    return {"score": sc, "sweep": sg, "greedy": gr, "trace": trace, "holdout": ho, "established": er, "established_old": er_old, "band": band, "noise": noise}

def holdout_gate(rows, chosen, losses=None):
    hold = [r for r in labelled(rows) if r["split"] == "holdout"]; f = lambda par: mean([row_loss(r, par, losses) for r in hold]) if hold else None
    return {"n_holdout": len(hold), "holdout_loss_default": f(D), "holdout_loss_chosen": f(chosen), "bad_passes_chosen": count_bad_passes(rows, chosen)}

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", nargs="?", default="all"); ap.add_argument("--losses", help="JSON overriding the loss weights"); ap.add_argument("--min-labelled", type=int, default=25)
    ap.add_argument("--labels", help="provisional label file used only where cases_real.csv is blank")
    ap.add_argument("--signals", default=str(ROOT / "evaluation" / "signals_real.json")); ap.add_argument("--report", default=str(ROOT / "evaluation" / "tuning_report.md"))
    ap.add_argument("--presets", default=str(ROOT / "evaluation" / "presets_candidate.json"))
    a = ap.parse_args(argv)
    global LOSSES
    if a.losses: LOSSES = {**LOSSES, **json.loads(a.losses)}
    rows = load_cases(signals_path=a.signals, labels_path=a.labels); doc = json.loads(Path(a.signals).read_text()); n = len(labelled(rows))
    if n < a.min_labelled: print(f"only {n} fully labelled rows (need {a.min_labelled}): not scoring"); return 1
    res = write_report(rows, doc, LOSSES, path=Path(a.report)); write_presets(rows, LOSSES, path=Path(a.presets)); print(f"scored {n} labelled rows; wrote tuning_report.md sections and presets_candidate.json"); return 0

if __name__ == "__main__": raise SystemExit(main())
