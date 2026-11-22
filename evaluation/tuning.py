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

CHECKS = ("exists", "active", "adverse_media")
LABEL_COL = {"exists": "expected_exists", "active": "expected_active", "adverse_media": "expected_adverse"}
VERDICT = {"pass": "CLEARED", "fail": "REJECTED", "unknown": "CANNOT_VERIFY", "unreachable": "HOLD_FOR_APPROVAL", "not_run": "CANNOT_VERIFY"}
W = run_eval.WEIGHTS
D = policy.PROPOSED_PARAMS
GRID = {"candidate_name_sim_floor": [0.70, 0.75, 0.80, 0.85, 0.90, 0.95], "min_headcount": [1, 3, 5, 10, 20], "max_decline_pct": [10, 20, 30, 40, 60],
        "max_series_age_days": [30, 45, 60, 90, 120, 180], "min_jobs_90d": [1, 2, 3, 5], "active_min_signals": [1, 2, 3], "min_searches": [1, 2, 3, 4, 5],
        "adverse_min_severity": [1, 2, 3], "reject_min_severity": [1, 2, 3], "reject_min_sources": [1, 2, 3]}

# ---------- loading ----------
def valid(x): return (x or "").strip().lower() in ("pass", "fail", "unknown")

def load_cases(csv_path=ROOT / "evaluation" / "cases_real.csv", signals_path=ROOT / "evaluation" / "signals_real.json"):
    sig = json.loads(Path(signals_path).read_text())["rows"] if Path(signals_path).exists() else {}
    rows = []
    for r in csv.DictReader(open(csv_path)):
        s = sig.get(r["case_id"])
        labels = {c: r[LABEL_COL[c]].strip().lower() if valid(r[LABEL_COL[c]]) else None for c in CHECKS}
        rows.append({"case_id": r["case_id"], "stratum": r["stratum"], "split": r["split"], "labels": labels, "sig": s})
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
    sig["adverse"] = s["adverse"] or {"state": "searched", "searches_run": 0, "hits": [], "sources": []}
    checks = policy.evaluate(sig, params, "low")
    return {c: (checks[c]["status"], checks[c]["reason"]) for c in CHECKS}

def check_loss(label, status): return run_eval.cost(VERDICT[label], VERDICT[status], W)
def row_loss(row, params):
    e = engine(row, params); return sum(check_loss(row["labels"][c], e[c][0]) for c in CHECKS)

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
            pc["wrong"] += l == W["wrong"]; pc["abstain"] += (l == W["abstain"]); pc["hold"] += (l == W["hold_vs_cnv"])
            for key, d in ((r["stratum"], strata), (r["split"], splits)): d.setdefault(key, {"n": 0, "loss": 0.0})["n"] += 1; d[key]["loss"] += l
            if l == W["wrong"]: wrong.append({"case_id": r["case_id"], "stratum": r["stratum"], "check": c, "label": r["labels"][c], "engine": st, "reason": why, "raw": raw_values(r, c, params)})
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

# ---------- phase 6: presets ----------
PRESET_SHAPES = {
    "lenient": {"candidate_name_sim_floor": 0.80, "min_headcount": 3, "max_decline_pct": 40.0, "max_series_age_days": 90, "min_jobs_90d": 1, "active_min_signals": 1, "min_searches": 2, "adverse_min_severity": 3},
    "balanced": {},
    "strict": {"candidate_name_sim_floor": 0.90, "min_headcount": 10, "max_decline_pct": 20.0, "max_series_age_days": 45, "active_min_signals": 3, "min_searches": 4, "adverse_min_severity": 1, "reject_min_sources": 2},
}
DESCRIPTIONS = {
    "lenient": "Gives the benefit of the doubt. A vendor is accepted on a looser name match, with fewer signs of activity, and only serious-looking reports are raised. Expect more vendors to be cleared automatically and a higher chance that a weak vendor slips through to a person for approval.",
    "balanced": "Our recommended middle setting. It asks for a clear name match and at least two independent signs that the business is operating, and it raises any report that names the company. Most genuine vendors get a clear answer; thin or unclear cases go to a person with a list of what is missing.",
    "strict": "Asks for more before saying yes. The name must match closely, the business must show three signs of activity with recent data, and even minor reports naming the company are raised, and a rejection needs two separate sources. Expect more cases handed to a person, fewer wrong approvals, and a heavier load on small or new firms, which often have little public data.",
}

def preset_params(name, balanced_changes=None):
    ch = dict(PRESET_SHAPES[name]) if name != "balanced" else dict(balanced_changes or {})
    return {**D, **ch}

def evaluate_preset(rows, params):
    lab = labelled(rows); folds = stratified_folds(lab)
    cv = mean([mean([row_loss(r, params) for r in te]) for _, te in folds if te]) if lab else None
    hold = [r for r in lab if r["split"] == "holdout"]; sm = [r for r in collected(rows) if r["stratum"] == "small_real"]; lg = [r for r in collected(rows) if r["stratum"] == "large_legit"]
    return {"mean_cv_loss": cv, "holdout_loss": mean([row_loss(r, params) for r in hold]) if hold else None, "n_holdout": len(hold),
            "small_real": {"nonpass_rate": round(nonpass_rate(sm, params), 3), "large_nonpass_rate": round(nonpass_rate(lg, params), 3),
                           "loss": mean([row_loss(r, params) for r in lab if r["stratum"] == "small_real"]) if any(r["stratum"] == "small_real" for r in lab) else None}}

# ---------- report ----------
def fmt(x, n=2): return "-" if x is None else f"{x:.{n}f}"

def write_report(rows, doc, path=ROOT / "evaluation" / "tuning_report.md"):
    lab = labelled(rows); sc = score(rows); sw = sweep(rows); ho = holdout_check(rows, None)
    sl, g0 = small_vs_large(rows); sens = sensitivity(rows); band = suspicious_band(rows); noise = repeat_noise(doc)
    L = ["", "## Phase 3: scoring the engine against your labels (defaults, 0 credits)", "",
         f"{len(lab)} rows have all three labels (of {len(collected(rows))} collected). Loss: wrong 3, abstain 1, hold-vs-cannot-verify 0.5 per check.", "",
         "| Check | Rows | Mean loss | Wrong (engine definitive, label different) | Abstained (engine unknown, label definitive) | Hold mismatch |", "|---|---|---|---|---|---|"]
    for c, v in sc["per_check"].items(): L.append(f"| {c} | {v['n']} | {fmt(v['loss'] / v['n'] if v['n'] else None)} | {v['wrong']} | {v['abstain']} | {v['hold']} |")
    L += ["", "| Stratum | Rows | Mean loss per row (3 checks) |", "|---|---|---|"] + [f"| {s} | {v['n'] // 3} | {fmt(v['loss'] / (v['n'] / 3))} |" for s, v in sorted(sc["per_stratum"].items())]
    L += ["", "| Split | Rows | Mean loss per row |", "|---|---|---|"] + [f"| {s} | {v['n'] // 3} | {fmt(v['loss'] / (v['n'] / 3))} |" for s, v in sorted(sc["per_split"].items())]
    L += ["", f"### Wrong cases ({len(sc['wrong'])}): engine definitive and different from your label", ""]
    if not sc["wrong"]: L.append("None.")
    for w in sc["wrong"]: L.append(f"- **{w['case_id']}** ({w['stratum']}), {w['check']}: label `{w['label']}`, engine `{w['engine']}`. Reason: {w['reason']}. Raw: `{json.dumps(w['raw'])}`")
    L += ["", "## Phase 4: parameter sweep (one at a time, others at defaults)", "",
          f"Labelled rows: {len(lab)}. 20 repeated stratified 2/3-1/3 splits plus 5-fold cross-validation ({len(all_splits(lab))} held-out parts). Loss = mean row loss (3 checks) on the held-out part. Plateau: 3 adjacent values within 5% of the best. Spike: an isolated interior best, marked OVERFIT. Inert: no value changes the loss.", "",
          "| Parameter | Best | Default | Shape | Chosen by train in | Mean loss by value (sd) |", "|---|---|---|---|---|---|"]
    for p, r in sw.items():
        vals = ", ".join(f"{v}: {fmt(m)} ({fmt(s)})" for v, m, s in zip(r["values"], r["mean_loss"], r["sd_loss"]))
        L.append(f"| {p} | {r['best']} | {D[p]} | {r['kind'].upper()}{' (OVERFIT)' if r['overfit'] else ''} | {fmt((r['selected_best_share'] or 0) * 100, 0)}% of splits | {vals} |")
    L += ["", f"Holdout check (best value per parameter chosen on {ho['n_tune']} tune rows, evaluated on {ho['n_holdout']} holdout rows): tune loss {fmt(ho['tune_loss_default'])} to {fmt(ho['tune_loss_chosen'])}; holdout loss {fmt(ho['holdout_loss_default'])} (defaults) to {fmt(ho['holdout_loss_chosen'])} (chosen). Chosen: `{json.dumps(ho['chosen_on_tune'])}`", "",
          f"### small_real versus large_legit (all collected rows; default gap {g0:+.3f} in non-pass rate)", "", "| Parameter | Value | small non-pass | large non-pass | gap | flag |", "|---|---|---|---|---|---|"]
    for p, rs in sl.items():
        for r in rs:
            if r["flag"]: L.append(f"| {p} | {r['value']} | {r['small_nonpass']} | {r['large_nonpass']} | {r['gap']:+.3f} | pushes small firms to unknown or fail more than large ones |")
    if not any(r["flag"] for rs in sl.values() for r in rs): L.append("| (none flagged) | | | | | |")
    L += ["", "### Sensitivity on ALL collected rows (verdict changes per parameter step)", "", "| Parameter | Step | Rows changed | by check (exists / active / adverse) |", "|---|---|---|---|"]
    for p, r in sens.items():
        for s in r["steps"]: L.append(f"| {p}{' **UNSTABLE**' if s['share'] >= 0.10 else ''} | {s['from']} to {s['to']} | {s['rows_changed']} of {r['n_rows']} ({s['share']:.0%}) | {s['by_check']['exists']} / {s['by_check']['active']} / {s['by_check']['adverse_media']} |")
    L += ["", "## Phase 5: the suspicious band and search noise", "", "A concern = adverse check `unknown` because reports name the company but cannot be confirmed (below the rejection bar).", "", "| Group | Rows | Concern fires | Rate |", "|---|---|---|---|"]
    for k, v in {**band["by_label"], **{f"stratum {s}": x for s, x in band["by_stratum"].items()}}.items(): L.append(f"| {k} | {v['n']} | {v['fires']} | {fmt(v['rate'])} |")
    L += ["", f"Repeat test ({len(noise)} rows, 3 runs each when complete): status flips between runs in {sum(1 for n in noise if n['status_flips'])} rows; minimum hit-set overlap (Jaccard) per row: "
          + (", ".join(str(n['hit_jaccard_min']) for n in noise) or "n/a") + f"; dates changed on {sum(n['date_changes'] for n in noise)} of {sum(n['common_hits'] for n in noise)} hits seen in every run."]
    path.write_text(path.read_text() + "\n".join(L) + "\n") if path.exists() else path.write_text("\n".join(L) + "\n")
    return {"score": sc, "sweep": sw, "holdout": ho, "small_vs_large": sl, "sensitivity": sens, "band": band, "noise": noise}

def write_presets(rows, results, path=ROOT / "evaluation" / "presets_candidate.json"):
    sw = results["sweep"]
    bal = {p: r["best"] for p, r in sw.items() if r["best"] != D[p] and r["kind"] in ("plateau", "narrow", "edge") and not r["overfit"]
           and p in ("candidate_name_sim_floor", "min_headcount", "max_decline_pct", "max_series_age_days", "min_jobs_90d", "active_min_signals", "min_searches", "adverse_min_severity")}
    out = {"approved": False, "strictness": {}, "note": "Candidate presets for the owner to review. Nothing here is applied. Invariants kept by every preset: no unsourced fail, unreachable leads to HOLD, no CANNOT_VERIFY to CLEARED when a required check is unknown, no rejection on one undated source (tests/test_preset_invariants.py).",
           "defaults": {"params": {p: D[p] for p in GRID}, **evaluate_preset(rows, D)}, "presets": {}}
    for name in ("lenient", "balanced", "strict"):
        par = preset_params(name, bal); ev = evaluate_preset(rows, par)
        changed = {p: v for p, v in par.items() if D.get(p) != v}
        out["strictness"][name] = changed             # the shape controls.py reads (only used once "approved" is set to true by the owner)
        out["presets"][name] = {"params_changed": changed, **ev, "customer_description": DESCRIPTIONS[name]}
    path.write_text(json.dumps(out, indent=1) + "\n"); return out

def main(argv=None):
    cmd = (argv or sys.argv[1:] or ["all"])[0]
    rows = load_cases(); doc = json.loads((ROOT / "evaluation" / "signals_real.json").read_text())
    n = len(labelled(rows))
    if n < 25: print(f"only {n} fully labelled rows (need 25): not scoring"); return 1
    res = write_report(rows, doc); write_presets(rows, res); print(f"scored {n} labelled rows; wrote tuning_report.md sections and presets_candidate.json"); return 0

if __name__ == "__main__": raise SystemExit(main())
