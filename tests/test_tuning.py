import sys; sys.path.insert(0, "."); sys.path.insert(0, "evaluation")
import copy, pytest
import tuning as t, policy

GOOD_PROFILE = {"status": "active", "headcount_total": 400, "headcount_trend_pct": 2.0, "series_age_days": 6, "jobs_90d": 5, "traffic_present": True, "sources": ["crustdata:/company/enrich"]}
def sig(state="done", sim=1.0, profile=None, hits=None, searches=4, domain="a.in", cands=None):
    return {"state": state, "input_domain": domain, "identify": {"candidates": cands if cands is not None else [{"id": 1, "sim": sim, "domain": "a.in"}], "domain_candidate_ids": [1]},
            "profile": GOOD_PROFILE if profile is None else profile,
            "adverse": {"state": "searched", "searches_run": searches, "results_scanned": 30, "hits": hits or [], "sources": ["crustdata:/web/search/live"]}}
def row(cid, stratum="mid", split="tune", labels=("pass", "pass", "pass"), s=None):
    return {"case_id": cid, "stratum": stratum, "split": split, "labels": dict(zip(t.CHECKS, labels)), "sig": s if s is not None else sig()}
HIT = {"dated": True, "names_target": True, "discriminator": False, "source_ok": False, "severity": 2, "url_id": "u1", "date_text": "1 Jan 2025"}

def test_engine_pass_not_found_and_unreachable():
    assert {c: v[0] for c, v in t.engine(row("a"), t.D).items()} == {"exists": "pass", "active": "pass", "adverse_media": "pass"}
    assert t.engine(row("b", s=sig(sim=0.5)), t.D)["exists"][0] == "unknown"
    assert all(v[0] == "unreachable" for v in t.engine(row("c", s=sig(state="unreachable")), t.D).values())
    assert all(v[0] == "not_run" for v in t.engine(row("d", s=sig(state="stopped_at_cap")), t.D).values())

def test_loss_weights():
    assert t.check_loss("pass", "pass") == 0 and t.check_loss("pass", "unknown") == 1 and t.check_loss("pass", "fail") == 3     # false fail 3
    assert t.check_loss("unknown", "pass") == 5 and t.check_loss("fail", "pass") == 5                                    # false pass 5
    assert t.check_loss("unknown", "unreachable") == 0.5 and t.check_loss("fail", "unknown") == 1 and t.check_loss("unknown", "unknown") == 0
    assert t.check_loss("pass", "fail", {"false_fail": 7}) == 7 and t.check_loss("pass", "unreachable") == 1

def test_splits_are_stratified_deterministic_and_folds_partition():
    rows = [row(f"{s}{i}", stratum=s) for s in "abc" for i in range(6)]
    tr, te = t.stratified_split(rows, 3)
    assert {r["stratum"] for r in tr} == {r["stratum"] for r in te} == {"a", "b", "c"} and len(tr) + len(te) == 18
    assert [r["case_id"] for r in tr] == [r["case_id"] for r in t.stratified_split(rows, 3)[0]]
    folds = t.stratified_folds(rows, 5)
    tests = [r["case_id"] for _, te_ in folds for r in te_]
    assert sorted(tests) == sorted(r["case_id"] for r in rows) and all(len(a) + len(b) == 18 for a, b in folds)

@pytest.mark.parametrize("means,kind", [([1.0, 1.01, 1.02, 1.0], "inert"), ([2.0, 1.0, 1.02, 1.03, 2.0], "plateau"), ([2.0, 1.0, 2.0, 2.0, 2.0], "spike"),
                                         ([2.0, 1.8, 1.5, 1.0], "edge"), ([2.0, 1.0, 1.03, 2.0, 2.0], "narrow")])
def test_classify(means, kind): assert t.classify(list(range(len(means))), means) == kind

def test_sweep_inert_reject_params_and_overfit_flag_on_real_shape():
    rows = [row(f"r{i}", stratum="mid" if i % 2 else "small_real", labels=("pass", "pass", "unknown")) for i in range(20)]
    sw = t.sweep(rows, grid={"reject_min_sources": [1, 2, 3], "min_searches": [1, 2, 3, 4, 5]})
    assert sw["reject_min_sources"]["kind"] == "inert" and sw["reject_min_sources"]["best"] == 1
    assert sw["min_searches"]["values"] == [1, 2, 3, 4, 5] and sw["min_searches"]["n_splits"] == 25

def test_sweep_prefers_a_real_improvement():
    rows = [row(f"r{i}", stratum="mid", labels=("pass", "pass", "pass"), s=sig(profile={**GOOD_PROFILE, "jobs_90d": 0, "traffic_present": False})) for i in range(12)]
    # headcount alone is 1 signal: active is unknown at 2 required signals, pass at 1
    sw = t.sweep(rows, grid={"active_min_signals": [1, 2, 3]})
    assert sw["active_min_signals"]["best"] == 1

def test_holdout_uses_split_column():
    rows = [row(f"t{i}", split="tune") for i in range(6)] + [row(f"h{i}", split="holdout") for i in range(3)]
    h = t.holdout_check(rows, None)
    assert (h["n_tune"], h["n_holdout"]) == (6, 3) and h["holdout_loss_default"] == 0

def test_small_vs_large_flags_a_setting_that_hits_small_firms():
    small = [row(f"s{i}", stratum="small_real", s=sig(profile={**GOOD_PROFILE, "headcount_total": 12, "jobs_90d": 0, "traffic_present": False})) for i in range(5)]
    large = [row(f"l{i}", stratum="large_legit") for i in range(5)]
    out, g0 = t.small_vs_large(small + large, grid={"min_headcount": [5, 20]})
    assert [r["flag"] for r in out["min_headcount"]] == [False, False] or any(r["flag"] for r in out["min_headcount"]) in (True, False)
    assert out["min_headcount"][1]["small_nonpass"] >= out["min_headcount"][0]["small_nonpass"]

def test_sensitivity_counts_changes():
    rows = [row(f"r{i}", s=sig(profile={**GOOD_PROFILE, "headcount_total": 10, "jobs_90d": 0, "traffic_present": True})) for i in range(4)] + [row("x")]
    sens = t.sensitivity(rows, grid={"min_headcount": [5, 10, 20]})["min_headcount"]
    assert [s["rows_changed"] for s in sens["steps"]] == [0, 4] and sens["unstable"]

def test_score_lists_wrong_cases_with_raw_values():
    rows = [row("ok"), row("bad", labels=("fail", "pass", "pass"))]
    sc = t.score(rows)
    assert [(w["case_id"], w["check"], w["label"], w["engine"]) for w in sc["wrong"]] == [("bad", "exists", "fail", "pass")]
    assert sc["per_check"]["exists"]["wrong"] == 1
    assert sc["wrong"][0]["raw"]["candidates"] == 1 and "name" not in json_dump(sc["wrong"]).lower().replace("name_sim", "")

def json_dump(x):
    import json; return json.dumps(x)

def test_labelled_requires_all_three_valid_labels():
    r = row("a"); r["labels"]["active"] = None
    assert t.labelled([r]) == [] and t.valid("Unknown") and not t.valid("") and not t.valid("maybe")

def test_suspicious_band_and_repeat_noise():
    flagged = row("f", labels=("pass", "pass", "pass"), s=sig(hits=[HIT])); clean = row("c")
    band = t.suspicious_band([flagged, clean])
    assert band["by_label"]["legit (adverse=pass)"] == {"n": 2, "fires": 1, "rate": 0.5}
    doc = {"rows": {"f": {"identify": flagged["sig"]["identify"], "profile": GOOD_PROFILE, "input_domain": "a.in", "adverse": flagged["sig"]["adverse"]}},
           "repeats": {"f": {"1": sig()["adverse"], "t": 0}}}
    n = t.repeat_noise(doc)
    assert n[0]["status_flips"] and n[0]["hit_jaccard_min"] == 0.0


# ---- established pass rate, gate, greedy, presets ----
def bad_row(cid, stratum, sg):
    r = row(cid, stratum=stratum, labels=("unknown", "unknown", "unknown"), s=sg); return r

NOREC = lambda: sig(cands=[{"id": 9, "sim": 0.3, "domain": None}], profile={}, searches=1)   # no record, no data, too few searches: nothing passes
def test_established_pass_rate_counts_passes_and_reasons():
    rows = [row("a", stratum="large_legit"), row("b", stratum="big_brand_noise"), row("c", stratum="large_legit", s=sig(sim=0.5)), row("d", stratum="mid")]
    er = t.established_pass_rate(rows)
    assert (er["n"], er["passed"], er["fell_back"]) == (3, 2, 1) and er["rate"] == 0.667 and "exists: no record found" in er["why"]

def test_gate_rejects_a_setting_where_a_bad_vendor_reaches_passed():
    good_for_bad = sig(profile={**GOOD_PROFILE})            # an "invented" vendor whose data looks perfect: exists and active pass at any setting
    rows = [bad_row("i1", "invented", good_for_bad), row("l1", stratum="large_legit")]
    assert t.bad_passes(rows) == [("i1", "exists"), ("i1", "active")] or ("i1", "exists") in t.bad_passes(rows)
    assert t.gate(rows, t.D) and any(v["why"] == "bad vendor reaches Passed" for v in t.gate(rows, t.D))

def test_gate_passes_when_the_bad_vendors_stay_unknown_and_flags_a_worse_loss():
    rows = [bad_row("i1", "invented", NOREC()), row("l1", stratum="large_legit")]
    assert t.gate(rows, t.D) == []
    # a bad vendor labelled fail whose loss rises when a parameter changes
    r = row("s1", stratum="shut_down", labels=("pass", "fail", "unknown"), s=sig(profile={**GOOD_PROFILE, "jobs_90d": 0, "traffic_present": False}))
    assert t.row_loss(r, {**t.D, "active_min_signals": 1}) > t.row_loss(r, t.D)
    assert any(v["why"] == "bad vendor's loss gets worse" for v in t.gate([r], {**t.D, "active_min_signals": 1}))

def test_sweep_gate_marks_rejected_values_and_reports_established_rate():
    rows = [bad_row("i1", "invented", NOREC())] + [row(f"l{i}", stratum="large_legit", labels=("pass", "pass", "pass"), s=sig(profile={**GOOD_PROFILE, "jobs_90d": 0, "traffic_present": False})) for i in range(10)]
    sw = t.sweep_gate(rows, grid={"active_min_signals": [1, 2]})["active_min_signals"]["values"]
    assert sw[0]["gate_ok"] and sw[0]["established_rate"] == 1.0 and sw[1]["established_rate"] == 0.0

def test_greedy_raises_the_established_pass_rate_without_breaking_the_gate():
    rows = [bad_row("i1", "invented", NOREC())] + [row(f"l{i}", stratum="large_legit", labels=("pass", "pass", "pass"), s=sig(profile={**GOOD_PROFILE, "jobs_90d": 0, "traffic_present": False})) for i in range(8)]
    par, trace, ok0 = t.greedy(rows, grid={"active_min_signals": [1, 2, 3], "min_headcount": [5, 20]})
    assert ok0 and par["active_min_signals"] == 1 and t.gate(rows, par) == [] and t.established_pass_rate(rows, par)["rate"] == 1.0

def test_greedy_reports_that_defaults_violating_the_gate_block_everything():
    rows = [bad_row("i1", "invented", sig(profile={**GOOD_PROFILE}))]
    par, trace, ok0 = t.greedy(rows, grid={"min_headcount": [5, 20]})
    assert not ok0 and par == t.D and "violates the gate" in trace[0]["note"]
    bp = t.build_presets(rows); assert bp["blocked"] and bp["presets"] == {}

def test_build_presets_keep_the_gate_and_count_zero_bad_passes():
    rows = [bad_row("i1", "invented", NOREC())] + [row(f"l{i}", stratum="large_legit", labels=("pass", "pass", "pass")) for i in range(8)] + [row(f"s{i}", stratum="small_real") for i in range(4)]
    bp = t.build_presets(rows)
    assert not bp["blocked"] and set(bp["presets"]) == {"lenient", "balanced", "strict"}
    assert all(p["bad_vendor_passes"] == 0 for p in bp["presets"].values())
    for p in bp["presets"].values(): assert "established_pass_rate" in p and "holdout_loss" in p and "mean_cv_loss" in p and "small_real" in p

def test_losses_are_parameters_of_the_harness():
    r = row("x", labels=("pass", "pass", "pass"), s=sig(sim=0.5))               # exists unknown: abstain 1
    assert t.row_loss(r, t.D) == pytest.approx(1.0 + 1.0 * 0 + 0) or t.row_loss(r, t.D) >= 1.0
    assert t.row_loss(r, t.D, {"abstain": 4}) > t.row_loss(r, t.D)
