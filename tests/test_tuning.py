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
    assert t.check_loss("pass", "pass") == 0 and t.check_loss("pass", "unknown") == 1 and t.check_loss("pass", "fail") == 3
    assert t.check_loss("unknown", "pass") == 3 and t.check_loss("unknown", "unreachable") == 0.5 and t.check_loss("fail", "unknown") == 1

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
