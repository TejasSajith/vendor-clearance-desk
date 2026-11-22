import json, random, sys; sys.path.insert(0, "."); sys.path.insert(0, "evaluation")
from pathlib import Path
import pytest
import decision, policy, tuning

PRESET_FILE = Path("evaluation/presets_candidate.json")
def all_presets():
    ps = {n: tuning.preset_params(n) for n in ("lenient", "balanced", "strict")}
    if PRESET_FILE.exists():
        for n, p in json.loads(PRESET_FILE.read_text())["presets"].items(): ps[f"file:{n}"] = {**policy.PROPOSED_PARAMS, **p["params_changed"]}
    return ps
PRESETS = all_presets()

def rand_signals(rnd):
    cands = [{"id": rnd.randint(1, 9), "sim": rnd.choice([0.5, 0.8, 0.9, 1.0]), "domain": rnd.choice([None, "a.in"])} for _ in range(rnd.randint(0, 4))]
    ident = {"candidates": cands, "domain_candidate_ids": rnd.choice([None, [], [1], [2]]), "status": rnd.choice([None, "active", "deleted"])}
    p = rnd.choice([{}, None, {"headcount_total": rnd.choice([None, 0, 3, 40, 900]), "headcount_trend_pct": rnd.choice([None, -50.0, 0.0, 9.0]),
                                "series_age_days": rnd.choice([None, 5, 70, 400]), "jobs_90d": rnd.choice([None, 0, 3]), "traffic_present": rnd.choice([None, False, True]),
                                "sources": ["s"]}])
    hits = [{"dated": rnd.random() < .5, "names_target": rnd.random() < .8, "discriminator": rnd.random() < .5, "source_ok": rnd.random() < .5,
             "severity": rnd.randint(0, 3), "url": rnd.choice([None, "https://x.example/a", "https://y.example/b"])} for _ in range(rnd.randint(0, 3))]
    adv = rnd.choice([None, {"state": "unreachable", "sources": ["w"]}, {"state": "searched", "searches_run": rnd.randint(0, 5), "results_scanned": rnd.randint(0, 40), "hits": hits, "sources": ["w"]}])
    dr = rnd.choice([{"not_requested": True}, {"no_company": True}, {"found": True, "company_id_match": True, "start_date_plausible": True, "discriminators_agree": True, "contradicted": rnd.random() < .3, "sources": ["p"]}, {}])
    sig = {"identify": pipeline_identify(ident, rnd), "director": dr}
    if p is not None: sig["profile"] = p
    if adv is not None: sig["adverse"] = adv
    return sig

def pipeline_identify(ident, rnd):
    import pipeline
    return pipeline.identify_signals("", rnd.choice(["", "a.in"]), ident, policy.PROPOSED_PARAMS)

@pytest.mark.parametrize("name", sorted(PRESETS))
def test_preset_is_inside_the_safe_bounds(name):
    p = PRESETS[name]
    assert p["reject_require_dated"] is True and p["reject_min_sources"] >= 1 and p["reject_min_severity"] >= 2
    assert p["min_searches"] >= 1 and p["active_min_signals"] >= 1 and p["min_headcount"] >= 1 and 0.5 <= p["candidate_name_sim_floor"] <= 0.99

@pytest.mark.parametrize("name", sorted(PRESETS))
def test_invariants_hold_on_random_signals(name):
    p, rnd = PRESETS[name], random.Random(11)
    for _ in range(600):
        sig = rand_signals(rnd)
        for tier in ("low", "high"):
            checks = policy.evaluate(sig, p, tier)
            for c, r in checks.items():                                                      # 1. no unsourced fail
                if r["status"] == "fail": assert len(set(r["sources"])) >= p["reject_min_sources"] >= 1, (c, r)
            d = decision.decide({**checks, **({} if "director_match" in checks else {})})
            if any(r["status"] == "unreachable" for r in checks.values()): assert d.verdict == decision.HOLD            # 2. unreachable -> HOLD
            if d.verdict == decision.CLEARED: assert all(checks[c]["status"] == "pass" for c in ("exists", "active", "director_match", "adverse_media"))   # 3.

@pytest.mark.parametrize("name", sorted(PRESETS))
def test_missing_data_never_passes(name):
    p = PRESETS[name]
    assert policy.evaluate({"identify": {"found": True, "name_similarity": 1.0, "top_ties": 1, "domain_match": True, "sources": ["i"]}, "profile": {}}, p)["active"]["status"] != "pass"
    assert policy.evaluate({"identify": {"found": True, "name_similarity": 1.0, "top_ties": 1, "domain_match": True, "sources": ["i"]},
                            "adverse": {"state": "searched", "searches_run": 0, "hits": [], "sources": ["w"]}}, p)["adverse_media"]["status"] != "pass"
    assert policy.evaluate({"identify": {"found": False, "sources": ["i"]}}, p)["exists"]["status"] == "unknown"

@pytest.mark.parametrize("name", sorted(PRESETS))
def test_no_rejection_on_one_undated_source(name):
    p = PRESETS[name]
    for severity in (1, 2, 3):
        hit = {"dated": False, "names_target": True, "discriminator": True, "source_ok": True, "severity": severity, "url": "https://x.example/a"}
        assert policy.evaluate({"adverse": {"state": "searched", "searches_run": 4, "hits": [hit], "sources": ["w"]}}, p)["adverse_media"]["status"] != "fail"

def test_presets_file_is_unapproved_and_descriptions_name_no_parameters():
    if not PRESET_FILE.exists(): pytest.skip("presets_candidate.json is written by phase 6")
    doc = json.loads(PRESET_FILE.read_text())
    assert doc["approved"] is False and set(doc["presets"]) == {"lenient", "balanced", "strict"}
    names = set(policy.PROPOSED_PARAMS)
    for n, p in doc["presets"].items():
        text = p["customer_description"].lower()
        assert text and not any(k in text for k in names) and "_" not in text and "threshold" not in text


def test_presets_file_works_through_controls_when_approved(tmp_path):
    if not PRESET_FILE.exists(): pytest.skip("presets_candidate.json is written by phase 6")
    import controls
    doc = json.loads(PRESET_FILE.read_text()); doc["approved"] = True
    f = tmp_path / "approved.json"; f.write_text(json.dumps(doc))
    for name in ("lenient", "balanced", "strict"):
        r = controls.resolve({"strictness": name}, candidate_path=str(f))
        assert r["params"]["reject_require_dated"] is True and r["params"]["reject_min_sources"] >= 1 and r["params"]["min_searches"] >= 1
        for k, v in doc["strictness"][name].items(): assert r["params"][k] == v, (name, k)
    unapproved = controls.resolve({"strictness": "strict"}, candidate_path=str(PRESET_FILE))
    assert unapproved["params"] == policy.PROPOSED_PARAMS and any("not approved" in n for n in unapproved["notes"])

@pytest.mark.parametrize("name", sorted(PRESETS))
def test_no_preset_passes_an_invented_or_shut_down_vendor(name):
    p = PRESETS[name]
    base = {"state": "done", "input_domain": "a.in", "adverse": {"state": "searched", "searches_run": 4, "results_scanned": 20, "per_search": [{"source": "web", "results": []}] * 4}}
    invented = {"case_id": "i", "name": "Quillvane Freight", "stratum": "invented", "split": "tune", "labels": {"exists": None, "active": None, "adverse_media": None},
                "sig": {**base, "identify": {"candidates": [{"id": 5, "sim": 0.2, "domain": None}], "domain_candidate_ids": None}, "profile": None}}
    shut = {"case_id": "s", "name": "Old Carriers", "stratum": "shut_down", "split": "tune", "labels": {"exists": None, "active": None, "adverse_media": None},
            "sig": {**base, "identify": {"candidates": [{"id": 5, "sim": 1.0, "domain": "a.in"}], "domain_candidate_ids": [5]},
                    "profile": {"status": "deleted", "headcount_total": 30, "headcount_trend_pct": -60.0, "series_age_days": 700, "jobs_90d": 0, "traffic_present": False, "sources": ["s"]}}}
    assert tuning.bad_passes([invented, shut], p) == []

def test_file_presets_report_zero_bad_vendor_passes_and_the_metrics():
    if not PRESET_FILE.exists(): pytest.skip("presets_candidate.json is written by the scoring step")
    doc = json.loads(PRESET_FILE.read_text())
    if doc.get("blocked"): assert doc["presets"] == {} and doc["reason"]; return
    for n, p in doc["presets"].items():
        assert p["bad_vendor_passes"] == 0, n
        for k in ("mean_cv_loss", "holdout_loss", "established_pass_rate", "small_real", "customer_description", "params_changed"): assert k in p, (n, k)
