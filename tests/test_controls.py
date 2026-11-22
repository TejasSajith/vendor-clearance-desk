"""Every control combination keeps the invariants. Cases are read (never edited) from evaluation/."""
import itertools, json, sys, pytest; sys.path.insert(0, ".")
from pathlib import Path
import controls, core, decision, pipeline, policy
from tests.fakes import FakeSources

EVAL = Path("evaluation")
CASES = json.loads((EVAL / "cases_synthetic.json").read_text()) + json.loads((EVAL / "cases_real.json").read_text())
REQUIRED = ["exists", "active", "director_match", "adverse_media"]

# A hostile "approved" candidate: tries to loosen hard rules and push floors to zero.
HOSTILE = {"approved": True,
           "strictness": {"lenient": {"reject_min_sources": 0, "reject_require_dated": False, "deleted_is_fail": True,
                                      "domain_mismatch_is_fail": True, "min_searches": 0, "active_min_signals": 0, "name_sim_min": 0.1},
                          "balanced": {}, "strict": {"active_min_signals": 3, "reject_min_severity": 3}}}

def combos(table):
    return [dict(zip(controls.CONTROLS, c)) for c in itertools.product(*(list(table[k]) for k in controls.CONTROLS))]

def _check_invariants(checks):
    d = decision.decide(checks)
    for name, c in checks.items():
        if c["status"] == "fail": assert c.get("sources"), f"{name}: fail without a source"
    if any(c["status"] == "unreachable" for c in checks.values()): assert d.verdict == decision.HOLD
    if any(checks[c]["status"] in ("unknown", "not_run") for c in REQUIRED): assert d.verdict != decision.CLEARED
    return d

@pytest.mark.parametrize("candidate", [None, "hostile"])
def test_every_combination_keeps_the_invariants(tmp_path, candidate):
    path = tmp_path / "presets_candidate.json"
    if candidate: path.write_text(json.dumps(HOSTILE))
    table, _ = controls.presets(path)
    for choice in combos(table):
        r = controls.resolve(choice, path)
        p = r["params"]
        for k in controls.HARD_KEYS: assert p[k] == policy.PROPOSED_PARAMS[k]
        assert p["reject_min_sources"] >= 1 and p["min_searches"] >= 1
        for case in CASES:
            checks = policy.evaluate(case["signals"], p, case.get("risk_tier", "low"))
            _check_invariants(checks)
            for name in REQUIRED:      # a timed-out source always holds, whatever the controls
                _check_invariants({**checks, name: {"status": "unreachable", "reason": "t", "sources": []}})
                capped = {**checks, name: {"status": "not_run", "reason": "cap", "sources": []}}
                held = any(c["status"] == "unreachable" for c in capped.values())
                assert decision.decide(capped).verdict == (decision.HOLD if held else decision.CANNOT_VERIFY)

def test_approval_is_required_for_clear_and_reject_under_every_combination(tmp_path):
    table, _ = controls.presets(tmp_path / "none.json")
    for i, choice in enumerate(combos(table)):
        db = core.connect(str(tmp_path / f"{i}.db"))
        r = controls.resolve(choice, tmp_path / "none.json")
        res = pipeline.run_request(db, {"vendor_name": "Acme Logistics Pvt Ltd", "website": "acme.in", "claimed_director": "Dir One"},
                                   FakeSources(), params=r["params"])
        assert res["verdict"] == "CLEARED" and res["action_key"]
        assert db.execute("SELECT status FROM actions WHERE key=?", (res["action_key"],)).fetchone()[0] == "pending"

def test_without_approved_file_all_strictness_levels_are_the_policy_defaults(tmp_path):
    path = tmp_path / "presets_candidate.json"
    path.write_text(json.dumps({**HOSTILE, "approved": False}))
    notes = controls.presets(path)[1]
    assert any("not approved" in n for n in notes) and any("same result" in n for n in notes)
    for lvl in ("lenient", "balanced", "strict"):
        assert controls.resolve({"strictness": lvl}, path)["params"] == policy.PROPOSED_PARAMS

def test_approved_file_is_used_and_hard_keys_ignored(tmp_path):
    path = tmp_path / "presets_candidate.json"; path.write_text(json.dumps(HOSTILE))
    r = controls.resolve({"strictness": "lenient"}, path)
    assert r["params"]["active_min_signals"] == 0 and r["params"]["reject_min_sources"] == 1
    assert any("reject_require_dated" in n and "ignored" in n for n in r["notes"])
    assert controls.resolve({"strictness": "strict"}, path)["params"]["active_min_signals"] == 3

def test_freshness_and_rejection_evidence(tmp_path):
    none = tmp_path / "none.json"
    assert controls.resolve({"freshness_days": "180"}, none)["params"]["max_series_age_days"] == 180
    assert controls.resolve({}, none)["params"] == policy.PROPOSED_PARAMS and controls.resolve({}, none)["tag"] == ""
    assert controls.resolve({"rejection_evidence": "high"}, none)["params"]["reject_min_sources"] == 2
    r = controls.resolve({"freshness_days": "7"}, none)
    assert r["controls"]["freshness_days"] == "policy" and any("not an option" in n for n in r["notes"])

def test_other_controls_make_a_separate_run_not_a_duplicate(tmp_path):
    db = core.connect(str(tmp_path / "t.db"))
    req = {"vendor_name": "Acme Logistics Pvt Ltd", "website": "acme.in"}
    a = pipeline.run_request(db, req, FakeSources())
    b = pipeline.run_request(db, req, FakeSources(), params=controls.resolve({"freshness_days": "30"}, tmp_path / "x")["params"])
    c = pipeline.run_request(db, req, FakeSources(), params=policy.PROPOSED_PARAMS)
    assert a["run_id"] != b["run_id"] and c["run_id"] == a["run_id"] and c["existing"]
